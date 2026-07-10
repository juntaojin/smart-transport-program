import os
import cv2
import numpy as np
import torch
from ultralytics import YOLO

BANK_FRAMES = 30
ALERT_FRAMES = 30
MAX_AGE = 15
MIN_AREA = 300
IOU_THRESH = 0.3
DIFF_THRESH = 25
EDGE_MARGIN = 4
NORMAL_CONF = 0.15

NORMAL_CLASSES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
    5: "bus", 6: "train", 7: "truck",
    9: "traffic light", 10: "fire hydrant", 11: "stop sign",
    12: "parking meter", 13: "bench",
}

_yolo_model = None
_change_detector = None
_anomaly_tracker = None


def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        root_dir = os.path.dirname(os.path.dirname(__file__))
        model_path = os.path.join(root_dir, "models", "yolo26n.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), "weights", "yolo26n.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), "yolo26n.pt")
        if not os.path.exists(model_path):
            model_path = "yolo26n.pt"
        _yolo_model = YOLO(model_path)
    return _yolo_model


def _box_iou(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-8)


class _ChangeDetector:
    """GPU-accelerated background subtraction + foreground blob detector."""

    # BGR → Gray weights (same as OpenCV)
    _GRAY_WEIGHTS = torch.tensor([0.1140, 0.5870, 0.2989], dtype=torch.float32)

    def __init__(self):
        self.min_area = MIN_AREA
        self.diff_thresh = DIFF_THRESH
        self.median_bg = None       # GPU float32 tensor
        self.running_bg = None      # GPU float32 tensor
        self.alpha = 0.01
        self.open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self._warmup_buffer = []
        self._warmed = False
        self._frame_h = 0
        self._frame_w = 0
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'

    def _bgr_to_gray(self, frame_cpu: np.ndarray) -> torch.Tensor:
        """Convert BGR numpy frame to gray GPU tensor."""
        t = torch.from_numpy(frame_cpu).to(self._device, dtype=torch.float32)
        # BGR matmul -> gray: (H, W, 3) @ (3,) -> (H, W)
        gray = t @ self._GRAY_WEIGHTS.to(self._device)
        return gray

    def warmup_feed(self, frame):
        if self._warmed:
            return True
        gray_cpu = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        self._warmup_buffer.append(gray_cpu)
        self._frame_h, self._frame_w = gray_cpu.shape
        if len(self._warmup_buffer) >= BANK_FRAMES:
            stack = np.stack(self._warmup_buffer, axis=0)
            median_cpu = np.median(stack, axis=0).astype(np.float32)
            self.median_bg = torch.from_numpy(median_cpu).to(self._device)
            self.running_bg = self.median_bg.clone()
            self._warmup_buffer.clear()
            self._warmed = True
        return self._warmed

    def detect(self, frame):
        # Convert frame to GPU gray
        gray = self._bgr_to_gray(frame)

        # Absdiff + max on GPU
        diff_median = torch.abs(gray - self.median_bg)
        diff_running = torch.abs(gray - self.running_bg)
        diff = torch.maximum(diff_median, diff_running)

        # Threshold
        fg = (diff > self.diff_thresh).to(torch.uint8)

        # Update running background (pixels where no motion)
        not_fg = torch.logical_not(fg.bool())
        self.running_bg[not_fg] = (
            (1.0 - self.alpha) * self.running_bg[not_fg]
            + self.alpha * gray[not_fg]
        )

        # Move to CPU for morphology + connected components
        fg_cpu = fg.cpu().numpy()

        fg_cpu = cv2.morphologyEx(fg_cpu, cv2.MORPH_OPEN, self.open_k)
        fg_cpu = cv2.morphologyEx(fg_cpu, cv2.MORPH_CLOSE, self.close_k)

        n, labels, stats, centroids = cv2.connectedComponentsWithStats(fg_cpu, 8)
        blobs = []
        H, W = fg_cpu.shape
        max_area = H * W * 0.35
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < self.min_area:
                continue
            if area > max_area:
                continue
            if (x < EDGE_MARGIN or y < EDGE_MARGIN
                    or x + w > W - EDGE_MARGIN or y + h > H - EDGE_MARGIN):
                continue
            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 15:
                continue
            blobs.append({
                "bbox": [x, y, x + w, y + h],
                "centroid": [centroids[i][0], centroids[i][1]],
                "area": int(area),
            })
        return blobs

    @property
    def is_ready(self):
        return self._warmed


class _NormalDetector:
    def detect(self, frame):
        model = _get_yolo()
        results = model(frame, verbose=False, conf=NORMAL_CONF, imgsz=640)
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []
        dets = []
        for box in boxes:
            cls_id = int(box.cls[0])
            if cls_id in NORMAL_CLASSES:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                dets.append({
                    "bbox": [x1, y1, x2, y2],
                    "cls": cls_id,
                    "label": NORMAL_CLASSES[cls_id],
                    "conf": float(box.conf[0]),
                })
        return dets


class _AnomalyTracker:
    def __init__(self):
        self.alert_frames = ALERT_FRAMES
        self.max_age = MAX_AGE
        self.iou_thresh = IOU_THRESH
        self.tracks = {}
        self.next_id = 0
        self.frame_count = 0

    def update(self, fg_blobs, normal_dets):
        self.frame_count += 1

        unknown_blobs = self._exclude_normal(fg_blobs, normal_dets)
        matches, unmatched_dets, unmatched_trks = self._associate(unknown_blobs)

        for det_idx, trk_id in matches:
            d = unknown_blobs[det_idx]
            trk = self.tracks[trk_id]
            trk["bbox"] = d["bbox"]
            trk["centroid"] = d["centroid"]
            trk["area"] = d["area"]
            trk["age"] += 1
            trk["time_since_update"] = 0

        for det_idx in unmatched_dets:
            d = unknown_blobs[det_idx]
            self.tracks[self.next_id] = {
                "track_id": self.next_id,
                "bbox": d["bbox"],
                "centroid": d["centroid"],
                "area": d["area"],
                "age": 1,
                "time_since_update": 0,
                "alerted": False,
            }
            self.next_id += 1

        for trk_id in unmatched_trks:
            self.tracks[trk_id]["time_since_update"] += 1
            self.tracks[trk_id]["age"] += 1

        alerts = []
        for trk_id in list(self.tracks):
            trk = self.tracks[trk_id]
            if trk["time_since_update"] > self.max_age:
                del self.tracks[trk_id]
                continue
            if (not trk["alerted"]
                    and trk["age"] >= self.alert_frames
                    and trk["time_since_update"] == 0):
                trk["alerted"] = True
                alerts.append(trk)

        active = [t for t in self.tracks.values()
                  if t["time_since_update"] <= self.max_age]

        return active, alerts

    def _exclude_normal(self, fg_blobs, normal_dets):
        if not normal_dets:
            return fg_blobs
        unknown = []
        for blob in fg_blobs:
            bx1, by1, bx2, by2 = blob["bbox"]
            excluded = False
            for nd in normal_dets:
                nx1, ny1, nx2, ny2 = nd["bbox"]
                if _box_iou([bx1, by1, bx2, by2], [nx1, ny1, nx2, ny2]) > 0.1:
                    excluded = True
                    break
            if not excluded:
                unknown.append(blob)
        return unknown

    def _associate(self, blobs):
        active = [t for t in self.tracks.values()
                  if t["time_since_update"] <= self.max_age]
        if not active or not blobs:
            if blobs:
                return [], list(range(len(blobs))), []
            return [], [], [t["track_id"] for t in active]

        n_det, n_trk = len(blobs), len(active)
        iou_flat = []
        for di in range(n_det):
            for ti in range(n_trk):
                iou_val = _box_iou(blobs[di]["bbox"], active[ti]["bbox"])
                iou_flat.append((iou_val, di, ti))
        iou_flat.sort(key=lambda x: x[0], reverse=True)

        matches = []
        used_det, used_trk = set(), set()
        for iou_val, di, ti in iou_flat:
            if iou_val < self.iou_thresh:
                break
            if di not in used_det and ti not in used_trk:
                matches.append((di, active[ti]["track_id"]))
                used_det.add(di)
                used_trk.add(ti)

        unmatched_dets = [i for i in range(n_det) if i not in used_det]
        unmatched_trks = [active[i]["track_id"] for i in range(n_trk)
                          if i not in used_trk]
        return matches, unmatched_dets, unmatched_trks


def detect_anomalies(frame):
    global _change_detector, _anomaly_tracker

    try:
        if _change_detector is None:
            _change_detector = _ChangeDetector()
            _anomaly_tracker = _AnomalyTracker()

        if not _change_detector.is_ready:
            _change_detector.warmup_feed(frame)
            return []

        yolo = _get_yolo()
        normal_detector = _NormalDetector()

        fg_blobs = _change_detector.detect(frame)
        normal_dets = normal_detector.detect(frame)
        active_tracks, alerts = _anomaly_tracker.update(fg_blobs, normal_dets)

        results = []
        for alert in alerts:
            x1, y1, x2, y2 = alert["bbox"]
            confidence = min(1.0, alert["age"] / ALERT_FRAMES)
            results.append({
                "box": [float(x1), float(y1), float(x2), float(y2)],
                "confidence": round(confidence, 4),
                "label": "road_anomaly",
            })
        return results
    except Exception:
        return []
