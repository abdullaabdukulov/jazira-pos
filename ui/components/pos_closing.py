"""Kassa yopish dialogi — POS Closing Entry yaratish."""
import json
from datetime import datetime
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
from ui.scale import s, font

logger = get_logger(__name__)


class ClosingDataWorker(QThread):
    """Serverdan kassa yopish ma'lumotlarini olish."""
    result_ready = pyqtSignal(bool, object)  # success, data

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
            self.result_ready.emit(True, response)
        else:
            self.result_ready.emit(False, response)


class ClosingWorker(QThread):
    """Kassani yopish — POS Closing Entry yaratish."""
    result_ready = pyqtSignal(bool, str, object)  # success, message, z_report_data

    def __init__(self, api: FrappeAPI, opening_entry: str, payment_reconciliation: list):
        super().__init__()
        self.api = api
        self.opening_entry = opening_entry
        self.payment_reconciliation = payment_reconciliation

    def run(self):
        try:
            success, response = self.api.call_method(
                "ury.ury_pos.api.createPosClosing",
                {
                    "pos_opening_entry": self.opening_entry,
                    "payment_reconciliation": json.dumps(self.payment_reconciliation),
                },
            )
            if success and isinstance(response, dict):
                self._close_local_shift()
                z_data = response.get("z_report_data", {})
                self.result_ready.emit(True, f"Kassa yopildi: {response.get('name', '')}", z_data)
            else:
                self.result_ready.emit(False, f"Kassa yopishda xatolik: {response}", {})
        finally:
            if not db.is_closed():
                db.close()

    def _close_local_shift(self):
        try:
            import datetime
            PosShift.update(
                status="Closed",
                closed_at=datetime.datetime.now(),
            ).where(PosShift.status == "Open").execute()
        except Exception as e:
            logger.error("Lokal shift yopishda xatolik: %s", e)


class PosClosingDialog(QDialog):
    closing_completed = pyqtSignal()

    def __init__(self, parent, api: FrappeAPI, opening_entry: str):
        super().__init__(parent)
        self.api = api
        self.opening_entry = opening_entry
        self.reconciliation_data = []
        self._cash_key = None
        self._verification_state = "first"
        self._first_cash_amount = None
        self.total_invoices = 0
        self._z_report_data_from_backend = {}  # Backend javobidagi Z-report ma'lumotlari
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
        self.setMinimumSize(s(900), s(700))
        self.resize(s(1024), s(768))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(s(30), s(30), s(30), s(30))
        main_h.setSpacing(s(30))

        # ── LEFT PANEL ───────────────────────────
        left = QWidget()
        self.left_layout = QVBoxLayout(left)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(s(16))

        # Header
        header = QFrame()
        header.setStyleSheet(f"background: #7c2d12; border-radius: {s(12)}px; padding: {s(24)}px;")
        h_layout = QVBoxLayout(header)

        title = QLabel("KASSA YOPISH")
        title.setStyleSheet(f"color: #fed7aa; font-size: {font(13)}px; font-weight: 700; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(title)

        self.info_label = QLabel("Ma'lumotlar yuklanmoqda...")
        self.info_label.setStyleSheet(f"color: white; font-size: {font(16)}px; font-weight: 600;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(self.info_label)

        self.left_layout.addWidget(header)

        # Loading label
        self.loading_label = QLabel("Serverdan ma'lumotlar olinmoqda...")
        self.loading_label.setStyleSheet(f"font-size: {font(14)}px; color: #64748b; padding: {s(20)}px;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_layout.addWidget(self.loading_label)

        # ── NAQD PUL KIRISH QISMI (ma'lumot yuklanganidan keyin ko'rinadi) ──
        self.cash_section = QWidget()
        self.cash_section.setVisible(False)
        cash_layout = QVBoxLayout(self.cash_section)
        cash_layout.setContentsMargins(0, 0, 0, 0)
        cash_layout.setSpacing(s(12))

        self.step_label = QLabel("NAQD PULNI SANING VA KIRITING")
        self.step_label.setStyleSheet(
            f"font-size: {font(11)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;"
        )
        cash_layout.addWidget(self.step_label)

        self.cash_input = ClickableLineEdit()
        self.cash_input.setValidator(QDoubleValidator(0.0, 999_999_999.0, 2))
        self.cash_input.setPlaceholderText("0")
        self.cash_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.cash_input.setFixedHeight(s(80))
        self.cash_input.setStyleSheet(
            f"padding: {s(12)}px {s(20)}px; font-size: {font(32)}px; font-weight: 800; "
            f"border: 2.5px solid #3b82f6; border-radius: {s(14)}px; "
            f"background: #eff6ff; color: #1e293b;"
        )
        cash_layout.addWidget(self.cash_input)

        self.left_layout.addWidget(self.cash_section)
        self.left_layout.addStretch()

        # Status label (faqat xatolik/tasdiqlash holati uchun, farq Ko'rsatilmaydi)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        self.left_layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(s(16))

        btn_cancel = QPushButton("Bekor")
        btn_cancel.setFixedHeight(s(64))
        btn_cancel.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: {font(16)}px; border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        btn_cancel.clicked.connect(self.reject)

        self.btn_close = QPushButton("KASSANI YOPISH")
        self.btn_close.setFixedHeight(s(64))
        self.btn_close.setEnabled(False)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #dc2626, stop:1 #b91c1c);
                color: white; font-weight: 800; font-size: {font(17)}px;
                border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #991b1b; }}
            QPushButton:disabled {{ background: #fca5a5; color: #fecaca; }}
        """)
        self.btn_close.clicked.connect(self._process_closing)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_close, 1)
        self.left_layout.addLayout(btn_layout)

        main_h.addWidget(left, 1)

        # ── RIGHT PANEL — Numpad ─────────────
        right = QWidget()
        right.setStyleSheet(f"background: #f8fafc; border-radius: {s(14)}px;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(s(16), s(16), s(16), s(16))
        right_layout.setSpacing(s(16))

        self.numpad_lbl = QLabel("NAQD PUL SUMMASI")
        self.numpad_lbl.setStyleSheet(
            f"font-size: {font(12)}px; font-weight: 800; color: #64748b; letter-spacing: 2px;"
        )
        right_layout.addWidget(self.numpad_lbl)

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
        self.data_worker.result_ready.connect(self._on_data_loaded)
        self.data_worker.start()

    def _on_data_loaded(self, success: bool, data):
        if not success:
            self.loading_label.setText("Ma'lumotlarni olishda xatolik yuz berdi.")
            return

        self.loading_label.setVisible(False)
        self.cash_section.setVisible(True)
        self.btn_close.setEnabled(True)

        self.total_invoices = data.get("total_invoices", 0)
        self.reconciliation_data = data.get("reconciliation", [])
        self.info_label.setText(f"Jami cheklar: {self.total_invoices}")

        # Naqd kalitini aniqlash (faqat ichki — ekranda ko'rsatilmaydi)
        _CASH_KEYWORDS = {"cash", "naqd", "naqd pul", "наличные", "cash in hand"}
        for idx, rec in enumerate(self.reconciliation_data):
            mop = rec["mode_of_payment"]
            if mop.lower().strip() in _CASH_KEYWORDS and self._cash_key is None:
                self._cash_key = mop
            if idx == 0 and self._cash_key is None:
                self._cash_key = mop

        self.cash_input.setText("")
        self.cash_input.setFocus()


    def _on_numpad_clicked(self, action: str):
        target = self.cash_input
        current = target.text()
        if action == "CLEAR":
            target.setText("")
        elif action == "BACKSPACE":
            target.setText(current[:-1])
        elif action == ".":
            if "." not in current:
                target.setText(current + ".")
        else:
            target.setText(current + action)

    def _show_status(self, text: str, color: str):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"font-size: {font(13)}px; font-weight: 700; color: {color}; padding: {s(6)}px;"
        )
        self.status_label.setVisible(True)

    def reject(self):
        if hasattr(self, 'closing_worker') and self.closing_worker.isRunning():
            return  # Worker ishlayotganda dialog yopilmasin
        super().reject()

    def _process_closing(self):
        """Double verification: birinchi marta → tasdiqlash so'rashi, ikkinchi marta → solishtirish."""
        try:
            cash_amount = float(self.cash_input.text() or "0")
        except ValueError:
            cash_amount = 0.0

        if self._verification_state == "first":
            if not self.cash_input.text().strip():
                self._show_status("Naqd pul summasini kiriting!", "#dc2626")
                return
            self._first_cash_amount = cash_amount
            self.cash_input.setText("")
            self._verification_state = "second"
            self.btn_close.setText("✓  TASDIQLASH")
            self.step_label.setText("2-QADAM: QAYTA SANING VA KIRITING")
            self.step_label.setStyleSheet(
                f"font-size: {font(11)}px; font-weight: 800; color: #f59e0b; letter-spacing: 2px;"
            )
            self.numpad_lbl.setText("QAYTA SANING — TASDIQLASH")
            self.numpad_lbl.setStyleSheet(
                f"font-size: {font(12)}px; font-weight: 800; color: #f59e0b; letter-spacing: 2px;"
            )
            self.cash_input.setStyleSheet(
                f"padding: {s(12)}px {s(20)}px; font-size: {font(32)}px; font-weight: 800; "
                f"border: 2.5px solid #f59e0b; border-radius: {s(14)}px; "
                f"background: #fffbeb; color: #1e293b;"
            )
            self._show_status("Naqd pulni qayta saning va summani kiriting.", "#f59e0b")

        elif self._verification_state == "second":
            if not self.cash_input.text().strip():
                self._show_status("Summani kiriting!", "#dc2626")
                return

            if abs(cash_amount - self._first_cash_amount) < 0.01:
                self._submit_closing()
            else:
                self._verification_state = "first"
                self._first_cash_amount = None
                self.cash_input.setText("")
                self.btn_close.setText("KASSANI YOPISH")
                self.step_label.setText("NAQD PULNI SANING VA KIRITING")
                self.step_label.setStyleSheet(
                    f"font-size: {font(11)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;"
                )
                self.numpad_lbl.setText("NAQD PUL SUMMASI")
                self.numpad_lbl.setStyleSheet(
                    f"font-size: {font(12)}px; font-weight: 800; color: #64748b; letter-spacing: 2px;"
                )
                self.cash_input.setStyleSheet(
                    f"padding: {s(12)}px {s(20)}px; font-size: {font(32)}px; font-weight: 800; "
                    f"border: 2.5px solid #3b82f6; border-radius: {s(14)}px; "
                    f"background: #eff6ff; color: #1e293b;"
                )
                self._show_status("❌  Summa mos kelmadi. Qaytadan saning.", "#dc2626")

    def _submit_closing(self):
        self.btn_close.setEnabled(False)
        self.btn_close.setText("Kassa yopilmoqda...")
        self.status_label.setVisible(False)

        try:
            actual_cash = float(self.cash_input.text() or 0)
        except ValueError:
            actual_cash = 0.0

        payment_reconciliation = []
        for rec in self.reconciliation_data:
            mop = rec["mode_of_payment"]
            is_cash = (mop == self._cash_key)
            payment_reconciliation.append({
                "mode_of_payment": mop,
                "opening_amount": rec["opening_amount"],
                "expected_amount": rec["expected_amount"],
                # Naqd: kassir kiritgan; boshqalar: avtomatik expected_amount
                "closing_amount": actual_cash if is_cash else float(rec["expected_amount"]),
            })

        self.closing_worker = ClosingWorker(self.api, self.opening_entry, payment_reconciliation)
        self.closing_worker.result_ready.connect(self._on_closing_finished)
        self.closing_worker.start()

    def _on_closing_finished(self, success: bool, message: str, z_report_data: object):
        self.btn_close.setEnabled(True)
        self.btn_close.setText("KASSANI YOPISH")

        if success:
            self._print_z_report(z_report_data if isinstance(z_report_data, dict) else {})
            self.closing_completed.emit()
            self.accept()
        else:
            logger.error("Kassa yopish xatosi: %s", message)
            self._verification_state = "first"
            self._first_cash_amount = None
            self.cash_input.setText("")
            self.btn_close.setText("KASSANI YOPISH")
            self.step_label.setText("NAQD PULNI SANING VA KIRITING")
            self.step_label.setStyleSheet(
                f"font-size: {font(11)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;"
            )
            self.cash_input.setStyleSheet(
                f"padding: {s(12)}px {s(20)}px; font-size: {font(32)}px; font-weight: 800; "
                f"border: 2.5px solid #3b82f6; border-radius: {s(14)}px; "
                f"background: #eff6ff; color: #1e293b;"
            )
            self._show_status(f"❌  Xatolik: {message}", "#dc2626")

    def _print_z_report(self, z_report_data: dict):
        """Z-otchyotni printerga yuborish. Backend javobidagi ma'lumotlardan foydalanadi."""
        try:
            from core.printer import print_z_report
            from core.config import load_config

            cfg = load_config()

            # Backend z_report_data dan olingan ma'lumotlar
            if z_report_data:
                expected_cash = float(z_report_data.get("expected_cash", 0))
                actual_cash = float(z_report_data.get("actual_cash", 0))
                cash_diff = float(z_report_data.get("cash_diff", 0))
                total_sales = float(z_report_data.get("total_sales", 0))
                total_invoices = z_report_data.get("total_invoices", self.total_invoices)
                payments = z_report_data.get("payments", [])
            else:
                # Fallback: lokal hisoblash (backend z_report_data qaytarmagan holda)
                try:
                    actual_cash = float(self.cash_input.text() or 0)
                except ValueError:
                    actual_cash = 0.0

                expected_cash = 0.0
                total_sales = 0.0
                payments = []
                for rec in self.reconciliation_data:
                    mop = rec["mode_of_payment"]
                    exp = float(rec.get("expected_amount", 0))
                    total_sales += exp
                    is_cash = (mop == self._cash_key)
                    if is_cash:
                        expected_cash = exp
                    payments.append({
                        "mode_of_payment": mop,
                        "expected_amount": exp,
                        "closing_amount": actual_cash if is_cash else exp,
                    })

                cash_diff = actual_cash - expected_cash
                total_invoices = self.total_invoices

            report_data = {
                "terminal_name": cfg.get("company", "JAZIRA POS"),
                "pos_profile": cfg.get("pos_profile", ""),
                "shift_id": self.opening_entry or "—",
                "cashier": cfg.get("cashier", cfg.get("user", "—")),
                "opened_at": "—",
                "closed_at": datetime.now().strftime("%Y-%m-%d  %H:%M"),
                "payments": payments,
                "total_invoices": total_invoices,
                "total_sales": total_sales,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "cash_diff": cash_diff,
            }

            ok = print_z_report(report_data)
            if not ok:
                logger.info("Z-report chop etilmadi (printer sozlanmagan yoki o'chirilgan)")
        except Exception as e:
            logger.error("Z-report print xatosi: %s", e)
