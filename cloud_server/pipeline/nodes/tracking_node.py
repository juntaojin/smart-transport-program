import cv2
import numpy as np
from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from model_api.reid import ReIDExtractor, IDMerger

REID_FRAME_INTERVAL = 3


class TrackingNode(PipelineNode):
    """基于 BoT-SORT + ReID 的目标跟踪节点"""

    def __init__(self):
        super().__init__(name="tracking")
        self._frame_count = 0
        self._reid = None
        self._id_merger = None

    def load_model(self):
        if self._reid is None:
            logger.info("[Tracking] Initializing BoT-SORT + ReID tracker")
            try:
                self._reid = ReIDExtractor(device="cuda")
                logger.info("[Tracking] ReID extractor loaded on CUDA")
            except Exception:
                self._reid = ReIDExtractor(device="cpu")
                logger.info("[Tracking] ReID extractor loaded on CPU")
            self._id_merger = IDMerger(similarity_threshold=0.85)
            self._frame_count = 0

    def unload_model(self):
        self._reid = None
        self._id_merger = None
        logger.info("[Tracking] ReID tracker cleared")

    def _do_process(self, context: FrameContext) -> FrameContext:
        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        classes = context.properties.get("vehicle_classes", [])
        raw_track_ids = context.properties.get("vehicle_track_ids", [])

        n = len(boxes)

        # 填充缺失的 track_ids (BoT-SORT may have None for some detections)
        track_ids = raw_track_ids[:n] if raw_track_ids else []
        while len(track_ids) < n:
            track_ids.append(None)

        # ReID ID merging every N frames
        if (self._frame_count % REID_FRAME_INTERVAL == 0
                and self._reid is not None
                and self._id_merger is not None
                and n > 0):
            try:
                crops = []
                valid_indices = []
                for i, box in enumerate(boxes):
                    x1, y1, x2, y2 = [int(c) for c in box]
                    crop = context.frame[max(0, y1):y2, max(0, x1):x2]
                    if crop.size > 0:
                        crops.append(crop)
                        valid_indices.append(i)

                if crops:
                    features = self._reid.extract_batch(crops)
                    valid_boxes = [boxes[i] for i in valid_indices]
                    raw_ids = [track_ids[i] if track_ids[i] is not None else -(i + 1)
                               for i in valid_indices]
                    merged_ids = self._id_merger.update_batch(raw_ids, features, valid_boxes)

                    merge_map = dict(zip(raw_ids, merged_ids))
                    for idx in range(n):
                        if idx in valid_indices:
                            rid = raw_ids[valid_indices.index(idx)]
                            track_ids[idx] = merge_map.get(rid, track_ids[idx])
                    logger.info(
                        f"[Tracking] Frame #{self._frame_count}: "
                        f"ReID merged {len(valid_indices)} vehicles"
                    )
            except Exception as e:
                logger.error(f"[Tracking] ReID error: {e}")

        # Ensure every vehicle has a track_id (use raw BoT-SORT ID or fallback index)
        for i in range(n):
            if track_ids[i] is None:
                track_ids[i] = -(i + 1)  # negative = unverified, ReID will merge soon

        context.properties["track_ids"] = track_ids
        context.properties["vehicle_boxes"] = boxes
        context.properties["vehicle_classes"] = classes

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[Tracking] Frame #{self._frame_count}: tracking {n} objects")

        return context
