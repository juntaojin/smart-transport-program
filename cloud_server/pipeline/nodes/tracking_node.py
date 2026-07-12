from loguru import logger

from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext


class TrackingNode(PipelineNode):
    """Stabilize vehicle tracks across frames using IoU matching.

    model_api.detect_vehicles may return ByteTrack IDs, but those IDs can briefly
    drop or switch when detection jitters. This node maintains per-device stable
    IDs and smoothed boxes for the rest of the pipeline and frontend overlay.
    """

    IOU_THRESHOLD = 0.25
    CENTER_DISTANCE_RATIO = 0.65
    SMOOTHING_ALPHA = 0.70
    MAX_MISSED_FRAMES = 2

    def __init__(self):
        super().__init__(name="tracking")
        self._frame_count = 0
        self._trackers: dict[str, dict] = {}

    def load_model(self):
        logger.info("[Tracking] Stable IoU tracker ready")
        self._frame_count = 0
        self._trackers.clear()

    def unload_model(self):
        logger.info("[Tracking] Node disabled")
        self._trackers.clear()

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])
        confidences = context.properties.get("vehicle_confidences", [])
        raw_track_ids = context.properties.get("vehicle_track_ids", [])

        device_id = context.device_id or "default"
        tracker = self._trackers.setdefault(device_id, {"next_id": 1, "tracks": {}})
        detections = self._build_detections(boxes, classes, confidences, raw_track_ids)
        active_tracks = self._update_tracks(tracker, detections)

        context.properties["vehicle_boxes"] = [track["bbox"] for _, track in active_tracks]
        context.properties["vehicle_classes"] = [track["class"] for _, track in active_tracks]
        context.properties["vehicle_confidences"] = [track["confidence"] for _, track in active_tracks]
        context.properties["track_ids"] = [track_id for track_id, _ in active_tracks]

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[Tracking] Frame #{self._frame_count}: "
                f"detections={len(detections)}, stable_tracks={len(active_tracks)}"
            )

        return context

    def _build_detections(self, boxes, classes, confidences, raw_track_ids):
        detections = []
        for index, box in enumerate(boxes):
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            try:
                bbox = [float(value) for value in box]
            except (TypeError, ValueError):
                continue
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            detections.append({
                "bbox": bbox,
                "class": classes[index] if index < len(classes) else "vehicle",
                "confidence": float(confidences[index]) if index < len(confidences) else 0.0,
                "raw_track_id": raw_track_ids[index] if index < len(raw_track_ids) else None,
            })
        return detections

    def _update_tracks(self, tracker, detections):
        tracks = tracker["tracks"]
        matches, unmatched_detections, unmatched_tracks = self._match(tracks, detections)

        for det_index, track_id in matches:
            detection = detections[det_index]
            track = tracks[track_id]
            track["bbox"] = self._smooth_box(track["bbox"], detection["bbox"])
            track["class"] = detection["class"]
            track["confidence"] = detection["confidence"]
            track["raw_track_id"] = detection["raw_track_id"]
            track["missed"] = 0
            track["hits"] += 1

        for det_index in unmatched_detections:
            detection = detections[det_index]
            track_id = tracker["next_id"]
            tracker["next_id"] += 1
            tracks[track_id] = {
                "bbox": detection["bbox"],
                "class": detection["class"],
                "confidence": detection["confidence"],
                "raw_track_id": detection["raw_track_id"],
                "missed": 0,
                "hits": 1,
            }

        for track_id in unmatched_tracks:
            if track_id in tracks:
                tracks[track_id]["missed"] += 1

        for track_id in list(tracks):
            if tracks[track_id]["missed"] > self.MAX_MISSED_FRAMES:
                del tracks[track_id]

        return [
            (track_id, track)
            for track_id, track in tracks.items()
            if track["missed"] <= self.MAX_MISSED_FRAMES
        ]

    def _match(self, tracks, detections):
        if not tracks or not detections:
            return [], list(range(len(detections))), list(tracks.keys())

        candidates = []
        track_items = list(tracks.items())
        for det_index, detection in enumerate(detections):
            for track_index, (track_id, track) in enumerate(track_items):
                iou = self._box_iou(detection["bbox"], track["bbox"])
                raw_bonus = 0.15 if detection["raw_track_id"] is not None and detection["raw_track_id"] == track.get("raw_track_id") else 0.0
                center_ok = self._center_distance_ok(detection["bbox"], track["bbox"])
                if iou >= self.IOU_THRESHOLD or center_ok:
                    candidates.append((iou + raw_bonus, det_index, track_index))

        candidates.sort(key=lambda item: item[0], reverse=True)
        matches = []
        used_detections = set()
        used_tracks = set()
        for _, det_index, track_index in candidates:
            if det_index in used_detections or track_index in used_tracks:
                continue
            track_id = track_items[track_index][0]
            matches.append((det_index, track_id))
            used_detections.add(det_index)
            used_tracks.add(track_index)

        unmatched_detections = [i for i in range(len(detections)) if i not in used_detections]
        unmatched_tracks = [track_id for i, (track_id, _) in enumerate(track_items) if i not in used_tracks]
        return matches, unmatched_detections, unmatched_tracks

    def _center_distance_ok(self, a, b):
        ax = (a[0] + a[2]) / 2.0
        ay = (a[1] + a[3]) / 2.0
        bx = (b[0] + b[2]) / 2.0
        by = (b[1] + b[3]) / 2.0
        distance = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        max_size = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1], 1.0)
        return distance <= max_size * self.CENTER_DISTANCE_RATIO

    def _smooth_box(self, previous, current):
        alpha = self.SMOOTHING_ALPHA
        return [previous[i] * (1.0 - alpha) + current[i] * alpha for i in range(4)]

    @staticmethod
    def _box_iou(a, b):
        x1 = max(a[0], b[0])
        y1 = max(a[1], b[1])
        x2 = min(a[2], b[2])
        y2 = min(a[3], b[3])
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        return inter / (area_a + area_b - inter + 1e-8)
