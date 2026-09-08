"""界面上"现在是什么状态"这件事。

同一个状态要在三个地方同时说:托盘图标、主窗口状态栏、悬浮麦克风。
三处各自 set 的话,早晚会出现托盘写着"就绪"而悬浮麦克风还亮着录音色。

**这里守着一条不变量:正在录音或识别时,任何"回到就绪"的刷新都不许生效。**
引擎加载完成、错误提示过期、配置保存完 —— 这些异步回调都可能在用户
已经重新开始录音之后才到,直接 set 就会把"正在聆听"覆盖成"就绪",
而录音其实还在继续。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger("voiceinput")

# 错误提示在状态栏上停留多久。比悬浮条上的 4000ms 稍长,
# 免得状态栏先变回"就绪"而悬浮条还红着。
ERROR_LINGER_MS = 4200

# 启动阶段的警告晚多久再弹。界面还在铺的时候弹会被盖掉。
STARTUP_WARNING_DELAY_MS = 1500

# 两条启动警告之间留的空档,让人看得出是两条而不是一条闪了一下。
_WARNING_GAP_MS = 400


class StatusPresenter(QObject):
    """把一个状态同时说给托盘、状态栏、悬浮麦克风。

    `idle_state` 回答"闲着的时候该显示什么",`is_idle` 回答"现在闲着吗" ——
    这两件事是业务判断,归 App;这里只负责什么时候显示、显示到哪几处。
    """

    def __init__(
        self,
        tray,
        window,
        badge,
        overlay,
        idle_state: Callable[[], tuple[str, str, str]],
        is_idle: Callable[[], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tray = tray
        self._window = window
        self._badge = badge
        self._overlay = overlay
        self._idle_state = idle_state
        self._is_idle = is_idle
        self._next_warning_ms = 0

        # **用同一个定时器并重启,不能每次 singleShot 起一个新的**:
        # 4.2 秒内失败两次就会有两个定时器在跑,先到的那个把状态重置成
        # "就绪",而第二次失败的错误还挂在界面上;更糟的是这期间若已
        # 重新开始录音,过期定时器会在录音中途把状态改成"就绪"。
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        # 间隔在这里定一次。`start(ms)` 每次传参会把间隔一起改掉 ——
        # 那样"停留多久"就变成了调用点的事,而它是这个对象的属性。
        self._reset_timer.setInterval(ERROR_LINGER_MS)
        self._reset_timer.timeout.connect(self.refresh)

    # ---- 显示 ----

    def show(self, state: str, text: str, detail: str = "") -> None:
        """无条件显示。调用方确定这就是当前状态时才用。"""
        self._tray.set_state(state, text)
        self._window.set_status(state, text, detail)
        # 悬浮麦克风是用户视线里最近的反馈,状态必须跟着走
        self._badge.set_state("paused" if self._tray.is_paused else state)

    def show_idle(self) -> None:
        """按"闲着该显示什么"来显示,**绕过忙碌守卫**。

        暂停/恢复是用户的显式操作,即便正在录音也应该如实反映。
        """
        self.show(*self._idle_state())

    def refresh(self) -> None:
        """把状态刷回该有的样子。**正在录音或识别时什么都不做。**"""
        if not self._is_idle():
            return
        self.show_idle()

    def fail(self, message: str) -> None:
        """失败必须看得见 —— 静默失败会让用户以为没按到热键,反复重试。"""
        log.warning("%s", message)
        self.show("error", "出错了", message)
        self._overlay.show_error(message, 4000)
        self._reset_timer.start()

    def warn_later(self, text: str, linger_ms: int) -> None:
        """启动阶段发现的问题,晚一点再弹。

        用它说的都是"程序知道、用户不知道"的事:设备被悄悄换掉了、
        热键被别的程序占着。这类事**不会报任何错**,不主动说就等于没有。

        两件事都要注意:

        - **延迟是必须的。** 启动那一刻界面还在铺,这时候弹出来会被盖掉。
        - **多条要排队。** 悬浮条只有一个,同时弹两条的话后一条直接把前一条
          顶掉,用户只看得见其中一条 —— 而这两条恰恰都是他需要知道的。
          (测试里实测过:两条同时安排,显示顺序连稳定都不稳定。)
        """
        delay = max(STARTUP_WARNING_DELAY_MS, self._next_warning_ms)
        self._next_warning_ms = delay + linger_ms + _WARNING_GAP_MS
        QTimer.singleShot(delay,
                          lambda: self._overlay.show_warning(text, linger_ms))

    def stop(self) -> None:
        self._reset_timer.stop()
