"""「常规」页:热键、输出时序、外观与启动。

放在一起是因为它们都是"程序怎么响应我"这一类设置,和音频/引擎那种
"用什么硬件、跑什么模型"是两件事。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton

from ... import autostart as autostart_mod
from ... import conflict
from ...config import Config
from ...hotkey import describe, labelled, validate as hotkey_validate
from ..hotkey_edit import HotkeyEdit
from ..widgets import Card, ComboBox, hint, labeled, spin
from .base import Page


class GeneralPage(Page):
    badgeHomeRequested = Signal()
    """把悬浮麦克风挪回默认位置。是一次性动作,不是一个配置值,所以走信号。"""

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent=parent)
        self._build_hotkeys(cfg)
        self._build_output(cfg)
        self._build_appearance(cfg)
        self.body.addStretch(1)

    # ---- 热键 ----

    def _build_hotkeys(self, cfg: Config) -> None:
        card = Card("热键")
        self.hk_paste = HotkeyEdit(cfg.hotkey.paste)
        self.hk_send = HotkeyEdit(cfg.hotkey.paste_and_send)
        self.hk_paste.changed.connect(self.emit_changed)
        self.hk_send.changed.connect(self.emit_changed)
        card.add_layout(labeled("粘贴文字", self.hk_paste))
        card.add_layout(labeled("粘贴并发送", self.hk_send))

        self.hk_mode = ComboBox()
        self.hk_mode.addItem("按住说话,松开结束", "push_to_talk")
        self.hk_mode.addItem("按一下开始,再按一下结束", "toggle")
        self.hk_mode.setCurrentIndex(0 if cfg.hotkey.mode == "push_to_talk" else 1)
        self.hk_mode.currentIndexChanged.connect(self.emit_changed)
        card.add_layout(labeled("触发方式", self.hk_mode))

        # 热键配置错了(比如两个绑成同一个)是静默失效的,必须当场说
        self.hk_problems = QLabel("")
        self.hk_problems.setWordWrap(True)
        self.hk_problems.setProperty("role", "danger")
        self.hk_problems.setVisible(False)
        card.add(self.hk_problems)

        row = QHBoxLayout()
        btn_probe = QPushButton("检查是否被别的程序占用")
        btn_probe.clicked.connect(self._probe_hotkeys)
        btn_free = QPushButton("自动换一个没人占用的")
        btn_free.clicked.connect(self._pick_free_hotkeys)
        row.addWidget(btn_probe)
        row.addWidget(btn_free)
        row.addStretch(1)
        card.add_layout(row)

        self.hk_probe = QLabel("")
        self.hk_probe.setWordWrap(True)
        self.hk_probe.setProperty("role", "hint")
        card.add(self.hk_probe)

        card.add(hint(
            "「粘贴并发送」会在粘贴后补一个回车,对着 Claude Code 连续说话时用。\n"
            "占用检查问的是 Windows 本身:它只看得见用系统接口注册的热键。"
            "有些软件走底层钩子(我们自己就是),那种撞了检查不出来 —— "
            "表现是按一下两边同时反应。\n"
            "实在配不好也不用慌 —— 桌面上那个悬浮麦克风完全不依赖热键。\n"
            "**说到一半按 Esc 可以取消这次录音,不会识别、不会粘贴** —— "
            "这个键固定,不能改,也不需要配。"
        ))
        self.body.addWidget(card)
        self.refresh_hotkey_problems()
        # 打开设置就该看见结论,而不是先点一下按钮才知道有没有撞。
        # 探测本身只是两次 RegisterHotKey,开销可以忽略。
        self._probe_hotkeys()

    def _bindings(self) -> dict[str, str]:
        return labelled({"paste": self.hk_paste.spec(),
                         "paste_and_send": self.hk_send.spec()})

    def refresh_hotkey_problems(self) -> None:
        problems = hotkey_validate(self._bindings())
        if not problems:
            # 文字也要清掉,不能只隐藏:留着过期文案,将来可见性逻辑一改
            # 就会把早就修好的问题又显示出来
            self.hk_problems.clear()
            self.hk_problems.setVisible(False)
            return
        self.hk_problems.setText("\n".join(p.describe() for p in problems))
        self.hk_problems.setVisible(True)

    # ---- 占用探测 ----
    #
    # 和上面的 validate 分开:validate 只看配置本身对不对,是纯函数;
    # 这里问的是**这台机器当前的状态**,答案随时会变(用户装了新软件、
    # 改了别的程序的热键),所以只在用户主动点的时候跑。

    def _probe_hotkeys(self) -> None:
        # 结论的措辞在 conflict.Verdict 里 —— 向导那一步显示的是同一份
        verdicts = conflict.report(self._bindings())
        self.hk_probe.setText("\n".join(v.marked() for v in verdicts))

    def _pick_free_hotkeys(self) -> None:
        """当场探测,给两个动作各挑一个空闲组合。

        **不预设哪个组合"应该没人用"** —— 那取决于这台机器装了什么,
        只有问系统才知道。开发机上的空闲组合在别人那儿可能正被占着。
        """
        first = conflict.suggest()
        second = conflict.suggest(exclude={first} if first else set())
        if first is None or second is None:
            self.hk_probe.setText("候选组合全都被占用了,请手动挑一个。")
            return
        self.hk_paste.set_spec(first)
        self.hk_send.set_spec(second)
        self.hk_probe.setText(
            f"已换成 {describe(first)} / {describe(second)},都是刚探测过的空闲组合。")
        self.emit_changed()

    def emit_changed(self, *_) -> None:
        # 冲突提示是本地反馈,立刻更新 —— 上层的防抖延迟 300ms 才标红会显得迟钝
        self.refresh_hotkey_problems()
        super().emit_changed()

    # ---- 输出 ----

    def _build_output(self, cfg: Config) -> None:
        card = Card("输出")
        self.out_restore = QCheckBox("粘贴后恢复原有剪贴板内容")
        self.out_restore.setChecked(cfg.output.restore_clipboard)
        self.out_restore.toggled.connect(self.emit_changed)
        card.add(self.out_restore)

        self.out_paste_delay = spin(10, 1000, cfg.output.paste_delay_ms, " ms", step=10)
        self.out_paste_delay.valueChanged.connect(self.emit_changed)
        card.add_layout(labeled("粘贴前等待", self.out_paste_delay))

        # 和「粘贴前等待」是同一类问题,而且后果更严重:
        # 目标应用慢一点,回车就会在文字落地之前触发,把空的或残缺的内容提交出去。
        # 对着 Claude Code 连续说话正是这个工具的主场景。
        self.out_send_delay = spin(10, 1000, cfg.output.send_delay_ms, " ms", step=10)
        self.out_send_delay.valueChanged.connect(self.emit_changed)
        card.add_layout(labeled("回车前等待", self.out_send_delay))

        card.add(hint(
            "「粘贴前等待」太短,某些应用会读到旧的剪贴板内容而粘错。\n"
            "「回车前等待」太短,回车会赶在文字落地之前触发,提交出去的是空的或残缺的 —— "
            "只影响「粘贴并发送」。遇到反应慢的应用就把这两个调大。"
        ))
        self.body.addWidget(card)

    # ---- 外观与启动 ----

    def _build_appearance(self, cfg: Config) -> None:
        card = Card("外观与启动")
        self.ui_theme = ComboBox()
        for label, value in [("跟随系统", "auto"), ("深色", "dark"), ("浅色", "light")]:
            self.ui_theme.addItem(label, value)
        self.ui_theme.setCurrentIndex(max(0, self.ui_theme.findData(cfg.ui.theme)))
        self.ui_theme.currentIndexChanged.connect(self.emit_changed)
        card.add_layout(labeled("主题", self.ui_theme))

        self.ui_overlay = QCheckBox("录音时显示悬浮提示条")
        self.ui_overlay.setChecked(cfg.ui.show_overlay)
        self.ui_overlay.toggled.connect(self.emit_changed)
        card.add(self.ui_overlay)

        self.ui_corner = ComboBox()
        for label, value in [
            ("右下角", "bottom_right"), ("左下角", "bottom_left"),
            ("右上角", "top_right"), ("顶部居中", "top_center"),
        ]:
            self.ui_corner.addItem(label, value)
        self.ui_corner.setCurrentIndex(max(0, self.ui_corner.findData(cfg.ui.overlay_corner)))
        self.ui_corner.currentIndexChanged.connect(self.emit_changed)
        card.add_layout(labeled("提示条位置", self.ui_corner))

        self.ui_preview = spin(0, 10_000, cfg.ui.preview_ms, " ms", step=100)
        self.ui_preview.valueChanged.connect(self.emit_changed)
        card.add_layout(labeled("结果停留", self.ui_preview))

        self.ui_badge = QCheckBox("桌面上显示悬浮麦克风")
        self.ui_badge.setChecked(cfg.ui.show_mic_badge)
        self.ui_badge.toggled.connect(self.emit_changed)
        card.add(self.ui_badge)

        self.badge_action = ComboBox()
        for label, value in [("只粘贴文字", "paste"),
                             ("粘贴后自动回车发送", "paste_and_send")]:
            self.badge_action.addItem(label, value)
        self.badge_action.setCurrentIndex(
            max(0, self.badge_action.findData(cfg.ui.badge_action)))
        self.badge_action.currentIndexChanged.connect(self.emit_changed)
        card.add_layout(labeled("点一下说完之后", self.badge_action))

        self.tray_click = ComboBox()
        for label, value in [("打开设置窗口", "open"),
                             ("开始/结束说话(同悬浮麦克风)", "talk")]:
            self.tray_click.addItem(label, value)
        self.tray_click.setCurrentIndex(
            max(0, self.tray_click.findData(cfg.ui.tray_click)))
        self.tray_click.currentIndexChanged.connect(self.emit_changed)
        card.add_layout(labeled("单击托盘图标", self.tray_click))

        row = QHBoxLayout()
        btn_home = QPushButton("把它挪回默认位置")
        btn_home.clicked.connect(self.badgeHomeRequested.emit)
        row.addWidget(btn_home)
        row.addStretch(1)
        card.add_layout(row)
        card.add(hint(
            "悬浮麦克风可以直接拖动,**右键点它就是这个菜单**。"
            "点一下开始说话,再点一下结束 —— "
            "**热键被别的软件占用时(比如微信),它是还能用的那条路**。\n"
            "「自动回车发送」适合对着 Claude Code 连续说话,"
            "但**发出去就撤不回来了,识别错也一样** —— 所以默认是只粘贴。\n"
            "换了显示器或分辨率之后如果找不着它了,点上面那个按钮挪回来。\n"
            "想把入口固定在任务栏上:「单击托盘图标」选「开始/结束说话」,再到 Windows "
            "设置 → 个性化 → 任务栏 → 其他系统托盘图标,把 VoiceInput 打开,"
            "它就一直显示在任务栏右下角。说完的字会送回你点托盘之前在用的那个窗口。"
        ))
        card.add(hint(
            "关掉提示条后,麦克风打不开、只录到静音这类失败也就看不见了,不建议关。\n"
            "「结果停留」设成 0 就是识别完不显示结果 —— 失败提示不受影响,那个必须看得见。"
        ))

        self.start_min = QCheckBox("启动时最小化到托盘")
        self.start_min.setChecked(cfg.start_minimized)
        self.start_min.toggled.connect(self.emit_changed)
        card.add(self.start_min)

        self.autostart = QCheckBox("开机自动启动")
        # **读真实状态,不读配置。** 用户可能直接把启动文件夹里的快捷方式删了,
        # 那时配置里还写着 true,复选框就会显示"已启用"而实际没有 ——
        # 又一次"显示的和实际的不一致"。配置只当缓存。
        try:
            self.autostart.setChecked(autostart_mod.is_enabled())
        except OSError:
            self.autostart.setChecked(cfg.autostart)
        self.autostart.toggled.connect(self.emit_changed)
        card.add(self.autostart)
        card.add(hint(
            "自启通过启动文件夹里的快捷方式实现,不写注册表。"
            "注意这个快捷方式在程序目录之外,删掉程序目录不会一并删掉它 —— "
            "具体路径见「关于」页。"
        ))
        self.body.addWidget(card)

    # ---- 写回 ----

    def collect(self, cfg: Config) -> None:
        cfg.hotkey.paste = self.hk_paste.spec()
        cfg.hotkey.paste_and_send = self.hk_send.spec()
        cfg.hotkey.mode = self.hk_mode.currentData()

        cfg.output.restore_clipboard = self.out_restore.isChecked()
        cfg.output.paste_delay_ms = self.out_paste_delay.value()
        cfg.output.send_delay_ms = self.out_send_delay.value()

        cfg.ui.theme = self.ui_theme.currentData()
        cfg.ui.show_overlay = self.ui_overlay.isChecked()
        cfg.ui.overlay_corner = self.ui_corner.currentData()
        cfg.ui.preview_ms = self.ui_preview.value()
        cfg.ui.show_mic_badge = self.ui_badge.isChecked()
        cfg.ui.badge_action = self.badge_action.currentData()
        cfg.ui.tray_click = self.tray_click.currentData()

        cfg.start_minimized = self.start_min.isChecked()
        cfg.autostart = self.autostart.isChecked()
