import time
import cv2
import base64
import json
import threading
import asyncio
from loguru import logger

from cloud_server.pipeline.context import FrameContext
from cloud_server.api.ws_routes import dashboard_manager, calculate_fps, annotate_frame, active_devices
from cloud_server.config import CONGESTION_HIGH, CONGESTION_MEDIUM, NO_PARKING_ZONES, JPEG_QUALITY

SAND_TABLE_CAMERAS = [
    {"id": "live1", "name": "桥面", "url": "rtsp://10.126.59.120:8554/live/live1"},
    {"id": "live2", "name": "停车场出口", "url": "rtsp://10.126.59.120:8554/live/live2"},
    {"id": "live3", "name": "行人检测", "url": "rtsp://10.126.59.120:8554/live/live3"},
    {"id": "live4", "name": "消防车识别", "url": "rtsp://10.126.59.120:8554/live/live4"},
    {"id": "live5", "name": "桥出口", "url": "rtsp://10.126.59.120:8554/live/live5"},
    {"id": "live6", "name": "桥入口", "url": "rtsp://10.126.59.120:8554/live/live6"},
    {"id": "live7", "name": "道路2", "url": "rtsp://10.126.59.120:8554/live/live7"},
    {"id": "live8", "name": "隧道(事故识别)", "url": "rtsp://10.126.59.120:8554/live/live8"},
    {"id": "live9", "name": "隧道(车辆数量)", "url": "rtsp://10.126.59.120:8554/live/live9"},
    {"id": "live10", "name": "道路3", "url": "rtsp://10.126.59.120:8554/live/live10"},
    {"id": "live11", "name": "停车场入口", "url": "rtsp://10.126.59.120:8554/live/live11"},
    {"id": "live12", "name": "道路1", "url": "rtsp://10.126.59.120:8554/live/live12"},
]


class RTSPStreamManager:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.active_streams = {}
        self._lock = threading.Lock()
        self._loop = asyncio.get_event_loop()
        self._frame_counters = {}

    def start_stream(self, device_id, rtsp_url):
        with self._lock:
            if device_id in self.active_streams:
                logger.warning(f"RTSP stream already active: {device_id}")
                return False
            thread = threading.Thread(
                target=self._stream_worker, args=(device_id, rtsp_url), daemon=True
            )
            self.active_streams[device_id] = {"thread": thread, "url": rtsp_url, "active": True}
            thread.start()
            logger.info(f"RTSP stream started: {device_id} -> {rtsp_url}")
            return True

    def stop_stream(self, device_id):
        with self._lock:
            if device_id not in self.active_streams:
                return False
            self.active_streams[device_id]["active"] = False
            logger.info(f"RTSP stream stopping: {device_id}")
            return True

    def get_status(self):
        with self._lock:
            return {
                did: {"url": info["url"], "active": info["active"]}
                for did, info in self.active_streams.items()
            }

    def cleanup(self):
        with self._lock:
            for info in self.active_streams.values():
                info["active"] = False
            logger.info("All RTSP streams signaled to stop")

    def _broadcast(self, payload):
        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                dashboard_manager.broadcast(payload), self._loop
            )

    def _open_capture(self, rtsp_url):
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _stream_worker(self, device_id, rtsp_url):
        cap = self._open_capture(rtsp_url)
        if cap is None:
            logger.error(f"Failed to open RTSP stream: {rtsp_url}")
            with self._lock:
                self.active_streams.pop(device_id, None)
            return

        logger.info(f"RTSP capture opened: {device_id}")
        reconnect_count = 0

        try:
            while True:
                with self._lock:
                    if device_id not in self.active_streams or not self.active_streams[device_id]["active"]:
                        break

                ret, frame = cap.read()
                if not ret:
                    logger.warning(f"RTSP frame read failed for {device_id}, reconnecting...")
                    cap.release()
                    reconnect_count += 1
                    time.sleep(1)
                    cap = self._open_capture(rtsp_url)
                    if cap is None:
                        logger.error(f"RTSP reconnect failed for {device_id} (attempt {reconnect_count})")
                        time.sleep(3)
                    continue

                reconnect_count = 0
                active_devices[device_id] = time.time()

                try:
                    frame = cv2.resize(frame, (1280, 720))

                    has_active_nodes = any(node.enabled for node in self.pipeline.nodes.values())
                    has_parking_zones = len(NO_PARKING_ZONES) > 0

                    if not has_active_nodes and not has_parking_zones:
                        success, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                        if not success:
                            continue
                        img_b64 = base64.b64encode(buffer).decode('utf-8')
                        payload = {
                            "device_id": device_id,
                            "timestamp": time.time(),
                            "fps": calculate_fps(),
                            "congestion_level": "low",
                            "image": f"data:image/jpeg;base64,{img_b64}",
                            "vehicles": [],
                            "violations": [],
                            "anomalies": [],
                            "system_metrics": self._get_metrics()
                        }
                    else:
                        context = FrameContext(frame_data=frame, timestamp=time.time(), device_id=device_id)
                        self._frame_counters[device_id] = self._frame_counters.get(device_id, 0) + 1
                        fc = self._frame_counters[device_id]
                        mode = "full" if fc % 15 == 0 else "track"
                        context = self.pipeline.execute(context, mode=mode)
                        annotated = annotate_frame(frame, context.properties)
                        success, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                        if not success:
                            continue
                        img_b64 = base64.b64encode(buffer).decode('utf-8')
                        fps_val = calculate_fps()

                        v_count = len(context.properties.get("vehicle_boxes", []))
                        congestion = "low"
                        if v_count > CONGESTION_HIGH:
                            congestion = "high"
                        elif v_count >= CONGESTION_MEDIUM:
                            congestion = "medium"

                        payload = {
                            "device_id": device_id,
                            "timestamp": context.timestamp,
                            "fps": fps_val,
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
                            "system_metrics": self._get_metrics()
                        }

                    self._broadcast(payload)

                except Exception as e:
                    logger.error(f"RTSP frame processing error for {device_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"RTSP stream worker fatal error for {device_id}: {e}")
        finally:
            cap.release()
            active_devices.pop(device_id, None)
            with self._lock:
                self.active_streams.pop(device_id, None)
            logger.info(f"RTSP stream worker exited: {device_id}")

    _last_metrics_time = 0
    _cached_metrics = None

    def _get_metrics(self):
        now = time.time()
        if self._cached_metrics is None or now - self._last_metrics_time > 2.0:
            from cloud_server.utils.system_info import get_detailed_metrics
            self._cached_metrics = get_detailed_metrics()
            self._last_metrics_time = now
        return self._cached_metrics
