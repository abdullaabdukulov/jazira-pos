from PyQt6.QtWidgets import QWidget, QGridLayout, QPushButton, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, QSize

class TouchNumpad(QWidget):
    digit_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(8) # Space between buttons
        layout.setContentsMargins(0, 0, 0, 0)

        # Standard 3x4 Numpad layout
        buttons = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('C', 3, 0), ('0', 3, 1), ('.', 3, 2),
            ('BACK', 4, 0, 1, 3) # Span 3 columns
        ]

        for b in buttons:
            text = b[0]
            btn = QPushButton()
            
            if text == 'BACK':
                btn.setText("⌫ O'CHIRISH")
                btn.setObjectName("backspace")
            else:
                btn.setText(text)
            
            # Match width with Quick Amount buttons (100px)
            btn.setFixedHeight(60)
            btn.setMinimumWidth(100)
            
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d1d5db;
                    border-radius: 8px;
                    font-size: 20px;
                    font-weight: bold;
                    color: #1f2937;
                }
                QPushButton:pressed { background-color: #f3f4f6; }
                QPushButton#backspace { 
                    background-color: #fee2e2; 
                    color: #ef4444; 
                    font-size: 16px; 
                }
            """)
            
            btn.clicked.connect(lambda checked, t=text: self.on_btn_click(t))
            
            if len(b) == 3:
                layout.addWidget(btn, b[1], b[2])
            else:
                layout.addWidget(btn, b[1], b[2], b[3], b[4])

    def on_btn_click(self, text):
        action = text
        if text == 'BACK': action = 'BACKSPACE'
        elif text == 'C': action = 'CLEAR'
        self.digit_clicked.emit(action)
