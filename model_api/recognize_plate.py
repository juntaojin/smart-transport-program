import os
import sys

# Ensure onnxruntime CUDA providers can find torch CUDA 12 DLLs
_torch_lib = os.path.join(sys.prefix, 'Lib', 'site-packages', 'torch', 'lib')
if os.path.isdir(_torch_lib):
    os.environ['PATH'] = _torch_lib + os.pathsep + os.environ.get('PATH', '')

import cv2
import numpy as np
import hyperlpr3 as lpr3
from hyperlpr3.inference.pipeline import get_rotate_crop_image
from .plate_format import is_valid_china_plate, normalize_plate_number

ROI_UPSCALE_TARGET = 800
LANDMARK_EXPAND_RATIO = 0.18
DETECTOR_THRESHOLD = 0.2
SANDBOX_PLATE_CANDIDATES = {
    "京B6789T",
    "京E4682Y",
    "京E7654Z",
    "京K9134J",
    "京H7912N",
}

_catcher = None
_pipeline = None
_recognizer = None


def _get_lpr():
    global _catcher, _pipeline, _recognizer
    if _catcher is None:
        _catcher = lpr3.LicensePlateCatcher()
        _pipeline = _catcher.pipeline
        _pipeline.detector.box_threshold = DETECTOR_THRESHOLD
        _recognizer = _pipeline.recognizer
    return _pipeline, _recognizer


def _upscale_roi(roi):
    h, w = roi.shape[:2]
    scale = max(1.0, ROI_UPSCALE_TARGET / w)
    if scale > 1.0:
        roi = cv2.resize(roi, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    return roi


def _detect_and_recognize(roi):
    pipeline, recognizer = _get_lpr()

    dets = pipeline.detector(roi)
    if len(dets) == 0:
        return "", 0.0

    best_det = max(dets, key=lambda d: d[4])
    landmarks = best_det[5:13].reshape(4, 2).astype(np.float32)
    warp_h, warp_w = roi.shape[:2]

    warped = get_rotate_crop_image(roi, landmarks)
    code, conf = recognizer(warped)

    if len(code) < 7:
        cx, cy = np.mean(landmarks, axis=0)
        expanded = landmarks.copy()
        for j in range(4):
            vec = expanded[j] - np.array([cx, cy])
            expanded[j] = expanded[j] + vec * LANDMARK_EXPAND_RATIO
        expanded = np.clip(expanded, [0, 0], [warp_w - 1, warp_h - 1])

        warped2 = get_rotate_crop_image(roi, expanded)
        code2, conf2 = recognizer(warped2)

        if len(code2) > len(code):
            code, conf = code2, conf2

    code = normalize_plate_number(code)
    if is_valid_china_plate(code):
        return code, conf
    return "", 0.0


def _is_sandbox_plate(code):
    return normalize_plate_number(code) in SANDBOX_PLATE_CANDIDATES


def recognize_plate(vehicle_roi):
    try:
        if vehicle_roi.size == 0 or vehicle_roi.shape[0] < 15 or vehicle_roi.shape[1] < 40:
            return "", 0.0

        # 先对完整 ROI 检测
        upscaled = _upscale_roi(vehicle_roi)
        code, conf = _detect_and_recognize(upscaled)
        if _is_sandbox_plate(code):
            return code, conf

        # 回退：裁剪下半部重试（车牌通常在车辆下半部）。沙盘只接受固定候选车牌，
        # 如果完整 ROI 识别到其他合法车牌，也继续重试，避免错误结果进入前端缓存。
        h = vehicle_roi.shape[0]
        lower_half = vehicle_roi[int(h * 0.35):, :]
        if lower_half.size > 0 and lower_half.shape[0] >= 15 and lower_half.shape[1] >= 40:
            upscaled = _upscale_roi(lower_half)
            code, conf = _detect_and_recognize(upscaled)
            if _is_sandbox_plate(code):
                return code, conf

        return "", 0.0
    except Exception:
        return "", 0.0
