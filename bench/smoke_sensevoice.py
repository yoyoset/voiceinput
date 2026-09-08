"""SenseVoice 冒烟测试:用模型自带的 test_wavs 验证推理通路 + 测本机真实耗时。

不需要麦克风,先把"模型能不能在这台机器上跑、跑多快"这件事确认掉。
"""

import argparse
import sys
import time
from pathlib import Path

import sherpa_onnx
import soundfile as sf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MODELS_DIR = Path(__file__).parent.parent / "models"


def build(model_dir: Path, provider: str, threads: int):
    t0 = time.perf_counter()
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model_dir / "model.int8.onnx"),
        tokens=str(model_dir / "tokens.txt"),
        use_itn=True,          # 开逆文本归一化:数字/标点会被规整
        num_threads=threads,
        provider=provider,
    )
    return rec, time.perf_counter() - t0


def transcribe(rec, wav: Path) -> tuple[str, float, float]:
    audio, sr = sf.read(wav, dtype="float32", always_2d=True)
    audio = audio[:, 0]
    dur = len(audio) / sr
    t0 = time.perf_counter()
    stream = rec.create_stream()
    stream.accept_waveform(sr, audio)
    rec.decode_stream(stream)
    return stream.result.text, time.perf_counter() - t0, dur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--provider", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--wavs", nargs="*", type=Path, help="不给就用模型自带的 test_wavs")
    args = ap.parse_args()

    model_dir = args.model_dir
    if not (model_dir / "model.int8.onnx").exists():
        print(f"模型不存在: {model_dir}")
        return 1

    print(f"模型:     {model_dir.name}")
    print(f"provider: {args.provider} | threads: {args.threads}")

    try:
        rec, load_s = build(model_dir, args.provider, args.threads)
    except Exception as e:
        print(f"加载失败: {e}")
        return 1
    print(f"加载耗时: {load_s:.2f}s\n")

    wavs = args.wavs
    if not wavs:
        td = model_dir / "test_wavs"
        # 每种语言挑一条,粤语那堆不用全跑
        prefer = ["zh.wav", "en.wav", "ja.wav", "ko.wav", "yue.wav"]
        wavs = [td / n for n in prefer if (td / n).exists()]
        if not wavs:
            wavs = sorted(td.glob("*.wav"))[:5]

    total_infer = total_audio = 0.0
    for wav in wavs:
        if not wav.exists():
            print(f"{wav.name}: 文件不存在")
            continue
        text, infer_s, dur = transcribe(rec, wav)
        total_infer += infer_s
        total_audio += dur
        rtf = infer_s / dur if dur else 0
        print(f"{wav.name:<12} 音频 {dur:5.1f}s | 推理 {infer_s:5.2f}s | RTF {rtf:.3f}")
        print(f"             {text}\n")

    if total_audio:
        print("=" * 60)
        print(f"合计: 音频 {total_audio:.1f}s | 推理 {total_infer:.2f}s | "
              f"平均 RTF {total_infer / total_audio:.3f} "
              f"({total_audio / total_infer:.1f}x 实时)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
