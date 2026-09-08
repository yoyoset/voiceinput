
import pytest

from voiceinput.metrics import (
    cer, edit_distance, is_punct, normalize, numbers_to_arabic, score,
)


class TestEditDistance:
    def test_identical(self):
        assert edit_distance("你好", "你好") == 0

    def test_empty(self):
        assert edit_distance("", "") == 0
        assert edit_distance("", "abc") == 3
        assert edit_distance("abc", "") == 3

    def test_substitution(self):
        assert edit_distance("开饭时间", "放饭时间") == 1

    def test_insertion_deletion(self):
        assert edit_distance("开饭时间", "饭时间") == 1
        assert edit_distance("饭时间", "开饭时间") == 1

    def test_mixed(self):
        # kitten -> sitting 是教科书例子,距离 3
        assert edit_distance("kitten", "sitting") == 3


class TestNormalize:
    def test_strips_punctuation(self):
        assert normalize("开饭时间早上9点至下午5点。") == "开饭时间早上9点至下午5点"

    def test_strips_whitespace(self):
        assert normalize("把这个 function 改成 async") == "把这个function改成async"

    def test_lowercases_ascii(self):
        assert normalize("Async PyTest") == "asyncpytest"

    def test_fullwidth_to_halfwidth(self):
        # NFKC 把全角数字/字母折成半角,否则同一句会因输入法不同判成错
        assert normalize("１２３ＡＢＣ") == "123abc"

    def test_chinese_punct_removed(self):
        assert normalize("这个,那个;还有:什么?") == "这个那个还有什么"

    def test_empty(self):
        assert normalize("") == ""
        assert normalize("。、,.!") == ""


class TestIsPunct:
    @pytest.mark.parametrize("ch", ["，", "。", "、", "?", ".", "!", "—", "「"])
    def test_punct(self, ch):
        assert is_punct(ch)

    @pytest.mark.parametrize("ch", ["你", "a", "9", "あ"])
    def test_not_punct(self, ch):
        assert not is_punct(ch)


class TestCer:
    def test_perfect(self):
        assert cer("你好世界", "你好世界") == 0.0

    def test_all_wrong(self):
        assert cer("你好", "") == 1.0

    def test_empty_truth(self):
        assert cer("", "") == 0.0
        assert cer("", "多出来的") == 1.0

    def test_one_of_four(self):
        assert cer("开饭时间", "放饭时间") == pytest.approx(0.25)


class TestScore:
    def test_punctuation_only_diff(self):
        """只差标点:raw 有惩罚,norm 应为 0。这正是两个口径要分开看的原因。"""
        s = score("开饭时间早上9点。", "开饭时间早上9点")
        assert s["cer_norm"] == 0.0
        assert s["cer_raw"] > 0.0

    def test_mixed_language(self):
        s = score("把这个 function 改成 async", "把这个function改成async")
        assert s["cer_norm"] == 0.0

    def test_real_error_survives_normalization(self):
        """真错字不能被归一化洗掉。"""
        s = score("开饭时间", "放饭时间")
        assert s["cer_norm"] == pytest.approx(0.25)


class TestNumbersToArabic:
    """中文数字要和阿拉伯数字对得上,否则含数字的样本会被判成大面积错误。

    实测:朗读稿写「三十秒」,开了 ITN 的模型输出「30秒」—— 内容完全正确,
    逐字比却算出 30.4% CER。不修的话真人标定时含数字的句子会把成绩
    压得莫名其妙地低,足以影响引擎选型。
    """

    @pytest.mark.parametrize("cn,expected", [
        ("三十", "30"), ("十六", "16"), ("十", "10"),
        ("一百二十", "120"), ("两千三百", "2300"), ("一万六千", "16000"),
        ("零", "0"), ("五", "5"),
    ])
    def test_converts(self, cn, expected):
        assert numbers_to_arabic(cn) == expected

    def test_keeps_surrounding_text(self):
        assert numbers_to_arabic("把超时改成三十秒") == "把超时改成30秒"

    def test_multiple_numbers(self):
        assert numbers_to_arabic("改成三十秒最多重试三次") == "改成30秒最多重试3次"

    def test_leaves_arabic_alone(self):
        assert numbers_to_arabic("改成 30 秒") == "改成 30 秒"

    def test_leaves_plain_text_alone(self):
        assert numbers_to_arabic("把这个 function 改成 async") == "把这个 function 改成 async"


class TestNumberAwareCer:
    def test_itn_output_is_not_penalized(self):
        """这是加数字归一化的**唯一理由**:ITN 转出来的数字不该被当成错误。"""
        s = score("把超时改成三十秒", "把超时改成30秒")
        assert s["cer_norm"] == 0.0
        # raw 仍然记这笔账 —— 它衡量的是"能不能直接用而不动手"
        assert s["cer_raw"] > 0.0

    def test_real_number_error_still_counts(self):
        """归一化不能把真的听错数字也洗掉。"""
        s = score("改成三十秒", "改成50秒")
        assert s["cer_norm"] > 0.0

    def test_both_sides_normalized(self):
        """两边都转,所以反过来写也一样。"""
        assert score("改成30秒", "改成三十秒")["cer_norm"] == 0.0

    def test_imperfect_conversion_does_not_invent_errors(self):
        """转换不完美时(比如没人这么说的怪组合),两边转法一致,
        所以只是"没修好",不会凭空造出错误。"""
        assert score("十六千赫兹", "十六千赫兹")["cer_norm"] == 0.0
