import sys
import time
import gc
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from loguru import logger
from ultralytics import YOLO

# ── 路径 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
VIDEO_PATH = ROOT / "t.mp4"
YOLO_PATH = ROOT / "yolo26s.pt"
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(exist_ok=True)

# ── 参数 ──────────────────────────────────────────────
BANK_FRAMES = 30           # 背景建模预热帧数
ALERT_FRAMES = 30          # 追踪持续 N 帧后告警 (约1秒@30fps)
MAX_AGE = 15               # 追踪丢失后保留帧数
MIN_AREA = 300             # 前景最小面积 (像素)
IOU_THRESH = 0.3           # IoU 匹配阈值
DIFF_THRESH = 25           # 背景差分阈值
EDGE_MARGIN = 4            # 排除触碰帧边缘的 blob (像素)

# Stage 2: YOLO 已知正常物体 (COCO 类别)
NORMAL_CLASSES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
    5: "bus", 6: "train", 7: "truck",
    9: "traffic light", 10: "fire hydrant", 11: "stop sign",
    12: "parking meter", 13: "bench",
}

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ═══════════════════════════════════════════════════════
# Stage 1: 变化检测与 ROI 提取
# ═══════════════════════════════════════════════════════

class ChangeDetector:
    """
    双路背景模型:
      - 中值背景: 静态参考, 捕获新出现物体
      - 运行平均背景: 自适应光照漂移, alpha=0.01
    合并两路差分 → 前景 blob
    """

    def __init__(self, min_area: int = MIN_AREA,
                 diff_thresh: int = DIFF_THRESH):
        self.min_area = min_area
        self.diff_thresh = diff_thresh
        self.median_bg: Optional[np.ndarray] = None   # 静态中值背景
        self.running_bg: Optional[np.ndarray] = None  # 运行平均背景 (float32)
        self.alpha = 0.01

        self.open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

        self._warmup_buffer: list[np.ndarray] = []
        self._warmed = False
        self._frame_h: int = 0
        self._frame_w: int = 0

    def warmup_feed(self, frame: np.ndarray) -> bool:
        """逐帧喂入预热, 返回 True 表示完成"""
        if self._warmed:
            return True
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._warmup_buffer.append(gray.copy())
        self._frame_h, self._frame_w = gray.shape
        if len(self._warmup_buffer) >= BANK_FRAMES:
            stack = np.stack(self._warmup_buffer, axis=0)
            self.median_bg = np.median(stack, axis=0).astype(np.uint8)
            self.running_bg = self.median_bg.astype(np.float32)
            self._warmup_buffer.clear()
            self._warmed = True
            logger.info(f"[Stage1] 中值背景就绪 (median={self.median_bg.mean():.1f})")
        return self._warmed

    def detect(self, frame: np.ndarray) -> list[dict]:
        """返回前景 blob 列表"""
        H, W = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 中值背景差分: 捕获任何与静态背景不同的区域
        diff_median = cv2.absdiff(gray, self.median_bg)

        # 运行平均差分: 捕获快速出现/移动的物体
        diff_running = cv2.absdiff(gray, self.running_bg.astype(np.uint8))

        # 取最大值合并 (OR 语义: 任一模型认为异常即候选)
        diff = cv2.max(diff_median, diff_running)

        fg = (diff > self.diff_thresh).astype(np.uint8)

        # 更新运行平均 (仅非前景像素, 防止异常被吸收)
        update_mask = (fg == 0)
        self.running_bg[update_mask] = (
            (1.0 - self.alpha) * self.running_bg[update_mask] +
            self.alpha * gray[update_mask]
        )

        # 形态学
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self.open_k)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self.close_k)

        # 连通域 + 过滤
        n, labels, stats, centroids = cv2.connectedComponentsWithStats(fg, 8)
        blobs = []
        max_area = H * W * 0.35
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < self.min_area:
                continue
            if area > max_area:
                continue
            if (x < EDGE_MARGIN or y < EDGE_MARGIN or
                    x + w > W - EDGE_MARGIN or y + h > H - EDGE_MARGIN):
                continue
            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 15:
                continue
            blobs.append({
                "bbox": [x, y, x + w, y + h],
                "centroid": [centroids[i][0], centroids[i][1]],
                "area": int(area),
            })
        return blobs

    @property
    def is_ready(self) -> bool:
        return self._warmed


# ═══════════════════════════════════════════════════════
# Stage 2: 正常物体检测 (YOLO26n)
# ═══════════════════════════════════════════════════════

class NormalObjectDetector:
    """YOLO26n 检测正常交通物体, 输出归一化边界框列表"""

    def __init__(self, model_path: str, conf: float = 0.15):
        logger.info(f"[Stage2] 加载 YOLO: {model_path}")
        self.model = YOLO(model_path)
        self.model.to(DEVICE)
        self.conf = conf
        self.imgsz = 640  # YOLO 推理分辨率
        logger.info(f"[Stage2] YOLO 就绪 ({DEVICE})")

    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        返回正常物体: [{"bbox":[x1,y1,x2,y2], "cls":int, "label":str, "conf":float}, ...]
        """
        results = self.model(frame, verbose=False, conf=self.conf, imgsz=self.imgsz, device=DEVICE)
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []

        dets = []
        for box in boxes:
            cls_id = int(box.cls[0])
            if cls_id in NORMAL_CLASSES:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                dets.append({
                    "bbox": [x1, y1, x2, y2],
                    "cls": cls_id,
                    "label": NORMAL_CLASSES[cls_id],
                    "conf": float(box.conf[0]),
                })
        return dets


# ═══════════════════════════════════════════════════════
# Stage 3: 目标追踪与异常判定
# ═══════════════════════════════════════════════════════

class AnomalyTracker:
    """IoU 多目标追踪器: 持久存在 + 非 YOLO 物体 → 异常告警"""

    def __init__(self, alert_frames: int = ALERT_FRAMES,
                 max_age: int = MAX_AGE, iou_thresh: float = IOU_THRESH):
        self.alert_frames = alert_frames
        self.max_age = max_age
        self.iou_thresh = iou_thresh
        self.tracks: dict[int, dict] = {}
        self.next_id = 0
        self.frame_count = 0
        self.total_alerts = 0

    def update(self, fg_blobs: list[dict],
               normal_dets: list[dict]) -> tuple[list[dict], list[dict]]:
        """
        Args:
            fg_blobs: Stage1 输出的前景 blob
            normal_dets: Stage2 输出的正常物体
        Returns:
            active_tracks: 所有活跃追踪
            alerts: 新触发的告警
        """
        self.frame_count += 1

        # 从前景 blob 中排除被 YOLO 检测到的正常物体
        unknown_blobs = self._exclude_normal(fg_blobs, normal_dets)

        # IoU 匹配
        matches, unmatched_dets, unmatched_trks = self._associate(unknown_blobs)

        # 更新匹配到的追踪
        for det_idx, trk_id in matches:
            d = unknown_blobs[det_idx]
            trk = self.tracks[trk_id]
            trk["bbox"] = d["bbox"]
            trk["centroid"] = d["centroid"]
            trk["area"] = d["area"]
            trk["age"] += 1
            trk["time_since_update"] = 0

        # 新追踪
        for det_idx in unmatched_dets:
            d = unknown_blobs[det_idx]
            self.tracks[self.next_id] = {
                "track_id": self.next_id,
                "bbox": d["bbox"],
                "centroid": d["centroid"],
                "area": d["area"],
                "age": 1,
                "time_since_update": 0,
                "alerted": False,
            }
            self.next_id += 1

        # 未匹配追踪老化
        for trk_id in unmatched_trks:
            self.tracks[trk_id]["time_since_update"] += 1
            self.tracks[trk_id]["age"] += 1

        # 检测告警
        alerts = []
        for trk_id in list(self.tracks):
            trk = self.tracks[trk_id]
            if trk["time_since_update"] > self.max_age:
                del self.tracks[trk_id]
                continue
            if (not trk["alerted"] and
                    trk["age"] >= self.alert_frames and
                    trk["time_since_update"] == 0):
                trk["alerted"] = True
                self.total_alerts += 1
                logger.info(
                    f"[ALERT #{self.total_alerts}] "
                    f"Track#{trk['track_id']} | "
                    f"BBox:({int(trk['bbox'][0])},{int(trk['bbox'][1])},"
                    f"{int(trk['bbox'][2])},{int(trk['bbox'][3])}) | "
                    f"存活: {trk['age']} 帧"
                )
                alerts.append(trk)

        active = [t for t in self.tracks.values()
                  if t["time_since_update"] <= self.max_age]

        return active, alerts

    def _exclude_normal(self, fg_blobs: list[dict],
                        normal_dets: list[dict]) -> list[dict]:
        """排除与 YOLO 正常物体重叠的前景 blob"""
        if not normal_dets:
            return fg_blobs

        unknown = []
        for blob in fg_blobs:
            bx1, by1, bx2, by2 = blob["bbox"]
            excluded = False
            for nd in normal_dets:
                nx1, ny1, nx2, ny2 = nd["bbox"]
                iou_val = _box_iou([bx1, by1, bx2, by2],
                                    [nx1, ny1, nx2, ny2])
                if iou_val > 0.1:  # 低阈值: 任何重叠即排除
                    excluded = True
                    break
            if not excluded:
                unknown.append(blob)
        return unknown

    def _associate(self, blobs: list[dict]) -> tuple:
        """IoU 匈牙利匹配"""
        active = [t for t in self.tracks.values()
                  if t["time_since_update"] <= self.max_age]
        if not active or not blobs:
            return ([], list(range(len(blobs))),
                    [t["track_id"] for t in active]) if blobs else ([], [], [])

        n_det, n_trk = len(blobs), len(active)
        iou_mat = np.zeros((n_det, n_trk), dtype=np.float32)
        for di in range(n_det):
            for ti in range(n_trk):
                iou_mat[di, ti] = _box_iou(blobs[di]["bbox"],
                                            active[ti]["bbox"])

        # 贪心匹配 (小规模, 无需 scipy)
        matches = []
        used_det, used_trk = set(), set()
        # 按 IoU 降序贪心
        iou_flat = [(iou_mat[di, ti], di, ti)
                    for di in range(n_det) for ti in range(n_trk)]
        iou_flat.sort(key=lambda x: x[0], reverse=True)
        for iou_val, di, ti in iou_flat:
            if iou_val < self.iou_thresh:
                break
            if di not in used_det and ti not in used_trk:
                matches.append((di, active[ti]["track_id"]))
                used_det.add(di)
                used_trk.add(ti)

        unmatched_dets = [i for i in range(n_det) if i not in used_det]
        unmatched_trks = [active[i]["track_id"] for i in range(n_trk)
                           if i not in used_trk]
        return matches, unmatched_dets, unmatched_trks


def _box_iou(a: list, b: list) -> float:
    """两个 bbox 的 IoU"""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-8)


# ═══════════════════════════════════════════════════════
# 可视化
# ═══════════════════════════════════════════════════════

def draw_output(frame: np.ndarray,
                normal_dets: list[dict],
                active_tracks: list[dict],
                anomaly_tracks: list[dict]) -> np.ndarray:
    """
    输出帧:
      - 绿色实线框 + 标签 = 正常物体 (YOLO)
      - 红色实线框 + ANOMALY 标签 = 已告警异常
      - 橙色虚线框 = 追踪中未告警的未知物体
    """
    out = frame.copy()

    # YOLO 正常物体: 绿色框
    for nd in normal_dets:
        x1, y1, x2, y2 = [int(v) for v in nd["bbox"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{nd['label']} {nd['conf']:.1f}"
        cv2.putText(out, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    # 已告警异常: 红色实线框
    alerted_ids = {t["track_id"] for t in anomaly_tracks}
    for trk in active_tracks:
        x1, y1, x2, y2 = [int(v) for v in trk["bbox"]]
        if trk["track_id"] in alerted_ids:
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(out, f"ANOMALY #{trk['track_id']}",
                        (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        elif trk["age"] > ALERT_FRAMES * 0.5:
            # 追踪中但未达告警阈值: 橙色虚线
            _draw_dashed_rect(out, (x1, y1), (x2, y2), (0, 165, 255), 1)

    # 左上角信息
    cv2.putText(out, f"Normal: {len(normal_dets)} | Tracks: {len(active_tracks)} | Alerts: {len(anomaly_tracks)}",
                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def _draw_dashed_rect(img, pt1, pt2, color, thickness=1, dash_len=8):
    """绘制虚线矩形"""
    x1, y1 = pt1
    x2, y2 = pt2
    # 上边
    for x in range(x1, x2, dash_len * 2):
        cv2.line(img, (x, y1), (min(x + dash_len, x2), y1), color, thickness)
    # 下边
    for x in range(x1, x2, dash_len * 2):
        cv2.line(img, (x, y2), (min(x + dash_len, x2), y2), color, thickness)
    # 左边
    for y in range(y1, y2, dash_len * 2):
        cv2.line(img, (x1, y), (x1, min(y + dash_len, y2)), color, thickness)
    # 右边
    for y in range(y1, y2, dash_len * 2):
        cv2.line(img, (x2, y), (x2, min(y + dash_len, y2)), color, thickness)


def gpu_mem_info() -> str:
    if not torch.cuda.is_available():
        return "N/A"
    a = torch.cuda.memory_allocated() / 1024**2
    r = torch.cuda.memory_reserved() / 1024**2
    return f"alloc={a:.0f}MB, reserved={r:.0f}MB"


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════

def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    logger.info("=" * 60)
    logger.info("三阶段异常检测流水线 — 单元测试")
    logger.info(f"设备: {DEVICE}")
    logger.info(f"视频: {VIDEO_PATH}")
    logger.info(f"YOLO: {YOLO_PATH}")
    logger.info(f"GPU: {gpu_mem_info()}")
    logger.info("=" * 60)

    # ── 初始化各阶段 ────────────────────────────
    stage1 = ChangeDetector()
    stage2 = NormalObjectDetector(str(YOLO_PATH))
    stage3 = AnomalyTracker()
    logger.info(f"[Init] GPU: {gpu_mem_info()}")

    cap = cv2.VideoCapture(str(VIDEO_PATH))
    assert cap.isOpened(), f"无法打开: {VIDEO_PATH}"
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    # 获取真实帧尺寸
    ok, test_frame = cap.read()
    assert ok
    H, W = test_frame.shape[:2]
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    logger.info(f"视频: {total_frames} 帧, {fps:.1f} FPS, {W}x{H}")

    # ── Stage1 预热 ────────────────────────────
    logger.info(f"[预热] Stage1 背景建模 ({BANK_FRAMES} 帧)...")
    warmup_count = 0
    while not stage1.is_ready and warmup_count < total_frames:
        ok, frame = cap.read()
        if not ok:
            break
        stage1.warmup_feed(frame)
        warmup_count += 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, warmup_count)
    logger.info(f"[预热] 完成, 消耗 {warmup_count} 帧")

    # ── 视频输出 ────────────────────────────────
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    vw = cv2.VideoWriter(str(OUT_DIR / "anomaly_output.mp4"),
                         fourcc, fps, (W, H))
    if not vw.isOpened():
        logger.error("视频写入器打开失败")
        cap.release()
        return

    # ── 主循环 ──────────────────────────────────
    logger.info("[运行] 开始处理...")
    total_alerts = 0
    frame_idx = warmup_count
    frame_idx = warmup_count
    stage1_times, stage2_times, stage3_times = [], [], []

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        # Stage 1: 变化检测
        t0 = time.perf_counter()
        fg_blobs = stage1.detect(frame)
        t1 = time.perf_counter()

        # Stage 2: 正常物体检测
        normal_dets = stage2.detect(frame)
        t2 = time.perf_counter()

        # Stage 3: 追踪 + 异常判定
        active_tracks, alerts = stage3.update(fg_blobs, normal_dets)
        t3 = time.perf_counter()

        stage1_times.append((t1 - t0) * 1000)
        stage2_times.append((t2 - t1) * 1000)
        stage3_times.append((t3 - t2) * 1000)

        total_alerts += len(alerts)

        # 绘制输出
        anomaly_tracks = [t for t in active_tracks if t["alerted"]]
        out_frame = draw_output(frame, normal_dets, active_tracks, anomaly_tracks)
        vw.write(out_frame)

        if frame_idx % 100 == 0:
            s1 = np.mean(stage1_times[-100:])
            s2 = np.mean(stage2_times[-100:])
            s3 = np.mean(stage3_times[-100:])
            logger.info(
                f"  帧 {frame_idx}/{total_frames} | "
                f"S1={s1:.1f}ms S2={s2:.1f}ms S3={s3:.1f}ms | "
                f"Blobs={len(fg_blobs)} Normal={len(normal_dets)} Tracks={len(active_tracks)} Alerts={total_alerts} | "
                f"GPU: {gpu_mem_info()}"
            )

    cap.release()
    vw.release()

    # ── 报告 ────────────────────────────────────
    logger.info("=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)

    if stage1_times:
        s1 = np.array(stage1_times)
        s2 = np.array(stage2_times)
        s3 = np.array(stage3_times)
        total = s1 + s2 + s3

        logger.info(f"\n── 延迟统计 (每帧) ──")
        logger.info(f"  Stage1 (变化检测):  mean={s1.mean():.1f}ms  median={np.median(s1):.1f}ms  p99={np.percentile(s1, 99):.1f}ms")
        logger.info(f"  Stage2 (正常检测):  mean={s2.mean():.1f}ms  median={np.median(s2):.1f}ms  p99={np.percentile(s2, 99):.1f}ms")
        logger.info(f"  Stage3 (追踪过滤):  mean={s3.mean():.1f}ms  median={np.median(s3):.1f}ms  p99={np.percentile(s3, 99):.1f}ms")
        logger.info(f"  总计:              mean={total.mean():.1f}ms  median={np.median(total):.1f}ms  p99={np.percentile(total, 99):.1f}ms")
        logger.info(f"  理论 FPS: {1000 / np.median(total):.1f}")

    logger.info(f"\n── 异常告警 ──")
    logger.info(f"  总告警数: {total_alerts}")
    if total_alerts == 0:
        logger.info(f"  ℹ t.mp4 为纯交通场景, 无真实异常物体, 0告警符合预期")

    logger.info(f"\n── 输出 ──")
    logger.info(f"  视频: {OUT_DIR / 'anomaly_output.mp4'} ({W}x{H}, {frame_idx - warmup_count} 帧)")
    logger.info(f"  GPU: {gpu_mem_info()}")

    # 清理
    del stage1, stage2, stage3
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info(f"清理后 GPU: {gpu_mem_info()}")


if __name__ == "__main__":
    main()
