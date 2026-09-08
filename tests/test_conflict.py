"""热键占用探测。

用户报"热键和微信冲突了"。当时的做法是我凭印象推荐一个"应该没人用"的组合 ——
而实测发现我推荐的 `Ctrl+Alt+空格` 在那台机器上**已经被占用了**。

这就是问题所在:哪个组合空闲取决于用户装了什么,开发机上看不见。
所以必须当场问系统,不能靠一张写死的表。
"""

import ctypes
import sys

import pytest

from voiceinput.conflict import (
    SUGGESTIONS,
    suggest,
    taken_by_another_app,
    to_win32,
)

windows_only = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="RegisterHotKey 是 Windows 的")


class TestToWin32:
    def test_letter_combo(self):
        mods, vk = to_win32("<ctrl>+<alt>+d")
        assert mods == 0x0002 | 0x0001
        assert vk == ord("D")

    def test_named_key(self):
        assert to_win32("<ctrl>+<alt>+<space>") == (0x0003, 0x20)

    def test_function_key(self):
        assert to_win32("<ctrl>+<shift>+f9") == (0x0006, 0x78)

    def test_digit(self):
        assert to_win32("<ctrl>+<alt>+1")[1] == ord("1")

    def test_left_right_modifiers_normalise(self):
        """pynput 会给出 ctrl_l / cmd_r 这种带左右的写法。"""
        assert to_win32("<ctrl_l>+<alt_r>+d") == to_win32("<ctrl>+<alt>+d")

    def test_modifier_only_is_inexpressible(self):
        """纯修饰键组合 RegisterHotKey 根本表达不了 —— 必须返回 None,
        不能假装成一个能探测的组合。"""
        assert to_win32("<ctrl>+<cmd>") is None

    def test_no_modifier_is_inexpressible(self):
        assert to_win32("d") is None

    def test_two_main_keys_inexpressible(self):
        assert to_win32("<ctrl>+a+b") is None

    def test_unknown_key_inexpressible(self):
        assert to_win32("<ctrl>+<alt>+<nonsense>") is None


@windows_only
class TestProbe:
    def test_free_combo_reads_as_free(self):
        # F13-F24 在普通键盘上按不出来,几乎不会有人拿它注册热键
        assert taken_by_another_app("<ctrl>+<alt>+<shift>+f24") is False

    def test_detects_a_really_taken_combo(self):
        """真的占住一个组合,再探测 —— 这条是整个模块的核心断言。"""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        spec = "<ctrl>+<alt>+<shift>+f23"
        mods, vk = to_win32(spec)
        assert taken_by_another_app(spec) is False, "测试开始前它就被占了,换一个键"

        assert user32.RegisterHotKey(None, 0x7654, mods, vk), "没占住,测试无意义"
        try:
            assert taken_by_another_app(spec) is True
        finally:
            user32.UnregisterHotKey(None, 0x7654)
        assert taken_by_another_app(spec) is False, "探测之后必须把组合还回去"

    def test_probe_does_not_keep_the_hotkey(self):
        """**探测不能把组合占住。**

        探测时注册成功后如果忘了注销,我们自己就成了占用者 ——
        用户真去按的时候,本该响应的那个程序反而收不到。
        """
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        spec = "<ctrl>+<alt>+<shift>+f22"
        assert taken_by_another_app(spec) is False
        mods, vk = to_win32(spec)
        # 探测完之后别人应该还能注册它
        assert user32.RegisterHotKey(None, 0x7655, mods, vk)
        user32.UnregisterHotKey(None, 0x7655)

    def test_inexpressible_returns_none_not_false(self):
        """探测不了要说"不知道",不能说"没被占用" ——
        后者会让用户以为已经确认安全了。"""
        assert taken_by_another_app("<ctrl>+<cmd>") is None


@windows_only
class TestSuggest:
    def test_returns_a_free_combo(self):
        spec = suggest()
        assert spec in SUGGESTIONS
        assert taken_by_another_app(spec) is False

    def test_respects_exclude(self):
        first = suggest()
        second = suggest(exclude={first})
        assert second != first

    def test_all_candidates_are_expressible(self):
        """候选表里每一个都必须是能探测的组合,否则 suggest 会永远跳过它。"""
        for spec in SUGGESTIONS:
            assert to_win32(spec) is not None, spec

    def test_every_candidate_passes_validation(self):
        """候选必须**同时**满足两边:RegisterHotKey 能表达,pynput 也能解析。

        这条一开始就抓到了真 bug:候选里写着 `<ctrl>+<alt>+f9`,
        RegisterHotKey 认,pynput 不认(功能键要写 `<f9>`)——
        真被 suggest() 选中的话,热键会注册失败,而且是在用户点完
        「自动换一个没人占用的」之后才失败。
        """
        from voiceinput.hotkey import validate

        for spec in SUGGESTIONS:
            assert validate({"甲": spec}) == [], spec


class TestVerdictWording:
    """占用结论的措辞只有一份。

    这段文案曾经在四个地方各写了一遍:设置页、向导那一步、自检、启动日志。
    措辞已经开始漂移(「查不了(纯修饰键组合)」vs
    「查不了 —— 纯修饰键组合系统接口表达不了」)—— 改一处另外三处继续过时。
    这正是 device_picker 顶部警告过的那种漂移。
    """

    def make(self, taken):
        from voiceinput.conflict import Verdict

        return Verdict("粘贴", "<ctrl>+<alt>+d", taken)

    def test_taken_is_marked_bad(self):
        v = self.make(True)
        assert v.mark == "✗" and not v.ok
        assert "已被别的程序占用" in v.describe()

    def test_describe_carries_no_mark(self):
        """记号由调用方拼 —— 自检那边前面已经有 [通过]/[注意] 了,
        再带一个 ✓/✗ 就是重复。"""
        for taken in (True, False, None):
            assert not self.make(taken).describe().startswith(("✓", "✗", "?"))

    def test_marked_adds_the_mark(self):
        assert self.make(True).marked().startswith("✗ ")

    def test_free_is_marked_good(self):
        v = self.make(False)
        assert v.mark == "✓" and v.ok
        assert "没有别的程序占用" in v.describe()

    def test_unknown_is_not_ok(self):
        """**"不知道"不能当成"没问题"。**

        纯修饰键组合探测不了,但它恰恰是最容易撞的那种 ——
        把它算成 ok 会让用户以为已经确认安全了。
        """
        v = self.make(None)
        assert v.mark == "?" and not v.ok
        assert "查不了" in v.describe()

    def test_describe_names_the_action_and_the_keys(self):
        assert "粘贴" in self.make(False).describe()
        assert "Ctrl + Alt + D" in self.make(False).describe()

    def test_report_skips_empty_bindings(self):
        """留空表示不绑这个动作,不该报一行"没被占用"。"""
        from voiceinput.conflict import report

        assert [v.action for v in report({"甲": "<ctrl>+<alt>+d", "乙": ""})] == ["甲"]


class TestActionLabelsAreSaidOneWay:
    """同一个动作在所有地方叫同一个名字。

    **之前是四种叫法**:设置页「粘贴文字」、向导「粘贴」、自检「粘贴」、
    日志里干脆是内部键名 `paste`。同一个热键被占用,用户在三个地方
    看到三个名字,对不上号 —— 而这恰恰是最需要他看懂的一条提示。
    """

    def test_internal_keys_map_to_one_label_each(self):
        from voiceinput.hotkey import ACTION_LABELS

        assert set(ACTION_LABELS) == {"paste", "paste_and_send"}
        assert len(set(ACTION_LABELS.values())) == 2, "两个动作不能重名"

    def test_labelled_translates_the_keys(self):
        from voiceinput.hotkey import labelled

        got = labelled({"paste": "<ctrl>+<alt>+d",
                        "paste_and_send": "<ctrl>+<alt>+<enter>"})
        assert got == {"粘贴文字": "<ctrl>+<alt>+d",
                       "粘贴并发送": "<ctrl>+<alt>+<enter>"}

    def test_unknown_keys_pass_through(self):
        """认不出的键原样保留,总比显示成空白或者报错强。"""
        from voiceinput.hotkey import labelled

        assert labelled({"某个新动作": "<ctrl>+j"}) == {"某个新动作": "<ctrl>+j"}

    def test_no_raw_internal_key_reaches_the_user(self):
        """**日志里出现 `paste` 是个 bug。** 那是内部键名,不是给人看的。"""
        from voiceinput.conflict import report
        from voiceinput.hotkey import labelled

        verdicts = report(labelled({"paste": "<ctrl>+<alt>+<shift>+f24"}))
        assert verdicts and "paste" not in verdicts[0].describe()
        assert "粘贴文字" in verdicts[0].describe()
