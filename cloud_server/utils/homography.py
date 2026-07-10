import cv2
import numpy as np
import os
import yaml
from typing import Optional
from loguru import logger
from cloud_server.config import BASE_DIR, CONFIG_PATH


def compute_homography(image_points: list[list[float]], world_points: list[list[float]]):
    """
    根据至少 4 对对应点计算单应性矩阵 H

    Args:
        image_points: 摄像头画面中的像素坐标 [[x, y], ...]
        world_points: 俯视图中的世界坐标 [[x, y], ...]

    Returns:
        np.ndarray: 3x3 单应性矩阵，或 None（点数不足时）
    """
    if len(image_points) < 4 or len(world_points) < 4:
        logger.error("至少需要 4 对对应点才能计算单应性矩阵")
        return None
    if len(image_points) != len(world_points):
        logger.error("image_points 和 world_points 数量不一致")
        return None

    src = np.array(image_points, dtype=np.float32).reshape(-1, 1, 2)
    dst = np.array(world_points, dtype=np.float32).reshape(-1, 1, 2)

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        logger.error("cv2.findHomography 计算失败，请检查对应点质量")
        return None

    inliers = int(mask.sum()) if mask is not None else 0
    logger.info(f"单应性矩阵计算成功，{inliers}/{len(image_points)} 个内点")
    return H


def apply_homography(points: np.ndarray, H: np.ndarray) -> np.ndarray:
    """
    将像素坐标通过单应性矩阵映射到世界坐标

    Args:
        points: np.ndarray, 形状 (N, 2), N 个 (x, y) 像素坐标
        H:       np.ndarray, 3x3 单应性矩阵

    Returns:
        np.ndarray, 形状 (N, 2), 变换后的 (x, y) 世界坐标
    """
    if points.ndim == 1:
        points = points.reshape(1, 2)
    pts = points.reshape(-1, 1, 2).astype(np.float32)
    transformed = cv2.perspectiveTransform(pts, H)
    return transformed.reshape(-1, 2)


def load_homography(device_id: str) -> Optional[np.ndarray]:
    """从 config.yaml 加载指定设备的单应性矩阵"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        calib = config.get("calibration", {})
        if device_id not in calib:
            return None

        h_data = calib[device_id].get("homography_matrix")
        if not h_data or len(h_data) != 3:
            return None

        return np.array(h_data, dtype=np.float64)
    except Exception as e:
        logger.error(f"加载单应性矩阵失败 [{device_id}]: {e}")
        return None


def save_homography(device_id: str, image_points: list[list[float]],
                    world_points: list[list[float]], H: np.ndarray) -> bool:
    """将标定结果写入 config.yaml"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        if "calibration" not in config:
            config["calibration"] = {}

        config["calibration"][device_id] = {
            "image_points": [[round(p[0], 2), round(p[1], 2)] for p in image_points],
            "world_points": [[round(p[0], 2), round(p[1], 2)] for p in world_points],
            "homography_matrix": [[round(float(v), 8) for v in row] for row in H],
        }

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"单应性矩阵已保存 [{device_id}]")
        return True
    except Exception as e:
        logger.error(f"保存单应性矩阵失败 [{device_id}]: {e}")
        return False


def delete_homography(device_id: str) -> bool:
    """从 config.yaml 删除指定设备的标定数据"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        if "calibration" in config and device_id in config["calibration"]:
            del config["calibration"][device_id]
            if not config["calibration"]:
                del config["calibration"]

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            logger.info(f"标定数据已删除 [{device_id}]")
            return True
        return False
    except Exception as e:
        logger.error(f"删除标定数据失败 [{device_id}]: {e}")
        return False
