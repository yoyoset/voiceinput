"""自检的输出不能因为编码问题凭空消失。

**踩过的坑:** 中文 Windows 的控制台是 GBK,而 `✓`(U+2713)GBK 编不出来。
打包版自检里两条热键结论就这样从控制台消失了 —— 报告文件(UTF-8)里有,
控制台里没有。看起来像"那段代码根本没跑",实际是 `print` 抛了
UnicodeEncodeError,被 `except Exception: pass` 吞掉。

**自检本身出现静默失败,比它要检查的那些问题更坏** —— 它是用来
排除静默失败的那个工具。
"""

import io
import sys

import pytest

from voiceinput.selftest.report import Report, safe_print


class GbkStdout(io.TextIOBase):
    """模拟中文 Windows 控制台:只认 GBK。"""

    encoding = "gbk"

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:
        text.encode("gbk")        # 编不了就抛,和真控制台一样
        self.written.append(text)
        return len(text)


class TestGbkConsole:
    def test_the_mark_really_is_unencodable(self):
        """先确认前提成立 —— 不然下面的测试测的是个假问题。"""
        with pytest.raises(UnicodeEncodeError):
            "✓".encode("gbk")

    def test_plain_chinese_goes_through(self, monkeypatch):
        out = GbkStdout()
        monkeypatch.setattr(sys, "stdout", out)
        safe_print("[通过] 模型加载成功")
        assert "[通过] 模型加载成功" in "".join(out.written)

    def test_unencodable_line_still_appears(self, monkeypatch):
        """**核心断言:整行不能消失。**

        字符本身可以退化成问号,但"这一行发生过"必须留下。
        """
        out = GbkStdout()
        monkeypatch.setattr(sys, "stdout", out)
        safe_print("✓ 热键没有别的程序占用")
        text = "".join(out.written)
        assert "热键没有别的程序占用" in text

    def test_no_stdout_at_all_is_survivable(self, monkeypatch):
        """frozen + console=False 时根本没有 stdout,不该因此崩掉。"""
        class Dead(io.TextIOBase):
            encoding = "utf-8"

            def write(self, text):
                raise OSError("no console")

        monkeypatch.setattr(sys, "stdout", Dead())
        safe_print("随便什么")          # 不抛就算过


class TestReportFileIsTheFullRecord:
    """控制台会退化,报告文件不会 —— 它是 UTF-8 写的。"""

    def test_report_keeps_the_original_text(self, tmp_path, monkeypatch):
        from voiceinput import selftest
        from voiceinput.selftest import report as report_mod  # noqa: F401

        monkeypatch.setattr(sys, "stdout", GbkStdout())
        report = tmp_path / "selftest.txt"
        # 只跑到写第一行就够了 —— 这里验的是写盘路径,不是各项检查
        monkeypatch.setattr(selftest.report, "safe_print", lambda msg: None)
        selftest.run(report_path=report)
        assert report.exists()
        assert "VoiceInput 自检" in report.read_text(encoding="utf-8")


class TestVerdictCannotDrift:
    """`[失败]` 和"结论不通过"必须是**同一个动作**。

    以前是 `say("[失败] …")` 后面手写一句 `ok = False`,靠人记得写 ——
    出现在十几个地方。漏一次的后果是:界面上报了失败,
    退出码却是 0,自检说的和它返回给调用方的东西不一致。
    """

    def report(self, tmp_path):
        return Report(tmp_path / "r.txt")

    def test_starts_ok(self, tmp_path):
        assert self.report(tmp_path).ok

    def test_passed_keeps_it_ok(self, tmp_path):
        r = self.report(tmp_path)
        r.passed("一切正常")
        assert r.ok and "[通过] 一切正常" in r.text

    def test_failed_flips_the_verdict(self, tmp_path):
        r = self.report(tmp_path)
        r.failed("坏了")
        assert not r.ok and "[失败] 坏了" in r.text

    def test_verdict_stays_bad_after_later_passes(self, tmp_path):
        """一次失败之后,后面再多的通过也不能把结论翻回来。"""
        r = self.report(tmp_path)
        r.failed("坏了")
        r.passed("这个没坏")
        assert not r.ok

    def test_noted_does_not_fail_the_run(self, tmp_path):
        """热键被别的软件占了要说,但那不是这个程序的问题。"""
        r = self.report(tmp_path)
        r.noted("热键被占用")
        assert r.ok and "[注意]" in r.text

    def test_detail_is_indented_and_neutral(self, tmp_path):
        """逐个设备的明细是上一行的补充,不单独构成结论。"""
        r = self.report(tmp_path)
        r.detail("[失败] #3 打不开")
        assert r.ok, "明细行不该直接决定整体结论"
        assert "        [失败] #3 打不开" in r.text

    def test_verdict_helper_picks_the_right_side(self, tmp_path):
        r = self.report(tmp_path)
        r.verdict(True, "行")
        assert r.ok
        r.verdict(False, "不行")
        assert not r.ok

    def test_every_line_is_flushed_immediately(self, tmp_path):
        """**不能等跑完再写。** 自检的价值恰恰在于定位"卡在哪一步",
        而卡住的时候正是写不到最后那一步的时候。"""
        path = tmp_path / "r.txt"
        r = Report(path)
        r.line("第一行")
        assert "第一行" in path.read_text(encoding="utf-8")

    def test_unwritable_path_does_not_crash(self, tmp_path):
        """报告写不出去也要继续跑完 —— 控制台上还有输出。"""
        r = Report(tmp_path / "no-such-dir" / "r.txt")
        r.passed("照样能跑")
        assert r.ok
