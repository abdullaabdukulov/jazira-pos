from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QPushButton, QLineEdit, QWidget, QFrame)
from PyQt6.QtCore import pyqtSignal, Qt, QSize

class TouchKeyboard(QDialog):
    text_confirmed = pyqtSignal(str)
    text_changed = pyqtSignal(str) # Emitted on every key press

    def __init__(self, parent=None, initial_text="", title="Matn kiriting", is_numeric=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(900, 500)
        self.setModal(False) # Allows interaction with parent (Item Grid)
        self.is_numeric = is_numeric
        self._caps = False
        self._letter_buttons = []
        self.init_ui(initial_text)

    def init_ui(self, initial_text):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 1. Text Display Area
        display_frame = QFrame()
        display_frame.setStyleSheet("background: white; border: 2px solid #3b82f6; border-radius: 10px;")
        display_layout = QVBoxLayout(display_frame)
        display_layout.setContentsMargins(5, 5, 5, 5)

        self.input_field = QLineEdit(initial_text)
        self.input_field.setStyleSheet("border: none; font-size: 26px; font-weight: bold; padding: 10px; color: #1f2937;")
        # Connect textChanged to our custom signal
        self.input_field.textChanged.connect(lambda t: self.text_changed.emit(t))
        display_layout.addWidget(self.input_field)
        layout.addWidget(display_frame)

        # 2. Keypad Area
        self.keys_widget = QWidget()
        self.grid = QGridLayout(self.keys_widget)
        self.grid.setSpacing(6)
        self.grid.setContentsMargins(0, 0, 0, 0)

        if self.is_numeric:
            self.setup_numeric_layout()
        else:
            self.setup_full_layout()

        layout.addWidget(self.keys_widget)

        # 3. Footer Actions
        footer = QHBoxLayout()
        btn_cancel = QPushButton("YOPISH")
        btn_cancel.setFixedHeight(60)
        btn_cancel.setStyleSheet("""
            QPushButton { background-color: #f3f4f6; color: #4b5563; font-weight: bold; border-radius: 10px; border: 1px solid #d1d5db; }
            QPushButton:pressed { background-color: #e5e7eb; }
        """)
        btn_cancel.clicked.connect(self.close)

        btn_ok = QPushButton("TASDIQLASH (OK)")
        btn_ok.setFixedHeight(60)
        btn_ok.setStyleSheet("""
            QPushButton { background-color: #10b981; color: white; font-weight: bold; border-radius: 10px; font-size: 18px; }
            QPushButton:pressed { background-color: #059669; }
        """)
        btn_ok.clicked.connect(self.confirm)

        footer.addWidget(btn_cancel, 1)
        footer.addWidget(btn_ok, 2)
        layout.addLayout(footer)

    def setup_numeric_layout(self):
        keys = [
            '7', '8', '9',
            '4', '5', '6',
            '1', '2', '3',
            'CLEAR', '0', '⌫'
        ]
        r, c = 0, 0
        for key in keys:
            btn = self.create_key(key)
            self.grid.addWidget(btn, r, c)
            c += 1
            if c > 2:
                c = 0
                r += 1

    def setup_full_layout(self):
        self._letter_buttons = []
        rows = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '⌫'],
            ['CAPS', 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'CLEAR'],
            ['Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', 'SPACE'],
            ['@', '-', '_', ':', '/', '#', '+', '='],
        ]
        for r_idx, row in enumerate(rows):
            for c_idx, key in enumerate(row):
                span = 1
                if key == 'SPACE': span = 3
                elif key in ['⌫', 'CLEAR', 'CAPS']: span = 2

                btn = self.create_key(key)
                self.grid.addWidget(btn, r_idx, c_idx, 1, span)

    def create_key(self, text):
        display_text = text
        if text == 'CLEAR': display_text = "TOZALASH"
        elif text == 'SPACE': display_text = "PROBEL"
        elif text == 'CAPS': display_text = "⇧ Aa"

        btn = QPushButton(display_text)
        btn.setMinimumHeight(65)

        style = """
            QPushButton {
                background-color: white;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
                color: #374151;
            }
            QPushButton:pressed { background-color: #f3f4f6; }
        """

        if text == '⌫':
            style += "QPushButton { background-color: #fee2e2; color: #ef4444; }"
        elif text == 'CLEAR':
            style += "QPushButton { background-color: #fff7ed; color: #ea580c; font-size: 14px; }"
        elif text == 'CAPS':
            style += "QPushButton { background-color: #e0e7ff; color: #4338ca; font-size: 16px; }"
        elif text == 'SPACE':
            style += "QPushButton { background-color: #eff6ff; color: #3b82f6; }"
            btn.setMinimumWidth(200)

        btn.setStyleSheet(style)
        btn.clicked.connect(lambda: self.on_key_pressed(text))

        if len(text) == 1 and text.isalpha():
            self._letter_buttons.append(btn)

        return btn

    def on_key_pressed(self, key):
        if key == 'CAPS':
            self._caps = not self._caps
            for btn in self._letter_buttons:
                txt = btn.text()
                btn.setText(txt.upper() if self._caps else txt.lower())
            return
        current = self.input_field.text()
        if key == '⌫':
            self.input_field.setText(current[:-1])
        elif key == 'CLEAR':
            self.input_field.clear()
        elif key == 'SPACE':
            self.input_field.setText(current + " ")
        else:
            char = key.lower() if not self._caps else key.upper()
            self.input_field.setText(current + char)

    def confirm(self):
        self.text_confirmed.emit(self.input_field.text())
        self.accept()
