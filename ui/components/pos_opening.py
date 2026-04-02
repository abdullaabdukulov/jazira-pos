"""Kassa ochish — dialog va to'liq sahifa variantlari."""
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QWidget,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer
from PyQt6.QtGui import QDoubleValidator, QColor
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
            f"padding: {s(12)}px {s(18)}px; font-size: {font(20)}px; font-weight: 700; "
            f"border: 2px solid #3b82f6; border-radius: {s(12)}px; background: #eff6ff; color: #1e293b;"
        )

    @staticmethod
    def _normal_input_style():
        return (
            f"padding: {s(12)}px {s(18)}px; font-size: {font(20)}px; font-weight: 700; "
            f"border: 1.5px solid #e2e8f0; border-radius: {s(12)}px; background: white; color: #1e293b;"
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

        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f172a, stop:0.5 #1e293b, stop:1 #0f172a
                );
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Karta
        card = QFrame()
        card.setObjectName("posOpenCard")
        card.setFixedWidth(s(1024))
        card.setStyleSheet(f"""
            QFrame#posOpenCard {{
                background: white;
                border-radius: {s(20)}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(s(50))
        shadow.setOffset(0, s(10))
        shadow.setColor(QColor(0, 0, 0, 80))
        card.setGraphicsEffect(shadow)

        main_h = QHBoxLayout(card)
        main_h.setContentsMargins(s(30), s(30), s(30), s(30))
        main_h.setSpacing(s(30))

        # ── LEFT PANEL ──────────────────────────────
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(s(14))

        # Header karta
        header = QFrame()
        header.setStyleSheet(f"background: #1e40af; border-radius: {s(16)}px;")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(s(24), s(20), s(24), s(20))

        title = QLabel("KASSA OCHISH")
        title.setStyleSheet(f"color: #93c5fd; font-size: {font(13)}px; font-weight: 700; letter-spacing: 2px; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(title)

        pos_profile = self.config.get("pos_profile", "—")
        company = self.config.get("company", "—")
        cashier = self.config.get("cashier", self.config.get("user", "—"))

        info = QLabel(f"{pos_profile}")
        info.setStyleSheet(f"color: white; font-size: {font(20)}px; font-weight: 800; background: transparent;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(info)

        sub_info = QLabel(f"{company}  •  {cashier}")
        sub_info.setStyleSheet(f"color: #93c5fd; font-size: {font(15)}px; background: transparent;")
        sub_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(sub_info)

        left_layout.addWidget(header)

        pay_label = QLabel("BOSHLANG'ICH SUMMALAR")
        pay_label.setStyleSheet(f"font-size: {font(12)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px; background: transparent;")
        left_layout.addWidget(pay_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(s(16))

        payment_methods = self.config.get("payment_methods", ["Cash"])

        for idx, mode in enumerate(payment_methods):
            row = QHBoxLayout()

            lbl = QLabel(mode)
            lbl.setStyleSheet(f"font-size: {font(16)}px; font-weight: 700; color: #334155; background: transparent;")

            inp = ClickableLineEdit()
            inp.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            inp.setPlaceholderText("0")
            inp.setText("0")
            inp.setFixedWidth(s(260))
            inp.setFixedHeight(s(56))
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
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)

        # Tugmalar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(s(16))

        btn_exit = QPushButton("Dasturdan chiqish")
        btn_exit.setFixedHeight(s(64))
        btn_exit.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: {font(15)}px; border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        btn_exit.clicked.connect(self.exit_requested.emit)

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

        main_h.addWidget(left, 3)

        # ── RIGHT PANEL — Numpad ─────────────────────
        right = QWidget()
        right.setStyleSheet(f"background: #f8fafc; border-radius: {s(14)}px;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(s(16), s(16), s(16), s(16))
        right_layout.setSpacing(s(16))

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setStyleSheet(f"font-size: {font(12)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px; background: transparent;")
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        right_layout.addStretch()

        main_h.addWidget(right, 2)

        outer.addWidget(card)

    @staticmethod
    def _active_input_style():
        return (
            f"padding: {s(12)}px {s(18)}px; font-size: {font(20)}px; font-weight: 700; "
            f"border: 2px solid #3b82f6; border-radius: {s(12)}px; background: #eff6ff; color: #1e293b;"
        )

    @staticmethod
    def _normal_input_style():
        return (
            f"padding: {s(12)}px {s(18)}px; font-size: {font(20)}px; font-weight: 700; "
            f"border: 1.5px solid #e2e8f0; border-radius: {s(12)}px; background: white; color: #1e293b;"
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
