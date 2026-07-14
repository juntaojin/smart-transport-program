import os
import threading
import time

import cv2
import numpy as np
from loguru import logger

DEFAULT_BANK_FRAMES = 5
DEFAULT_ALERT_FRAMES = 2
DEFAULT_MAX_AGE = 6
DEFAULT_MIN_AREA = 900
DEFAULT_DIFF_THRESH = 26
DEFAULT_MIN_EXTENT = 0.18
DEFAULT_MIN_BOX_SIZE = 24
DEFAULT_STABILIZATION_ENABLED = True
DEFAULT_MAX_JITTER_PX = 20
DEFAULT_ALERT_SECONDS = 0.8
DEFAULT_MAX_MISSING_SECONDS = 0.5
DEFAULT_STATIC_EDGE_SUPPRESSION_PX = 3
DEFAULT_VEHICLE_MASK_PADDING = 8
IOU_THRESH = 0.3
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
_min_area = DEFAULT_MIN_AREA
_diff_thresh = DEFAULT_DIFF_THRESH
_min_extent = DEFAULT_MIN_EXTENT
_min_box_size = DEFAULT_MIN_BOX_SIZE
_stabilization_enabled = DEFAULT_STABILIZATION_ENABLED
_max_jitter_px = DEFAULT_MAX_JITTER_PX
_alert_seconds = DEFAULT_ALERT_SECONDS
_max_missing_seconds = DEFAULT_MAX_MISSING_SECONDS
_static_edge_suppression_px = DEFAULT_STATIC_EDGE_SUPPRESSION_PX
_vehicle_mask_padding = DEFAULT_VEHICLE_MASK_PADDING
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
    min_area=None,
    diff_thresh=None,
    min_extent=None,
    min_box_size=None,
    stabilization_enabled=None,
    max_jitter_px=None,
    alert_seconds=None,
    max_missing_seconds=None,
    static_edge_suppression_px=None,
    vehicle_mask_padding=None,
):
    """Load the shared normal-object model from an existing local path."""
    global _model, _model_device, _bank_frames, _alert_frames, _max_age
    global _min_area, _diff_thresh, _min_extent, _min_box_size
    global _stabilization_enabled, _max_jitter_px, _alert_seconds
    global _max_missing_seconds, _static_edge_suppression_px, _vehicle_mask_padding
    _bank_frames = max(1, int(bank_frames or DEFAULT_BANK_FRAMES))
    _alert_frames = max(1, int(alert_frames or DEFAULT_ALERT_FRAMES))
    _max_age = max(1, int(max_age or DEFAULT_MAX_AGE))
    _min_area = max(1, int(min_area or DEFAULT_MIN_AREA))
    _diff_thresh = max(1, int(diff_thresh or DEFAULT_DIFF_THRESH))
    _min_extent = max(0.0, min(1.0, float(min_extent or DEFAULT_MIN_EXTENT)))
    _min_box_size = max(1, int(min_box_size or DEFAULT_MIN_BOX_SIZE))
    _stabilization_enabled = (
        DEFAULT_STABILIZATION_ENABLED if stabilization_enabled is None
        else bool(stabilization_enabled)
    )
    _max_jitter_px = max(0.0, float(max_jitter_px or DEFAULT_MAX_JITTER_PX))
    _alert_seconds = max(0.0, float(alert_seconds or DEFAULT_ALERT_SECONDS))
    _max_missing_seconds = max(0.0, float(max_missing_seconds or DEFAULT_MAX_MISSING_SECONDS))
    _static_edge_suppression_px = max(0, int(
        static_edge_suppression_px if static_edge_suppression_px is not None
        else DEFAULT_STATIC_EDGE_SUPPRESSION_PX
    ))
    _vehicle_mask_padding = max(0, int(
        vehicle_mask_padding if vehicle_mask_padding is not None
        else DEFAULT_VEHICLE_MASK_PADDING
    ))
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


def _box_overlap_ratio(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    return inter / (area_a + 1e-8)


def _normalize_external_boxes(boxes):
    normalized = []
    for box in boxes or []:
        if isinstance(box, dict):
            box = box.get("box") or box.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x1, y1, x2, y2 = [float(value) for value in box]
        except (TypeError, ValueError):
            continue
        if x2 > x1 and y2 > y1:
            normalized.append({"bbox": [x1, y1, x2, y2], "label": "normal", "conf": 1.0})
    return normalized


class _FrameStabilizer:
    """Estimate current-frame-to-reference affine motion using sparse LK flow."""

    def __init__(self):
        self.enabled = _stabilization_enabled
        self.max_jitter_px = _max_jitter_px
        self.reference_gray = None
        self.feature_params = dict(maxCorners=200, qualityLevel=0.01, minDistance=7, blockSize=7)
        self.lk_params = dict(
            winSize=(21, 21), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )

    def reset(self, gray):
        self.reference_gray = gray.copy()

    def stabilize(self, gray):
        if not self.enabled:
            if self.reference_gray is None:
                self.reset(gray)
            return gray
        if self.reference_gray is None:
            self.reset(gray)
            return gray
        matrix = self._estimate_current_to_reference(gray)
        if matrix is None:
            return gray
        height, width = gray.shape[:2]
        return cv2.warpAffine(
            gray, matrix, (width, height), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

    def _estimate_current_to_reference(self, gray):
        ref_pts = cv2.goodFeaturesToTrack(self.reference_gray, mask=None, **self.feature_params)
        if ref_pts is None or len(ref_pts) < 8:
            return None
        cur_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            self.reference_gray, gray, ref_pts, None, **self.lk_params
        )
        if cur_pts is None or status is None:
            return None
        status = status.reshape(-1).astype(bool)
        ref_good = ref_pts.reshape(-1, 2)[status]
        cur_good = cur_pts.reshape(-1, 2)[status]
        if len(ref_good) < 8:
            return None
        matrix, inliers = cv2.estimateAffinePartial2D(
            cur_good, ref_good, method=cv2.RANSAC, ransacReprojThreshold=3.0,
            maxIters=2000, confidence=0.99,
        )
        if matrix is None or inliers is None or int(inliers.sum()) < 6:
            return None
        dx, dy = float(matrix[0, 2]), float(matrix[1, 2])
        if np.hypot(dx, dy) > self.max_jitter_px:
            return None
        return matrix.astype(np.float32)


class _ChangeDetector:
    """Stabilized background subtraction with static-edge residual suppression."""

    def __init__(self):
        self.min_area = _min_area
        self.diff_thresh = _diff_thresh
        self.median_bg = None
        self.running_bg = None
        self.alpha = 0.01
        self.open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self.bank_frames = _bank_frames
        self.min_extent = _min_extent
        self.min_box_size = _min_box_size
        self.static_edge_suppression_px = _static_edge_suppression_px
        self.edge_k = None
        if self.static_edge_suppression_px > 0:
            size = self.static_edge_suppression_px * 2 + 1
            self.edge_k = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
        self.stabilizer = _FrameStabilizer()
        self._warmup_buffer = []
        self._warmed = False

        self.dirty_bg_mask = None
        self._dirty_absence_count = None

    def warmup_feed(self, frame, normal_dets=None):
        if self._warmed:
            return True
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        stabilized = self.stabilizer.stabilize(gray)
        self._warmup_buffer.append(stabilized.copy())

        if normal_dets:
            if self.dirty_bg_mask is None:
                self.dirty_bg_mask = np.zeros(gray.shape, dtype=np.uint8)
            for det in normal_dets:
                if det["label"] in ["car", "bus", "truck", "motorcycle"]:
                    x1, y1, x2, y2 = map(int, det["bbox"])
                    pad = _vehicle_mask_padding
                    cv2.rectangle(self.dirty_bg_mask,
                                  (max(0, x1 - pad), max(0, y1 - pad)),
                                  (min(gray.shape[1], x2 + pad), min(gray.shape[0], y2 + pad)),
                                  255, -1)

        if len(self._warmup_buffer) >= self.bank_frames:
            stack = np.stack(self._warmup_buffer, axis=0)
            self.median_bg = np.median(stack, axis=0).astype(np.uint8)
            self.running_bg = self.median_bg.astype(np.float32)
            self.stabilizer.reference_gray = self.median_bg.copy()
            self._warmup_buffer.clear()
            self._warmed = True
        return self._warmed

    def detect(self, frame, normal_dets=None):
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        stabilized = self.stabilizer.stabilize(gray)

        if self.dirty_bg_mask is not None and np.any(self.dirty_bg_mask):
            current_vehicle_mask = np.zeros_like(self.dirty_bg_mask)
            if normal_dets:
                for det in normal_dets:
                    if det["label"] in ["car", "bus", "truck", "motorcycle"]:
                        x1, y1, x2, y2 = map(int, det["bbox"])
                        cv2.rectangle(current_vehicle_mask, (x1, y1), (x2, y2), 255, -1)

            safe_current = cv2.dilate(current_vehicle_mask, np.ones((25, 25), np.uint8))

            occupied_zone = cv2.bitwise_and(self.dirty_bg_mask, safe_current)

            if self._dirty_absence_count is None:
                self._dirty_absence_count = np.zeros_like(self.dirty_bg_mask, dtype=np.int32)

            self._dirty_absence_count = np.where(
                self.dirty_bg_mask > 0,
                np.where(occupied_zone > 0, 0, self._dirty_absence_count + 1),
                0,
            )

            patch_mask = (self._dirty_absence_count >= 30).astype(np.uint8)
            patch_mask = cv2.bitwise_and(self.dirty_bg_mask, patch_mask)

            if np.any(patch_mask):
                self.median_bg[patch_mask > 0] = stabilized[patch_mask > 0]
                self.running_bg[patch_mask > 0] = stabilized[patch_mask > 0].astype(np.float32)
                self.dirty_bg_mask[patch_mask > 0] = 0
                self._dirty_absence_count[patch_mask > 0] = 0

        diff_median = cv2.absdiff(stabilized, self.median_bg)
        diff_running = cv2.absdiff(stabilized, self.running_bg.astype(np.uint8))
        diff = cv2.min(diff_median, diff_running)
        fg = (diff > self.diff_thresh).astype(np.uint8)
        fg = self._suppress_static_edges(fg, stabilized)
        if self.dirty_bg_mask is not None:
            fg[self.dirty_bg_mask > 0] = 0
        update_mask = fg == 0
        self.running_bg[update_mask] = (
            (1.0 - self.alpha) * self.running_bg[update_mask]
            + self.alpha * stabilized[update_mask]
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
            if w < self.min_box_size or h < self.min_box_size:
                continue
            extent = area / max(w * h, 1)
            if extent < self.min_extent:
                continue
            if (x < EDGE_MARGIN or y < EDGE_MARGIN
                    or x + w > width - EDGE_MARGIN or y + h > height - EDGE_MARGIN):
                continue
            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 8:
                continue
            blobs.append({
                "bbox": [x, y, x + w, y + h],
                "centroid": [centroids[i][0], centroids[i][1]],
                "area": int(area),
            })
        return blobs

    def _suppress_static_edges(self, fg, stabilized_gray):
        if self.edge_k is None:
            return fg
        bg_edges = cv2.Canny(self.median_bg, 50, 150)
        frame_edges = cv2.Canny(stabilized_gray, 50, 150)
        edge_mask = cv2.dilate(cv2.max(bg_edges, frame_edges), self.edge_k) > 0
        suppressed = fg.copy()
        suppressed[edge_mask] = 0
        return suppressed

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
        self.alert_seconds = _alert_seconds
        self.max_missing_seconds = _max_missing_seconds
        self.vehicle_mask_padding = _vehicle_mask_padding
        self.iou_thresh = IOU_THRESH
        self.tracks = {}
        self.next_id = 0
        self.frame_count = 0

    def update(self, fg_blobs, normal_dets, timestamp=None):
        now = float(time.monotonic() if timestamp is None else timestamp)
        self.frame_count += 1
        unknown_blobs = self._exclude_normal(fg_blobs, normal_dets)
        matches, unmatched_dets, unmatched_trks = self._associate(unknown_blobs)
        for det_idx, trk_id in matches:
            detection = unknown_blobs[det_idx]
            track = self.tracks[trk_id]
            track.update({
                "bbox": detection["bbox"], "centroid": detection["centroid"],
                "area": detection["area"], "time_since_update": 0,
                "last_seen": now,
            })
            track["age"] += 1
        for det_idx in unmatched_dets:
            detection = unknown_blobs[det_idx]
            self.tracks[self.next_id] = {
                "track_id": self.next_id, "bbox": detection["bbox"],
                "centroid": detection["centroid"], "area": detection["area"],
                "age": 1, "time_since_update": 0, "alerted": False,
                "first_seen": now, "last_seen": now,
            }
            self.next_id += 1
        for trk_id in unmatched_trks:
            self.tracks[trk_id]["time_since_update"] += 1
            self.tracks[trk_id]["age"] += 1
        alerts = []
        for trk_id in list(self.tracks):
            track = self.tracks[trk_id]
            missing_seconds = now - track.get("last_seen", now)
            if (track["time_since_update"] > self.max_age
                    or missing_seconds > self.max_missing_seconds):
                del self.tracks[trk_id]
            elif (not track["alerted"]
                  and track["time_since_update"] == 0
                  and track["age"] >= self.alert_frames
                  and now - track.get("first_seen", now) >= self.alert_seconds):
                track["alerted"] = True
                alerts.append(track)
        active = [track for track in self.tracks.values()
                  if track["time_since_update"] <= self.max_age]
        return active, alerts

    def _exclude_normal(self, fg_blobs, normal_dets):
        if not normal_dets:
            return fg_blobs
        padded = []
        for detection in normal_dets:
            box = detection["bbox"]
            padded.append([
                box[0] - self.vehicle_mask_padding,
                box[1] - self.vehicle_mask_padding,
                box[2] + self.vehicle_mask_padding,
                box[3] + self.vehicle_mask_padding,
            ])
        return [blob for blob in fg_blobs if not any(
            _box_iou(blob["bbox"], box) > 0.1
            or _box_overlap_ratio(blob["bbox"], box) > 0.35
            or (box[0] <= blob["centroid"][0] <= box[2]
                and box[1] <= blob["centroid"][1] <= box[3])
            for box in padded
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


def detect_anomalies(frame, device_id="default", timestamp=None, normal_boxes=None):
    """Detect persistent road anomalies using state isolated by device ID."""
    if not _valid_frame(frame):
        logger.warning("[AnomalyDetection] Ignoring invalid frame; expected non-empty uint8 BGR image")
        return []
    try:
        state = _get_device_state(device_id, frame.shape[:2])
        with state.lock:
            external_normal = _normalize_external_boxes(normal_boxes)
            normal_dets = external_normal or state.normal_detector.detect(frame)

            if not state.change_detector.is_ready:
                state.change_detector.warmup_feed(frame, normal_dets)
                return [], normal_dets

            fg_blobs = state.change_detector.detect(frame, normal_dets)
            if not fg_blobs:
                active_tracks, _ = state.anomaly_tracker.update([], [], timestamp=timestamp)
            else:
                active_tracks, _ = state.anomaly_tracker.update(
                    fg_blobs, normal_dets, timestamp=timestamp
                )

            active_alerts = [track for track in active_tracks if track.get("alerted")]
            return [{
                "box": [float(value) for value in alert["bbox"]],
                "confidence": round(min(
                    1.0,
                    max(
                        alert["age"] / state.anomaly_tracker.alert_frames,
                        (float(time.monotonic() if timestamp is None else timestamp)
                         - alert.get("first_seen", 0.0))
                        / max(state.anomaly_tracker.alert_seconds, 1e-6),
                    ),
                ), 4),
                "label": "road_anomaly",
            } for alert in active_alerts], normal_dets
    except Exception as e:
        logger.exception(
            f"[AnomalyDetection] Detection failed for device {device_id!r}: {e}"
        )
        return [], []
