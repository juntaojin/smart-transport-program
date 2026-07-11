from loguru import logger

from cloud_server.config import ANOMALY_THRESHOLD
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from model_api import detect_anomalies


class AnomalyDetectionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="anomaly_detection")
        self._frame_count = 0

    def load_model(self):
        self._frame_count = 0
        logger.info(
            f"[AnomalyDetection] Node ready (stateful function-call mode, threshold={ANOMALY_THRESHOLD})"
        )

    def unload_model(self):
        logger.info("[AnomalyDetection] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1

        try:
            anomalies = detect_anomalies(context.frame)
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
            normalized = self._normalize_anomaly(anomaly)
            if normalized is not None:
                filtered.append(normalized)

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[AnomalyDetection] Frame #{self._frame_count}: "
                f"{len(filtered)} anomalies (raw: {len(anomalies)})"
            )

        context.properties["road_anomalies"] = filtered
        return context

    def _normalize_anomaly(self, anomaly):
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

        if confidence < ANOMALY_THRESHOLD:
            return None

        return {
            "box": normalized_box,
            "confidence": confidence,
            "label": anomaly.get("label") or anomaly.get("class") or "road_anomaly",
        }
