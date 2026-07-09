import gc
import cv2
import numpy as np
import torch
from loguru import logger
import hyperlpr3 as lpr3
from hyperlpr3.inference.pipeline import get_rotate_crop_image
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext


class PlateRecognitionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="plate_ocr")
        self._lpr_catcher = None
        self._lpr_pipeline = None
        self._lpr_rec = None
        self._frame_count = 0

    def load_model(self):
        if self._model is None:
            logger.info("[PlateOCR] Loading HyperLPR3 license plate engine...")
            logger.info(f"[PlateOCR] CUDA available: {torch.cuda.is_available()}, device count: {torch.cuda.device_count()}")
            if torch.cuda.is_available():
                logger.info(f"[PlateOCR] CUDA device: {torch.cuda.get_device_name(0)}")
            else:
                logger.warning("[PlateOCR] CUDA not available, HyperLPR3 will run on CPU")
            self._lpr_catcher = lpr3.LicensePlateCatcher()
            self._lpr_pipeline = self._lpr_catcher.pipeline
            self._lpr_rec = self._lpr_pipeline.recognizer
            self._lpr_pipeline.detector.box_threshold = 0.2
            self._model = True
            self._frame_count = 0
            logger.info("[PlateOCR] HyperLPR3 loaded successfully (detection threshold: 0.2)")

    def unload_model(self):
        if self._model is not None:
            logger.info("[PlateOCR] Unloading HyperLPR3 engine and clearing cache")
            self._lpr_catcher = None
            self._lpr_pipeline = None
            self._lpr_rec = None
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("[PlateOCR] Model unloaded")

    def _recognize_plate(self, frame, vehicle_bbox):
        x1, y1, x2, y2 = vehicle_bbox
        img_h, img_w = frame.shape[:2]
        vehicle_h = y2 - y1
        vehicle_w = x2 - x1

        roi_y1 = max(0, y1 + int(vehicle_h * 0.35))
        roi_y2 = min(img_h, y2)
        roi_x1 = max(0, x1)
        roi_x2 = min(img_w, x2)
        vehicle_roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

        if vehicle_roi.size == 0 or vehicle_roi.shape[0] < 15 or vehicle_roi.shape[1] < 40:
            return "", 0.0

        raw_h, raw_w = vehicle_roi.shape[:2]
        scale = max(1.0, 800.0 / raw_w)
        if scale > 1.0:
            vehicle_roi = cv2.resize(vehicle_roi, (int(raw_w * scale), int(raw_h * scale)), interpolation=cv2.INTER_CUBIC)

        dets = self._lpr_pipeline.detector(vehicle_roi)

        if len(dets) == 0:
            dets_full = self._lpr_pipeline.detector(frame)
            if len(dets_full) == 0:
                return "", 0.0
            best_in_vehicle = None
            for d in sorted(dets_full, key=lambda x: x[4], reverse=True):
                dcx = (d[0] + d[2]) / 2
                dcy = (d[1] + d[3]) / 2
                if x1 <= dcx <= x2 and y1 <= dcy <= y2:
                    best_in_vehicle = d
                    break
            if best_in_vehicle is None:
                return "", 0.0
            warp_image = frame
            best_det = best_in_vehicle
        else:
            warp_image = vehicle_roi
            best_det = max(dets, key=lambda d: d[4])

        landmarks = best_det[5:13].reshape(4, 2).astype(np.float32)
        warp_h, warp_w = warp_image.shape[:2]

        warped = get_rotate_crop_image(warp_image, landmarks)
        code, conf = self._lpr_rec(warped)

        if len(code) < 7:
            cx, cy = np.mean(landmarks, axis=0)
            expanded_lms = landmarks.copy()
            for j in range(4):
                vec = expanded_lms[j] - np.array([cx, cy])
                expanded_lms[j] = expanded_lms[j] + vec * 0.18
            expanded_lms = np.clip(expanded_lms, [0, 0], [warp_w - 1, warp_h - 1])
            warped2 = get_rotate_crop_image(warp_image, expanded_lms)
            code2, conf2 = self._lpr_rec(warped2)
            if len(code2) > len(code):
                code, conf = code2, conf2

        if len(code) >= 6:
            return code, conf
        return "", 0.0

    def _do_process(self, context: FrameContext) -> FrameContext:
        if self._model is None:
            self.load_model()

        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])

        plates = []
        confidences = []
        recognized = 0

        for idx, box in enumerate(boxes):
            cls_name = classes[idx] if idx < len(classes) else "vehicle"
            if cls_name not in ["car", "truck", "bus"]:
                plates.append("")
                confidences.append(0.0)
                continue

            x1, y1, x2, y2 = [int(c) for c in box]
            try:
                plate, pconf = self._recognize_plate(context.frame, (x1, y1, x2, y2))
                if plate and pconf >= 0.995:
                    plates.append(plate)
                    confidences.append(pconf)
                    recognized += 1
                    logger.info(f"[PlateOCR] Frame #{self._frame_count}: {plate} (conf={pconf:.3f})")
                else:
                    plates.append("")
                    confidences.append(0.0)
            except Exception as e:
                logger.error(f"[PlateOCR] Error on frame #{self._frame_count}, vehicle {idx}: {e}")
                plates.append("")
                confidences.append(0.0)

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[PlateOCR] Frame #{self._frame_count}: {len(boxes)} vehicles, {recognized} plates recognized")

        context.properties["plate_numbers"] = plates
        context.properties["plate_confidences"] = confidences
        return context
