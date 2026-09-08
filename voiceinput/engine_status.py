"""引擎的加载状态该往哪几个界面上写、写什么字。

拆出来的判据是**谁在改这个状态**:`EngineHost` 只管加载/推理那条线本身,
不该知道"加载完了要往主窗口、悬浮条、状态栏分别写什么字"——那是三个不同
控件的展示细节。这和 `StatusPresenter` 是同一类问题(一个状态要同时说给
好几个地方看),但对象不是同一个:`StatusPresenter` 管的是"闲着/录音/
识别中"这条主状态机,这里管的是引擎这条线自己的加载进度和保留意见,
两者各自独立更新——合并会让 `StatusPresenter` 认识本不该认识的
caveat 细节(哪个 provider 悄悄回退了、加载失败还能不能继续用旧模型)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Slot

log = logging.getLogger("voiceinput")


class EngineStatus(QObject):
    """把 `EngineHost` 的三个信号翻译成主窗口/悬浮条/状态栏该显示什么。"""

    def __init__(self, window, overlay, status, is_idle: Callable[[], bool],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._overlay = overlay
        self._status = status
        self._is_idle = is_idle

    def loading(self) -> None:
        # 录音中就别改状态栏了 —— 录音仍在继续,盖成"正在加载模型…"
        # 会让用户以为录音断了。加载本身照常进行。
        if self._is_idle():
            self._status.show("loading", "正在加载模型…")
        self._window.set_model_status(True, "正在加载…")

    @Slot(str, object)
    def ready(self, name: str, caveat) -> None:
        self._status.refresh()   # 用户可能已经在录音了,别覆盖
        if caveat is None:
            self._window.set_model_status(True, f"已加载:{name}")
            return
        # 跑起来了,但不是你以为的那样 —— 不说的话用户只会觉得"这工具就这样"
        self._window.set_model_status(False, f"已加载:{name}\n{caveat.detail}")
        log.warning("模型加载完成但有保留意见: %s", caveat.detail)
        if caveat.loud:
            self._overlay.show_warning(caveat.banner, 6000)

    @Slot(str, bool)
    def failed(self, message: str, still_usable: bool) -> None:
        # still_usable:新模型没加载起来,但旧的还在 worker 里活着。
        # 这时候不能把热键禁掉 —— 用户只是配置填错了,不该连原来能用的都没了。
        self._window.set_model_status(False, message)
        if still_usable:
            self._status.refresh()
            self._overlay.show_warning("新模型没加载成功,仍在用之前的模型", 5000)
            log.warning("模型加载失败,继续使用旧模型: %s", message)
        else:
            self._status.show("error", "模型未加载", message.splitlines()[0])
            self._overlay.show_error("模型加载失败,请在设置里检查", 5000)
            log.error("模型加载失败: %s", message)
