"""Zamonaviy loading indikatorlar — POS uchun."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QConicalGradient
from ui.scale import s, font
import math


class SpinnerWidget(QWidget):
    """Aylanuvchi halqa — zamonaviy loading spinner."""

    def __init__(self, size=48, color="#3b82f6", thickness=4, parent=None):
        super().__init__(parent)
        self._size = s(size)
        self._color = QColor(color)
        self._thickness = s(thickness)
        self._angle = 0

        self.setFixedSize(self._size, self._size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.setInterval(16)  # ~60 fps

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _rotate(self):
        self._angle = (self._angle + 5) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fon halqa (xira)
        pen_bg = QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), 40))
        pen_bg.setWidth(self._thickness)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        margin = self._thickness
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        p.setPen(pen_bg)
        p.drawEllipse(rect)

        # Gradient arc
        cx = float(rect.center().x())
        cy = float(rect.center().y())
        gradient = QConicalGradient(cx, cy, self._angle)
        gradient.setColorAt(0.0, self._color)
        gradient.setColorAt(0.5, QColor(self._color.red(), self._color.green(), self._color.blue(), 0))
        gradient.setColorAt(1.0, self._color)

        pen = QPen(gradient, self._thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(self._angle * 16), int(120 * 16))
        p.end()


class LoadingOverlay(QWidget):
    """Shaffof qatlamli sahifa loading — spinner + matn."""

    def __init__(self, parent=None, text="Yuklanmoqda...", size=48, bg_opacity=200):
        super().__init__(parent)
        self._bg_opacity = bg_opacity
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(s(14))

        self._spinner = SpinnerWidget(size=size, parent=self)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel(text)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"font-size: {font(14)}px; font-weight: 600; color: #64748b;"
            f" background: transparent;"
        )
        layout.addWidget(self._label)

        self.hide()

    def set_text(self, text: str):
        self._label.setText(text)

    def show_loading(self, text: str = ""):
        if text:
            self._label.setText(text)
        if self.parent():
            self.setGeometry(self.parent().rect())
        self._spinner.start()
        self.show()
        self.raise_()

    def hide_loading(self):
        self._spinner.stop()
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(255, 255, 255, self._bg_opacity))
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(self.parent().rect())


class InlineSpinner(QWidget):
    """Kichik inline spinner — tugma yoki label yonida."""

    def __init__(self, size=20, color="#3b82f6", parent=None):
        super().__init__(parent)
        self._spinner = SpinnerWidget(size=size, color=color, thickness=3, parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._spinner)
        self.setFixedSize(s(size + 4), s(size + 4))
        self.hide()

    def start(self):
        self._spinner.start()
        self.show()

    def stop(self):
        self._spinner.stop()
        self.hide()
