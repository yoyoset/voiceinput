"""图标全部用 QPainter 画出来,不带图片资源文件。

这样打包成单文件 exe 时不用处理资源路径,换主题色也不用重新导出一套图,
而且高 DPI 下是矢量绘制,不会糊。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap


def _mic_path(w: float, h: float) -> QPainterPath:
    """话筒的实心部分:胶囊形的头、支柱、底座。

    托架那条弧不在这里——弧线要用描边画,填充画不出细弧,见 mic_icon。
    """
    path = QPainterPath()
    cap_w = w * 0.30
    cap_h = h * 0.44
    path.addRoundedRect(
        QRectF((w - cap_w) / 2, h * 0.13, cap_w, cap_h), cap_w / 2, cap_w / 2
    )
    path.addRect(QRectF(w * 0.47, h * 0.72, w * 0.06, h * 0.13))              # 支柱
    path.addRoundedRect(QRectF(w * 0.32, h * 0.85, w * 0.36, h * 0.06), 3, 3)  # 底座
    return path


def mic_icon(color: str, size: int = 64, badge: str | None = None) -> QIcon:
    """画一个话筒图标。badge 是右下角的小圆点颜色,用来表示状态。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    c = QColor(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(_mic_path(size, size))

    # 托架的弧线用描边画,填充画不出细弧
    pen = p.pen()
    pen.setColor(c)
    pen.setWidthF(size * 0.075)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    arc_w, arc_h = size * 0.52, size * 0.40
    p.drawArc(QRectF((size - arc_w) / 2, size * 0.34, arc_w, arc_h), 200 * 16, 160 * 16)

    if badge:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(badge))
        d = size * 0.34
        p.drawEllipse(QRectF(size - d - 1, size - d - 1, d, d))

    p.end()
    return QIcon(pm)


def state_icon(state: str, accent: str, danger: str, dim: str) -> QIcon:
    """按运行状态给图标。

    托盘图标是用户唯一能持续看到的状态指示,状态区分必须一眼可辨。
    """
    if state == "recording":
        return mic_icon(accent, badge=danger)
    if state == "busy":
        return mic_icon(accent, badge="#F59E0B")
    if state == "error":
        return mic_icon(danger)
    if state == "loading":
        return mic_icon(dim)
    return mic_icon(accent)
