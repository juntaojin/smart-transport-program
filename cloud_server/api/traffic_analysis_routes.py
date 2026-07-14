"""Traffic analysis HTTP API."""

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cloud_server.services.traffic_analysis import analyze_traffic


router = APIRouter(prefix="/api/traffic-analysis")


class TrafficAnalysisRequest(BaseModel):
    camera_id: str = Field(min_length=1, max_length=100)
    lane_id: str = Field(min_length=1, max_length=100)
    capacity: int | None = Field(default=None, ge=1, le=10)
    frames: list[dict]


@router.post("")
async def create_traffic_analysis(payload: TrafficAnalysisRequest):
    if not payload.frames:
        return JSONResponse(status_code=400, content={"code": 400, "message": "缺少回放帧数据", "data": None})
    if len(payload.frames) > 200:
        return JSONResponse(status_code=400, content={"code": 400, "message": "回放帧数量不能超过 200", "data": None})
    try:
        result = await asyncio.to_thread(
            analyze_traffic,
            payload.frames,
            payload.camera_id,
            payload.lane_id,
            payload.capacity,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"code": 400, "message": str(exc), "data": None})
    return {"code": 200, "message": "success", "data": result}
