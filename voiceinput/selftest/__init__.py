"""开机自检:按顺序把每一项真的跑一遍。

**这个文件只管顺序,不管任何一项具体怎么验。** 各项在同目录的
`devices` / `engine` / `hotkeys` / `interface` 里,按"坏了会怎样"分组:

- devices  —— 录不到音
- engine   —— 识别不出来
- hotkeys  —— 触发不了
- interface —— 看不见,或者文字送不出去

贯穿始终的一条判据:**"看得见" ≠ "能用"。** 每一项都要问自己验的是哪一个 ——
"枚举到 7 个设备"和"7 个设备都能打开"听起来差不多,差别是十九轮
没发现一个致命 bug。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import config as config_mod
from ..config import app_dir
from . import devices, engine, hotkeys, interface
from .report import Report, safe_print

__all__ = ["run", "Report", "safe_print"]


def run(report_path: Path | None = None) -> int:
    report = Report(report_path or (app_dir() / "selftest.txt"))

    report.line(f"[启动] argv={sys.argv}")
    report.line("=" * 56)
    report.line("VoiceInput 自检")
    report.line("=" * 56)
    report.line(f"frozen      : {getattr(sys, 'frozen', False)}")
    report.line(f"程序目录    : {app_dir()}")

    cfg = config_mod.load()
    have_config = config_mod.CONFIG_PATH.exists()
    report.line(f"配置        : {'已存在' if have_config else '将用默认值'}")
    report.line(f"模型目录    : {cfg.model_path()}")

    have_model = engine.check_model_file(report, cfg)
    devices.check_devices(report)

    loaded = engine.check_load(report, cfg) if have_model else None
    if loaded is not None:
        engine.check_inference(report, cfg, loaded)

    devices.check_silence_guard(report)
    if have_model:
        engine.check_dispatch(report, cfg)

    hotkeys.check_hook(report)
    hotkeys.check_cancel_key(report)
    hotkeys.check_conflicts(report, cfg)
    engine.check_provider(report, cfg)

    app = interface.check_qt(report)
    if app is not None:
        interface.check_clipboard(report, app)
        interface.check_render(report, app)

    report.line("=" * 56)
    report.line("自检结果: " + ("全部通过" if report.ok else "存在失败项"))
    return 0 if report.ok else 1
