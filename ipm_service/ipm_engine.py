import cv2
import numpy as np
from loguru import logger


def compute_ipm(camera_points, world_points):
    """根据4对对应点计算3x3单应性矩阵（RANSAC）"""
    src = np.array(camera_points, dtype=np.float32).reshape(-1, 1, 2)
    dst = np.array(world_points, dtype=np.float32).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        raise ValueError("cv2.findHomography 计算失败，请检查对应点质量")
    inliers = int(mask.sum()) if mask is not None else 0
    logger.info(f"单应性矩阵计算成功，{inliers}/{len(camera_points)} 个内点")
    return H


def transform_points(points, H):
    """通过单应性矩阵将像素坐标映射到俯视坐标"""
    if not points:
        return []
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    result = cv2.perspectiveTransform(pts, H)
    return result.reshape(-1, 2).tolist()
