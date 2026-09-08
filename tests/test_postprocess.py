
import pytest

from voiceinput.postprocess import (
    apply_replacements,
    clean,
    collapse_whitespace,
    fix_cjk_ascii_spacing,
    fix_punct_spacing,
    is_effectively_empty,
    strip_tags,
)


class TestStripTags:
    def test_sensevoice_tags(self):
        assert strip_tags("<|zh|><|NEUTRAL|><|Speech|>你好") == "你好"

    def test_woitn_tag(self):
        assert strip_tags("<|woitn|>测试") == "测试"

    def test_no_tags(self):
        assert strip_tags("你好世界") == "你好世界"

    def test_angle_brackets_not_tags(self):
        """普通的尖括号不能被当成标记吃掉。"""
        assert strip_tags("a < b > c") == "a < b > c"


class TestCollapseWhitespace:
    def test_multiple_spaces(self):
        assert collapse_whitespace("a    b") == "a b"

    def test_strips_ends(self):
        assert collapse_whitespace("  你好  ") == "你好"

    def test_newlines_become_space(self):
        assert collapse_whitespace("a\nb") == "a b"


class TestCjkAsciiSpacing:
    def test_adds_space_both_sides(self):
        assert fix_cjk_ascii_spacing("把这个function改成async") == "把这个 function 改成 async"

    def test_half_present_spacing(self):
        """实测 SenseVoice 会输出这种半有半无的空格。"""
        got = fix_cjk_ascii_spacing("把这个 function改成async")
        assert got == "把这个 function 改成 async"

    def test_pure_chinese_untouched(self):
        assert fix_cjk_ascii_spacing("我想做一个语音输入的工具") == "我想做一个语音输入的工具"

    def test_pure_english_untouched(self):
        assert fix_cjk_ascii_spacing("hello world") == "hello world"

    def test_digits(self):
        assert fix_cjk_ascii_spacing("把超时改成30秒") == "把超时改成 30 秒"

    def test_dotted_identifier_kept_whole(self):
        assert fix_cjk_ascii_spacing("改一下config.toml里的值") == "改一下 config.toml 里的值"

    def test_hyphenated_identifier(self):
        assert fix_cjk_ascii_spacing("用large-v3模型") == "用 large-v3 模型"

    def test_trailing_ascii_period_not_spaced(self):
        """单独的标点不是"英文词",不能被拆出空格。

        实测触发过:静音时模型幻觉出 `그.`,后处理给成了 `그 .`。
        """
        assert fix_cjk_ascii_spacing("你好.") == "你好."
        assert fix_cjk_ascii_spacing("그.") == "그."

    def test_leading_ascii_punct_not_spaced(self):
        assert fix_cjk_ascii_spacing(".你好") == ".你好"


class TestPunctSpacing:
    def test_no_space_before(self):
        assert fix_punct_spacing("你好 ，世界") == "你好，世界"

    def test_no_space_after(self):
        assert fix_punct_spacing("你好， 世界") == "你好，世界"

    def test_ascii_spacing_does_not_break_punct(self):
        """加中英空格那步可能在标点旁边留下空格,这一步要收拾干净。"""
        text = fix_cjk_ascii_spacing("跑一遍pytest，然后commit")
        assert fix_punct_spacing(text) == "跑一遍 pytest，然后 commit"


class TestReplacements:
    def test_simple(self):
        assert apply_replacements("keyper 项目", {"keyper": "keytyper"}) == "keytyper 项目"

    def test_case_insensitive(self):
        assert apply_replacements("Keyper", {"keyper": "keytyper"}) == "keytyper"

    def test_longest_key_first(self):
        """短 key 不能先把长 key 的一部分吃掉。"""
        rules = {"test": "TEST", "P test": "pytest"}
        assert apply_replacements("再跑一遍 P test", rules) == "再跑一遍 pytest"

    def test_empty_dict(self):
        assert apply_replacements("原样", {}) == "原样"

    def test_regex_chars_in_key_are_literal(self):
        """key 里的正则元字符必须按字面处理。"""
        assert apply_replacements("a.b", {"a.b": "X"}) == "X"
        assert apply_replacements("axb", {"a.b": "X"}) == "axb"

    def test_backslash_in_value(self):
        assert apply_replacements("path", {"path": r"C:\tmp"}) == r"C:\tmp"


class TestClean:
    def test_full_chain(self):
        got = clean("<|zh|>把这个 function改成async，再跑一遍P test", {"P test": "pytest"})
        assert got == "把这个 function 改成 async，再跑一遍 pytest"

    def test_pure_chinese(self):
        text = "我想做一个语音输入的工具，按住热键说话"
        assert clean(text) == text

    def test_empty(self):
        assert clean("") == ""

    def test_proper_nouns(self):
        rules = {"keyper": "keytyper", "aniggo": "enigo"}
        got = clean("帮我看一下keyper项目的依赖aniggo是什么版本", rules)
        assert got == "帮我看一下 keytyper 项目的依赖 enigo 是什么版本"


class TestIsEffectivelyEmpty:
    @pytest.mark.parametrize("text", ["", "   ", "。", "，。、", "<|zh|><|NEUTRAL|>", "<|zh|>。"])
    def test_empty(self, text):
        assert is_effectively_empty(text)

    @pytest.mark.parametrize("text", ["你好", "a", "1", "<|zh|>好"])
    def test_not_empty(self, text):
        assert not is_effectively_empty(text)


class TestFinalize:
    """原始识别结果 → (可以粘的文字, 失败原因)。

    调用方原来自己写两遍判断加同一句失败文案 —— 那种写法迟早会
    只改其中一处,于是同一件事出现两种说法。
    """

    def test_normal_text_passes(self):
        from voiceinput.postprocess import finalize

        text, problem = finalize("把这个 function 改成 async")
        assert problem == ""
        assert "async" in text

    def test_replacements_are_applied(self):
        from voiceinput.postprocess import finalize

        text, problem = finalize("跑一遍 P test", {"P test": "pytest"})
        assert problem == "" and "pytest" in text

    def test_empty_input_is_reported(self):
        from voiceinput.postprocess import NOTHING_RECOGNISED, finalize

        assert finalize("") == ("", NOTHING_RECOGNISED)

    def test_punctuation_only_is_reported(self):
        """**第一道关。** 没录到人声时模型会吐纯标点 ——
        粘一堆标点比什么都不做更烦人。"""
        from voiceinput.postprocess import NOTHING_RECOGNISED, finalize

        assert finalize("。。。") == ("", NOTHING_RECOGNISED)

    def test_dictionary_emptying_the_sentence_is_reported(self):
        """**第二道关。** 词条的目标写成空是合法的(意思是"这个词删掉"),
        但整句话被替换没了就等于没识别到。"""
        from voiceinput.postprocess import NOTHING_RECOGNISED, finalize

        assert finalize("嗯", {"嗯": ""}) == ("", NOTHING_RECOGNISED)

    def test_both_gates_give_the_same_reason(self):
        """两道关都算"没有识别到内容" —— 用户没必要区分是哪一道拦的。"""
        from voiceinput.postprocess import finalize

        assert finalize("")[1] == finalize("嗯", {"嗯": ""})[1]

    def test_exactly_one_of_the_two_is_empty(self):
        from voiceinput.postprocess import finalize

        for raw, repl in [("你好", None), ("", None), ("。", None), ("嗯", {"嗯": ""})]:
            text, problem = finalize(raw, repl)
            assert bool(text) != bool(problem), (raw, repl)
