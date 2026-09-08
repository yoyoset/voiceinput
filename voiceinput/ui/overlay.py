"""录音/识别状态的悬浮指示条。

这个东西存在的理由不是好看,是**排除"后台失败但用户以为成功"**:
麦克风打不开、模型没加载、只录到静音、识别返回空——这些如果什么都不显示,
用户会以为自己没按到热键,反复按,越来越困惑。所以失败必须看得见。

**由此来的一条不对称:用户关掉提示条,关掉的只是顺利时的那些提示,
失败提示照常显示。** 这条规矩原来靠调用方记着(五处 `if show_overlay:`
守着成功类、失败类故意不守),迟早有一处漏掉或者多守。现在归这里:
`show_recording` / `show_busy` / `show_result` 认 `enabled`,
`show_error` / `show_warning` 不认。

窗口不抢焦点(WindowDoesNotAcceptFocus + ToolTip),否则按下热键的瞬间
当前输入框就失去焦点了,粘贴会粘到别处去。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

from .theme import Palette
from .widgets import FloatingHud

_MARGIN = 24
_WIDTH = 320
_HEIGHT = 62


class Overlay(FloatingHud, QWidget):
    def __init__(self, palette: Palette) -> None:
        self._init_floating(palette, Qt.WindowType.ToolTip, (_WIDTH, _HEIGHT))

        self._corner = "bottom_right"   # 真正的位置由 apply(cfg) 决定
        self._enabled = True
        self._preview_ms = 1200
        self._state = "idle"
        self._message = ""
        self._note = ""    # 右上角小字,录音时显示已录时长
        self._level = 0.0  # 0..1,画音量条用

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._pulse = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick)

    # ---- 对外 ----

    def set_corner(self, corner: str) -> None:
        self._corner = corner
        self._reposition()

    def apply(self, cfg) -> None:
        """提示条自己的显示设置:摆在哪、开不开、结果停留多久。"""
        self._enabled = cfg.ui.show_overlay
        self._preview_ms = cfg.ui.preview_ms
        self.set_corner(cfg.ui.overlay_corner)
        if not self._enabled:
            self.hide()

    def _show_live(self, state: str, message: str) -> None:
        """"正在进行中"的提示:一直亮着并跳动,等下一个状态把它换掉。

        **这一类认 `enabled`** —— 它们是顺利时的提示,用户关掉提示条
        关掉的就是它们。(失败提示不认,见 `show_error` / `show_warning`。)
        规则写在这一处,不是两处各记一遍。
        """
        if not self._enabled:
            return
        self._state = state
        self._message = message
        self._hide_timer.stop()
        self._pulse_timer.start(60)
        self._present()

    def show_recording(self, message: str = "正在聆听") -> None:
        self._show_live("recording", message)

    def show_busy(self, message: str = "识别中") -> None:
        self._show_live("busy", message)

    def show_result(self, text: str) -> None:
        """识别成功后闪一下结果。

        停留时间设成 0 = 不显示结果。**直接跳过,不能显示 0 毫秒** ——
        那会闪一下再消失,比不显示更烦人。
        """
        if not self._enabled or self._preview_ms <= 0:
            return
        self._state = "result"
        self._message = text
        self._pulse_timer.stop()
        self._present()
        self._hide_timer.start(self._preview_ms)

    def show_cancelled(self) -> None:
        """录音被主动取消(Esc)。

        **认 `enabled`**——这不是"后台失败但用户以为成功"那类必须硬塞给
        用户看的事:用户自己按了 Esc,已经知道发生了什么。这条只是确认
        "确实取消了、不会有东西被粘贴出去",提示条关着就不用多此一举。
        """
        if not self._enabled:
            return
        self._state = "cancelled"
        self._message = "已取消"
        self._note = ""
        self._pulse_timer.stop()
        self._present()
        self._hide_timer.start(1500)

    def show_error(self, message: str, duration_ms: int = 4000) -> None:
        """错误停留时间明显长于成功——用户需要时间读懂发生了什么。

        **不认 `enabled`。** 关掉提示条关掉的是顺利时的提示,不是失败提示。
        """
        self._show_transient("error", message, duration_ms)

    def show_warning(self, message: str, duration_ms: int = 4500) -> None:
        """半成功:结果给了,但有内容缺失。

        和 error 分开是因为它们要传达的行动不同——error 是"这次没成",
        warning 是"这次成了但不完整,你可能要补说一遍"。

        和 error 一样**不认 `enabled`**。
        """
        self._show_transient("warning", message, duration_ms)

    def _show_transient(self, state: str, message: str, duration_ms: int) -> None:
        """出了状况的提示:显示一段时间后自己退掉。

        **这一类不认 `enabled`。** 用户关掉提示条,关掉的只是顺利时的提示 ——
        失败和残缺照常要说,否则就成了"后台失败但用户以为成功"。
        规则写在这一处,不是两处各记一遍。

        顺带把右上角的小字清掉:那里放的是录音时长,这会儿它已经过期了。
        """
        self._state = state
        self._message = message
        self._note = ""
        self._pulse_timer.stop()
        self._present()
        self._hide_timer.start(duration_ms)

    def set_note(self, note: str) -> None:
        """右上角小字。录音时用来显示已录时长。"""
        if note != self._note:
            self._note = note
            self.update()

    def set_level(self, level_dbfs: float) -> None:
        """把 dBFS 映射到 0..1。-60 dBFS 当作静音,-10 dBFS 当作满格。"""
        if level_dbfs == float("-inf"):
            self._level = 0.0
        else:
            self._level = max(0.0, min(1.0, (level_dbfs + 60.0) / 50.0))
        if self._state == "recording":
            self.update()

    # ---- 内部 ----

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.08) % 1.0
        # 用 `repaint()` 不用 `update()`——见 mic_badge.py 里同样的注释:
        # 置顶 + 透明背景 + 不抢焦点的窗口,实测 Windows 偶尔会把 `update()`
        # 排的队直接吞掉,画面卡在原地。这里同样每次跳动画都要求立即同步画。
        self.repaint()

    def _present(self) -> None:
        self._reposition()
        self.show()
        self.raise_()
        self.update()

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        if self._corner == "bottom_left":
            pos = QPoint(area.left() + _MARGIN, area.bottom() - _HEIGHT - _MARGIN)
        elif self._corner == "top_right":
            pos = QPoint(area.right() - _WIDTH - _MARGIN, area.top() + _MARGIN)
        elif self._corner == "top_center":
            pos = QPoint(area.center().x() - _WIDTH // 2, area.top() + _MARGIN)
        else:
            pos = QPoint(area.right() - _WIDTH - _MARGIN, area.bottom() - _HEIGHT - _MARGIN)
        self.move(pos)

    def _accent_for_state(self) -> str:
        p = self._palette
        return {
            "recording": p.accent,
            "busy": p.warning,
            "result": p.accent,
            "warning": p.warning,
            "error": p.danger,
            "cancelled": p.text_dim,   # 既不是成功也不是失败,用中性色
        }.get(self._state, p.accent)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背板
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, _WIDTH, _HEIGHT), 12, 12)
        bg = QColor(p.surface)
        bg.setAlpha(242)
        painter.fillPath(path, bg)
        painter.setPen(QColor(p.border))
        painter.drawPath(path)

        accent = QColor(self._accent_for_state())

        # 左侧状态圆点。录音和识别时呼吸,静态时不动。
        cx, cy, r = 26.0, _HEIGHT / 2, 7.0
        if self._state in ("recording", "busy"):
            import math

            scale = 1.0 + 0.35 * math.sin(self._pulse * 2 * math.pi)
            halo = QColor(accent)
            halo.setAlpha(70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QRectF(cx - r * scale * 1.9, cy - r * scale * 1.9,
                                       r * scale * 3.8, r * scale * 3.8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 右上角小字(已录时长)。先画它,好把宽度从正文里让出来。
        note_w = 0.0
        if self._note:
            note_font = painter.font()
            note_font.setPointSize(8)
            painter.setFont(note_font)
            note_w = painter.fontMetrics().horizontalAdvance(self._note) + 10
            painter.setPen(QColor(p.text_dim))
            painter.drawText(
                QRectF(_WIDTH - note_w - 12, 8, note_w, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._note,
            )

        # 文本
        text_x = 48
        text_w = _WIDTH - text_x - 16 - note_w
        painter.setPen(QColor(p.text))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(self._state in ("recording", "busy", "error", "warning"))
        painter.setFont(font)

        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self._message, Qt.TextElideMode.ElideRight, text_w)
        if self._state == "recording":
            painter.drawText(QRectF(text_x, 12, text_w, 20),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             elided)
            # 音量条画满整行——小字只占用标题那一行的宽度,不该让条也缩短
            bar = QRectF(text_x, 38, _WIDTH - text_x - 16, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.surface_alt))
            painter.drawRoundedRect(bar, 3, 3)
            if self._level > 0:
                filled = QRectF(bar.x(), bar.y(), bar.width() * self._level, bar.height())
                painter.setBrush(accent)
                painter.drawRoundedRect(filled, 3, 3)
        else:
            # 警告和错误经常一句话说不完,单行会被省略号吃掉关键信息
            # (「超过 120 秒上限,后面的话没录进去 —— ...」),所以最多排两行。
            rect = QRectF(text_x, 6, text_w, _HEIGHT - 12)
            flags = (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                     | Qt.TextFlag.TextWordWrap)
            needed = painter.boundingRect(rect, flags, self._message)
            if needed.height() > rect.height():
                # 两行还放不下就缩一号字再试,仍放不下才省略
                font.setPointSize(9)
                painter.setFont(font)
                needed = painter.boundingRect(rect, flags, self._message)
            if needed.height() > rect.height():
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    painter.fontMetrics().elidedText(
                        self._message, Qt.TextElideMode.ElideRight,
                        int(text_w * 2),
                    ),
                )
            else:
                painter.drawText(rect, flags, self._message)
        painter.end()
