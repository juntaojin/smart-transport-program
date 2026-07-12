from loguru import logger

from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext


class TrackingNode(PipelineNode):
    """Pass through YOLO/ByteTrack IDs produced by model_api.detect_vehicles.

    The standalone reference script uses Ultralytics YOLO ``model.track`` with
    ``tracker="bytetrack.yaml"`` and renders ``result.boxes.id`` directly.  To
    keep the system behavior consistent with that tested path, this node no
    longer reassigns IDs with a second IoU tracker when ByteTrack IDs are
    available.
    """

    def __init__(self):
        super().__init__(name="tracking")
        self._frame_count = 0

    def load_model(self):
        logger.info("[Tracking] ByteTrack pass-through ready")
        self._frame_count = 0

    def unload_model(self):
        logger.info("[Tracking] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])
        confidences = context.properties.get("vehicle_confidences", [])
        raw_track_ids = context.properties.get("vehicle_track_ids", [])

        filtered_boxes = []
        filtered_classes = []
        filtered_confidences = []
        track_ids = []

        for index, box in enumerate(boxes):
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            raw_id = raw_track_ids[index] if index < len(raw_track_ids) else None
            if raw_id is None:
                continue
            try:
                track_id = int(raw_id)
                bbox = [float(value) for value in box]
            except (TypeError, ValueError):
                continue
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue

            filtered_boxes.append(bbox)
            filtered_classes.append(classes[index] if index < len(classes) else "vehicle")
            filtered_confidences.append(float(confidences[index]) if index < len(confidences) else 0.0)
            track_ids.append(track_id)

        context.properties["vehicle_boxes"] = filtered_boxes
        context.properties["vehicle_classes"] = filtered_classes
        context.properties["vehicle_confidences"] = filtered_confidences
        context.properties["track_ids"] = track_ids

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[Tracking] Frame #{self._frame_count}: "
                f"bytetrack_tracks={len(track_ids)}"
            )

        return context
