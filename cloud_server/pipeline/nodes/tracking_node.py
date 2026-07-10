import numpy as np
from scipy.optimize import linear_sum_assignment
from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext

def linear_assignment(cost_matrix):
    x, y = linear_sum_assignment(cost_matrix)
    return np.array(list(zip(x, y)))

def iou_batch(bb_test, bb_gt):
    """
    Computes Intersection over Union (IoU) between two batches of bounding boxes.
    bb_test: [N, 4] (predicted)
    bb_gt: [M, 4] (detected)
    Returns: [N, M] matrix of IoU values
    """
    bb_gt = np.expand_dims(bb_gt, 0)
    bb_test = np.expand_dims(bb_test, 1)
    
    xx1 = np.maximum(bb_test[..., 0], bb_gt[..., 0])
    yy1 = np.maximum(bb_test[..., 1], bb_gt[..., 1])
    xx2 = np.minimum(bb_test[..., 2], bb_gt[..., 2])
    yy2 = np.minimum(bb_test[..., 3], bb_gt[..., 3])
    
    w = np.maximum(0., xx2 - xx1)
    h = np.maximum(0., yy2 - yy1)
    wh = w * h
    
    o = wh / ((bb_test[..., 2] - bb_test[..., 0]) * (bb_test[..., 3] - bb_test[..., 1]) 
              + (bb_gt[..., 2] - bb_gt[..., 0]) * (bb_gt[..., 3] - bb_gt[..., 1]) - wh)
    return o


class KalmanBoxTracker:
    """
    Represents the internal state of individual tracked objects observed as bbox.
    Uses pure numpy to implement a 2D Kalman Filter.
    """
    count = 0
    def __init__(self, bbox):
        # State vector: [u, v, s, r, u_dot, v_dot, s_dot]^T
        # u, v: center coordinates. s: scale (area). r: aspect ratio.
        self.id = KalmanBoxTracker.count
        KalmanBoxTracker.count += 1
        
        # Initialize state with bbox
        u, v, s, r = self._bbox_to_state(bbox)
        self.x = np.array([[u], [v], [s], [r], [0.], [0.], [0.]])
        
        # State transition matrix F
        self.F = np.array([
            [1, 0, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1]
        ])
        
        # Measurement matrix H (we only observe u, v, s, r)
        self.H = np.array([
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0]
        ])
        
        # Covariance matrices
        self.P = np.eye(7) * 10.
        self.P[4:, 4:] *= 1000.  # high uncertainty in velocities
        
        self.Q = np.eye(7)
        self.Q[4:, 4:] *= 0.01
        
        self.R = np.eye(4)
        self.R[2:, 2:] *= 10.
        
        self.time_since_update = 0
        self.history = []
        self.hits = 0
        self.hit_streak = 0
        self.age = 0

    def update(self, bbox):
        self.time_since_update = 0
        self.history = []
        self.hits += 1
        self.hit_streak += 1
        
        # Measurement update
        z = np.array(self._bbox_to_state(bbox)).reshape(4, 1)
        y = z - np.dot(self.H, self.x)
        S = np.dot(self.H, np.dot(self.P, self.H.T)) + self.R
        K = np.dot(self.P, np.dot(self.H.T, np.linalg.inv(S)))
        self.x = self.x + np.dot(K, y)
        self.P = self.P - np.dot(K, np.dot(self.H, self.P))

    def predict(self):
        # State prediction
        if (self.x[6] + self.x[2]) <= 0:
            self.x[6] *= 0.0
        self.x = np.dot(self.F, self.x)
        self.P = np.dot(self.F, np.dot(self.P, self.F.T)) + self.Q
        
        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        
        # Append predicted state to history
        self.history.append(self.get_state())
        return self.history[-1]

    def get_state(self):
        """Returns the current bounding box estimate in xyxy format"""
        u, v, s, r = self.x[0, 0], self.x[1, 0], self.x[2, 0], self.x[3, 0]
        w = np.sqrt(s * r)
        h = s / w
        x1 = u - w / 2.
        y1 = v - h / 2.
        x2 = u + w / 2.
        y2 = v + h / 2.
        return np.array([x1, y1, x2, y2])

    def _bbox_to_state(self, bbox):
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x_center = bbox[0] + w / 2.
        y_center = bbox[1] + h / 2.
        area = w * h
        aspect_ratio = w / float(h) if h > 0 else 0.0
        return x_center, y_center, area, aspect_ratio


class Sort:
    """SORT Multi-Object Tracker"""

    def __init__(self, max_age=3, min_hits=1, iou_threshold=0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers = []
        self.frame_count = 0

    def update(self, dets=np.empty((0, 5))):
        """
        dets - a numpy array of detections in the format [[x1,y1,x2,y2,score],...]
        Requires: this method must be called once for each frame even with empty detections.
        Returns a similar array, where the last column is the object ID.
        """
        self.frame_count += 1
        
        # Get predicted locations from existing trackers
        trks = np.zeros((len(self.trackers), 5))
        to_del = []
        ret = []
        for t, trk in enumerate(trks):
            pos = self.trackers[t].predict()
            trk[:] = [pos[0], pos[1], pos[2], pos[3], 0]
            if np.any(np.isnan(pos)):
                to_del.append(t)
        
        # Remove any trackers that returned NaN
        trks = np.delete(trks, to_del, axis=0)
        for index in sorted(to_del, reverse=True):
            self.trackers.pop(index)
            
        # Match detections to predicted trackers
        matched, unmatched_dets, unmatched_trks = self._associate_detections_to_trackers(dets, trks)
        
        # Update matched trackers with assigned detections
        for m in matched:
            self.trackers[m[1]].update(dets[m[0], :4])
            
        # Create and initialize new trackers for unmatched detections
        for i in unmatched_dets:
            trk = KalmanBoxTracker(dets[i, :4])
            self.trackers.append(trk)
            
        i = len(self.trackers)
        for trk in reversed(self.trackers):
            if trk.time_since_update > self.max_age:
                self.trackers.pop(i)
                i -= 1
                continue
            d = trk.get_state()
            # Output: matched in current frame, OR recently active (Kalman prediction)
            confirmed = (trk.hit_streak >= self.min_hits or self.frame_count <= self.min_hits)
            if confirmed and trk.time_since_update <= self.max_age:
                ret.append(np.concatenate((d, [trk.id + 1])).reshape(1, -1))
            i -= 1
                
        if len(ret) > 0:
            return np.concatenate(ret)
        return np.empty((0, 5))

    def _associate_detections_to_trackers(self, detections, trackers):
        """Associates detections to tracked objects (both in xyxy format)"""
        if len(trackers) == 0:
            return np.empty((0, 2), dtype=int), np.arange(len(detections)), np.empty((0, 5), dtype=int)
            
        iou_matrix = iou_batch(detections, trackers)
        
        if min(iou_matrix.shape) > 0:
            a = (iou_matrix > self.iou_threshold)
            if a.all() or np.any(a):
                matched_indices = linear_assignment(-iou_matrix)
            else:
                matched_indices = np.empty((0, 2), dtype=int)
        else:
            matched_indices = np.empty((0, 2), dtype=int)
            
        unmatched_detections = []
        for d, det in enumerate(detections):
            if d not in matched_indices[:, 0]:
                unmatched_detections.append(d)
                
        unmatched_trackers = []
        for t, trk in enumerate(trackers):
            if t not in matched_indices[:, 1]:
                unmatched_trackers.append(t)
                
        # Filter out matched items with low IoU
        matches = []
        for m in matched_indices:
            if iou_matrix[m[0], m[1]] < self.iou_threshold:
                unmatched_detections.append(m[0])
                unmatched_trackers.append(m[1])
            else:
                matches.append(m.reshape(1, 2))
                
        if len(matches) == 0:
            matches = np.empty((0, 2), dtype=int)
        else:
            matches = np.concatenate(matches, axis=0)
            
        return matches, np.array(unmatched_detections), np.array(unmatched_trackers)


class TrackingNode(PipelineNode):
    """基于 SORT 跟踪器的目标跟踪节点"""

    def __init__(self):
        super().__init__(name="tracking")
        self.tracker = None
        self._frame_count = 0
        self._class_registry: dict[int, str] = {}

    def load_model(self):
        if self.tracker is None:
            logger.info("[Tracking] Initializing SORT Multi-Object Tracker (max_age=8, iou=0.3, prediction enabled)")
            self.tracker = Sort(max_age=8, min_hits=1, iou_threshold=0.3)
            self._frame_count = 0
            self._class_registry: dict[int, str] = {}  # track_id -> class

    def unload_model(self):
        if self.tracker is not None:
            logger.info("[Tracking] Clearing SORT Tracker state")
            self.tracker = None
            self._class_registry.clear()

    def _do_process(self, context: FrameContext) -> FrameContext:
        if self.tracker is None:
            self.load_model()

        self._frame_count += 1
        boxes = context.properties.get("vehicle_boxes", [])
        confs = context.properties.get("vehicle_confidences", [])
        classes = context.properties.get("vehicle_classes", [])

        # Always call update even with empty detections (SORT outputs predictions)
        dets = []
        for box, conf in zip(boxes, confs):
            dets.append([box[0], box[1], box[2], box[3], conf])
        dets_arr = np.array(dets) if dets else np.empty((0, 5))
        tracked_objects = self.tracker.update(dets_arr)

        track_ids = []
        tracked_boxes = []
        tracked_classes = []

        for obj in tracked_objects:
            tx1, ty1, tx2, ty2, obj_id = obj
            tid = int(obj_id)
            track_ids.append(tid)
            tracked_boxes.append([float(tx1), float(ty1), float(tx2), float(ty2)])

            if len(boxes) > 0:
                # IoU match to find best class label from current detections
                best_cls = "vehicle"
                best_iou = -1
                for idx, orig_box in enumerate(boxes):
                    ix1 = max(tx1, orig_box[0])
                    iy1 = max(ty1, orig_box[1])
                    ix2 = min(tx2, orig_box[2])
                    iy2 = min(ty2, orig_box[3])
                    iw = max(0, ix2 - ix1)
                    ih = max(0, iy2 - iy1)
                    inter = iw * ih
                    union = (tx2 - tx1) * (ty2 - ty1) + (orig_box[2] - orig_box[0]) * (orig_box[3] - orig_box[1]) - inter
                    iou = inter / union if union > 0 else 0
                    if iou > best_iou:
                        best_iou = iou
                        best_cls = classes[idx]
                self._class_registry[tid] = best_cls
                tracked_classes.append(best_cls)
            else:
                # No detections this frame: use remembered class
                tracked_classes.append(self._class_registry.get(tid, "car"))

        # Clean up registry for stale trackers
        active_ids = set(track_ids)
        stale = [k for k in self._class_registry if k not in active_ids]
        for k in stale:
            del self._class_registry[k]

        context.properties["track_ids"] = track_ids
        context.properties["vehicle_boxes"] = tracked_boxes
        context.properties["vehicle_classes"] = tracked_classes

        if self._frame_count <= 5 or self._frame_count % 30 == 0:
            logger.info(f"[Tracking] Frame #{self._frame_count}: tracking {len(track_ids)} objects")

        return context
