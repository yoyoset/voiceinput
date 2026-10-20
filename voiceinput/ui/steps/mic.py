"""向导第三步:确认选中的设备真的是你的话筒。

**这一步必须真的录一句话跑一遍识别。** 电平只能证明"有声音进来",
证明不了"这是你的人声、而且识别得出来" —— 而选错设备(录到系统回环)
的表现恰恰是电平有反应、识别出一堆无关的词。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from ... import audio as audio_mod
from ...config import Config
from ...metrics import score
from ...postprocess import clean
from ..device_picker import DevicePicker, device_hint
from ..theme import Palette
from ..widgets import Card, hint, restyle
from .base import Step

# 标定用的句子。**必须是纯中文,不要再加英文术语。**
#
# 原来用的是「把这个 function 改成 async」—— 想着贴近真实使用场景。
# 实测这是个错误的判据:SenseVoice 对口说的英文术语本来就不准,
# `async` 会被听成"think"之类的东西。于是**话筒完全正常的人也会被判成
# "和原句差得比较多,可能是设备选错"** —— 这一步给出的是假警报。
#
# 这一步要回答的只有一个问题:**这个设备是不是我的话筒。**
# 英文术语准不准是另一件事(去「词典」页纠正),把两件事混进同一个
# 判据里,结果就是两件事都判不准。
#
# 太短的句子("你好")识别不出问题,太长的又难念。
CALIBRATION_PHRASE = "今天先把这段话整理一下,再看看有没有说错的地方"

# 字错误率高于它就认为"不只是个别词的出入"。
CER_TOLERANCE = 0.2


class MicStep(Step):
    def __init__(self, cfg: Config, palette: Palette, backend, parent=None) -> None:
        super().__init__("标定麦克风", parent)
        self._cfg = cfg
        self._palette = palette
        self._backend = backend
        self._recorder: audio_mod.Recorder | None = None

        pick = Card("第一步:选设备,看电平")
        # 跟设置页共用同一个组件 —— 判断"这到底是不是话筒"的标准只有一份
        self.picker = DevicePicker(palette, self._saved_index())
        self.picker.deviceChanged.connect(self._on_device_changed)
        pick.add(self.picker)
        pick.add(hint(device_hint()))
        self.body.addWidget(pick)

        test = Card("第二步:念一句话,确认识别得出来")
        phrase = QLabel(f"「{CALIBRATION_PHRASE}」")
        phrase.setProperty("role", "section")
        phrase.setWordWrap(True)
        test.add(phrase)

        self.btn_record = QPushButton("按住说话")
        self.btn_record.setProperty("role", "primary")   # 这页的主操作,要显眼
        self.btn_record.setMinimumHeight(38)
        self.btn_record.pressed.connect(self.start_recording)
        self.btn_record.released.connect(self.stop_recording)
        test.add(self.btn_record)

        self.result = QLabel("还没测试")
        self.result.setWordWrap(True)
        self.result.setProperty("role", "hint")
        test.add(self.result)

        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        test.add(self.verdict)
        test.add(hint(
            "电平只能证明有声音进来,证明不了那是你的人声、也证明不了识别得出来。"
            "所以这一步要真的跑一遍。\n"
            "这句话**故意是纯中文的** —— 这一步只判断「设备对不对」。"
            "英文术语(async、pytest 之类)本来就容易听错,那是「词典」页的事,"
            "混进来只会让这一步给出假警报。"
        ))
        self.body.addWidget(test)
        self.body.addStretch(1)

    def _saved_index(self) -> int | None:
        """配置里那个设备**现在**的编号。按名字找,编号只是缓存 —— 见 AudioPage。"""
        a = self._cfg.audio
        try:
            return audio_mod.resolve_device(a.device, a.device_name, a.device_hostapi)[0]
        except Exception:
            return None

    # ---- 进出 ----

    def on_enter(self) -> None:
        self.picker.reload_devices(self._saved_index())
        self.picker.start_monitor()

    def on_leave(self) -> None:
        # 别一直占着麦克风
        self.picker.stop_monitor()

    shutdown = on_leave

    def _on_device_changed(self, device) -> None:
        self._cfg.audio.device = device
        self._cfg.audio.device_name, self._cfg.audio.device_hostapi = \
            self.picker.device_identity()
        # 换了设备,之前那次标定结果就不作数了
        self.result.setText("换了设备,重新测一次")
        self.verdict.setText("")

    # ---- 录一句 ----

    def start_recording(self) -> None:
        # 录音和电平监听不能同时开着抢同一个设备
        self.picker.stop_monitor()
        try:
            self._recorder = audio_mod.Recorder(
                device=self.picker.device(), max_seconds=20.0)
            self._recorder.start()
        except audio_mod.RecordingError as e:
            self._recorder = None
            self._say(False, str(e))
            self.picker.start_monitor()
            return
        self.btn_record.setText("正在录音,松开结束")
        self.result.setText("")
        self.verdict.setText("")

    def stop_recording(self) -> None:
        recorder, self._recorder = self._recorder, None
        self.btn_record.setText("按住说话")
        if recorder is None:
            return
        audio = recorder.stop()
        self.picker.start_monitor()

        if audio.size == 0:
            self._say(False, "没有录到音频")
            return
        if audio_mod.looks_silent(audio):
            self._say(False, "只录到静音 —— 这个设备很可能不是你的话筒,换一个试试")
            return
        if not self._backend.is_engine_ready():
            self._say(False, "模型还没准备好,先回上一步装模型")
            return

        self.result.setText("识别中…")
        # 用录音**实际**的采样率,不能写死 16000 —— WASAPI 设备是 48k,
        # 谎报速率会让识别悄悄变差,标定结果就不可信了。
        self._backend.transcribe_async(audio, recorder.sample_rate, self.on_result)

    def on_result(self, text: str | None, error: str | None) -> None:
        if error:
            self._say(False, error)
            return
        recognized = clean(text or "")
        self.result.setText(f"识别结果:{recognized or '(空)'}")
        if not recognized:
            self._say(False, "没有识别到内容,再试一次")
            return

        cer = score(CALIBRATION_PHRASE, recognized)["cer_norm"]
        if cer == 0:
            self._say(True, "完全正确,麦克风没问题")
        elif cer < CER_TOLERANCE:
            self._say(True, f"基本正确(字错误率 {cer:.0%})。"
                            "少量出入正常,专有名词可以之后在「词典」页纠正")
        else:
            # 判据句是纯中文的,所以这里可以直说是设备/环境的问题 ——
            # 混着英文术语的时候这句话是站不住的,那时差得多完全可能只是
            # 术语没听准,而话筒好得很。
            self._say(False, f"和原句差得比较多(字错误率 {cer:.0%})。"
                             "可能是设备选错、离麦克风太远,或者环境太吵")

    def _say(self, ok: bool, message: str) -> None:
        self.verdict.setText(("✓ " if ok else "✗ ") + message)
        self.verdict.setProperty("role", "hint" if ok else "danger")
        self.verdict.setStyleSheet(f"color: {self._palette.accent};" if ok else "")
        restyle(self.verdict)

    # ---- 写回 ----

    def apply_to(self, cfg: Config) -> None:
        cfg.audio.device = self.picker.device()
        cfg.audio.device_name, cfg.audio.device_hostapi = self.picker.device_identity()

    def summary_rows(self) -> list[tuple[str, str]]:
        return [("麦克风", self.picker.combo.currentText())]
