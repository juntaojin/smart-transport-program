import cv2
import numpy as np
from typing import Optional
from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from model_api import recognize_plate


class PlateRecognitionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="plate_ocr")
        self._frame_count = 0
        self._plate_cache: dict = {}  # {device_id: {track_id: (plate_number, confidence)}}

    def load_model(self):
        logger.info("[PlateOCR] Node ready (sync with track_id cache)")
        self._frame_count = 0
        self._plate_cache.clear()

    def unload_model(self):
        self._plate_cache.clear()
        logger.info("[PlateOCR] Node disabled, cache cleared")

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

        plates = []
        confidences = []
        recognized = 0
        cached = 0

        for idx, box in enumerate(boxes):
            cls_name = classes[idx] if idx < len(classes) else "vehicle"
            tid = track_ids[idx] if idx < len(track_ids) else None

            if cls_name not in ["car", "truck", "bus"]:
                plates.append("")
                confidences.append(0.0)
                continue

            if tid is not None and tid in device_cache:
                cached_plate, cached_conf = device_cache[tid]
                plates.append(cached_plate)
                confidences.append(cached_conf)
                cached += 1
                continue

            try:
                roi = self._crop_vehicle_roi(context.frame, box)
                if roi is None:
                    plates.append("")
                    confidences.append(0.0)
                    continue

                plate, pconf = recognize_plate(roi)

                if plate and pconf >= 0.6:
                    plates.append(plate)
                    confidences.append(pconf)
                    recognized += 1
                    if tid is not None:
                        device_cache[tid] = (plate, pconf)
                    logger.info(f"[PlateOCR] Frame #{self._frame_count}: track_id={tid} -> {plate} (conf={pconf:.3f})")
                else:
                    plates.append("")
                    confidences.append(0.0)
            except NotImplementedError:
                logger.error("[PlateOCR] recognize_plate() 尚未实现！")
                plates.append("")
                confidences.append(0.0)
            except Exception as e:
                logger.error(f"[PlateOCR] Error frame #{self._frame_count}, vehicle {idx}: {e}")
                plates.append("")
                confidences.append(0.0)

        active_ids = {track_ids[i] for i in range(len(track_ids)) if track_ids[i] is not None}
        stale_ids = [tid for tid in device_cache if tid not in active_ids]
        for tid in stale_ids:
            device_cache.pop(tid, None)

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[PlateOCR] Frame #{self._frame_count}: {len(boxes)} vehicles, "
                f"{recognized} new plates, {cached} from cache"
            )

        context.properties["plate_numbers"] = plates
        context.properties["plate_confidences"] = confidences
        return context
