from cloud_server.services.traffic_analysis import build_rule_report, calculate_count_metrics


def _frame(timestamp_ms, count):
    return {
        "timestamp_ms": timestamp_ms,
        "vehicles": [
            {"id": index, "world": [100 + index, 200 + index]}
            for index in range(count)
        ],
    }


def test_count_metrics_detects_full_capacity_congestion():
    frames = [_frame(second * 1000, 3) for second in range(15)]
    metrics = calculate_count_metrics(frames, capacity=3)
    assert metrics["average_count"] == 3
    assert metrics["full_capacity_ratio"] == 1
    assert metrics["level"] == "严重拥堵"
    assert metrics["score"] == 95


def test_count_metrics_detects_increasing_trend():
    frames = [_frame(second * 1000, 1 if second < 8 else 2) for second in range(15)]
    metrics = calculate_count_metrics(frames, capacity=3)
    assert metrics["trend"] == "加重"
    assert metrics["maximum_count"] == 2
    assert build_rule_report(metrics)["overall_level"] == metrics["level"]


def test_invalid_coordinates_are_not_counted():
    frames = [{"timestamp_ms": 0, "vehicles": [{"id": 1, "world": None}, {"id": 2, "world": [1, 2]}]}]
    metrics = calculate_count_metrics(frames, capacity=3)
    assert metrics["current_count"] == 1
