"""Thread-safe model parameters that can be updated while inference is running."""

import os
import threading
from copy import deepcopy

import yaml

from cloud_server import config as server_config


PARAMETER_SCHEMA = {
    "vehicle_detection": {
        "confidence": {
            "label": "检测置信度",
            "type": "number",
            "min": 0.01,
            "max": 1.0,
            "step": 0.01,
            "config_section": "models",
            "config_key": "yolo_confidence",
        },
        "iou": {
            "label": "IoU 阈值",
            "type": "number",
            "min": 0.01,
            "max": 1.0,
            "step": 0.01,
            "config_section": "models",
            "config_key": "yolo_iou",
        },
    },
    "plate_ocr": {},
    "anomaly_detection": {
        "confidence": {
            "label": "异常置信度",
            "type": "number",
            "min": 0.01,
            "max": 1.0,
            "step": 0.01,
            "config_section": "models",
            "config_key": "anomaly_threshold",
        },
    },
    "violation_detection": {
        "parking_duration": {
            "label": "违停判定时长（秒）",
            "type": "number",
            "min": 0.1,
            "max": 3600.0,
            "step": 0.1,
            "config_section": "thresholds",
            "config_key": "parking_duration_limit",
        },
    },
}

_values = {
    "vehicle_detection": {
        "confidence": float(server_config.YOLO_CONFIDENCE),
        "iou": float(server_config.YOLO_IOU),
    },
    "plate_ocr": {},
    "anomaly_detection": {
        "confidence": float(server_config.ANOMALY_THRESHOLD),
    },
    "violation_detection": {
        "parking_duration": float(server_config.PARKING_THRESHOLD),
    },
}
_lock = threading.RLock()


def get_model_parameters(model_name: str) -> dict:
    """Return one immutable-by-convention snapshot for a frame/API response."""
    with _lock:
        return deepcopy(_values.get(model_name, {}))


def get_parameter_schema(model_name: str) -> dict:
    schema = deepcopy(PARAMETER_SCHEMA.get(model_name, {}))
    for definition in schema.values():
        definition.pop("config_section", None)
        definition.pop("config_key", None)
        definition["apply_mode"] = "hot"
    return schema


def _validate(model_name: str, parameters: dict) -> dict:
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")

    schema = PARAMETER_SCHEMA.get(model_name, {})
    unknown = set(parameters) - set(schema)
    if unknown:
        raise ValueError(f"unsupported parameters: {', '.join(sorted(unknown))}")

    validated = {}
    for key, raw_value in parameters.items():
        if isinstance(raw_value, bool):
            raise ValueError(f"{key} must be a number")
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number") from None
        definition = schema[key]
        if not definition["min"] <= value <= definition["max"]:
            raise ValueError(
                f"{key} must be between {definition['min']} and {definition['max']}"
            )
        validated[key] = value
    return validated


def _persist(model_name: str, parameters: dict) -> None:
    config_path = server_config.CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as file:
        document = yaml.safe_load(file) or {}

    cloud_config = document.setdefault("cloud_server", {})
    for key, value in parameters.items():
        definition = PARAMETER_SCHEMA[model_name][key]
        section = cloud_config.setdefault(definition["config_section"], {})
        section[definition["config_key"]] = value

    temp_path = f"{config_path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(
                document,
                file,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        os.replace(temp_path, config_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def update_model_parameters(model_name: str, parameters: dict) -> dict:
    """Validate, persist, then publish values so failed writes never partly apply."""
    validated = _validate(model_name, parameters)
    if not validated:
        return get_model_parameters(model_name)

    with _lock:
        _persist(model_name, validated)
        _values[model_name].update(validated)
        return deepcopy(_values[model_name])
