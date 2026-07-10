import os
import numpy as np
from ultralytics import YOLO

CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
VEHICLE_CLASSES = list(CLASS_NAMES.keys())
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
IMGSZ = 640

_model = None


def _get_model():
    global _model
    if _model is None:
        root_dir = os.path.dirname(os.path.dirname(__file__))
        model_path = os.path.join(root_dir, "models", "yolo26n.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), "weights", "yolo26n.pt")
        if not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(__file__), "yolo26n.pt")
        if not os.path.exists(model_path):
            model_path = "yolo26n.pt"
        _model = YOLO(model_path)
    return _model


def detect_vehicles(frame):
    try:
        model = _get_model()
        results = model(
            frame,
            conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD,
            imgsz=IMGSZ,
            classes=VEHICLE_CLASSES,
            verbose=False,
        )

        vehicles = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                xyxy = boxes.xyxy[i].cpu().numpy()
                vehicles.append({
                    "box": xyxy.tolist(),
                    "class": CLASS_NAMES.get(cls_id, "car"),
                    "confidence": conf,
                })

        return vehicles
    except Exception:
        return []
