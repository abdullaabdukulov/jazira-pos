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
        self.setFixedSize(500, 450) # Window kengaytirildi

        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(15)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("Kassir kirishi")
        self.title_label.setStyleSheet("font-size: 26px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        config = load_config()
        default_url = config.get("url", "http://192.168.1.53:8000")
        default_site = config.get("site", "jazira.local")

        # Server URL
        layout.addWidget(QLabel("Server manzili (masalan: http://192.168.1.53:8000):"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://192.168.1.53:8000")
        self.url_input.setText(default_url)
        self.url_input.setStyleSheet("padding: 12px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(self.url_input)

        # Site Name (X-Frappe-Site-Name uchun)
        layout.addWidget(QLabel("Sayt nomi (Multi-site uchun):"))
        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText("jazira.local")
        self.site_input.setText(default_site)
        self.site_input.setStyleSheet("padding: 12px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(self.site_input)

        # User Login
        layout.addWidget(QLabel("Kassir logini (Email):"))
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("kassa@jazira.uz")
        self.user_input.setStyleSheet("padding: 12px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(self.user_input)

        # Password
        layout.addWidget(QLabel("Parol:"))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Parol")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet("padding: 12px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 5px;")
        layout.addWidget(self.password_input)

        # Login Button
        self.login_btn = QPushButton("KIRISH")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet("""
            QPushButton {
                padding: 15px; background-color: #2563eb; color: white; 
                font-weight: bold; border-radius: 5px; font-size: 16px;
                margin-top: 10px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #94a3b8; }
        """)
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        self.setLayout(layout)

    def handle_login(self):
        url = self.url_input.text().strip()
        site = self.site_input.text().strip()
        user = self.user_input.text().strip()
        password = self.password_input.text().strip()

        if not url or not user or not password:
            QMessageBox.warning(self, "Xatolik", "Barcha maydonlarni to'ldiring!")
            return

        # URL validation
        if not url.startswith("http"):
            url = "http://" + url

        self.login_btn.setText("Kirilmoqda...")
        self.login_btn.setEnabled(False)

        # Attempt login with Site Name
        success, message = self.api.login(url, user, password, site)

        if success:
            # Persist credentials including site
            save_credentials(url, user, password, site)
            save_config({"url": url, "site": site})
            self.api.reload_config()
            
            logger.info("Login muvaffaqiyatli: %s (Site: %s, User: %s)", url, site, user)
            self.login_successful.emit()
            self.close()
        else:
            QMessageBox.critical(self, "Xatolik", f"Tizimga kirishda xato:\n{message}")
            self.login_btn.setText("KIRISH")
            self.login_btn.setEnabled(True)
