import os
import time
import cv2
import numpy as np
from ultralytics import YOLO


def main():
    MODEL_PATH = "yolo11s.pt"
    VIDEO_PATH = "test.mp4"
    OUTPUT_PATH = "output_tracked.mp4"
    TRACKER_CONFIG = "bytetrack.yaml"

    if not os.path.exists(VIDEO_PATH):
        print(f"[ERROR] 找不到视频文件: {VIDEO_PATH}")
        return

    print(f"[INFO] 加载检测模型: {MODEL_PATH} ...")
    model = YOLO(MODEL_PATH)

    INFERENCE_SIZE = 1920
    CONFIDENCE_THRESHOLD = 0.3

    IOU_THRESHOLD = 0.5
    TARGET_CLASSES = [2, 5, 7]
    CLASS_NAMES = {2: "car", 5: "bus", 7: "truck"}

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开视频: {VIDEO_PATH}")
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (width, height))

    print(f"\n[INFO] 开始追踪推理 (ByteTrack) ...")
    print(f"  分辨率: {INFERENCE_SIZE}  置信度: {CONFIDENCE_THRESHOLD}  总帧数: {total_frames}")
    print(f"  目标类别: {[CLASS_NAMES.get(c, c) for c in TARGET_CLASSES]}")

    results_gen = model.track(
        source=VIDEO_PATH,
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
    inference_times = []
    total_start = time.time()

    for result in results_gen:
        frame_start = time.time()
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
                (lw, lh), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                )
                cv2.rectangle(
                    frame, (x1, y1 - lh - baseline - 6), (x1 + lw + 4, y1),
                    (0, 255, 0), -1,
                )
                cv2.putText(
                    frame, label, (x1 + 2, y1 - baseline - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2,
                )

        out.write(frame)
        frame_idx += 1
        inference_times.append(time.time() - frame_start)

        if frame_idx % 30 == 0:
            elapsed = time.time() - total_start
            fps_avg = frame_idx / elapsed if elapsed > 0 else 0
            print(f"  [{frame_idx}/{total_frames}] {100*frame_idx/total_frames:.1f}%  "
                  f"FPS: {fps_avg:.1f}")

    out.release()

    total_time = time.time() - total_start
    avg_latency = np.mean(inference_times) * 1000
    avg_fps = total_frames / total_time if total_time > 0 else 0

    print(f"\n{'='*50}")
    print(f"[DONE] 输出视频: {OUTPUT_PATH}")
    print(f"{'='*50}")
    print(f"  模型:          {MODEL_PATH}")
    print(f"  追踪器:        {TRACKER_CONFIG}")
    print(f"  唯一车辆数:    {len(seen_ids)}")
    print(f"  总检测数:      {total_detections}")
    print(f"  平均每帧检测:  {total_detections / max(frame_idx, 1):.2f}")
    print(f"  总帧数:        {frame_idx}")
    print(f"  总耗时:        {total_time:.2f}s")
    print(f"  平均 FPS:      {avg_fps:.2f}")
    print(f"  平均延迟:      {avg_latency:.2f}ms/帧")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
