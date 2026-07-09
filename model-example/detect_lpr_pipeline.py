"""
车辆检测 + 车牌识别流水线
YOLO 检测车辆 → ROI 放大 → HyperLPR3 检测+识别车牌

用法:
    python detect_lpr_pipeline.py --source test.mp4                    # 视频文件
    python detect_lpr_pipeline.py --source 0                           # 摄像头
    python detect_lpr_pipeline.py --source test.mp4 --no-show --save   # 静默保存

依赖:
    pip install ultralytics hyperlpr3 opencv-python numpy
"""

import os
import sys
import argparse
import time
import cv2
import numpy as np
from ultralytics import YOLO
import hyperlpr3 as lpr3
from hyperlpr3.inference.pipeline import get_rotate_crop_image

# ---- Windows 终端 UTF-8 编码修复 ----
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# ============================================================
# 工具函数
# ============================================================

def unicode_hex(text: str) -> str:
    """将字符串转为 Unicode 码点，用于诊断中文编码"""
    return " ".join(f"U+{ord(c):04X}" for c in text)


# ============================================================
# 主流水线类
# ============================================================

class VehicleLPRPipeline:
    """车辆检测 + 车牌识别流水线 (YOLO + HyperLPR3)"""

    def __init__(
        self,
        yolo_model_path: str = "yolo26n.pt",
        vehicle_classes: list = None,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        imgsz: int = 640,
        gpu: bool = True,
    ):
        """
        Args:
            yolo_model_path: YOLO 模型权重路径
            vehicle_classes: YOLO 中车辆的类别 ID 列表 (COCO: 2=car, 5=bus, 7=truck)
            conf_threshold: YOLO 置信度阈值
            iou_threshold: YOLO NMS IoU 阈值
            imgsz: YOLO 推理分辨率
            gpu: 保留参数（HyperLPR3 自动选择设备）
        """
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.imgsz = imgsz

        # 车辆类别（COCO 默认：2=car, 5=bus, 7=truck, 3=motorcycle）
        self.vehicle_classes = vehicle_classes or [2, 3, 5, 7]

        # ---- 加载 YOLO 模型 ----
        print(f"[加载] YOLO 模型: {yolo_model_path}")
        self.yolo = YOLO(yolo_model_path)
        self.yolo_names = self.yolo.names if hasattr(self.yolo, 'names') else {}
        print(f"[信息] YOLO 类别: {len(self.yolo_names)} 类")
        print(f"[信息] 车辆类别 ID: {self.vehicle_classes}")

        # ---- 加载 HyperLPR3 ----
        print(f"[加载] HyperLPR3 车牌检测+识别引擎 ...")
        self.lpr = lpr3.LicensePlateCatcher()
        self.lpr_pipeline = self.lpr.pipeline
        self.lpr_rec = self.lpr_pipeline.recognizer
        # 降低检测阈值（远处小车牌也能检测到）
        self.lpr_pipeline.detector.box_threshold = 0.2
        print(f"[信息] HyperLPR3 加载完成 (检测阈值: 0.2)")

        # ---- 编码验证 ----
        test_plate = "京A12345"
        test_hex = unicode_hex(test_plate)
        print(f"[编码验证] 中文测试: '{test_plate}' -> hex=[{test_hex}]")
        print(f"[编码验证] 系统编码: stdout={sys.stdout.encoding}")

        # ---- 配置参数 ----
        self.roi_upscale_target = 800    # ROI 放大到至少 800px 宽
        self.landmark_expand = 0.18      # landmarks 向外扩展 18%

        # 统计
        self.frame_count = 0
        self.fps = 0
        self.fps_timer = time.time()

        # ---- 车辆追踪 (SORT-like IoU 匹配) ----
        self._tracks = {}               # {track_id: {bbox, cls_name, best_plate, plate_conf, last_seen, ...}}
        self._next_track_id = 0
        self._track_max_age = 30        # 30帧未见则移除追踪
        self._iou_match_threshold = 0.3  # IoU 匹配阈值
        self._global_frame = 0          # 持久帧计数器（不受 FPS 重置影响）
        self.plate_conf_threshold = 0.995  # 仅保留置信度 >= 0.995 的车牌结果

        # 调试：OCR 诊断计数器
        self._lpr_call_count = 0
        self._verbose = os.environ.get("LPR_VERBOSE", "").lower() in ("1", "true", "yes")

    def detect_vehicles(self, frame: np.ndarray) -> list:
        """
        使用 YOLO 检测车辆
        Returns:
            list[dict]: 每辆车 {bbox, cls_id, cls_name, conf}
        """
        results = self.yolo(
            frame,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.imgsz,
            classes=self.vehicle_classes,
            verbose=False,
        )

        vehicles = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                xyxy = boxes.xyxy[i].cpu().numpy()
                vehicles.append({
                    "bbox": tuple(map(int, xyxy)),     # (x1, y1, x2, y2)
                    "cls_id": cls_id,
                    "cls_name": self.yolo_names.get(cls_id, str(cls_id)),
                    "conf": conf,
                })
        return vehicles

    @staticmethod
    def _compute_iou(bbox1, bbox2):
        """计算两个边界框的 IoU"""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0.0

    def _match_tracks(self, detections: list, frame_num: int) -> list:
        """IoU 匹配：将新检测关联到已有追踪
        Args:
            detections: YOLO 检测结果列表
            frame_num: 当前帧号（全局持久）
        Returns:
            list[int]: 每个检测对应的 track_id
        """
        # 过滤活跃追踪
        active = {tid: t for tid, t in self._tracks.items()
                  if frame_num - t['last_seen'] <= self._track_max_age}

        if not active:
            track_ids = []
            for det in detections:
                tid = self._next_track_id
                self._next_track_id += 1
                self._tracks[tid] = {
                    'bbox': det['bbox'],
                    'cls_name': det['cls_name'],
                    'cls_conf': det['conf'],
                    'best_plate': '',
                    'plate_conf': 0.0,
                    'last_seen': frame_num,
                    'first_seen': frame_num,
                }
                track_ids.append(tid)
            return track_ids

        # 计算 IoU 矩阵
        track_bboxes = [t['bbox'] for t in active.values()]
        track_tids = list(active.keys())
        n_det, n_trk = len(detections), len(track_bboxes)
        iou_mat = np.zeros((n_det, n_trk))
        for i in range(n_det):
            for j in range(n_trk):
                iou_mat[i, j] = self._compute_iou(detections[i]['bbox'], track_bboxes[j])

        # 贪婪匹配：每个检测找最佳 IoU 追踪
        matched = set()
        track_ids = []
        for i, det in enumerate(detections):
            best_iou = self._iou_match_threshold
            best_j = -1
            for j in range(n_trk):
                if j in matched:
                    continue
                if iou_mat[i, j] > best_iou:
                    best_iou = iou_mat[i, j]
                    best_j = j

            if best_j >= 0:
                tid = track_tids[best_j]
                matched.add(best_j)
                self._tracks[tid].update({
                    'bbox': det['bbox'],
                    'cls_name': det['cls_name'],
                    'cls_conf': det['conf'],
                    'last_seen': frame_num,
                })
                track_ids.append(tid)
            else:
                tid = self._next_track_id
                self._next_track_id += 1
                self._tracks[tid] = {
                    'bbox': det['bbox'],
                    'cls_name': det['cls_name'],
                    'cls_conf': det['conf'],
                    'best_plate': '',
                    'plate_conf': 0.0,
                    'last_seen': frame_num,
                    'first_seen': frame_num,
                }
                track_ids.append(tid)

        # 清理过期追踪（超过 max_age 帧未出现）
        stale = [tid for tid, t in self._tracks.items()
                 if frame_num - t['last_seen'] > self._track_max_age]
        for tid in stale:
            t = self._tracks[tid]
            if t['best_plate'] and t['plate_conf'] >= self.plate_conf_threshold:
                print(f"[追踪结束] ID={tid} {t['cls_name']} → {t['best_plate']} (conf={t['plate_conf']:.3f})")
            del self._tracks[tid]

        return track_ids

    def recognize_plate_in_roi(self, frame: np.ndarray, vehicle_bbox: tuple):
        """
        HyperLPR3 流水线识别车牌：
        1. 裁剪车辆下半部 ROI
        2. 放大到至少 800px 宽
        3. HyperLPR3 检测器查找车牌
        4. 透视矫正 + 识别器读出车牌号
        5. landmarks 扩展 18% 捕获边缘字符
        """
        x1, y1, x2, y2 = vehicle_bbox
        img_h, img_w = frame.shape[:2]
        vehicle_h = y2 - y1
        vehicle_w = x2 - x1

        # ---- 1. 裁剪车辆下半部 ROI ----
        roi_y1 = max(0, y1 + int(vehicle_h * 0.35))
        roi_y2 = min(img_h, y2)
        roi_x1 = max(0, x1)
        roi_x2 = min(img_w, x2)
        vehicle_roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

        if vehicle_roi.size == 0 or vehicle_roi.shape[0] < 15 or vehicle_roi.shape[1] < 40:
            return "", 0.0

        raw_h, raw_w = vehicle_roi.shape[:2]

        # ---- 2. 放大 ROI ----
        scale = max(1.0, self.roi_upscale_target / raw_w)
        if scale > 1.0:
            vehicle_roi = cv2.resize(
                vehicle_roi,
                (int(raw_w * scale), int(raw_h * scale)),
                interpolation=cv2.INTER_CUBIC,
            )

        roi_h, roi_w = vehicle_roi.shape[:2]

        # ---- 3. HyperLPR3 检测车牌 ----
        dets = self.lpr_pipeline.detector(vehicle_roi)

        # 回退：ROI 中没检测到则用全图检测
        if len(dets) == 0:
            dets_full = self.lpr_pipeline.detector(frame)
            if len(dets_full) == 0:
                return "", 0.0
            # 取置信度最高且在车辆 bbox 内的
            best_in_vehicle = None
            for d in sorted(dets_full, key=lambda x: x[4], reverse=True):
                dcx = (d[0] + d[2]) / 2
                dcy = (d[1] + d[3]) / 2
                if x1 <= dcx <= x2 and y1 <= dcy <= y2:
                    best_in_vehicle = d
                    break
            if best_in_vehicle is None:
                return "", 0.0
            # 用全图做 warp
            warp_image = frame
            best_det = best_in_vehicle
        else:
            warp_image = vehicle_roi
            best_det = max(dets, key=lambda d: d[4])

        landmarks = best_det[5:13].reshape(4, 2).astype(np.float32)
        bconf = best_det[4]
        warp_h, warp_w = warp_image.shape[:2]

        # ---- 诊断输出 ----
        self._lpr_call_count += 1
        if self._verbose or self._lpr_call_count <= 10:
            bx1, by1, bx2, by2 = best_det[:4]
            plate_px = f"{bx2-bx1:.0f}x{by2-by1:.0f}"
            print(f"  [LPR #{self._lpr_call_count}] vehicle={vehicle_w}x{vehicle_h}  "
                  f"roi={raw_w}x{raw_h}  upscale={scale:.1f}x→{roi_w}x{roi_h}  "
                  f"plate={plate_px}px  det_conf={bconf:.3f}")
            if self._lpr_call_count == 10:
                print("  [LPR] 10次后静默 (LPR_VERBOSE=1 持续输出)\n")

        # ---- 4. 透视矫正 + 识别 ----
        warped = get_rotate_crop_image(warp_image, landmarks)
        code, conf = self.lpr_rec(warped)

        # ---- 5. 如果结果不完整(<7字符)，扩展 landmarks 重试 ----
        if len(code) < 7:
            cx, cy = np.mean(landmarks, axis=0)
            expanded_lms = landmarks.copy()
            for j in range(4):
                vec = expanded_lms[j] - np.array([cx, cy])
                expanded_lms[j] = expanded_lms[j] + vec * self.landmark_expand
            expanded_lms = np.clip(expanded_lms, [0, 0], [warp_w - 1, warp_h - 1])

            warped2 = get_rotate_crop_image(warp_image, expanded_lms)
            code2, conf2 = self.lpr_rec(warped2)

            if len(code2) > len(code):
                code, conf = code2, conf2

        # 至少 6 位才算有效车牌
        if len(code) >= 6:
            return code, conf
        return "", 0.0

    def draw_annotations(self, frame: np.ndarray, vehicles: list, plates: list,
                         track_ids: list = None) -> np.ndarray:
        """
        在帧上绘制车辆检测框、追踪ID和车牌号码
        """
        track_ids = track_ids or []
        class_colors = {
            "car": (0, 255, 0),
            "bus": (255, 191, 0),
            "truck": (0, 128, 255),
            "motorcycle": (255, 0, 255),
        }

        for i, (vehicle, plate) in enumerate(zip(vehicles, plates)):
            x1, y1, x2, y2 = vehicle["bbox"]
            cls_name = vehicle["cls_name"].lower()
            conf = vehicle["conf"]
            tid = track_ids[i] if i < len(track_ids) else None

            # 根据类别选择颜色
            color = (0, 255, 0)
            for key, c in class_colors.items():
                if key in cls_name:
                    color = c
                    break

            # 绘制车辆边界框
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # 类别标签（含追踪ID）
            label = f"#{tid} {cls_name} {conf:.2f}" if tid is not None else f"{cls_name} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # 车牌号码显示
            if plate:
                plate_label = f"Plate: {plate}"
                # 在车辆框下方显示车牌
                plate_y = y2 + 24
                (pw, ph), _ = cv2.getTextSize(plate_label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                # 绘制车牌背景
                cv2.rectangle(frame,
                              (x1, plate_y - ph - 4),
                              (x1 + pw + 8, plate_y + 2),
                              (0, 0, 0), -1)
                cv2.rectangle(frame,
                              (x1, plate_y - ph - 4),
                              (x1 + pw + 8, plate_y + 2),
                              (0, 255, 255), 2)
                cv2.putText(frame, plate_label, (x1 + 4, plate_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # 左上角 FPS 和统计信息
        cv2.putText(frame, f"FPS: {self.fps:.1f}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        active_tracks = sum(1 for t in self._tracks.values()
                           if t['best_plate'] and t['plate_conf'] >= self.plate_conf_threshold)
        cv2.putText(frame, f"Vehicles: {len(vehicles)}  |  Tracked: {active_tracks}",
                    (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        nb_recognized = sum(1 for p in plates if p)
        cv2.putText(frame, f"Plates Read: {nb_recognized}",
                    (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        return frame

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        处理单帧图像：检测车辆 -> 识别车牌
        Returns:
            np.ndarray: 带标注的帧
        """
        self.frame_count += 1
        self._global_frame += 1

        # 1. YOLO 检测车辆
        vehicles = self.detect_vehicles(frame)

        # 2. 追踪匹配
        track_ids = self._match_tracks(vehicles, self._global_frame)

        # 3. 对每辆车识别车牌（保留同追踪最高置信度结果）
        plates = []
        track_ids_out = []
        for vehicle, tid in zip(vehicles, track_ids):
            track = self._tracks[tid]
            # 每 10 帧重新 OCR 一次，其余帧使用追踪缓存
            if track['best_plate'] and self._global_frame % 10 != 0:
                # 仅当已有高置信度结果时才使用缓存
                plates.append(track['best_plate'] if track['plate_conf'] >= self.plate_conf_threshold else '')
                track_ids_out.append(tid)
            else:
                plate, pconf = self.recognize_plate_in_roi(frame, vehicle["bbox"])
                if plate and pconf >= self.plate_conf_threshold:
                    # 保留同追踪内最高置信度的结果
                    if pconf > track['plate_conf']:
                        track['best_plate'] = plate
                        track['plate_conf'] = pconf
                        print(f"[车牌识别] ID={tid} {plate} (类别: {vehicle['cls_name']}, 车牌置信度: {pconf:.3f})")
                # 仅当有高置信度结果时才显示车牌
                plates.append(track['best_plate'] if track['plate_conf'] >= self.plate_conf_threshold else '')
                track_ids_out.append(tid)

        # 4. 绘制标注
        result = self.draw_annotations(frame, vehicles, plates, track_ids_out)

        # 5. 更新 FPS
        elapsed = time.time() - self.fps_timer
        if elapsed >= 1.0:
            self.fps = self.frame_count / elapsed
            self.frame_count = 0
            self.fps_timer = time.time()

        return result

    def run(
        self,
        source,
        show: bool = True,
        save: bool = False,
        output_path: str = "output_plate.mp4",
    ):
        """
        运行视频流处理
        Args:
            source: 视频路径 或 摄像头索引 (0, 1, ...)
            show: 是否实时显示
            save: 是否保存输出视频
            output_path: 输出视频保存路径
        """
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            print(f"[错误] 无法打开视频源: {source}")
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        writer = None
        if save:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            print(f"[信息] 输出视频将保存至: {output_path}")

        print(f"\n[运行] 开始处理视频流 (分辨率: {width}x{height}, FPS: {fps:.0f})")
        print("[提示] 按 'q' 键停止, 按 's' 键截图\n")

        while True:
            ret, frame = cap.read()
            if not ret:
                print("[信息] 视频流结束")
                break

            # 处理帧
            result_frame = self.process_frame(frame)

            # 显示
            if show:
                cv2.imshow("Vehicle LPR Pipeline (YOLO + HyperLPR3)", result_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    print("[信息] 用户停止")
                    break
                elif key == ord("s"):
                    screenshot_path = f"screenshot_{int(time.time())}.jpg"
                    cv2.imwrite(screenshot_path, result_frame)
                    print(f"[截图] 已保存: {screenshot_path}")

            # 保存
            if writer:
                writer.write(result_frame)

        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()
        print(f"\n[完成] 处理结束")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="车辆检测 + 车牌识别流水线 (YOLO + HyperLPR3)"
    )
    parser.add_argument(
        "--source", type=str, default="test.mp4",
        help="视频源：文件路径 或 摄像头索引 (如 0)"
    )
    parser.add_argument(
        "--yolo-weights", type=str, default="yolo26n.pt",
        help="YOLO 模型权重路径"
    )
    parser.add_argument(
        "--conf", type=float, default=0.25,
        help="YOLO 置信度阈值 (默认: 0.25)"
    )
    parser.add_argument(
        "--iou", type=float, default=0.45,
        help="YOLO NMS IoU 阈值 (默认: 0.45)"
    )
    parser.add_argument(
        "--imgsz", type=int, default=640,
        help="YOLO 推理分辨率 (默认: 640)"
    )
    parser.add_argument(
        "--vehicle-classes", type=int, nargs="+", default=None,
        help="自定义车辆类别 ID，如: --vehicle-classes 2 5 7 (COCO: 2=car, 5=bus, 7=truck)"
    )
    parser.add_argument(
        "--cpu", action="store_true",
        help="保留参数（HyperLPR3 自动选择设备）"
    )
    parser.add_argument(
        "--no-show", action="store_true",
        help="不显示实时画面"
    )
    parser.add_argument(
        "--save", action="store_true",
        help="保存带标注的输出视频"
    )
    parser.add_argument(
        "--output", type=str, default="output_plate.mp4",
        help="输出视频文件路径"
    )

    args = parser.parse_args()

    # 解析视频源（摄像头索引或文件路径）
    source = args.source
    if source.isdigit():
        source = int(source)

    # 检查文件存在
    if isinstance(source, str) and not source.isdigit() and not os.path.exists(source):
        print(f"[错误] 视频文件不存在: {source}")
        sys.exit(1)

    pipeline = VehicleLPRPipeline(
        yolo_model_path=args.yolo_weights,
        vehicle_classes=args.vehicle_classes,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        imgsz=args.imgsz,
        gpu=not args.cpu,
    )

    pipeline.run(
        source=source,
        show=not args.no_show,
        save=args.save,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()