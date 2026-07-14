import secrets
import time
import uuid
from datetime import datetime

from sqlalchemy import select

from cloud_server.database.connection import async_session
from cloud_server.database.orm_models import EdgeDevice, EdgeStreamRecord

CODE_TTL_SECONDS = 120
TOKEN_TTL_SECONDS = 300

pending_requests: dict[str, dict] = {}
stream_tokens: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def cleanup_edge_auth_state() -> None:
    now = _now()
    for request_id, item in list(pending_requests.items()):
        if item["expires_at_ts"] <= now:
            pending_requests.pop(request_id, None)
    for token, item in list(stream_tokens.items()):
        if item["expires_at_ts"] <= now:
            stream_tokens.pop(token, None)


def create_registration_request(device_info: dict, client_ip: str | None = None) -> dict:
    cleanup_edge_auth_state()
    edge_device_uid = device_info.get("edge_device_uid") or device_info["device_id"]
    stream_device_id = device_info.get("stream_device_id") or device_info.get("device_id") or edge_device_uid
    for request_id, item in list(pending_requests.items()):
        if item["device_id"] == edge_device_uid:
            pending_requests.pop(request_id, None)
    request_id = uuid.uuid4().hex
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at_ts = _now() + CODE_TTL_SECONDS
    item = {
        "request_id": request_id,
        "code": code,
        "device_id": edge_device_uid,
        "edge_device_uid": edge_device_uid,
        "stream_device_id": stream_device_id,
        "device_name": device_info.get("device_name") or edge_device_uid,
        "source_mode": device_info.get("source_mode") or "camera",
        "user_agent": device_info.get("user_agent") or "",
        "client_ip": client_ip or "",
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": datetime.utcfromtimestamp(expires_at_ts).isoformat(),
        "expires_at_ts": expires_at_ts,
    }
    pending_requests[request_id] = item
    return item


async def get_edge_device_status(device_id: str) -> dict:
    async with async_session() as db:
        result = await db.execute(select(EdgeDevice).where(EdgeDevice.device_id == device_id))
        device = result.scalar_one_or_none()
        if device is None:
            return {"device_id": device_id, "allowed": False, "registered": False}
        return {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "source_mode": device.source_mode,
            "last_ip": device.last_ip,
            "allowed": bool(device.allowed),
            "registered": True,
            "last_verified_at": device.last_verified_at.isoformat() if device.last_verified_at else None,
            "last_stream_at": device.last_stream_at.isoformat() if device.last_stream_at else None,
        }


def list_pending_requests() -> list[dict]:
    cleanup_edge_auth_state()
    return [
        {key: value for key, value in item.items() if key != "expires_at_ts"}
        for item in sorted(pending_requests.values(), key=lambda value: value["created_at"], reverse=True)
    ]


async def verify_registration_request(request_id: str, code: str) -> dict | None:
    cleanup_edge_auth_state()
    item = pending_requests.get(request_id)
    if not item or item["code"] != str(code).strip():
        return None

    token = uuid.uuid4().hex
    stream_tokens[token] = {
        "device_id": item["device_id"],
        "edge_device_uid": item["device_id"],
        "stream_device_id": item.get("stream_device_id") or item["device_id"],
        "device_name": item["device_name"],
        "source_mode": item["source_mode"],
        "client_ip": item["client_ip"],
        "expires_at_ts": _now() + TOKEN_TTL_SECONDS,
    }
    pending_requests.pop(request_id, None)

    async with async_session() as db:
        result = await db.execute(select(EdgeDevice).where(EdgeDevice.device_id == item["device_id"]))
        device = result.scalar_one_or_none()
        if device is None:
            device = EdgeDevice(device_id=item["device_id"])
            db.add(device)
        device.device_name = item["device_name"]
        device.source_mode = item["source_mode"]
        device.user_agent = item["user_agent"]
        device.last_ip = item["client_ip"]
        device.allowed = True
        device.last_verified_at = datetime.utcnow()
        await db.commit()

    return {
        "stream_token": token,
        "device_id": item["device_id"],
        "edge_device_uid": item["device_id"],
        "stream_device_id": item.get("stream_device_id") or item["device_id"],
        "device_name": item["device_name"],
        "source_mode": item["source_mode"],
        "expires_at": datetime.utcfromtimestamp(stream_tokens[token]["expires_at_ts"]).isoformat(),
    }


async def consume_stream_token(device_id: str, token: str | None) -> dict | None:
    cleanup_edge_auth_state()
    if not token:
        return None
    item = stream_tokens.pop(token, None)
    if not item or item.get("stream_device_id") != device_id:
        return None

    async with async_session() as db:
        result = await db.execute(select(EdgeDevice).where(EdgeDevice.device_id == item["edge_device_uid"]))
        device = result.scalar_one_or_none()
        if device is None or not device.allowed:
            return None
        device.last_stream_at = datetime.utcnow()
        await db.commit()

    return item


async def authorize_edge_stream(device_id: str, token: str | None, client_ip: str | None = None) -> dict | None:
    return await authorize_edge_stream_for_uid(device_id, token, None, client_ip)


async def authorize_edge_stream_for_uid(
    stream_device_id: str,
    token: str | None,
    edge_device_uid: str | None = None,
    client_ip: str | None = None,
) -> dict | None:
    token_info = await consume_stream_token(stream_device_id, token)
    if token_info is not None:
        return token_info
    if not edge_device_uid:
        return None

    async with async_session() as db:
        result = await db.execute(select(EdgeDevice).where(EdgeDevice.device_id == edge_device_uid))
        device = result.scalar_one_or_none()
        if device is None or not device.allowed:
            return None
        device.last_ip = client_ip or device.last_ip
        device.last_stream_at = datetime.utcnow()
        await db.commit()
        return {
            "device_id": device.device_id,
            "edge_device_uid": device.device_id,
            "stream_device_id": stream_device_id,
            "device_name": device.device_name or device.device_id,
            "source_mode": device.source_mode or "camera",
            "client_ip": client_ip or device.last_ip or "",
        }


async def create_stream_record(device_id: str, token_info: dict, client_ip: str | None = None) -> int:
    async with async_session() as db:
        record = EdgeStreamRecord(
            device_id=token_info.get("edge_device_uid") or token_info.get("device_id") or device_id,
            device_name=token_info.get("device_name") or token_info.get("edge_device_uid") or device_id,
            source_mode=token_info.get("source_mode") or "camera",
            client_ip=client_ip or token_info.get("client_ip") or "",
            status="streaming",
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return int(record.id)


async def finish_stream_record(record_id: int | None, frames_received: int, status: str = "ended") -> None:
    if record_id is None:
        return
    async with async_session() as db:
        record = await db.get(EdgeStreamRecord, record_id)
        if record is None:
            return
        record.ended_at = datetime.utcnow()
        record.frames_received = frames_received
        record.status = status
        await db.commit()
