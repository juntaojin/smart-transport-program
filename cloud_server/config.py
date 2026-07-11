import os
import yaml
from loguru import logger

# Base directory setup
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

# Default configurations in case loading fails
defaults = {
    "cloud_server": {
        "host": "0.0.0.0",
        "port": 8000,
        "enable_ssl": False,
        "database": {"path": "data/its.db"},
        "video": {"width": 1280, "height": 720, "fps": 15, "jpeg_quality": 95,
                   "rtsp_mjpeg_qscale": 5, "capture_fps": 24,
                   "stream_broadcast_fps": 24, "rtsp_broadcast_fps": 30},
        "models": {
            "yolo_model_path": "models/yolo26s.pt",
            "yolo_confidence": 0.25,
            "yolo_iou": 0.45,
            "yolo_imgsz": 640,
            "anomaly_threshold": 0.25
        },
        "zones": {
            "no_parking": [
                {"name": "主路禁停区", "points": [[0.1, 0.1], [0.3, 0.1], [0.3, 0.4], [0.1, 0.4]]},
                {"name": "路口禁停区", "points": [[0.6, 0.5], [0.9, 0.5], [0.9, 0.9], [0.6, 0.9]]}
            ]
        },
        "thresholds": {
            "parking_duration_limit": 10.0,
            "congestion_high": 8,
            "congestion_medium": 5,
            "congestion_low": 3,
            "device_timeout": 30,
            "data_retention_days": 30,
            "monitor_interval": 5
        }
    }
}

config_data = defaults
if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if loaded and "cloud_server" in loaded:
                config_data = loaded
                logger.info(f"Successfully loaded global configuration from {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Failed to parse config.yaml, using default values. Error: {e}")
else:
    logger.warning(f"config.yaml not found at {CONFIG_PATH}. Using internal defaults.")

c_server = config_data["cloud_server"]

# Web Server parameters
HOST = c_server.get("host", "0.0.0.0")
PORT = c_server.get("port", 8000)
ENABLE_SSL = c_server.get("enable_ssl", False)

# Database Config
db_path = c_server["database"]["path"]
# If it's a relative path, join with BASE_DIR
if not os.path.isabs(db_path):
    db_path = os.path.join(BASE_DIR, db_path)
    
DATA_DIR = os.path.dirname(db_path)
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

# Video Stream Config
VIDEO_FRAME_WIDTH = c_server["video"]["width"]
VIDEO_FRAME_HEIGHT = c_server["video"]["height"]
VIDEO_FPS = c_server["video"]["fps"]
JPEG_QUALITY = c_server["video"].get("jpeg_quality", 95)
RTSP_MJPEG_QSCALE = c_server["video"].get("rtsp_mjpeg_qscale", 5)
CAPTURE_FPS = c_server["video"].get("capture_fps", 20)
STREAM_BROADCAST_FPS = c_server["video"].get("stream_broadcast_fps", 15)
RTSP_BROADCAST_FPS = c_server["video"].get("rtsp_broadcast_fps", 20)

# AI Model Config
model_path = c_server["models"]["yolo_model_path"]
if not os.path.isabs(model_path):
    YOLO_MODEL_PATH = os.path.join(BASE_DIR, model_path)
else:
    YOLO_MODEL_PATH = model_path
os.makedirs(os.path.dirname(YOLO_MODEL_PATH), exist_ok=True)

YOLO_CONFIDENCE = c_server["models"]["yolo_confidence"]
YOLO_IOU = c_server["models"].get("yolo_iou", 0.45)
YOLO_IMGSZ = c_server["models"].get("yolo_imgsz", 640)
ANOMALY_THRESHOLD = c_server["models"].get("anomaly_threshold", 0.25)

# No Parking Zones (map to tuples for points to keep pipeline logic unchanged)
raw_zones = c_server["zones"]["no_parking"]
NO_PARKING_ZONES = []
for zone in raw_zones:
    NO_PARKING_ZONES.append({
        "name": zone["name"],
        "points": [tuple(pt) for pt in zone["points"]]
    })

# System Thresholds
c_thresh = c_server["thresholds"]
PARKING_THRESHOLD = c_thresh["parking_duration_limit"]
CONGESTION_HIGH = c_thresh["congestion_high"]
CONGESTION_MEDIUM = c_thresh["congestion_medium"]
CONGESTION_LOW = c_thresh["congestion_low"]
DEVICE_TIMEOUT = c_thresh["device_timeout"]
DATA_RETENTION_DAYS = c_thresh["data_retention_days"]
MONITOR_INTERVAL = c_thresh["monitor_interval"]
