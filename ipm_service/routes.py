from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from loguru import logger
import numpy as np

from ipm_service.ipm_engine import compute_ipm, transform_points
from ipm_service.config_manager import (
    load_all_cameras,
    load_camera_lanes,
    load_lane_config,
    save_lane_config,
    delete_lane_config,
)

router = APIRouter(prefix="/api/ipm")


def ok(data=None):
    return {"code": 200, "message": "success", "data": data}


def err(code: int, message: str):
    return JSONResponse(
        status_code=code,
        content={"code": code, "message": message, "data": None},
    )


class CalibrateRequest(BaseModel):
    camera_id: str
    lane_id: str
    camera_points: list[list[float]]
    world_points: list[list[float]]


class TransformSingle(BaseModel):
    camera_id: str
    lane_id: str
    vehicles: list[list[float]]


@router.post("/calibrate")
async def calibrate(req: CalibrateRequest):
    camera_points = req.camera_points
    world_points = req.world_points

    if len(camera_points) < 4:
        return err(400, f"camera_points 必须各有恰好 4 个点，当前 {len(camera_points)} 个")
    if len(world_points) < 4:
        return err(400, f"world_points 必须各有恰好 4 个点，当前 {len(world_points)} 个")
    if len(camera_points) > 4:
        logger.warning(f"camera_points 超过 4 个点({len(camera_points)})，仅使用前 4 个")
        camera_points = camera_points[:4]
    if len(world_points) > 4:
        logger.warning(f"world_points 超过 4 个点({len(world_points)})，仅使用前 4 个")
        world_points = world_points[:4]

    try:
        H = compute_ipm(camera_points, world_points)
    except ValueError as e:
        return err(400, str(e))

    save_lane_config(req.camera_id, req.lane_id, camera_points, world_points, H)

    return ok({
        "camera_id": req.camera_id,
        "lane_id": req.lane_id,
        "homography_matrix": [[round(float(v), 8) for v in row] for row in H],
    })


@router.post("/transform")
async def transform(request: Request):
    body = await request.json()

    if "requests" in body:
        return await _transform_batch(body["requests"])

    return await _transform_single(body)


async def _transform_single(body: dict):
    camera_id = body.get("camera_id")
    lane_id = body.get("lane_id")
    vehicles = body.get("vehicles", [])

    if not camera_id or not lane_id:
        return err(400, "camera_id 和 lane_id 是必填字段")

    lane_cfg = load_lane_config(camera_id, lane_id)
    if lane_cfg is None:
        return err(404, f"标定数据不存在: {camera_id} / {lane_id}")

    H = np.array(lane_cfg["homography_matrix"], dtype=np.float64)
    transformed = transform_points(vehicles, H)

    return ok({"transformed": transformed})


async def _transform_batch(requests: list[dict]):
    results = []
    for item in requests:
        camera_id = item.get("camera_id", "")
        lane_id = item.get("lane_id", "")
        vehicles = item.get("vehicles", [])

        lane_cfg = load_lane_config(camera_id, lane_id)
        if lane_cfg is None:
            results.append({
                "camera_id": camera_id,
                "lane_id": lane_id,
                "transformed": None,
            })
            continue

        H = np.array(lane_cfg["homography_matrix"], dtype=np.float64)
        transformed = transform_points(vehicles, H)
        results.append({
            "camera_id": camera_id,
            "lane_id": lane_id,
            "transformed": transformed,
        })

    return ok({"results": results})


@router.get("/config")
async def list_configs():
    cameras = load_all_cameras()
    return ok({"cameras": cameras})


@router.get("/config/{camera_id}")
async def get_camera_config(camera_id: str):
    lanes = load_camera_lanes(camera_id)
    if lanes is None:
        return err(404, f"摄像头 {camera_id} 无标定数据")
    return ok({"camera_id": camera_id, "lanes": lanes})


@router.delete("/config/{camera_id}/{lane_id}")
async def delete_config(camera_id: str, lane_id: str):
    deleted = delete_lane_config(camera_id, lane_id)
    if not deleted:
        return err(404, f"标定数据不存在: {camera_id} / {lane_id}")
    return ok(None)
