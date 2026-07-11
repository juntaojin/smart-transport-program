import os
import threading
import cv2
import numpy as np
import torch
from ultralytics import YOLO

BANK_FRAMES = 30
ALERT_FRAMES = 30
MAX_AGE = 15
MIN_AREA = 300
IOU_THRESH = 0.3
EDGE_MARGIN = 4
NORMAL_CONF = 0.15
STATIONARY_MAX_AGE = 375

NORMAL_CLASSES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
    5: "bus", 6: "train", 7: "truck",
    9: "traffic light", 10: "fire hydrant", 11: "stop sign",
    12: "parking meter", 13: "bench",
}

_yolo_model = None
_state = threading.local()


def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        root_dir = os.path.dirname(os.path.dirname(__file__))
        model_path = os.path.join(root_dir, "models", "yolo26s.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), "weights", "yolo26s.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), "yolo26s.pt")
        if not os.path.exists(model_path):
            model_path = "yolo26s.pt"
        _yolo_model = YOLO(model_path)
    return _yolo_model


def _get_change_detector():
    if not hasattr(_state, 'cd'):
        _state.cd = _ChangeDetector()
    return _state.cd


def _get_anomaly_tracker():
    if not hasattr(_state, 'at'):
        _state.at = _AnomalyTracker()
    return _state.at


def _get_normal_detector():
    if not hasattr(_state, 'nd'):
        _state.nd = _NormalDetector()
    return _state.nd


def _box_iou(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-8)


def _box_ioa(blob_box, yolo_box):
    x1 = max(blob_box[0], yolo_box[0])
    y1 = max(blob_box[1], yolo_box[1])
    x2 = min(blob_box[2], yolo_box[2])
    y2 = min(blob_box[3], yolo_box[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    blob_area = max(0, blob_box[2] - blob_box[0]) * max(0, blob_box[3] - blob_box[1])
    return inter / (blob_area + 1e-8)


class _ChangeDetector:
    """GPU-accelerated background subtraction + foreground blob detector.

    Uses PyTorch CUDA for BGR→Gray, absdiff, threshold, and running-background
    update.  Only morphology and connected-components stay on CPU (no GPU
    equivalent in OpenCV's Python bindings).
    """

    _GRAY_WEIGHTS = torch.tensor([0.1140, 0.5870, 0.2989], dtype=torch.float32)

    def __init__(self):
        self.min_area = MIN_AREA
        self.diff_thresh = 16
        self.median_bg = None       # GPU float32 tensor (H, W)
        self.running_bg = None      # GPU float32 tensor (H, W)
        self.alpha = 0.01
        self.open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self._warmup_buffer = []
        self._warmed = False
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'

    def _bgr_to_gray_gpu(self, frame_cpu: np.ndarray) -> torch.Tensor:
        """Convert BGR numpy frame (H, W, 3) to gray GPU float32 tensor (H, W)."""
        t = torch.from_numpy(frame_cpu).to(self._device, dtype=torch.float32)
        return t @ self._GRAY_WEIGHTS.to(self._device)

    def warmup_feed(self, frame):
        if self._warmed:
            return True
        gray_cpu = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        self._warmup_buffer.append(gray_cpu)
        if len(self._warmup_buffer) >= BANK_FRAMES:
            stack = np.stack(self._warmup_buffer, axis=0)
            median_cpu = np.median(stack, axis=0).astype(np.float32)
            self.median_bg = torch.from_numpy(median_cpu).to(self._device)
            self.running_bg = self.median_bg.clone()
            self._warmup_buffer.clear()
            self._warmed = True
        return self._warmed

    def detect(self, frame):
        H, W = frame.shape[:2]

        # 1. GPU: BGR → gray + absdiff + threshold + running-background update
        gray = self._bgr_to_gray_gpu(frame)

        diff_median = torch.abs(gray - self.median_bg)
        diff_running = torch.abs(gray - self.running_bg)
        diff = torch.maximum(diff_median, diff_running)

        fg_gpu = (diff > self.diff_thresh).to(torch.uint8)

        # Update running background where NO motion is detected
        not_fg = torch.logical_not(fg_gpu.bool())
        self.running_bg[not_fg] = (
            (1.0 - self.alpha) * self.running_bg[not_fg]
            + self.alpha * gray[not_fg]
        )

        # 2. CPU: morphology + connected-components
        fg_cpu = fg_gpu.cpu().numpy()
        fg_cpu = cv2.morphologyEx(fg_cpu, cv2.MORPH_OPEN, self.open_k)
        fg_cpu = cv2.morphologyEx(fg_cpu, cv2.MORPH_CLOSE, self.close_k)

        n, labels, stats, centroids = cv2.connectedComponentsWithStats(fg_cpu, 8)
        blobs = []
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
        self.stale_regions = []
        self._stale_max = 20

    def update(self, fg_blobs, normal_dets):
        self.frame_count += 1

        unknown_blobs = self._exclude_normal(fg_blobs, normal_dets)
        matches, unmatched_dets, unmatched_trks = self._associate(unknown_blobs)

        for det_idx, trk_id in matches:
            d = unknown_blobs[det_idx]
            trk = self.tracks[trk_id]
            old_centroid = trk["centroid"]
            trk["bbox"] = d["bbox"]
            trk["centroid"] = d["centroid"]
            trk["area"] = d["area"]
            trk["age"] += 1
            trk["time_since_update"] = 0
            dist = ((d["centroid"][0] - old_centroid[0]) ** 2
                    + (d["centroid"][1] - old_centroid[1]) ** 2) ** 0.5
            if dist > 10:
                trk["last_move_frame"] = self.frame_count

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
                "last_move_frame": self.frame_count,
            }
            self.next_id += 1

        for trk_id in unmatched_trks:
            self.tracks[trk_id]["time_since_update"] += 1
            self.tracks[trk_id]["age"] += 1

        alerts = []
        stale_bboxes = []
        for trk_id in list(self.tracks):
            trk = self.tracks[trk_id]
            if trk["time_since_update"] > self.max_age:
                del self.tracks[trk_id]
                continue
            if (trk["time_since_update"] == 0
                    and self.frame_count - trk["last_move_frame"] > STATIONARY_MAX_AGE):
                stale_bboxes.append(trk["bbox"])
                del self.tracks[trk_id]
                continue
            if (not trk["alerted"]
                    and trk["age"] >= self.alert_frames
                    and trk["time_since_update"] == 0):
                trk["alerted"] = True
                alerts.append(trk)

        self.stale_regions.extend(stale_bboxes)
        if len(self.stale_regions) > self._stale_max:
            self.stale_regions = self.stale_regions[-self._stale_max:]

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
                if _box_ioa([bx1, by1, bx2, by2], [nx1, ny1, nx2, ny2]) > 0.5:
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
    try:
        cd = _get_change_detector()
        at = _get_anomaly_tracker()
        nd = _get_normal_detector()

        if not cd.is_ready:
            cd.warmup_feed(frame)
            return []

        fg_blobs = cd.detect(frame)

        if at.stale_regions:
            fg_blobs = [b for b in fg_blobs if not any(
                _box_iou(b["bbox"], sb) > 0.3 for sb in at.stale_regions
            )]

        if len(fg_blobs) == 0:
            at.update([], [])
            return []

        normal_dets = nd.detect(frame)
        active_tracks, alerts = at.update(fg_blobs, normal_dets)

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
