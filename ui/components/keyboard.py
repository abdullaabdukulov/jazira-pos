"""TouchKeyboard — sensorli ekran uchun elite klaviatura dialogi."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLineEdit, QWidget, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont
from ui.scale import s, font


# ── Elite palette ─────────────────────────────────────
_GOLD = "#c89968"
_SLATE_900 = "#0f172a"
_SLATE_800 = "#1e293b"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748b"
_SLATE_400 = "#94a3b8"
_SLATE_300 = "#cbd5e1"
_SLATE_200 = "#e2e8f0"
_SLATE_100 = "#f1f5f9"
_SLATE_50 = "#f8fafc"
_EMERALD_600 = "#059669"
_EMERALD_700 = "#047857"
_RED_700 = "#b91c1c"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"


class TouchKeyboard(QDialog):
    text_confirmed = pyqtSignal(str)
    text_changed = pyqtSignal(str)

    def __init__(self, parent=None, initial_text="", title="Matn kiriting",
                 is_numeric=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(s(900), s(500))
        self.setModal(False)
        self.setStyleSheet(f"background: white;")
        self.is_numeric = is_numeric
        self._caps = False
        self._letter_buttons = []
        self.init_ui(initial_text)

    def init_ui(self, initial_text):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(24), s(20), s(24), s(20))
        layout.setSpacing(s(14))

        # 1. Display
        self.input_field = QLineEdit(initial_text)
        self.input_field.setFixedHeight(s(58))
        input_font = QFont()
        input_font.setPixelSize(font(22))
        input_font.setWeight(QFont.Weight.DemiBold)
        self.input_field.setFont(input_font)
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: white;
                color: {_SLATE_900};
                border: 1px solid {_SLATE_200};
                border-radius: {s(12)}px;
                padding: 0 {s(16)}px;
                selection-background-color: #fff7ed;
                selection-color: {_GOLD};
                outline: none;
            }}
            QLineEdit:focus {{
                border: 1px solid {_GOLD};
            }}
        """)
        self.input_field.textChanged.connect(lambda t: self.text_changed.emit(t))
        layout.addWidget(self.input_field)

        # 2. Keypad Area
        self.keys_widget = QWidget()
        self.keys_widget.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.keys_widget)
        self.grid.setSpacing(s(7))
        self.grid.setContentsMargins(0, 0, 0, 0)

        if self.is_numeric:
            self.setup_numeric_layout()
        else:
            self.setup_full_layout()

        layout.addWidget(self.keys_widget)

        # 3. Footer
        footer = QHBoxLayout()
        footer.setSpacing(s(10))

        btn_cancel = QPushButton("YOPISH")
        btn_cancel.setFixedHeight(s(56))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {_SLATE_700};
                font-weight: 700;
                font-size: {font(13)}px;
                letter-spacing: 1.5px;
                border-radius: {s(12)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        btn_cancel.clicked.connect(self.close)

        btn_ok = QPushButton("TASDIQLASH")
        btn_ok.setFixedHeight(s(56))
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {_EMERALD_600};
                color: white;
                font-weight: 800;
                font-size: {font(15)}px;
                letter-spacing: 2px;
                border-radius: {s(12)}px;
                border: 1px solid {_EMERALD_600};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_EMERALD_700};
                border-color: {_EMERALD_700};
            }}
            QPushButton:pressed {{ background: #065f46; }}
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
            'CLEAR', '0', '⌫',
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
        elif text == 'CAPS': display_text = "Aa"

        btn = QPushButton(display_text)
        btn.setMinimumHeight(s(60))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Default — letter/digit key
        base = f"""
            QPushButton {{
                background: white;
                border: 1px solid {_SLATE_200};
                border-radius: {s(10)}px;
                font-size: {font(17)}px;
                font-weight: 700;
                color: {_SLATE_900};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """

        if text == '⌫':
            base = f"""
                QPushButton {{
                    background: white;
                    border: 1px solid {_RED_200};
                    color: {_RED_700};
                    border-radius: {s(10)}px;
                    font-size: {font(17)}px;
                    font-weight: 700;
                    outline: none;
                }}
                QPushButton:hover {{
                    background: {_RED_50};
                    border-color: #fca5a5;
                }}
                QPushButton:pressed {{ background: #fee2e2; }}
            """
        elif text == 'CLEAR':
            base = f"""
                QPushButton {{
                    background: white;
                    border: 1px solid {_SLATE_200};
                    color: {_SLATE_500};
                    border-radius: {s(10)}px;
                    font-size: {font(11)}px;
                    font-weight: 800;
                    letter-spacing: 1.5px;
                    outline: none;
                }}
                QPushButton:hover {{
                    background: {_SLATE_50};
                    border-color: {_SLATE_300};
                    color: {_SLATE_900};
                }}
                QPushButton:pressed {{ background: {_SLATE_100}; }}
            """
        elif text == 'CAPS':
            base = f"""
                QPushButton {{
                    background: white;
                    border: 1px solid {_SLATE_200};
                    color: {_SLATE_700};
                    border-radius: {s(10)}px;
                    font-size: {font(14)}px;
                    font-weight: 800;
                    outline: none;
                }}
                QPushButton:hover {{
                    background: {_SLATE_50};
                    border-color: {_SLATE_300};
                    color: {_SLATE_900};
                }}
                QPushButton:pressed {{ background: {_SLATE_100}; }}
            """
        elif text == 'SPACE':
            base = f"""
                QPushButton {{
                    background: white;
                    border: 1px solid {_SLATE_200};
                    color: {_SLATE_700};
                    border-radius: {s(10)}px;
                    font-size: {font(11)}px;
                    font-weight: 800;
                    letter-spacing: 2px;
                    outline: none;
                }}
                QPushButton:hover {{
                    background: {_SLATE_50};
                    border-color: {_SLATE_300};
                    color: {_SLATE_900};
                }}
                QPushButton:pressed {{ background: {_SLATE_100}; }}
            """
            btn.setMinimumWidth(s(200))

        btn.setStyleSheet(base)
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
