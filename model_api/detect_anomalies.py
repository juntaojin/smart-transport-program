import os
import threading

import cv2
import numpy as np
from loguru import logger

DEFAULT_BANK_FRAMES = 5
DEFAULT_ALERT_FRAMES = 3
DEFAULT_MAX_AGE = 6
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

_model = None
_model_device = "auto"
_bank_frames = DEFAULT_BANK_FRAMES
_alert_frames = DEFAULT_ALERT_FRAMES
_max_age = DEFAULT_MAX_AGE
_model_lock = threading.RLock()
_registry_lock = threading.RLock()
_device_states = {}


class _DeviceState:
    def __init__(self, frame_shape):
        self.frame_shape = frame_shape
        self.change_detector = _ChangeDetector()
        self.anomaly_tracker = _AnomalyTracker()
        self.normal_detector = _NormalDetector()
        self.lock = threading.RLock()


def _default_model_path():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "yolo26s.pt")


def load_anomaly_model(
    model_path=None,
    device="auto",
    bank_frames=None,
    alert_frames=None,
    max_age=None,
):
    """Load the shared normal-object model from an existing local path."""
    global _model, _model_device, _bank_frames, _alert_frames, _max_age
    _bank_frames = max(1, int(bank_frames or DEFAULT_BANK_FRAMES))
    _alert_frames = max(1, int(alert_frames or DEFAULT_ALERT_FRAMES))
    _max_age = max(1, int(max_age or DEFAULT_MAX_AGE))
    path = os.path.abspath(os.path.expanduser(model_path or _default_model_path()))
    if not os.path.isfile(path):
        logger.error(f"[AnomalyDetection] Model file does not exist: {path}")
        return False

    with _model_lock:
        if _model is not None:
            return True
        try:
            from ultralytics import YOLO
            _model = YOLO(path)
            _model_device = device or "auto"
            logger.info(
                f"[AnomalyDetection] Loaded normal-object model from {path} "
                f"(device={_model_device})"
            )
            return True
        except Exception as e:
            _model = None
            logger.exception(f"[AnomalyDetection] Failed to load model: {e}")
            return False


def unload_anomaly_model():
    """Release the shared model and all per-device detector state."""
    global _model, _model_device
    reset_anomaly_state()
    with _model_lock:
        _model = None
        _model_device = "auto"
    logger.info("[AnomalyDetection] Model unloaded")


def reset_anomaly_state(device_id=None):
    """Reset one device, or every device when device_id is omitted."""
    with _registry_lock:
        if device_id is None:
            _device_states.clear()
        else:
            _device_states.pop(str(device_id), None)


def _get_model():
    with _model_lock:
        if _model is None and not load_anomaly_model():
            return None
        return _model


def _get_device_state(device_id, frame_shape):
    key = str(device_id)
    with _registry_lock:
        state = _device_states.get(key)
        if state is None or state.frame_shape != frame_shape:
            if state is not None:
                logger.info(
                    f"[AnomalyDetection] Resetting device {key!r} after frame "
                    f"resolution changed from {state.frame_shape} to {frame_shape}"
                )
            state = _DeviceState(frame_shape)
            _device_states[key] = state
        return state


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
    """双路背景模型: 中值背景 + 运行平均背景, 合并差分提取前景"""

    def __init__(self):
        self.min_area = MIN_AREA
        self.diff_thresh = DIFF_THRESH
        self.median_bg = None
        self.running_bg = None
        self.alpha = 0.01
        self.open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self.bank_frames = _bank_frames
        self._warmup_buffer = []
        self._warmed = False

    def warmup_feed(self, frame):
        if self._warmed:
            return True
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._warmup_buffer.append(gray.copy())
        if len(self._warmup_buffer) >= self.bank_frames:
            stack = np.stack(self._warmup_buffer, axis=0)
            self.median_bg = np.median(stack, axis=0).astype(np.uint8)
            self.running_bg = self.median_bg.astype(np.float32)
            self._warmup_buffer.clear()
            self._warmed = True
        return self._warmed

    def detect(self, frame):
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff_median = cv2.absdiff(gray, self.median_bg)
        diff_running = cv2.absdiff(gray, self.running_bg.astype(np.uint8))
        diff = cv2.max(diff_median, diff_running)
        fg = (diff > self.diff_thresh).astype(np.uint8)
        update_mask = fg == 0
        self.running_bg[update_mask] = (
            (1.0 - self.alpha) * self.running_bg[update_mask]
            + self.alpha * gray[update_mask]
        )
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self.open_k)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self.close_k)
        n, _, stats, centroids = cv2.connectedComponentsWithStats(fg, 8)
        blobs = []
        max_area = height * width * 0.35
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < self.min_area or area > max_area:
                continue
            if (x < EDGE_MARGIN or y < EDGE_MARGIN
                    or x + w > width - EDGE_MARGIN or y + h > height - EDGE_MARGIN):
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
        model = _get_model()
        if model is None:
            return []
        kwargs = {"verbose": False, "conf": NORMAL_CONF, "imgsz": 640}
        if _model_device != "auto":
            kwargs["device"] = _model_device
        with _model_lock:
            results = model(frame, **kwargs)
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
        self.alert_frames = _alert_frames
        self.max_age = _max_age
        self.iou_thresh = IOU_THRESH
        self.tracks = {}
        self.next_id = 0
        self.frame_count = 0

    def update(self, fg_blobs, normal_dets):
        self.frame_count += 1
        unknown_blobs = self._exclude_normal(fg_blobs, normal_dets)
        matches, unmatched_dets, unmatched_trks = self._associate(unknown_blobs)
        for det_idx, trk_id in matches:
            detection = unknown_blobs[det_idx]
            track = self.tracks[trk_id]
            track.update({
                "bbox": detection["bbox"], "centroid": detection["centroid"],
                "area": detection["area"], "time_since_update": 0,
            })
            track["age"] += 1
        for det_idx in unmatched_dets:
            detection = unknown_blobs[det_idx]
            self.tracks[self.next_id] = {
                "track_id": self.next_id, "bbox": detection["bbox"],
                "centroid": detection["centroid"], "area": detection["area"],
                "age": 1, "time_since_update": 0, "alerted": False,
            }
            self.next_id += 1
        for trk_id in unmatched_trks:
            self.tracks[trk_id]["time_since_update"] += 1
            self.tracks[trk_id]["age"] += 1
        alerts = []
        for trk_id in list(self.tracks):
            track = self.tracks[trk_id]
            if track["time_since_update"] > self.max_age:
                del self.tracks[trk_id]
            elif (not track["alerted"] and track["age"] >= self.alert_frames
                  and track["time_since_update"] == 0):
                track["alerted"] = True
                alerts.append(track)
        active = [track for track in self.tracks.values()
                  if track["time_since_update"] <= self.max_age]
        return active, alerts

    def _exclude_normal(self, fg_blobs, normal_dets):
        if not normal_dets:
            return fg_blobs
        return [blob for blob in fg_blobs if not any(
            _box_iou(blob["bbox"], detection["bbox"]) > 0.1
            for detection in normal_dets
        )]

    def _associate(self, blobs):
        active = [track for track in self.tracks.values()
                  if track["time_since_update"] <= self.max_age]
        if not active or not blobs:
            return ([], list(range(len(blobs))), []) if blobs else (
                [], [], [track["track_id"] for track in active]
            )
        iou_flat = [
            (_box_iou(blob["bbox"], track["bbox"]), di, ti)
            for di, blob in enumerate(blobs) for ti, track in enumerate(active)
        ]
        iou_flat.sort(key=lambda item: item[0], reverse=True)
        matches = []
        used_det, used_trk = set(), set()
        for iou_val, di, ti in iou_flat:
            if iou_val < self.iou_thresh:
                break
            if di not in used_det and ti not in used_trk:
                matches.append((di, active[ti]["track_id"]))
                used_det.add(di)
                used_trk.add(ti)
        unmatched_dets = [i for i in range(len(blobs)) if i not in used_det]
        unmatched_trks = [active[i]["track_id"] for i in range(len(active))
                          if i not in used_trk]
        return matches, unmatched_dets, unmatched_trks


def _valid_frame(frame):
    return (isinstance(frame, np.ndarray) and frame.ndim == 3
            and frame.shape[0] > 0 and frame.shape[1] > 0
            and frame.shape[2] == 3 and frame.dtype == np.uint8)


def detect_anomalies(frame, device_id="default"):
    """Detect newly persistent road anomalies using state isolated by device ID."""
    if not _valid_frame(frame):
        logger.warning("[AnomalyDetection] Ignoring invalid frame; expected non-empty uint8 BGR image")
        return []
    try:
        state = _get_device_state(device_id, frame.shape[:2])
        with state.lock:
            if not state.change_detector.is_ready:
                state.change_detector.warmup_feed(frame)
                return []
            fg_blobs = state.change_detector.detect(frame)
            if not fg_blobs:
                state.anomaly_tracker.update([], [])
                return []
            normal_dets = state.normal_detector.detect(frame)
            _, alerts = state.anomaly_tracker.update(fg_blobs, normal_dets)
            return [{
                "box": [float(value) for value in alert["bbox"]],
                "confidence": round(min(1.0, alert["age"] / state.anomaly_tracker.alert_frames), 4),
                "label": "road_anomaly",
            } for alert in alerts]
    except Exception as e:
        logger.exception(
            f"[AnomalyDetection] Detection failed for device {device_id!r}: {e}"
        )
        return []
