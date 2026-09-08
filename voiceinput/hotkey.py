"""全局热键。

pynput 自带的 `GlobalHotKeys` 只在组合键**激活**时回调一次,没有"松开"事件,
做不了 push-to-talk(按住说话、松开结束)。所以这里直接用原始 Listener
自己维护按键状态。

三个要点:

1. **子集歧义**。`<ctrl>+<cmd>` 是 `<ctrl>+<shift>+<cmd>` 的子集,按下后者时
   前者的条件也同时成立。`_best_match()` 取键数最多的那个,即"最具体的优先"。

2. **但只有 `_best_match()` 是不够的 —— 组合键按不可能同时按下。**
   按 Ctrl+Shift+Win 时,按到 Ctrl+Win 那一刻 Ctrl+Win 就已经命中并触发了,
   再按 Shift 已经晚了。所以还要在整个按下期间追踪**峰值**(`_peak`,
   命中过的最具体组合),**松开时按峰值决定动作**。
   详见 `_on_press` 里的说明和 docs/pitfalls.md。

   (这一条曾经只写着第 1 点,于是"粘贴并发送"这个热键长期几乎不生效 ——
   读的人会以为 `_best_match` 已经把问题解决了。)

3. **回调在 pynput 的监听线程上跑**,绝不能在里面做耗时的事(录音、推理、
   弹窗),否则整个键盘事件队列会被堵住,表现为系统级卡键。上层负责转交。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from pynput import keyboard


class HotkeyError(RuntimeError):
    pass


def parse(spec: str) -> frozenset:
    """把 '<ctrl>+<shift>+<cmd>' 解析成规范化的键集合。"""
    try:
        return frozenset(keyboard.HotKey.parse(spec))
    except ValueError as e:
        raise HotkeyError(f"热键格式不对: {spec!r} ({e})") from e


def describe(spec: str) -> str:
    """给界面显示用的人话形式:<ctrl>+<cmd> -> Ctrl + Win。"""
    names = {
        "ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl",
        "shift": "Shift", "shift_l": "Shift", "shift_r": "Shift",
        "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt", "alt_gr": "AltGr",
        "cmd": "Win", "cmd_l": "Win", "cmd_r": "Win",
        "space": "Space", "enter": "Enter", "tab": "Tab", "esc": "Esc",
        "caps_lock": "CapsLock",
    }
    order = {"Ctrl": 0, "Alt": 1, "Shift": 2, "Win": 3}
    parts = []
    for token in spec.split("+"):
        token = token.strip().strip("<>")
        parts.append(names.get(token, token.upper() if len(token) == 1 else token.title()))
    parts.sort(key=lambda p: (order.get(p, 99), p))
    return " + ".join(parts)


# 两个动作给用户看的名字。**只有这一份。**
#
# 之前是四种叫法:设置页「粘贴文字」、向导「粘贴」、自检「粘贴」、
# 日志里干脆是内部键名 `paste`。同一个热键被占用,用户在三个地方
# 看到三个名字,对不上号 —— 而这恰恰是最需要他看懂的一条提示。
ACTION_LABELS = {"paste": "粘贴文字", "paste_and_send": "粘贴并发送"}


def labelled(bindings: dict[str, str]) -> dict[str, str]:
    """把内部键的绑定表换成给用户看的名字。认不出的键原样保留。"""
    return {ACTION_LABELS.get(key, key): spec for key, spec in bindings.items()}


_MODIFIER_TOKENS = {
    "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr",
    "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r",
}

# 常见到几乎一定会撞的组合。
#
# 注意 pynput 用的是底层键盘钩子,**不会吞掉按键**——撞了不是"我们收不到",
# 而是"两边同时触发":你想说话,结果顺手把文件另存为了。
# 所以这里只能提醒,没法靠技术手段规避。
_RISKY = {
    frozenset({"ctrl", "c"}), frozenset({"ctrl", "v"}), frozenset({"ctrl", "x"}),
    frozenset({"ctrl", "z"}), frozenset({"ctrl", "y"}), frozenset({"ctrl", "a"}),
    frozenset({"ctrl", "s"}), frozenset({"ctrl", "f"}), frozenset({"ctrl", "w"}),
    frozenset({"ctrl", "t"}), frozenset({"ctrl", "n"}), frozenset({"ctrl", "p"}),
    frozenset({"alt", "tab"}), frozenset({"alt", "f4"}),
    frozenset({"cmd", "d"}), frozenset({"cmd", "e"}), frozenset({"cmd", "l"}),
    frozenset({"cmd", "r"}), frozenset({"cmd", "tab"}),
}


def _tokens(spec: str) -> set[str]:
    return {t.strip().strip("<>").lower() for t in spec.split("+") if t.strip()}


@dataclass(frozen=True)
class Problem:
    """一条热键配置问题。

    `actions` 是**一起**构成这个问题的动作。用列表而不是给每个动作各报一条,
    是因为"两个绑了同一个组合"本质上是**一个**问题:各报一条的话界面上会出现
    「甲和乙是同一个组合」「乙和甲是同一个组合」两行说同一件事。
    """

    actions: tuple[str, ...]
    message: str

    def describe(self) -> str:
        names = "、".join(f"「{a}」" for a in self.actions)
        return f"{names}{self.message}"


def validate(bindings: dict[str, str]) -> list[Problem]:
    """检查热键配置。没问题时返回空列表。

    检查项:

    - **解析不了**:写法不合法。
    - **没有修饰键**:纯字母做全局热键会把正常打字整个劫持掉。
    - **两个动作绑了同一个组合**:此时 `_best_match` 只能按字典序任选一个,
      另一个永远不会触发 —— 而且是静默的。
    - **撞常用快捷键**:只能提醒。pynput 是底层钩子、不吞按键,
      撞了是两边同时触发,不是我们收不到。

    注意**子集关系不算问题**:`<ctrl>+<cmd>` 是 `<ctrl>+<shift>+<cmd>` 的子集,
    这正是默认配置,`_best_match` 取最具体的那个,是设计好的行为。
    """
    problems: list[Problem] = []
    parsed: dict[str, frozenset] = {}

    for action, spec in bindings.items():
        if not spec:
            continue
        try:
            parsed[action] = parse(spec)
        except HotkeyError as e:
            problems.append(Problem((action,), f"写法不合法:{e}"))
            continue

        tokens = _tokens(spec)
        if not (tokens & _MODIFIER_TOKENS):
            problems.append(Problem(
                (action,), "至少要含一个修饰键,否则会把正常打字劫持掉"))
            continue
        if tokens <= _MODIFIER_TOKENS:
            # **纯修饰键组合会被它的每一个超集触发。**
            #
            # Ctrl+Win 命中的条件是"Ctrl 和 Win 都按着",所以按
            # Ctrl+Win+左(Windows 切虚拟桌面)、Ctrl+Win+任何键
            # (别的软件的热键),我们这边照样会开始录音。
            #
            # 这是从组合本身推出来的性质,不取决于装了什么软件 ——
            # 用户报的"和微信撞了"就是这个,不是微信的问题。
            problems.append(Problem(
                (action,),
                "只有修饰键,任何以它开头的组合(Ctrl+Win+左 这类)都会触发它;"
                "加一个普通键会稳得多"))
        elif frozenset(tokens) in _RISKY:
            problems.append(Problem(
                (action,), "和常用快捷键重合,按下时两边会同时触发"))

    # 同一个组合绑给了多个动作 —— 报成一条,涉及的动作都列出来
    by_combo: dict[frozenset, list[str]] = {}
    for action, combo in parsed.items():
        by_combo.setdefault(combo, []).append(action)
    for actions in by_combo.values():
        if len(actions) > 1:
            problems.append(Problem(
                tuple(actions), "绑了同一个组合,只有其中一个会触发"))

    return problems


class HotkeyManager:
    """监听多组热键,把按下/松开翻译成 on_start(action) / on_stop(action)。

    mode:
      - push_to_talk:按住触发 on_start,松开触发 on_stop
      - toggle:按一下 on_start,再按一下 on_stop
    """

    def __init__(
        self,
        bindings: dict[str, str],
        mode: str = "push_to_talk",
        on_start: Callable[[str], None] | None = None,
        on_stop: Callable[[str], None] | None = None,
        on_upgrade: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._combos: dict[str, frozenset] = {}
        for action, spec in bindings.items():
            if spec:
                self._combos[action] = parse(spec)
        self._mode = mode
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_upgrade = on_upgrade
        self._on_error = on_error

        self._pressed: set = set()
        self._active: str | None = None
        # 本次按下期间命中过的**最具体**组合。松开时按它决定动作。
        self._peak: str | None = None
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()
        with self._lock:
            self._pressed.clear()
            self._active = self._peak = None

    @property
    def is_running(self) -> bool:
        return self._listener is not None

    # ---- 内部 ----

    def _canonical(self, key):
        listener = self._listener
        if listener is None:
            return key
        try:
            return listener.canonical(key)
        except Exception:
            return key

    def _best_match(self) -> str | None:
        """当前按下的键满足哪个组合。多个满足时取键数最多的(最具体优先)。

        键数相同(两个动作绑了同一个组合)时按 action 名排序取第一个 ——
        这种配置本身就是错的,`validate()` 会提示用户,但运行期至少要**确定**,
        不能这次触发这个、下次触发那个。
        """
        best: str | None = None
        best_size = 0
        for action in sorted(self._combos):
            combo = self._combos[action]
            if combo <= self._pressed and len(combo) > best_size:
                best, best_size = action, len(combo)
        return best

    def _on_press(self, key) -> None:
        key = self._canonical(key)
        start: str | None = None
        upgraded: str | None = None

        with self._lock:
            if key in self._pressed:
                return  # 按住不放会持续产生 press 事件,忽略重复
            self._pressed.add(key)

            match = self._best_match()
            if match is None:
                return
            if self._mode == "toggle":
                # toggle 在 release 里处理,避免一次按-松就开始又结束
                return

            if self._active is None:
                self._active = self._peak = match
                start = match
            elif self._peak is not None and \
                    len(self._combos[match]) > len(self._combos[self._peak]):
                # **组合键按不可能同时按下。**
                #
                # 按 Ctrl+Shift+Win 时,按到 Ctrl+Win 那一刻 Ctrl+Win 就已经命中
                # 并触发了,再按 Shift 时 _active 已被占用 —— 结果"粘贴并发送"
                # 基本永远不会生效,行为完全取决于按键顺序。
                #
                # 不用延迟去消歧(那会牺牲 push-to-talk 的即时感):
                # 两个动作**录的音频是一样的**,区别只在结束时要不要补回车。
                # 所以照常立刻开始录,同时记住"按到过的最具体组合",
                # 松开时按它决定动作 —— 零延迟代价。
                self._peak = upgraded = match

        if start:
            self._safe(self._on_start, start)
        if upgraded:
            self._safe(self._on_upgrade, upgraded)

    def _on_release(self, key) -> None:
        key = self._canonical(key)
        start: str | None = None
        stop: str | None = None

        with self._lock:
            # 先按"还没松开"的状态判断命中哪个组合,再把键移出去
            matched = self._best_match()
            self._pressed.discard(key)

            if self._mode == "toggle":
                # toggle 统一在松开时判定:按下就切换的话,一次完整的按-松
                # 会立刻开始又结束
                if matched is not None:
                    if self._active is None:
                        self._active = self._peak = matched
                        start = matched
                    elif self._active == matched:
                        self._active = self._peak = None
                        stop = matched
            elif self._active is not None and key in self._combos[self._active]:
                # push-to-talk:组合里任意一个键松开就算说完了。
                # 用 _peak 而不是 _active —— 见 _on_press 里关于按键顺序的说明。
                stop = self._peak or self._active
                self._active = self._peak = None

        if start:
            self._safe(self._on_start, start)
        if stop:
            self._safe(self._on_stop, stop)

    def _safe(self, cb: Callable[[str], None] | None, action: str) -> None:
        """回调里出异常不能弄死监听线程,否则热键会静默失效。"""
        if cb is None:
            return
        try:
            cb(action)
        except Exception as e:  # pragma: no cover - 防御性
            if self._on_error:
                try:
                    self._on_error(f"热键回调出错: {e}")
                except Exception:
                    pass
