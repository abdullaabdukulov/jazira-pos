"""Kassa yopish dialogi — POS Closing Entry yaratish."""
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer
from PyQt6.QtGui import QDoubleValidator
from core.api import FrappeAPI
from core.logger import get_logger
from database.models import PosShift, db
from ui.components.numpad import TouchNumpad
from ui.components.dialogs import ClickableLineEdit

logger = get_logger(__name__)


class ClosingDataWorker(QThread):
    """Serverdan kassa yopish ma'lumotlarini olish."""
    finished = pyqtSignal(bool, object)  # success, data

    def __init__(self, api: FrappeAPI, opening_entry: str):
        super().__init__()
        self.api = api
        self.opening_entry = opening_entry

    def run(self):
        success, response = self.api.call_method(
            "ury.ury_pos.api.getPosClosingData",
            {"pos_opening_entry": self.opening_entry},
        )
        if success and isinstance(response, dict):
            self.finished.emit(True, response)
        else:
            self.finished.emit(False, response)


class ClosingWorker(QThread):
    """Kassani yopish — POS Closing Entry yaratish."""
    finished = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, opening_entry: str, payment_reconciliation: list):
        super().__init__()
        self.api = api
        self.opening_entry = opening_entry
        self.payment_reconciliation = payment_reconciliation

    def run(self):
        success, response = self.api.call_method(
            "ury.ury_pos.api.createPosClosing",
            {
                "pos_opening_entry": self.opening_entry,
                "payment_reconciliation": json.dumps(self.payment_reconciliation),
            },
        )
        if success and isinstance(response, dict):
            self._close_local_shift()
            self.finished.emit(True, f"Kassa yopildi: {response.get('name', '')}")
        else:
            self.finished.emit(False, f"Kassa yopishda xatolik: {response}")

    def _close_local_shift(self):
        try:
            db.connect(reuse_if_open=True)
            import datetime
            PosShift.update(
                status="Closed",
                closed_at=datetime.datetime.now(),
            ).where(PosShift.status == "Open").execute()
        except Exception as e:
            logger.error("Lokal shift yopishda xatolik: %s", e)
        finally:
            if not db.is_closed():
                db.close()


class PosClosingDialog(QDialog):
    closing_completed = pyqtSignal()

    def __init__(self, parent, api: FrappeAPI, opening_entry: str):
        super().__init__(parent)
        self.api = api
        self.opening_entry = opening_entry
        self.reconciliation_data = []
        self.closing_inputs = {}
        self.active_input = None
        self.init_ui()
        QTimer.singleShot(50, self._center_on_parent)
        self._load_closing_data()

    def _center_on_parent(self):
        if self.parent():
            p_geo = self.parent().frameGeometry()
            c_geo = self.frameGeometry()
            c_geo.moveCenter(p_geo.center())
            self.move(c_geo.topLeft())

    def init_ui(self):
        self.setWindowTitle("Kassa yopish")
        self.setFixedSize(820, 600)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(20, 20, 20, 20)
        main_h.setSpacing(20)

        # ── LEFT PANEL ───────────────────────────
        left = QWidget()
        self.left_layout = QVBoxLayout(left)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(12)

        # Header
        header = QFrame()
        header.setStyleSheet("background: #7c2d12; border-radius: 10px; padding: 15px;")
        h_layout = QVBoxLayout(header)

        title = QLabel("KASSA YOPISH")
        title.setStyleSheet("color: #fed7aa; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(title)

        self.info_label = QLabel("Ma'lumotlar yuklanmoqda...")
        self.info_label.setStyleSheet("color: white; font-size: 14px; font-weight: 600;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(self.info_label)

        self.left_layout.addWidget(header)

        # Loading label
        self.loading_label = QLabel("Serverdan ma'lumotlar olinmoqda...")
        self.loading_label.setStyleSheet("font-size: 14px; color: #64748b; padding: 20px;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_layout.addWidget(self.loading_label)

        # Scroll area (hidden until data loads)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        self.scroll.setVisible(False)
        self.left_layout.addWidget(self.scroll)

        # Difference label
        self.diff_label = QLabel()
        self.diff_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diff_label.setVisible(False)
        self.left_layout.addWidget(self.diff_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("Bekor")
        btn_cancel.setFixedHeight(52)
        btn_cancel.setStyleSheet("""
            QPushButton { background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: 14px; border-radius: 12px; border: none; }
            QPushButton:hover { background: #e2e8f0; }
        """)
        btn_cancel.clicked.connect(self.reject)

        self.btn_close = QPushButton("KASSANI YOPISH")
        self.btn_close.setFixedHeight(52)
        self.btn_close.setEnabled(False)
        self.btn_close.setStyleSheet("""
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #dc2626, stop:1 #b91c1c);
                color: white; font-weight: 800; font-size: 15px;
                border-radius: 12px; border: none; }
            QPushButton:hover { background: #991b1b; }
            QPushButton:disabled { background: #fca5a5; color: #fecaca; }
        """)
        self.btn_close.clicked.connect(self._process_closing)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_close, 1)
        self.left_layout.addLayout(btn_layout)

        main_h.addWidget(left, 1)

        # ── RIGHT PANEL — Numpad ─────────────
        right = QWidget()
        right.setStyleSheet("background: #f8fafc; border-radius: 14px;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        numpad_lbl = QLabel("YOPISH SUMMASI")
        numpad_lbl.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;"
        )
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        right_layout.addStretch()

        main_h.addWidget(right, 1)

    def _load_closing_data(self):
        if not self.opening_entry:
            self.loading_label.setText("Ochiq kassa topilmadi.")
            return

        self.data_worker = ClosingDataWorker(self.api, self.opening_entry)
        self.data_worker.finished.connect(self._on_data_loaded)
        self.data_worker.start()

    def _on_data_loaded(self, success: bool, data):
        if not success:
            self.loading_label.setText("Ma'lumotlarni olishda xatolik yuz berdi.")
            return

        self.loading_label.setVisible(False)
        self.scroll.setVisible(True)
        self.diff_label.setVisible(True)
        self.btn_close.setEnabled(True)

        total_invoices = data.get("total_invoices", 0)
        self.reconciliation_data = data.get("reconciliation", [])

        self.info_label.setText(f"Jami cheklar: {total_invoices}")

        # Build reconciliation form
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)

        col_header = QHBoxLayout()
        for text, width in [("To'lov turi", 120), ("Kutilgan", 100), ("Haqiqiy", 130)]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
            col_header.addWidget(lbl)
        col_header.addStretch()
        scroll_layout.addLayout(col_header)

        for idx, rec in enumerate(self.reconciliation_data):
            mop = rec["mode_of_payment"]
            expected = rec["expected_amount"]

            row = QHBoxLayout()

            lbl = QLabel(mop)
            lbl.setFixedWidth(120)
            lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #334155;")
            row.addWidget(lbl)

            exp_lbl = QLabel(f"{expected:,.0f}".replace(",", " "))
            exp_lbl.setFixedWidth(100)
            exp_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #1e40af;")
            row.addWidget(exp_lbl)

            inp = ClickableLineEdit()
            inp.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            inp.setPlaceholderText("0")
            inp.setText(str(int(expected)))
            inp.setFixedWidth(130)
            inp.setFixedHeight(44)
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)
            inp.clicked.connect(self._set_active_input)
            inp.textChanged.connect(self._update_difference)

            if idx == 0:
                self.active_input = inp
                inp.setStyleSheet(
                    "padding: 8px 12px; font-size: 16px; font-weight: 700; "
                    "border: 2px solid #3b82f6; border-radius: 10px; background: #eff6ff; color: #1e293b;"
                )
            else:
                inp.setStyleSheet(
                    "padding: 8px 12px; font-size: 16px; font-weight: 700; "
                    "border: 1.5px solid #e2e8f0; border-radius: 10px; background: white; color: #1e293b;"
                )

            row.addWidget(inp)
            row.addStretch()

            self.closing_inputs[mop] = {"input": inp, "expected": expected}
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        self.scroll.setWidget(scroll_content)
        self._update_difference()

    def _set_active_input(self, inp):
        if self.active_input:
            self.active_input.setStyleSheet(
                "padding: 8px 12px; font-size: 16px; font-weight: 700; "
                "border: 1.5px solid #e2e8f0; border-radius: 10px; background: white; color: #1e293b;"
            )
        self.active_input = inp
        inp.setStyleSheet(
            "padding: 8px 12px; font-size: 16px; font-weight: 700; "
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

    def _update_difference(self):
        total_diff = 0
        for mop, data in self.closing_inputs.items():
            try:
                closing_amt = float(data["input"].text() or 0)
            except ValueError:
                closing_amt = 0
            diff = data["expected"] - closing_amt
            total_diff += abs(diff)

        if total_diff == 0:
            self.diff_label.setText("Farq yo'q — hammasi to'g'ri")
            self.diff_label.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #16a34a; padding: 6px;"
            )
        else:
            self.diff_label.setText(f"Farq: {total_diff:,.0f} UZS".replace(",", " "))
            self.diff_label.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #dc2626; padding: 6px;"
            )

    def _process_closing(self):
        self.btn_close.setEnabled(False)
        self.btn_close.setText("Kassa yopilmoqda...")

        payment_reconciliation = []
        for rec in self.reconciliation_data:
            mop = rec["mode_of_payment"]
            data = self.closing_inputs.get(mop, {})
            try:
                closing_amount = float(data["input"].text() or 0)
            except (ValueError, KeyError):
                closing_amount = 0

            payment_reconciliation.append({
                "mode_of_payment": mop,
                "opening_amount": rec["opening_amount"],
                "expected_amount": rec["expected_amount"],
                "closing_amount": closing_amount,
            })

        self.closing_worker = ClosingWorker(self.api, self.opening_entry, payment_reconciliation)
        self.closing_worker.finished.connect(self._on_closing_finished)
        self.closing_worker.start()

    def _on_closing_finished(self, success: bool, message: str):
        self.btn_close.setEnabled(True)
        self.btn_close.setText("KASSANI YOPISH")

        if success:
            self.accept()
            self.closing_completed.emit()
        else:
            logger.error("Kassa yopish xatosi: %s", message)
            self.btn_close.setText("Qayta urinish")
            self.btn_close.setEnabled(True)
