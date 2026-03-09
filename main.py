import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from core.api import FrappeAPI
from core.logger import get_logger
from core.config import clear_credentials
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from ui.styles import GLOBAL_STYLE

logger = get_logger(__name__)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLE)

    api = FrappeAPI()

    # We use a list to hold window references so we can recreate them
    windows = {"main": None, "login": None}

    def show_login():
        if windows["main"]:
            windows["main"].close()
            windows["main"] = None
        
        windows["login"] = LoginWindow()
        windows["login"].login_successful.connect(show_main)
        windows["login"].show()

    def show_main():
        if windows["login"]:
            windows["login"].close()
            windows["login"] = None
            
        windows["main"] = MainWindow()
        windows["main"].logout_requested.connect(handle_logout)
        windows["main"].show()

    def handle_logout():
        logger.info("Foydalanuvchi tizimdan chiqdi")
        clear_credentials()
        # Reset API configuration state
        api.reload_config()
        show_login()

    if api.is_configured():
        show_main()
    else:
        show_login()

    logger.info("Ilova ishga tushdi")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
