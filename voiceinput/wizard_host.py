"""向导的开关,以及"它正在等一个标定结果"这件事。

拆出来的判据是**谁在改这两样状态**:那个对话框实例、和那个还没回来的
标定回调。以前它俩是 App 上的 `_wizard` / `_wizard_cb`,被五处代码
各自读写(打开向导、关闭向导、识别成功、识别失败、识别超时)。

**这里守着一条不变量:向导一销毁,等待中的回调就必须丢掉。**
那个回调指向向导里的控件,对着已销毁的 Qt 对象调会抛 RuntimeError ——
而它是在识别线程回来时才被调用的,也就是说崩溃发生在用户关掉向导
之后好几秒,现场早就没了。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("voiceinput")

Callback = Callable[[str | None, str | None], None]


class WizardHost(QObject):
    """一次只允许开一个向导。"""

    configCommitted = Signal(object)   # Config,向导点了完成/跳过
    closed = Signal()

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._dialog = None
        self._pending: Callback | None = None
        self._cfg = None

    @property
    def is_open(self) -> bool:
        return self._dialog is not None

    @property
    def is_waiting(self) -> bool:
        """向导正在等一个标定结果。"""
        return self._pending is not None

    def open(self, cfg, palette) -> None:
        """打开向导。已经开着就把它拿到前面来,不再开第二个。

        **后端就是这个对象自己。** 向导要的三样东西(引擎准备好没、
        重新加载模型、跑一次标定转写)都是关于引擎的,而"谁在等标定结果"
        本来就归这里管 —— 让 App 转发一遍只是多一层。
        """
        from .ui.wizard import Wizard

        self._cfg = cfg
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return

        dialog = Wizard(cfg, palette, self)
        self._dialog = dialog
        dialog.finished_setup.connect(self.configCommitted.emit)
        dialog.finished.connect(self._on_closed)
        dialog.show()

    def _on_closed(self, *_) -> None:
        self._dialog = None
        # **这一句是这个类存在的理由。** 标定录音可能还在识别中,
        # 回调指向向导里的控件,向导销毁后再调会抛 RuntimeError。
        self._pending = None
        self.closed.emit()

    # ---- 向导要的后端接口 ----

    def is_engine_ready(self) -> bool:
        return self._engine.is_ready

    def reload_engine(self) -> None:
        """向导刚装好模型,让引擎去认它。

        **必须是 `load` 而不是 `apply`。** 模型目录这个字符串可能一点没变
        (原来就指着这个路径,只是里面没东西),`apply` 会认为"没变"而跳过 ——
        表现是下载完成了却一直"模型未加载"。
        """
        if self._cfg is not None:
            self._engine.load(self._cfg)

    def transcribe_async(self, audio, sample_rate: int, callback: Callback) -> None:
        """给标定用的一次性转写。结果原样回传,不粘贴也不写历史。"""
        if not self._engine.is_ready:
            callback(None, "模型尚未加载完成")
            return
        self.expect(callback)
        self._engine.transcribe(audio, sample_rate, "wizard")

    # ---- 标定结果 ----

    def expect(self, callback: Callback) -> None:
        """记下一个等待中的标定回调。"""
        self._pending = callback

    def deliver(self, text: str | None, error: str | None) -> bool:
        """把结果交给等待中的回调。没人在等就返回 False,由调用方另行处理。

        **回调只用一次**,交完就清掉 —— 否则下一次普通听写的结果
        会被塞进一个早就不该收东西的地方。
        """
        callback, self._pending = self._pending, None
        if callback is None:
            return False
        try:
            callback(text, error)
        except RuntimeError as e:
            # 向导控件已销毁而 closed 信号还没到。丢掉,不能让它冒到
            # Qt 的信号处理里去 —— 那会变成一次无人接管的崩溃。
            log.warning("向导回调已失效: %s", e)
        return True
