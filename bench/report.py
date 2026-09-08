"""汇总各引擎的结果 JSON,算 CER,输出对比表(markdown)。

用法:
    uv run python bench/report.py bench/results/*.json -o docs/engine-benchmark.md
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from voiceinput.metrics import score  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLES = Path(__file__).parent / "samples"


def load_runs(paths: list[Path]) -> list[dict]:
    runs = []
    for p in paths:
        data = json.loads(p.read_text("utf-8"))
        data["_file"] = p.name
        runs.append(data)
    return runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    manifest = json.loads((SAMPLES / "manifest.json").read_text("utf-8"))
    runs = load_runs(args.results)

    lines: list[str] = []
    w = lines.append

    w("# 引擎实测对比")
    w("")
    w(f"样本 {len(manifest)} 条,其中自由发挥 "
      f"{sum(1 for m in manifest.values() if m.get('freeform'))} 条。")
    w("")

    # ---- 汇总表 ----
    w("## 汇总")
    w("")
    w("| 配置 | 平均 CER(raw) | 平均 CER(norm) | 平均 RTF | 加载耗时 |")
    w("|---|---|---|---|---|")
    summary = []
    for run in runs:
        cers_raw, cers_norm, infer, audio = [], [], 0.0, 0.0
        for key, meta in manifest.items():
            r = run["results"].get(key)
            if not r:
                continue
            s = score(meta["truth"], r["text"])
            cers_raw.append(s["cer_raw"])
            cers_norm.append(s["cer_norm"])
            infer += r["infer_s"]
            audio += r["audio_s"]
        if not cers_raw:
            continue
        avg_raw = sum(cers_raw) / len(cers_raw)
        avg_norm = sum(cers_norm) / len(cers_norm)
        rtf = infer / audio if audio else 0
        summary.append((run["label"], avg_raw, avg_norm, rtf))
        w(f"| {run['label']} | {avg_raw:.1%} | {avg_norm:.1%} | "
          f"{rtf:.3f} ({audio / infer:.1f}x) | {run['load_s']:.1f}s |")
    w("")

    if summary:
        best = min(summary, key=lambda s: s[2])
        w(f"**norm CER 最低**:`{best[0]}` ({best[2]:.1%})")
        w("")

    # ---- 逐条明细 ----
    w("## 逐条明细")
    w("")
    for key, meta in manifest.items():
        tag = "自由" if meta.get("freeform") else "朗读"
        w(f"### {key} ({tag})")
        w("")
        w(f"- **ground truth**: `{meta['truth']}`")
        for run in runs:
            r = run["results"].get(key)
            if not r:
                w(f"- {run['label']}: (无结果)")
                continue
            s = score(meta["truth"], r["text"])
            w(f"- {run['label']}: `{r['text']}`  "
              f"— raw {s['cer_raw']:.1%} / norm {s['cer_norm']:.1%}, {r['infer_s']:.2f}s")
        w("")

    text = "\n".join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, "utf-8")
        print(f"写入 {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
