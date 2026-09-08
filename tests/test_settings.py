"""配置变了之后谁要跟着动。

以前这是 App 里一串语句,读的人得从头看到尾才知道有哪些子系统参与。
现在是一份名单 —— 忘了登记的表现仍然是"改了设置对它没生效",
但名单在一处、看得见。
"""

import pytest

from voiceinput.config import Config
from voiceinput.settings import Settings


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """把落盘引到临时文件,别碰真实配置。"""
    path = tmp_path / "config.toml"
    monkeypatch.setattr("voiceinput.settings.config_mod.CONFIG_PATH", path)

    import voiceinput.config as config_mod

    real_save = config_mod.save
    monkeypatch.setattr("voiceinput.settings.config_mod.save",
                        lambda cfg, p=None: real_save(cfg, path))
    return path


@pytest.fixture
def settings(qapp, saved):
    return Settings(Config())


class TestCurrent:
    def test_starts_with_what_it_was_given(self, settings):
        assert settings.current.ui.theme == "auto"

    def test_update_swaps_it(self, settings):
        cfg = Config()
        cfg.ui.theme = "dark"
        settings.update(cfg)
        assert settings.current is cfg


class TestFollowers:
    def test_everyone_on_the_list_is_told(self, settings):
        seen = [[], [], []]
        settings.follow(seen[0].append, seen[1].append, seen[2].append)
        cfg = Config()
        settings.update(cfg)
        assert all(s == [cfg] for s in seen)

    def test_order_is_the_registration_order(self, settings):
        """有些子系统之间有先后要求(比如换主题要在控件还活着的时候)——
        名单的顺序就是执行顺序,不能靠字典序之类的巧合。"""
        order = []
        settings.follow(lambda c: order.append("甲"),
                        lambda c: order.append("乙"),
                        lambda c: order.append("丙"))
        settings.update(Config())
        assert order == ["甲", "乙", "丙"]

    def test_nobody_registered_is_fine(self, settings):
        settings.update(Config())      # 不抛就算过

    def test_followers_registered_later_still_get_told(self, settings):
        early, late = [], []
        settings.follow(early.append)
        settings.follow(late.append)
        settings.update(Config())
        assert len(early) == 1 and len(late) == 1


class TestPersistence:
    def test_update_writes_to_disk(self, settings, saved):
        cfg = Config()
        cfg.engine.num_threads = 12
        settings.update(cfg)
        assert "num_threads = 12" in saved.read_text(encoding="utf-8")

    def test_save_writes_without_telling_anyone(self, settings, saved):
        """拖动悬浮麦克风走这条:位置直接改在 Config 上,
        没有"新配置"这回事,也不需要惊动任何子系统。"""
        seen = []
        settings.follow(seen.append)
        settings.current.ui.mic_badge_x = 300
        settings.save()
        assert seen == []
        assert "mic_badge_x = 300" in saved.read_text(encoding="utf-8")

    def test_disk_is_written_before_followers_run(self, settings, saved):
        """**顺序不能反。**

        通知过程中任何一个 follower 抛异常都会中断后面的,而那时配置
        已经在内存里生效了 —— 不先存盘的话,用户重启一次改动就没了,
        而界面上明明显示改过。
        """
        def boom(cfg):
            raise RuntimeError("某个子系统炸了")

        settings.follow(boom)
        cfg = Config()
        cfg.engine.num_threads = 9
        with pytest.raises(RuntimeError):
            settings.update(cfg)
        assert "num_threads = 9" in saved.read_text(encoding="utf-8")

    def test_unwritable_path_does_not_crash(self, qapp, tmp_path, monkeypatch):
        """存不下来不该拦住程序 —— 这次改动在内存里仍然生效。"""
        def boom(cfg, p=None):
            raise OSError("只读磁盘")

        monkeypatch.setattr("voiceinput.settings.config_mod.save", boom)
        s = Settings(Config())
        seen = []
        s.follow(seen.append)
        cfg = Config()
        s.update(cfg)
        assert s.current is cfg
        assert seen == [cfg], "存盘失败不该连通知都跳过"
