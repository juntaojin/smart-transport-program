import gc
import torch
from loguru import logger
from ultralytics import YOLO
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.config import YOLO_MODEL_PATH, YOLO_CONFIDENCE, YOLO_IOU, YOLO_IMGSZ

VEHICLE_CLASS_IDS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

class VehicleDetectionNode(PipelineNode):
    def __init__(self, confidence=None, iou=None, imgsz=None):
        super().__init__(name="vehicle_detection")
        self.confidence = confidence if confidence is not None else YOLO_CONFIDENCE
        self.iou = iou if iou is not None else YOLO_IOU
        self.imgsz = imgsz if imgsz is not None else YOLO_IMGSZ
        self._frame_count = 0

    def load_model(self):
        if self._model is None:
            logger.info(f"[VehicleDetection] Loading YOLO model: {YOLO_MODEL_PATH}")
            logger.info(f"[VehicleDetection] Config: conf={self.confidence}, iou={self.iou}, imgsz={self.imgsz}")
            logger.info(f"[VehicleDetection] CUDA available: {torch.cuda.is_available()}, device count: {torch.cuda.device_count()}")
            if torch.cuda.is_available():
                logger.info(f"[VehicleDetection] CUDA device: {torch.cuda.get_device_name(0)}")
                logger.info(f"[VehicleDetection] CUDA memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
            self._model = YOLO(YOLO_MODEL_PATH)
            actual_device = str(self._model.device) if hasattr(self._model, 'device') else 'unknown'
            logger.info(f"[VehicleDetection] YOLO loaded on device: {actual_device}")
            if torch.cuda.is_available():
                try:
                    self._model.to("cuda")
                    logger.info(f"[VehicleDetection] Explicitly moved model to CUDA, device now: {self._model.device}")
                except Exception as e:
                    logger.warning(f"[VehicleDetection] Failed to move model to CUDA: {e}")
            else:
                logger.warning("[VehicleDetection] CUDA not available, model running on CPU. Performance will be slow.")
            self._frame_count = 0
            logger.info("[VehicleDetection] Model loaded successfully")

    def unload_model(self):
        if self._model is not None:
            logger.info("[VehicleDetection] Unloading model and clearing cache")
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("[VehicleDetection] Model unloaded")

    def _do_process(self, context: FrameContext) -> FrameContext:
        if self._model is None:
            self.load_model()

        self._frame_count += 1
        results = self._model(
            context.frame,
            conf=self.confidence,
            iou=self.iou,
            imgsz=self.imgsz,
            classes=list(VEHICLE_CLASS_IDS.keys()),
            verbose=False,
        )

        boxes = []
        classes = []
        confs = []

        if results and results[0].boxes is not None:
            for box in results[0].boxes:
                cls_id = int(box.cls[0].item())
                if cls_id in VEHICLE_CLASS_IDS:
                    xyxy = box.xyxy[0].cpu().numpy().tolist()
                    conf = float(box.conf[0].item())
                    boxes.append(xyxy)
                    classes.append(VEHICLE_CLASS_IDS[cls_id])
                    confs.append(conf)

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[VehicleDetection] Frame #{self._frame_count}: detected {len(boxes)} vehicles")

        context.properties["vehicle_boxes"] = boxes
        context.properties["vehicle_classes"] = classes
        context.properties["vehicle_confidences"] = confs
        return context
