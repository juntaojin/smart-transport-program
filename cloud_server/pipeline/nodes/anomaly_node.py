from loguru import logger

from cloud_server.config import (
    ANOMALY_ALERT_FRAMES,
    ANOMALY_BANK_FRAMES,
    ANOMALY_DEVICE,
    ANOMALY_MAX_AGE,
    ANOMALY_MIN_AREA,
    ANOMALY_DIFF_THRESH,
    ANOMALY_MIN_EXTENT,
    ANOMALY_MIN_BOX_SIZE,
    ANOMALY_MODEL_PATH,
    ANOMALY_STABILIZATION_ENABLED,
    ANOMALY_MAX_JITTER_PX,
    ANOMALY_ALERT_SECONDS,
    ANOMALY_MAX_MISSING_SECONDS,
    ANOMALY_STATIC_EDGE_SUPPRESSION_PX,
    ANOMALY_VEHICLE_MASK_PADDING,
    ANOMALY_DIRTY_ABSENCE_FRAMES,
)
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.runtime_config import get_model_parameters
from model_api import (
    detect_anomalies,
    load_anomaly_model,
    reset_anomaly_state,
    unload_anomaly_model,
)


class AnomalyDetectionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="anomaly_detection")
        self._frame_count = 0

    def load_model(self):
        self._frame_count = 0
        threshold = get_model_parameters(self.name)["confidence"]
        reset_anomaly_state()
        if not load_anomaly_model(
            ANOMALY_MODEL_PATH,
            ANOMALY_DEVICE,
            bank_frames=ANOMALY_BANK_FRAMES,
            alert_frames=ANOMALY_ALERT_FRAMES,
            max_age=ANOMALY_MAX_AGE,
            min_area=ANOMALY_MIN_AREA,
            diff_thresh=ANOMALY_DIFF_THRESH,
            min_extent=ANOMALY_MIN_EXTENT,
            min_box_size=ANOMALY_MIN_BOX_SIZE,
            stabilization_enabled=ANOMALY_STABILIZATION_ENABLED,
            max_jitter_px=ANOMALY_MAX_JITTER_PX,
            alert_seconds=ANOMALY_ALERT_SECONDS,
            max_missing_seconds=ANOMALY_MAX_MISSING_SECONDS,
            static_edge_suppression_px=ANOMALY_STATIC_EDGE_SUPPRESSION_PX,
            vehicle_mask_padding=ANOMALY_VEHICLE_MASK_PADDING,
            dirty_absence_frames=ANOMALY_DIRTY_ABSENCE_FRAMES,
        ):
            raise RuntimeError(
                f"Failed to load anomaly model from {ANOMALY_MODEL_PATH}"
            )
        logger.info(
            f"[AnomalyDetection] Node ready (threshold={threshold}, "
            f"device={ANOMALY_DEVICE}, warmup={ANOMALY_BANK_FRAMES}, "
            f"alert_frames={ANOMALY_ALERT_FRAMES}, alert_seconds={ANOMALY_ALERT_SECONDS}, "
            f"min_area={ANOMALY_MIN_AREA}, diff_thresh={ANOMALY_DIFF_THRESH}, "
            f"min_extent={ANOMALY_MIN_EXTENT}, stabilization={ANOMALY_STABILIZATION_ENABLED})"
        )

    def unload_model(self):
        unload_anomaly_model()
        logger.info("[AnomalyDetection] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        threshold = get_model_parameters(self.name)["confidence"]

        try:
            normal_boxes = context.properties.get("vehicle_boxes")
            anomalies = detect_anomalies(
                context.frame,
                device_id=context.device_id,
                timestamp=context.timestamp,
                normal_boxes=normal_boxes,
            )
        except NotImplementedError:
            logger.error("[AnomalyDetection] detect_anomalies() is not implemented yet")
            context.properties["road_anomalies"] = []
            return context
        except Exception as e:
            logger.error(f"[AnomalyDetection] function call failed: {e}")
            context.properties["road_anomalies"] = []
            return context

        if not isinstance(anomalies, list):
            logger.warning(
                f"[AnomalyDetection] unexpected return type: {type(anomalies).__name__}"
            )
            anomalies = []

        filtered = []
        for anomaly in anomalies:
            normalized = self._normalize_anomaly(anomaly, threshold)
            if normalized is not None:
                filtered.append(normalized)

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[AnomalyDetection] Frame #{self._frame_count}: "
                f"{len(filtered)} anomalies (raw: {len(anomalies)})"
            )

        context.properties["road_anomalies"] = filtered
        return context

    def _normalize_anomaly(self, anomaly, threshold):
        if not isinstance(anomaly, dict):
            return None

        box = anomaly.get("box") or anomaly.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return None

        try:
            confidence = float(anomaly.get("confidence", anomaly.get("conf", 0.0)))
            normalized_box = [float(value) for value in box]
        except (TypeError, ValueError):
            return None

        width = max(0.0, normalized_box[2] - normalized_box[0])
        height = max(0.0, normalized_box[3] - normalized_box[1])
        area = width * height

        if confidence < threshold:
            return None
        if area < ANOMALY_MIN_AREA:
            return None
        if width < ANOMALY_MIN_BOX_SIZE or height < ANOMALY_MIN_BOX_SIZE:
            return None

        return {
            "box": normalized_box,
            "confidence": confidence,
            "label": anomaly.get("label") or anomaly.get("class") or "road_anomaly",
        }
