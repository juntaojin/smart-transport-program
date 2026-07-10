import cv2
import numpy as np
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, Future
from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from model_api import recognize_plate


class PlateRecognitionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="plate_ocr")
        self._frame_count = 0
        self._plate_cache: dict = {}       # {device_id: {track_id: (plate, conf)}}
        self._pending: dict = {}            # {device_id: {track_id: Future}}
        self._executor: ThreadPoolExecutor | None = None

    def load_model(self):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")
        self._frame_count = 0
        self._plate_cache.clear()
        self._pending.clear()
        logger.info("[PlateOCR] Node ready (async OCR with thread pool)")

    def unload_model(self):
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._plate_cache.clear()
        self._pending.clear()
        logger.info("[PlateOCR] Node disabled, executor shut down")

    def _crop_vehicle_roi(self, frame: np.ndarray, bbox: list) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = [int(c) for c in bbox]
        img_h, img_w = frame.shape[:2]
        vehicle_h = y2 - y1

        roi_y1 = max(0, y1 + int(vehicle_h * 0.35))
        roi_y2 = min(img_h, y2)
        roi_x1 = max(0, x1)
        roi_x2 = min(img_w, x2)
        vehicle_roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

        if vehicle_roi.size == 0 or vehicle_roi.shape[0] < 15 or vehicle_roi.shape[1] < 40:
            return None

        raw_h, raw_w = vehicle_roi.shape[:2]
        scale = max(1.0, 800.0 / raw_w)
        if scale > 1.0:
            vehicle_roi = cv2.resize(vehicle_roi, (int(raw_w * scale), int(raw_h * scale)),
                                     interpolation=cv2.INTER_CUBIC)

        return vehicle_roi

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])
        track_ids = context.properties.get("track_ids", [])

        device_cache = self._plate_cache.setdefault(context.device_id, {})
        device_pending = self._pending.setdefault(context.device_id, {})

        plates = []
        confidences = []
        recognized = 0
        cached = 0
        pending_count = 0

        # 1. Harvest completed OCR futures
        for tid in list(device_pending):
            fut = device_pending[tid]
            if fut.done():
                try:
                    plate, pconf = fut.result()
                    if plate and pconf >= 0.6:
                        device_cache[tid] = (plate, pconf)
                        logger.info(
                            f"[PlateOCR] Frame #{self._frame_count}: "
                            f"track_id={tid} -> {plate} (conf={pconf:.3f}) [async]"
                        )
                except Exception as e:
                    logger.error(f"[PlateOCR] Async OCR failed for track_id={tid}: {e}")
                del device_pending[tid]

        active_ids = set()

        for idx, box in enumerate(boxes):
            cls_name = classes[idx] if idx < len(classes) else "vehicle"
            tid = track_ids[idx] if idx < len(track_ids) else None

            if cls_name not in ["car", "truck", "bus"]:
                plates.append("")
                confidences.append(0.0)
                continue

            if tid is not None:
                active_ids.add(tid)

            # Hit cache
            if tid is not None and tid in device_cache:
                cp, cc = device_cache[tid]
                plates.append(cp)
                confidences.append(cc)
                cached += 1
                continue

            # Already submitted, waiting
            if tid is not None and tid in device_pending:
                plates.append("")
                confidences.append(0.0)
                pending_count += 1
                continue

            # New vehicle: submit async OCR
            if tid is not None:
                roi = self._crop_vehicle_roi(context.frame, box)
                if roi is not None and self._executor is not None:
                    fut = self._executor.submit(recognize_plate, roi.copy())
                    device_pending[tid] = fut
                    pending_count += 1
                plates.append("")
                confidences.append(0.0)
                continue

            plates.append("")
            confidences.append(0.0)

        # Clean up stale cache entries
        stale = [tid for tid in device_cache if tid not in active_ids]
        for tid in stale:
            device_cache.pop(tid, None)

        # Clean up stale pending futures (vehicle disappeared)
        stale_pending = [tid for tid in device_pending if tid not in active_ids]
        for tid in stale_pending:
            device_pending.pop(tid, None)

        context.properties["plate_numbers"] = plates
        context.properties["plate_confidences"] = confidences

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[PlateOCR] Frame #{self._frame_count}: {len(boxes)} vehicles, "
                f"{recognized} new plates, {cached} from cache, {pending_count} pending"
            )

        return context
