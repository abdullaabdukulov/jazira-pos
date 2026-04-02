from PyQt6.QtWidgets import QWidget, QGridLayout, QPushButton
from PyQt6.QtCore import pyqtSignal
from ui.scale import s, font


class TouchNumpad(QWidget):
    digit_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(s(10))
        layout.setContentsMargins(0, 0, 0, 0)

        # Standard 3x4 + backspace layout
        buttons = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('C', 3, 0), ('0', 3, 1), ('.', 3, 2),
            ('BACK', 4, 0, 1, 3),   # Span 3 columns
        ]

        for b in buttons:
            text = b[0]
            btn = QPushButton()

            if text == 'BACK':
                btn.setText("⌫  O'CHIRISH")
                btn.setObjectName("backspace")
            elif text == 'C':
                btn.setText("C  Tozalash")
                btn.setObjectName("clear")
            else:
                btn.setText(text)

            # Touch-friendly: katta balandlik
            btn.setFixedHeight(s(68))
            btn.setMinimumWidth(s(80))

            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #ffffff;
                    border: 1.5px solid #d1d5db;
                    border-radius: {s(12)}px;
                    font-size: {font(22)}px;
                    font-weight: 700;
                    color: #1f2937;
                }}
                QPushButton:hover {{
                    background: #f0f9ff;
                    border-color: #3b82f6;
                    color: #1d4ed8;
                }}
                QPushButton:pressed {{
                    background: #dbeafe;
                    border-color: #2563eb;
                }}
                QPushButton#backspace {{
                    background: #fff1f2;
                    border-color: #fca5a5;
                    color: #dc2626;
                    font-size: {font(16)}px;
                    font-weight: 700;
                }}
                QPushButton#backspace:hover {{
                    background: #fee2e2;
                    border-color: #ef4444;
                }}
                QPushButton#backspace:pressed {{
                    background: #fecaca;
                }}
                QPushButton#clear {{
                    background: #fffbeb;
                    border-color: #fcd34d;
                    color: #b45309;
                    font-size: {font(14)}px;
                    font-weight: 700;
                }}
                QPushButton#clear:hover {{
                    background: #fef3c7;
                    border-color: #f59e0b;
                }}
                QPushButton#clear:pressed {{
                    background: #fde68a;
                }}
            """)

            btn.clicked.connect(lambda checked, t=text: self.on_btn_click(t))

            if len(b) == 3:
                layout.addWidget(btn, b[1], b[2])
            else:
                layout.addWidget(btn, b[1], b[2], b[3], b[4])

    def on_btn_click(self, text):
        action = text
        if text == 'BACK':
            action = 'BACKSPACE'
        elif text == 'C':
            action = 'CLEAR'
        self.digit_clicked.emit(action)