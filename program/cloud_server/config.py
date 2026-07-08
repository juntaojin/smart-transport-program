import os

# Base directory setup
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Database Config
DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(DATA_DIR, 'its.db')}"

# Video Stream Config
VIDEO_FRAME_WIDTH = 1280
VIDEO_FRAME_HEIGHT = 720
VIDEO_FPS = 15

# AI Model Config
YOLO_MODEL_PATH = os.path.join(BASE_DIR, "models", "yolov8n.pt")
os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)
YOLO_CONFIDENCE = 0.5
PLATE_CONFIDENCE = 0.6

# No Parking Zones (normalized coordinates [0, 1] relative to resolution)
NO_PARKING_ZONES = [
    {"name": "主路禁停区", "points": [(0.1, 0.1), (0.3, 0.1), (0.3, 0.4), (0.1, 0.4)]},
    {"name": "路口禁停区", "points": [(0.6, 0.5), (0.9, 0.5), (0.9, 0.9), (0.6, 0.9)]},
]

# System Thresholds
PARKING_THRESHOLD = 10.0      # Seconds before triggering alarm
CONGESTION_HIGH = 8
CONGESTION_MEDIUM = 5
CONGESTION_LOW = 3
DEVICE_TIMEOUT = 30           # Device heartbeat timeout in seconds
DATA_RETENTION_DAYS = 30      # Retain history database records for 30 days
MONITOR_INTERVAL = 5          # System metrics collection interval in seconds
