import sys
import os
import signal
import traceback
import faulthandler
faulthandler.enable()

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox
from core.api import FrappeAPI
from core.logger import get_logger
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

        windows["main"] = MainWindow(shared_api)
        windows["main"].showMaximized()

    if not shared_api.is_configured():
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Tizim sozlanmagan")
        msg.setText(".env fayli topilmadi yoki to'liq emas.\n\nAdmin FRAPPE_URL, FRAPPE_USER, FRAPPE_PASSWORD ni sozlashi kerak.")
        msg.exec()
        sys.exit(1)

    # Har doim PIN ekrani — kassir har safar PIN kiritishi shart
    show_login()

    logger.info("Ilova ishga tushdi")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
