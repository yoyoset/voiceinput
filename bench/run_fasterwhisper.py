"""跑 faster-whisper 转写 bench/samples 下的样本,结果写 JSON。

必须在独立的 venv 里跑(见 run_sensevoice.py 顶部说明):
    C:/Users/yoyos/AppData/Local/Temp/claude/fwbench/Scripts/python.exe bench/run_fasterwhisper.py ...
"""

import argparse
import json
import sys
import time
from pathlib import Path

import soundfile as sf
from faster_whisper import WhisperModel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLES = Path(__file__).parent / "samples"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--compute-type", default="int8_float16")
    ap.add_argument("--language", default=None, help="留空为自动检测;中英混说建议试 zh")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    manifest_path = SAMPLES / "manifest.json"
    if not manifest_path.exists():
        print(f"找不到 {manifest_path},先跑 record_samples.py")
        return 1
    manifest = json.loads(manifest_path.read_text("utf-8"))

    label = args.label or f"faster-whisper/{args.model}/{args.device}/{args.compute_type}/lang={args.language or 'auto'}"
    print(f"配置: {label}")

    t0 = time.perf_counter()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
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
        segments, _info = model.transcribe(audio, language=args.language, beam_size=5)
        text = "".join(s.text for s in segments).strip()  # 生成器,这里才真正开始算
        infer_s = time.perf_counter() - t0

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
