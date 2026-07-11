import yaml
from loguru import logger
from cloud_server.config import CONFIG_PATH


def _read_config():
    """读取 config.yaml 完整内容"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _write_config(config):
    """写入 config.yaml"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        logger.error(f"写入 config.yaml 失败: {e}")
        raise


def load_all_cameras():
    """列出所有已标定的摄像头及其车道"""
    config = _read_config()
    ipm = config.get("ipm_service", {})
    return {cam_id: list(lanes.keys()) for cam_id, lanes in ipm.items()}


def load_camera_lanes(camera_id):
    """获取指定摄像头的全部车道标定（不含 homography_matrix）"""
    config = _read_config()
    ipm = config.get("ipm_service", {})
    if camera_id not in ipm:
        return None
    lanes = {}
    for lane_id, lane_cfg in ipm[camera_id].items():
        lanes[lane_id] = {
            "camera_points": lane_cfg["camera_points"],
            "world_points": lane_cfg["world_points"],
        }
    return lanes


def load_lane_config(camera_id, lane_id):
    """获取指定 (camera_id, lane_id) 的完整标定配置"""
    config = _read_config()
    ipm = config.get("ipm_service", {})
    if camera_id not in ipm:
        return None
    if lane_id not in ipm[camera_id]:
        return None
    return ipm[camera_id][lane_id]


def save_lane_config(camera_id, lane_id, camera_points, world_points, H):
    """保存标定配置到 config.yaml ipm_service 节"""
    config = _read_config()
    if "ipm_service" not in config:
        config["ipm_service"] = {}
    if camera_id not in config["ipm_service"]:
        config["ipm_service"][camera_id] = {}

    config["ipm_service"][camera_id][lane_id] = {
        "camera_points": [[round(p[0], 2), round(p[1], 2)] for p in camera_points],
        "world_points": [[round(p[0], 2), round(p[1], 2)] for p in world_points],
        "homography_matrix": [[round(float(v), 8) for v in row] for row in H],
    }

    _write_config(config)
    logger.info(f"IPM 标定已保存: {camera_id}/{lane_id}")


def delete_lane_config(camera_id, lane_id):
    """删除指定车道标定，若摄像头下车道全部删除则同时删除摄像头条目"""
    config = _read_config()
    ipm = config.get("ipm_service", {})
    if camera_id not in ipm or lane_id not in ipm.get(camera_id, {}):
        return False

    del ipm[camera_id][lane_id]
    if not ipm[camera_id]:
        del ipm[camera_id]
    if not ipm:
        del config["ipm_service"]

    _write_config(config)
    logger.info(f"IPM 标定已删除: {camera_id}/{lane_id}")
    return True
