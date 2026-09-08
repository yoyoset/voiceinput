"""绿色主题。深浅两套配色 + 一份 Qt 样式表。

配色不是随手挑的:主色用了偏冷的翠绿(#16A34A / #22C55E),在深浅底色上都能
达到足够对比度;深色模式下把主色提亮一档,否则在深底上会发闷。
状态色(录音红、警告橙)刻意跟主色拉开色相,不然指示条上分不出来。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_dim: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    danger: str
    warning: str
    is_dark: bool


LIGHT = Palette(
    bg="#F6F8F6",
    surface="#FFFFFF",
    surface_alt="#EFF4EF",
    border="#D6DFD6",
    text="#16211A",
    text_dim="#5C6B60",
    accent="#16A34A",
    accent_hover="#15903F",
    accent_pressed="#127A36",
    accent_text="#FFFFFF",
    danger="#DC2626",
    warning="#D97706",
    is_dark=False,
)

DARK = Palette(
    bg="#121814",
    surface="#1A221D",
    surface_alt="#212B24",
    border="#2E3A32",
    text="#E6EDE8",
    text_dim="#94A69B",
    accent="#22C55E",
    accent_hover="#34D371",
    accent_pressed="#16A34A",
    accent_text="#0A0F0C",
    danger="#F87171",
    warning="#FBBF24",
    is_dark=True,
)


def system_prefers_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    try:
        scheme = app.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        # 老版本 Qt 没有 colorScheme,退回按窗口底色亮度判断
        window = app.palette().color(QPalette.ColorRole.Window)
        return window.lightness() < 128


def resolve(theme: str) -> Palette:
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    return DARK if system_prefers_dark() else LIGHT


def stylesheet(p: Palette) -> str:
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QWidget {{
    background: {p.bg};
    color: {p.text};
}}

QDialog, QMainWindow {{ background: {p.bg}; }}

QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 19px; font-weight: 600; }}
QLabel[role="subtitle"] {{ font-size: 12px; color: {p.text_dim}; }}
QLabel[role="section"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="hint"] {{ font-size: 12px; color: {p.text_dim}; }}
QLabel[role="danger"] {{ color: {p.danger}; }}
QLabel[role="mono"] {{ font-family: "Cascadia Mono", Consolas, monospace; }}

/* ---- 卡片 ---- */
QFrame[role="card"] {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 16px;
    min-height: 18px;
}}
QPushButton:hover  {{ border-color: {p.accent}; }}
QPushButton:pressed{{ background: {p.surface_alt}; }}
QPushButton:disabled {{ color: {p.text_dim}; border-color: {p.border}; }}

QPushButton[role="primary"] {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: {p.accent_text};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover   {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[role="primary"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[role="primary"]:disabled {{
    background: {p.surface_alt}; border-color: {p.border}; color: {p.text_dim};
}}

QPushButton[role="danger"] {{ color: {p.danger}; }}
QPushButton[role="danger"]:hover {{ border-color: {p.danger}; }}

/* ---- 输入控件 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled, QComboBox:disabled {{ color: {p.text_dim}; background: {p.surface_alt}; }}

/* 数字框的上下箭头同样由 widgets 自己画。系统原生那对按钮在深色主题里
   是两个发亮的浅色方块 —— 看着像外来的、坏掉的东西。这里只把它们抹平,
   留出位置和颜色,箭头本身归 _Stepper 画。 */
QSpinBox, QDoubleSpinBox {{ padding-right: 26px; qproperty-arrowColor: {p.text_dim}; }}
QSpinBox:hover, QDoubleSpinBox:hover {{ qproperty-arrowColor: {p.accent}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    background: transparent;
    border: none;
    width: 22px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none; width: 0; height: 0;
}}

/* 箭头由 widgets.ComboBox 自己画(样式表画箭头要带图片资源,
   绿色软件不想带)。这里只负责留出位置和给颜色。 */
QComboBox {{ padding-right: 26px; qproperty-arrowColor: {p.text_dim}; }}
QComboBox:hover {{ qproperty-arrowColor: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
    outline: none;
}}

/* ---- 复选框 ---- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {p.border};
    border-radius: 4px;
    background: {p.surface};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    image: none;
}}

/* ---- 选项卡 ---- */
QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: 10px;
    background: {p.surface};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_dim};
    padding: 8px 18px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{
    background: {p.surface};
    color: {p.accent};
    border-color: {p.border};
    border-bottom-color: {p.surface};
    font-weight: 600;
}}

/* ---- 表格 ---- */
QTableWidget, QTableView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    gridline-color: {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 7px 9px;
    font-weight: 600;
}}
QTableWidget::item {{ padding: 5px 4px; }}

/* ---- 进度条(电平表)---- */
QProgressBar {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    height: 12px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 5px; }}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{
    background: {p.border}; border-radius: 5px; min-width: 28px;
}}

/* ---- 菜单(托盘)---- */
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 7px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent}; color: {p.accent_text}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}

QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 5px 8px;
}}
"""


def apply_theme(app: QApplication, theme: str) -> Palette:
    p = resolve(theme)
    app.setStyleSheet(stylesheet(p))
    return p
