import os
import traceback
import numpy as np
from ultralytics import YOLO

try:
    from cloud_server.config import YOLO_MODEL_PATH, YOLO_CONFIDENCE, YOLO_IOU, YOLO_IMGSZ
except Exception:
    YOLO_MODEL_PATH = None
    YOLO_CONFIDENCE = 0.75
    YOLO_IOU = 0.5
    YOLO_IMGSZ = 640

CLASS_NAMES = {0: "car"}
VEHICLE_CLASSES = list(CLASS_NAMES.keys())
CONF_THRESHOLD = float(YOLO_CONFIDENCE or 0.3)
IOU_THRESHOLD = float(YOLO_IOU or 0.45)
IMGSZ = int(YOLO_IMGSZ or 640)
DEFAULT_MODEL_NAME = "yolov11s_cisdrone_t.pt"
FALLBACK_MODEL_NAMES = ("yolov11s_visdrone_t.pt", "yolo26s.pt")

_model = None


def _candidate_model_paths():
    root_dir = os.path.dirname(os.path.dirname(__file__))
    candidates = []
    if YOLO_MODEL_PATH:
        candidates.append(YOLO_MODEL_PATH)
    for model_name in (DEFAULT_MODEL_NAME, *FALLBACK_MODEL_NAMES):
        candidates.extend([
            os.path.join(root_dir, "models", model_name),
            os.path.join(os.path.dirname(__file__), "weights", model_name),
            os.path.join(os.path.dirname(__file__), model_name),
            model_name,
        ])
    return candidates


def _get_model():
    global _model
    if _model is None:
        model_path = next((path for path in _candidate_model_paths() if os.path.exists(path)), DEFAULT_MODEL_NAME)
        if YOLO_MODEL_PATH and not os.path.exists(YOLO_MODEL_PATH) and model_path != DEFAULT_MODEL_NAME:
            print(f"[detect_vehicles] Configured model not found: {YOLO_MODEL_PATH}; using fallback: {model_path}")
        print(f"[detect_vehicles] Loading YOLO model: {model_path}, conf={CONF_THRESHOLD}, iou={IOU_THRESHOLD}, imgsz={IMGSZ}, classes={VEHICLE_CLASSES}")
        _model = YOLO(model_path)
    return _model


def detect_vehicles(frame):
    try:
        model = _get_model()
        results = model.track(
            frame,
            conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD,
            imgsz=IMGSZ,
            classes=VEHICLE_CLASSES,
            tracker="bytetrack.yaml",
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
