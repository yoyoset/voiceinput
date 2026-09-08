"""开机自启。之前零测试,而它是**唯一会在系统里留下痕迹的模块**。

测试把 `APPDATA` 重定向到临时目录 —— 既是真跑(真的调 PowerShell 建 .lnk、
真的读回来验证),又绝不碰用户真实的启动文件夹。
"""

import os
import sys
from pathlib import Path

import pytest

from voiceinput import autostart

pytestmark = pytest.mark.skipif(os.name != "nt", reason="只在 Windows 上有意义")


@pytest.fixture
def fake_appdata(tmp_path, monkeypatch):
    """把启动文件夹指到临时目录,绝不动真的那个。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    startup = tmp_path / "Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True)
    return startup


def read_shortcut(lnk: Path) -> dict:
    """用 PowerShell 把 .lnk 读回来 —— 只验证文件存在是不够的,
    要确认它真的指向对的东西。"""
    import subprocess

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); "
        "Write-Output $s.TargetPath; Write-Output $s.Arguments; "
        "Write-Output $s.WorkingDirectory"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "LNK": str(lnk)},
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    keys = ["target", "arguments", "workdir"]
    return dict(zip(keys, lines + [""] * 3))


class TestPaths:
    def test_startup_dir_follows_appdata(self, fake_appdata):
        assert autostart.startup_dir() == fake_appdata

    def test_shortcut_name(self, fake_appdata):
        assert autostart.shortcut_path().name == "VoiceInput.lnk"

    def test_shortcut_lives_outside_program_dir(self, fake_appdata):
        """自启快捷方式**不在**程序目录里 —— 这正是"删掉程序目录即卸载干净"
        这句话的例外,README 里必须交代。"""
        from voiceinput.config import app_dir

        assert app_dir() not in autostart.shortcut_path().parents


class TestEnableDisable:
    def test_starts_disabled(self, fake_appdata):
        assert not autostart.is_enabled()

    def test_enable_creates_shortcut(self, fake_appdata):
        autostart.enable()
        assert autostart.shortcut_path().exists()
        assert autostart.is_enabled()

    def test_shortcut_points_at_something_real(self, fake_appdata):
        """建了个指向不存在文件的快捷方式,等于每次开机静默失败一次。"""
        autostart.enable()
        info = read_shortcut(autostart.shortcut_path())
        assert Path(info["target"]).exists(), info

    def test_shortcut_workdir_is_project_root(self, fake_appdata):
        """开发模式下走 `-m voiceinput`,工作目录不对就 import 不到包。"""
        autostart.enable()
        info = read_shortcut(autostart.shortcut_path())
        assert info["workdir"], info
        assert Path(info["workdir"]).exists()

    def test_disable_removes_shortcut(self, fake_appdata):
        autostart.enable()
        autostart.disable()
        assert not autostart.shortcut_path().exists()
        assert not autostart.is_enabled()

    def test_disable_leaves_nothing_behind(self, fake_appdata):
        """绿色软件的承诺:关掉之后目录里干干净净。"""
        autostart.enable()
        autostart.disable()
        assert list(fake_appdata.iterdir()) == []

    def test_disable_when_not_enabled_is_safe(self, fake_appdata):
        autostart.disable()          # 不该抛
        assert not autostart.is_enabled()

    def test_enable_twice_is_idempotent(self, fake_appdata):
        autostart.enable()
        autostart.enable()
        assert len(list(fake_appdata.glob("*.lnk"))) == 1

    def test_set_enabled_roundtrip(self, fake_appdata):
        autostart.set_enabled(True)
        assert autostart.is_enabled()
        autostart.set_enabled(False)
        assert not autostart.is_enabled()


class TestLaunchTarget:
    def test_dev_mode_uses_pythonw(self, fake_appdata):
        """用 pythonw 而不是 python:否则每次开机弹一个黑框。"""
        target, args, _ = autostart._launch_target()
        assert "pythonw" in target.lower() or "python" in target.lower()
        assert args == "-m voiceinput"

    def test_frozen_mode_points_at_exe(self, fake_appdata, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\somewhere\VoiceInput.exe")
        target, args, workdir = autostart._launch_target()
        assert target.endswith("VoiceInput.exe")
        assert args == ""                       # 打包版不需要 -m
        assert workdir == r"C:\somewhere"


class TestUiReflectsReality:
    """设置里的复选框必须反映**磁盘上的真实状态**,不能读配置。

    用户可以直接把启动文件夹里的快捷方式删掉。那时配置里还写着 true,
    复选框就会显示"已启用"而实际没有 —— 又一次"显示的和实际的不一致"。
    """

    def test_checkbox_follows_disk_not_config(self, qapp, fake_appdata, tmp_path):
        from voiceinput.config import Config
        from voiceinput.history import History
        from voiceinput.ui import theme
        from voiceinput.ui.main_window import MainWindow

        cfg = Config()
        cfg.autostart = True          # 配置说开着
        assert not autostart.is_enabled()   # 磁盘上其实没有

        h = History(path=tmp_path / "h.db")
        w = MainWindow(cfg, theme.DARK, h)
        assert not w.general.autostart.isChecked(), "复选框应该跟磁盘走,不跟配置走"
        w.close()
        h.close()


class TestApply:
    """`apply()` 和**磁盘真实状态**比,不和上一次的配置比。

    用户可能自己把启动文件夹里的快捷方式删了 —— 那时配置里还写着 true,
    按"配置有没有变"来判断的话就永远不会有人去修好它。
    """

    def test_enabling_when_missing_creates_it(self, fake_appdata):
        assert not autostart.is_enabled()
        assert autostart.apply(True) == ""
        assert autostart.is_enabled()

    def test_self_heals_a_manually_deleted_shortcut(self, fake_appdata):
        """**这是它存在的理由。** 配置没变,但磁盘上的东西没了。"""
        autostart.apply(True)
        autostart.shortcut_path().unlink()
        assert not autostart.is_enabled()
        autostart.apply(True)          # 配置仍然是 True,没有"变化"可言
        assert autostart.is_enabled()

    def test_already_correct_is_a_noop(self, fake_appdata, monkeypatch):
        autostart.apply(True)
        called = []
        monkeypatch.setattr(autostart, "set_enabled",
                            lambda e: called.append(e))
        autostart.apply(True)
        assert called == []

    def test_disabling_removes_it(self, fake_appdata):
        autostart.apply(True)
        assert autostart.apply(False) == ""
        assert not autostart.is_enabled()

    def test_setting_failure_is_reported(self, fake_appdata, monkeypatch):
        """**设置失败必须告诉用户** —— 他明确要求了开机自启,没做到就得说。"""
        def boom(enabled):
            raise RuntimeError("写不进启动文件夹")

        monkeypatch.setattr(autostart, "set_enabled", boom)
        assert "写不进启动文件夹" in autostart.apply(True)

    def test_read_failure_is_swallowed(self, fake_appdata, monkeypatch):
        """读状态失败只记日志:那是个只读检查,失败了下次还有机会 ——
        为它弹一个用户看不懂的框没有意义。"""
        def boom():
            raise OSError("路径不可达")

        monkeypatch.setattr(autostart, "is_enabled", boom)
        assert autostart.apply(True) == ""
