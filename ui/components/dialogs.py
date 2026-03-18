"""Shared modern dialogs and widgets for the POS application.

InfoDialog — success / warning / error
ConfirmDialog — yes / no
ClickableLineEdit — click signal bilan QLineEdit
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QLineEdit,
)
from PyQt6.QtCore import pyqtSignal


class ClickableLineEdit(QLineEdit):
    """Bosilganda signal chiqaradigan QLineEdit — numpad bilan ishlash uchun."""
    clicked = pyqtSignal(object)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self)


class InfoDialog(QDialog):
    """kind: 'success' | 'warning' | 'error'"""
    _ICONS = {"success": "✓", "warning": "⚠️", "error": "✕"}
    _COLORS = {"success": "#16a34a", "warning": "#d97706", "error": "#dc2626"}
    _BG = {"success": "#f0fdf4", "warning": "#fffbeb", "error": "#fef2f2"}
    _BORDER = {"success": "#bbf7d0", "warning": "#fde68a", "error": "#fecaca"}

    def __init__(self, parent, title: str, message: str, kind: str = "success"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(380)
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        ic = QLabel(self._ICONS.get(kind, "ℹ"))
        ic.setStyleSheet(
            f"font-size:26px; background:{self._BG.get(kind, '#f8fafc')};"
            f"border:1.5px solid {self._BORDER.get(kind, '#e2e8f0')};"
            f"border-radius:10px; padding:6px 12px;"
        )
        top.addWidget(ic)
        ttl = QLabel(title)
        ttl.setStyleSheet(f"font-size:16px; font-weight:800; color:{self._COLORS.get(kind, '#1e293b')};")
        top.addWidget(ttl, 1)
        layout.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#f1f5f9; max-height:1px;")
        layout.addWidget(sep)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size:13px; color:#334155; line-height:1.5;")
        layout.addWidget(msg)

        ok = QPushButton("OK")
        ok.setFixedHeight(42)
        ok.setStyleSheet(
            f"QPushButton{{background:{self._COLORS.get(kind, '#3b82f6')};"
            f"color:white;font-weight:700;border-radius:10px;border:none;}}"
            f"QPushButton:hover{{opacity:0.9;}}"
        )
        ok.clicked.connect(self.accept)
        layout.addWidget(ok)


class ConfirmDialog(QDialog):
    """Tasdiqlash dialogi — Ha / Yo'q"""
    def __init__(self, parent, title: str, message: str, icon: str = "❓",
                 yes_text: str = "Ha", no_text: str = "Yo'q",
                 yes_color: str = "#dc2626"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(380)
        self.setStyleSheet("background: white;")
        self.result_accepted = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        ic = QLabel(icon)
        ic.setStyleSheet(
            "font-size:26px; background:#fffbeb;"
            "border:1.5px solid #fde68a; border-radius:10px; padding:6px 12px;"
        )
        top.addWidget(ic)
        ttl = QLabel(title)
        ttl.setStyleSheet("font-size:16px; font-weight:800; color:#1e293b;")
        top.addWidget(ttl, 1)
        layout.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#f1f5f9; max-height:1px;")
        layout.addWidget(sep)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size:13px; color:#334155;")
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        no_btn = QPushButton(no_text)
        no_btn.setFixedHeight(42)
        no_btn.setStyleSheet(
            "QPushButton{background:#f1f5f9;color:#64748b;font-weight:700;"
            "border-radius:10px;border:none;}"
            "QPushButton:hover{background:#e2e8f0;}"
        )
        no_btn.clicked.connect(self.reject)

        yes_btn = QPushButton(yes_text)
        yes_btn.setFixedHeight(42)
        yes_btn.setStyleSheet(
            f"QPushButton{{background:{yes_color};color:white;font-weight:700;"
            f"border-radius:10px;border:none;}}"
            f"QPushButton:hover{{opacity:0.9;}}"
        )
        yes_btn.clicked.connect(self._on_yes)

        btn_row.addWidget(no_btn, 1)
        btn_row.addWidget(yes_btn, 1)
        layout.addLayout(btn_row)

    def _on_yes(self):
        self.result_accepted = True
        self.accept()
