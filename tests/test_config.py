from pathlib import Path

from voiceinput import config as cfg_mod
from voiceinput.config import Config


class TestRoundTrip:
    def test_defaults_survive(self, tmp_path):
        path = tmp_path / "c.toml"
        original = Config()
        cfg_mod.save(original, path)
        loaded = cfg_mod.load(path)
        assert loaded.hotkey.paste == original.hotkey.paste
        assert loaded.engine.num_threads == original.engine.num_threads
        assert loaded.output.restore_clipboard == original.output.restore_clipboard

    def test_modified_values(self, tmp_path):
        path = tmp_path / "c.toml"
        c = Config()
        c.hotkey.paste = "<ctrl>+<alt>+d"
        c.engine.num_threads = 16
        c.audio.max_seconds = 45.0
        c.ui.theme = "dark"
        c.start_minimized = False
        cfg_mod.save(c, path)

        loaded = cfg_mod.load(path)
        assert loaded.hotkey.paste == "<ctrl>+<alt>+d"
        assert loaded.engine.num_threads == 16
        assert loaded.audio.max_seconds == 45.0
        assert loaded.ui.theme == "dark"
        assert loaded.start_minimized is False

    def test_device_none_round_trips(self, tmp_path):
        """TOML 没有 null。None 必须整键省略,不能写成空串再读回字符串。"""
        path = tmp_path / "c.toml"
        c = Config()
        c.audio.device = None
        cfg_mod.save(c, path)
        # 精确匹配键名。`device_name` / `device_hostapi` 也含 "device",
        # 用子串判断会误判。
        lines = [ln.strip() for ln in path.read_text("utf-8").splitlines()]
        assert not any(ln.startswith("device =") for ln in lines), lines
        assert cfg_mod.load(path).audio.device is None

    def test_device_int_round_trips(self, tmp_path):
        path = tmp_path / "c.toml"
        c = Config()
        c.audio.device = 29
        cfg_mod.save(c, path)
        assert cfg_mod.load(path).audio.device == 29

    def test_replacements(self, tmp_path):
        path = tmp_path / "c.toml"
        c = Config()
        c.replacements = {"keyper": "keytyper", "P test": "pytest"}
        cfg_mod.save(c, path)
        assert cfg_mod.load(path).replacements == c.replacements

    def test_replacement_with_quotes(self, tmp_path):
        path = tmp_path / "c.toml"
        c = Config()
        c.replacements = {'say "hi"': "greeting"}
        cfg_mod.save(c, path)
        assert cfg_mod.load(path).replacements == c.replacements


class TestResilience:
    def test_missing_file(self, tmp_path):
        assert cfg_mod.load(tmp_path / "nope.toml").hotkey.paste == Config().hotkey.paste

    def test_corrupt_file_falls_back(self, tmp_path):
        """配置写坏了不能卡住启动。"""
        path = tmp_path / "c.toml"
        path.write_text("this is not [valid toml", encoding="utf-8")
        assert cfg_mod.load(path).engine.num_threads == Config().engine.num_threads

    def test_unknown_keys_ignored(self, tmp_path):
        """旧程序读到新版本写的配置不该崩。"""
        path = tmp_path / "c.toml"
        path.write_text(
            '[engine]\nnum_threads = 4\nfuture_option = "x"\n', encoding="utf-8"
        )
        assert cfg_mod.load(path).engine.num_threads == 4

    def test_partial_section_uses_defaults(self, tmp_path):
        path = tmp_path / "c.toml"
        path.write_text("[engine]\nnum_threads = 2\n", encoding="utf-8")
        loaded = cfg_mod.load(path)
        assert loaded.engine.num_threads == 2
        assert loaded.engine.use_itn == Config().engine.use_itn

    def test_broken_section_type(self, tmp_path):
        """段被写成标量而不是表,应回退默认值而不是抛异常。"""
        path = tmp_path / "c.toml"
        path.write_text('engine = "oops"\n', encoding="utf-8")
        assert cfg_mod.load(path).engine.num_threads == Config().engine.num_threads


class TestModelPath:
    def test_relative_resolves_under_app_dir(self):
        c = Config()
        c.engine.model_dir = "models/foo"
        assert c.model_path() == cfg_mod.app_dir() / "models/foo"

    def test_absolute_kept(self):
        c = Config()
        c.engine.model_dir = "C:/elsewhere/model"
        assert c.model_path() == Path("C:/elsewhere/model")
