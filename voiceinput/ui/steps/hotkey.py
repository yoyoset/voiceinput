"""向导第四步:挑一组不会撞车的热键。

**这一步的职责是"避开冲突",光让用户填不算做到了。**
哪个组合空闲取决于这台机器装了什么 —— 开发机上空闲的组合在别人那儿
可能正被占着(实测:默认的 Ctrl+Alt+Space 在开发机上就是被占的)。
所以进到这一步就当场问系统,被占了直接换掉。
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from ... import conflict
from ...config import Config
from ...hotkey import describe, labelled
from ..hotkey_edit import HotkeyEdit
from ..widgets import Card, ComboBox, hint, restyle
from .base import Step


class HotkeyStep(Step):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__("设置热键", parent)

        card = Card()
        self.paste = HotkeyEdit(cfg.hotkey.paste)
        self.send = HotkeyEdit(cfg.hotkey.paste_and_send)
        card.add(QLabel("说完把文字粘贴到光标处"))
        card.add(self.paste)
        card.add(QLabel("说完粘贴并按回车发送"))
        card.add(self.send)

        self.mode = ComboBox()
        self.mode.addItem("按住说话,松开结束", "push_to_talk")
        self.mode.addItem("按一下开始,再按一下结束", "toggle")
        self.mode.setCurrentIndex(0 if cfg.hotkey.mode == "push_to_talk" else 1)
        card.add(QLabel("触发方式"))
        card.add(self.mode)

        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        card.add(self.verdict)

        btns = QHBoxLayout()
        btn_check = QPushButton("检查冲突")
        btn_check.clicked.connect(self.check)
        btn_fix = QPushButton("自动换一个没人占用的")
        btn_fix.clicked.connect(self.pick_free)
        btns.addWidget(btn_check)
        btns.addWidget(btn_fix)
        btns.addStretch(1)
        card.add_layout(btns)
        self.body.addWidget(card)

        self.body.addWidget(hint(
            "点进输入框直接按下想用的组合键即可。至少要含一个修饰键 —— "
            "纯字母做全局热键会把正常打字全劫持掉。\n"
            "也别用纯修饰键的组合(Ctrl+Win 这种):任何 Ctrl+Win+X 都会触发它。\n\n"
            "「粘贴并发送」适合对着 Claude Code 连续说话:说完直接提交,不用再去按回车。"
        ))
        self.body.addStretch(1)
        self._autofix()

    # ---- 探测 ----

    def _autofix(self) -> None:
        """默认组合被占了就直接换掉,并且**说出来**。

        让用户先撞一次再去点按钮没有意义;但默默改掉他看到过的值同样不行。
        """
        bad = [
            edit.spec() for edit in (self.paste, self.send)
            if conflict.taken_by_another_app(edit.spec()) is not False
        ]
        if not bad:
            self.check()
            return
        before = describe(self.paste.spec())
        self.pick_free()
        if self.paste.spec() != bad[0]:
            self.verdict.setText(
                f"默认的 {before} 在这台机器上已经被别的程序占用,已经替你换掉了。\n"
                + self.verdict.text())

    def check(self) -> None:
        """问 Windows:这两个组合有没有被别的程序占了。

        结论的措辞在 `conflict.Verdict` 里 —— 设置页显示的是同一份,
        免得两处漂移成两种说法。
        """
        verdicts = conflict.report(labelled({
            "paste": self.paste.spec(), "paste_and_send": self.send.spec()}))
        self.verdict.setText("\n".join(v.marked() for v in verdicts))
        self.verdict.setProperty(
            "role", "hint" if all(v.ok for v in verdicts) else "danger")
        restyle(self.verdict)

    def pick_free(self) -> None:
        first = conflict.suggest()
        second = conflict.suggest(exclude={first} if first else set())
        if first is None or second is None:
            self.verdict.setText("候选组合全都被占用了,请手动挑一个。")
            return
        self.paste.set_spec(first)
        self.send.set_spec(second)
        self.check()

    # ---- 写回 ----

    def apply_to(self, cfg: Config) -> None:
        cfg.hotkey.paste = self.paste.spec()
        cfg.hotkey.paste_and_send = self.send.spec()
        cfg.hotkey.mode = self.mode.currentData()

    def summary_rows(self) -> list[tuple[str, str]]:
        return [
            ("粘贴热键", describe(self.paste.spec())),
            ("粘贴并发送", describe(self.send.spec())),
            ("触发方式", self.mode.currentText()),
        ]
