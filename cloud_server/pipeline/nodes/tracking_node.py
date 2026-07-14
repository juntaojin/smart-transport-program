import threading

import numpy as np
from loguru import logger
from ultralytics.engine.results import Boxes
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace, YAML
from ultralytics.utils.checks import check_yaml

from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext

_tracker_update_lock = threading.RLock()


class _DeviceBYTETracker(BYTETracker):
    """Do not reset Ultralytics' global ID allocator when another camera starts."""

    def reset_id(self):
        pass


class _TrackerState:
    def __init__(self, tracker):
        self.tracker = tracker
        self.lock = threading.RLock()


class TrackingNode(PipelineNode):
    """Run one independent ByteTrack state machine for each input device."""

    def __init__(self):
        super().__init__(name="tracking")
        self._frame_count = 0
        self._registry_lock = threading.RLock()
        self._trackers = {}

    @staticmethod
    def _new_tracker():
        config = IterableSimpleNamespace(**YAML.load(check_yaml("bytetrack.yaml")))
        return _DeviceBYTETracker(config)

    def _get_tracker_state(self, device_id):
        key = str(device_id)
        with self._registry_lock:
            state = self._trackers.get(key)
            if state is None:
                state = _TrackerState(self._new_tracker())
                self._trackers[key] = state
                logger.info(f"[Tracking] Created independent ByteTrack for device={key}")
            return state

    def load_model(self):
        with self._registry_lock:
            self._trackers.clear()
        logger.info("[Tracking] Per-device ByteTrack ready")
        self._frame_count = 0

    def unload_model(self):
        with self._registry_lock:
            self._trackers.clear()
        logger.info("[Tracking] Node disabled")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])
        confidences = context.properties.get("vehicle_confidences", [])

        filtered_boxes = []
        filtered_classes = []
        filtered_confidences = []

        for index, box in enumerate(boxes):
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            try:
                bbox = [float(value) for value in box]
            except (TypeError, ValueError):
                continue
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue

            filtered_boxes.append(bbox)
            filtered_classes.append(classes[index] if index < len(classes) else "vehicle")
            filtered_confidences.append(
                float(confidences[index]) if index < len(confidences) else 0.0
            )

        # ByteTrack output contains the original detection index as its final
        # column. Keep an aligned list so unconfirmed detections remain visible
        # with a null track ID instead of being removed from the dashboard.
        track_ids = [None] * len(filtered_boxes)
        box_data = np.asarray(
            [
                [*box, filtered_confidences[index], 0.0]
                for index, box in enumerate(filtered_boxes)
            ],
            dtype=np.float32,
        ).reshape((-1, 6))
        detections = Boxes(box_data, context.frame.shape[:2])
        state = self._get_tracker_state(context.device_id)
        with _tracker_update_lock, state.lock:
            tracks = state.tracker.update(detections, context.frame)
        for track in tracks:
            detection_index = int(track[-1])
            if 0 <= detection_index < len(track_ids):
                track_ids[detection_index] = int(track[4])

        context.properties["vehicle_boxes"] = filtered_boxes
        context.properties["vehicle_classes"] = filtered_classes
        context.properties["vehicle_confidences"] = filtered_confidences
        context.properties["track_ids"] = track_ids

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(
                f"[Tracking] Frame #{self._frame_count}: "
                f"detections={len(filtered_boxes)}, "
                f"confirmed_tracks={sum(track_id is not None for track_id in track_ids)}"
            )

        return context
