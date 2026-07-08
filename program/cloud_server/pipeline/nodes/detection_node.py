import gc
import torch
from loguru import logger
from ultralytics import YOLO
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.config import YOLO_MODEL_PATH, YOLO_CONFIDENCE

class VehicleDetectionNode(PipelineNode):
    """基于 YOLOv8n 的车辆检测节点"""

    def __init__(self, confidence: float = None):
        super().__init__(name="vehicle_detection")
        self.confidence = confidence if confidence is not None else YOLO_CONFIDENCE

    def load_model(self):
        if self._model is None:
            logger.info(f"Loading YOLOv8 model from {YOLO_MODEL_PATH}")
            self._model = YOLO(YOLO_MODEL_PATH)
            # Warmup
            if torch.cuda.is_available():
                self._model.to("cuda")
            elif torch.backends.mps.is_available():
                # For macOS Apple Silicon
                self._model.to("mps")

    def unload_model(self):
        if self._model is not None:
            logger.info("Unloading YOLOv8 model and clearing cache")
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif torch.backends.mps.is_available():
                # Clear Apple Silicon MPS cache if needed
                pass

    def _do_process(self, context: FrameContext) -> FrameContext:
        if self._model is None:
            self.load_model()

        # Run YOLO detection
        results = self._model(context.frame, conf=self.confidence, verbose=False)
        boxes, classes, confs = self._extract_vehicle_results(results)

        # Write to property bag
        context.properties["vehicle_boxes"] = boxes
        context.properties["vehicle_classes"] = classes
        context.properties["vehicle_confidences"] = confs
        return context

    def _extract_vehicle_results(self, results):
        boxes = []
        classes = []
        confs = []
        
        # Class names in YOLOv8 COCO dataset:
        # 2: car, 3: motorcycle, 5: bus, 7: truck, 1: bicycle
        vehicle_class_ids = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 1: "bicycle"}

        if not results:
            return boxes, classes, confs

        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    cls_id = int(box.cls[0].item())
                    if cls_id in vehicle_class_ids:
                        # Extract coordinates: xyxy format [x1, y1, x2, y2]
                        xyxy = box.xyxy[0].cpu().numpy().tolist()
                        conf = float(box.conf[0].item())
                        
                        boxes.append(xyxy)
                        classes.append(vehicle_class_ids[cls_id])
                        confs.append(conf)

        return boxes, classes, confs
