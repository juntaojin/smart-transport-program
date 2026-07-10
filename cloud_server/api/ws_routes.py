import time
import cv2
import numpy as np
import json
import asyncio
import torch
from torchvision.io import decode_jpeg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_server.pipeline.context import FrameContext
from cloud_server.database.connection import async_session
from cloud_server.database.orm_models import (
    PlateRecord, VehicleStat, ParkingViolation, RoadAnomaly, SystemMetric
)
from cloud_server.config import (
    VIDEO_FPS, CONGESTION_HIGH, CONGESTION_MEDIUM, CONGESTION_LOW, NO_PARKING_ZONES, JPEG_QUALITY
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

    async def broadcast_bytes(self, data: bytes):
        for connection in self.active_connections:
            try:
                await connection.send_bytes(data)
            except Exception:
                pass

dashboard_manager = ConnectionManager()
active_devices = {}  # Keep track of active streaming devices {device_id: last_seen}
frame_counters = {}  # Per-device frame counter for key frame strategy
plate_db = {}  # Per-device plate history: {device_id: {track_id: plate_string}}
device_busy: dict[str, bool] = {}  # Per-device processing guard, skip frame if busy

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
        if i < len(track_ids):
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
            
        # B. Store Plates (Only log newly recognized plates, limit duplicates within 15s)
        plates = properties.get("plate_numbers", [])
        for plate in plates:
            if plate:
                # Deduplicate plates in memory
                if plate not in registered_plates or (current_time - registered_plates[plate] > 15.0):
                    registered_plates[plate] = current_time
                    
                    # Read whitelist file to see if plate is whitelisted
                    whitelist_file = json.loads(open("./data/whitelist.json", "r").read() if open("./data/whitelist.json", "r") else "[]")
                    is_white = plate in whitelist_file
                    
                    record = PlateRecord(plate_number=plate, is_whitelisted=is_white)
                    db.add(record)
                    logger.info(f"DB Log: Recognized plate {plate} (whitelisted={is_white})")

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


def _process_frame(pipeline, frame, mode, device_id, fc):
    """Run pipeline + annotate + encode in thread (blocks, don't call from async)"""
    context = FrameContext(
        frame_data=frame,
        timestamp=time.time(),
        device_id=device_id,
    )
    context = pipeline.execute(context, mode=mode)
    annotated = annotate_frame(frame, context.properties)
    success, buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not success:
        return None, None
    return context, buf


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
    await websocket.accept()
    logger.info(f"Edge streaming device connected: {device_id}")
    active_devices[device_id] = time.time()
    
    pipeline = websocket.app.state.pipeline
    last_broadcast_time = 0.0
    BROADCAST_INTERVAL = 1.0 / 10  # max 10 fps broadcast
    
    try:
        frame_no = 0
        while True:
            data = await websocket.receive_bytes()
            active_devices[device_id] = time.time()
            frame_no += 1
            
            # Frame rate throttle: skip if too soon since last broadcast
            now = time.time()
            if now - last_broadcast_time < BROADCAST_INTERVAL:
                continue
            
            has_active_nodes = any(node.enabled for node in pipeline.nodes.values())
            has_parking_zones = len(NO_PARKING_ZONES) > 0
            
            if not has_active_nodes and not has_parking_zones:
                from cloud_server.utils.system_info import get_detailed_metrics
                payload = {
                    "device_id": device_id,
                    "timestamp": time.time(),
                    "fps": calculate_fps(),
                    "congestion_level": "low",
                    "vehicles": [],
                    "violations": [],
                    "anomalies": [],
                    "system_metrics": get_detailed_metrics()
                }
                asyncio.create_task(dashboard_manager.broadcast_bytes(data))
                asyncio.create_task(dashboard_manager.broadcast(payload))
                last_broadcast_time = time.time()
                
                if frame_no % 30 == 0:
                    logger.info(
                        f"[Timing {device_id}] frame #{frame_no} (fast) | "
                    f"payload img: {len(img_b64)/1024:.0f}KB" if img_b64 else "no viewers"
                    )
                continue

            # Skip if still processing previous frame
            if device_busy.get(device_id, False):
                if frame_no % 60 == 0:
                    logger.warning(f"[{device_id}] Skipping frame #{frame_no}: pipeline busy")
                continue
            
            device_busy[device_id] = True
            try:
                # GPU JPEG decode
                try:
                    tensor = decode_jpeg(
                        torch.frombuffer(bytearray(data), dtype=torch.uint8),
                        device='cuda'
                    )
                    frame = tensor[[2, 1, 0], :, :].permute(1, 2, 0).contiguous().cpu().numpy()
                except Exception:
                    nparr = np.frombuffer(data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is None:
                    device_busy[device_id] = False
                    continue

                frame_counters[device_id] = frame_counters.get(device_id, 0) + 1
                fc = frame_counters[device_id]
                mode = "full" if fc % 15 == 0 else "track"

                has_viewers = len(dashboard_manager.active_connections) > 0
                if has_viewers:
                    context, annotated_buffer = await asyncio.to_thread(
                        _process_frame, pipeline, frame, mode, device_id, fc
                    )
                else:
                    context = await asyncio.to_thread(
                        _process_pipeline_only, pipeline, frame, mode, device_id, fc
                    )
                    annotated_buffer = None
            finally:
                device_busy[device_id] = False

            if context is None:
                continue

            # Persist plates by track_id
            if mode == "full":
                track_ids = context.properties.get("track_ids", [])
                plates = context.properties.get("plate_numbers", [])
                if device_id not in plate_db:
                    plate_db[device_id] = {}
                for tid, plate in zip(track_ids, plates):
                    if plate:
                        plate_db[device_id][tid] = plate

            # Build vehicle list with persisted plates and world coordinates
            dev_plates = plate_db.get(device_id, {})
            world_coords = context.properties.get("world_coords", {})
            track_ids = context.properties.get("track_ids", [])
            vehicle_boxes = context.properties.get("vehicle_boxes", [])
            vehicle_classes = context.properties.get("vehicle_classes", [])
            vehicles_payload = []
            for i, box in enumerate(vehicle_boxes):
                tid = track_ids[i] if i < len(track_ids) else None
                cls_name = vehicle_classes[i] if i < len(vehicle_classes) else "vehicle"
                plate = dev_plates.get(tid, "") if tid is not None else ""
                wc = world_coords.get(tid, None)
                vehicles_payload.append({
                    "id": tid,
                    "class": cls_name,
                    "box": [float(c) for c in box],
                    "plate": plate,
                    "world_coord": wc,
                })
                
            fps = calculate_fps()
            
            v_count = len(context.properties.get("vehicle_boxes", []))
            congestion = "low"
            if v_count > CONGESTION_HIGH:
                congestion = "high"
            elif v_count >= CONGESTION_MEDIUM:
                congestion = "medium"

            from cloud_server.utils.system_info import get_detailed_metrics
            sys_metrics = get_detailed_metrics()

            payload = {
                "device_id": device_id,
                "timestamp": context.timestamp,
                "fps": fps,
                "congestion_level": congestion,
                "vehicles": vehicles_payload,
                "violations": context.properties.get("violations", []),
                "anomalies": context.properties.get("road_anomalies", []),
                "system_metrics": sys_metrics
            }
            
            asyncio.create_task(save_aggregated_stats(context.properties, device_id))
            if has_viewers and annotated_buffer is not None:
                asyncio.create_task(dashboard_manager.broadcast_bytes(bytes(annotated_buffer)))
                asyncio.create_task(dashboard_manager.broadcast(payload))
            last_broadcast_time = time.time()
            
            if fc % 30 == 0:
                logger.info(
                    f"[Timing {device_id}] frame #{fc} mode={mode}"
                )

    except WebSocketDisconnect:
        logger.info(f"Edge streaming device disconnected: {device_id}")
        active_devices.pop(device_id, None)
        frame_counters.pop(device_id, None)
    except Exception as e:
        logger.error(f"Error on edge stream WebSocket {device_id}: {e}")
        active_devices.pop(device_id, None)
        frame_counters.pop(device_id, None)


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
