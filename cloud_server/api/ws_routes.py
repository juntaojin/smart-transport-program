import time
import cv2
import numpy as np
import json
import asyncio
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_server.pipeline.context import FrameContext
from model_api import is_valid_china_plate, normalize_plate_number, reset_anomaly_state
from cloud_server.database.connection import async_session
from cloud_server.database.orm_models import (
    PlateRecord, VehicleStat, ParkingViolation, RoadAnomaly, SystemMetric
)
from cloud_server.config import (
    CONGESTION_HIGH, CONGESTION_MEDIUM, DATA_DIR,
)

router = APIRouter(prefix="/ws")

# Store active websocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        payload = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                pass

    async def broadcast_bytes(self, data: bytes, device_id: str | None = None):
        payload = data
        if device_id:
            header = f"STJ1 {device_id}\n".encode("utf-8")
            payload = header + data
        for connection in self.active_connections:
            try:
                await connection.send_bytes(payload)
            except Exception:
                pass

dashboard_manager = ConnectionManager()
active_devices = {}  # Keep track of active streaming devices {device_id: last_seen}
frame_counters = {}  # Per-device frame counter for key frame strategy
plate_db = {}  # Per-device plate history: {device_id: {track_id: plate_string}}

# FPS and throughput calculation helpers
frame_times = []
def calculate_fps():
    current = time.time()
    frame_times.append(current)
    # Only keep frame times from last 2 seconds
    while frame_times and frame_times[0] < current - 2.0:
        frame_times.pop(0)
    if len(frame_times) > 1:
        return len(frame_times) / (frame_times[-1] - frame_times[0])
    return 0.0

# Rate limits to prevent DB flooding
last_stat_time = 0.0
last_system_metric_time = 0.0
registered_plates = {}  # {plate_number: last_logged_timestamp}
active_violations_db = {}  # {vehicle_id: db_id}

# Colors mapping in BGR
COLOR_MAP = {
    "car": (0, 255, 0),        # Green
    "truck": (255, 0, 0),      # Blue
    "bus": (0, 0, 255),        # Red
    "motorcycle": (255, 255, 0), # Cyan
    "bicycle": (255, 0, 255),   # Purple
    "vehicle": (200, 200, 200) # Gray
}

def annotate_frame(frame, properties):
    """Draw bounding boxes, tracking IDs, plates and anomalies on frame"""
    h_img, w_img = frame.shape[:2]

    # 1. Draw vehicles (bounding boxes, tracking IDs, plates)
    boxes = properties.get("vehicle_boxes", [])
    classes = properties.get("vehicle_classes", [])
    track_ids = properties.get("track_ids", [])
    plates = properties.get("plate_numbers", [])
    
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = [int(c) for c in box]
        cls = classes[i] if i < len(classes) else "vehicle"
        color = COLOR_MAP.get(cls, COLOR_MAP["vehicle"])
        
        # Draw box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        
        # Label text
        label_parts = []
        if i < len(track_ids) and track_ids[i] is not None:
            label_parts.append(f"ID:{track_ids[i]}")
        label_parts.append(cls)
        
        if i < len(plates) and plates[i]:
            label_parts.append(f"[{plates[i]}]")
            
        label = " ".join(label_parts)
        cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    # 2. Draw anomalies
    anomalies = properties.get("road_anomalies", [])
    for a in anomalies:
        abox = [int(c) for c in a["box"]]
        conf = a["confidence"]
        lbl = a["label"]
        color = (0, 0, 255) if conf > 0.5 else (0, 165, 255)  # Red if high conf, Orange if low
        
        # Draw dotted bounding box
        cv2.rectangle(frame, (abox[0], abox[1]), (abox[2], abox[3]), color, 2)
        cv2.putText(frame, f"ANOMALY: {lbl} ({conf:.2f})", (abox[0], abox[1] - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    return frame


async def save_recognized_plates(plates):
    """Persist valid OCR results from either edge or RTSP streams."""
    current_time = time.time()
    valid_plates = []
    for raw_plate in plates:
        plate = normalize_plate_number(raw_plate)
        if not is_valid_china_plate(plate):
            continue
        if plate not in registered_plates or current_time - registered_plates[plate] > 15.0:
            registered_plates[plate] = current_time
            valid_plates.append(plate)

    if not valid_plates:
        return

    whitelist_path = os.path.join(DATA_DIR, "whitelist.json")
    try:
        with open(whitelist_path, "r", encoding="utf-8") as whitelist_file:
            whitelist = set(json.load(whitelist_file))
    except (OSError, json.JSONDecodeError):
        whitelist = set()
    async with async_session() as db:
        for plate in valid_plates:
            is_white = plate in whitelist
            db.add(PlateRecord(plate_number=plate, is_whitelisted=is_white))
            logger.info(f"DB Log: Recognized plate {plate} (whitelisted={is_white})")
        await db.commit()


async def save_aggregated_stats(properties, device_id):
    """Aggregate real-time data and periodically log into sqlite database"""
    global last_stat_time, last_system_metric_time
    current_time = time.time()
    
    # Run DB tasks asynchronously
    async with async_session() as db:
        # A. Store Vehicle Density (Once every 5 seconds)
        if current_time - last_stat_time >= 5.0:
            last_stat_time = current_time
            boxes = properties.get("vehicle_boxes", [])
            count = len(boxes)
            
            # Determine congestion level
            if count > CONGESTION_HIGH:
                level = "high"
            elif count >= CONGESTION_MEDIUM:
                level = "medium"
            else:
                level = "low"
                
            stat = VehicleStat(zone_name="Main Road", vehicle_count=count, congestion_level=level)
            db.add(stat)
            
        # B. Plate records are persisted by the shared edge/RTSP helper below.

        # C. Store Violations (Log violation trigger and duration update)
        violations = properties.get("violations", [])
        active_ids = set()
        for v in violations:
            vid = str(v["vehicle_id"])
            active_ids.add(vid)
            duration = v["duration"]
            
            if vid not in active_violations_db:
                # Insert new violation
                v_record = ParkingViolation(
                    vehicle_id=vid,
                    zone_name=v["zone_name"],
                    parking_duration=duration,
                    alert_triggered=True,
                    start_time=datetime.utcnow()
                )
                db.add(v_record)
                await db.flush()  # populate ID
                active_violations_db[vid] = v_record.id
                logger.info(f"DB Log: Violation start for vehicle {vid} in {v['zone_name']}")
            else:
                # Update violation duration in existing record
                db_id = active_violations_db[vid]
                v_record = await db.get(ParkingViolation, db_id)
                if v_record:
                    v_record.parking_duration = duration
                    v_record.end_time = datetime.utcnow()
                    db.add(v_record)
                    
        # Clean up ended violations
        ended_ids = [vid for vid in active_violations_db if vid not in active_ids]
        for vid in ended_ids:
            active_violations_db.pop(vid, None)

        # D. Store Road Anomalies (Rate-limit to once per type/location to avoid flooding)
        anomalies = properties.get("road_anomalies", [])
        for a in anomalies:
            if a["confidence"] > 0.4:
                # Add to DB
                anom_record = RoadAnomaly(
                    anomaly_type=a["label"],
                    confidence=a["confidence"],
                    location_x=(a["box"][0] + a["box"][2]) / 2.0,
                    location_y=a["box"][3]
                )
                db.add(anom_record)
                logger.warning(f"DB Log: Road anomaly logged: {a['label']}")

        # E. System resource logging (Once every 10 seconds)
        if current_time - last_system_metric_time >= 10.0:
            last_system_metric_time = current_time
            from cloud_server.utils.system_info import get_detailed_metrics
            metrics = get_detailed_metrics()
            
            metric = SystemMetric(
                cpu_usage=metrics["cpu"]["percent"],
                gpu_usage=metrics["gpu"]["load"] if metrics["gpu"] else None,
                memory_usage=metrics["memory"]["percent"],
                disk_usage=metrics["disk"]["percent"],
                video_fps=calculate_fps(),
                active_devices=len(active_devices)
            )
            db.add(metric)
            
        await db.commit()

    await save_recognized_plates(properties.get("plate_numbers", []))


def _process_pipeline_only(pipeline, frame, mode, device_id, fc):
    """Run pipeline only, skip annotation/encode if no viewers"""
    context = FrameContext(
        frame_data=frame,
        timestamp=time.time(),
        device_id=device_id,
    )
    context = pipeline.execute(context, mode=mode)
    return context


# --- Stream WebSocket (Edge -> Cloud) ---
@router.websocket("/stream/{device_id}")
async def receive_stream(websocket: WebSocket, device_id: str):
    """Receive edge JPEGs without coupling video delivery to AI latency."""
    await websocket.accept()
    logger.info(f"Edge streaming device connected: {device_id}")
    reset_anomaly_state(device_id)
    active_devices[device_id] = time.time()

    pipeline = websocket.app.state.pipeline
    inference_event = asyncio.Event()
    inference_state = {
        "latest_jpeg": None,
        "latest_context": None,
        "stopping": False,
        "submitted": frame_counters.get(device_id, 0),
        "completed": 0,
        "last_persist_time": 0.0,
    }

    def build_payload(context):
        properties = context.properties if context is not None else {}
        dev_plates = plate_db.get(device_id, {})
        track_ids = properties.get("track_ids", [])
        boxes = properties.get("vehicle_boxes", [])
        classes = properties.get("vehicle_classes", [])
        world_coords = properties.get("world_coords", {})
        vehicles = []
        for index, box in enumerate(boxes):
            track_id = track_ids[index] if index < len(track_ids) else None
            vehicles.append({
                "id": track_id,
                "class": classes[index] if index < len(classes) else "vehicle",
                "box": [float(value) for value in box],
                "plate": dev_plates.get(track_id, "") if track_id is not None else "",
                "world_coord": world_coords.get(track_id),
            })

        vehicle_count = len(boxes)
        congestion = "high" if vehicle_count > CONGESTION_HIGH else (
            "medium" if vehicle_count >= CONGESTION_MEDIUM else "low"
        )
        from cloud_server.utils.system_info import get_detailed_metrics
        return {
            "device_id": device_id,
            "timestamp": context.timestamp if context is not None else time.time(),
            "fps": calculate_fps(),
            "congestion_level": congestion,
            "vehicles": vehicles,
            "violations": properties.get("violations", []),
            "anomalies": properties.get("road_anomalies", []),
            "system_metrics": get_detailed_metrics(),
        }

    def process_jpeg(jpeg_data, mode):
        frame = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        return _process_pipeline_only(pipeline, frame, mode, device_id, 0)

    async def inference_worker():
        while not inference_state["stopping"]:
            await inference_event.wait()
            inference_event.clear()
            jpeg_data = inference_state["latest_jpeg"]
            inference_state["latest_jpeg"] = None
            if jpeg_data is None or inference_state["stopping"]:
                continue

            inference_state["submitted"] += 1
            inference_number = inference_state["submitted"]
            mode = "full" if inference_number % 15 == 0 else "track"
            context = await asyncio.to_thread(process_jpeg, jpeg_data, mode)
            if context is None:
                continue

            inference_state["latest_context"] = context
            inference_state["completed"] += 1
            frame_counters[device_id] = inference_number

            if mode == "full":
                track_ids = context.properties.get("track_ids", [])
                plates = context.properties.get("plate_numbers", [])
                device_plates = plate_db.setdefault(device_id, {})
                active_ids = {track_id for track_id in track_ids if track_id is not None}
                for stale_id in set(device_plates) - active_ids:
                    device_plates.pop(stale_id, None)
                for track_id, plate in zip(track_ids, plates):
                    if plate:
                        device_plates[track_id] = plate
                asyncio.create_task(save_recognized_plates(plates))

            now = time.monotonic()
            if now - inference_state["last_persist_time"] >= 1.0:
                inference_state["last_persist_time"] = now
                asyncio.create_task(save_aggregated_stats(context.properties, device_id))

    worker_task = asyncio.create_task(inference_worker())
    stats_started_at = time.monotonic()
    received_count = 0
    broadcast_count = 0
    previous_completed = 0

    try:
        while True:
            data = await websocket.receive_bytes()
            active_devices[device_id] = time.time()
            received_count += 1


            has_active_nodes = any(node.enabled for node in pipeline.nodes.values())
            if has_active_nodes:
                # Keep one pending frame: newer input replaces stale work.
                inference_state["latest_jpeg"] = data
                inference_event.set()
            else:
                inference_state["latest_context"] = None

            payload = build_payload(inference_state["latest_context"])
            asyncio.create_task(dashboard_manager.broadcast_bytes(data, device_id))
            asyncio.create_task(dashboard_manager.broadcast(payload))
            broadcast_count += 1

            stats_elapsed = time.monotonic() - stats_started_at
            if stats_elapsed >= 5.0:
                completed = inference_state["completed"]
                logger.info(
                    f"[Edge Stats {device_id}] receive={received_count / stats_elapsed:.1f} fps, "
                    f"broadcast={broadcast_count / stats_elapsed:.1f} fps, "
                    f"inference={(completed - previous_completed) / stats_elapsed:.1f} fps"
                )
                stats_started_at = time.monotonic()
                received_count = 0
                broadcast_count = 0
                previous_completed = completed

    except WebSocketDisconnect:
        logger.info(f"Edge streaming device disconnected: {device_id}")
    except Exception as exc:
        logger.error(f"Error on edge stream WebSocket {device_id}: {exc}")
    finally:
        active_devices.pop(device_id, None)
        frame_counters.pop(device_id, None)
        inference_state["stopping"] = True
        inference_state["latest_jpeg"] = None
        inference_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await dashboard_manager.broadcast({
            "type": "stream_status",
            "status": "stopped",
            "device_id": device_id,
        })

# --- Dashboard WebSocket (Cloud -> Frontend Cockpit) ---
@router.websocket("/dashboard")
async def dashboard_socket(websocket: WebSocket):
    await dashboard_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client might send heartbeats
            data = await websocket.receive_text()
            # Echo heartbeat or ignore
            await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        dashboard_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Error on dashboard WebSocket: {e}")
        dashboard_manager.disconnect(websocket)
