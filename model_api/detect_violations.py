_state = {}

# Detection boxes and tracker IDs can flicker in sandbox videos. Keep timeout
# occupancy state alive briefly so a vehicle that is still in the configured
# area does not restart its timer because of one missed frame or one ID switch.
_ZONE_EXIT_GRACE_SECONDS = 1.5
_TRACK_MISSING_GRACE_SECONDS = 2.5
_ID_SWITCH_GRACE_SECONDS = 2.5
_REASSOC_IOU_THRESHOLD = 0.15
_REASSOC_CENTER_DISTANCE = 0.12


def _point_in_polygon(px, py, polygon):
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _normalize_box(box, image_width, image_height):
    x1, y1, x2, y2 = box
    return [x1 / image_width, y1 / image_height, x2 / image_width, y2 / image_height]


def _box_iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 1e-12 else 0.0


def _center_distance(a, b):
    acx = (a[0] + a[2]) / 2
    acy = (a[1] + a[3]) / 2
    bcx = (b[0] + b[2]) / 2
    bcy = (b[1] + b[3]) / 2
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


def _bbox_zone_hit(box, zone_points, image_width, image_height):
    """Return whether the vehicle should count as occupying the zone.

    The primary point is still the bottom-center contact point. To avoid a
    moving vehicle flickering around zone borders, also sample the bbox center
    and the lower-left/lower-right contact area. This does not require the
    vehicle to be static; it only checks whether the tracked vehicle overlaps
    the configured area in the camera view.
    """
    x1, y1, x2, y2 = box
    samples = [
        ((x1 + x2) / 2 / image_width, y2 / image_height),
        ((x1 + x2) / 2 / image_width, (y1 + y2) / 2 / image_height),
        (x1 / image_width, y2 / image_height),
        (x2 / image_width, y2 / image_height),
    ]
    return any(_point_in_polygon(px, py, zone_points) for px, py in samples), samples[0]


def _find_reassociation_candidate(registry, current_tid, zone_name, norm_box, timestamp):
    best_tid = None
    best_score = -1.0
    for old_tid, zones in registry.items():
        if old_tid == current_tid or zone_name not in zones:
            continue
        state = zones[zone_name]
        last_seen = state.get("last_seen", timestamp)
        if timestamp - last_seen > _ID_SWITCH_GRACE_SECONDS:
            continue
        old_box = state.get("last_box")
        if not old_box:
            continue
        iou = _box_iou(norm_box, old_box)
        distance = _center_distance(norm_box, old_box)
        if iou < _REASSOC_IOU_THRESHOLD and distance > _REASSOC_CENTER_DISTANCE:
            continue
        score = iou - distance
        if score > best_score:
            best_score = score
            best_tid = old_tid
    return best_tid


def detect_violations(
    vehicles,
    no_parking_zones,
    timestamp,
    parking_threshold,
    image_width,
    image_height,
    device_id="",
):
    try:
        if device_id not in _state:
            _state[device_id] = {}

        registry = _state[device_id]
        active_track_ids = set()
        alerts = []
        current_zone_hits = {}

        for v in vehicles:
            tid = v["track_id"]
            active_track_ids.add(tid)

            x1, y1, x2, y2 = v["box"]
            norm_box = _normalize_box((x1, y1, x2, y2), image_width, image_height)

            if tid not in registry:
                registry[tid] = {}

            for zone in no_parking_zones:
                zone_name = zone["name"]
                points = zone["points"]
                in_zone, contact_point = _bbox_zone_hit(
                    (x1, y1, x2, y2),
                    points,
                    image_width,
                    image_height,
                )

                if not in_zone:
                    continue

                current_zone_hits.setdefault(tid, set()).add(zone_name)

                if zone_name not in registry[tid]:
                    old_tid = _find_reassociation_candidate(registry, tid, zone_name, norm_box, timestamp)
                    if old_tid is not None:
                        registry[tid][zone_name] = registry[old_tid].pop(zone_name)
                    else:
                        registry[tid][zone_name] = {
                            "entry_time": timestamp,
                            "last_seen": timestamp,
                        }

                registry[tid][zone_name]["last_seen"] = timestamp
                registry[tid][zone_name]["last_box"] = norm_box
                registry[tid][zone_name]["contact_point"] = contact_point

                entry_time = registry[tid][zone_name]["entry_time"]
                duration = timestamp - entry_time

                if duration >= parking_threshold:
                    alerts.append({
                        "vehicle_id": tid,
                        "zone_name": zone_name,
                        "duration": round(duration, 2),
                        "box": [float(x1), float(y1), float(x2), float(y2)],
                        "contact_point": contact_point,
                    })

        # If a vehicle is temporarily missed, keep its timer and keep reporting
        # timeout during a short grace period. This prevents the frontend count
        # from flickering to zero when detection/tracking drops for a moment.
        for tid in list(registry.keys()):
            hit_zones = current_zone_hits.get(tid, set())
            for zone_name in list(registry[tid].keys()):
                state = registry[tid][zone_name]
                last_seen = state.get("last_seen", timestamp)
                missing_for = timestamp - last_seen

                if tid not in active_track_ids:
                    if missing_for > _TRACK_MISSING_GRACE_SECONDS:
                        del registry[tid][zone_name]
                    elif timestamp - state.get("entry_time", timestamp) >= parking_threshold:
                        alerts.append({
                            "vehicle_id": tid,
                            "zone_name": zone_name,
                            "duration": round(timestamp - state["entry_time"], 2),
                            "box": [],
                            "contact_point": state.get("contact_point"),
                        })
                    continue

                if zone_name in hit_zones:
                    continue

                if missing_for > _ZONE_EXIT_GRACE_SECONDS:
                    del registry[tid][zone_name]

        empty_tids = [tid for tid in registry if not registry[tid]]
        for tid in empty_tids:
            del registry[tid]

        return alerts
    except Exception:
        return []
