from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QScrollArea,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from core.api import FrappeAPI
from core.config import save_credentials, load_config
from core.logger import get_logger
from ui.components.dialogs import ClickableLineEdit

logger = get_logger(__name__)


class LoginWindow(QWidget):
    login_successful = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self._active_field = None
        self._caps = False
        self._letter_buttons = []
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

        # ——— Asosiy tuzilma: yuqori (karta) + pastki (keyboard) ———
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Yuqori qism: karta markazda ---
        top_area = QWidget()
        top_area.setStyleSheet("background: transparent;")
        top_layout = QVBoxLayout(top_area)
        top_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

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

        INPUT_ACTIVE_STYLE = """
            QLineEdit {
                padding: 12px 14px;
                font-size: 14px;
                border: 2px solid #3b82f6;
                border-radius: 10px;
                background: #ffffff;
                color: #1e293b;
            }
            QLineEdit:disabled {
                background: #f1f5f9;
                color: #94a3b8;
            }
        """

        self._input_style = INPUT_STYLE
        self._input_active_style = INPUT_ACTIVE_STYLE

        LABEL_STYLE = """
            font-size: 12px; font-weight: 700; color: #64748b;
            margin-bottom: 4px; margin-top: 10px; background: transparent;
        """

        # Server URL
        layout.addWidget(self._label("Server manzili", LABEL_STYLE))
        self.url_input = ClickableLineEdit()
        self.url_input.setPlaceholderText("masalan: http://192.168.1.53:8000")
        self.url_input.setText(default_url)
        self.url_input.setReadOnly(True)
        self.url_input.setStyleSheet(INPUT_STYLE)
        self.url_input.clicked.connect(lambda w: self._activate_field(w, "Server manzili"))
        layout.addWidget(self.url_input)

        # Login (Email)
        layout.addWidget(self._label("Email yoki Login", LABEL_STYLE))
        self.user_input = ClickableLineEdit()
        self.user_input.setPlaceholderText("cashier@example.uz")
        self.user_input.setReadOnly(True)
        self.user_input.setStyleSheet(INPUT_STYLE)
        self.user_input.clicked.connect(lambda w: self._activate_field(w, "Email yoki Login"))
        layout.addWidget(self.user_input)

        # Parol
        layout.addWidget(self._label("Parol", LABEL_STYLE))
        self.password_input = ClickableLineEdit()
        self.password_input.setPlaceholderText("••••••••")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setReadOnly(True)
        self.password_input.setStyleSheet(INPUT_STYLE)
        self.password_input.clicked.connect(lambda w: self._activate_field(w, "Parol"))
        layout.addWidget(self.password_input)

        # ——— Kengaytirilgan sozlamalar (Site name) ———
        self.advanced_toggle = QPushButton("Kengaytirilgan sozlamalar ▸")
        self.advanced_toggle.setFixedHeight(44)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setStyleSheet("""
            QPushButton {
                font-size: 12px; font-weight: 600; color: #94a3b8;
                background: transparent; border: none; margin-top: 8px;
                text-align: left; padding-left: 4px;
            }
            QPushButton:checked { color: #3b82f6; }
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

        self.site_input = ClickableLineEdit()
        self.site_input.setPlaceholderText("sayt nomi (masalan: mysite.local)")
        self.site_input.setText(config.get("site", ""))
        self.site_input.setReadOnly(True)
        self.site_input.setStyleSheet(INPUT_STYLE)
        self.site_input.clicked.connect(lambda w: self._activate_field(w, "Sayt nomi"))
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
        self.login_btn.setFixedHeight(56)
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

        top_layout.addWidget(card)
        root_layout.addWidget(top_area, stretch=1)

        # --- Pastki qism: inline keyboard ---
        self.keyboard_panel = self._build_keyboard_panel()
        self.keyboard_panel.setVisible(False)
        root_layout.addWidget(self.keyboard_panel)

    # ─── Inline Keyboard ──────────────────────────────────
    def _build_keyboard_panel(self):
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: #f1f5f9;
                border-top: 2px solid #cbd5e1;
            }
        """)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 10, 16, 12)
        panel_layout.setSpacing(6)

        # Yuqori qator: aktiv field nomi + display + yopish
        top_row = QHBoxLayout()

        self.kb_field_label = QLabel("")
        self.kb_field_label.setStyleSheet("""
            font-size: 12px; font-weight: 700; color: #3b82f6;
            background: transparent; padding: 0 4px;
        """)

        self.kb_display = QLabel("")
        self.kb_display.setStyleSheet("""
            font-size: 16px; font-weight: 600; color: #334155;
            background: white; border: 1.5px solid #3b82f6;
            border-radius: 8px; padding: 6px 12px;
        """)
        self.kb_display.setFixedHeight(40)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(44, 44)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #ef4444; color: white;
                font-weight: bold; font-size: 16px;
                border-radius: 8px; border: none;
            }
            QPushButton:pressed { background: #dc2626; }
        """)
        close_btn.clicked.connect(self._close_keyboard)

        top_row.addWidget(self.kb_field_label)
        top_row.addWidget(self.kb_display, stretch=1)
        top_row.addWidget(close_btn)
        panel_layout.addLayout(top_row)

        # Klaviatura qatorlari
        self._letter_buttons = []
        rows = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '⌫'],
            ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
            ['CAPS', 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'CLR'],
            ['Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', ' SPACE '],
            ['@', '-', '_', ':', '/', '#', '+', '='],
        ]
        for row_keys in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(5)
            for key in row_keys:
                btn = self._make_key(key)
                row_layout.addWidget(btn)
            panel_layout.addLayout(row_layout)

        return panel

    def _make_key(self, key):
        label = key.strip()
        if label == 'SPACE':
            label = 'PROBEL'
        elif label == 'CLR':
            label = 'TOZALASH'
        elif label == 'CAPS':
            label = '⇧ Aa'

        btn = QPushButton(label)
        btn.setFixedHeight(48)

        if key.strip() == '⌫':
            style = "background:#fee2e2; color:#ef4444; font-size:18px; font-weight:bold;"
        elif key.strip() == 'CLR':
            style = "background:#fff7ed; color:#ea580c; font-size:11px; font-weight:bold;"
        elif key.strip() == 'CAPS':
            style = "background:#e0e7ff; color:#4338ca; font-size:13px; font-weight:bold;"
        elif 'SPACE' in key:
            style = "background:#eff6ff; color:#3b82f6; font-size:13px; font-weight:bold;"
            btn.setMinimumWidth(120)
        elif key.strip().isdigit():
            style = "background:#e0e7ff; color:#3730a3; font-size:16px; font-weight:bold;"
        else:
            style = "background:white; color:#1e293b; font-size:15px; font-weight:600;"

        btn.setStyleSheet(f"""
            QPushButton {{
                {style}
                border: 1px solid #e2e8f0;
                border-radius: 7px;
            }}
            QPushButton:pressed {{ background: #dbeafe; }}
        """)
        btn.clicked.connect(lambda _, k=key.strip(): self._on_key(k))

        # Harf tugmalarini saqlash (caps uchun)
        if len(key.strip()) == 1 and key.strip().isalpha():
            self._letter_buttons.append(btn)

        return btn

    def _on_key(self, key):
        if key == 'CAPS':
            self._caps = not self._caps
            for btn in self._letter_buttons:
                txt = btn.text()
                btn.setText(txt.upper() if self._caps else txt.lower())
            return
        if not self._active_field:
            return
        current = self._active_field.text()
        if key == '⌫':
            new_text = current[:-1]
        elif key == 'CLR':
            new_text = ''
        elif key == 'SPACE':
            new_text = current + ' '
        else:
            char = key.lower() if not self._caps else key.upper()
            new_text = current + char
        self._active_field.setText(new_text)
        # Display yangilash — parol uchun yashirish
        if self._active_field == self.password_input:
            self.kb_display.setText('•' * len(new_text) if new_text else "")
        else:
            self.kb_display.setText(new_text)

    def _activate_field(self, widget, title: str):
        # Avvalgi field stilini qaytarish
        if self._active_field and self._active_field != widget:
            self._active_field.setStyleSheet(self._input_style)
        self._active_field = widget
        widget.setStyleSheet(self._input_active_style)
        self.kb_field_label.setText(title)
        # Display yangilash
        if widget == self.password_input:
            self.kb_display.setText('•' * len(widget.text()) if widget.text() else "")
        else:
            self.kb_display.setText(widget.text())
        self.keyboard_panel.setVisible(True)

    def _close_keyboard(self):
        if self._active_field:
            self._active_field.setStyleSheet(self._input_style)
            self._active_field = None
        self.keyboard_panel.setVisible(False)

    # ─── Helpers ─────────────────────────────────────────
    @staticmethod
    def _label(text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _toggle_advanced(self, checked: bool):
        self.site_frame.setVisible(checked)
        self.advanced_toggle.setText("Kengaytirilgan sozlamalar ▾" if checked else "Kengaytirilgan sozlamalar ▸")

    def _show_error(self, msg: str):
        self.error_label.setText(f"⚠  {msg}")
        self.error_label.setVisible(True)

    def _hide_error(self):
        self.error_label.setVisible(False)

    # ─── Login handler ───────────────────────────────────
    def _handle_login(self):
        self._close_keyboard()
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
