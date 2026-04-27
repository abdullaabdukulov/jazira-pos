# type:ignore
import json
import uuid
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame, QGridLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
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


class CheckoutWorker(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, invoice_data: dict, payments: list, offline_id: str, api: FrappeAPI):
        super().__init__()
        self.invoice_data = invoice_data
        self.payments = payments
        self.offline_id = offline_id
        self.api = api

    def run(self):
        try:
            # Shared API orqali chaqiriladi
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

                payment_payload = {
                    "customer": self.invoice_data.get("customer"),
                    "payments": self.payments,
                    "cashier": self.invoice_data.get("cashier"),
                    "pos_profile": self.invoice_data.get("pos_profile"),
                    "owner": self.invoice_data.get("owner"),
                    "additionalDiscount": 0,
                    "table": None,
                    "invoice": invoice_name,
                }

                submit_success, submit_response = self.api.call_method(
                    "ury.ury.doctype.ury_order.ury_order.make_invoice", payment_payload
                )

                if submit_success:
                    self.result_ready.emit(True, "To'lov muvaffaqiyatli yakunlandi!")
                else:
                    # sync_order muvaffaqiyatli o'tdi — buyurtma serverda bor.
                    # make_invoice xatosi bo'lsa ham chek chiqaramiz (True emit),
                    # lekin keyinchalik qayta urinish uchun oflayn ham saqlaymiz.
                    self._save_offline(
                        f"To'lovda xatolik (make_invoice): {submit_response}",
                        sync_order_name=invoice_name,
                        partial_success=True,
                    )
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
        self.resize(s(1100), s(820))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(s(28), s(28), s(28), s(28))
        main_h_layout.setSpacing(s(24))

        # ── LEFT PANEL ───────────────────────────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(s(16))

        # Jami summa kartasi
        total_card = QFrame()
        total_card.setStyleSheet(f"background: #0f172a; border-radius: {s(14)}px;")
        total_layout = QVBoxLayout(total_card)
        total_layout.setContentsMargins(s(24), s(20), s(24), s(20))
        total_layout.setSpacing(s(6))

        lbl_title = QLabel("JAMI TO'LOV SUMMASI")
        lbl_title.setStyleSheet(
            f"color: #64748b; font-size: {font(11)}px; font-weight: 700; letter-spacing: 2px;"
        )
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(lbl_title)

        self.lbl_total = QLabel(f"{self.total_amount:,.0f} UZS".replace(",", " "))
        self.lbl_total.setStyleSheet(
            f"color: #f8fafc; font-size: {font(38)}px; font-weight: 900;"
        )
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(self.lbl_total)
        left_layout.addWidget(total_card)

        # Qolgan / qaytim holati — jami summa ostida
        self.lbl_remaining = QLabel("Yuklanmoqda...")
        self.lbl_remaining.setFixedHeight(s(52))
        self.lbl_remaining.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_remaining.setStyleSheet(
            f"font-size: {font(20)}px; font-weight: 800; color: #16a34a; "
            f"background: #f0fdf4; border-radius: {s(10)}px; border: 2px solid #bbf7d0;"
        )
        left_layout.addWidget(self.lbl_remaining)

        # To'lov turlari sarlavhasi
        pay_label = QLabel("TO'LOV TURLARI")
        pay_label.setStyleSheet(
            f"font-size: {font(11)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;"
        )
        left_layout.addWidget(pay_label)

        # Inputlar scroll ichida — ekran kichik bo'lsa ham sig'adi
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(s(12))
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        config = load_config()
        payment_methods = config.get("payment_methods", ["Cash"])
        self.primary_input = None

        self._active_css = (
            f"padding: {s(12)}px {s(18)}px; font-size: {font(22)}px; font-weight: 800; "
            f"border: 2.5px solid #3b82f6; border-radius: {s(12)}px; "
            f"background: #eff6ff; color: #1e293b;"
        )
        self._normal_css = (
            f"padding: {s(12)}px {s(18)}px; font-size: {font(22)}px; font-weight: 800; "
            f"border: 1.5px solid #e2e8f0; border-radius: {s(12)}px; "
            f"background: white; color: #1e293b;"
        )

        for idx, mode in enumerate(payment_methods):
            row_frame = QFrame()
            row_frame.setStyleSheet(
                f"QFrame {{ background: {'#f8fafc' if idx % 2 == 0 else 'white'}; "
                f"border-radius: {s(10)}px; }}"
            )
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(s(14), s(8), s(14), s(8))
            row.setSpacing(s(12))

            lbl = QLabel(mode)
            lbl.setStyleSheet(
                f"font-size: {font(16)}px; font-weight: 700; color: #334155; background: transparent;"
            )
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            input_field = ClickableLineEdit()
            input_field.setValidator(QDoubleValidator(0.0, 999_999_999.0, 2))
            input_field.setPlaceholderText("0")
            input_field.setMinimumWidth(s(220))
            input_field.setFixedHeight(s(60))
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

        btn_cancel = QPushButton("✕  Bekor")
        btn_cancel.setFixedHeight(s(64))
        btn_cancel.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: {font(15)}px;
                border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; color: #334155; }}
            QPushButton:pressed {{ background: #cbd5e1; }}
        """)
        btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("✓  TO'LOV QILISH")
        self.btn_confirm.setFixedHeight(s(64))
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{ background: #16a34a;
                color: white; font-weight: 900; font-size: {font(17)}px;
                border-radius: {s(14)}px; border: none; }}
            QPushButton:hover {{ background: #15803d; }}
            QPushButton:pressed {{ background: #166534; }}
            QPushButton:disabled {{ background: #d1fae5; color: #86efac; }}
        """)
        self.btn_confirm.clicked.connect(self._process_checkout)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_confirm, 3)
        left_layout.addLayout(btn_layout)

        main_h_layout.addWidget(left_widget, 3)

        # ── RIGHT PANEL — Numpad + Tezkor summalar ─────────────
        right_widget = QWidget()
        right_widget.setStyleSheet(f"background: #f8fafc; border-radius: {s(16)}px;")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(s(20), s(20), s(20), s(20))
        right_layout.setSpacing(s(14))

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setStyleSheet(
            f"font-size: {font(11)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;"
        )
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)

        # Tezkor summalar
        quick_lbl = QLabel("TEZKOR SUMMA")
        quick_lbl.setStyleSheet(
            f"font-size: {font(11)}px; font-weight: 800; color: #94a3b8; letter-spacing: 2px;"
        )
        right_layout.addWidget(quick_lbl)

        quick_layout = QGridLayout()
        quick_layout.setSpacing(s(8))
        amounts = [1_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, "MAX"]
        r, c = 0, 0
        for amt in amounts:
            display = f"{amt:,}".replace(",", " ") if isinstance(amt, int) else "MAX ↑"
            btn = QPushButton(display)
            btn.setFixedHeight(s(52))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if amt == "MAX":
                btn.setStyleSheet(f"""
                    QPushButton {{ background: #1d4ed8; color: white;
                        font-weight: 800; font-size: {font(13)}px;
                        border-radius: {s(10)}px; border: none; }}
                    QPushButton:hover {{ background: #1e40af; }}
                    QPushButton:pressed {{ background: #1e3a8a; }}
                """)
                btn.clicked.connect(self._fill_max)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: white; color: #1e293b;
                        font-weight: 700; font-size: {font(13)}px;
                        border-radius: {s(10)}px;
                        border: 1.5px solid #e2e8f0; }}
                    QPushButton:hover {{ background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }}
                    QPushButton:pressed {{ background: #dbeafe; }}
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
        fs = f"font-size: {font(20)}px; font-weight: 800; border-radius: {s(10)}px; border: 2px solid"

        if remaining > 0:
            text = f"Qolgan: {remaining:,.0f} UZS".replace(",", " ")
            self.lbl_remaining.setText(text)
            self.lbl_remaining.setStyleSheet(
                f"{fs} #fca5a5; color: #dc2626; background: #fff1f2;"
            )
            self.btn_confirm.setEnabled(False)
        elif remaining == 0:
            self.lbl_remaining.setText("✓  To'lov to'liq yopildi")
            self.lbl_remaining.setStyleSheet(
                f"{fs} #86efac; color: #16a34a; background: #f0fdf4;"
            )
            self.btn_confirm.setEnabled(True)
        else:
            qaytim = abs(remaining)
            self.lbl_remaining.setText(f"QAYTIM: {qaytim:,.0f} UZS".replace(",", " "))
            self.lbl_remaining.setStyleSheet(
                f"{fs} #93c5fd; color: #1d4ed8; background: #eff6ff;"
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
            "cashier": str(config.get("cashier", "Administrator")),
            "owner": str(config.get("owner", "Administrator")),
            "mode_of_payment": payments[0]["mode_of_payment"] if payments else (config.get("payment_methods") or ["Cash"])[0],
            "customer": str(self.order_data.get("customer") or config.get("default_customer", "")),
            "no_of_pax": 1,
            "last_invoice": "",
            "waiter": str(config.get("cashier", "Administrator")),  # server API talab qiladi
            "pos_profile": str(config.get("pos_profile", "")),
            "order_type": ORDER_TYPE_MAP.get(self.order_data.get("order_type", "Shu yerda"), "Dine In"),
            "ticket_number": (
                int(self.order_data.get("ticket_number", 0))
                if self.order_data.get("ticket_number")
                else 0
            ),
            "comments": str(self.order_data.get("comment", "")),
            "room": "",
            "aggregator_id": "",
            "total_amount": float(self.total_amount),
            "custom_offline_id": self.offline_id,
            "active_cashier": str(self.order_data.get("active_cashier", "")),
        }
        # MANA SHU YERDA QO'SHASIZ:
        import json
        print("\n=== YUBORILAYOTGAN PAYLOAD ===")
        print(json.dumps(payload, indent=4, ensure_ascii=False))
        print("==============================\n")
        logger.info(f"Yuborilayotgan payload: {json.dumps(payload, ensure_ascii=False)}")

        self.worker = CheckoutWorker(payload, payments, self.offline_id, self.api)

        self.worker = CheckoutWorker(payload, payments, self.offline_id, self.api)
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

        try:
            results = print_receipt(self, self.order_data, final_payments)
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
        """Printer xatosi haqida foydalanuvchiga ogohlantirish"""
        from ui.components.dialogs import InfoDialog
        names = ", ".join(failed_printers)
        InfoDialog(
            self, "Printer xatosi",
            f"Quyidagi printerlar chop etilmadi:\n{names}\n\nBuyurtma saqlandi.",
            kind="warning",
        ).exec()
