"""Kassa ochish — dialog va to'liq sahifa variantlari."""
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QWidget,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer
from PyQt6.QtGui import QDoubleValidator, QColor, QFont


# ── Elite palette ────────────────────────────────────────
_GOLD = "#c89968"
_GOLD_LIGHT = "#e6c693"
_GOLD_DEEP = "#a07a44"
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
from core.api import FrappeAPI
from core.config import load_config
from core.logger import get_logger
from database.models import PosShift, db
from ui.components.numpad import TouchNumpad
from ui.components.dialogs import ClickableLineEdit
from ui.scale import s, font

logger = get_logger(__name__)


class OpeningWorker(QThread):
    result_ready = pyqtSignal(bool, str, str)

    def __init__(self, api: FrappeAPI, pos_profile: str, company: str, balance_details: list):
        super().__init__()
        self.api = api
        self.pos_profile = pos_profile
        self.company = company
        self.balance_details = balance_details

    def run(self):
        try:
            success, response = self.api.call_method(
                "ury.ury_pos.api.createPosOpening",
                {
                    "pos_profile": self.pos_profile,
                    "company": self.company,
                    "balance_details": json.dumps(self.balance_details),
                },
            )

            if success and isinstance(response, dict):
                name = response.get("name", "")
                self._save_local_shift(name)
                self.result_ready.emit(True, "Kassa muvaffaqiyatli ochildi!", name)
            elif isinstance(response, str) and ("Server xatosi" in response or "417" in response or "403" in response):
                self.result_ready.emit(False, f"Server xatosi: {response}", "")
            else:
                self._save_local_shift(None)
                self.result_ready.emit(False, "Server bilan aloqa yo'q. Kassa lokal ochildi.", "")
        finally:
            if not db.is_closed():
                db.close()

    def _save_local_shift(self, opening_entry):
        try:
            PosShift.update(status="Closed").where(PosShift.status == "Open").execute()
            PosShift.create(
                opening_entry=opening_entry,
                pos_profile=self.pos_profile,
                company=self.company,
                user=self.api.user or "offline",
                opening_amounts=json.dumps(self.balance_details),
                status="Open",
            )
        except Exception as e:
            logger.error("Lokal shift saqlashda xatolik: %s", e)


class PosOpeningDialog(QDialog):
    opening_completed = pyqtSignal(str)
    exit_requested = pyqtSignal()

    def __init__(self, parent, api: FrappeAPI):
        super().__init__(parent)
        self.api = api
        self.config = load_config()
        self.payment_inputs = {}
        self.active_input = None
        self.init_ui()
        QTimer.singleShot(50, self._center_on_parent)

    def _center_on_parent(self):
        if self.parent():
            p_geo = self.parent().frameGeometry()
            c_geo = self.frameGeometry()
            c_geo.moveCenter(p_geo.center())
            self.move(c_geo.topLeft())

    def init_ui(self):
        self.setWindowTitle("Kassa ochish")
        self.setMinimumSize(s(900), s(700))
        self.resize(s(1024), s(768))
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet("background: white;")

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(s(30), s(30), s(30), s(30))
        main_h.setSpacing(s(30))

        # ── LEFT PANEL ───────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(s(16))

        header = QFrame()
        header.setStyleSheet(f"background: #1e40af; border-radius: {s(12)}px; padding: {s(24)}px;")
        h_layout = QVBoxLayout(header)

        title = QLabel("KASSA OCHISH")
        title.setStyleSheet(f"color: #93c5fd; font-size: {font(13)}px; font-weight: 700; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(title)

        pos_profile = self.config.get("pos_profile", "—")
        company = self.config.get("company", "—")
        info = QLabel(f"{pos_profile}\n{company}")
        info.setStyleSheet(f"color: white; font-size: {font(18)}px; font-weight: 700;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(info)

        left_layout.addWidget(header)

        pay_label = QLabel("BOSHLANG'ICH SUMMALAR")
        pay_label.setStyleSheet(f"font-size: {font(12)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;")
        left_layout.addWidget(pay_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(s(12))

        payment_methods = self.config.get("payment_methods", ["Cash"])

        for idx, mode in enumerate(payment_methods):
            row = QHBoxLayout()
            lbl = QLabel(mode)
            lbl.setStyleSheet(f"font-size: {font(16)}px; font-weight: 700; color: #334155;")

            inp = ClickableLineEdit()
            inp.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            inp.setPlaceholderText("0")
            inp.setText("0")
            inp.setFixedWidth(s(260))
            inp.setFixedHeight(s(56))
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)

            if idx == 0:
                self.active_input = inp
                inp.setFocus()
                inp.setStyleSheet(self._active_input_style())
            else:
                inp.setStyleSheet(self._normal_input_style())

            inp.clicked.connect(self._set_active_input)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(inp)

            self.payment_inputs[mode] = inp
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(s(16))

        btn_exit = QPushButton("Chiqish")
        btn_exit.setFixedHeight(s(64))
        btn_exit.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: {font(15)}px; border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        btn_exit.clicked.connect(self._on_exit)

        self.btn_open = QPushButton("KASSANI OCHISH")
        self.btn_open.setFixedHeight(s(64))
        self.btn_open.setStyleSheet(f"""
            QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1d4ed8, stop:1 #1e40af);
                color: white; font-weight: 800; font-size: {font(17)}px;
                border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #1e3a8a; }}
            QPushButton:disabled {{ background: #93c5fd; color: #dbeafe; }}
        """)
        self.btn_open.clicked.connect(self._process_opening)

        btn_layout.addWidget(btn_exit, 1)
        btn_layout.addWidget(self.btn_open, 2)
        left_layout.addLayout(btn_layout)

        main_h.addWidget(left, 1)

        # ── RIGHT PANEL — Numpad ─────────────
        right = QWidget()
        right.setStyleSheet(f"background: #f8fafc; border-radius: {s(14)}px;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(s(16), s(16), s(16), s(16))
        right_layout.setSpacing(s(16))

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setStyleSheet(f"font-size: {font(12)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;")
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        right_layout.addStretch()

        main_h.addWidget(right, 1)

    @staticmethod
    def _active_input_style():
        return (
            f"padding: {s(8)}px {s(14)}px; font-size: {font(16)}px; font-weight: 800; "
            f"border: 2px solid {_GOLD}; border-radius: {s(8)}px; "
            f"background: #fff7ed; color: {_SLATE_900}; outline: none;"
        )

    @staticmethod
    def _normal_input_style():
        return (
            f"padding: {s(8)}px {s(14)}px; font-size: {font(16)}px; font-weight: 800; "
            f"border: 1px solid {_SLATE_200}; border-radius: {s(8)}px; "
            f"background: white; color: {_SLATE_900}; outline: none;"
        )

    def reject(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            return  # Worker ishlayotganda dialog yopilmasin
        super().reject()

    def _on_exit(self):
        self.exit_requested.emit()
        self.reject()

    def _on_logout(self):
        self.logout_requested.emit()
        self.reject()

    def _set_active_input(self, inp):
        if self.active_input:
            self.active_input.setStyleSheet(self._normal_input_style())
        self.active_input = inp
        inp.setStyleSheet(self._active_input_style())
        inp.setFocus()

    def _on_numpad_clicked(self, action: str):
        if not self.active_input:
            return
        current = self.active_input.text()
        if action == "CLEAR":
            self.active_input.setText("0")
        elif action == "BACKSPACE":
            new_val = current[:-1] if len(current) > 1 else "0"
            self.active_input.setText(new_val)
        elif action == ".":
            if "." not in current:
                self.active_input.setText(current + ".")
        else:
            if current == "0":
                self.active_input.setText(action)
            else:
                self.active_input.setText(current + action)

    def _process_opening(self):
        self.btn_open.setEnabled(False)
        self.btn_open.setText("Kassa ochilmoqda...")

        balance_details = []
        for mode, inp in self.payment_inputs.items():
            try:
                amount = float(inp.text() or 0)
            except ValueError:
                amount = 0
            balance_details.append({
                "mode_of_payment": mode,
                "opening_amount": amount,
            })

        pos_profile = self.config.get("pos_profile", "")
        company = self.config.get("company", "")

        self.worker = OpeningWorker(self.api, pos_profile, company, balance_details)
        self.worker.result_ready.connect(self._on_opening_finished)
        self.worker.start()

    def _on_opening_finished(self, success: bool, message: str, opening_entry: str):
        self.btn_open.setEnabled(True)
        self.btn_open.setText("KASSANI OCHISH")

        if success:
            self.opening_completed.emit(opening_entry)
            self.accept()
        elif opening_entry == "" and "Server xatosi" in message:
            from ui.components.dialogs import InfoDialog
            InfoDialog(self, "Xatolik", message, kind="error").exec()
        else:
            logger.warning("Kassa oflayn ochildi: %s", message)
            self.opening_completed.emit("")
            self.accept()


# ══════════════════════════════════════════════════════════════════
#  PosOpeningPage — to'liq oyna (QWidget, dialog emas)
#  MainWindow da QStackedWidget sahifasi sifatida ishlatiladi
# ══════════════════════════════════════════════════════════════════
class PosOpeningPage(QWidget):
    """Kassa ochish — to'liq ekranli sahifa."""
    opening_completed = pyqtSignal(str)   # opening_entry
    exit_requested = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.config = load_config()
        self.payment_inputs = {}
        self.active_input = None
        self._init_ui()

    def refresh(self):
        """Sahifani yangilash — yangidan ochilganda payment inputlarni tozalash."""
        self.config = load_config()
        for inp in self.payment_inputs.values():
            inp.setText("0")
        if self.active_input:
            self.active_input.setStyleSheet(self._active_input_style())

    def _init_ui(self):
        from ui.components.numpad import TouchNumpad
        from ui.components.dialogs import ClickableLineEdit

        # Premium navy gradient fon — login window stilida
        self.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a1224, stop:0.5 #101a32, stop:1 #050a18
                );
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Karta — elite shadow
        card = QFrame()
        card.setObjectName("posOpenCard")
        card.setFixedWidth(s(1100))
        card.setStyleSheet(f"""
            QFrame#posOpenCard {{
                background: white;
                border-radius: {s(16)}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(s(60))
        shadow.setOffset(0, s(12))
        shadow.setColor(QColor(0, 0, 0, 100))
        card.setGraphicsEffect(shadow)

        # Card content: header + body horizontal split
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(s(28), s(20), s(28), s(20))
        card_layout.setSpacing(s(12))

        # ── Header (caps title + subtitle + exit) ─────
        header_row = QHBoxLayout()
        header_row.setSpacing(s(12))

        title_block = QVBoxLayout()
        title_block.setSpacing(s(3))

        title = QLabel("KASSA OCHISH")
        title.setFrameShape(QFrame.Shape.NoFrame)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _tf = QFont()
        _tf.setPixelSize(font(20))
        _tf.setWeight(QFont.Weight.Black)
        _tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        title.setFont(_tf)
        title.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        title_block.addWidget(title)

        subtitle = QLabel("Smenani boshlash — boshlang'ich summalarni kiriting")
        subtitle.setFrameShape(QFrame.Shape.NoFrame)
        _stf = QFont()
        _stf.setPixelSize(font(11))
        _stf.setWeight(QFont.Weight.Medium)
        subtitle.setFont(_stf)
        subtitle.setStyleSheet(
            f"color: {_SLATE_500}; background: transparent;"
            f" border: none; outline: none;"
        )
        title_block.addWidget(subtitle)
        header_row.addLayout(title_block)
        header_row.addStretch()

        # Exit (top right ikonka)
        btn_exit = QPushButton("✕")
        btn_exit.setFixedSize(s(40), s(40))
        btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_exit.setToolTip("Dasturdan chiqish")
        btn_exit.setStyleSheet(f"""
            QPushButton {{
                background: {_SLATE_50};
                color: {_SLATE_700};
                font-weight: 700;
                font-size: {font(16)}px;
                border-radius: {s(10)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: white; color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        btn_exit.clicked.connect(self.exit_requested.emit)
        header_row.addWidget(btn_exit)
        card_layout.addLayout(header_row)

        # Gradient hairline (gold accent — brand)
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {_GOLD}, stop:0.15 {_SLATE_100}, stop:1 {_SLATE_100});"
            f" border: none;"
        )
        card_layout.addWidget(sep)

        # ── Main horizontal split ──────────────────────
        main_h = QHBoxLayout()
        main_h.setContentsMargins(0, s(8), 0, 0)
        main_h.setSpacing(s(20))
        card_layout.addLayout(main_h)

        # ── LEFT PANEL ──────────────────────────────
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(s(12))

        # POS Profile info card — slate-900 + gold accent border
        info_card = QFrame()
        info_card.setStyleSheet(f"""
            QFrame {{
                background: {_SLATE_900};
                border-radius: {s(12)}px;
                border: 1px solid {_SLATE_800};
                border-left: 4px solid {_GOLD};
            }}
        """)
        ic_layout = QVBoxLayout(info_card)
        ic_layout.setContentsMargins(s(24), s(16), s(24), s(16))
        ic_layout.setSpacing(s(6))

        pos_profile = self.config.get("pos_profile", "—")
        company = self.config.get("company", "—")
        cashier = self.config.get("cashier", self.config.get("user", "—"))

        ic_title = QLabel("POS PROFILE")
        ic_title.setFrameShape(QFrame.Shape.NoFrame)
        _ict_font = QFont()
        _ict_font.setPixelSize(font(10))
        _ict_font.setWeight(QFont.Weight.Black)
        _ict_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        ic_title.setFont(_ict_font)
        ic_title.setStyleSheet(
            f"color: {_GOLD_LIGHT}; background: transparent;"
            f" border: none; outline: none;"
        )
        ic_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_layout.addWidget(ic_title)

        info = QLabel(f"{pos_profile}")
        info.setFrameShape(QFrame.Shape.NoFrame)
        _info_font = QFont()
        _info_font.setPixelSize(font(20))
        _info_font.setWeight(QFont.Weight.Black)
        _info_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        info.setFont(_info_font)
        info.setStyleSheet(
            f"color: white; background: transparent;"
            f" border: none; outline: none;"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_layout.addWidget(info)

        sub_info = QLabel(f"{company}  ·  {cashier}")
        sub_info.setFrameShape(QFrame.Shape.NoFrame)
        _si_font = QFont()
        _si_font.setPixelSize(font(12))
        _si_font.setWeight(QFont.Weight.Medium)
        _si_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        sub_info.setFont(_si_font)
        sub_info.setStyleSheet(
            f"color: {_SLATE_300}; background: transparent;"
            f" border: none; outline: none;"
        )
        sub_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_layout.addWidget(sub_info)

        left_layout.addWidget(info_card)

        # ── BOSHLANG'ICH SUMMALAR ─────────────────────
        pay_label = QLabel("BOSHLANG'ICH SUMMALAR")
        pay_label.setFrameShape(QFrame.Shape.NoFrame)
        _pl_font = QFont()
        _pl_font.setPixelSize(font(10))
        _pl_font.setWeight(QFont.Weight.Black)
        _pl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        pay_label.setFont(_pl_font)
        pay_label.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        left_layout.addWidget(pay_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                width: {s(6)}px; background: transparent; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {_SLATE_300}; border-radius: {s(3)}px;
                min-height: {s(30)}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(s(8))
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        payment_methods = self.config.get("payment_methods", ["Cash"])

        for idx, mode in enumerate(payment_methods):
            row_frame = QFrame()
            row_frame.setStyleSheet(
                f"QFrame {{ background: transparent;"
                f" border-radius: {s(8)}px; border: none; }}"
            )
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(s(12), s(6), s(12), s(6))
            row.setSpacing(s(10))

            lbl = QLabel(mode)
            lbl.setFrameShape(QFrame.Shape.NoFrame)
            _lbl_font = QFont()
            _lbl_font.setPixelSize(font(15))
            _lbl_font.setWeight(QFont.Weight.Bold)
            _lbl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
            lbl.setFont(_lbl_font)
            lbl.setStyleSheet(
                f"color: {_SLATE_900}; background: transparent;"
                f" border: none; outline: none;"
            )

            inp = ClickableLineEdit()
            inp.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            inp.setPlaceholderText("0")
            inp.setText("0")
            inp.setMinimumWidth(s(200))
            inp.setFixedHeight(s(44))
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)

            if idx == 0:
                self.active_input = inp
                inp.setStyleSheet(self._active_input_style())
            else:
                inp.setStyleSheet(self._normal_input_style())

            inp.clicked.connect(self._set_active_input)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(inp)

            self.payment_inputs[mode] = inp
            scroll_layout.addWidget(row_frame)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll, stretch=1)

        # ── Bottom action button (kassa ochish) ────────
        self.btn_open = QPushButton("KASSANI OCHISH")
        self.btn_open.setFixedHeight(s(56))
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_open.setStyleSheet(f"""
            QPushButton {{
                background: {_EMERALD_600};
                color: white;
                font-weight: 900;
                font-size: {font(14)}px;
                letter-spacing: 2px;
                border-radius: {s(10)}px;
                border: 1px solid {_EMERALD_600};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_EMERALD_700}; border-color: {_EMERALD_700};
            }}
            QPushButton:pressed {{ background: #065f46; }}
            QPushButton:disabled {{
                background: {_SLATE_100};
                color: {_SLATE_400};
                border-color: {_SLATE_200};
            }}
        """)
        self.btn_open.clicked.connect(self._process_opening)
        left_layout.addWidget(self.btn_open)

        main_h.addWidget(left, 1)

        # ── RIGHT PANEL — Numpad ─────────────────────
        right = QWidget()
        right.setStyleSheet(
            f"background: {_SLATE_50};"
            f" border-radius: {s(14)}px;"
            f" border: 1px solid {_SLATE_200};"
        )
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(s(18), s(18), s(18), s(18))
        right_layout.setSpacing(s(14))

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setFrameShape(QFrame.Shape.NoFrame)
        _nl_font = QFont()
        _nl_font.setPixelSize(font(10))
        _nl_font.setWeight(QFont.Weight.Black)
        _nl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        numpad_lbl.setFont(_nl_font)
        numpad_lbl.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        right_layout.addStretch()

        main_h.addWidget(right, 1)

        outer.addWidget(card)

    @staticmethod
    def _active_input_style():
        return (
            f"padding: {s(8)}px {s(14)}px; font-size: {font(16)}px; font-weight: 800; "
            f"border: 2px solid {_GOLD}; border-radius: {s(8)}px; "
            f"background: #fff7ed; color: {_SLATE_900}; outline: none;"
        )

    @staticmethod
    def _normal_input_style():
        return (
            f"padding: {s(8)}px {s(14)}px; font-size: {font(16)}px; font-weight: 800; "
            f"border: 1px solid {_SLATE_200}; border-radius: {s(8)}px; "
            f"background: white; color: {_SLATE_900}; outline: none;"
        )

    def _set_active_input(self, inp):
        if self.active_input:
            self.active_input.setStyleSheet(self._normal_input_style())
        self.active_input = inp
        inp.setStyleSheet(self._active_input_style())
        inp.setFocus()

    def _on_numpad_clicked(self, action: str):
        if not self.active_input:
            return
        current = self.active_input.text()
        if action == "CLEAR":
            self.active_input.setText("0")
        elif action == "BACKSPACE":
            new_val = current[:-1] if len(current) > 1 else "0"
            self.active_input.setText(new_val)
        elif action == ".":
            if "." not in current:
                self.active_input.setText(current + ".")
        else:
            if current == "0":
                self.active_input.setText(action)
            else:
                self.active_input.setText(current + action)

    def _process_opening(self):
        self.btn_open.setEnabled(False)
        self.btn_open.setText("Kassa ochilmoqda...")

        balance_details = []
        for mode, inp in self.payment_inputs.items():
            try:
                amount = float(inp.text() or 0)
            except ValueError:
                amount = 0
            balance_details.append({"mode_of_payment": mode, "opening_amount": amount})

        self.config = load_config()
        pos_profile = self.config.get("pos_profile", "")
        company = self.config.get("company", "")

        self.worker = OpeningWorker(self.api, pos_profile, company, balance_details)
        self.worker.result_ready.connect(self._on_opening_finished)
        self.worker.start()

    def _on_opening_finished(self, success: bool, message: str, opening_entry: str):
        self.btn_open.setEnabled(True)
        self.btn_open.setText("KASSANI OCHISH")

        if success:
            self.opening_completed.emit(opening_entry)
        elif opening_entry == "" and "Server xatosi" in message:
            from ui.components.dialogs import InfoDialog
            InfoDialog(self, "Xatolik", message, kind="error").exec()
        else:
            logger.warning("Kassa oflayn ochildi: %s", message)
            self.opening_completed.emit("")
