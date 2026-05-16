"""Ofitsant offline blok ekrani — Desktop POS Phase 2 (TZ 4.7).

Ofitsant rolida tarmoq uzilganda to'liq ekran modal overlay ko'rsatiladi.
Ofitsant offline rejimida zakaz urolmaydi; mijoz kassirga yo'naltiriladi.

UI tuzilmasi:
    📡 ❌
    Tarmoq bilan aloqa yo'q
    Iltimos, mijozni kassaga yuboring.
    Tarmoq tiklangach avto ochiladi.
    [⟳ Qayta urinish]    [📞 Yordam]
    Tekshirilmoqda... N sek o'tdi
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QDialog, QTextEdit,
)

from core.logger import get_logger
from ui.scale import s, font

logger = get_logger(__name__)


class OfflineBlockOverlay(QWidget):
    """To'liq ekran modal overlay. Parent oynasiga (MainWindow) joylashtirilganda
    butun bo'ylab cho'ziladi.

    Signals:
        retry_requested: foydalanuvchi "Qayta urinish" tugmasini bossadi
    """

    retry_requested = pyqtSignal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._elapsed_sec = 0
        self._debug_info_provider = None  # callable() → str
        self._init_ui()

        # Vaqt hisoblagich (har sek yangilanadi)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    # ── UI ────────────────────────────────────────────────
    def _init_ui(self):
        # Klik o'tib ketmasin (ostidagi widgetlarga)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "OfflineBlockOverlay { background: rgba(15, 23, 42, 0.96); }"
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Tarkib markazlashgan ramka
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("blockCard")
        card.setStyleSheet(f"""
            #blockCard {{
                background: #0b1220;
                border: 2px solid #1e293b;
                border-radius: {s(20)}px;
                padding: {s(40)}px {s(60)}px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(s(18))
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("📡 ❌")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: {font(64)}px; background: transparent;")
        card_layout.addWidget(icon_lbl)

        title = QLabel("Tarmoq bilan aloqa yo'q")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: {font(28)}px; font-weight: 900; color: white;"
            f" letter-spacing: 1px; background: transparent;"
        )
        card_layout.addWidget(title)

        msg = QLabel(
            "Iltimos, mijozni kassaga yuboring.\n"
            "Kassir to'g'ridan-to'g'ri zakazni qabul qiladi.\n\n"
            "Tarmoq tiklangach bu oyna avto yopiladi."
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(
            f"font-size: {font(15)}px; color: #cbd5e1; background: transparent;"
            f" line-height: 1.6;"
        )
        card_layout.addWidget(msg)

        # Tugmalar
        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(14))

        self.retry_btn = QPushButton("⟳  Qayta urinish")
        self.retry_btn.setFixedHeight(s(56))
        self.retry_btn.setMinimumWidth(s(200))
        self.retry_btn.setStyleSheet(f"""
            QPushButton {{
                background: #3b82f6; color: white;
                font-size: {font(15)}px; font-weight: 800;
                padding: 0 {s(28)}px; border: none;
                border-radius: {s(12)}px;
            }}
            QPushButton:hover {{ background: #2563eb; }}
            QPushButton:pressed {{ background: #1d4ed8; }}
        """)
        self.retry_btn.clicked.connect(self._on_retry)
        btn_row.addWidget(self.retry_btn)

        self.help_btn = QPushButton("📞  Yordam (admin)")
        self.help_btn.setFixedHeight(s(56))
        self.help_btn.setMinimumWidth(s(200))
        self.help_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: #94a3b8;
                font-size: {font(14)}px; font-weight: 700;
                padding: 0 {s(28)}px; border: 1.5px solid #475569;
                border-radius: {s(12)}px;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.05); color: #cbd5e1; }}
        """)
        self.help_btn.clicked.connect(self._on_help)
        btn_row.addWidget(self.help_btn)

        card_layout.addLayout(btn_row)

        # Status (kuzatuv vaqti)
        self._status = QLabel("Tekshirilmoqda...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            f"font-size: {font(12)}px; color: #64748b; background: transparent;"
            f" margin-top: {s(8)}px;"
        )
        card_layout.addWidget(self._status)

        outer.addWidget(card)

    # ── Public ────────────────────────────────────────────
    def set_debug_info_provider(self, fn):
        """`fn()` → str — debug ma'lumotlar matni (yordam dialogi uchun)."""
        self._debug_info_provider = fn

    def show_overlay(self):
        if self.parent():
            self.setGeometry(self.parent().rect())
        self._elapsed_sec = 0
        self._update_status()
        self._timer.start()
        self.raise_()
        self.show()
        self.setFocus()

    def hide_overlay(self):
        self._timer.stop()
        self.hide()

    # ── Internal ──────────────────────────────────────────
    def _on_tick(self):
        self._elapsed_sec += 1
        self._update_status()

    def _update_status(self):
        self._status.setText(f"Tekshirilmoqda... {self._elapsed_sec} sek o'tdi")

    def _on_retry(self):
        self.retry_btn.setEnabled(False)
        self.retry_btn.setText("Tekshirilmoqda...")
        self.retry_requested.emit()
        # 2 sek dan keyin tugmani qayta yoqamiz (UX uchun)
        QTimer.singleShot(2000, self._restore_retry_btn)

    def _restore_retry_btn(self):
        self.retry_btn.setEnabled(True)
        self.retry_btn.setText("⟳  Qayta urinish")

    def _on_help(self):
        text = "Tarmoq sozlamalarini administrator bilan tekshiring."
        if self._debug_info_provider:
            try:
                debug = self._debug_info_provider()
                text = f"{text}\n\nDiagnostika:\n{debug}"
            except Exception as e:
                logger.debug("Debug info provider xatosi: %s", e)
        dlg = _HelpDialog(self, text)
        dlg.exec()

    # ── Eventlar — ESC/keyboard ni bloklash ───────────────
    def keyPressEvent(self, e):
        # ESC ni o'tkazib yubormaymiz, focus chiqib ketmasin
        e.accept()

    def resizeEvent(self, e):
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(e)


class _HelpDialog(QDialog):
    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle("Yordam — tarmoq diagnostikasi")
        self.setMinimumSize(s(520), s(360))
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(20), s(20), s(20), s(20))
        layout.setSpacing(s(12))

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(text)
        body.setStyleSheet(f"""
            QTextEdit {{
                font-family: monospace; font-size: {font(12)}px;
                border: 1px solid #e2e8f0; border-radius: {s(8)}px;
                padding: {s(10)}px;
            }}
        """)
        layout.addWidget(body)

        close_btn = QPushButton("Yopish")
        close_btn.setFixedHeight(s(40))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: #1e293b; color: white;
                font-weight: 700; font-size: {font(13)}px;
                border-radius: {s(8)}px; border: none;
                padding: 0 {s(20)}px;
            }}
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)
