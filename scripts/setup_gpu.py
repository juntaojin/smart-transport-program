"""
GPU 加速环境配置脚本 —— 车牌识别迁移到 GPU 必需。
在 `pip install -r requirements.txt` 之后运行一次即可。
用法: python scripts/setup_gpu.py
"""
import os
import sys
import shutil


def patch_hyperlpr3_providers():
    """将 hyperlpr3 所有 ONNX 推理模块强制切换到 CUDAExecutionProvider。"""
    site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')
    hyperlpr3_inference = os.path.join(site_packages, 'hyperlpr3', 'inference')

    if not os.path.isdir(hyperlpr3_inference):
        print('[SKIP] hyperlpr3 inference dir not found, skipping')
        return

    files = ['classification.py', 'detect.py', 'multitask_detect.py',
             'recognition.py', 'vertex.py']

    for fname in files:
        fpath = os.path.join(hyperlpr3_inference, fname)
        if not os.path.isfile(fpath):
            print(f'  [SKIP] {fname} not found')
            continue

        with open(fpath, 'r', encoding='utf-8') as fh:
            content = fh.read()

        original = content

        # Pattern 1: providers=['CPUExecutionProvider'] → CUDA
        content = content.replace(
            "providers=['CPUExecutionProvider']",
            "providers=['CUDAExecutionProvider', 'CPUExecutionProvider']"
        )

        # Pattern 2: InferenceSession(onnx_path, None) → CUDA
        content = content.replace(
            'ort.InferenceSession(onnx_path, None)',
            "ort.InferenceSession(onnx_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])"
        )

        if content != original:
            with open(fpath, 'w', encoding='utf-8') as fh:
                fh.write(content)
            print(f'  [PATCHED] {fname}')
        else:
            print(f'  [OK] {fname} (already patched)')


def link_cuda_dlls():
    """将 torch 中的 CUDA 12 DLL 硬链接到 onnxruntime 目录，0 额外磁盘占用。"""
    site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')
    torch_lib = os.path.join(site_packages, 'torch', 'lib')
    onnx_capi = os.path.join(site_packages, 'onnxruntime', 'capi')

    if not os.path.isdir(torch_lib):
        print('[SKIP] torch/lib not found')
        return
    if not os.path.isdir(onnx_capi):
        print('[SKIP] onnxruntime/capi not found')
        return

    link_count = 0
    skip_count = 0

    for fname in os.listdir(torch_lib):
        if not fname.endswith('.dll'):
            continue
        # Only link NVIDIA/CUDA related DLLs
        lower = fname.lower()
        if not any(kw in lower for kw in
                   ['cublas', 'cudnn', 'cufft', 'cudart', 'cupti',
                    'curand', 'cusolver', 'cusparse', 'nvrtc', 'nvjitlink']):
            continue

        src = os.path.join(torch_lib, fname)
        dst = os.path.join(onnx_capi, fname)

        if os.path.exists(dst):
            skip_count += 1
            continue

        try:
            os.link(src, dst)  # hard link on NTFS
        except OSError:
            shutil.copy2(src, dst)
        link_count += 1

    print(f'  Linked: {link_count} DLLs, already present: {skip_count}')


def verify():
    """快速验证 GPU 推理可用。"""
    site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')
    torch_lib = os.path.join(site_packages, 'torch', 'lib')
    os.environ['PATH'] = torch_lib + os.pathsep + os.environ.get('PATH', '')

    try:
        import hyperlpr3 as lpr3
        catcher = lpr3.LicensePlateCatcher()
        pipeline = catcher.pipeline
        d_prov = pipeline.detector.session.get_providers()
        r_prov = pipeline.recognizer.session.get_providers()

        assert 'CUDAExecutionProvider' in d_prov[0], \
            f'Detector NOT on GPU: {d_prov}'
        assert 'CUDAExecutionProvider' in r_prov[0], \
            f'Recognizer NOT on GPU: {r_prov}'

        print(f'  Detector:  {d_prov[0]}')
        print(f'  Recognizer: {r_prov[0]}')

        import numpy as np
        dummy = np.random.randint(0, 255, (48, 160, 3), dtype=np.uint8)
        code, conf = pipeline.recognizer(dummy)
        print(f'  推理测试: code={code!r} conf={conf:.4f}')
        print('\n  GPU 车牌识别配置成功!')
        return True
    except Exception as e:
        print(f'\n  [FAIL] GPU 验证失败: {e}')
        return False


if __name__ == '__main__':
    print('=== [1/3] 修补 hyperlpr3 CUDA providers ===')
    patch_hyperlpr3_providers()

    print('\n=== [2/3] 链接 CUDA 12 DLLs ===')
    link_cuda_dlls()

    print('\n=== [3/3] 验证 GPU 推理 ===')
    ok = verify()

    sys.exit(0 if ok else 1)
