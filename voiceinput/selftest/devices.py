"""录得到音吗。

这一步原来只调 `list_devices()`。结果是"能看见"和"能录音"被当成了一回事 ——
而开发机上所有 WASAPI 设备曾经因为采样率写死 16000 完全打不开,
一半的设备选项是坏的,却一路混过了十九轮打包验证。
"""

from __future__ import annotations

import numpy as np

from ..audio import LevelMonitor, RecordingError, list_devices, looks_silent, native_sample_rate
from .report import Report


def check_devices(report: Report) -> None:
    """枚举输入设备,并**逐个真的打开一次**。"""
    try:
        devices = list_devices()
    except Exception as e:
        report.failed(f"枚举音频设备: {e}")
        return

    report.line(f"枚举到 {len(devices)} 个输入设备,逐个试开:")
    openable = 0
    for d in devices:
        rate = native_sample_rate(d.index)
        try:
            mon = LevelMonitor(device=d.index)
            mon.start()
            mon.stop()
            openable += 1
            report.detail(f"[通过] #{d.index:<3} {rate:>5} Hz  {d.label}")
        except RecordingError as e:
            report.detail(f"[失败] #{d.index:<3} {rate:>5} Hz  {d.label} —— {e}")

    if openable == 0:
        report.failed("没有一个输入设备能打开,录不了音")
    elif openable < len(devices):
        report.failed(f"{len(devices) - openable}/{len(devices)} 个设备打不开 —— "
                      "设备下拉框里会有选了就用不了的选项")
    else:
        report.passed(f"{openable} 个设备全部可以打开")


def check_silence_guard(report: Report) -> None:
    """静音判定 —— 这是防幻觉的关键防线,坏了会往光标处粘垃圾。"""
    try:
        assert looks_silent(np.zeros(16000, dtype=np.float32))
        assert not looks_silent(
            (0.2 * np.random.default_rng(0).standard_normal(16000)).astype(np.float32))
        report.passed("静音判定正常")
    except Exception as e:
        report.failed(f"静音判定: {e}")
