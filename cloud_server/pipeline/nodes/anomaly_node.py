from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from model_api import detect_anomalies


class AnomalyDetectionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="anomaly_detection")
        self._frame_count = 0

    def load_model(self):
        logger.info("[AnomalyDetection] Node ready (function-call mode)")
        self._frame_count = 0

    def unload_model(self):
        logger.info("[AnomalyDetection] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1

        try:
            anomalies = detect_anomalies(context.frame)
        except NotImplementedError:
            logger.error("[AnomalyDetection] detect_anomalies() 尚未实现！等待模型同学实现。")
            context.properties["road_anomalies"] = []
            return context
        except Exception as e:
            logger.error(f"[AnomalyDetection] 函数调用失败: {e}")
            context.properties["road_anomalies"] = []
            return context

        filtered = []
        for a in anomalies:
            if a.get("confidence", 0.0) >= 0.4:
                filtered.append({
                    "box": [float(c) for c in a["box"]],
                    "confidence": float(a.get("confidence", 0.0)),
                    "label": a.get("label", "road_anomaly"),
                })

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[AnomalyDetection] Frame #{self._frame_count}: {len(filtered)} anomalies (raw: {len(anomalies)})")

        context.properties["road_anomalies"] = filtered
        return context
