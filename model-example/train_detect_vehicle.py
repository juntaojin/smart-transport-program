import os
import time
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "triple_output"
TRACKER_CONFIG = "bytetrack.yaml"

INFERENCE_SIZE = 640
CONFIDENCE_THRESHOLD = 0.75
IOU_THRESHOLD = 0.5
TARGET_CLASSES = [0]
CLASS_NAMES = {0: "car"}

MODELS = {
    "yolo11n_t": ROOT / "weights" / "yolo11n_t.pt",
    "yolo11s_t": ROOT / "weights" / "yolo11s_t.pt",
    "yolov11s_visdrone_t": ROOT / "weights" / "yolov11s_visdrone_t.pt",
}


def process_video(video_path: str, model_path: str, model_name: str):
    video_stem = Path(video_path).stem
    output_path = str(OUTPUT_DIR / f"output_{video_stem}_{model_name}.mp4")

    if not os.path.exists(video_path):
        print(f"[{model_name}] 找不到视频文件: {video_path}")
        return

    print(f"\n{'='*50}")
    print(f"[{model_name}] 加载模型: {model_path}")
    model = YOLO(str(model_path))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[{model_name}] 无法打开视频: {video_path}")
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    print(f"[{model_name}] 开始追踪推理 分辨率:{INFERENCE_SIZE} 置信度:{CONFIDENCE_THRESHOLD} 总帧:{total_frames}")

    results_gen = model.track(
        source=video_path,
        stream=True,
        persist=True,
        imgsz=INFERENCE_SIZE,
        conf=CONFIDENCE_THRESHOLD,
        iou=IOU_THRESHOLD,
        classes=TARGET_CLASSES,
        tracker=TRACKER_CONFIG,
        verbose=False,
    )

    frame_idx = 0
    total_detections = 0
    seen_ids = set()
    total_start = time.time()

    for result in results_gen:
        frame = result.orig_img

        if result.boxes is not None and result.boxes.id is not None:
            boxes = result.boxes.xyxy.cpu().numpy()
            track_ids = result.boxes.id.cpu().numpy().astype(int)
            clss = result.boxes.cls.cpu().numpy().astype(int)
            total_detections += len(boxes)
            seen_ids.update(track_ids.tolist())

            for box, raw_id, cls in zip(boxes, track_ids, clss):
                x1, y1, x2, y2 = map(int, box)
                class_name = CLASS_NAMES.get(int(cls), "vehicle")
                label = f"{class_name} #{int(raw_id)}"

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                (lw, lh), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(frame, (x1, y1 - lh - baseline - 6), (x1 + lw + 4, y1), (0, 255, 0), -1)
                cv2.putText(frame, label, (x1 + 2, y1 - baseline - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        out.write(frame)
        frame_idx += 1

        if frame_idx % 30 == 0:
            elapsed = time.time() - total_start
            print(f"  [{frame_idx}/{total_frames}] {100*frame_idx/total_frames:.1f}%  "
                  f"FPS: {frame_idx/elapsed:.1f}" if elapsed > 0 else "")

    out.release()

    total_time = time.time() - total_start
    avg_fps = total_frames / total_time if total_time > 0 else 0

    print(f"[{model_name}] 完成: {output_path}")
    print(f"  唯一车辆数: {len(seen_ids)}  总检测数: {total_detections}  FPS: {avg_fps:.1f}")

    return {"model": model_name, "output": output_path, "vehicles": len(seen_ids),
            "detections": total_detections, "fps": avg_fps, "time": total_time}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    test_videos = [ROOT / "test4.mp4"]
    if not test_videos[0].exists():
        print("[ERROR] 找不到 test4.mp4")
        return

    all_results = []
    for video in test_videos:
        for name, path in MODELS.items():
            if not path.exists():
                print(f"[SKIP] 模型不存在: {path}")
                continue
            r = process_video(str(video), path, name)
            if r:
                r["video"] = video.name
                all_results.append(r)

    print(f"\n{'='*60}")
    print("测试总结")
    print(f"{'='*60}")
    print(f"{'视频':<10} {'模型':<20} {'车辆数':<8} {'检测数':<10} {'FPS':<8} {'耗时':<10}")
    print("-" * 56)
    for r in all_results:
        print(f"{r['video']:<10} {r['model']:<20} {r['vehicles']:<8} {r['detections']:<10} {r['fps']:<8.1f} {r['time']:<10.1f}s")
    print(f"\n视频输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
