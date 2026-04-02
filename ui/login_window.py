"""Login oynasi — faqat 4 xonali PIN orqali kirish.
Credentials (.env da) admin tomonidan sozlanadi.
Dizayn: Markazlashtirilgan — logo, dots, numpad.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QThread
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QBrush

from core.api import FrappeAPI
from core.config import load_config, save_pin, verify_pin, has_pin
from core.logger import get_logger
from ui.scale import s, font

logger = get_logger(__name__)


# ── Stil ──────────────────────────────────────────────────
_DOT_SIZE = 18
_BTN_SIZE = 72


def _dot_style(filled: bool) -> str:
    r = s(_DOT_SIZE // 2)
    sz = s(_DOT_SIZE)
    if filled:
        return (
            f"background: #60a5fa; border-radius: {r}px;"
            f" min-width: {sz}px; min-height: {sz}px;"
            f" max-width: {sz}px; max-height: {sz}px;"
        )
    return (
        f"background: transparent; border: 2px solid rgba(255,255,255,0.3);"
        f" border-radius: {r}px;"
        f" min-width: {sz}px; min-height: {sz}px;"
        f" max-width: {sz}px; max-height: {sz}px;"
    )


def _btn_style():
    return f"""
        QPushButton {{
            background: rgba(255,255,255,0.07);
            color: white;
            font-size: {font(26)}px;
            font-weight: 600;
            border-radius: {s(_BTN_SIZE // 2)}px;
            border: 1.5px solid rgba(255,255,255,0.10);
            min-width: {s(_BTN_SIZE)}px; min-height: {s(_BTN_SIZE)}px;
            max-width: {s(_BTN_SIZE)}px; max-height: {s(_BTN_SIZE)}px;
        }}
        QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
        QPushButton:pressed {{
            background: rgba(96,165,250,0.3);
            border-color: #60a5fa;
        }}
    """


def _btn_clear_style():
    return f"""
        QPushButton {{
            background: rgba(239,68,68,0.12);
            color: #fca5a5;
            font-size: {font(20)}px; font-weight: 700;
            border-radius: {s(_BTN_SIZE // 2)}px;
            border: 1.5px solid rgba(239,68,68,0.2);
            min-width: {s(_BTN_SIZE)}px; min-height: {s(_BTN_SIZE)}px;
            max-width: {s(_BTN_SIZE)}px; max-height: {s(_BTN_SIZE)}px;
        }}
        QPushButton:pressed {{ background: rgba(239,68,68,0.25); }}
    """


def _btn_back_style():
    return f"""
        QPushButton {{
            background: rgba(255,255,255,0.04);
            color: rgba(255,255,255,0.5);
            font-size: {font(22)}px; font-weight: 600;
            border-radius: {s(_BTN_SIZE // 2)}px;
            border: 1.5px solid rgba(255,255,255,0.08);
            min-width: {s(_BTN_SIZE)}px; min-height: {s(_BTN_SIZE)}px;
            max-width: {s(_BTN_SIZE)}px; max-height: {s(_BTN_SIZE)}px;
        }}
        QPushButton:pressed {{ background: rgba(255,255,255,0.12); }}
    """


# ── Background auto-login ────────────────────────────────
class AutoLoginWorker(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        cfg = load_config()
        url, user, pwd, site = cfg.get("url",""), cfg.get("user",""), cfg.get("password",""), cfg.get("site","")
        if not (url and user and pwd):
            self.result_ready.emit(False, "Credentials topilmadi")
            return
        try:
            ok, msg = self.api.login(url, user, pwd, site)
            self.result_ready.emit(ok, msg)
        except Exception as e:
            self.result_ready.emit(False, str(e))


# ══════════════════════════════════════════════════════════
#  LoginWindow — markazlashtirilgan PIN ekrani
# ══════════════════════════════════════════════════════════
class LoginWindow(QWidget):
    login_successful = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self._api_ready = False
        self._digits = ""
        self._setup_first = ""
        self._setup_state = "verify_old"   # verify_old | enter_new | confirm_new
        self._mode = "enter"               # enter | setup

        self._build_ui()
        self._start_auto_login()

    # ── Gradient fon ─────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.0, QColor("#0a0f1e"))
        g.setColorAt(0.5, QColor("#0d1b3e"))
        g.setColorAt(1.0, QColor("#061029"))
        p.fillRect(self.rect(), QBrush(g))

    # ── UI ────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("Jazira POS — Kassir kirish")
        self.setMinimumSize(s(480), s(600))
        self.showMaximized()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Markaziy konteyner — vertikal
        col = QVBoxLayout()
        col.setSpacing(s(20))
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Logo
        logo = QLabel("🍽")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"font-size: {font(48)}px; background: transparent;")
        col.addWidget(logo)

        # Brand
        brand = QLabel("Jazira POS")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet(
            f"font-size: {font(26)}px; font-weight: 900; color: white;"
            f" letter-spacing: 4px; background: transparent;"
        )
        col.addWidget(brand)

        col.addSpacing(s(8))

        # Sarlavha
        self._title = QLabel("PIN kiriting")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            f"font-size: {font(18)}px; font-weight: 700; color: rgba(255,255,255,0.85);"
            f" background: transparent;"
        )
        col.addWidget(self._title)

        # 4 dot
        dots_row = QHBoxLayout()
        dots_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dots_row.setSpacing(s(18))
        self._dots = []
        for _ in range(4):
            d = QLabel()
            d.setFixedSize(s(_DOT_SIZE), s(_DOT_SIZE))
            d.setStyleSheet(_dot_style(False))
            self._dots.append(d)
            dots_row.addWidget(d)
        col.addLayout(dots_row)

        # Status / xato labeli
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setFixedHeight(s(28))
        self._status.setStyleSheet(
            f"font-size: {font(13)}px; color: #fca5a5; background: transparent;"
        )
        col.addWidget(self._status)

        # Numpad
        col.addWidget(self._build_numpad())

        # PIN reset link
        self._link = QPushButton("PIN ni qayta o'rnatish")
        self._link.setStyleSheet(
            f"QPushButton {{ background: transparent; color: rgba(255,255,255,0.2);"
            f" font-size: {font(11)}px; border: none; text-decoration: underline; }}"
            f"QPushButton:hover {{ color: rgba(255,255,255,0.45); }}"
        )
        self._link.clicked.connect(self._goto_setup)
        col.addWidget(self._link, alignment=Qt.AlignmentFlag.AlignCenter)

        root.addLayout(col)

        # Boshlang'ich holat
        if has_pin():
            self._set_mode_enter()
        else:
            self._set_mode_setup_new()

    # ── Numpad ────────────────────────────────────────────
    def _build_numpad(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(w)
        grid.setSpacing(s(10))
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        rows = [["7","8","9"], ["4","5","6"], ["1","2","3"], ["✕","0","⌫"]]
        for keys in rows:
            row = QHBoxLayout()
            row.setSpacing(s(10))
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            for k in keys:
                btn = QPushButton(k)
                if k == "✕":
                    btn.setStyleSheet(_btn_clear_style())
                elif k == "⌫":
                    btn.setStyleSheet(_btn_back_style())
                else:
                    btn.setStyleSheet(_btn_style())
                btn.clicked.connect(lambda _, key=k: self._on_key(key))
                row.addWidget(btn)
            grid.addLayout(row)
        return w

    # ── Numpad handler ────────────────────────────────────
    def _on_key(self, key: str):
        if key == "✕":
            self._digits = ""
        elif key == "⌫":
            self._digits = self._digits[:-1]
        elif len(self._digits) < 4:
            self._digits += key

        self._refresh_dots()
        self._status.setText("")

        if len(self._digits) == 4:
            QTimer.singleShot(100, self._on_complete)

    def _refresh_dots(self):
        for i, d in enumerate(self._dots):
            d.setStyleSheet(_dot_style(i < len(self._digits)))

    def _reset_input(self):
        self._digits = ""
        self._refresh_dots()

    # ── 4 raqam kiritilganda ─────────────────────────────
    def _on_complete(self):
        pin = self._digits
        self._reset_input()

        if self._mode == "enter":
            self._verify_pin(pin)
        else:
            self._handle_setup(pin)

    # ── PIN kirish ────────────────────────────────────────
    def _verify_pin(self, pin: str):
        if verify_pin(pin):
            logger.info("PIN tasdiqlandi")
            self.login_successful.emit()
            self.close()
        else:
            self._show_error("PIN noto'g'ri!")

    # ── PIN o'rnatish (3 bosqich) ─────────────────────────
    def _handle_setup(self, pin: str):
        if self._setup_state == "verify_old":
            if verify_pin(pin):
                self._setup_state = "enter_new"
                self._title.setText("Yangi PIN kiriting")
                self._show_status("Eski PIN tasdiqlandi ✅", "#86efac")
                QTimer.singleShot(800, lambda: self._status.setText(""))
            else:
                self._show_error("Eski PIN noto'g'ri!")

        elif self._setup_state == "enter_new":
            self._setup_first = pin
            self._setup_state = "confirm_new"
            self._title.setText("PIN ni tasdiqlang")
            self._show_status("Qayta kiriting", "#93c5fd")

        elif self._setup_state == "confirm_new":
            if pin == self._setup_first:
                save_pin(pin)
                logger.info("PIN o'rnatildi")
                self.login_successful.emit()
                self.close()
            else:
                self._setup_state = "enter_new"
                self._setup_first = ""
                self._title.setText("Yangi PIN kiriting")
                self._show_error("PIN mos kelmadi! Qaytadan kiriting")

    # ── Mode o'tkazish ────────────────────────────────────
    def _set_mode_enter(self):
        self._mode = "enter"
        self._digits = ""
        self._refresh_dots()
        self._title.setText("PIN kiriting")
        self._status.setText("")
        self._link.setText("PIN ni qayta o'rnatish")
        self._link.setVisible(True)
        self._link.clicked.disconnect()
        self._link.clicked.connect(self._goto_setup)

    def _set_mode_setup_new(self):
        """Birinchi marta PIN o'rnatish (eski PIN yo'q)."""
        self._mode = "setup"
        self._setup_state = "enter_new"
        self._setup_first = ""
        self._digits = ""
        self._refresh_dots()
        self._title.setText("PIN belgilang")
        self._status.setText("")
        self._link.setVisible(False)

    def _goto_setup(self):
        self._mode = "setup"
        self._setup_first = ""
        self._digits = ""
        self._refresh_dots()
        if has_pin():
            self._setup_state = "verify_old"
            self._title.setText("Eski PIN ni kiriting")
            self._show_status("Xavfsizlik uchun eski PINni kiriting", "#fbbf24")
        else:
            self._setup_state = "enter_new"
            self._title.setText("PIN belgilang")
            self._status.setText("")
        self._link.setText("Bekor qilish")
        self._link.setVisible(has_pin())
        self._link.clicked.disconnect()
        self._link.clicked.connect(self._set_mode_enter)

    # ── Yordamchi ─────────────────────────────────────────
    def _show_error(self, text: str):
        self._status.setStyleSheet(
            f"font-size: {font(13)}px; color: #fca5a5; background: transparent;"
        )
        self._status.setText(f"❌  {text}")
        QTimer.singleShot(1500, lambda: self._status.setText(""))

    def _show_status(self, text: str, color: str = "#93c5fd"):
        self._status.setStyleSheet(
            f"font-size: {font(13)}px; color: {color}; background: transparent;"
        )
        self._status.setText(text)

    # ── Background auto-login ─────────────────────────────
    def _start_auto_login(self):
        self._auto_worker = AutoLoginWorker(self.api)
        self._auto_worker.result_ready.connect(self._on_auto_login)
        self._auto_worker.start()

    def _on_auto_login(self, success: bool, message: str):
        self._api_ready = success
        if success:
            logger.info("Background auto-login muvaffaqiyatli")
            self.api.reload_settings()
        else:
            logger.warning("Background auto-login xatosi: %s", message)
            self._show_status("⚠  Server bilan aloqa yo'q", "#fbbf24")
