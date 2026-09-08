"""开机自启。

走**启动文件夹里放快捷方式**,不写注册表——绿色软件的要求之一,
卸载就是删目录 + 删这个快捷方式,不留痕迹。用户也能自己在
`shell:startup` 里一眼看到并删掉,比藏在注册表里透明。

快捷方式用 PowerShell 的 WScript.Shell 创建:.lnk 是 COM 对象格式,
不引入 pywin32 的话这是最省事的路子。写 .cmd 会闪控制台窗口,
.vbs 在不少环境里被安全策略拦,都不如 .lnk。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("voiceinput")

APP_NAME = "VoiceInput"


def startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"


def shortcut_path() -> Path:
    return startup_dir() / f"{APP_NAME}.lnk"


def _launch_target() -> tuple[str, str, str]:
    """返回 (目标, 参数, 工作目录)。

    打包后直接指向 exe;开发时指向 pythonw.exe 加 -m voiceinput,
    用 pythonw 而不是 python 是为了不弹控制台窗口。
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return str(exe), "", str(exe.parent)

    project = Path(__file__).resolve().parent.parent
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return str(interpreter), "-m voiceinput", str(project)


def is_enabled() -> bool:
    return shortcut_path().exists()


def enable() -> None:
    target, args, workdir = _launch_target()
    lnk = shortcut_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:VI_LNK); "
        "$s.TargetPath = $env:VI_TARGET; "
        "$s.Arguments = $env:VI_ARGS; "
        "$s.WorkingDirectory = $env:VI_WORKDIR; "
        "$s.Description = 'VoiceInput 语音输入'; "
        "$s.Save()"
    )
    env = {
        **os.environ,
        "VI_LNK": str(lnk),
        "VI_TARGET": target,
        "VI_ARGS": args,
        "VI_WORKDIR": workdir,
    }
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or not lnk.exists():
        raise RuntimeError(f"创建启动项失败: {result.stderr.strip() or '未知错误'}")


def disable() -> None:
    lnk = shortcut_path()
    if lnk.exists():
        try:
            lnk.unlink()
        except OSError as e:
            raise RuntimeError(f"删除启动项失败: {e}") from e


def set_enabled(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()


def apply(enabled: bool) -> str:
    """把自启设成想要的样子。返回要告诉用户的话,没有就是空串。

    **和磁盘上的真实状态比,不和上一次的配置比。** 用户可能自己把启动
    文件夹里的快捷方式删了 —— 那时配置里还写着 true,按"配置有没有变"
    来判断的话就永远不会有人去修好它。(设置页那个复选框也是读真实状态的,
    两边得一致。)

    读状态失败只记日志:那是个只读检查,失败了下次还有机会;
    而**设置失败必须告诉用户** —— 他明确要求了开机自启,没做到就得说。
    """
    try:
        if is_enabled() == enabled:
            return ""
    except OSError as e:
        log.warning("检查开机自启失败: %s", e)
        return ""
    try:
        set_enabled(enabled)
    except RuntimeError as e:
        return str(e)
    return ""
