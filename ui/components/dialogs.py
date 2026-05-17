"""Shared modern dialogs and widgets for the POS application.

InfoDialog — success / warning / error
ConfirmDialog — yes / no
ClickableLineEdit — click signal bilan QLineEdit
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QLineEdit,
)
from PyQt6.QtCore import pyqtSignal, Qt
from ui.scale import s, font


class ClickableLineEdit(QLineEdit):
    """Bosilganda signal chiqaradigan QLineEdit — numpad bilan ishlash uchun."""
    clicked = pyqtSignal(object)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self)


class InfoDialog(QDialog):
    """kind: 'success' | 'warning' | 'error' | 'info'

    `icon` parametri orqali default emoji o'rniga ixtiyoriy ikona ko'rsatish
    mumkin (masalan printer xatosi uchun 🖨️).
    """
    _ICONS = {"success": "✓", "warning": "!", "error": "✕", "info": "i"}
    _COLORS = {
        "success": "#16a34a",
        "warning": "#0369a1",   # qizil/sariq emas — yumshoqroq ko'k
        "error": "#dc2626",
        "info": "#0369a1",
    }
    _BG = {
        "success": "#f0fdf4",
        "warning": "#eff6ff",
        "error": "#fef2f2",
        "info": "#eff6ff",
    }
    _BORDER = {
        "success": "#bbf7d0",
        "warning": "#bfdbfe",
        "error": "#fecaca",
        "info": "#bfdbfe",
    }

    def __init__(self, parent, title: str, message: str,
                 kind: str = "success", icon: str = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        # Fixed o'rniga min/max — uzun matn uchun keng bo'lsin
        self.setMinimumWidth(s(440))
        self.setMaximumWidth(s(640))
        self.setStyleSheet("background: white;")
        self.setSizeGripEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(24), s(20), s(24), s(20))
        layout.setSpacing(s(14))

        # ── Top row: icon + title ─────────────────
        top = QHBoxLayout()
        top.setSpacing(s(14))
        top.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        ic_text = icon if icon is not None else self._ICONS.get(kind, "i")
        ic = QLabel(ic_text)
        ic.setFixedSize(s(44), s(44))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(
            f"font-size:{font(22)}px; font-weight:800;"
            f"color:{self._COLORS.get(kind, '#0369a1')};"
            f"background:{self._BG.get(kind, '#f8fafc')};"
            f"border:1.5px solid {self._BORDER.get(kind, '#e2e8f0')};"
            f"border-radius:{s(22)}px;"
        )
        top.addWidget(ic)

        ttl = QLabel(title)
        ttl.setStyleSheet(
            f"font-size:{font(17)}px; font-weight:800;"
            f"color:#0f172a; background:transparent;"
        )
        ttl.setWordWrap(True)
        top.addWidget(ttl, 1)
        layout.addLayout(top)

        # ── Separator ─────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#f1f5f9; max-height:1px;")
        layout.addWidget(sep)

        # ── Message ───────────────────────────────
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setMinimumHeight(s(40))
        msg.setStyleSheet(
            f"font-size:{font(13)}px; color:#334155; background:transparent;"
            f" padding:{s(4)}px 0;"
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(msg, 1)

        # ── OK button ─────────────────────────────
        btn_color = self._COLORS.get(kind, "#0369a1")
        ok = QPushButton("Tushunarli")
        ok.setFixedHeight(s(44))
        ok.setMinimumWidth(s(140))
        ok.setStyleSheet(
            f"QPushButton{{background:{btn_color}; color:white;"
            f"font-weight:700; font-size:{font(13)}px;"
            f"border-radius:{s(10)}px; border:none; padding:0 {s(20)}px;}}"
            f"QPushButton:hover{{background:{btn_color}; opacity:0.9;}}"
            f"QPushButton:pressed{{background:#0f172a;}}"
        )
        ok.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        # Content ga qarab o'lcham
        self.adjustSize()


class ConfirmDialog(QDialog):
    """Tasdiqlash dialogi — Ha / Yo'q"""
    def __init__(self, parent, title: str, message: str, icon: str = "❓",
                 yes_text: str = "Ha", no_text: str = "Yo'q",
                 yes_color: str = "#dc2626"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(s(380))
        self.setStyleSheet("background: white;")
        self.result_accepted = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(22), s(18), s(22), s(18))
        layout.setSpacing(s(12))

        top = QHBoxLayout()
        ic = QLabel(icon)
        ic.setStyleSheet(
            f"font-size:{font(26)}px; background:#fffbeb;"
            f"border:1.5px solid #fde68a; border-radius:{s(10)}px; padding:{s(6)}px {s(12)}px;"
        )
        top.addWidget(ic)
        ttl = QLabel(title)
        ttl.setStyleSheet(f"font-size:{font(16)}px; font-weight:800; color:#1e293b;")
        top.addWidget(ttl, 1)
        layout.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#f1f5f9; max-height:1px;")
        layout.addWidget(sep)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"font-size:{font(13)}px; color:#334155;")
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(10))

        no_btn = QPushButton(no_text)
        no_btn.setFixedHeight(s(42))
        no_btn.setStyleSheet(
            f"QPushButton{{background:#f1f5f9;color:#64748b;font-weight:700;"
            f"border-radius:{s(10)}px;border:none;}}"
            f"QPushButton:hover{{background:#e2e8f0;}}"
        )
        no_btn.clicked.connect(self.reject)

        yes_btn = QPushButton(yes_text)
        yes_btn.setFixedHeight(s(42))
        yes_btn.setStyleSheet(
            f"QPushButton{{background:{yes_color};color:white;font-weight:700;"
            f"border-radius:{s(10)}px;border:none;}}"
            f"QPushButton:hover{{opacity:0.9;}}"
        )
        yes_btn.clicked.connect(self._on_yes)

        btn_row.addWidget(no_btn, 1)
        btn_row.addWidget(yes_btn, 1)
        layout.addLayout(btn_row)

    def _on_yes(self):
        self.result_accepted = True
        self.accept()
