import numpy as np

class FrameContext:
    """上下文属性包：承载一帧的原始数据及所有流经节点的计算结果"""

    def __init__(self, frame_data: np.ndarray, timestamp: float, device_id: str):
        self.frame = frame_data            # 原始图像帧 (BGR numpy array)
        self.timestamp = timestamp          # 帧时间戳 (Unix timestamp)
        self.device_id = device_id          # 来源设备 ID
        self.properties: dict = {}          # 属性包字典，由各节点动态写入
