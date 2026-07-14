import threading

from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.runtime_config import get_model_parameters
from model_api import detect_vehicles, load_vehicle_model, unload_vehicle_model


class VehicleDetectionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="vehicle_detection")
        self._frame_count = 0
        self._lifecycle_lock = threading.RLock()
        self._ready = False

    def load_model(self):
        with self._lifecycle_lock:
            if not load_vehicle_model():
                self._ready = False
                raise RuntimeError("vehicle detection model failed to load")
            self._ready = True
            self._frame_count = 0
            logger.info("[VehicleDetection] Node ready")

    def unload_model(self):
        with self._lifecycle_lock:
            self._ready = False
            unload_vehicle_model()
            logger.info("[VehicleDetection] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        with self._lifecycle_lock:
            if not self._ready:
                context.properties["vehicle_boxes"] = []
                context.properties["vehicle_classes"] = []
                context.properties["vehicle_confidences"] = []
                return context

            self._frame_count += 1
            parameters = get_model_parameters(self.name)

            try:
                vehicles = detect_vehicles(
                    context.frame,
                    confidence=parameters["confidence"],
                    iou=parameters["iou"],
                )
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

            for v in vehicles:
                boxes.append(v["box"])
                classes.append(v["class"])
                confs.append(v.get("confidence", 0.0))

            if self._frame_count <= 5 or self._frame_count % 30 == 0:
                logger.info(f"[VehicleDetection] Frame #{self._frame_count}: detected {len(boxes)} vehicles")

            context.properties["vehicle_boxes"] = boxes
            context.properties["vehicle_classes"] = classes
            context.properties["vehicle_confidences"] = confs
            return context
