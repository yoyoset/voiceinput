"""应用主控:把热键线程、识别线程、UI 线程串起来。

线程边界(容易出错的地方,先说清楚):

- pynput 的热键回调跑在**它自己的监听线程**上,里面绝不能做耗时的事,
  否则整个键盘事件队列被堵住,表现为系统级卡键。所以回调只发 Qt 信号,
  经队列连接甩到主线程。
- 模型加载和推理在 **EngineHost 管的那个线程**上。
- 剪贴板和所有界面操作只能在**主线程**。粘贴用 QTimer 串,不用 sleep。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from . import autostart, config as config_mod
from .cancel_key import CancelKey
from .config import Config, app_dir
from .delivery import Delivery
from .engine_host import EngineHost
from .engine_status import EngineStatus
from .foreground import foreground_window
from .history_host import HistoryHost
from .hotkey_host import HotkeyHost
from .microphone import Microphone
from .postprocess import finalize
from .session import RecordingSession
from .settings import Settings
from .ui.history_window import HistoryWindow
from .ui.main_window import MainWindow
from .ui.badge_placement import BadgePlacement
from .ui.mic_badge import MicBadge
from .ui.overlay import Overlay
from .ui.theming import Theme
from .ui.status import StatusPresenter
from .ui.tray import Tray
from .wizard_host import WizardHost

log = logging.getLogger("voiceinput")


def _listening_text(action: str) -> str:
    return "正在聆听(说完直接发送)" if action == "paste_and_send" else "正在聆听"


class App(QObject):
    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self.qapp = qapp
        # 先判断再 load:load 对缺文件和坏文件都返回默认值,分不出是哪种
        self._is_first_run = not config_mod.CONFIG_PATH.exists()
        self.settings = Settings(config_mod.load(), self)
        log.info("启动,程序目录 %s", app_dir())

        self.theme = Theme(qapp, self.cfg, self)

        self.history = HistoryHost(self.cfg, self)
        self.session = RecordingSession(self)
        self.delivery = Delivery(self.cfg, self._yield_focus, self)
        # 按下热键那一刻的前台窗口——识别结果送出去时用来判断目标窗口
        # 有没有被换掉,见 `_begin_recording` / `_on_transcribed`。
        self._target_window: int | None = None

        self.overlay = Overlay(self.theme.palette)
        self.badge = MicBadge(self.theme.palette)
        self.tray = Tray(self.theme.palette)
        self.window = MainWindow(self.cfg, self.theme.palette, self.history.current)
        self.history_window = HistoryWindow(self.theme.palette, self.history.current)

        self.mic = Microphone(self)

        self.status = StatusPresenter(
            self.tray, self.window, self.badge, self.overlay,
            idle_state=self._current_idle_state,
            is_idle=lambda: self.session.is_idle,
            parent=self,
        )
        self.engine = EngineHost(self)
        self.engine_status = EngineStatus(
            self.window, self.overlay, self.status,
            is_idle=lambda: self.session.is_idle, parent=self)
        self.wizard = WizardHost(self.engine, self)
        self.placement = BadgePlacement(self.badge, self.settings, self)
        self.hotkeys = HotkeyHost(self)
        self.cancel_key = CancelKey(self)

        self._wire()
        # 解析设备**必须在 _wire 之后**:结果可能带一句要告诉用户的话,
        # 而那句话是通过信号出来的 —— 线还没接上就等于没说。
        self.overlay.apply(self.cfg)
        self.tray.apply(self.cfg)
        self.mic.apply(self.cfg)
        self.engine.start()
        self._reload_engine()
        self.hotkeys.apply(self.cfg)
        self.cancel_key.start()

        self.tray.show()
        self.placement.apply(self.cfg)

        # 没有配置文件 = 第一次运行。此时大概率连模型都没有,
        # 直接扔给用户一个"模型未加载"的红字很不友好,走向导。
        if self._is_first_run:
            QTimer.singleShot(200, self.show_wizard)
        elif not self.cfg.start_minimized:
            self.window.show()

    @property
    def cfg(self) -> Config:
        """当前配置。只读别名 —— 换配置一律走 `settings.update()`,
        那条路会落盘并通知所有子系统。"""
        return self.settings.current

    # ================= 装配 =================

    def _wire(self) -> None:
        self.tray.openRequested.connect(self._show_window)
        self.tray.historyRequested.connect(self.history_window.open)
        self.window.historyWindowRequested.connect(self.history_window.open)
        self.history_window.repasteRequested.connect(self.delivery.resend)
        self.tray.quitRequested.connect(self.shutdown)
        self.tray.pauseToggled.connect(self._on_pause_toggled)
        self.tray.wizardRequested.connect(self.show_wizard)
        self.tray.sendAfterChanged.connect(self._set_badge_action)

        # 桌面上一个圆按钮,出了问题第一反应就是右键点它。用托盘那一份菜单 ——
        # 两份会漂移成不一样的选项,而且没人会发现。
        self.badge.set_menu(self.tray.contextMenu())

        self.window.configChanged.connect(self.settings.update)
        self.window.engineReloadRequested.connect(self._reload_engine)
        self.window.modelDownloadRequested.connect(self.show_wizard)
        self.history_window.addToDictionaryRequested.connect(self._add_to_dictionary)
        self.delivery.pasted.connect(self.overlay.show_result)
        self.delivery.blocked.connect(self._on_delivery_blocked)

        self.hotkeys.startRequested.connect(self._begin_recording)
        self.hotkeys.stopRequested.connect(self.session.finish)
        self.hotkeys.upgradeRequested.connect(self._upgrade_action)
        self.hotkeys.registerFailed.connect(
            lambda msg: self.status.show("error", "热键注册失败", msg))
        # 热键被占着不会报任何错,按下去两个程序一起动 —— 必须主动说
        self.hotkeys.conflictDetected.connect(lambda actions: self.status.warn_later(
            f"热键「{actions}」被别的程序占用了,按下去两边都会响应。"
            "可以在设置里换一个,或者直接用桌面上的悬浮麦克风。", 9000))

        self.badge.clicked.connect(self._toggle_from_badge)

        self.session.started.connect(self._on_recording_started)
        self.session.levelChanged.connect(self._on_level)
        self.session.noteChanged.connect(self.overlay.set_note)
        self.session.ready.connect(self._on_audio_ready)
        self.session.failed.connect(self.status.fail)
        self.session.timedOut.connect(self._on_transcribe_timeout)
        self.session.cancelled.connect(self._on_cancelled)

        self.cancel_key.pressed.connect(self.session.cancel)

        self.engine.loading.connect(self.engine_status.loading)
        self.engine.ready.connect(self.engine_status.ready)
        self.engine.failed.connect(self.engine_status.failed)
        self.engine.transcribed.connect(self._on_transcribed)
        self.engine.transcribeFailed.connect(self._on_transcribe_failed)

        # 换配色时谁需要被通知,登记在一处 —— 新加带配色的控件时
        # 不用再回到配置分发里补一行
        self.theme.watch(self.overlay.set_palette, self.badge.set_palette,
                         self.tray.set_palette, self.window.apply_palette,
                         self.history_window.set_palette)

        self.mic.noteChanged.connect(lambda note: self.status.warn_later(note, 6000))
        # 开关了历史就换了个对象(或者没有对象了),界面得跟着换
        self.history.changed.connect(self.window.set_history)
        self.history.changed.connect(self.history_window.set_history)

        # **配置变了之后谁要跟着动,就是这份名单。**
        # 各家自己判断"跟我有关的那几项变了没",所以这里不写任何比较。
        self.settings.follow(
            self.theme.apply,
            self.hotkeys.apply,
            self.mic.apply,
            self.history.apply,
            self.engine.apply,
            self.placement.apply,
            self.delivery.apply,
            self._apply_autostart,
            self.overlay.apply,
            self.tray.apply,
            lambda cfg: self.status.refresh(),
        )

        self.wizard.configCommitted.connect(self.settings.update)
        # 向导里可能刚装好模型、改了设备,回到主界面让用户看到当前状态
        self.wizard.closed.connect(self._show_window)

    # ================= 引擎 =================

    def _reload_engine(self) -> None:
        self.engine.load(self.cfg)

    # ================= 录音 =================
    #
    # 录音本身的状态(Recorder、忙碌标记、看门狗、电平定时器)全在
    # RecordingSession 里,这里只负责"什么时候允许开始"和"结果怎么显示"。

    @Slot(str)
    def _begin_recording(self, action: str) -> None:
        if self.tray.is_paused:
            return
        if not self.engine.is_ready:
            self.overlay.show_error("模型还没加载好", 2500)
            return
        # 记下这一刻的前台窗口。说话 + 识别要花点时间,这段时间里
        # 用户点去别的窗口的话,结果不该硬贴过去——见 `_on_transcribed`。
        self._target_window = foreground_window()
        self.session.begin(action, self.mic.index, self.cfg.audio.max_seconds)

    def _on_recording_started(self, action: str) -> None:
        self.status.show("recording", "正在聆听")
        self.overlay.show_recording(_listening_text(action))

    @Slot(str)
    def _upgrade_action(self, action: str) -> None:
        """按下过程中动作被升级了(比如补按了 Shift)。

        录音照常继续 —— 两个动作录的音频一样。这里只是把悬浮条文案改对,
        否则会一直显示"正在聆听"而实际松开后会直接发送。
        """
        if not self.session.is_recording:
            return
        self.overlay.show_recording(_listening_text(action))

    def _on_cancelled(self) -> None:
        """Esc 取消了录音。回到就绪,顺手说一句"确实取消了"。"""
        self.status.refresh()
        self.overlay.show_cancelled()

    def _on_level(self, level: float) -> None:
        self.overlay.set_level(level)
        self.badge.set_level(level)   # 外圈随音量涨落 = "它真的听到了"

    def _on_audio_ready(self, audio, sample_rate: int, action: str) -> None:
        self.status.show("busy", "识别中…")
        self.overlay.show_busy("识别中…")
        self.engine.transcribe(audio, sample_rate, action)

    def _on_transcribe_timeout(self, message: str) -> None:
        """识别迟迟不返回。**先把还挂着的调用方放掉**,再报错。

        这里问的是"有没有人在等"(`deliver` 的返回值),而下面两处问的是
        "这次录音是不是向导要的"(`action == "wizard"`)。看着像不一致,
        **但不能统一成前者**:向导用的是它自己的 Recorder,和主会话并行,
        拿 `deliver` 当判据的话,一次普通听写的结果会被向导那个还挂着的
        回调吃掉 —— 用户说的话就凭空消失了。
        超时这条只是没有 action 可问,不得已才用返回值。
        """
        if self.wizard.deliver(None, "识别超时"):
            return
        self.status.fail(message)

    # ================= 识别结果 =================

    @Slot(object, str)
    def _on_transcribed(self, result, action: str) -> None:
        self.session.settle()

        # 向导的标定录音走这条路:只把结果回传,不粘贴、不写历史
        if action == "wizard":
            self.wizard.deliver(result.text or "", None)
            return

        raw = result.text or ""
        text, problem = finalize(raw, self.cfg.replacements)
        if problem:
            self.status.fail(problem)
            return

        log.info("识别 %.2fs/%.1fs: %s", result.infer_seconds, result.audio_seconds, text)
        # 引擎页上显示的性能数字来自这里 —— 这台机器刚跑出来的,
        # 不是开发机的成绩
        self.window.set_measured(result.infer_seconds, result.audio_seconds)
        self.history.add(text, raw, result.audio_seconds,
                         result.infer_seconds, "sensevoice")
        self.history_window.refresh()

        self.status.refresh()
        warning = self.session.take_warning()
        if warning:
            # 文字照常粘贴(残缺的总比没有强),但提示要停久一点让人看清。
            # **削过音这件事必须说**,所以走 warning —— 它不受"关掉提示条"影响。
            self.overlay.show_warning(f"{warning} —— 已粘贴识别到的部分", 4500)
        else:
            self.overlay.show_result(text)
        self.delivery.send(text, then_enter=(action == "paste_and_send"),
                          expected_window=self._target_window)

    def _on_delivery_blocked(self, text: str) -> None:
        """目标窗口换了,没敢硬贴。文字已经在剪贴板里,得说清楚,
        不能让它看起来像是凭空消失了。"""
        self.overlay.show_warning(
            "原来的窗口已经切换,识别结果已复制到剪贴板,自己粘贴一下", 5000)

    @Slot(str, str)
    def _on_transcribe_failed(self, message: str, action: str) -> None:
        self.session.settle()
        if action == "wizard":
            self.wizard.deliver(None, message)
            return
        self.status.fail(message)

    # ================= 配置变更 =================

    def _apply_autostart(self, cfg: Config) -> None:
        problem = autostart.apply(cfg.autostart)
        if problem:
            QMessageBox.warning(self.window, "开机自启", problem)

    def _on_pause_toggled(self, paused: bool) -> None:
        self.status.show_idle()

    # ================= 杂项 =================

    def _current_idle_state(self) -> tuple[str, str, str]:
        """没有在录音/识别时,状态栏该显示什么。

        原来这段逻辑在五个地方各写了一遍(引擎加载完、识别完、错误提示过期、
        配置变更、暂停切换),改一处就得记得改另外四处。
        """
        if self.tray.is_paused:
            return ("loading", "已暂停", "托盘菜单里可恢复")
        if not self.engine.is_ready:
            return ("error", "模型未加载", "")
        return ("ready", "就绪", self.hotkeys.summary())

    # ================= 悬浮麦克风 =================

    def _toggle_from_badge(self) -> None:
        """点悬浮麦克风:第一下开始,第二下结束。

        热键是"按住说话",鼠标按住不放很别扭,所以这里用点击切换。
        **这条路径不依赖全局热键** —— 热键被别的软件占用时(实测和微信撞过),
        它是唯一还能用的入口。

        做完是粘贴还是"粘贴并回车"由 `cfg.ui.badge_action` 决定
        (右键菜单里那个「点一下说完直接发送」)。
        """
        action = self.cfg.ui.badge_action
        if self.session.is_recording:
            self.session.finish(action)
        else:
            self._begin_recording(action)

    def _set_badge_action(self, send_after: bool) -> None:
        """右键菜单里勾了「说完直接发送」。

        **就地改再走 update()**,和设置页走同一条落盘+分发的路 ——
        另开一条"只存不通知"的捷径的话,设置页那个下拉框就不会跟着变,
        于是同一个开关在两处显示得不一样。
        """
        cfg = self.cfg
        cfg.ui.badge_action = "paste_and_send" if send_after else "paste"
        self.settings.update(cfg)

    def _show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _add_to_dictionary(self, text: str) -> None:
        """历史窗口里点了「加入词典」:打开设置窗口,词典页新建一行带着原句。"""
        self.window.add_to_dictionary(text)
        self._show_window()

    def _yield_focus(self) -> bool:
        """把前台焦点让出去,返回是否真的动了手。

        从历史重新粘贴时要用:前台窗口是 VoiceInput 自己,不藏起来的话
        文字会粘进它自己的搜索框。主窗口和历史窗口**两个都要藏** ——
        只藏一个的话,焦点会落到另一个上,粘贴照样进了自己。
        本来就没显示就什么都不用做。
        """
        moved = False
        for w in (self.window, self.history_window):
            if w.isVisible():
                w.hide()
                moved = True
        return moved

    # ================= 向导 =================

    def show_wizard(self) -> None:
        """打开设置向导。首次运行自动弹,之后可以从托盘或设置页手动打开。

        向导要的后端是 WizardHost 自己 —— App 不再转发那三个方法。
        """
        self.wizard.open(self.cfg, self.theme.palette)

    def shutdown(self) -> None:
        log.info("退出")
        # 配置变更是防抖的,退出前得把还压着的那次发出来,否则用户改完
        # 最后一项就关程序,那次改动会随没触发的定时器一起丢掉
        self.window.flush_pending()
        self.hotkeys.stop()
        self.cancel_key.stop()
        self.status.stop()
        self.session.abort()
        self.engine.stop()
        self.history.close()
        self.badge.hide()
        self.tray.hide()
        self.qapp.quit()

