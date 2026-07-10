from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from model_api import detect_vehicles


class VehicleDetectionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="vehicle_detection")
        self._frame_count = 0

    def load_model(self):
        logger.info("[VehicleDetection] Node ready (function-call mode)")
        self._frame_count = 0

    def unload_model(self):
        logger.info("[VehicleDetection] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1

        try:
            vehicles = detect_vehicles(context.frame)
        except NotImplementedError:
            logger.error("[VehicleDetection] detect_vehicles() 尚未实现！等待模型同学实现。")
            context.properties["vehicle_boxes"] = []
            context.properties["vehicle_classes"] = []
            context.properties["vehicle_confidences"] = []
            return context
        except Exception as e:
            logger.error(f"[VehicleDetection] 函数调用失败: {e}")
            context.properties["vehicle_boxes"] = []
            context.properties["vehicle_classes"] = []
            context.properties["vehicle_confidences"] = []
            return context

        boxes = []
        classes = []
        confs = []
        tids = []

        for v in vehicles:
            boxes.append(v["box"])
            classes.append(v["class"])
            confs.append(v.get("confidence", 0.0))
            tids.append(v.get("track_id"))

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[VehicleDetection] Frame #{self._frame_count}: detected {len(boxes)} vehicles")

        context.properties["vehicle_boxes"] = boxes
        context.properties["vehicle_classes"] = classes
        context.properties["vehicle_confidences"] = confs
        context.properties["vehicle_track_ids"] = tids
        return context
