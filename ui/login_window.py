from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PyQt6.QtCore import pyqtSignal, Qt
from core.api import FrappeAPI
from core.config import save_config, save_credentials, load_config
from core.logger import get_logger

logger = get_logger(__name__)


class LoginWindow(QWidget):
    login_successful = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Ury POS - Cashier Login")
        self.setFixedSize(400, 380)

        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("Kassir kirishi")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        config = load_config()
        default_url = config.get("url", "https://jazira.erpcontrol.uz/")

        # Server URL
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.frappe.cloud")
        self.url_input.setText(default_url)
        self.url_input.setStyleSheet("padding: 10px; font-size: 14px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(QLabel("Server manzili:"))
        layout.addWidget(self.url_input)

        # User Login
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Email yoki Login")
        self.user_input.setStyleSheet("padding: 10px; font-size: 14px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(QLabel("Kassir logini:"))
        layout.addWidget(self.user_input)

        # Password
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Parol")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet("padding: 10px; font-size: 14px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(QLabel("Parol:"))
        layout.addWidget(self.password_input)

        # Login Button
        self.login_btn = QPushButton("KIRISH")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet("""
            QPushButton {
                padding: 12px; background-color: #2563eb; color: white; 
                font-weight: bold; border-radius: 5px; font-size: 14px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #94a3b8; }
        """)
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        self.setLayout(layout)

    def handle_login(self):
        url = self.url_input.text().strip()
        user = self.user_input.text().strip()
        password = self.password_input.text().strip()

        if not url or not user or not password:
            QMessageBox.warning(self, "Xatolik", "Barcha maydonlarni to'ldiring!")
            return

        # URL validation
        if not url.startswith("http"):
            url = "https://" + url

        self.login_btn.setText("Kirilmoqda...")
        self.login_btn.setEnabled(False)

        # Attempt session-based login
        success, message = self.api.login(url, user, password)

        if success:
            # Login successful. Attempt to fetch API Key for extra reliability (optional)
            api_key = ""
            try:
                # Get current logged user name
                s, current_user = self.api.call_method("frappe.auth.get_logged_user")
                if s:
                    # Get user document to see if api_key exists
                    s2, user_doc = self.api.call_method("frappe.client.get", {"doctype": "User", "name": current_user})
                    if s2 and isinstance(user_doc, dict):
                        api_key = user_doc.get("api_key", "")
            except Exception as e:
                logger.debug("Optional API key fetch failed: %s", e)

            # Persist credentials
            save_credentials(url, user, password)
            if api_key:
                # If we found an API key, we can append it to .env or handle it via save_credentials update
                # For now, session + user/pass is enough.
                pass

            save_config({"url": url})
            self.api.reload_config()
            
            logger.info("Login muvaffaqiyatli: %s (%s)", url, user)
            self.login_successful.emit()
            self.close()
        else:
            QMessageBox.critical(self, "Xatolik", f"Tizimga kirishda xato:\n{message}")
            self.login_btn.setText("KIRISH")
            self.login_btn.setEnabled(True)
