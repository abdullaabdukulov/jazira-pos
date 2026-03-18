"""Kassa ochish dialogi — POS Opening Entry yaratish."""
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer
from PyQt6.QtGui import QDoubleValidator
from core.api import FrappeAPI
from core.config import load_config
from core.logger import get_logger
from database.models import PosShift, db
from ui.components.numpad import TouchNumpad
from ui.components.dialogs import ClickableLineEdit

logger = get_logger(__name__)


class OpeningWorker(QThread):
    finished = pyqtSignal(bool, str, str)  # success, message, opening_entry_name

    def __init__(self, api: FrappeAPI, pos_profile: str, company: str, balance_details: list):
        super().__init__()
        self.api = api
        self.pos_profile = pos_profile
        self.company = company
        self.balance_details = balance_details

    def run(self):
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
            self.finished.emit(True, "Kassa muvaffaqiyatli ochildi!", name)
        elif isinstance(response, str) and ("Server xatosi" in response or "417" in response or "403" in response):
            # Server javob berdi lekin xato qaytardi — lokal saqlash KERAK EMAS
            self.finished.emit(False, f"Server xatosi: {response}", "")
        else:
            # Server bilan umuman aloqa yo'q — oflayn rejimda lokal saqlash
            self._save_local_shift(None)
            self.finished.emit(False, "Server bilan aloqa yo'q. Kassa lokal ochildi.", "")

    def _save_local_shift(self, opening_entry):
        try:
            db.connect(reuse_if_open=True)
            # Avvalgi ochiq shiftlarni yopish
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
        finally:
            if not db.is_closed():
                db.close()


class PosOpeningDialog(QDialog):
    opening_completed = pyqtSignal(str)  # opening_entry name
    exit_requested = pyqtSignal()  # dasturdan chiqish
    logout_requested = pyqtSignal()  # boshqa kassir uchun logout

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
        self.setFixedSize(780, 560)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet("background: white;")

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(20, 20, 20, 20)
        main_h.setSpacing(20)

        # ── LEFT PANEL ───────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        # Header
        header = QFrame()
        header.setStyleSheet("background: #1e40af; border-radius: 10px; padding: 15px;")
        h_layout = QVBoxLayout(header)

        title = QLabel("KASSA OCHISH")
        title.setStyleSheet("color: #93c5fd; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(title)

        pos_profile = self.config.get("pos_profile", "—")
        company = self.config.get("company", "—")
        info = QLabel(f"{pos_profile}\n{company}")
        info.setStyleSheet("color: white; font-size: 16px; font-weight: 700;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(info)

        left_layout.addWidget(header)

        # Payment mode inputs
        pay_label = QLabel("BOSHLANG'ICH SUMMALAR")
        pay_label.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;"
        )
        left_layout.addWidget(pay_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)

        payment_methods = self.config.get("payment_methods", ["Cash"])

        for idx, mode in enumerate(payment_methods):
            row = QHBoxLayout()
            lbl = QLabel(mode)
            lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #334155;")

            inp = ClickableLineEdit()
            inp.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            inp.setPlaceholderText("0")
            inp.setText("0")
            inp.setFixedWidth(190)
            inp.setFixedHeight(48)
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)

            if idx == 0:
                self.active_input = inp
                inp.setFocus()
                inp.setStyleSheet(
                    "padding: 10px 14px; font-size: 18px; font-weight: 700; "
                    "border: 2px solid #3b82f6; border-radius: 10px; background: #eff6ff; color: #1e293b;"
                )
            else:
                inp.setStyleSheet(
                    "padding: 10px 14px; font-size: 18px; font-weight: 700; "
                    "border: 1.5px solid #e2e8f0; border-radius: 10px; background: white; color: #1e293b;"
                )

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
        btn_layout.setSpacing(10)

        btn_exit = QPushButton("Chiqish")
        btn_exit.setFixedHeight(52)
        btn_exit.setStyleSheet("""
            QPushButton { background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: 13px; border-radius: 12px; border: none; }
            QPushButton:hover { background: #e2e8f0; }
        """)
        btn_exit.clicked.connect(self._on_exit)

        btn_logout = QPushButton("Logout")
        btn_logout.setFixedHeight(52)
        btn_logout.setStyleSheet("""
            QPushButton { background: #fef3c7; color: #92400e;
                font-weight: 700; font-size: 13px; border-radius: 12px; border: 1px solid #fde68a; }
            QPushButton:hover { background: #fde68a; }
        """)
        btn_logout.clicked.connect(self._on_logout)

        self.btn_open = QPushButton("KASSANI OCHISH")
        self.btn_open.setFixedHeight(52)
        self.btn_open.setStyleSheet("""
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1d4ed8, stop:1 #1e40af);
                color: white; font-weight: 800; font-size: 15px;
                border-radius: 12px; border: none; }
            QPushButton:hover { background: #1e3a8a; }
            QPushButton:disabled { background: #93c5fd; color: #dbeafe; }
        """)
        self.btn_open.clicked.connect(self._process_opening)

        btn_layout.addWidget(btn_exit, 1)
        btn_layout.addWidget(btn_logout, 1)
        btn_layout.addWidget(self.btn_open, 2)
        left_layout.addLayout(btn_layout)

        main_h.addWidget(left, 1)

        # ── RIGHT PANEL — Numpad ─────────────
        right = QWidget()
        right.setStyleSheet("background: #f8fafc; border-radius: 14px;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;"
        )
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        right_layout.addStretch()

        main_h.addWidget(right, 1)

    def _on_exit(self):
        self.exit_requested.emit()
        self.reject()

    def _on_logout(self):
        self.logout_requested.emit()
        self.reject()

    def _set_active_input(self, inp):
        # Reset previous
        if self.active_input:
            self.active_input.setStyleSheet(
                "padding: 10px 14px; font-size: 18px; font-weight: 700; "
                "border: 1.5px solid #e2e8f0; border-radius: 10px; background: white; color: #1e293b;"
            )
        self.active_input = inp
        inp.setStyleSheet(
            "padding: 10px 14px; font-size: 18px; font-weight: 700; "
            "border: 2px solid #3b82f6; border-radius: 10px; background: #eff6ff; color: #1e293b;"
        )
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
        self.worker.finished.connect(self._on_opening_finished)
        self.worker.start()

    def _on_opening_finished(self, success: bool, message: str, opening_entry: str):
        self.btn_open.setEnabled(True)
        self.btn_open.setText("KASSANI OCHISH")

        if success:
            self.opening_completed.emit(opening_entry)
            self.accept()
        elif opening_entry == "" and "Server xatosi" in message:
            # Server javob berdi lekin xato — foydalanuvchiga xabar, dialog ochiq qoladi
            from ui.components.dialogs import InfoDialog
            InfoDialog(self, "Xatolik", message, kind="error").exec()
        else:
            # Oflayn — lokal ochildi, POS ga ruxsat beramiz
            logger.warning("Kassa oflayn ochildi: %s", message)
            self.opening_completed.emit("")
            self.accept()
