from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext


class TrackingNode(PipelineNode):
    """ByteTrack 追踪节点 — 透传 YOLO model.track() 产生的 track_id"""

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
        raw_track_ids = context.properties.get("vehicle_track_ids", [])

        n = len(boxes)
        track_ids = list(raw_track_ids[:n]) if raw_track_ids else []
        while len(track_ids) < n:
            track_ids.append(None)

        # ByteTrack 已持续分配 ID，缺失的用负索引兜底
        for i in range(n):
            if track_ids[i] is None:
                track_ids[i] = -(i + 1)

        context.properties["track_ids"] = track_ids
        context.properties["vehicle_boxes"] = boxes
        context.properties["vehicle_classes"] = classes

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[Tracking] Frame #{self._frame_count}: tracking {n} objects")

        return context
