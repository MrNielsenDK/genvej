#!/usr/bin/env python3
"""Tegner Genvejs programikon og skriver det i brugerens hicolor-tema."""

import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QRectF

SIZES = (32, 48, 64, 128, 256, 512)
CANVAS = 512


def draw() -> QtGui.QImage:
    image = QtGui.QImage(CANVAS, CANVAS, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    gradient = QtGui.QLinearGradient(0, 0, CANVAS, CANVAS)
    gradient.setColorAt(0.0, QtGui.QColor("#4f7cf7"))
    gradient.setColorAt(1.0, QtGui.QColor("#7b3fe4"))
    painter.setBrush(QtGui.QBrush(gradient))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(24, 24, CANVAS - 48, CANVAS - 48), 108, 108)

    pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 235))
    pen.setWidth(20)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    centre, radius = CANVAS / 2, 128
    painter.drawEllipse(QtCore.QPointF(centre, centre - 14), radius, radius)
    painter.drawEllipse(QtCore.QPointF(centre, centre - 14), radius * 0.48, radius)
    painter.drawLine(QtCore.QPointF(centre - radius, centre - 14),
                     QtCore.QPointF(centre + radius, centre - 14))

    bx, by, br = CANVAS - 150, CANVAS - 150, 74
    painter.setPen(Qt.NoPen)
    painter.setBrush(QtGui.QColor("#ffffff"))
    painter.drawEllipse(QtCore.QPointF(bx, by), br, br)
    plus = QtGui.QPen(QtGui.QColor("#5a4ae8"))
    plus.setWidth(22)
    plus.setCapStyle(Qt.RoundCap)
    painter.setPen(plus)
    painter.drawLine(QtCore.QPointF(bx - 34, by), QtCore.QPointF(bx + 34, by))
    painter.drawLine(QtCore.QPointF(bx, by - 34), QtCore.QPointF(bx, by + 34))
    painter.end()
    return image


def main() -> None:
    QtWidgets.QApplication([])
    image = draw()
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".local/share/icons/hicolor"
    for size in SIZES:
        target = root / f"{size}x{size}" / "apps"
        target.mkdir(parents=True, exist_ok=True)
        image.scaled(size, size, Qt.KeepAspectRatio,
                     Qt.SmoothTransformation).save(str(target / "genvej.png"), "PNG")
    print(f"skrev genvej.png i {len(SIZES)} størrelser under {root}")


if __name__ == "__main__":
    main()
