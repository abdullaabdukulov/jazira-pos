"""Kassa yopish dialogi — POS Closing Entry yaratish (elite dizayn)."""
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer
from PyQt6.QtGui import QDoubleValidator, QFont
from core.api import FrappeAPI
from core.logger import get_logger
from database.models import PosShift, db
from ui.components.numpad import TouchNumpad
from ui.components.dialogs import ClickableLineEdit
from ui.scale import s, font

logger = get_logger(__name__)


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
_EMERALD_700 = "#047857"
_RED_700 = "#b91c1c"
_RED_600 = "#dc2626"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"
_AMBER_700 = "#b45309"
_AMBER_500 = "#f59e0b"
_AMBER_50 = "#fffbeb"


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
        self.setMinimumSize(s(960), s(720))
        self.resize(s(1100), s(780))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(28), s(18), s(28), s(18))
        root.setSpacing(s(12))

        # ── Header (caps title + close) ───────────────
        header = QHBoxLayout()
        header.setSpacing(s(12))

        title_block = QVBoxLayout()
        title_block.setSpacing(s(3))

        title = QLabel("KASSA YOPISH")
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

        subtitle = QLabel("Smena yakunini tasdiqlash va Z-hisobot chiqarish")
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
        header.addLayout(title_block)
        header.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(40), s(40))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
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
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        root.addLayout(header)

        # Gradient hairline (red accent — danger context)
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {_RED_600}, stop:0.15 {_SLATE_100}, stop:1 {_SLATE_100});"
            f" border: none;"
        )
        root.addWidget(sep)

        # ── Main horizontal split ───────────────────
        main_h = QHBoxLayout()
        main_h.setContentsMargins(0, s(6), 0, 0)
        main_h.setSpacing(s(20))
        root.addLayout(main_h)

        # ── LEFT PANEL ───────────────────────────
        left = QWidget()
        self.left_layout = QVBoxLayout(left)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(s(12))

        # Info card — red-tinted danger context with gold accent border-left
        info_card = QFrame()
        info_card.setStyleSheet(f"""
            QFrame {{
                background: {_SLATE_900};
                border-radius: {s(12)}px;
                border: 1px solid {_SLATE_800};
                border-left: 4px solid {_RED_600};
            }}
        """)
        ic_layout = QVBoxLayout(info_card)
        ic_layout.setContentsMargins(s(24), s(18), s(24), s(18))
        ic_layout.setSpacing(s(8))

        ic_title = QLabel("SMENA YAKUNI")
        ic_title.setFrameShape(QFrame.Shape.NoFrame)
        _ict_font = QFont()
        _ict_font.setPixelSize(font(10))
        _ict_font.setWeight(QFont.Weight.Black)
        _ict_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        ic_title.setFont(_ict_font)
        ic_title.setStyleSheet(
            f"color: #fca5a5; background: transparent;"
            f" border: none; outline: none;"
        )
        ic_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_layout.addWidget(ic_title)

        self.info_label = QLabel("Ma'lumotlar yuklanmoqda...")
        self.info_label.setFrameShape(QFrame.Shape.NoFrame)
        _il_font = QFont()
        _il_font.setPixelSize(font(20))
        _il_font.setWeight(QFont.Weight.Black)
        _il_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        self.info_label.setFont(_il_font)
        self.info_label.setStyleSheet(
            f"color: white; background: transparent;"
            f" border: none; outline: none;"
        )
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_layout.addWidget(self.info_label)
        self.left_layout.addWidget(info_card)

        # Loading label
        self.loading_label = QLabel("Serverdan ma'lumotlar olinmoqda...")
        self.loading_label.setFrameShape(QFrame.Shape.NoFrame)
        _ll_font = QFont()
        _ll_font.setPixelSize(font(12))
        _ll_font.setWeight(QFont.Weight.Medium)
        self.loading_label.setFont(_ll_font)
        self.loading_label.setStyleSheet(
            f"color: {_SLATE_500}; background: transparent;"
            f" border: none; outline: none; padding: {s(16)}px;"
        )
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_layout.addWidget(self.loading_label)

        # ── NAQD PUL KIRISH ────────────────────────
        self.cash_section = QWidget()
        self.cash_section.setVisible(False)
        cash_layout = QVBoxLayout(self.cash_section)
        cash_layout.setContentsMargins(0, 0, 0, 0)
        cash_layout.setSpacing(s(8))

        self.step_label = QLabel("NAQD PULNI SANANG VA KIRITING")
        self.step_label.setFrameShape(QFrame.Shape.NoFrame)
        _sl_font = QFont()
        _sl_font.setPixelSize(font(10))
        _sl_font.setWeight(QFont.Weight.Black)
        _sl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        self.step_label.setFont(_sl_font)
        self.step_label.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        cash_layout.addWidget(self.step_label)

        self.cash_input = ClickableLineEdit()
        self.cash_input.setValidator(QDoubleValidator(0.0, 999_999_999.0, 2))
        self.cash_input.setPlaceholderText("0")
        self.cash_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.cash_input.setFixedHeight(s(72))
        self.cash_input.setStyleSheet(self._input_css("step1"))
        cash_layout.addWidget(self.cash_input)

        self.left_layout.addWidget(self.cash_section)
        self.left_layout.addStretch()

        # Status label
        self.status_label = QLabel()
        self.status_label.setFrameShape(QFrame.Shape.NoFrame)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        self.left_layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(s(12))

        btn_cancel = QPushButton("BEKOR")
        btn_cancel.setFixedHeight(s(56))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {_SLATE_100};
                color: {_SLATE_700};
                font-weight: 800;
                font-size: {font(13)}px;
                letter-spacing: 2px;
                border-radius: {s(10)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_200}; color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_300}; }}
        """)
        btn_cancel.clicked.connect(self.reject)

        self.btn_close = QPushButton("KASSANI YOPISH")
        self.btn_close.setFixedHeight(s(56))
        self.btn_close.setEnabled(False)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background: {_RED_600};
                color: white;
                font-weight: 900;
                font-size: {font(14)}px;
                letter-spacing: 2px;
                border-radius: {s(10)}px;
                border: 1px solid {_RED_600};
                outline: none;
            }}
            QPushButton:hover {{ background: {_RED_700}; border-color: {_RED_700}; }}
            QPushButton:pressed {{ background: #991b1b; }}
            QPushButton:disabled {{
                background: {_SLATE_100};
                color: {_SLATE_400};
                border-color: {_SLATE_200};
            }}
        """)
        self.btn_close.clicked.connect(self._process_closing)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_close, 2)
        self.left_layout.addLayout(btn_layout)

        main_h.addWidget(left, 1)

        # ── RIGHT PANEL — Numpad ─────────────
        right = QWidget()
        right.setStyleSheet(
            f"background: {_SLATE_50};"
            f" border-radius: {s(14)}px;"
            f" border: 1px solid {_SLATE_200};"
        )
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(s(18), s(18), s(18), s(18))
        right_layout.setSpacing(s(14))

        self.numpad_lbl = QLabel("NAQD PUL SUMMASI")
        self.numpad_lbl.setFrameShape(QFrame.Shape.NoFrame)
        _nl_font = QFont()
        _nl_font.setPixelSize(font(10))
        _nl_font.setWeight(QFont.Weight.Black)
        _nl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        self.numpad_lbl.setFont(_nl_font)
        self.numpad_lbl.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        right_layout.addWidget(self.numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        right_layout.addStretch()

        main_h.addWidget(right, 1)

    @staticmethod
    def _input_css(state: str) -> str:
        """Cash input style by step: step1 (initial), step2 (verify), error."""
        common = (
            f"padding: {s(12)}px {s(20)}px;"
            f" font-size: {font(28)}px;"
            f" font-weight: 800;"
            f" border-radius: {s(12)}px;"
            f" outline: none;"
            f" color: {_SLATE_900};"
        )
        if state == "step2":
            return (
                f"{common}"
                f" border: 2px solid {_AMBER_500};"
                f" background: {_AMBER_50};"
            )
        # step1 / default
        return (
            f"{common}"
            f" border: 2px solid {_GOLD};"
            f" background: #fff7ed;"
        )

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
            f"font-size: {font(13)}px; font-weight: 800;"
            f" letter-spacing: 0.5px;"
            f" color: {color}; background: transparent;"
            f" border: none; outline: none;"
            f" padding: {s(6)}px;"
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
                self._show_status("Naqd pul summasini kiriting!", _RED_600)
                return
            self._first_cash_amount = cash_amount
            self.cash_input.setText("")
            self._verification_state = "second"
            self.btn_close.setText("TASDIQLASH")
            self.step_label.setText("2-QADAM: QAYTA SANANG VA KIRITING")
            self.step_label.setStyleSheet(
                f"color: {_AMBER_500}; background: transparent;"
                f" border: none; outline: none;"
            )
            self.numpad_lbl.setText("QAYTA SANANG — TASDIQLASH")
            self.numpad_lbl.setStyleSheet(
                f"color: {_AMBER_500}; background: transparent;"
                f" border: none; outline: none;"
            )
            self.cash_input.setStyleSheet(self._input_css("step2"))
            self._show_status(
                "Naqd pulni qayta sanang va summani kiriting.",
                _AMBER_500,
            )

        elif self._verification_state == "second":
            if not self.cash_input.text().strip():
                self._show_status("Summani kiriting!", _RED_600)
                return

            if abs(cash_amount - self._first_cash_amount) < 0.01:
                self._submit_closing()
            else:
                self._verification_state = "first"
                self._first_cash_amount = None
                self.cash_input.setText("")
                self.btn_close.setText("KASSANI YOPISH")
                self.step_label.setText("NAQD PULNI SANANG VA KIRITING")
                self.step_label.setStyleSheet(
                    f"color: {_SLATE_400}; background: transparent;"
                    f" border: none; outline: none;"
                )
                self.numpad_lbl.setText("NAQD PUL SUMMASI")
                self.numpad_lbl.setStyleSheet(
                    f"color: {_SLATE_400}; background: transparent;"
                    f" border: none; outline: none;"
                )
                self.cash_input.setStyleSheet(self._input_css("step1"))
                self._show_status(
                    "Summa mos kelmadi. Qaytadan sanang.",
                    _RED_600,
                )

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
            self.step_label.setText("NAQD PULNI SANANG VA KIRITING")
            self.step_label.setStyleSheet(
                f"color: {_SLATE_400}; background: transparent;"
                f" border: none; outline: none;"
            )
            self.cash_input.setStyleSheet(self._input_css("step1"))
            self._show_status(f"Xatolik: {message}", _RED_600)

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
