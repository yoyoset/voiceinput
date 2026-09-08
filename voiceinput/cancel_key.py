"""录音时按 Esc,取消这次录音——不识别、不粘贴。

**为什么不走 `HotkeyManager`**:那套是为"可配置的按住/切换动作"设计的
组合键状态机(子集歧义、峰值追踪)。这里要的是完全不同的东西:固定按键、
随时监听、只在正在录音时才有动作——业务判断留给上层,这里只管把
"按下了 Esc"这件事翻成一个 Qt 信号。

**为什么不做成可配置热键**:Esc 在几乎所有软件里都是"取消"的通用语义,
配置反而增加认知负担。而且它只在正在录音时才有效果——不录音时按 Esc,
对本程序完全没有作用,和别的软件冲突的机会因此很小(见 `hotkey.py`
关于 pynput 不吞按键的说明:即使冲突,代价也只是"顺带关了个对话框",
不是"说话说一半突然被打断成别的动作")。

回调和 `HotkeyManager` 一样跑在 pynput 自己的监听线程上,不能做耗时的事,
只发信号。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from pynput import keyboard


class CancelKey(QObject):
    """全局监听 Esc。是否要理会由上层判断(只在录音中才有意义)。"""

    pressed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        if key == keyboard.Key.esc:
            self.pressed.emit()
