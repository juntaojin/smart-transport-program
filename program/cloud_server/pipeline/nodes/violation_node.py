import time
from loguru import logger
from cloud_server.pipeline.engine import PipelineNode
from cloud_server.pipeline.context import FrameContext
from cloud_server.config import NO_PARKING_ZONES, PARKING_THRESHOLD

def point_in_polygon(x, y, poly):
    """
    Ray Casting algorithm for Point-in-Polygon test.
    poly is a list of tuples/lists: [(x1, y1), (x2, y2), ...]
    """
    n = len(poly)
    inside = False
    if n == 0:
        return False
        
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


class ViolationDetectionNode(PipelineNode):
    """禁停区违停检测节点"""

    def __init__(self, parking_threshold: float = None):
        super().__init__(name="violation_detection")
        self.parking_threshold = parking_threshold if parking_threshold is not None else PARKING_THRESHOLD
        
        # Track parking start times: {vehicle_id: {zone_name: start_time}}
        self.tracking_registry = {}
        self.zones = NO_PARKING_ZONES

    def load_model(self):
        # Violation logic doesn't require model files, just initialize structures
        logger.info("Violation detection node initialized")

    def unload_model(self):
        self.tracking_registry.clear()
        logger.info("Violation detection node state cleared")

    def _do_process(self, context: FrameContext) -> FrameContext:
        boxes = context.properties.get("vehicle_boxes", [])
        track_ids = context.properties.get("track_ids", [])
        
        violations = []
        current_time = context.timestamp
        h_img, w_img = context.frame.shape[:2]

        active_vehicle_ids = set()

        for idx, box in enumerate(boxes):
            if idx >= len(track_ids):
                continue
            
            veh_id = track_ids[idx]
            active_vehicle_ids.add(veh_id)
            
            x1, y1, x2, y2 = box
            # Contact point (bottom-middle of bounding box)
            px = ((x1 + x2) / 2.0) / w_img
            py = y2 / h_img

            # Check if this vehicle is inside any forbidden zones
            in_any_zone = False
            for zone in self.zones:
                zone_name = zone["name"]
                points = zone["points"]
                
                if point_in_polygon(px, py, points):
                    in_any_zone = True
                    
                    # Register parking start
                    if veh_id not in self.tracking_registry:
                        self.tracking_registry[veh_id] = {}
                        
                    if zone_name not in self.tracking_registry[veh_id]:
                        self.tracking_registry[veh_id][zone_name] = current_time
                        logger.info(f"Vehicle {veh_id} entered forbidden zone '{zone_name}'")
                        
                    # Calculate elapsed time
                    start_time = self.tracking_registry[veh_id][zone_name]
                    elapsed = current_time - start_time
                    
                    if elapsed > self.parking_threshold:
                        violations.append({
                            "vehicle_id": veh_id,
                            "zone_name": zone_name,
                            "duration": elapsed,
                            "box": [float(coord) for coord in box],
                            "contact_point": (px, py)
                        })
                        logger.warning(f"VIOLATION ALERT: Vehicle {veh_id} parked in '{zone_name}' for {elapsed:.1f}s")
                else:
                    # If vehicle is tracked but not in this specific zone, remove zone tracker
                    if veh_id in self.tracking_registry and zone_name in self.tracking_registry[veh_id]:
                        self.tracking_registry[veh_id].pop(zone_name)

            if not in_any_zone:
                # Remove if not in any zone
                self.tracking_registry.pop(veh_id, None)

        # Cleanup registry for vehicles that are no longer in the frame
        stale_ids = [vid for vid in self.tracking_registry if vid not in active_vehicle_ids]
        for vid in stale_ids:
            self.tracking_registry.pop(vid, None)

        context.properties["violations"] = violations
        return context
