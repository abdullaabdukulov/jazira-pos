# type:ignore
import json
import uuid
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame, QGridLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QFont
from core.api import FrappeAPI
from core.config import load_config
from core.constants import ORDER_TYPE_MAP
from core.logger import get_logger
from database.models import PendingInvoice, db
from database.invoice_processor import is_permanent_error
from core.printer import print_receipt
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
_EMERALD_600 = "#059669"
_EMERALD_700 = "#047857"
_EMERALD_50 = "#ecfdf5"
_EMERALD_200 = "#a7f3d0"
_RED_700 = "#b91c1c"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"


class CheckoutWorker(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, invoice_data: dict, payments: list, offline_id: str, api: FrappeAPI,
                 existing_invoice: str = ""):
        super().__init__()
        # Idempotency key — offline_id (UUID) ni server tomonga `client_ref` sifatida
        # jo'natamiz. Server bir xil UUID bilan kelgan sync_order so'rovini
        # bitta POS Invoice ga ulaydi (tarmoq response yo'qolsa ham duplikat yo'q).
        self.invoice_data = dict(invoice_data)
        self.invoice_data["client_ref"] = offline_id
        self.payments = payments
        self.offline_id = offline_id
        self.api = api
        # Phase 3 TZ #12: pending listdan davom etish — mavjud Draft POS Invoice
        # uchun sync_order chaqirilmaydi, faqat make_invoice
        self.existing_invoice = existing_invoice or ""

    def run(self):
        try:
            if self.existing_invoice:
                self._submit_existing()
                return

            # Yangi buyurtma flow — sync_order + make_invoice
            success, response = self.api.call_method(
                "ury.ury.doctype.ury_order.ury_order.sync_order", self.invoice_data
            )

            if success and isinstance(response, dict):
                if response.get("status") == "Failure":
                    error_msg = str(response.get("message") or response)
                    if is_permanent_error(error_msg):
                        self.result_ready.emit(False, f"Server rad etdi: {error_msg}")
                    else:
                        self._save_offline(error_msg)
                    return

                invoice_name = response.get("name")
                if not invoice_name:
                    self._save_offline("Chek raqami (invoice name) qaytmadi")
                    return

                self._make_invoice(invoice_name)
            else:
                # sync_order muvaffaqiyatsiz
                error_msg = str(response)
                if is_permanent_error(error_msg):
                    # 417/403/404 — server bu buyurtmani qabul qilmaydi,
                    # retry qilsa ham foyda yo'q → oflayn saqlamaymiz
                    self.result_ready.emit(False, f"Server xatosi: {error_msg}")
                else:
                    # Tarmoq muammosi — oflayn saqlash, keyinroq retry
                    self._save_offline(error_msg)
        finally:
            if not db.is_closed():
                db.close()

    def _submit_existing(self):
        """Pending listdan kelgan mavjud Draft uchun faqat make_invoice (TZ #12)."""
        try:
            self._make_invoice(self.existing_invoice)
        except Exception as e:
            logger.error("Existing invoice submit xatosi: %s", e)
            self.result_ready.emit(False, f"To'lovda xatolik: {e}")

    def _make_invoice(self, invoice_name: str):
        # KPI: pending dan to'lov bo'lsa, server invoice.cashier ni shu kassir
        # email'iga yangilaydi (waiter — ofitsant — o'zgartirilmaydi).
        # active_cashier — aktiv kassirning ismi (chek va custom field uchun).
        payment_payload = {
            "customer": self.invoice_data.get("customer"),
            "payments": self.payments,
            "cashier": self.invoice_data.get("cashier"),
            "pos_profile": self.invoice_data.get("pos_profile"),
            "owner": self.invoice_data.get("owner"),
            "additionalDiscount": 0,
            "table": None,
            "invoice": invoice_name,
            "active_cashier": self.invoice_data.get("active_cashier", ""),
            "active_cashier_role": self.invoice_data.get("active_cashier_role", "Kassir"),
        }
        submit_success, submit_response = self.api.call_method(
            "ury.ury.doctype.ury_order.ury_order.make_invoice", payment_payload
        )
        if submit_success:
            self.result_ready.emit(True, "To'lov muvaffaqiyatli yakunlandi!")
        else:
            logger.error(
                "make_invoice xatosi — invoice=%s, existing=%s, table=%s, payments=%s: %s",
                invoice_name, bool(self.existing_invoice),
                self.invoice_data.get("table"), self.payments, submit_response,
            )
            # Existing invoice uchun oflayn saqlash mantiqsiz — invoice
            # allaqachon serverda. Faqat xatoni qaytaramiz.
            if self.existing_invoice:
                self.result_ready.emit(False, f"To'lovda xatolik: {submit_response}")
            else:
                # Yangi flow — sync_order muvaffaqiyatli o'tdi (invoice serverda bor).
                # make_invoice xatosi bo'lsa ham True emit qilamiz, lekin retry uchun
                # oflayn ham saqlaymiz.
                self._save_offline(
                    f"To'lovda xatolik (make_invoice): {submit_response}",
                    sync_order_name=invoice_name,
                    partial_success=True,
                )

    def _save_offline(self, error, sync_order_name=None, partial_success=False):
        try:
            if not PendingInvoice.select().where(PendingInvoice.offline_id == self.offline_id).exists():
                save_data = dict(self.invoice_data)
                save_data["_payments"] = self.payments
                if sync_order_name:
                    save_data["_sync_order_name"] = sync_order_name
                PendingInvoice.create(
                    offline_id=self.offline_id,
                    invoice_data=json.dumps(save_data),
                    status="Pending",
                    error_message=str(error),
                )
            if partial_success:
                # Buyurtma serverda bor, faqat invoice yaratish kechikdi
                self.result_ready.emit(True, "Buyurtma qabul qilindi! Invoice keyinroq yaratiladi.")
            else:
                self.result_ready.emit(False, "Server bilan aloqa yo'qligi sababli chek oflayn saqlandi!")
        except Exception as e:
            logger.error("Oflayn saqlashda xatolik: %s", e)
            self.result_ready.emit(False, f"Oflayn saqlashda xatolik: {e}")


class CheckoutWindow(QDialog):
    checkout_completed = pyqtSignal()

    def __init__(self, parent, order_data: dict, api: FrappeAPI):
        super().__init__(parent)
        self.api = api
        self.order_data = order_data
        self.total_amount = float(order_data.get("total_amount", 0.0))
        self.payment_inputs = {}
        self.active_input = None
        self._is_calculating = False
        self.offline_id = str(uuid.uuid4())
        self.init_ui()
        QTimer.singleShot(50, self._center_on_parent)

    def _center_on_parent(self):
        if self.parent():
            p_geo = self.parent().frameGeometry()
            c_geo = self.frameGeometry()
            c_geo.moveCenter(p_geo.center())
            self.move(c_geo.topLeft())

    def init_ui(self):
        self.setWindowTitle("To'lov")
        self.setMinimumSize(s(960), s(680))
        self.resize(s(1100), s(780))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(28), s(16), s(28), s(16))
        root.setSpacing(s(10))

        # ── Header (caps title + close) ───────────────
        header = QHBoxLayout()
        header.setSpacing(s(12))

        # Title block — sarlavha + subtitle (gold accent)
        title_block = QVBoxLayout()
        title_block.setSpacing(s(3))

        title = QLabel("TO'LOV")
        title.setFrameShape(QFrame.Shape.NoFrame)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _tf = QFont()
        _tf.setPixelSize(font(22))
        _tf.setWeight(QFont.Weight.Black)
        _tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        title.setFont(_tf)
        title.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        title_block.addWidget(title)

        subtitle = QLabel("Buyurtmani yakunlash uchun summa kiriting")
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
                background: white;
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        root.addLayout(header)

        # Hairline + tag aksent (oltin)
        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {_GOLD}, stop:0.15 {_SLATE_100}, stop:1 {_SLATE_100});"
            f" border: none;"
        )
        root.addWidget(sep)

        main_h_layout = QHBoxLayout()
        main_h_layout.setContentsMargins(0, s(8), 0, 0)
        main_h_layout.setSpacing(s(20))
        root.addLayout(main_h_layout)

        # ── LEFT PANEL ───────────────────────────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(s(10))

        # Jami summa kartasi — slate-900 + gold accent border (kompakt)
        total_card = QFrame()
        total_card.setStyleSheet(f"""
            QFrame {{
                background: {_SLATE_900};
                border-radius: {s(12)}px;
                border: 1px solid {_SLATE_800};
                border-left: 4px solid {_GOLD};
            }}
        """)
        total_layout = QVBoxLayout(total_card)
        total_layout.setContentsMargins(s(24), s(14), s(24), s(14))
        total_layout.setSpacing(s(4))

        lbl_title = QLabel("JAMI TO'LOV SUMMASI")
        lbl_title.setFrameShape(QFrame.Shape.NoFrame)
        _lt_font = QFont()
        _lt_font.setPixelSize(font(10))
        _lt_font.setWeight(QFont.Weight.Black)
        _lt_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        lbl_title.setFont(_lt_font)
        lbl_title.setStyleSheet(
            f"color: {_GOLD_LIGHT}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(lbl_title)

        self.lbl_total = QLabel(f"{self.total_amount:,.0f} UZS".replace(",", " "))
        self.lbl_total.setFrameShape(QFrame.Shape.NoFrame)
        _tot_font = QFont()
        _tot_font.setPixelSize(font(30))
        _tot_font.setWeight(QFont.Weight.Black)
        _tot_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        self.lbl_total.setFont(_tot_font)
        self.lbl_total.setStyleSheet(
            f"color: white; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(self.lbl_total)
        left_layout.addWidget(total_card)

        # Qolgan / qaytim holati — jami summa ostida (kompakt)
        self.lbl_remaining = QLabel("Yuklanmoqda...")
        self.lbl_remaining.setFrameShape(QFrame.Shape.NoFrame)
        self.lbl_remaining.setFixedHeight(s(40))
        self.lbl_remaining.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _rem_font = QFont()
        _rem_font.setPixelSize(font(13))
        _rem_font.setWeight(QFont.Weight.Black)
        _rem_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.lbl_remaining.setFont(_rem_font)
        # Boshlang'ich stilini _update_remaining_label belgilab beradi
        left_layout.addWidget(self.lbl_remaining)

        # To'lov turlari sarlavhasi
        pay_label = QLabel("TO'LOV TURLARI")
        pay_label.setFrameShape(QFrame.Shape.NoFrame)
        _pl_font = QFont()
        _pl_font.setPixelSize(font(10))
        _pl_font.setWeight(QFont.Weight.Black)
        _pl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        pay_label.setFont(_pl_font)
        pay_label.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        left_layout.addWidget(pay_label)

        # Inputlar scroll ichida — ekran kichik bo'lsa ham sig'adi
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(s(10))
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        config = load_config()
        payment_methods = config.get("payment_methods", ["Cash"])
        self.primary_input = None

        self._active_css = (
            f"padding: {s(8)}px {s(14)}px; font-size: {font(16)}px; font-weight: 800; "
            f"border: 2px solid {_GOLD}; border-radius: {s(8)}px; "
            f"background: #fff7ed; color: {_SLATE_900}; outline: none;"
        )
        self._normal_css = (
            f"padding: {s(8)}px {s(14)}px; font-size: {font(16)}px; font-weight: 800; "
            f"border: 1px solid {_SLATE_200}; border-radius: {s(8)}px; "
            f"background: white; color: {_SLATE_900}; outline: none;"
        )

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
            lbl_font = QFont()
            lbl_font.setPixelSize(font(15))
            lbl_font.setWeight(QFont.Weight.Bold)
            lbl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
            lbl.setFont(lbl_font)
            lbl.setStyleSheet(
                f"color: {_SLATE_900};"
                f" background: transparent; border: none; outline: none;"
            )
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            input_field = ClickableLineEdit()
            input_field.setValidator(QDoubleValidator(0.0, 999_999_999.0, 2))
            input_field.setPlaceholderText("0")
            input_field.setMinimumWidth(s(200))
            input_field.setFixedHeight(s(44))
            input_field.setAlignment(Qt.AlignmentFlag.AlignRight)
            input_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            if idx == 0:
                input_field.setText(str(round(self.total_amount)))
                self.active_input = input_field
                self.primary_input = input_field
                input_field.setFocus()
                input_field.setStyleSheet(self._active_css)
            else:
                input_field.setStyleSheet(self._normal_css)

            input_field.clicked.connect(self._set_active_input)
            input_field.textChanged.connect(self._on_payment_changed)

            row.addWidget(lbl)
            row.addWidget(input_field)

            self.payment_inputs[mode] = input_field
            scroll_layout.addWidget(row_frame)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll, stretch=1)

        # Tugmalar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(s(14))

        btn_cancel = QPushButton("BEKOR")
        btn_cancel.setFixedHeight(s(54))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {_SLATE_100};
                color: {_SLATE_700};
                font-weight: 800;
                font-size: {font(14)}px;
                letter-spacing: 2px;
                border-radius: {s(12)}px;
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

        self.btn_confirm = QPushButton("TO'LOV QILISH")
        self.btn_confirm.setFixedHeight(s(54))
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{
                background: {_EMERALD_600};
                color: white;
                font-weight: 900;
                font-size: {font(16)}px;
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
            QPushButton:disabled {{
                background: {_SLATE_100};
                color: {_SLATE_400};
                border-color: {_SLATE_200};
            }}
        """)
        self.btn_confirm.clicked.connect(self._process_checkout)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_confirm, 3)
        left_layout.addLayout(btn_layout)

        main_h_layout.addWidget(left_widget, 3)

        # ── RIGHT PANEL — Numpad + Tezkor summalar ─────────────
        right_widget = QWidget()
        right_widget.setStyleSheet(
            f"background: {_SLATE_50};"
            f" border-radius: {s(14)}px;"
            f" border: 1px solid {_SLATE_200};"
        )
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(s(20), s(20), s(20), s(20))
        right_layout.setSpacing(s(14))

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setFrameShape(QFrame.Shape.NoFrame)
        _np_font = QFont()
        _np_font.setPixelSize(font(10))
        _np_font.setWeight(QFont.Weight.Black)
        _np_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        numpad_lbl.setFont(_np_font)
        numpad_lbl.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)

        # Tezkor summalar
        quick_lbl = QLabel("TEZKOR SUMMA")
        quick_lbl.setFrameShape(QFrame.Shape.NoFrame)
        quick_lbl.setFont(_np_font)
        quick_lbl.setStyleSheet(
            f"color: {_SLATE_400}; background: transparent;"
            f" border: none; outline: none;"
        )
        right_layout.addWidget(quick_lbl)

        quick_layout = QGridLayout()
        quick_layout.setSpacing(s(8))
        amounts = [1_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, "MAX"]
        r, c = 0, 0
        for amt in amounts:
            display = f"{amt:,}".replace(",", " ") if isinstance(amt, int) else "MAX ↑"
            btn = QPushButton(display)
            btn.setFixedHeight(s(54))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if amt == "MAX":
                # MAX — gold accent (asosiy tezkor)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_GOLD};
                        color: white;
                        font-weight: 800;
                        font-size: {font(13)}px;
                        letter-spacing: 1.5px;
                        border-radius: {s(10)}px;
                        border: 1px solid {_GOLD};
                        outline: none;
                    }}
                    QPushButton:hover {{
                        background: {_GOLD_DEEP};
                        border-color: {_GOLD_DEEP};
                    }}
                    QPushButton:pressed {{ background: #855e30; }}
                """)
                btn.clicked.connect(self._fill_max)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: white;
                        color: {_SLATE_900};
                        font-weight: 700;
                        font-size: {font(13)}px;
                        border-radius: {s(10)}px;
                        border: 1px solid {_SLATE_200};
                        outline: none;
                    }}
                    QPushButton:hover {{
                        background: {_SLATE_50};
                        border-color: {_SLATE_300};
                    }}
                    QPushButton:pressed {{ background: {_SLATE_100}; }}
                """)
                btn.clicked.connect(lambda checked, a=amt: self._add_quick_amount(a))
            quick_layout.addWidget(btn, r, c)
            c += 1
            if c > 2:
                c = 0
                r += 1
        right_layout.addLayout(quick_layout)
        right_layout.addStretch()

        main_h_layout.addWidget(right_widget, 2)
        self._update_remaining_label()

    def _set_active_input(self, widget):
        self.active_input = widget
        for inp in self.payment_inputs.values():
            inp.setStyleSheet(self._active_css if inp == widget else self._normal_css)
        widget.setFocus()

    def _on_numpad_clicked(self, action: str):
        if not self.active_input:
            return
        t = self.active_input.text()
        if action == "CLEAR":
            self.active_input.clear()
        elif action == "BACKSPACE":
            self.active_input.setText(t[:-1])
        elif action == ".":
            if "." not in t:
                self.active_input.setText(t + ".")
        else:
            self.active_input.setText(t + action)

    def _add_quick_amount(self, amount: int):
        if not self.active_input:
            return
        try:
            curr = float(self.active_input.text() or 0)
            self.active_input.setText(str(round(curr + amount)))
        except ValueError:
            pass

    def _fill_max(self):
        if not self.active_input:
            return
        other = 0.0
        for inp in self.payment_inputs.values():
            if inp != self.active_input:
                try:
                    other += float(inp.text() or 0)
                except ValueError:
                    pass
        self.active_input.setText(str(round(max(0, self.total_amount - other))))

    def _on_payment_changed(self):
        if self._is_calculating:
            return
        self._is_calculating = True
        try:
            sender = self.sender()
            if sender is not self.primary_input and self.primary_input:
                other_total = 0.0
                for inp in self.payment_inputs.values():
                    if inp is self.primary_input:
                        continue
                    try:
                        other_total += float(inp.text().replace(" ", "") or 0)
                    except ValueError:
                        pass

                primary_amount = max(0, self.total_amount - other_total)
                self.primary_input.blockSignals(True)
                self.primary_input.setText(str(round(primary_amount)))
                self.primary_input.blockSignals(False)

            self._update_remaining_label()
        finally:
            self._is_calculating = False

    def _update_remaining_label(self):
        total_paid = 0.0
        for inp in self.payment_inputs.values():
            try:
                total_paid += float(inp.text().replace(" ", "") or 0)
            except ValueError:
                pass

        remaining = self.total_amount - total_paid
        # Border yo'q (sof matn) — faqat QAYTIM holatida alert chiqadi.
        # Bu vizual shovqinni kamaytiradi va payment'ga ko'proq joy qoldiradi.
        plain_base = (
            f"border-radius: {s(8)}px;"
            f" border: none; outline: none;"
            f" padding: 0; margin: 0;"
            f" background: transparent;"
        )

        if remaining > 0:
            text = f"QOLGAN  ·  {remaining:,.0f} UZS".replace(",", " ")
            self.lbl_remaining.setText(text)
            self.lbl_remaining.setStyleSheet(
                f"{plain_base} color: {_RED_700};"
            )
            self.btn_confirm.setEnabled(False)
        elif remaining == 0:
            self.lbl_remaining.setText("✓  TO'LOV TO'LIQ YOPILDI")
            self.lbl_remaining.setStyleSheet(
                f"{plain_base} color: {_EMERALD_700};"
            )
            self.btn_confirm.setEnabled(True)
        else:
            # QAYTIM — borderless gold text (xuddi boshqa holatlar kabi sof)
            qaytim = abs(remaining)
            text = f"QAYTIM  ·  {qaytim:,.0f} UZS".replace(",", " ")
            self.lbl_remaining.setText(text)
            self.lbl_remaining.setStyleSheet(
                f"{plain_base} color: {_GOLD_DEEP};"
            )
            self.btn_confirm.setEnabled(True)

    def _process_checkout(self):
        if not self.order_data.get("items"):
            from ui.components.dialogs import InfoDialog
            InfoDialog(self, "Xatolik", "Savat bo'sh — tovar qo'shing!", kind="error").exec()
            return

        self.btn_confirm.setEnabled(False)
        self.btn_confirm.setText("Yuborilmoqda...")

        payments = []
        for mode, inp in self.payment_inputs.items():
            try:
                amt = float(inp.text().replace(" ", "") or 0)
                if amt > 0:
                    payments.append({"mode_of_payment": mode, "amount": amt})
            except ValueError:
                pass

        config = load_config()

        # KPI uchun (TZ Phase 3):
        # - cashier = to'lov qabul qilayotgan aktiv kassirning email'i
        #   (POS Profile default emas — haqiqiy kassir ismida ko'rinishi kerak)
        # - waiter = zakazni qabul qilgan foydalanuvchi.
        #   Yangi to'lov (saqlashsiz): kassir o'zi → cashier bilan bir xil.
        #   Pending dan to'lov: ofitsant qo'ygan, kassir to'laydi → cashier
        #   yangilanadi, lekin waiter (ofitsant) o'zgartirilmaydi (server make_invoice).
        active_user = str(self.order_data.get("active_cashier_user") or "")
        default_user = str(config.get("cashier", "Administrator"))
        cashier_user = active_user or default_user
        waiter_user = active_user or default_user

        payload = {
            "items": [
                {
                    "item": str(i["item_code"]),
                    "item_name": str(i["name"]),
                    "qty": float(i["qty"]),
                    "rate": float(i["price"]),
                    "comment": "",
                }
                for i in self.order_data["items"]
            ],
            "cashier": cashier_user,
            "owner": str(config.get("owner", "Administrator")),
            "mode_of_payment": payments[0]["mode_of_payment"] if payments else (config.get("payment_methods") or ["Cash"])[0],
            "customer": str(self.order_data.get("customer") or config.get("default_customer", "")),
            "no_of_pax": 1,
            "last_invoice": "",
            "waiter": waiter_user,
            "pos_profile": str(config.get("pos_profile", "")),
            "order_type": ORDER_TYPE_MAP.get(self.order_data.get("order_type", "Shu yerda"), "Dine In"),
            "ticket_number": (
                int(self.order_data.get("ticket_number", 0))
                if self.order_data.get("ticket_number")
                else 0
            ),
            "comments": str(self.order_data.get("comment") or ""),
            "room": "",
            "aggregator_id": "",
            "total_amount": float(self.total_amount),
            "custom_offline_id": self.offline_id,
            "active_cashier": str(self.order_data.get("active_cashier", "")),
            "active_cashier_role": str(self.order_data.get("active_cashier_role", "Kassir")),
            "table": (str(self.order_data.get("restaurant_table", "")) or None),
        }
        logger.info("Checkout payload: %s", json.dumps(payload, ensure_ascii=False))

        # Phase 3 TZ #12: pending listdan davom etish — existing_invoice uzatamiz
        existing_invoice = str(self.order_data.get("existing_invoice", ""))
        self.worker = CheckoutWorker(
            payload, payments, self.offline_id, self.api,
            existing_invoice=existing_invoice,
        )
        self.worker.result_ready.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self, success: bool, message: str):
        from ui.components.dialogs import InfoDialog
        if success or "oflayn saqlandi" in message.lower():
            kind = "success" if success else "warning"
            title = "Muvaffaqiyatli" if success else "Oflayn saqlandi"
            InfoDialog(self, title, message, kind=kind).exec()
            self._finalize_checkout()
        else:
            InfoDialog(self, "Xatolik", message, kind="error").exec()
            self.btn_confirm.setEnabled(True)
            self.btn_confirm.setText("✓  TO'LOV QILISH")

    def _finalize_checkout(self):
        final_payments = []
        for mode, inp in self.payment_inputs.items():
            try:
                amt = float(inp.text().replace(" ", "") or 0)
                if amt > 0:
                    final_payments.append({"mode_of_payment": mode, "amount": amt})
            except ValueError:
                pass

        # KOT dublikatining oldini olish:
        # - existing_invoice bor bo'lsa (pending listdan to'lov) → KOT save paytida
        #   allaqachon chiqqan, hozir faqat mijoz cheki
        # - existing_invoice yo'q bo'lsa (yangi yangi to'lov) → ikkala chek
        is_pending_pay = bool(self.order_data.get("existing_invoice"))
        try:
            results = print_receipt(
                self, self.order_data, final_payments,
                include_customer=True,
                include_production=not is_pending_pay,
            )
            failed = [k for k, v in results.items() if not v]
            if failed:
                logger.warning("Printerlar chop etilmadi: %s", ", ".join(failed))
                self._show_printer_warning(failed)
        except Exception as e:
            logger.error("Chek chop etishda xatolik: %s", e)

        self.checkout_completed.emit()
        self.accept()

    def reject(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            return  # Worker ishlayotganda dialog yopilmasin
        super().reject()

    def _show_printer_warning(self, failed_printers: list):
        """Printer xatosi haqida foydalanuvchiga ogohlantirish (yumshoq)."""
        from ui.components.dialogs import InfoDialog
        names = ", ".join(failed_printers)
        InfoDialog(
            self, "Printer ulanmagan",
            f"To'lov muvaffaqiyatli yakunlandi ✓\n\n"
            f"Lekin chek printeri ({names}) ulanmagan.\n"
            f"Iltimos, printerni tekshiring yoki chekni qo'lda yetkazing.",
            kind="info",
            icon="🖨️",
        ).exec()
