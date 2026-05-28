from PyQt6.QtWidgets import QWidget, QGridLayout, QPushButton
from PyQt6.QtCore import pyqtSignal, Qt
from ui.scale import s, font


# ── Elite palette ─────────────────────────────────────
_SLATE_900 = "#0f172a"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748b"
_SLATE_300 = "#cbd5e1"
_SLATE_200 = "#e2e8f0"
_SLATE_100 = "#f1f5f9"
_SLATE_50 = "#f8fafc"
_RED_700 = "#b91c1c"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"


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
                btn.setText("O'CHIRISH")
                btn.setObjectName("backspace")
            elif text == 'C':
                btn.setText("TOZALASH")
                btn.setObjectName("clear")
            else:
                btn.setText(text)

            btn.setFixedHeight(s(68))
            btn.setMinimumWidth(s(80))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            btn.setStyleSheet(f"""
                QPushButton {{
                    background: white;
                    border: 1px solid {_SLATE_200};
                    border-radius: {s(12)}px;
                    font-size: {font(24)}px;
                    font-weight: 800;
                    color: {_SLATE_900};
                    outline: none;
                }}
                QPushButton:hover {{
                    background: #fff7ed;
                    border: 1px solid #c89968;
                    color: #a07a44;
                }}
                QPushButton:pressed {{
                    background: #ffedd5;
                }}
                QPushButton#backspace {{
                    background: {_RED_50};
                    border: 1px solid {_RED_200};
                    color: {_RED_700};
                    font-size: {font(13)}px;
                    font-weight: 800;
                    letter-spacing: 2px;
                }}
                QPushButton#backspace:hover {{
                    background: #fee2e2;
                    border-color: #fca5a5;
                    color: #991b1b;
                }}
                QPushButton#backspace:pressed {{
                    background: #fecaca;
                }}
                QPushButton#clear {{
                    background: white;
                    border: 1px solid {_SLATE_200};
                    color: {_SLATE_500};
                    font-size: {font(11)}px;
                    font-weight: 800;
                    letter-spacing: 2px;
                }}
                QPushButton#clear:hover {{
                    background: {_SLATE_50};
                    border-color: {_SLATE_300};
                    color: {_SLATE_900};
                }}
                QPushButton#clear:pressed {{
                    background: {_SLATE_100};
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
