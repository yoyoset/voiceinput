"""探测一个热键组合在**这台机器上**是不是已经被别的程序占用了。

为什么需要运行时探测,而不是列一张"常见冲突"的表:

表只能写下写表的人知道的软件。用户装了什么、改过什么快捷键,
开发机上是看不见的 —— 把开发机的情况写进产品文案,对别人就是错的。

Windows 的 `RegisterHotKey` 是全局独占的:某个程序注册了 Ctrl+Alt+W,
别人再注册就会失败并返回 `ERROR_HOTKEY_ALREADY_REGISTERED`。
借这一点可以直接问系统"这个组合有人占了吗",不用猜是谁占的。

**这个探测有明确的盲区,不要当成万能的:**

- 只看得见用 `RegisterHotKey` 注册的热键。用底层键盘钩子的程序
  (我们自己就是)不占用任何东西,探测不到 —— 撞上了是两边同时触发。
- 纯修饰键组合(Ctrl+Win 这种)根本没法用 `RegisterHotKey` 表达,
  探测不了。这类组合的问题是另一回事,见 `hotkey.validate()`。
- 非 Windows 平台直接返回"不知道"。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

# RegisterHotKey 的修饰键位
_MOD = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "cmd": 0x0008}
_ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# 非字母数字键的虚拟键码。只列热键里真的用得上的。
_VK = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "page_up": 0x21, "page_down": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}

_MODIFIER_TOKENS = frozenset({
    "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr",
    "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r",
})


def _tokens(spec: str) -> list[str]:
    return [t.strip().strip("<>").lower() for t in spec.split("+") if t.strip()]


def to_win32(spec: str) -> tuple[int, int] | None:
    """把 '<ctrl>+<alt>+d' 换成 RegisterHotKey 要的 (modifiers, vk)。

    表达不了就返回 None —— 纯修饰键组合、多个主键、不认识的键名。
    """
    mods = 0
    main: str | None = None
    for token in _tokens(spec):
        base = token.rstrip("_lr") if token.rstrip("_lr") in _MOD else token
        base = {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt",
                "alt_gr": "alt", "shift_l": "shift", "shift_r": "shift",
                "cmd_l": "cmd", "cmd_r": "cmd"}.get(token, token)
        if base in _MOD:
            mods |= _MOD[base]
            continue
        if main is not None:
            return None            # 两个主键,RegisterHotKey 表达不了
        main = token
    if main is None or mods == 0:
        return None
    if len(main) == 1 and (main.isalpha() or main.isdigit()):
        return mods, ord(main.upper())
    vk = _VK.get(main)
    return (mods, vk) if vk is not None else None


def taken_by_another_app(spec: str) -> bool | None:
    """这个组合已经被别的程序占用了吗?

    True = 确实被占了;False = 没有人用 RegisterHotKey 占它;
    None = 探测不了(见模块开头的盲区说明),**不要当成 False 用**。
    """
    if not sys.platform.startswith("win"):
        return None
    parsed = to_win32(spec)
    if parsed is None:
        return None
    mods, vk = parsed

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                      wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL

    # id 用一个不太可能和别人撞的值。hWnd=None 表示挂在当前线程上。
    hotkey_id = 0x5649        # 'VI'
    ok = user32.RegisterHotKey(None, hotkey_id, mods, vk)
    if ok:
        # **注册成功必须马上注销。** 不注销的话我们自己就把这个组合占住了,
        # 用户真正去按的时候,别的程序反而收不到。
        user32.UnregisterHotKey(None, hotkey_id)
        return False
    return ctypes.get_last_error() == _ERROR_HOTKEY_ALREADY_REGISTERED


# 挑替代组合时的候选顺序。
#
# **这只是候选,不是结论** —— 哪个能用由 `suggest()` 当场探测决定。
# 排前面的是好按、且不太可能和编辑类快捷键重合的;
# 功能键排最后,因为有些键盘要按 Fn 才够得着。
SUGGESTIONS = (
    "<ctrl>+<alt>+<space>", "<ctrl>+<shift>+<space>",
    "<ctrl>+<alt>+<enter>", "<ctrl>+<shift>+<enter>",
    "<ctrl>+<alt>+j", "<ctrl>+<alt>+k", "<ctrl>+<alt>+m",
    "<ctrl>+<alt>+q", "<ctrl>+<alt>+g", "<ctrl>+<shift>+j",
    # 功能键必须写成 <f9> —— 写 f9 的话 pynput 解析不了,
    # 而 RegisterHotKey 那边两种写法都认。真被选中就是注册失败。
    "<ctrl>+<alt>+<f9>", "<ctrl>+<alt>+<f10>",
)


def suggest(exclude: set[str] | None = None) -> str | None:
    """挑一个这台机器上没人占用的组合。全都被占就返回 None。

    每次调用都真的去问系统 —— 用户装了什么、改过什么快捷键,
    只有当场探测才知道。
    """
    exclude = exclude or set()
    for spec in SUGGESTIONS:
        if spec in exclude:
            continue
        if taken_by_another_app(spec) is False:
            return spec
    return None


@dataclass(frozen=True)
class Verdict:
    """一个组合的探测结论。

    **措辞放在这里,不放在界面上。** 向导和设置页都要显示这个结论,
    各写一份的话会漂移成两种说法(设备提示那一栏就这么漂过一次),
    改了一处另一处继续过时。
    """

    action: str
    spec: str
    taken: bool | None

    @property
    def ok(self) -> bool:
        """探测不了也算不 ok —— "不知道"不能当成"没问题"。"""
        return self.taken is False

    @property
    def mark(self) -> str:
        return {True: "✗", False: "✓"}.get(self.taken, "?")

    def describe(self) -> str:
        """结论本身,**不带 ✓/✗ 记号** —— 记号由调用方拼。

        自检那边前面已经有 `[通过]`/`[注意]` 了,再带一个就是重复。
        """
        from .hotkey import describe as describe_spec

        what = f"「{self.action}」{describe_spec(self.spec)}"
        if self.taken is True:
            return f"{what} 已被别的程序占用"
        if self.taken is False:
            return f"{what} 没有别的程序占用"
        return f"{what} 查不了 —— 纯修饰键组合,系统接口表达不了它"

    def marked(self) -> str:
        """带记号的一行,界面上用。"""
        return f"{self.mark} {self.describe()}"


def report(bindings: dict[str, str]) -> list[Verdict]:
    """挨个探测,返回结论。空的绑定跳过。"""
    return [Verdict(action, spec, taken_by_another_app(spec))
            for action, spec in bindings.items() if spec]
