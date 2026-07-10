import os
import traceback
import numpy as np
from ultralytics import YOLO

CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
VEHICLE_CLASSES = list(CLASS_NAMES.keys())
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
IMGSZ = 640

_model = None
_tracker_config = None


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


def _get_tracker_config():
    global _tracker_config
    if _tracker_config is None:
        cfg = os.path.join(os.path.dirname(__file__), "botsort_custom.yaml")
        if os.path.exists(cfg):
            _tracker_config = cfg
        else:
            _tracker_config = "botsort.yaml"  # fallback to default
    return _tracker_config


def detect_vehicles(frame):
    try:
        model = _get_model()
        tracker_cfg = _get_tracker_config()
        results = model.track(
            frame,
            conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD,
            imgsz=IMGSZ,
            classes=VEHICLE_CLASSES,
            tracker=tracker_cfg,
            persist=True,
            verbose=False,
        )

        vehicles = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                xyxy = boxes.xyxy[i].cpu().numpy()
                tid = None
                if boxes.id is not None and i < len(boxes.id):
                    tid = int(boxes.id[i].item())
                vehicles.append({
                    "box": xyxy.tolist(),
                    "class": CLASS_NAMES.get(cls_id, "car"),
                    "confidence": conf,
                    "track_id": tid,
                })

        return vehicles
    except Exception as e:
        print(f"[detect_vehicles] Error: {e}")
        traceback.print_exc()
        return []
