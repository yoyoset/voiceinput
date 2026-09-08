"""跑 SenseVoice 转写 bench/samples 下的样本,结果写 JSON。

单独一个脚本是因为 sherpa-onnx 和 faster-whisper 不能共存于同一个 venv
(见 docs/engine-benchmark.md 的 DLL 劫持记录),两个引擎各自在自己的环境里跑,
产出统一格式的 JSON,最后由 report.py 汇总算 CER。
"""

import argparse
import json
import sys
import time
from pathlib import Path

import sherpa_onnx
import soundfile as sf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLES = Path(__file__).parent / "samples"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--provider", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--language", default="auto", help="auto/zh/en/ja/ko/yue")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default=None, help="结果里的配置名,默认按模型目录+provider 生成")
    args = ap.parse_args()

    manifest_path = SAMPLES / "manifest.json"
    if not manifest_path.exists():
        print(f"找不到 {manifest_path},先跑 record_samples.py")
        return 1
    manifest = json.loads(manifest_path.read_text("utf-8"))

    label = args.label or f"sensevoice/{args.model_dir.name[-10:]}/{args.provider}/lang={args.language}"
    print(f"配置: {label}")

    t0 = time.perf_counter()
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(args.model_dir / "model.int8.onnx"),
        tokens=str(args.model_dir / "tokens.txt"),
        use_itn=True,
        num_threads=args.threads,
        provider=args.provider,
        language=args.language,
    )
    load_s = time.perf_counter() - t0
    print(f"加载耗时: {load_s:.2f}s\n")

    results = {}
    for key, meta in manifest.items():
        wav = SAMPLES / meta["wav"]
        if not wav.exists():
            print(f"{key}: 音频缺失,跳过")
            continue
        audio, sr = sf.read(wav, dtype="float32", always_2d=True)
        audio = audio[:, 0]
        dur = len(audio) / sr

        t0 = time.perf_counter()
        stream = rec.create_stream()
        stream.accept_waveform(sr, audio)
        rec.decode_stream(stream)
        infer_s = time.perf_counter() - t0

        text = stream.result.text.strip()
        results[key] = {"text": text, "infer_s": infer_s, "audio_s": dur}
        print(f"{key:<16} {infer_s:5.2f}s / {dur:5.1f}s  {text}")

    args.out.write_text(
        json.dumps({"label": label, "load_s": load_s, "results": results},
                   ensure_ascii=False, indent=2),
        "utf-8",
    )
    print(f"\n写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
