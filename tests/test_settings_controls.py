"""设置页上那些控件"用起来对不对"。

三条都是用户当面提出来的问题,不是想象出来的边界情况:

1. **步长**。所有数字框原来都是默认步长 1,而框里放的是 80 毫秒、2000 条 ——
   点一下箭头 2000 变 2001,用户的原话是"上下调整数值的这个是不能用的"。
2. **滚轮**。设置页可滚动,Qt 默认把滚轮交给鼠标底下的控件,于是滚一下页面
   路过的控件全被顺手改掉,而且**不报任何错**。
3. **说明文字里的 markdown**。文案照着文档的写法敲了 `**粗体**`,
   QLabel 按纯文本显示,界面上就原样出现两个星号。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QScrollArea

from voiceinput.config import Config
from voiceinput.ui.main_window import MainWindow
from voiceinput.ui.theme import apply_theme
from voiceinput.ui.widgets import SpinBox, hint


@pytest.fixture
def window(qapp):
    cfg = Config()
    win = MainWindow(cfg, apply_theme(qapp, "dark"), None)
    win.resize(680, 400)      # 做矮一点,保证内容超出、滚动条有得滚
    win.show()
    qapp.processEvents()
    yield win, qapp
    win.deleteLater()


def _pages(win, qapp):
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        for _ in range(5):
            qapp.processEvents()
        yield win.tabs.tabText(i), win.tabs.widget(i)


def _wheel(qapp, w, dy=-120):
    c = w.rect().center()
    qapp.sendEvent(w, QWheelEvent(
        c, w.mapToGlobal(c), QPoint(0, dy), QPoint(0, dy),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False))
    qapp.processEvents()


# ---- 步长 ----


def test_每个数字框点一下都走得动(window):
    """判据是"一次点击至少让当前这个数变动百分之二"。

    **不拿范围当判据。** 试过,不成立:历史条数的范围是 50~100000,
    上限纯粹是个不想设限的大数,而实际值在两千上下 —— 按范围算会要求
    步长一千,那是另一个方向的难用。用户看着的是框里那个数,不是范围。

    也不写死具体步长,那样每调一次默认值都得回来改测试。这里守的是
    "别再出现一个步长 1 的两千档数字框"。窗口是拿默认配置建的,
    所以比的是各项的默认值。
    """
    win, qapp = window
    seen = 0
    for tab, page in _pages(win, qapp):
        for box in page.findChildren(QAbstractSpinBox):
            seen += 1
            assert box.singleStep() * 50 >= box.value(), (
                f"[{tab}] 当前值 {box.value()} 却只走 {box.singleStep()} "
                f"—— 点一下等于没动")
    assert seen >= 5, "数字框都没找到,这个测试自己坏了"


# ---- 滚轮 ----


def test_滚轮滑过不改值(window):
    """没有焦点的控件不许被滚轮改掉 —— 数字框和下拉框都算。"""
    win, qapp = window
    for tab, page in _pages(win, qapp):
        for box in page.findChildren(QAbstractSpinBox):
            before = box.value()
            _wheel(qapp, box)
            assert box.value() == before, f"[{tab}] 数字框被滚轮悄悄改掉了"
        for combo in page.findChildren(QComboBox):
            before = combo.currentIndex()
            _wheel(qapp, combo)
            assert combo.currentIndex() == before, f"[{tab}] 下拉框被滚轮悄悄改掉了"


def test_鼠标停在控件上时页面还能滚(window):
    """**修一个不能坏一个。** 光把滚轮吞掉的话,鼠标停在控件上
    整个设置页就滚不动了 —— 那比原来的问题更烦人。
    """
    win, qapp = window
    win.tabs.setCurrentIndex(0)
    for _ in range(8):
        qapp.processEvents()
    page = win.tabs.widget(0)
    area = page.findChild(QScrollArea)
    box = page.findChildren(SpinBox)[0]
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0, "内容没超出,这个测试证明不了什么"

    bar.setValue(0)
    _wheel(qapp, box)
    assert bar.value() > 0, "鼠标停在数字框上,页面滚不动了"


def test_点过之后滚轮仍然能调值(window):
    """挡住的是"路过",不是"想用"。"""
    win, qapp = window
    win.tabs.setCurrentIndex(0)
    for _ in range(8):
        qapp.processEvents()
    box = win.tabs.widget(0).findChildren(SpinBox)[0]
    box.setFocus()
    qapp.processEvents()
    before = box.value()
    _wheel(qapp, box)
    assert box.value() != before, "点过之后滚轮反而调不动了"


# ---- 说明文字 ----


def test_说明文字里的星号变成粗体(qapp):
    label = hint("注意:**别按设备名猜** —— 名字好听的未必是话筒。")
    assert "<b>别按设备名猜</b>" in label.text()
    assert "**" not in label.text()


def test_说明文字里的尖括号不会被当成标签(qapp):
    """文案里出现 `<ctrl>` 这类写法时,不能整段消失。"""
    label = hint("热键写作 <ctrl>+<alt>+a。")
    assert "&lt;ctrl&gt;" in label.text()


def test_没有星号的文案原样显示(qapp):
    label = hint("防止热键卡住导致无限录音把内存吃满。")
    assert label.text() == "防止热键卡住导致无限录音把内存吃满。"
