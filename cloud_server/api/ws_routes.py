import time
import cv2
import numpy as np
import base64
import json
import asyncio
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
        # Broadcast JSON message
        payload = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                # Connection might be dead
                pass

dashboard_manager = ConnectionManager()
active_devices = {}  # Keep track of active streaming devices {device_id: last_seen}

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


# --- Stream WebSocket (Edge -> Cloud) ---
@router.websocket("/stream/{device_id}")
async def receive_stream(websocket: WebSocket, device_id: str):
    await websocket.accept()
    logger.info(f"Edge streaming device connected: {device_id}")
    active_devices[device_id] = time.time()
    
    pipeline = websocket.app.state.pipeline
    
    try:
        while True:
            # Receive binary frame (JPEG)
            data = await websocket.receive_bytes()
            active_devices[device_id] = time.time()
            
            # Check if any pipeline node is enabled
            has_active_nodes = any(node.enabled for node in pipeline.nodes.values())
            has_parking_zones = len(NO_PARKING_ZONES) > 0
            
            if not has_active_nodes and not has_parking_zones:
                # Fast path: forward raw JPEG without decode-reencode cycle
                img_b64 = base64.b64encode(data).decode('utf-8')
                fps = calculate_fps()
                
                from cloud_server.utils.system_info import get_detailed_metrics
                payload = {
                    "device_id": device_id,
                    "timestamp": time.time(),
                    "fps": fps,
                    "congestion_level": "low",
                    "image": f"data:image/jpeg;base64,{img_b64}",
                    "vehicles": [],
                    "violations": [],
                    "anomalies": [],
                    "system_metrics": get_detailed_metrics()
                }
                await dashboard_manager.broadcast(payload)
                continue
            
            # Decode JPEG to OpenCV image
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                continue
                
            # Create computation context
            context = FrameContext(
                frame_data=frame,
                timestamp=time.time(),
                device_id=device_id
            )
            
            # Run inference pipeline
            context = pipeline.execute(context)
            
            # Draw annotations on the frame
            annotated = annotate_frame(frame, context.properties)
            
            # Re-encode to JPEG
            success, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not success:
                continue
                
            # Base64 encode for simple websocket transport to browser
            img_b64 = base64.b64encode(buffer).decode('utf-8')
            
            # Calculate metrics
            fps = calculate_fps()
            
            # Calculate congestion level based on vehicle count
            v_count = len(context.properties.get("vehicle_boxes", []))
            congestion = "low"
            if v_count > CONGESTION_HIGH:
                congestion = "high"
            elif v_count >= CONGESTION_MEDIUM:
                congestion = "medium"

            # Query real-time hardware metrics
            from cloud_server.utils.system_info import get_detailed_metrics
            sys_metrics = get_detailed_metrics()

            # Construct payload
            payload = {
                "device_id": device_id,
                "timestamp": context.timestamp,
                "fps": fps,
                "congestion_level": congestion,
                "image": f"data:image/jpeg;base64,{img_b64}",
                "vehicles": [
                    {
                        "id": context.properties["track_ids"][i] if i < len(context.properties.get("track_ids", [])) else None,
                        "class": context.properties["vehicle_classes"][i] if i < len(context.properties.get("vehicle_classes", [])) else "vehicle",
                        "box": [float(c) for c in box],
                        "plate": context.properties["plate_numbers"][i] if i < len(context.properties.get("plate_numbers", [])) else ""
                    } for i, box in enumerate(context.properties.get("vehicle_boxes", []))
                ],
                "violations": context.properties.get("violations", []),
                "anomalies": context.properties.get("road_anomalies", []),
                "system_metrics": sys_metrics
            }
            
            # Save aggregated metrics to DB asynchronously
            asyncio.create_task(save_aggregated_stats(context.properties, device_id))
            
            # Broadcast to Dashboard clients
            await dashboard_manager.broadcast(payload)
            
    except WebSocketDisconnect:
        logger.info(f"Edge streaming device disconnected: {device_id}")
        active_devices.pop(device_id, None)
    except Exception as e:
        logger.error(f"Error on edge stream WebSocket {device_id}: {e}")
        active_devices.pop(device_id, None)


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
