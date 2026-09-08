"""命令行入口的实际逻辑。

**为什么不直接写在 `__main__.py` 里**:PyInstaller 会把入口脚本当成顶层脚本执行,
`__package__` 是空的,于是 `from .app import main` 这类相对导入全部报
`ImportError: attempted relative import with no known parent package`,
打出来的 exe 根本起不来。

所以入口逻辑放在这个**包内模块**里(在这里相对导入是合法的),
外面由两个薄壳去调它,两边都用绝对导入:

  - `voiceinput/__main__.py` —— 支持 `python -m voiceinput`
  - `entry.py`(项目根)      —— 给 PyInstaller 用

这个坑很隐蔽:windowed 打包时 `disable_windowed_traceback=False` 会弹一个
错误对话框等人点,从命令行看就是"进程活着、CPU 接近零、没有任何输出",
非常像卡死。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---- 启动面包屑 ----
#
# windowed exe 没有 stdout,卡在 import 阶段时线索为零。所以在导入任何
# 重量级模块之前就开始逐行落盘,每个 import 前记一行。
# 只用 os/sys/pathlib,它们不可能是卡住的原因,所以面包屑本身可信。

_TRACE = os.environ.get("VOICEINPUT_TRACE") == "1" or "--selftest" in sys.argv

# 单例锁用的命名 Mutex。名字里带随机后缀纯粹是避免和别的软件撞名字,
# 没有别的含义。
_SINGLETON_MUTEX_NAME = "VoiceInput-SingleInstance-3F6E1B2C"
_ERROR_ALREADY_EXISTS = 183

# 必须一直握着这个句柄:一旦被 GC/关闭,Windows 就当我们退出了,
# 别的实例的 CreateMutexW 就不会再报"已存在"。不主动 CloseHandle ——
# 进程退出(含崩溃)时系统会自动回收,这比在异常路径上记着去关更可靠。
_singleton_handle = None


def _acquire_singleton() -> bool:
    """True = 拿到锁,这是唯一实例;False = 已经有一个在跑。

    非 Windows 平台直接放行——这个锁本来就是给 Windows 单机托盘场景用的。
    """
    global _singleton_handle
    if not sys.platform.startswith("win"):
        return True

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, _SINGLETON_MUTEX_NAME)
    if not handle:
        return True  # Mutex 建不了就别拦启动,这不该是个阻断性故障
    _singleton_handle = handle
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def _base_dir() -> Path:
    """和 `config.app_dir()` 逻辑一样,但**不能直接调它**——面包屑存在的
    意义就是在导入任何重量级模块之前先落盘一行,而 `config.py` 本身
    正是要被面包屑记录的那一批导入之一。调 `app_dir()` 等于让面包屑
    依赖它要追踪的东西,这两份短小的重复是那条边界的代价,不是漏拆分。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _crumb(msg: str) -> None:
    if not _TRACE:
        return
    try:
        with (_base_dir() / "startup-trace.txt").open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def _setup_logging() -> None:
    """把日志配好,**在任何重量级导入之前**。

    原来这件事在 `App.__init__` 里做,也就是所有 import 都跑完之后 ——
    而最需要日志的恰恰是启动阶段。`--selftest` 那条路更是从来没配过,
    于是自检里的 warning 全落到未配置的 root logger 上:
    开发时打到 stderr,**windowed 打包后直接消失**。
    """
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(_base_dir() / "voiceinput.log", encoding="utf-8")],
    )


def main() -> int:
    _crumb(f"--- start argv={sys.argv} frozen={getattr(sys, 'frozen', False)} "
           f"package={__package__!r}")
    try:
        _setup_logging()
    except OSError:
        pass          # 日志文件建不了不该拦住启动

    if "--selftest" in sys.argv:
        # 自检不能走 app:那会创建 QApplication、托盘和全局热键监听,
        # 抢占热键是自检不该有的副作用。
        _crumb("importing selftest")
        from .selftest import run

        _crumb("running selftest")
        code = run()
        _crumb(f"selftest done rc={code}")
        return code

    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    if not _acquire_singleton():
        _crumb("another instance already running, exiting")
        qapp = QApplication(sys.argv)  # 弹窗需要一个 QApplication 才能显示
        QMessageBox.information(None, "VoiceInput", "已经有一个 VoiceInput 在运行了。")
        return 0

    _crumb("importing app")
    from .app import App

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("VoiceInput")
    qapp.setQuitOnLastWindowClosed(False)  # 关窗口不退出,留在托盘

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "VoiceInput", "系统托盘不可用,无法启动。")
        return 1

    _crumb("running app")
    app = App(qapp)          # noqa: F841 - 持有引用,别被 GC 掉
    return qapp.exec()
