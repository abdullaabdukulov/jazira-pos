import sys
import os
import signal
import traceback
import faulthandler
faulthandler.enable()

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from core.api import FrappeAPI
from core.logger import get_logger
from core.config import clear_credentials
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from ui.styles import get_global_style

logger = get_logger(__name__)


# Uncaught exception handler — segfault dan oldin Python xatolarni ushlab olish
def _excepthook(exc_type, exc_value, exc_tb):
    logger.error("=== UNCAUGHT EXCEPTION ===")
    logger.error("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(get_global_style())

    # Bitta shared API instance yaratamiz
    shared_api = FrappeAPI()

    windows = {"main": None, "login": None}

    def show_login():
        if windows["main"]:
            windows["main"].close()
            windows["main"] = None
        
        # API instance'ni Login oynasiga beramiz
        windows["login"] = LoginWindow(shared_api)
        windows["login"].login_successful.connect(show_main)
        windows["login"].show()

    def show_main():
        if windows["login"]:
            windows["login"].close()
            windows["login"] = None
            
        # API instance'ni Asosiy oynaga beramiz
        windows["main"] = MainWindow(shared_api)
        windows["main"].logout_requested.connect(handle_logout)
        windows["main"].showMaximized()

    def handle_logout():
        logger.info("Foydalanuvchi tizimdan chiqdi")
        clear_credentials()
        shared_api.reload_config()
        show_login()

    if shared_api.is_configured():
        # Workerlardan OLDIN login qilish — cookie barcha threadlarga tarqaladi
        if shared_api.user and shared_api.password:
            success, msg = shared_api.login(
                shared_api.url, shared_api.user, shared_api.password, shared_api.site
            )
            if not success:
                logger.warning("Avtomatik login xatosi: %s — login oynasi ochiladi", msg)
                show_login()
                logger.info("Ilova ishga tushdi")
                sys.exit(app.exec())
        show_main()
    else:
        show_login()

    logger.info("Ilova ishga tushdi")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
