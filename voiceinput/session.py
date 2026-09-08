"""一次"按下 → 说话 → 松开 → 等识别结果"的过程。

拆出来的判据是**谁在改这些状态**:当前的 Recorder、是不是在等识别结果、
这次录音有没有被削过、电平定时器、识别看门狗 —— 这五样以前散在 App 里,
被七八个方法各自读写。现在只有这里能碰。

**这个文件不认识任何界面。** 它只发信号说"开始了""电平是多少""失败了"
"音频准备好了",怎么显示由 App 决定。这样整条录音状态机可以在没有
Qt 窗口、没有托盘、没有悬浮条的情况下单独测。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from .audio import Recorder, RecordingError, looks_silent

log = logging.getLogger("voiceinput")

# 识别看门狗超时。正常一句话 0.3 秒转完,30 秒还没回来一定是出事了。
TRANSCRIBE_TIMEOUT_MS = 30_000

LEVEL_POLL_MS = 60


class RecordingSession(QObject):
    """录音会话的状态机。一个 App 只需要一个。"""

    started = Signal(str)                    # action
    levelChanged = Signal(float)             # dBFS
    noteChanged = Signal(str)                # 悬浮条上的小字(已录时长 / 上限)
    ready = Signal(object, int, str)         # audio, sample_rate, action
    failed = Signal(str)                     # 人话形式的失败原因

    # **超时和普通失败不是一回事**,所以不合并成一个信号:
    # 普通失败(没录到音、只有静音)是录音本身的问题,只需要告诉用户;
    # 超时意味着**有一个还在等结果的调用方**(比如向导的标定回调),
    # 必须先把它放掉,否则它会一直挂着。
    timedOut = Signal(str)

    cancelled = Signal()
    """录音被主动取消(按了 Esc)。**不是失败** —— 用户是故意的,
    音频被直接扔掉,不走"没录到音/只录到静音"那些判断,也不识别。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recorder: Recorder | None = None
        self._busy = False
        self._warning = ""

        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._push_level)

        # `_busy` 在识别开始时置 True、拿到结果时置 False。万一 worker 因为任何
        # 原因不返回(模型崩了、线程卡死),`_busy` 会永远是 True,之后按热键
        # **什么都不会发生、也没有任何提示** —— 正是这个项目最想排除的静默失败。
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_timeout)

    # ---- 外部只读的状态 ----

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None

    @property
    def is_busy(self) -> bool:
        """已经松开、正在等识别结果。"""
        return self._busy

    @property
    def is_idle(self) -> bool:
        return self._recorder is None and not self._busy

    def take_warning(self) -> str:
        """取走"这次录音被削过"的提示,取完就清空(它只该说一次)。"""
        warning, self._warning = self._warning, ""
        return warning

    # ---- 开始 ----

    def begin(self, action: str, device: int | None, max_seconds: float) -> bool:
        """开始录音。已经在录、或正在等识别结果时什么都不做。"""
        if self._busy or self._recorder is not None:
            return False
        try:
            self._recorder = Recorder(
                device=device,
                # 不指定 = 用设备原生速率。写死 16000 会让 WASAPI 设备
                # 直接开不了流,见 audio.native_sample_rate。
                sample_rate=None,
                max_seconds=max_seconds,
            )
            self._recorder.start()
        except RecordingError as e:
            self._recorder = None
            self.failed.emit(str(e))
            return False

        self._level_timer.start(LEVEL_POLL_MS)
        self.started.emit(action)
        return True

    def _push_level(self) -> None:
        rec = self._recorder
        if rec is None:
            return
        self.levelChanged.emit(rec.peek_level())

        # 把已录时长和上限显示出来。撞到上限才发现被截断就太晚了,
        # 快到的时候要能看见。
        elapsed, limit = rec.duration_seconds, rec.max_seconds
        if limit and elapsed >= limit * 0.8:
            self.noteChanged.emit(f"{elapsed:.0f}s / 上限 {limit:.0f}s")
        elif elapsed >= 10:
            self.noteChanged.emit(f"{elapsed:.0f}s")
        else:
            self.noteChanged.emit("")

    # ---- 结束 ----

    def finish(self, action: str) -> None:
        """松开热键。音频过关就发 ready,不过关就发 failed。"""
        self._level_timer.stop()
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            return

        audio = recorder.stop()
        if audio.size == 0:
            self.failed.emit("没有录到音频")
            return
        if looks_silent(audio):
            # 这是最常见的"以为成功其实失败":设备选错(比如录到系统回环)、
            # 麦克风静音、离得太远。必须明确说出来,不能静默。
            self.failed.emit("只录到静音,检查麦克风设备是否选对")
            return

        # 音频被削过就必须说。这两种情况下识别结果看着是完整一句话,
        # 实际缺了内容,用户不被告知根本发现不了。
        self._warning = ""
        if recorder.truncated:
            self._warning = f"超过 {recorder.max_seconds:.0f} 秒上限,后面的话没录进去"
            log.warning("录音被截断: 上限 %.0fs", recorder.max_seconds)
        elif recorder.overflowed:
            self._warning = "录音期间有丢帧,结果可能缺字"
            log.warning("录音溢出丢帧")

        self._busy = True
        self._watchdog.start(TRANSCRIBE_TIMEOUT_MS)
        # **必须是实际录音用的速率**,不能写死 16000。
        # 按 48k 录完却声明 16k,识别会悄悄变差而不是报错。
        self.ready.emit(audio, recorder.sample_rate, action)

    def cancel(self) -> bool:
        """录音中途反悔。丢弃已录到的音频,不识别、不粘贴。

        和 `finish()` 的区别是"要不要处理这段音频"——`finish` 无论好坏都会
        走一遍识别流程;这里是用户明确反悔,连"只录到静音"这类判断都不需要
        跑,直接扔。

        **正在等识别结果时取消不了**,返回 False:那时候音频已经交出去了,
        已经没有"反悔"的窗口——`_busy` 期间 `_recorder` 本来就是 None。
        """
        if self._recorder is None:
            return False
        self._level_timer.stop()
        self._recorder.stop()
        self._recorder = None
        self.cancelled.emit()
        return True

    def settle(self) -> None:
        """识别有结果了(成功或失败都算)。看门狗停掉,忙碌标记放开。"""
        self._watchdog.stop()
        self._busy = False

    def _on_timeout(self) -> None:
        """识别迟迟不返回。把 busy 放开,否则热键从此静默失效。"""
        if not self._busy:
            return
        self._busy = False
        self.timedOut.emit(
            f"识别超时({TRANSCRIBE_TIMEOUT_MS // 1000} 秒没有返回),已恢复可用")

    def abort(self) -> None:
        """退出时收摊。定时器停掉,录音机关掉。"""
        self._level_timer.stop()
        self._watchdog.stop()
        if self._recorder is not None:
            self._recorder.stop()
            self._recorder = None
        self._busy = False
