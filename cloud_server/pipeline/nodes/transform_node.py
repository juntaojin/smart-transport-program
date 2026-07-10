import numpy as np
from typing import Optional
from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.utils.homography import load_homography, apply_homography


class CoordinateTransformNode(PipelineNode):
    """
    坐标变换节点：将车辆像素坐标（斜视摄像头视角）映射到俯视世界坐标

    依赖追踪节点输出的 vehicle_boxes 和 track_ids。
    仅读取，不覆盖 context 中的任何字段。
    """

    def __init__(self):
        super().__init__(name="transform")
        self._frame_count = 0
        self._H_cache = {}  # {device_id: (H_matrix, timestamp)}

    def load_model(self):
        logger.info("[Transform] Node ready")
        self._frame_count = 0

    def unload_model(self):
        self._H_cache.clear()
        logger.info("[Transform] Node disabled, cache cleared")

    def _get_homography(self, device_id: str) -> Optional[np.ndarray]:
        """获取单应性矩阵（带缓存，避免每帧读 YAML）"""
        if device_id in self._H_cache:
            return self._H_cache[device_id]

        H = load_homography(device_id)
        if H is not None:
            self._H_cache[device_id] = H
        return H

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1

        H = self._get_homography(context.device_id)
        if H is None:
            context.properties["world_coords"] = {}
            if self._frame_count <= 3 or self._frame_count % 120 == 0:
                logger.warning(
                    f"[Transform] 设备 {context.device_id} 未标定，"
                    f"跳过坐标变换（请使用 /api/calibration 进行标定）"
                )
            return context

        boxes = context.properties.get("vehicle_boxes", [])
        track_ids = context.properties.get("track_ids", [])

        world_coords = {}

        if boxes and len(boxes) > 0:
            bottom_centers = np.array([
                [(b[0] + b[2]) / 2.0, b[3]]  # 底部中心点
                for b in boxes
            ], dtype=np.float32)

            transformed = apply_homography(bottom_centers, H)

            for i, (wx, wy) in enumerate(transformed):
                tid = track_ids[i] if i < len(track_ids) else None
                if tid is not None:
                    world_coords[tid] = {"x": float(wx), "y": float(wy)}

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[Transform] Frame #{self._frame_count}: "
                f"{len(world_coords)} vehicles transformed"
            )

        context.properties["world_coords"] = world_coords
        return context
