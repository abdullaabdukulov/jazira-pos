"""Shared modern dialogs and widgets for the POS application.

Bitta standart, professional modal:
    InfoDialog    — success / warning / error / info (bitta "Tushunarli" tugma)
    ConfirmDialog — Ha / Yo'q tasdiqlash

Ikkalasi ham `_ModalBase` ustida quriladi: ramkasiz (frameless) yumaloq karta,
orqada xira fon (dim backdrop), yumshoq soya va yumshoq fade-in. Parent oyna
to'liq qoplanadi va karta markazda turadi.

    ClickableLineEdit — bosilganda signal chiqaradigan QLineEdit (numpad uchun)
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QLineEdit, QGraphicsDropShadowEffect, QApplication,
)
from PyQt6.QtCore import pyqtSignal, Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QPainter, QFont, QFontMetrics
from ui.scale import s, font

CARD_WIDTH = 460


# ── Yordamchilar ──────────────────────────────────────────────────────────
def _darken(hex_color: str, factor: float = 0.88) -> str:
    """Hex rangni `factor` ga qarab to'qlashtirish (hover/pressed uchun)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _solid_btn_css(bg: str, fg: str = "white") -> str:
    return (
        f"QPushButton{{background:{bg}; color:{fg}; font-weight:700;"
        f" font-size:{font(14)}px; border:none; border-radius:{s(11)}px;"
        f" padding:0 {s(22)}px;}}"
        f"QPushButton:hover{{background:{_darken(bg, 0.90)};}}"
        f"QPushButton:pressed{{background:{_darken(bg, 0.80)};}}"
    )


def _neutral_btn_css() -> str:
    return (
        f"QPushButton{{background:#f1f5f9; color:#475569; font-weight:700;"
        f" font-size:{font(14)}px; border:none; border-radius:{s(11)}px;"
        f" padding:0 {s(22)}px;}}"
        f"QPushButton:hover{{background:#e2e8f0;}}"
        f"QPushButton:pressed{{background:#cbd5e1;}}"
    )


class ClickableLineEdit(QLineEdit):
    """Bosilganda signal chiqaradigan QLineEdit — numpad bilan ishlash uchun."""
    clicked = pyqtSignal(object)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self)


# ── Modal asos ─────────────────────────────────────────────────────────────
class _ModalBase(QDialog):
    """Ramkasiz, markazlashgan karta + xira fon. Subklasslar `self.card_layout`
    ga kontent qo'shadi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setWindowOpacity(0.0)
        self._fade = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(s(40), s(40), s(40), s(40))
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = QFrame()
        self.card.setObjectName("modalCard")
        self.card.setFrameShape(QFrame.Shape.NoFrame)
        self.card.setFixedWidth(s(CARD_WIDTH))
        self.card.setStyleSheet(
            f"QFrame#modalCard{{background:#ffffff; border-radius:{s(18)}px;}}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(s(48))
        shadow.setColor(QColor(15, 23, 42, 90))
        shadow.setOffset(0, s(10))
        self.card.setGraphicsEffect(shadow)
        # Per-widget AlignCenter — karta kontentga sig'adi va markazda turadi
        # (layout.setAlignment yakka widgetni cho'zilishdan saqlamaydi).
        outer.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(s(26), s(24), s(26), s(22))
        self.card_layout.setSpacing(s(16))

    # Xira fon
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(15, 23, 42, 115))

    def showEvent(self, event):
        # Parent oynani (yoki ekranni) to'liq qoplaymiz
        par = self.parentWidget()
        if par is not None and par.window() is not None:
            self.setGeometry(par.window().geometry())
        else:
            scr = QApplication.primaryScreen()
            if scr is not None:
                self.setGeometry(scr.geometry())
        super().showEvent(event)
        # Yumshoq fade-in
        try:
            self._fade = QPropertyAnimation(self, b"windowOpacity")
            self._fade.setDuration(140)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade.start()
        except Exception:
            self.setWindowOpacity(1.0)

    # ── Umumiy sarlavha (badge + title) ──────────────────────────────────
    def _add_header(self, glyph: str, title: str,
                    accent: str, tint: str, border: str):
        row = QHBoxLayout()
        row.setSpacing(s(14))
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel(glyph)
        badge.setFixedSize(s(46), s(46))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"font-size:{font(22)}px; font-weight:800; color:{accent};"
            f"background:{tint}; border:1.5px solid {border};"
            f"border-radius:{s(23)}px;"
        )
        row.addWidget(badge)

        ttl = QLabel(title)
        ttl.setStyleSheet(
            f"font-size:{font(17)}px; font-weight:800;"
            f"color:#0f172a; background:transparent;"
        )
        ttl.setWordWrap(True)
        row.addWidget(ttl, 1)
        self.card_layout.addLayout(row)

    def _add_message(self, message: str):
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"font-size:{font(14)}px; color:#475569; background:transparent;"
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # QVBoxLayout wordWrap heightForWidth ni hisobga olmaydi — o'ralgan
        # matn balandligini eksplicit beramiz, aks holda uzun matn kesiladi.
        mf = QFont(msg.font())
        mf.setPixelSize(font(14))
        text_h = QFontMetrics(mf).boundingRect(
            0, 0, s(CARD_WIDTH) - s(56), 10000,
            int(Qt.TextFlag.TextWordWrap), message,
        ).height()
        msg.setMinimumHeight(max(s(40), text_h + s(4)))
        self.card_layout.addWidget(msg)


# ── Bildirishnoma ──────────────────────────────────────────────────────────
class InfoDialog(_ModalBase):
    """kind: 'success' | 'warning' | 'error' | 'info'

    `icon` berilsa, default belgisi o'rniga shu emoji ko'rsatiladi (masalan 🖨️).
    """
    _PALETTE = {
        "success": {"accent": "#16a34a", "tint": "#f0fdf4", "border": "#bbf7d0", "glyph": "✓"},
        "warning": {"accent": "#d97706", "tint": "#fffbeb", "border": "#fde68a", "glyph": "!"},
        "error":   {"accent": "#dc2626", "tint": "#fef2f2", "border": "#fecaca", "glyph": "✕"},
        "info":    {"accent": "#2563eb", "tint": "#eff6ff", "border": "#bfdbfe", "glyph": "i"},
    }

    def __init__(self, parent, title: str, message: str,
                 kind: str = "success", icon: str = None):
        super().__init__(parent)
        pal = self._PALETTE.get(kind, self._PALETTE["info"])
        glyph = icon if icon is not None else pal["glyph"]

        self._add_header(glyph, title, pal["accent"], pal["tint"], pal["border"])
        self._add_message(message)

        ok = QPushButton("Tushunarli")
        ok.setFixedHeight(s(46))
        ok.setMinimumWidth(s(150))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(_solid_btn_css(pal["accent"]))
        ok.clicked.connect(self.accept)
        ok.setDefault(True)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(ok)
        self.card_layout.addLayout(btn_row)


# ── Tasdiqlash ─────────────────────────────────────────────────────────────
class ConfirmDialog(_ModalBase):
    """Tasdiqlash dialogi — Ha / Yo'q. `.exec()` dan keyin `.result_accepted`."""

    def __init__(self, parent, title: str, message: str, icon: str = "⚠️",
                 yes_text: str = "Ha", no_text: str = "Yo'q",
                 yes_color: str = "#dc2626"):
        super().__init__(parent)
        self.result_accepted = False

        # Tasdiqlash — ehtiyotkorlik uchun amber aksent badge
        self._add_header(icon, title, "#d97706", "#fffbeb", "#fde68a")
        self._add_message(message)

        no_btn = QPushButton(no_text)
        no_btn.setFixedHeight(s(46))
        no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        no_btn.setStyleSheet(_neutral_btn_css())
        no_btn.clicked.connect(self.reject)

        yes_btn = QPushButton(yes_text)
        yes_btn.setFixedHeight(s(46))
        yes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        yes_btn.setStyleSheet(_solid_btn_css(yes_color))
        yes_btn.clicked.connect(self._on_yes)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(10))
        btn_row.addWidget(no_btn, 1)
        btn_row.addWidget(yes_btn, 1)
        self.card_layout.addLayout(btn_row)

    def _on_yes(self):
        self.result_accepted = True
        self.accept()
