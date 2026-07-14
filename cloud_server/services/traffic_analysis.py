"""Vehicle-count congestion metrics and DeepSeek report generation."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from statistics import mean
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cloud_server.config import BASE_DIR, TRAFFIC_ANALYSIS_CONFIG


def _load_deepseek_api_key() -> str:
    """Load the key from the environment first, then the git-ignored local file."""
    config = TRAFFIC_ANALYSIS_CONFIG
    key_env = str(config.get("api_key_env", "DEEPSEEK_API_KEY"))
    api_key = os.environ.get(key_env, "").strip()
    if api_key:
        return api_key

    key_file = str(config.get("api_key_file", "secrets/deepseek.env"))
    key_path = key_file if os.path.isabs(key_file) else os.path.join(BASE_DIR, key_file)
    try:
        with open(key_path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                if name.strip() == key_env:
                    return value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def _valid_vehicle_count(frame: dict) -> int:
    """Count distinct tracked vehicles with valid IPM world coordinates."""
    identities: set[str] = set()
    anonymous_count = 0
    for index, vehicle in enumerate(frame.get("vehicles") or []):
        world = vehicle.get("world")
        if not isinstance(world, list) or len(world) < 2:
            continue
        try:
            float(world[0])
            float(world[1])
        except (TypeError, ValueError):
            continue
        vehicle_id = vehicle.get("id")
        if vehicle_id is None:
            anonymous_count += 1
        else:
            identities.add(str(vehicle_id))
    return len(identities) + anonymous_count


def calculate_count_metrics(frames: list[dict], capacity: int = 3) -> dict:
    """Calculate count-only metrics for a small school sand-table scene."""
    if not frames:
        raise ValueError("至少需要一帧车辆坐标数据")

    capacity = max(1, int(capacity))
    normalized = sorted(frames, key=lambda frame: float(frame.get("timestamp_ms", 0)))
    timeline = [
        {
            "timestamp_ms": max(0, int(float(frame.get("timestamp_ms", 0)))),
            "count": _valid_vehicle_count(frame),
        }
        for frame in normalized
    ]
    counts = [point["count"] for point in timeline]
    duration_ms = max(0, timeline[-1]["timestamp_ms"] - timeline[0]["timestamp_ms"])

    # One point per second is compact enough to send to the language model.
    buckets: dict[int, list[int]] = defaultdict(list)
    for point in timeline:
        relative_ms = point["timestamp_ms"] - timeline[0]["timestamp_ms"]
        buckets[relative_ms // 1000].append(point["count"])
    count_timeline = [
        {"second": second, "count": round(mean(values), 2)}
        for second, values in sorted(buckets.items())
    ]

    window_start = timeline[0]["timestamp_ms"]
    window_end = timeline[-1]["timestamp_ms"]
    first_boundary = window_start + min(5000, duration_ms)
    last_boundary = window_end - min(5000, duration_ms)
    first_counts = [point["count"] for point in timeline if point["timestamp_ms"] <= first_boundary] or counts[:1]
    last_counts = [point["count"] for point in timeline if point["timestamp_ms"] >= last_boundary] or counts[-1:]
    first_average = mean(first_counts)
    last_average = mean(last_counts)
    change = last_average - first_average
    trend = "加重" if change > 0.5 else "缓解" if change < -0.5 else "稳定"

    average_count = mean(counts)
    two_or_more_ratio = sum(count >= min(2, capacity) for count in counts) / len(counts)
    full_capacity_ratio = sum(count >= capacity for count in counts) / len(counts)

    if average_count < 0.3:
        level = "空闲"
    elif average_count < min(1.2, capacity * 0.45):
        level = "畅通"
    elif average_count < capacity * 0.74:
        level = "轻度拥堵"
    elif full_capacity_ratio < 0.6:
        level = "中度拥堵"
    else:
        level = "严重拥堵"

    score = round(min(100, max(0, (
        average_count / capacity * 60
        + max(counts) / capacity * 20
        + full_capacity_ratio * 15
        + (5 if trend == "加重" else 0)
    ))))

    return {
        "duration_ms": duration_ms,
        "frame_count": len(timeline),
        "capacity": capacity,
        "current_count": counts[-1],
        "average_count": round(average_count, 2),
        "maximum_count": max(counts),
        "two_or_more_ratio": round(two_or_more_ratio, 3),
        "full_capacity_ratio": round(full_capacity_ratio, 3),
        "first_5s_average": round(first_average, 2),
        "last_5s_average": round(last_average, 2),
        "trend": trend,
        "level": level,
        "score": score,
        "count_timeline": count_timeline,
    }


def build_rule_report(metrics: dict) -> dict:
    level = metrics["level"]
    trend = metrics["trend"]
    average = metrics["average_count"]
    maximum = metrics["maximum_count"]
    full_percent = round(metrics["full_capacity_ratio"] * 100)
    return {
        "overall_level": level,
        "score": metrics["score"],
        "confidence": 0.9 if metrics["duration_ms"] >= 10000 else 0.7,
        "trend": trend,
        "summary": (
            f"最近 {metrics['duration_ms'] / 1000:.1f} 秒平均检测到 {average} 辆车，"
            f"最多同时出现 {maximum} 辆，满载画面占比 {full_percent}%。"
            f"综合判断为{level}，车辆数量趋势为{trend}。"
        ),
        "evidence": [
            f"平均车辆数 {average} 辆，沙盘容量按 {metrics['capacity']} 辆计算",
            f"最高同时出现 {maximum} 辆车",
            f"满载画面占比 {full_percent}%",
            f"最初5秒平均 {metrics['first_5s_average']} 辆，最近5秒平均 {metrics['last_5s_average']} 辆",
        ],
        "recommendations": _recommendations(level, trend),
        "limitations": ["报告仅依据车辆数量判断，不包含速度、真实距离和道路通行能力分析"],
    }


def _recommendations(level: str, trend: str) -> list[str]:
    if level in {"中度拥堵", "严重拥堵"}:
        advice = ["关注该摄像头覆盖路段的车辆聚集情况", "检查下游路口或沙盘信号灯的放行状态"]
    elif level == "轻度拥堵":
        advice = ["继续观察车辆数量变化，避免车辆进一步聚集"]
    else:
        advice = ["当前无需采取额外疏导措施"]
    if trend == "加重":
        advice.append("车辆数量正在增加，建议提高该路段监控优先级")
    return advice


def _deepseek_request(metrics: dict, camera_id: str, lane_id: str) -> dict:
    config = TRAFFIC_ANALYSIS_CONFIG
    key_env = str(config.get("api_key_env", "DEEPSEEK_API_KEY"))
    api_key = _load_deepseek_api_key()
    if not api_key:
        key_file = config.get("api_key_file", "secrets/deepseek.env")
        raise RuntimeError(f"未在环境变量 {key_env} 或 {key_file} 中配置密钥")

    model = str(config.get("deepseek_model", "deepseek-v4-pro"))
    base_url = str(config.get("deepseek_base_url", "https://api.deepseek.com")).rstrip("/")
    prompt_data = {
        "scene": "学校智慧交通沙盘",
        "camera_id": camera_id,
        "lane_id": lane_id,
        "statistics": {key: value for key, value in metrics.items() if key != "count_timeline"},
        "count_timeline": metrics["count_timeline"],
    }
    system_prompt = (
        "你是学校智慧交通沙盘的拥堵分析助手。只依据提供的车辆数量指标进行判断，"
        "不要计算或猜测车辆速度、真实距离、道路长度。规则引擎给出的等级和分数是事实基线。"
        "请输出JSON对象，字段必须包括 overall_level、score、confidence、trend、summary、"
        "evidence、recommendations、limitations；evidence、recommendations、limitations必须为字符串数组。"
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False)},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
        "max_tokens": 1000,
    }, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=float(config.get("timeout_seconds", 30))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"DeepSeek API 返回 {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"DeepSeek API 连接失败: {exc}") from exc

    content = result["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    report = json.loads(content)
    required = {"overall_level", "score", "confidence", "trend", "summary", "evidence", "recommendations", "limitations"}
    if not required.issubset(report):
        raise RuntimeError("DeepSeek 返回的报告字段不完整")
    if not isinstance(report.get("summary"), str):
        raise RuntimeError("DeepSeek 返回的 summary 格式错误")
    for field in ("evidence", "recommendations", "limitations"):
        if not isinstance(report.get(field), list) or not all(isinstance(item, str) for item in report[field]):
            raise RuntimeError(f"DeepSeek 返回的 {field} 格式错误")
    return report


def analyze_traffic(frames: list[dict], camera_id: str, lane_id: str, capacity: int | None = None) -> dict:
    configured_capacity = int(TRAFFIC_ANALYSIS_CONFIG.get("camera_capacity", 3))
    metrics = calculate_count_metrics(frames, capacity or configured_capacity)
    rule_report = build_rule_report(metrics)
    if not TRAFFIC_ANALYSIS_CONFIG.get("enabled", True):
        return {"metrics": metrics, "report": rule_report, "source": "rule", "llm_error": "大模型分析已禁用"}
    try:
        report = _deepseek_request(metrics, camera_id, lane_id)
        # Numeric classification remains deterministic; DeepSeek writes the narrative.
        report["overall_level"] = metrics["level"]
        report["score"] = metrics["score"]
        report["trend"] = metrics["trend"]
        return {"metrics": metrics, "report": report, "source": "deepseek-v4", "llm_error": None}
    except Exception as exc:
        return {"metrics": metrics, "report": rule_report, "source": "rule_fallback", "llm_error": str(exc)}
