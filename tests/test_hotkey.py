
import pytest

from voiceinput.hotkey import HotkeyError, HotkeyManager, describe, parse, validate


class TestParse:
    def test_valid(self):
        assert len(parse("<ctrl>+<cmd>")) == 2
        assert len(parse("<ctrl>+<shift>+<cmd>")) == 3

    def test_invalid_raises(self):
        with pytest.raises(HotkeyError):
            parse("<nonsense_key>+x")

    def test_subset_relationship(self):
        """子集关系是 _best_match 要处理的核心问题,先确认它确实成立。"""
        assert parse("<ctrl>+<cmd>") < parse("<ctrl>+<shift>+<cmd>")


class TestDescribe:
    def test_modifiers(self):
        assert describe("<ctrl>+<cmd>") == "Ctrl + Win"

    def test_ordering_is_canonical(self):
        """无论写的顺序如何,显示顺序都一致,否则界面上看着像两个不同热键。"""
        assert describe("<cmd>+<ctrl>") == describe("<ctrl>+<cmd>")

    def test_three_modifiers(self):
        assert describe("<ctrl>+<shift>+<cmd>") == "Ctrl + Shift + Win"

    def test_letter_key(self):
        assert describe("<ctrl>+<alt>+d") == "Ctrl + Alt + D"


class TestBestMatch:
    """_best_match 必须选最具体的组合。

    按下 Ctrl+Shift+Win 时,Ctrl+Win 的条件也成立;若选错就会变成
    "想发送却只粘贴了"。
    """

    def make(self) -> HotkeyManager:
        return HotkeyManager({
            "paste": "<ctrl>+<cmd>",
            "paste_and_send": "<ctrl>+<shift>+<cmd>",
        })

    def test_picks_shorter_combo(self):
        m = self.make()
        m._pressed = set(parse("<ctrl>+<cmd>"))
        assert m._best_match() == "paste"

    def test_picks_longer_combo_when_both_match(self):
        m = self.make()
        m._pressed = set(parse("<ctrl>+<shift>+<cmd>"))
        assert m._best_match() == "paste_and_send"

    def test_no_match(self):
        m = self.make()
        m._pressed = set(parse("<alt>+<shift>"))
        assert m._best_match() is None

    def test_extra_keys_still_match(self):
        """组合是子集判断,多按了别的键不影响命中。"""
        m = self.make()
        m._pressed = set(parse("<ctrl>+<cmd>")) | set(parse("<alt>"))
        assert m._best_match() == "paste"

    def test_empty_binding_ignored(self):
        m = HotkeyManager({"paste": "<ctrl>+<cmd>", "paste_and_send": ""})
        assert "paste_and_send" not in m._combos

    def test_tie_is_deterministic(self):
        """两个动作绑了同一个组合时,至少要每次都选同一个。

        这种配置本身是错的(validate 会提示),但运行期不能这次触发这个、
        下次触发那个。
        """
        m = HotkeyManager({"zzz": "<ctrl>+<cmd>", "aaa": "<ctrl>+<cmd>"})
        m._pressed = set(parse("<ctrl>+<cmd>"))
        assert m._best_match() == "aaa"          # 按 action 名排序
        assert m._best_match() == m._best_match()


class TestValidate:
    def test_default_config_is_clean(self):
        """默认配置不该自己就带着问题。"""
        from voiceinput.config import HotkeyConfig

        cfg = HotkeyConfig()
        assert validate({
            "粘贴文字": cfg.paste,
            "粘贴并发送": cfg.paste_and_send,
        }) == []

    def test_subset_relationship_is_not_a_conflict(self):
        """子集关系本身不是冲突 —— _best_match 取最具体的那个,是设计好的。"""
        problems = validate({
            "粘贴文字": "<ctrl>+<alt>+<space>",
            "粘贴并发送": "<ctrl>+<alt>+<shift>+<space>",
        })
        assert problems == []

    def test_duplicate_reported_once_with_both_actions(self):
        """两个绑同一个组合是**一个**问题,不能报成两条。

        之前各报一条,界面上就出现了「甲和乙…」「乙和甲…」两行说同一件事。
        """
        problems = validate({"甲": "<ctrl>+<alt>+d", "乙": "<ctrl>+<alt>+d"})
        assert len(problems) == 1
        assert set(problems[0].actions) == {"甲", "乙"}

    def test_duplicate_describe_names_both(self):
        problems = validate({"甲": "<ctrl>+<alt>+d", "乙": "<ctrl>+<alt>+d"})
        text = problems[0].describe()
        assert "甲" in text and "乙" in text

    def test_three_way_duplicate_is_one_problem(self):
        problems = validate({
            "甲": "<ctrl>+<alt>+d", "乙": "<ctrl>+<alt>+d", "丙": "<ctrl>+<alt>+d",
        })
        assert len(problems) == 1
        assert len(problems[0].actions) == 3

    def test_no_modifier_rejected(self):
        problems = validate({"甲": "d"})
        assert len(problems) == 1
        assert "修饰键" in problems[0].message

    def test_risky_combo_warned(self):
        problems = validate({"甲": "<ctrl>+c"})
        assert "常用快捷键" in problems[0].message

    def test_unparseable_reported(self):
        problems = validate({"甲": "<nonsense_key>+x"})
        assert len(problems) == 1
        assert problems[0].actions == ("甲",)

    def test_unparseable_does_not_also_count_as_duplicate(self):
        """解析失败的两个热键不该再被算成"绑了同一个组合"。"""
        problems = validate({"甲": "<bogus>+x", "乙": "<bogus>+x"})
        assert all(len(p.actions) == 1 for p in problems)

    def test_empty_spec_skipped(self):
        """留空表示不绑这个动作,不是错误。"""
        assert validate({"甲": "<ctrl>+<alt>+d", "乙": ""}) == []

    def test_multiple_empties_not_duplicates(self):
        """两个都留空不该被当成"绑了同一个组合"。"""
        assert validate({"甲": "", "乙": ""}) == []

    def test_modifier_only_combo_is_reported(self):
        """**这条测试原来断言的是反的**(叫 test_modifier_only_combo_ok)。

        纯修饰键组合会被它的每一个超集触发:Ctrl+Win 命中的条件是
        "Ctrl 和 Win 都按着",所以 Ctrl+Win+左(Windows 切虚拟桌面)、
        Ctrl+Win+任何键(别的软件的热键)都会让我们开始录音。

        用户报的"热键和微信冲突了"就是这个,而当时默认配置正是
        `<ctrl>+<cmd>` —— 旧测试把这个缺陷当成正确行为钉住了。
        """
        problems = validate({"甲": "<ctrl>+<cmd>"})
        assert len(problems) == 1
        assert "修饰键" in problems[0].message

    def test_modifier_plus_real_key_is_fine(self):
        assert validate({"甲": "<ctrl>+<alt>+<space>"}) == []

    def test_describe_format(self):
        p = validate({"甲": "d"})[0]
        assert p.describe().startswith("「甲」")


class TestPressReleaseMachine:
    """按下/松开的状态机 —— 决定何时开始录音、何时结束。

    之前只测了 `_best_match`(哪个组合被命中),没测过完整的
    按下→触发→松开→结束流程,而 push-to-talk 和 toggle 两套语义
    正是在这里分叉的。

    不调 `start()`:那会装一个真的全局键盘钩子。直接喂 `_on_press`/`_on_release`。
    """

    def make(self, mode="push_to_talk"):
        events = []
        m = HotkeyManager(
            {"paste": "<ctrl>+<cmd>", "paste_and_send": "<ctrl>+<shift>+<cmd>"},
            mode=mode,
            on_start=lambda a: events.append(("start", a)),
            on_stop=lambda a: events.append(("stop", a)),
        )
        return m, events

    @staticmethod
    def keys(spec):
        return sorted(parse(spec), key=repr)

    def press_all(self, m, spec):
        for k in self.keys(spec):
            m._on_press(k)

    def release_all(self, m, spec):
        for k in self.keys(spec):
            m._on_release(k)

    # ---- push-to-talk ----

    def test_push_to_talk_full_cycle(self):
        m, events = self.make()
        self.press_all(m, "<ctrl>+<cmd>")
        assert events == [("start", "paste")]
        self.release_all(m, "<ctrl>+<cmd>")
        assert events == [("start", "paste"), ("stop", "paste")]

    def test_partial_press_does_not_start(self):
        """只按下组合里的一个键不该触发。"""
        m, events = self.make()
        m._on_press(self.keys("<ctrl>+<cmd>")[0])
        assert events == []

    def test_repeat_press_ignored(self):
        """按住不放会持续产生 press 事件,不能反复触发。"""
        m, events = self.make()
        self.press_all(m, "<ctrl>+<cmd>")
        self.press_all(m, "<ctrl>+<cmd>")
        assert events == [("start", "paste")]

    def test_releasing_one_key_ends_it(self):
        """组合里任意一个键松开就算说完了。"""
        m, events = self.make()
        self.press_all(m, "<ctrl>+<cmd>")
        m._on_release(self.keys("<ctrl>+<cmd>")[0])
        assert events[-1] == ("stop", "paste")

    def test_more_specific_combo_wins_on_stop(self):
        """**组合键按不可能同时按下。**

        按 Ctrl+Shift+Win 时,按到 Ctrl+Win 那一刻就已经命中"粘贴文字"了。
        真正决定行为的是**松开时**报哪个动作 —— 必须是按到过的最具体组合,
        否则"粘贴并发送"基本永远不会生效。
        """
        m, events = self.make()
        self.press_all(m, "<ctrl>+<shift>+<cmd>")
        self.release_all(m, "<ctrl>+<shift>+<cmd>")
        assert events[-1] == ("stop", "paste_and_send")

    def test_recording_starts_immediately_not_after_disambiguation(self):
        """消歧不能靠延迟 —— push-to-talk 的即时感比动作准确更早被感知。"""
        m, events = self.make()
        self.press_all(m, "<ctrl>+<cmd>")
        assert events[0][0] == "start"

    def test_plain_combo_still_reports_plain(self):
        """只按 Ctrl+Win 时不能被"升级"成发送。"""
        m, events = self.make()
        self.press_all(m, "<ctrl>+<cmd>")
        self.release_all(m, "<ctrl>+<cmd>")
        assert events[-1] == ("stop", "paste")

    def test_no_stop_without_start(self):
        """没触发过就松开,不该冒出一个 stop。"""
        m, events = self.make()
        self.release_all(m, "<ctrl>+<cmd>")
        assert events == []

    def test_unrelated_keys_ignored(self):
        m, events = self.make()
        alt = next(iter(parse("<alt>")))
        m._on_press(alt)
        m._on_release(alt)
        assert events == []

    def test_second_cycle_works(self):
        """连续说两句,第二次也要正常触发。"""
        m, events = self.make()
        for _ in range(2):
            self.press_all(m, "<ctrl>+<cmd>")
            self.release_all(m, "<ctrl>+<cmd>")
        assert events == [
            ("start", "paste"), ("stop", "paste"),
            ("start", "paste"), ("stop", "paste"),
        ]

    # ---- toggle ----

    def test_toggle_needs_two_cycles(self):
        """按一下开始,再按一下结束 —— 一次完整的按-松只能开始,不能又结束。"""
        m, events = self.make(mode="toggle")
        self.press_all(m, "<ctrl>+<cmd>")
        self.release_all(m, "<ctrl>+<cmd>")
        assert events == [("start", "paste")]

        self.press_all(m, "<ctrl>+<cmd>")
        self.release_all(m, "<ctrl>+<cmd>")
        assert events == [("start", "paste"), ("stop", "paste")]

    def test_toggle_does_not_fire_on_press(self):
        m, events = self.make(mode="toggle")
        self.press_all(m, "<ctrl>+<cmd>")
        assert events == []

    def test_toggle_third_cycle_starts_again(self):
        m, events = self.make(mode="toggle")
        for _ in range(3):
            self.press_all(m, "<ctrl>+<cmd>")
            self.release_all(m, "<ctrl>+<cmd>")
        assert [e[0] for e in events] == ["start", "stop", "start"]

    # ---- 健壮性 ----

    def test_callback_exception_does_not_kill_listener(self):
        """回调里抛异常不能弄死监听线程,否则热键会静默失效。"""
        errors = []
        m = HotkeyManager(
            {"paste": "<ctrl>+<cmd>"},
            on_start=lambda a: (_ for _ in ()).throw(RuntimeError("boom")),
            on_error=errors.append,
        )
        self.press_all(m, "<ctrl>+<cmd>")   # 不该抛出去
        assert errors and "boom" in errors[0]

    def test_stop_clears_state(self):
        """stop 之后残留的按下状态不能影响下次。"""
        m, events = self.make()
        self.press_all(m, "<ctrl>+<cmd>")
        m.stop()
        assert m._pressed == set()
        assert m._active is None
