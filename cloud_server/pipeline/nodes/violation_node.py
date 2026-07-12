from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
import cloud_server.config as server_config
from model_api import detect_violations


class ViolationDetectionNode(PipelineNode):
    def __init__(self):
        super().__init__(name="violation_detection")
        self._frame_count = 0

    def load_model(self):
        logger.info("[ViolationDetection] Node ready (function-call mode)")
        self._frame_count = 0

    def unload_model(self):
        logger.info("[ViolationDetection] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        track_ids = context.properties.get("track_ids", [])
        classes = context.properties.get("vehicle_classes", [])
        h_img, w_img = context.frame.shape[:2]

        vehicles_payload = []
        for idx, box in enumerate(boxes):
            if idx >= len(track_ids):
                continue
            vehicles_payload.append({
                "track_id": track_ids[idx],
                "box": [float(c) for c in box],
                "class": classes[idx] if idx < len(classes) else "vehicle",
            })

        zones_payload = []
        parking_threshold = server_config.PARKING_THRESHOLD
        for zone in server_config.NO_PARKING_ZONES:
            zones_payload.append({
                "name": zone["name"],
                "points": [list(pt) for pt in zone["points"]],
            })

        try:
            violations = detect_violations(
                vehicles=vehicles_payload,
                no_parking_zones=zones_payload,
                timestamp=context.timestamp,
                parking_threshold=parking_threshold,
                image_width=w_img,
                image_height=h_img,
                device_id=context.device_id,
            )
        except NotImplementedError:
            logger.error("[ViolationDetection] detect_violations() 尚未实现！等待模型同学实现。")
            context.properties["violations"] = []
            return context
        except Exception as e:
            logger.error(f"[ViolationDetection] 函数调用失败: {e}")
            context.properties["violations"] = []
            return context

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[ViolationDetection] Frame #{self._frame_count}: "
                f"vehicles={len(vehicles_payload)}, track_ids={len(track_ids)}, "
                f"zones={len(zones_payload)}, threshold={parking_threshold:.1f}s, "
                f"timeouts={len(violations)}"
            )

        for v in violations:
            if "duration" in v and v["duration"] > parking_threshold:
                logger.warning(f"TIMEOUT ALERT: Vehicle {v['vehicle_id']} stayed in '{v['zone_name']}' for {v['duration']:.1f}s")

        context.properties["violations"] = violations
        return context
