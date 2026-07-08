import gc
import torch
import cv2
from PIL import Image
from loguru import logger
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext

class AnomalyDetectionNode(PipelineNode):
    """基于 Grounding DINO 的零样本路面异常检测节点"""

    def __init__(self, threshold: float = 0.25):
        super().__init__(name="anomaly_detection")
        self.threshold = threshold
        self.model_id = "IDEA-Research/grounding-dino-tiny"
        self.processor = None

    def load_model(self):
        if self._model is None:
            logger.info(f"Loading Grounding DINO model '{self.model_id}'...")
            self.processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = AutoModelForZeroShotObjectDetection.from_pretrained(self.model_id)
            
            # Move to GPU/device if available
            device = "cpu"
            if torch.cuda.is_available():
                device = "cuda"
            elif torch.backends.mps.is_available():
                device = "mps"
            self._model.to(device)

    def unload_model(self):
        if self._model is not None:
            logger.info("Unloading Grounding DINO model and clearing cache")
            self._model = None
            self.processor = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _do_process(self, context: FrameContext) -> FrameContext:
        if self._model is None:
            self.load_model()

        # Text prompt for anomalies/obstacles on the road
        prompt = "obstacle . debris . dropped cargo . tire . box . trash . rock"
        
        # Convert BGR frame to PIL RGB
        image_rgb = cv2.cvtColor(context.frame, cv2.COLOR_BGR2RGB)
        image_pil = Image.fromarray(image_rgb)
        
        device = next(self._model.parameters()).device
        
        # Process inputs
        inputs = self.processor(images=image_pil, text=prompt, return_tensors="pt").to(device)
        
        with torch.no_grad():
            outputs = self._model(**inputs)
            
        # Post-process detections
        results = self.processor.post_process_grounded_object_detection(
            outputs, 
            input_ids=inputs.input_ids,
            threshold=self.threshold, 
            text_threshold=0.25,
            target_sizes=[image_pil.size[::-1]]
        )[0]
        
        # Extract bounding boxes, labels, and confidences
        anomalies = []
        boxes = results["boxes"].cpu().numpy().tolist()
        scores = results["scores"].cpu().numpy().tolist()
        labels = results["labels"]
        
        for box, score, label in zip(boxes, scores, labels):
            anomalies.append({
                "box": [float(coord) for coord in box],
                "confidence": float(score),
                "label": label
            })
            
        context.properties["road_anomalies"] = anomalies
        return context
