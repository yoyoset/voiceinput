"""faster-whisper 冒烟测试:用 SenseVoice 自带的 test_wavs 跑,和 SenseVoice 结果直接可比。

必须用独立 venv 跑(sherpa-onnx 与 onnxruntime pip 包的 DLL 问题,见 docs/engine-benchmark.md):
    C:/Users/yoyos/AppData/Local/Temp/claude/fwbench/Scripts/python.exe bench/smoke_fasterwhisper.py
"""

import argparse
import os
import sys
import time
from pathlib import Path


def add_nvidia_dll_dirs() -> list[str]:
    """把 pip 装的 CUDA 库目录加进 DLL 搜索路径。

    nvidia-cublas-cu12 / nvidia-cudnn-cu12 把 DLL 放在
    site-packages/nvidia/<lib>/bin,CTranslate2 不会自己去那儿找,
    不加这一步就是 "Library cublas64_12.dll is not found or cannot be loaded"。
    必须在 import faster_whisper 之前调用。
    """
    if os.name != "nt":
        return []
    added = []
    for site in sys.path:
        nvidia = Path(site) / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in sorted(nvidia.glob("*/bin")):
            if any(bin_dir.glob("*.dll")):
                os.add_dll_directory(str(bin_dir))
                added.append(str(bin_dir))
    return added


_DLL_DIRS = add_nvidia_dll_dirs()

import soundfile as sf  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEST_WAVS = (
    Path(__file__).parent.parent
    / "models"
    / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    / "test_wavs"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--compute-type", default="int8_float16")
    ap.add_argument("--beam-size", type=int, default=5)
    args = ap.parse_args()

    print(f"模型: {args.model} | {args.device} | {args.compute_type}", flush=True)
    print(f"CUDA DLL 目录: {len(_DLL_DIRS)} 个", flush=True)

    t0 = time.perf_counter()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print(f"加载耗时: {time.perf_counter() - t0:.2f}s\n", flush=True)

    total_infer = total_audio = 0.0
    for name in ["zh.wav", "en.wav", "ja.wav", "ko.wav", "yue.wav"]:
        wav = TEST_WAVS / name
        if not wav.exists():
            print(f"{name}: 不存在,跳过", flush=True)
            continue
        audio, sr = sf.read(wav, dtype="float32", always_2d=True)
        audio = audio[:, 0]
        dur = len(audio) / sr

        t0 = time.perf_counter()
        segments, info = model.transcribe(audio, beam_size=args.beam_size)
        text = "".join(s.text for s in segments).strip()  # 生成器,这里才真开始算
        infer_s = time.perf_counter() - t0

        total_infer += infer_s
        total_audio += dur
        print(f"{name:<10} 音频 {dur:5.1f}s | 推理 {infer_s:6.2f}s | "
              f"RTF {infer_s / dur:.3f} | 检测语种={info.language}", flush=True)
        print(f"           {text}\n", flush=True)

    if total_audio:
        print("=" * 60)
        print(f"合计: 音频 {total_audio:.1f}s | 推理 {total_infer:.2f}s | "
              f"平均 RTF {total_infer / total_audio:.3f} "
              f"({total_audio / total_infer:.1f}x 实时)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
