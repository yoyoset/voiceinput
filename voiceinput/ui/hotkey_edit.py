"""点进去直接按组合键就能录制的输入框。

拆出来的判据是**只有这一个控件需要的东西**:修饰键名字的映射表、
pynput 键名对照——`widgets.py` 里的数字框、下拉框、卡片都不认识这些,
硬凑在一个文件里只是因为"都是控件"这个表面相似,而不是真的共享状态。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from ..hotkey import describe

# Qt 修饰键 -> pynput 的写法
_MODIFIERS = [
    (Qt.KeyboardModifier.ControlModifier, "<ctrl>"),
    (Qt.KeyboardModifier.AltModifier, "<alt>"),
    (Qt.KeyboardModifier.ShiftModifier, "<shift>"),
    (Qt.KeyboardModifier.MetaModifier, "<cmd>"),
]

# 单独按下修饰键时,keyPressEvent 收到的是这些键码,不能当成"主键"
_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
    Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
}

_NAMED_KEYS = {
    Qt.Key.Key_Space: "<space>",
    Qt.Key.Key_Tab: "<tab>",
    Qt.Key.Key_Return: "<enter>",
    Qt.Key.Key_Enter: "<enter>",
    Qt.Key.Key_CapsLock: "<caps_lock>",
}


class HotkeyEdit(QLineEdit):
    """点进去直接按组合键就能录制。

    只接受**至少一个修饰键**的组合:纯字母做全局热键会把正常打字全劫持掉。
    """

    changed = Signal(str)

    def __init__(self, spec: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按下组合键")
        self._spec = ""
        self.set_spec(spec)

    def spec(self) -> str:
        return self._spec

    def set_spec(self, spec: str) -> None:
        self._spec = spec
        self.setText(describe(spec) if spec else "")

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.setText("按下组合键…")

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.set_spec(self._spec)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = Qt.Key(event.key())

        if key == Qt.Key.Key_Escape:
            self.clearFocus()
            return

        mods = [name for flag, name in _MODIFIERS if event.modifiers() & flag]
        if not mods:
            return  # 还没按修饰键,继续等

        if key in _MODIFIER_KEYS:
            # 纯修饰键组合也是合法热键(比如 Ctrl+Win),但要至少两个
            if len(mods) >= 2:
                self._commit(mods)
            else:
                self.setText(" + ".join(describe(m) for m in mods) + " + …")
            return

        main = _NAMED_KEYS.get(key)
        if main is None:
            text = event.text().strip()
            if not text or not text.isprintable():
                return
            main = text.lower()
        self._commit(mods + [main])

    def _commit(self, parts: list[str]) -> None:
        spec = "+".join(parts)
        self.set_spec(spec)
        self.changed.emit(spec)
        self.clearFocus()
