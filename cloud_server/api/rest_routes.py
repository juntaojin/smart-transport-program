import os
import json
import yaml
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from loguru import logger
import psutil

from cloud_server.database.connection import get_db
from cloud_server.database.orm_models import (
    PlateRecord, VehicleStat, ParkingViolation, RoadAnomaly, SystemMetric, ModelConfig
)
from cloud_server.config import BASE_DIR, DATA_DIR, NO_PARKING_ZONES

router = APIRouter(prefix="/api")

# --- Helper for Whitelist ---
WHITELIST_FILE = os.path.join(DATA_DIR, "whitelist.json")

def load_whitelist():
    if not os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return []
    try:
        with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading whitelist: {e}")
        return []

def save_whitelist(whitelist):
    try:
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            json.dump(whitelist, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving whitelist: {e}")


# --- 1. Whitelist API (Plate Records & Management) ---

@router.get("/whitelist")
async def get_whitelist():
    """Retrieve all white-listed license plates"""
    return {"code": 200, "message": "success", "data": load_whitelist()}

@router.post("/whitelist")
async def add_to_whitelist(payload: dict):
    """Add a new plate number to the whitelist"""
    plate = payload.get("plate_number")
    if not plate:
        raise HTTPException(status_code=400, detail="plate_number is required")
    
    whitelist = load_whitelist()
    if plate not in whitelist:
        whitelist.append(plate)
        save_whitelist(whitelist)
        
    return {"code": 200, "message": "success", "data": whitelist}

@router.delete("/whitelist/{plate}")
async def remove_from_whitelist(plate: str):
    """Remove a plate number from the whitelist"""
    whitelist = load_whitelist()
    if plate in whitelist:
        whitelist.remove(plate)
        save_whitelist(whitelist)
        return {"code": 200, "message": "success", "data": whitelist}
    raise HTTPException(status_code=404, detail=f"Plate '{plate}' not in whitelist")


# --- 2. Statistical Analysis APIs ---

@router.get("/stats/vehicles")
async def get_vehicle_stats(
    zone: str = None,
    minutes: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Get historical vehicle density statistics"""
    time_limit = datetime.utcnow() - timedelta(minutes=minutes)
    query = select(VehicleStat).where(VehicleStat.timestamp >= time_limit)
    if zone:
        query = query.where(VehicleStat.zone_name == zone)
    query = query.order_by(VehicleStat.timestamp.asc())
    
    result = await db.execute(query)
    stats = result.scalars().all()
    
    data = [{
        "id": s.id,
        "zone_name": s.zone_name,
        "vehicle_count": s.vehicle_count,
        "congestion_level": s.congestion_level,
        "timestamp": s.timestamp.isoformat()
    } for s in stats]
    
    return {"code": 200, "message": "success", "data": data}

@router.get("/stats/violations")
async def get_violation_stats(
    zone: str = None,
    minutes: int = 60,
    db: AsyncSession = Depends(get_db)
):
    """Get parking violations list"""
    time_limit = datetime.utcnow() - timedelta(minutes=minutes)
    query = select(ParkingViolation).where(ParkingViolation.timestamp >= time_limit)
    if zone:
        query = query.where(ParkingViolation.zone_name == zone)
    query = query.order_by(ParkingViolation.timestamp.desc())
    
    result = await db.execute(query)
    violations = result.scalars().all()
    
    data = [{
        "id": v.id,
        "vehicle_id": v.vehicle_id,
        "zone_name": v.zone_name,
        "parking_duration": v.parking_duration,
        "start_time": v.start_time.isoformat(),
        "end_time": v.end_time.isoformat() if v.end_time else None,
        "alert_triggered": v.alert_triggered,
        "timestamp": v.timestamp.isoformat()
    } for v in violations]
    
    return {"code": 200, "message": "success", "data": data}

@router.get("/stats/anomalies")
async def get_anomaly_stats(
    minutes: int = 60,
    db: AsyncSession = Depends(get_db)
):
    """Get road anomaly detection records"""
    time_limit = datetime.utcnow() - timedelta(minutes=minutes)
    query = select(RoadAnomaly).where(RoadAnomaly.timestamp >= time_limit).order_by(RoadAnomaly.timestamp.desc())
    
    result = await db.execute(query)
    anomalies = result.scalars().all()
    
    data = [{
        "id": a.id,
        "anomaly_type": a.anomaly_type,
        "confidence": a.confidence,
        "location_x": a.location_x,
        "location_y": a.location_y,
        "affected_lane": a.affected_lane,
        "timestamp": a.timestamp.isoformat()
    } for a in anomalies]
    
    return {"code": 200, "message": "success", "data": data}

@router.get("/stats/system")
async def get_system_stats(
    minutes: int = 15,
    db: AsyncSession = Depends(get_db)
):
    """Get system resource monitoring metrics (real-time + history)"""
    from cloud_server.utils.system_info import get_detailed_metrics
    metrics = get_detailed_metrics()

    # Fetch historical stats
    time_limit = datetime.utcnow() - timedelta(minutes=minutes)
    query = select(SystemMetric).where(SystemMetric.timestamp >= time_limit).order_by(SystemMetric.timestamp.asc())
    result = await db.execute(query)
    history = result.scalars().all()

    history_data = [{
        "cpu_usage": h.cpu_usage,
        "gpu_usage": h.gpu_usage,
        "memory_usage": h.memory_usage,
        "disk_usage": h.disk_usage,
        "network_rx": h.network_rx,
        "network_tx": h.network_tx,
        "video_fps": h.video_fps,
        "active_devices": h.active_devices,
        "timestamp": h.timestamp.isoformat()
    } for h in history]

    realtime = {
        "cpu_usage": metrics["cpu"]["percent"],
        "gpu_usage": metrics["gpu"]["load"] if metrics["gpu"] else None,
        "memory_usage": metrics["memory"]["percent"],
        "disk_usage": metrics["disk"]["percent"],
        "network_rx": metrics["network"]["rx_mbps"],
        "network_tx": metrics["network"]["tx_mbps"],
        "video_fps": 0.0,
        "active_devices": 0,
        
        # Advanced details
        "cpu_details": metrics["cpu"],
        "memory_details": metrics["memory"],
        "disk_details": metrics["disk"],
        "gpu_details": metrics["gpu"]
    }
    
    return {
        "code": 200,
        "message": "success",
        "data": {
            "realtime": realtime,
            "history": history_data
        }
    }


# --- 3. Configuration Management APIs ---

@router.get("/configs/models")
async def get_model_configs(request: Request):
    """Get user-facing AI capabilities; internal dependency nodes stay hidden."""
    pipeline = request.app.state.pipeline
    data = []
    for name in pipeline.USER_CAPABILITIES:
        node = pipeline.nodes[name]
        data.append({
            "model_name": name,
            "enabled": node.enabled,
            "requires_vehicle_pipeline": name in pipeline.VEHICLE_DEPENDENTS,
        })
    return {"code": 200, "message": "success", "data": data}

@router.put("/configs/models")
async def update_model_configs(payload: dict, request: Request):
    """Modify AI model configurations and toggle nodes in real-time"""
    model_name = payload.get("model_name")
    enabled = payload.get("enabled")
    
    if not model_name:
        raise HTTPException(status_code=400, detail="model_name is required")
        
    pipeline = request.app.state.pipeline
    
    if model_name not in pipeline.USER_CAPABILITIES:
        raise HTTPException(status_code=400, detail=f"'{model_name}' is not a user-facing capability")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="enabled must be a boolean")

    pipeline.set_capability_state(model_name, enabled)
    logger.info(f"Updated capability {model_name}: enabled={enabled}")

    states = {
        name: pipeline.nodes[name].enabled
        for name in pipeline.USER_CAPABILITIES
    }
    return {"code": 200, "message": "success", "data": states}

@router.get("/configs/zones")
async def get_zones_config(request: Request):
    """Get configured no parking zones"""
    from cloud_server.config import NO_PARKING_ZONES
    zones = []
    for z in NO_PARKING_ZONES:
        zones.append({
            "name": z["name"],
            "points": [list(pt) for pt in z["points"]],
        })
    return {"code": 200, "message": "success", "data": zones}

@router.put("/configs/zones")
async def update_zones_config(payload: list = Body(...), request: Request = None):
    """Update no-parking zones, write to config.yaml for persistence"""
    from cloud_server.config import CONFIG_PATH

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        zones_data = []
        for z in payload:
            zones_data.append({
                "name": z["name"],
                "points": z["points"],
            })

        config["cloud_server"]["zones"]["no_parking"] = zones_data
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"Updated no-parking zones: {len(zones_data)} zones written to config.yaml")
        return {"code": 200, "message": "success", "data": zones_data}
    except Exception as e:
        logger.error(f"Failed to update zones: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 4. Calibration API (摄像头标定) ---

from cloud_server.utils.homography import compute_homography, save_homography, load_homography, delete_homography


@router.post("/calibration/compute")
async def compute_calibration(payload: dict):
    """计算并保存单应性标定矩阵

    body: {
        "device_id": "camera_01",
        "image_points": [[x, y], ...],    # 摄像头画面中的点（至少4个）
        "world_points": [[x, y], ...]     # 俯视图中对应的点
    }
    """
    device_id = payload.get("device_id")
    image_points = payload.get("image_points", [])
    world_points = payload.get("world_points", [])

    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")
    if not image_points or not world_points:
        raise HTTPException(status_code=400, detail="image_points and world_points are required")
    if len(image_points) < 4:
        raise HTTPException(status_code=400, detail="at least 4 point pairs required")

    H = compute_homography(image_points, world_points)
    if H is None:
        raise HTTPException(status_code=400,
                            detail="Failed to compute homography. Check point correspondence quality.")

    success = save_homography(device_id, image_points, world_points, H)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save calibration to config file.")

    return {
        "code": 200,
        "message": "success",
        "data": {
            "device_id": device_id,
            "homography_matrix": [[round(float(v), 8) for v in row] for row in H],
        }
    }


@router.get("/calibration")
async def list_calibrations():
    """列出所有已标定的设备"""
    try:
        config = yaml.safe_load(open(CONFIG_PATH, "r", encoding="utf-8")) or {}
    except Exception:
        config = {}
    calibrations = config.get("calibration", {})
    return {"code": 200, "message": "success", "data": {"devices": list(calibrations.keys())}}


@router.get("/calibration/{device_id}")
async def get_calibration(device_id: str):
    """获取指定设备的标定数据"""
    H = load_homography(device_id)
    if H is None:
        raise HTTPException(status_code=404, detail=f"No calibration found for device '{device_id}'")

    try:
        config = yaml.safe_load(open(CONFIG_PATH, "r", encoding="utf-8")) or {}
    except Exception:
        config = {}
    calib_data = config.get("calibration", {}).get(device_id, {})
    return {
        "code": 200,
        "message": "success",
        "data": {
            "device_id": device_id,
            "image_points": calib_data.get("image_points", []),
            "world_points": calib_data.get("world_points", []),
            "homography_matrix": calib_data.get("homography_matrix", []),
        }
    }


@router.delete("/calibration/{device_id}")
async def remove_calibration(device_id: str):
    """删除指定设备的标定数据"""
    success = delete_homography(device_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"No calibration found for device '{device_id}'")
    return {"code": 200, "message": "success", "data": {"device_id": device_id}}


# --- 5. RTSP Sand Table Camera Stream Management ---


# --- 6. Health Check API ---


@router.get("/health")
async def health_check():
    return {"code": 200, "message": "healthy", "data": {"status": "OK", "timestamp": datetime.utcnow().isoformat()}}

from cloud_server.api.rtsp_streamer import SAND_TABLE_CAMERAS


@router.get("/stream/rtsp/cameras")
async def list_sand_table_cameras():
    """List all available sand table RTSP cameras"""
    return {"code": 200, "message": "success", "data": SAND_TABLE_CAMERAS}


@router.post("/stream/rtsp/start")
async def start_rtsp_stream(payload: dict, request: Request):
    """Start one sand-table RTSP camera or a limited batch of cameras."""
    rtsp_manager = request.app.state.rtsp_manager
    start_all = bool(payload.get("start_all"))
    camera_ids = payload.get("camera_ids")
    default_max_streams = len(camera_ids) if isinstance(camera_ids, list) else (len(SAND_TABLE_CAMERAS) if start_all else 1)
    max_streams = int(payload.get("max_streams") or default_max_streams)
    max_streams = max(1, min(max_streams, len(SAND_TABLE_CAMERAS)))

    if start_all or isinstance(camera_ids, list):
        requested_ids = [str(cid) for cid in camera_ids] if isinstance(camera_ids, list) else [c["id"] for c in SAND_TABLE_CAMERAS]
        camera_map = {camera["id"]: camera for camera in SAND_TABLE_CAMERAS}
        selected_cameras = [camera_map[cid] for cid in requested_ids if cid in camera_map][:max_streams]
        if not selected_cameras:
            raise HTTPException(status_code=400, detail="No valid sand-table camera selected")

        started = []
        already_active = []
        for camera in selected_cameras:
            device_id = f"rtsp_{camera['id']}"
            success = rtsp_manager.start_stream(device_id, camera["url"], camera["id"], camera["name"])
            item = {"camera_id": camera["id"], "name": camera["name"], "device_id": device_id}
            if success:
                started.append(item)
            else:
                already_active.append(item)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "started": started,
                "already_active": already_active,
                "max_streams": max_streams,
                "selected": [{"camera_id": camera["id"], "name": camera["name"], "device_id": f"rtsp_{camera['id']}"} for camera in selected_cameras],
            },
        }

    camera_id = payload.get("camera_id")
    if not camera_id:
        raise HTTPException(status_code=400, detail="camera_id is required")

    camera = next((c for c in SAND_TABLE_CAMERAS if c["id"] == camera_id), None)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    device_id = f"rtsp_{camera_id}"
    success = rtsp_manager.start_stream(device_id, camera["url"], camera["id"], camera["name"])
    if not success:
        return {"code": 409, "message": "Stream already active", "data": {"camera_id": camera_id}}

    return {"code": 200, "message": "success", "data": {"camera_id": camera_id, "name": camera["name"], "device_id": device_id}}


@router.post("/stream/rtsp/stop")
async def stop_rtsp_stream(payload: dict, request: Request):
    """Stop one sand-table RTSP camera, or all active sand-table cameras."""
    camera_id = payload.get("camera_id")
    if not camera_id:
        raise HTTPException(status_code=400, detail="camera_id is required")

    rtsp_manager = request.app.state.rtsp_manager
    if camera_id == "all":
        stopped = []
        for camera in SAND_TABLE_CAMERAS:
            device_id = f"rtsp_{camera['id']}"
            if rtsp_manager.stop_stream(device_id):
                stopped.append(camera["id"])
        return {"code": 200, "message": "success", "data": {"stopped": stopped}}

    device_id = f"rtsp_{camera_id}"
    success = rtsp_manager.stop_stream(device_id)
    if not success:
        return {"code": 404, "message": "No active stream for this camera", "data": None}

    return {"code": 200, "message": "success", "data": {"camera_id": camera_id}}


@router.get("/stream/rtsp/status")
async def get_rtsp_status(request: Request):
    """Get active RTSP stream status"""
    rtsp_manager = request.app.state.rtsp_manager
    return {"code": 200, "message": "success", "data": rtsp_manager.get_status()}


@router.get("/health")
async def health_check():
    return {"code": 200, "message": "healthy", "data": {"status": "OK", "timestamp": datetime.utcnow().isoformat()}}
