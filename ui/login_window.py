from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QCheckBox,
)
from PyQt6.QtCore import pyqtSignal, Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QFont
from core.api import FrappeAPI
from core.config import save_credentials, load_config
from core.logger import get_logger
from ui.components.dialogs import InfoDialog

logger = get_logger(__name__)


class LoginWindow(QWidget):
    login_successful = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("URY POS — Kirish")
        self.setMinimumSize(480, 600)
        self.showMaximized()

        # ——— Asosiy fon ———
        self.setStyleSheet("""
            QWidget#loginBg {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f172a, stop:0.5 #1e293b, stop:1 #0f172a
                );
            }
        """)
        self.setObjectName("loginBg")

        # ——— Markaziy karta ———
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("loginCard")
        card.setFixedWidth(420)
        card.setStyleSheet("""
            QFrame#loginCard {
                background: white;
                border-radius: 20px;
                border: 1px solid #e2e8f0;
            }
        """)

        # Soya effekti
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 60))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(0)

        # ——— Logo / Branding ———
        logo = QLabel("🍽")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 48px; margin-bottom: 4px; background: transparent;")
        layout.addWidget(logo)

        title = QLabel("URY POS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("""
            font-size: 26px; font-weight: 900; color: #0f172a;
            letter-spacing: 2px; margin-bottom: 2px; background: transparent;
        """)
        layout.addWidget(title)

        subtitle = QLabel("Kassir tizimiga kirish")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("""
            font-size: 13px; color: #94a3b8; margin-bottom: 20px; background: transparent;
        """)
        layout.addWidget(subtitle)

        # ——— Separator ———
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #f1f5f9; max-height: 1px; margin-bottom: 16px;")
        layout.addWidget(sep)

        # ——— Formalar ———
        config = load_config()
        default_url = config.get("url", "")

        INPUT_STYLE = """
            QLineEdit {
                padding: 12px 14px;
                font-size: 14px;
                border: 1.5px solid #e2e8f0;
                border-radius: 10px;
                background: #f8fafc;
                color: #1e293b;
            }
            QLineEdit:focus {
                border: 1.5px solid #3b82f6;
                background: #ffffff;
            }
            QLineEdit:disabled {
                background: #f1f5f9;
                color: #94a3b8;
            }
        """

        LABEL_STYLE = """
            font-size: 12px; font-weight: 700; color: #64748b;
            margin-bottom: 4px; margin-top: 10px; background: transparent;
        """

        # Server URL
        layout.addWidget(self._label("Server manzili", LABEL_STYLE))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("masalan: http://192.168.1.53:8000")
        self.url_input.setText(default_url)
        self.url_input.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self.url_input)

        # Login (Email)
        layout.addWidget(self._label("Email yoki Login", LABEL_STYLE))
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("cashier@example.uz")
        self.user_input.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self.user_input)

        # Parol
        layout.addWidget(self._label("Parol", LABEL_STYLE))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("••••••••")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet(INPUT_STYLE)
        self.password_input.returnPressed.connect(self._handle_login)
        layout.addWidget(self.password_input)

        # ——— Kengaytirilgan sozlamalar (Site name) ———
        self.advanced_toggle = QCheckBox("Kengaytirilgan sozlamalar")
        self.advanced_toggle.setStyleSheet("""
            QCheckBox {
                font-size: 12px; color: #94a3b8; margin-top: 12px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 14px; height: 14px; border-radius: 3px;
                border: 1.5px solid #cbd5e1;
            }
            QCheckBox::indicator:checked {
                background: #3b82f6; border-color: #3b82f6;
            }
        """)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle)

        # Site name (yashirin)
        self.site_frame = QFrame()
        self.site_frame.setVisible(False)
        self.site_frame.setStyleSheet("background: transparent;")
        site_layout = QVBoxLayout(self.site_frame)
        site_layout.setContentsMargins(0, 0, 0, 0)
        site_layout.setSpacing(2)

        site_hint = QLabel("Multi-site bench uchun (ixtiyoriy)")
        site_hint.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent;")
        site_layout.addWidget(site_hint)

        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText("sayt nomi (masalan: mysite.local)")
        self.site_input.setText(config.get("site", ""))
        self.site_input.setStyleSheet(INPUT_STYLE)
        site_layout.addWidget(self.site_input)
        layout.addWidget(self.site_frame)

        # ——— Xatolik xabari ———
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.error_label.setStyleSheet("""
            font-size: 12px; color: #dc2626; background: #fef2f2;
            border: 1px solid #fecaca; border-radius: 8px;
            padding: 8px 12px; margin-top: 10px;
        """)
        layout.addWidget(self.error_label)

        # ——— Login tugma ———
        self.login_btn = QPushButton("KIRISH")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setFixedHeight(48)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2563eb, stop:1 #3b82f6
                );
                color: white;
                font-weight: 800;
                font-size: 15px;
                border-radius: 12px;
                border: none;
                letter-spacing: 1px;
                margin-top: 16px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1d4ed8, stop:1 #2563eb
                );
            }
            QPushButton:pressed {
                background: #1e40af;
            }
            QPushButton:disabled {
                background: #cbd5e1;
                color: #94a3b8;
            }
        """)
        self.login_btn.clicked.connect(self._handle_login)
        layout.addWidget(self.login_btn)

        # ——— Pastki yozuv ———
        footer = QLabel("Ury Restaurant POS v1.0")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("""
            font-size: 11px; color: #cbd5e1; margin-top: 14px; background: transparent;
        """)
        layout.addWidget(footer)

        outer.addWidget(card)

    # ─── Helpers ─────────────────────────────────────────
    @staticmethod
    def _label(text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _toggle_advanced(self, checked: bool):
        self.site_frame.setVisible(checked)

    def _show_error(self, msg: str):
        self.error_label.setText(f"⚠  {msg}")
        self.error_label.setVisible(True)

    def _hide_error(self):
        self.error_label.setVisible(False)

    # ─── Login handler ───────────────────────────────────
    def _handle_login(self):
        self._hide_error()

        url = self.url_input.text().strip()
        user = self.user_input.text().strip()
        password = self.password_input.text().strip()
        site = self.site_input.text().strip() if self.advanced_toggle.isChecked() else ""

        # Validatsiya
        if not url:
            self._show_error("Server manzilini kiriting!")
            self.url_input.setFocus()
            return
        if not user:
            self._show_error("Email yoki loginni kiriting!")
            self.user_input.setFocus()
            return
        if not password:
            self._show_error("Parolni kiriting!")
            self.password_input.setFocus()
            return

        # http:// avtomatik qo'shish
        if not url.startswith("http"):
            url = "http://" + url

        # UI holati
        self.login_btn.setText("⏳  Kirilmoqda...")
        self.login_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        self.user_input.setEnabled(False)
        self.password_input.setEnabled(False)

        # Login so'rovi
        try:
            success, message = self.api.login(url, user, password, site)
        except Exception as e:
            logger.error("Login xatosi: %s", e)
            success, message = False, f"Kutilmagan xatolik: {e}"

        if success:
            save_credentials(url, user, password, site)
            self.api.reload_config()
            logger.info("Login muvaffaqiyatli: %s (User: %s)", url, user)
            self.login_successful.emit()
            self.close()
        else:
            # Xatolik xabarini foydalanuvchiga tushunarli qilish
            if "aloqa" in message.lower() or "connection" in message.lower():
                friendly = "Serverga ulanib bo'lmadi.\nServer manzilini tekshiring yoki internet ulanishini tekshiring."
            elif "noto'g'ri" in message.lower() or "incorrect" in message.lower():
                friendly = "Login yoki parol noto'g'ri.\nIltimos, qayta tekshirib ko'ring."
            elif "timeout" in message.lower():
                friendly = "Server javob bermadi.\nInternet ulanishini yoki server manzilini tekshiring."
            else:
                friendly = message

            self._show_error(friendly)
            self._reset_form()

    def _reset_form(self):
        self.login_btn.setText("KIRISH")
        self.login_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self.user_input.setEnabled(True)
        self.password_input.setEnabled(True)
