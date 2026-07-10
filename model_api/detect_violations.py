_state = {}


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

        for v in vehicles:
            tid = v["track_id"]
            active_track_ids.add(tid)

            # 车辆底部中心归一化坐标
            x1, y1, x2, y2 = v["box"]
            cx = ((x1 + x2) / 2) / image_width
            cy = y2 / image_height
            contact_point = [cx, cy]

            for zone in no_parking_zones:
                zone_name = zone["name"]
                points = zone["points"]

                in_zone = _point_in_polygon(cx, cy, points)

                if in_zone:
                    if tid not in registry:
                        registry[tid] = {}

                    if zone_name not in registry[tid]:
                        registry[tid][zone_name] = timestamp

                    entry_time = registry[tid][zone_name]
                    duration = timestamp - entry_time

                    if duration >= parking_threshold:
                        alerts.append({
                            "vehicle_id": tid,
                            "zone_name": zone_name,
                            "duration": round(duration, 2),
                            "box": [float(x1), float(y1), float(x2), float(y2)],
                            "contact_point": contact_point,
                        })
                else:
                    # 离开该禁停区则清除
                    if tid in registry and zone_name in registry[tid]:
                        del registry[tid][zone_name]

        # 离开画面的车辆清除注册
        stale_tids = [tid for tid in registry if tid not in active_track_ids]
        for tid in stale_tids:
            del registry[tid]

        # 清理空洞（车辆记录中无zone的条目）
        empty_tids = [tid for tid in registry if not registry[tid]]
        for tid in empty_tids:
            del registry[tid]

        return alerts
    except Exception:
        return []
