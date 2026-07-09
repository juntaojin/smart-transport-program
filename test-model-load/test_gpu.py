"""
GPU 模型加载测试脚本
测试 YOLO 和 HyperLPR3 是否能成功加载到 GPU

用法:
    python test-model-load/test_gpu.py
"""

import sys
import torch
import numpy as np

print("=" * 60)
print("GPU 模型加载测试")
print("=" * 60)

# ── 1. PyTorch CUDA 检测 ──
print("\n[1/4] PyTorch 环境检测")
print(f"  PyTorch 版本: {torch.__version__}")
print(f"  CUDA 编译版本: {torch.version.cuda}")
print(f"  CUDA 运行时可用: {torch.cuda.is_available()}")
print(f"  CUDA 设备数量: {torch.cuda.device_count()}")

if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        print(f"  GPU[{i}]: {torch.cuda.get_device_name(i)}")
        props = torch.cuda.get_device_properties(i)
        print(f"         显存: {props.total_memory / 1024**3:.1f} GB")
        print(f"         CUDA Capability: {props.major}.{props.minor}")
else:
    print("  [警告] CUDA 不可用! 请检查:")
    print("         1. pip list | findstr torch  (确认是 cu118/cu121 版本而非 cpu 版本)")
    print("         2. nvidia-smi  (确认驱动正常)")
    print("         3. 系统 PATH 包含 CUDA 库路径")

# ── 2. YOLO 模型加载测试 ──
print("\n[2/4] YOLO 车辆检测模型加载测试")

try:
    from ultralytics import YOLO

    yolo_path = "models/yolo26n.pt"
    print(f"  模型路径: {yolo_path}")

    import os
    if not os.path.exists(yolo_path):
        print(f"  [错误] 模型文件不存在: {yolo_path}")
        print(f"  当前目录: {os.getcwd()}")
        print(f"  目录内容: {os.listdir('models') if os.path.exists('models') else 'models/ 不存在'}")
        sys.exit(1)

    yolo = YOLO(yolo_path)
    device = str(yolo.device) if hasattr(yolo, 'device') else 'unknown'
    print(f"  YOLO 加载后设备: {device}")

    if torch.cuda.is_available():
        print("  尝试显式移动到 CUDA...")
        yolo.to("cuda")
        print(f"  移动后设备: {yolo.device}")

    # 测试推理
    print("  运行测试推理 (640x640 随机图像)...")
    test_frame = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    results = yolo(test_frame, conf=0.25, iou=0.45, imgsz=640, classes=[2, 3, 5, 7], verbose=False)
    num_boxes = len(results[0].boxes) if results and results[0].boxes is not None else 0
    print(f"  YOLO 测试推理完成, 检出: {num_boxes} 个框 (随机图像预期为 0)")

    # 清理
    del yolo
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("  [通过] YOLO 模型加载测试通过")

except Exception as e:
    print(f"  [失败] YOLO 加载失败: {e}")
    import traceback
    traceback.print_exc()

# ── 3. HyperLPR3 模型加载测试 ──
print("\n[3/4] HyperLPR3 车牌识别模型加载测试")

try:
    import hyperlpr3 as lpr3
    from hyperlpr3.inference.pipeline import get_rotate_crop_image
    import cv2

    print("  加载 LicensePlateCatcher...")
    catcher = lpr3.LicensePlateCatcher()
    pipeline = catcher.pipeline
    recognizer = pipeline.recognizer
    pipeline.detector.box_threshold = 0.2
    print("  HyperLPR3 加载完成")

    # 测试推理
    print("  运行测试推理 (随机图像 + 模拟车牌区域)...")
    import cv2
    test_img = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)

    # 模拟一个车牌区域 (白色矩形 + 黑色文字)
    x1, y1, x2, y2 = 400, 300, 600, 360
    cv2.rectangle(test_img, (x1, y1), (x2, y2), (255, 255, 255), -1)
    cv2.putText(test_img, "京A12345", (x1 + 10, y1 + 35),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

    dets = pipeline.detector(test_img)
    print(f"  车牌检测器找到: {len(dets)} 个候选区域")

    if len(dets) > 0:
        best_det = max(dets, key=lambda d: d[4])
        landmarks = best_det[5:13].reshape(4, 2).astype(np.float32)
        warped = get_rotate_crop_image(test_img, landmarks)
        code, conf = recognizer(warped)
        print(f"  识别结果: '{code}' (置信度: {conf:.3f})")

    del catcher
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("  [通过] HyperLPR3 模型加载测试通过")

except Exception as e:
    print(f"  [失败] HyperLPR3 加载失败: {e}")
    import traceback
    traceback.print_exc()

# ── 4. 总结 ──
print("\n[4/4] 总结")
print("=" * 60)
if torch.cuda.is_available():
    print("  GPU 可用，模型应能在 GPU 上运行")
    print(f"  当前 GPU 显存使用: {torch.cuda.memory_allocated(0) / 1024**2:.1f} MB")
else:
    print("  [警告] GPU 不可用，模型将在 CPU 上运行")
    print("  请执行: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118")
print("=" * 60)
