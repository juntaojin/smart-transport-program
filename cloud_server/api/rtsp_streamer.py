import time
import cv2
import json
import threading
import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from loguru import logger

from cloud_server.pipeline.context import FrameContext
from cloud_server.api.ws_routes import dashboard_manager, calculate_fps, active_devices
from cloud_server.config import (
    CONGESTION_HIGH,
    CONGESTION_MEDIUM,
    RTSP_BROADCAST_FPS,
    RTSP_MJPEG_QSCALE,
    VIDEO_FRAME_HEIGHT,
    VIDEO_FRAME_WIDTH,
)

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
        self._plate_db = {}

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

    def _broadcast_bytes(self, jpeg_bytes):
        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                dashboard_manager.broadcast_bytes(jpeg_bytes), self._loop
            )

    def _open_ffmpeg(self, rtsp_url):
        """启动ffmpeg子进程，从RTSP拉流输出MJPEG到stdout"""
        try:
            proc = subprocess.Popen(
                ['ffmpeg', '-rtsp_transport', 'tcp',
                 '-i', rtsp_url,
                 '-vf', f'scale={VIDEO_FRAME_WIDTH}:{VIDEO_FRAME_HEIGHT}',
                 '-q:v', str(RTSP_MJPEG_QSCALE),
                 '-f', 'image2pipe', '-vcodec', 'mjpeg',
                 '-an', '-'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            return proc
        except FileNotFoundError:
            logger.error("ffmpeg not found. Install ffmpeg or add to PATH.")
            return None

    def _execute_pipeline(self, frame, device_id, frame_count):
        mode = "full" if frame_count % 15 == 0 else "track"
        context = FrameContext(
            frame_data=frame,
            timestamp=time.time(),
            device_id=device_id,
        )
        return mode, self.pipeline.execute(context, mode=mode)

    def _update_plate_cache(self, device_id, mode, context):
        if mode != "full":
            return
        track_ids = context.properties.get("track_ids", [])
        plates = context.properties.get("plate_numbers", [])
        device_plates = self._plate_db.setdefault(device_id, {})
        active_track_ids = {track_id for track_id in track_ids if track_id is not None}
        for stale_track_id in set(device_plates) - active_track_ids:
            device_plates.pop(stale_track_id, None)
        for track_id, plate in zip(track_ids, plates):
            if plate:
                device_plates[track_id] = plate

    def _build_payload(self, device_id, context):
        if context is None:
            return {
                "device_id": device_id,
                "timestamp": time.time(),
                "fps": calculate_fps(),
                "congestion_level": "low",
                "vehicles": [],
                "violations": [],
                "anomalies": [],
                "system_metrics": self._get_metrics(),
            }

        properties = context.properties
        device_plates = self._plate_db.get(device_id, {})
        track_ids = properties.get("track_ids", [])
        boxes = properties.get("vehicle_boxes", [])
        classes = properties.get("vehicle_classes", [])
        vehicles = []
        for index, box in enumerate(boxes):
            track_id = track_ids[index] if index < len(track_ids) else None
            class_name = classes[index] if index < len(classes) else "vehicle"
            vehicles.append({
                "id": track_id,
                "class": class_name,
                "box": [float(value) for value in box],
                "plate": device_plates.get(track_id, "") if track_id is not None else "",
            })

        vehicle_count = len(boxes)
        congestion = "low"
        if vehicle_count > CONGESTION_HIGH:
            congestion = "high"
        elif vehicle_count >= CONGESTION_MEDIUM:
            congestion = "medium"

        return {
            "device_id": device_id,
            "timestamp": context.timestamp,
            "fps": calculate_fps(),
            "congestion_level": congestion,
            "vehicles": vehicles,
            "violations": properties.get("violations", []),
            "anomalies": properties.get("road_anomalies", []),
            "system_metrics": self._get_metrics(),
        }

    def _stream_worker(self, device_id, rtsp_url):
        proc = self._open_ffmpeg(rtsp_url)
        if proc is None:
            logger.error(f"Failed to start ffmpeg for: {rtsp_url}")
            with self._lock:
                self.active_streams.pop(device_id, None)
            return

        logger.info(f"RTSP FFmpeg capture opened: {device_id}")
        last_broadcast_time = 0.0
        broadcast_interval = 1.0 / RTSP_BROADCAST_FPS
        buf = bytearray()
        was_using_fast_path = None
        stats_started_at = time.monotonic()
        source_frame_count = 0
        broadcast_frame_count = 0
        broadcast_byte_count = 0
        inference_completed_count = 0
        inference_future = None
        latest_context = None
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"inference-{device_id}")

        try:
            while True:
                with self._lock:
                    if device_id not in self.active_streams or not self.active_streams[device_id]["active"]:
                        break

                # Read one complete JPEG frame (buffer persists across loops to avoid dropping frames)
                jpeg_bytes = None
                while True:
                    soi = buf.find(b'\xff\xd8')
                    if soi >= 0:
                        eoi = buf.find(b'\xff\xd9', soi + 2)
                        if eoi >= 0:
                            jpeg_bytes = bytes(buf[soi:eoi + 2])
                            del buf[:eoi + 2]
                            break
                    chunk = proc.stdout.read(8192)
                    if not chunk:
                        jpeg_bytes = None
                        break
                    if soi < 0:
                        if b'\xff\xd8' in chunk:
                            buf = bytearray(chunk[chunk.find(b'\xff\xd8'):])
                            continue
                    buf.extend(chunk)
                if jpeg_bytes is None:
                    logger.warning(f"RTSP stream ended for {device_id}, reconnecting...")
                    proc.terminate()
                    proc.wait()
                    time.sleep(1)
                    proc = self._open_ffmpeg(rtsp_url)
                    if proc is None:
                        logger.error(f"RTSP reconnect failed for {device_id}")
                        time.sleep(3)
                    continue

                active_devices[device_id] = time.time()
                source_frame_count += 1

                now = time.time()
                if now - last_broadcast_time < broadcast_interval:
                    continue

                try:
                    has_active_nodes = any(node.enabled for node in self.pipeline.nodes.values())
                    using_fast_path = not has_active_nodes
                    if using_fast_path != was_using_fast_path:
                        path_name = "JPEG passthrough" if using_fast_path else "AI processing"
                        logger.info(f"RTSP stream {device_id} switched to {path_name} path")
                        was_using_fast_path = using_fast_path
                        latest_context = None

                    # A configured parking zone does not need server-side image processing by
                    # itself. The dashboard draws zones as an overlay, and violation analysis
                    # only becomes meaningful when its pipeline nodes are enabled.
                    if using_fast_path:
                        payload = self._build_payload(device_id, None)
                        self._broadcast_bytes(jpeg_bytes)
                        self._broadcast(payload)
                        sent_byte_count = len(jpeg_bytes)
                    else:
                        # Video transport never waits for inference. Consume a finished
                        # result, then submit only the newest frame when the worker is idle.
                        if inference_future is not None and inference_future.done():
                            try:
                                mode, latest_context = inference_future.result()
                                self._update_plate_cache(device_id, mode, latest_context)
                                inference_completed_count += 1
                            except Exception as exc:
                                logger.error(f"RTSP inference failed for {device_id}: {exc}")
                            inference_future = None

                        if inference_future is None:
                            frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
                            if frame is not None:
                                self._frame_counters[device_id] = self._frame_counters.get(device_id, 0) + 1
                                frame_count = self._frame_counters[device_id]
                                inference_future = executor.submit(
                                    self._execute_pipeline,
                                    frame,
                                    device_id,
                                    frame_count,
                                )

                        payload = self._build_payload(device_id, latest_context)
                        self._broadcast_bytes(jpeg_bytes)
                        self._broadcast(payload)
                        sent_byte_count = len(jpeg_bytes)

                    last_broadcast_time = time.time()
                    broadcast_frame_count += 1
                    broadcast_byte_count += sent_byte_count

                    stats_elapsed = time.monotonic() - stats_started_at
                    if stats_elapsed >= 5.0:
                        source_fps = source_frame_count / stats_elapsed
                        broadcast_fps = broadcast_frame_count / stats_elapsed
                        broadcast_mbps = broadcast_byte_count * 8 / stats_elapsed / 1_000_000
                        logger.info(
                            f"[RTSP Stats {device_id}] source={source_fps:.1f} fps, "
                            f"broadcast={broadcast_fps:.1f} fps, "
                            f"inference={inference_completed_count / stats_elapsed:.1f} fps, "
                            f"{broadcast_mbps:.1f} Mbps"
                        )
                        stats_started_at = time.monotonic()
                        source_frame_count = 0
                        broadcast_frame_count = 0
                        broadcast_byte_count = 0
                        inference_completed_count = 0

                except Exception as e:
                    logger.error(f"RTSP frame processing error for {device_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"RTSP stream worker fatal error for {device_id}: {e}")
        finally:
            if inference_future is not None:
                inference_future.cancel()
            executor.shutdown(wait=False)
            proc.terminate()
            proc.wait()
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
