"""探测哪个输入设备真的能录到人声。

背景:本机音频走 RØDE Connect,暴露出来的全是虚拟设备(System Input / Stream Input /
Virtual Input),名字看不出哪个接的是麦克风——"System Input" 在 RØDE Connect 里
往往是系统声音回环而不是话筒。所以不猜,挨个录一段比 RMS。

用法:
    uv run python bench/probe_devices.py
按提示对着麦克风持续说话,脚本会给出每个设备的电平,并把录音存到 bench/probe/ 供试听。
"""

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

# Windows 控制台默认 GBK,设备名里的 Ø / 中文会直接抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLE_RATE = 16000
SECONDS = 4.0
OUT_DIR = Path(__file__).parent / "probe"


def candidate_devices():
    """挑出值得一试的输入设备,同名同 hostapi 只留一个。

    优先 WASAPI(Windows 上最直接),同时保留 MME 的默认设备做对照。
    """
    hostapis = sd.query_hostapis()
    seen = set()
    out = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        api = hostapis[dev["hostapi"]]["name"]
        if api not in ("Windows WASAPI", "MME"):
            continue
        key = (dev["name"], api)
        if key in seen:
            continue
        seen.add(key)
        out.append((idx, dev["name"], api, dev["max_input_channels"]))
    return out


def level_stats(audio: np.ndarray) -> tuple[float, float]:
    """返回 (RMS dBFS, 峰值 dBFS)。全静音时返回 -inf。"""
    if audio.size == 0:
        return float("-inf"), float("-inf")
    rms = float(np.sqrt(np.mean(np.square(audio))))
    peak = float(np.max(np.abs(audio)))
    to_db = lambda x: 20 * np.log10(x) if x > 1e-9 else float("-inf")
    return to_db(rms), to_db(peak)


def native_rate(device: int) -> int:
    """设备原生采样率。

    **不能一律用 16000**:WASAPI 共享模式只接受设备原生速率,
    请求别的会直接报 `Invalid sample rate [PaErrorCode -9997]` ——
    表现就是所有 WASAPI 设备都"打不开",而它们其实完全正常。
    """
    try:
        rate = int(sd.query_devices(device, "input")["default_samplerate"])
        return rate if rate > 0 else SAMPLE_RATE
    except Exception:
        return SAMPLE_RATE


def record(device: int, channels: int) -> tuple[np.ndarray, int]:
    """录一段并降成单声道 float32,连同实际采样率一起返回。"""
    rate = native_rate(device)
    frames = int(rate * SECONDS)
    audio = sd.rec(
        frames,
        samplerate=rate,
        channels=min(channels, 2),
        dtype="float32",
        device=device,
    )
    sd.wait()
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, rate


def main() -> int:
    devices = candidate_devices()
    if not devices:
        print("没有找到任何输入设备。")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"将依次测试 {len(devices)} 个输入设备,每个录 {SECONDS:.0f} 秒。")
    print("请在每次提示后 *持续说话*(念一句完整的话就行),这样电平才有区分度。\n")
    input("准备好了按回车开始 > ")

    results = []
    for idx, name, api, channels in devices:
        print(f"\n[{api}] #{idx} {name}")
        for i in (3, 2, 1):
            print(f"  {i}...", end="\r", flush=True)
            time.sleep(0.6)
        print("  >>> 说话 <<<        ", flush=True)
        try:
            audio, rate = record(idx, channels)
        except Exception as e:
            print(f"  打不开: {e}")
            results.append((idx, name, api, None, None, None))
            continue

        rms_db, peak_db = level_stats(audio)
        safe = "".join(c if c.isalnum() else "_" for c in f"{idx}_{name}")
        path = OUT_DIR / f"{safe}.wav"
        sf.write(path, audio, rate)
        print(f"  RMS {rms_db:7.1f} dBFS | 峰值 {peak_db:7.1f} dBFS | {rate} Hz -> {path.name}")
        results.append((idx, name, api, rms_db, peak_db, path))

    print("\n" + "=" * 72)
    print("结果(按 RMS 从高到低):")
    print("=" * 72)
    ok = [r for r in results if r[3] is not None and r[3] > float("-inf")]
    ok.sort(key=lambda r: r[3], reverse=True)
    for idx, name, api, rms_db, peak_db, path in ok:
        # -50 dBFS 以下基本可以认为没录到东西
        verdict = "有信号" if rms_db > -50 else "近乎静音"
        print(f"  #{idx:<3} {rms_db:7.1f} dBFS  {verdict:<8} [{api}] {name}")

    dead = [r for r in results if r[3] is None or r[3] == float("-inf")]
    for idx, name, api, *_ in dead:
        print(f"  #{idx:<3} {'--':>7}        无法录制   [{api}] {name}")

    print(f"\n录音文件在 {OUT_DIR},请试听确认 RMS 最高的那个确实是你的声音")
    print("(而不是电脑正在播放的系统声音——RØDE Connect 的 System Input 有这个嫌疑)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
