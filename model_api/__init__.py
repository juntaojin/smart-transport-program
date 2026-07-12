"""智能交通系统模型API包 - 统一导出核心视觉检测/识别/判断函数供主服务调用。"""

from .detect_vehicles import detect_vehicles     # YOLO车辆检测: BGR帧 → [{box, class, confidence}]
from .recognize_plate import recognize_plate     # HyperLPR3车牌识别: 车辆ROI → (plate_number, confidence)
from .detect_anomalies import (                  # 双路背景建模 + YOLO排除 → 路面异常物体检测
    detect_anomalies,
    load_anomaly_model,
    reset_anomaly_state,
    unload_anomaly_model,
)
from .detect_violations import detect_violations  # 有状态超时判断: 归一化坐标 + 射线法 + 超时告警
