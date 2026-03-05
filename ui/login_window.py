from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PyQt6.QtCore import pyqtSignal, Qt
from core.api import FrappeAPI
from core.config import save_config

class LoginWindow(QWidget):
    login_successful = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.api = FrappeAPI()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Ury POS - Login')
        self.setFixedSize(400, 300)

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("Tizimga kirish (Ury POS)")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(self.title_label)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Frappe URL (misol: https://erp.example.com)")
        layout.addWidget(self.url_input)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("API Key")
        layout.addWidget(self.api_key_input)

        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText("API Secret")
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_secret_input)

        self.login_btn = QPushButton("Kirish")
        self.login_btn.setStyleSheet("padding: 10px; background-color: #4CAF50; color: white; font-weight: bold;")
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        self.setLayout(layout)

    def handle_login(self):
        url = self.url_input.text().strip()
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()

        if not url or not api_key or not api_secret:
            QMessageBox.warning(self, "Xatolik", "Barcha maydonlarni to'ldiring!")
            return

        self.login_btn.setText("Kutilmoqda...")
        self.login_btn.setEnabled(False)

        # In a real app this should be in a QThread to avoid freezing UI
        success, message = self.api.ping(url, api_key, api_secret)

        if success:
            save_config({
                "url": url,
                "api_key": api_key,
                "api_secret": api_secret
            })
            self.login_successful.emit()
            self.close()
        else:
            QMessageBox.critical(self, "Xatolik", f"Ulanishda xatolik yuz berdi:\\n{message}")
            self.login_btn.setText("Kirish")
            self.login_btn.setEnabled(True)
