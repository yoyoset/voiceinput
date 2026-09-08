"""录制基准测试语音样本。

样本分两类:
  - 朗读类:给定文本,ground truth 就是给定文本本身,用来测术语/中英混说的字准确率
  - 自由类:自己随便说,说完手打 ground truth,用来测真实口语(口水词、思考停顿)

朗读类和自由类都要有:只测朗读会高估效果(朗读比自然口语清晰得多),
只测自由类则 ground truth 靠手打,量上不来。

用法:
    uv run python bench/record_samples.py [--device N]
录音是"回车开始、回车结束",不设固定时长,和最终工具的 push-to-talk 行为接近。
样本存到 bench/samples/,ground truth 存到 bench/samples/manifest.json。
"""

import argparse
import json
import queue
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLE_RATE = 16000
OUT_DIR = Path(__file__).parent / "samples"
MANIFEST = OUT_DIR / "manifest.json"

# 朗读类:覆盖真实使用场景。ground truth = 提示文本本身。
SCRIPTED = [
    ("term_mixed_1", "把这个 function 改成 async,再跑一遍 pytest"),
    ("term_mixed_2", "帮我看一下 keytyper 那个项目的 Cargo.toml,依赖里 enigo 是什么版本"),
    ("term_mixed_3", "这个 commit 先别 push,我要改一下 config 里的 hotkey"),
    ("proper_noun", "OpenWrt 的路由器上跑一个 sherpa-onnx 的推理服务现实吗"),
    ("command_short", "打开那个文件看一下"),
    ("pure_zh_long", "我想做一个语音输入的工具,按住热键说话,松开之后文字直接出现在光标位置"),
    # 数字用自然说法。别写"十六千赫兹"那种没人这么说的 —— 既难念,
    # 又会让 CER 归一化对不上(实测那句被判成 30% 错误,其实一个字没错)。
    ("digits_units", "把超时改成三十秒,最多重试三次,单声道就够了"),
]

# 自由类:提示场景,内容自己发挥,录完手打 ground truth。
FREEFORM = [
    ("free_filler", "随便说一段带口水词的话(呃、就是、然后……),模拟你平时想事情时的语速"),
    ("free_pause", "说一句话,中间故意停顿两三秒再接着说完"),
    ("free_real", "假装你正在对 Claude Code 下达一个真实的开发指令"),
]


def native_rate(device: int | None) -> int:
    """设备原生采样率。WASAPI 只接受它,请求 16000 会直接开不了流。"""
    try:
        rate = int(sd.query_devices(device, "input")["default_samplerate"])
        return rate if rate > 0 else SAMPLE_RATE
    except Exception:
        return SAMPLE_RATE


def record_until_enter(device: int | None) -> tuple[np.ndarray, int]:
    """回车开始、回车结束地录一段,返回 (单声道 float32, 实际采样率)。"""
    chunks: queue.Queue[np.ndarray] = queue.Queue()
    stop = threading.Event()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"  [音频告警] {status}", file=sys.stderr)
        chunks.put(indata.copy())

    rate = native_rate(device)
    input("  回车开始录音 > ")
    with sd.InputStream(
        samplerate=rate,
        channels=1,
        dtype="float32",
        device=device,
        callback=callback,
    ):
        print("  >>> 录音中,说完按回车 <<<")
        input()
        stop.set()

    parts = []
    while not chunks.empty():
        parts.append(chunks.get())
    if not parts:
        return np.zeros(0, dtype=np.float32), rate
    audio = np.concatenate(parts, axis=0)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32), rate


def report_level(audio: np.ndarray, rate: int) -> bool:
    """打印电平并判断这条是不是废了。返回 True 表示看起来正常。"""
    if audio.size == 0:
        print("  ! 没录到任何数据")
        return False
    rms = float(np.sqrt(np.mean(np.square(audio))))
    rms_db = 20 * np.log10(rms) if rms > 1e-9 else float("-inf")
    dur = audio.size / rate
    print(f"  时长 {dur:.1f}s | RMS {rms_db:.1f} dBFS", end="")
    if rms_db < -50:
        print("  ← 电平过低,可能录错设备了")
        return False
    print("  ok")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None, help="输入设备编号(先跑 probe_devices.py 确定)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}

    dev_name = sd.query_devices(args.device if args.device is not None else None, "input")["name"]
    print(f"输入设备: {dev_name}")
    print(f"共 {len(SCRIPTED)} 条朗读 + {len(FREEFORM)} 条自由发挥。")
    print("每条录完会报电平,不满意可以当场重录。\n")

    todo = [(k, t, False) for k, t in SCRIPTED] + [(k, t, True) for k, t in FREEFORM]

    for i, (key, prompt, freeform) in enumerate(todo, 1):
        wav_path = OUT_DIR / f"{key}.wav"
        if key in manifest and wav_path.exists():
            if input(f"[{i}/{len(todo)}] {key} 已存在,重录? (y/N) > ").strip().lower() != "y":
                continue

        print(f"\n[{i}/{len(todo)}] {key}")
        if freeform:
            print(f"  场景: {prompt}")
        else:
            print(f"  请朗读: 「{prompt}」")

        while True:
            audio, rate = record_until_enter(args.device)
            ok = report_level(audio, rate)
            again = input("  重录? (y/N) > ").strip().lower() == "y" if ok else True
            if not again:
                break
            if not ok and input("  电平不对,还要继续录吗? (Y/n) > ").strip().lower() == "n":
                break

        if audio.size == 0:
            print("  跳过这条")
            continue

        sf.write(wav_path, audio, rate)

        if freeform:
            print("  请把你刚才说的话原样打出来(作为 ground truth):")
            truth = input("  > ").strip()
        else:
            truth = prompt

        manifest[key] = {"wav": wav_path.name, "truth": truth, "freeform": freeform}
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
        print(f"  已保存 -> {wav_path.name}")

    print(f"\n完成,共 {len(manifest)} 条样本。manifest: {MANIFEST}")
    print("接下来跑: uv run python bench/compare.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
