"""主窗口:把各个设置分页装配起来,别的什么都不做。

窗口本身不认识任何一个具体控件 —— 控件属于分页(见 `pages/`),
分页自己知道怎么写回 Config。这里只负责三件事:
顶部状态条、分页的装配与切换、以及**配置变更的防抖与落盘时机**。

改了什么都通过信号交给 App 去执行。这样窗口关掉、重开、甚至根本不打开,
后台的录音-识别-粘贴链路都照常工作。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from .pages import (
    AboutPage,
    AudioPage,
    DictionaryPage,
    EnginePage,
    GeneralPage,
    HistoryPage,
)
from .theme import Palette

CONFIG_DEBOUNCE_MS = 300


class MainWindow(QMainWindow):
    configChanged = Signal(object)     # Config
    engineReloadRequested = Signal()
    modelDownloadRequested = Signal()
    historyWindowRequested = Signal()

    def __init__(self, cfg: Config, palette: Palette, history, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._palette = palette

        self.setWindowTitle("VoiceInput 语音输入")
        self.resize(680, 620)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())

        self.general = GeneralPage(cfg)
        self.audio = AudioPage(cfg, palette)
        self.engine = EnginePage(cfg)
        self.dictionary = DictionaryPage(cfg)
        self.history = HistoryPage(cfg, history)
        self.about = AboutPage()

        self.tabs = QTabWidget()
        for title, page in [
            ("常规", self.general), ("音频", self.audio), ("引擎", self.engine),
            ("词典", self.dictionary), ("历史", self.history), ("关于", self.about),
        ]:
            page.changed.connect(self._on_page_changed)
            self.tabs.addTab(page, title)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        self.general.badgeHomeRequested.connect(self._badge_home)
        self.engine.reloadRequested.connect(self.engineReloadRequested.emit)
        self.engine.downloadRequested.connect(self.modelDownloadRequested.emit)
        self.history.openWindowRequested.connect(self.historyWindowRequested.emit)

        # 配置变更防抖。
        #
        # 不加的话,拖一次数字框会连续发几十次 configChanged —— 实测把
        # 「粘贴前等待」从 80 拖到 200 就是 24 次。写盘本身很快(0.44ms)不是问题,
        # **真正的问题是「引擎」页的线程数**:每变一步都会触发一次完整的模型重载
        # (每次 3 秒),从 8 拖到 16 就是 8 次重载排队,二十多秒抖动。
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(CONFIG_DEBOUNCE_MS)
        self._config_timer.timeout.connect(self._flush_config)

    # ---- 顶部状态条 ----

    def _build_header(self) -> QHBoxLayout:
        self.status_dot = QLabel("●")
        self.status_dot.setFixedWidth(16)
        self.status_text = QLabel("正在启动")
        self.status_text.setProperty("role", "title")
        self.status_detail = QLabel("")
        self.status_detail.setProperty("role", "subtitle")

        top = QHBoxLayout()
        top.setSpacing(7)
        top.addWidget(self.status_dot)
        top.addWidget(self.status_text)
        top.addStretch(1)

        left = QVBoxLayout()
        left.setSpacing(1)
        left.addLayout(top)
        left.addWidget(self.status_detail)

        bar = QHBoxLayout()
        bar.addLayout(left, 1)
        return bar

    def set_status(self, state: str, text: str, detail: str = "") -> None:
        color = {
            "ready": self._palette.accent,
            "recording": self._palette.accent,
            "busy": self._palette.warning,
            "error": self._palette.danger,
            "loading": self._palette.text_dim,
        }.get(state, self._palette.text_dim)
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 15px;")
        self.status_text.setText(text)
        self.status_detail.setText(detail)

    # ---- 转给分页 ----

    def set_model_status(self, ok: bool, message: str) -> None:
        self.engine.set_model_status(ok, message)

    def set_measured(self, infer_seconds: float, audio_seconds: float) -> None:
        self.engine.set_measured(infer_seconds, audio_seconds)

    def set_history(self, history) -> None:
        self.history.set_history(history)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.audio.apply_palette(palette)

    # ---- 配置的收集与落盘时机 ----

    def collect(self) -> Config:
        """把所有分页的当前值汇总成一个 Config。

        **就地改 self._cfg 而不是新建一个**:配置里有些字段不属于任何控件
        (比如悬浮麦克风被拖到哪了),新建的话那些值会被抹掉。
        """
        for page in (self.general, self.audio, self.engine,
                     self.dictionary, self.history, self.about):
            page.collect(self._cfg)
        return self._cfg

    def _on_page_changed(self) -> None:
        self._config_timer.start()

    def _flush_config(self) -> None:
        self._config_timer.stop()
        self.configChanged.emit(self.collect())

    def flush_pending(self) -> None:
        """把还没发出的改动立刻发出去。

        退出前必须调:否则用户改完最后一项就关掉程序,那次改动会随着
        没触发的定时器一起丢掉。
        """
        if self._config_timer.isActive():
            self._flush_config()

    def add_to_dictionary(self, text: str) -> None:
        """历史窗口点了「加入词典」:切到词典页,新建一行,把选中的原句带过去。"""
        self.tabs.setCurrentWidget(self.dictionary)
        self.dictionary.prefill(text)

    def _badge_home(self) -> None:
        """把悬浮麦克风挪回默认位置。

        换显示器/改分辨率之后,存下来的坐标可能已经在屏幕外,
        那样按钮就永远看不见了 —— 得有个不靠鼠标找回来的办法。
        """
        self._cfg.ui.mic_badge_x = -1
        self._cfg.ui.mic_badge_y = -1
        self._on_page_changed()

    # ---- 生命周期 ----

    def _on_tab_changed(self, index: int) -> None:
        title = self.tabs.tabText(index)
        # 离开音频页就把电平监听停掉,别让麦克风一直被占着
        if title != "音频":
            self.audio.stop_test()
        if title == "历史":
            self.history.refresh_count()

    def closeEvent(self, event) -> None:  # noqa: N802
        """关窗口只是隐藏,程序继续在托盘里跑。"""
        self.audio.stop_test()
        self.flush_pending()   # 改完就关窗口,不能把这次改动压丢
        event.ignore()
        self.hide()
