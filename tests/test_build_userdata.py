"""重新打包不能删掉用户的配置和历史。

**这组测试有具体的事故来源。** 2026-08-26 重新打包时,`clean_dist()` 的
`shutil.rmtree(dist)` 把用户的 config.toml 和 history.db 一起删了 ——
没有提示、没有备份、不可恢复。

根因不是"忘了备份",是**备份这一步靠人记住**。绿色软件把数据放在 exe 旁边
(这是对的),那么打包流程就必须自己认得哪些文件是用户的、哪些是产物。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def build():
    """build.py 在项目根,不是包的一部分,按路径加载。"""
    spec = importlib.util.spec_from_file_location("_buildscript", ROOT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_buildscript"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "VoiceInput"
    d.mkdir()
    (d / "config.toml").write_text('[audio]\ndevice = 3\n', encoding="utf-8")
    (d / "history.db").write_bytes(b"SQLite format 3\x00fake")
    (d / "VoiceInput.exe").write_bytes(b"MZ")      # 产物,不该被备份
    return d


class TestRescue:
    def test_backs_up_user_files(self, build, dist):
        backup = build.rescue_user_data(dist)
        assert backup is not None
        assert (backup / "config.toml").exists()
        assert (backup / "history.db").exists()

    def test_does_not_back_up_build_output(self, build, dist):
        """exe 是产物,备份它没有意义,还会在还原时和新产物打架。"""
        backup = build.rescue_user_data(dist)
        assert not (backup / "VoiceInput.exe").exists()

    def test_backup_lives_outside_dist(self, build, dist):
        """备份必须在 dist 之外 —— 否则下一步的 rmtree 会连备份一起删掉,
        那就等于没备份。"""
        backup = build.rescue_user_data(dist)
        assert dist not in backup.parents and backup != dist

    def test_nothing_to_rescue(self, build, tmp_path):
        """全新的机器上没有旧产物,不该报错。"""
        assert build.rescue_user_data(tmp_path / "nope") is None


class TestRestore:
    def test_round_trip_survives_rmtree(self, build, dist):
        """完整走一遍事故当时的流程:备份 → 删光 → 重建 → 还原。"""
        import shutil

        backup = build.rescue_user_data(dist)
        shutil.rmtree(dist)                       # 就是这一步删掉了用户数据
        dist.mkdir()
        (dist / "VoiceInput.exe").write_bytes(b"MZ")

        build.restore_user_data(backup, dist)
        assert (dist / "config.toml").read_text(encoding="utf-8") == '[audio]\ndevice = 3\n'
        assert (dist / "history.db").read_bytes() == b"SQLite format 3\x00fake"

    def test_does_not_overwrite_existing(self, build, dist, capsys):
        """新产物里已经有同名文件时不覆盖,并且要说出来。

        静默二选一是这个项目最不能接受的行为 —— 无论选哪个都有人会丢东西。
        """
        backup = build.rescue_user_data(dist)
        (dist / "config.toml").write_text("新的\n", encoding="utf-8")
        build.restore_user_data(backup, dist)
        assert (dist / "config.toml").read_text(encoding="utf-8") == "新的\n"
        assert "没有覆盖" in capsys.readouterr().out

    def test_restore_none_is_noop(self, build, dist):
        build.restore_user_data(None, dist)
        assert (dist / "config.toml").exists()

    def test_backup_cleaned_up_after_restore(self, build, dist):
        """还原成功后备份就没用了,别在 temp 里越积越多。"""
        backup = build.rescue_user_data(dist)
        for name in ("config.toml", "history.db"):
            (dist / name).unlink()
        build.restore_user_data(backup, dist)
        assert not backup.exists()
