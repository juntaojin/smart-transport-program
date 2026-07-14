import os
import gc
import threading
import numpy as np
from loguru import logger
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
_loaded_model_path = None
_model_error = None
_model_lock = threading.RLock()
_inference_lock = threading.RLock()


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
    with _model_lock:
        model = _model
    if model is None:
        if not load_vehicle_model():
            raise RuntimeError(_model_error or "vehicle model failed to load")
        with _model_lock:
            model = _model
    return model


def load_vehicle_model():
    """Load and warm up the shared detector before the node reports ready."""
    global _model, _loaded_model_path, _model_error
    with _inference_lock, _model_lock:
        if _model is not None:
            return True

        model_path = next(
            (path for path in _candidate_model_paths() if os.path.isfile(path)),
            None,
        )
        if model_path is None:
            _model_error = f"vehicle model file not found; configured path={YOLO_MODEL_PATH!r}"
            logger.error(f"[VehicleDetection] {_model_error}")
            return False

        model_path = os.path.abspath(model_path)
        if YOLO_MODEL_PATH and not os.path.isfile(YOLO_MODEL_PATH):
            logger.warning(
                f"[VehicleDetection] Configured model not found: {YOLO_MODEL_PATH}; "
                f"using fallback: {model_path}"
            )

        try:
            logger.info(
                f"[VehicleDetection] Loading YOLO model: {model_path}, "
                f"conf={CONF_THRESHOLD}, iou={IOU_THRESHOLD}, imgsz={IMGSZ}, "
                f"classes={VEHICLE_CLASSES}"
            )
            model = YOLO(model_path)
            model.predict(
                np.zeros((IMGSZ, IMGSZ, 3), dtype=np.uint8),
                conf=CONF_THRESHOLD,
                iou=IOU_THRESHOLD,
                imgsz=IMGSZ,
                classes=VEHICLE_CLASSES,
                verbose=False,
            )
            _model = model
            _loaded_model_path = model_path
            _model_error = None
            logger.info(f"[VehicleDetection] YOLO model loaded and warmed up: {model_path}")
            return True
        except Exception as exc:
            _model = None
            _loaded_model_path = None
            _model_error = str(exc)
            logger.exception(f"[VehicleDetection] Failed to load or warm up model: {exc}")
            return False


def unload_vehicle_model():
    """Release the detector after any active inference call has finished."""
    global _model, _loaded_model_path, _model_error
    with _inference_lock, _model_lock:
        model = _model
        _model = None
        _loaded_model_path = None
        _model_error = None
        if model is not None:
            del model
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as exc:
                logger.debug(f"[VehicleDetection] CUDA cache cleanup skipped: {exc}")
        logger.info("[VehicleDetection] YOLO model unloaded")


def get_vehicle_model_status():
    with _model_lock:
        return {
            "state": "ready" if _model is not None else ("error" if _model_error else "unloaded"),
            "loaded": _model is not None,
            "path": _loaded_model_path,
            "error": _model_error,
        }


def detect_vehicles(frame, confidence=None, iou=None):
    try:
        confidence = CONF_THRESHOLD if confidence is None else float(confidence)
        iou = IOU_THRESHOLD if iou is None else float(iou)
        with _inference_lock:
            model = _get_model()
            results = model.predict(
                frame,
                conf=confidence,
                iou=iou,
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
    except Exception as e:
        logger.exception(f"[VehicleDetection] Inference failed: {e}")
        return []
