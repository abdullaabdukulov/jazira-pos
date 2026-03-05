import sys
import os
from PyQt6.QtWidgets import QApplication

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.api import FrappeAPI
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from ui.styles import GLOBAL_STYLE

def main():
    app = QApplication(sys.path)
    
    # Apply global modern and clean stylesheet
    app.setStyleSheet(GLOBAL_STYLE)
    
    api = FrappeAPI()
    
    main_window = MainWindow()
    login_window = LoginWindow()
    
    def on_login_success():
        main_window.show()
        
    login_window.login_successful.connect(on_login_success)

    if api.is_configured():
        main_window.show()
    else:
        login_window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
