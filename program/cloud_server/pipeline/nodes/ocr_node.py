import gc
import cv2
import torch
from loguru import logger
import easyocr
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.config import PLATE_CONFIDENCE

class PlateRecognitionNode(PipelineNode):
    """基于 EasyOCR 的车牌识别节点"""

    def __init__(self, confidence: float = None):
        super().__init__(name="plate_ocr")
        self.confidence = confidence if confidence is not None else PLATE_CONFIDENCE

    def load_model(self):
        if self._model is None:
            logger.info("Loading EasyOCR Reader for Chinese and English...")
            gpu_available = torch.cuda.is_available() or torch.backends.mps.is_available()
            self._model = easyocr.Reader(['ch_sim', 'en'], gpu=gpu_available)

    def unload_model(self):
        if self._model is not None:
            logger.info("Unloading EasyOCR Reader and clearing cache")
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _do_process(self, context: FrameContext) -> FrameContext:
        if self._model is None:
            self.load_model()

        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])
        
        plates = []
        confidences = []

        h_img, w_img = context.frame.shape[:2]

        for idx, box in enumerate(boxes):
            # Only perform plate recognition on motor vehicles (car, truck, bus)
            if classes[idx] not in ["car", "truck", "bus"]:
                plates.append("")
                confidences.append(0.0)
                continue

            x1, y1, x2, y2 = [int(coord) for coord in box]
            
            # Constrain bounding boxes to frame dimensions
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)

            if (x2 - x1) <= 0 or (y2 - y1) <= 0:
                plates.append("")
                confidences.append(0.0)
                continue

            # Crop lower half of vehicle bounding box where license plate is usually located
            y_lower = y1 + int((y2 - y1) * 0.4)
            crop = context.frame[y_lower:y2, x1:x2]

            try:
                # Read text
                results = self._model.readtext(crop)
                
                # Filter results by confidence threshold and find license plate pattern
                best_text = ""
                best_conf = 0.0
                
                for res in results:
                    # res: ([[x,y], ...], text, confidence)
                    text = res[1].strip()
                    conf = float(res[2])
                    
                    if conf >= self.confidence:
                        # Clean up text (remove spaces, punctuation)
                        cleaned = "".join([c for c in text if c.isalnum() or c in ["警", "学", "挂", "港", "澳"]])
                        if len(cleaned) > len(best_text):
                            best_text = cleaned
                            best_conf = conf
                            
                plates.append(best_text)
                confidences.append(best_conf)
            except Exception as e:
                logger.error(f"EasyOCR error on vehicle index {idx}: {e}")
                plates.append("")
                confidences.append(0.0)

        context.properties["plate_numbers"] = plates
        context.properties["plate_confidences"] = confidences
        return context
