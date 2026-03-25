import json
import uuid
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame, QGridLayout,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from core.api import FrappeAPI
from core.config import load_config
from core.logger import get_logger
from database.models import PendingInvoice, db
from core.qz_printer import print_receipt
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
                    self._save_offline(response)
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
                    self._save_offline(f"To'lovda xatolik (make_invoice): {submit_response}", sync_order_name=invoice_name)
            else:
                self._save_offline(response)
        finally:
            if not db.is_closed():
                db.close()

    def _save_offline(self, error, sync_order_name=None):
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
        self.setFixedSize(s(880), s(620))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("background: white;")

        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(s(20), s(20), s(20), s(20))
        main_h_layout.setSpacing(s(20))

        # ── LEFT PANEL ───────────────────────────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(s(12))

        total_card = QFrame()
        total_card.setStyleSheet(f"background-color: #1f2937; border-radius: {s(10)}px; padding: {s(15)}px;")
        total_layout = QVBoxLayout(total_card)

        lbl_title = QLabel("JAMI SUMMA")
        lbl_title.setStyleSheet(f"color: #9ca3af; font-size: {font(12)}px; font-weight: bold;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(lbl_title)

        self.lbl_total = QLabel(f"{self.total_amount:,.0f} UZS".replace(",", " "))
        self.lbl_total.setStyleSheet(f"color: #ffffff; font-size: {font(32)}px; font-weight: bold;")
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        total_layout.addWidget(self.lbl_total)
        left_layout.addWidget(total_card)

        pay_label = QLabel("TO'LOV TURLARI")
        pay_label.setStyleSheet(f"font-size: {font(10)}px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        left_layout.addWidget(pay_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(s(8))

        config = load_config()
        payment_methods = config.get("payment_methods", ["Cash"])
        self.primary_input = None

        _active_css = (
            f"padding: {s(10)}px {s(14)}px; font-size: {font(18)}px; font-weight: 700; "
            f"border: 2px solid #3b82f6; border-radius: {s(10)}px; background: #eff6ff; color: #1e293b;"
        )
        _normal_css = (
            f"padding: {s(10)}px {s(14)}px; font-size: {font(18)}px; font-weight: 700; "
            f"border: 1.5px solid #e2e8f0; border-radius: {s(10)}px; background: white; color: #1e293b;"
        )
        self._active_css = _active_css
        self._normal_css = _normal_css

        for idx, mode in enumerate(payment_methods):
            row = QHBoxLayout()
            lbl = QLabel(mode)
            lbl.setStyleSheet(f"font-size: {font(14)}px; font-weight: 600; color: #334155;")

            input_field = ClickableLineEdit()
            input_field.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            input_field.setPlaceholderText("0")

            if idx == 0:
                input_field.setText(str(round(self.total_amount)))
                self.active_input = input_field
                self.primary_input = input_field
                input_field.setFocus()
                input_field.setStyleSheet(_active_css)
            else:
                input_field.setStyleSheet(_normal_css)

            input_field.setFixedWidth(s(190))
            input_field.setFixedHeight(s(48))
            input_field.setAlignment(Qt.AlignmentFlag.AlignRight)
            input_field.clicked.connect(self._set_active_input)
            input_field.textChanged.connect(self._on_payment_changed)

            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(input_field)

            self.payment_inputs[mode] = input_field
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)

        self.lbl_remaining = QLabel("To'lov summasi to'liq yopildi")
        self.lbl_remaining.setStyleSheet(
            f"font-size: {font(16)}px; font-weight: 700; color: #16a34a; padding: {s(6)}px;"
        )
        self.lbl_remaining.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.lbl_remaining)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(s(10))

        btn_cancel = QPushButton("Bekor")
        btn_cancel.setFixedHeight(s(52))
        btn_cancel.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; font-size: {font(14)}px; border-radius: {s(12)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("TO'LOV QILISH")
        self.btn_confirm.setFixedHeight(s(52))
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #22c55e, stop:1 #16a34a);
                color: white; font-weight: 800; font-size: {font(15)}px;
                border-radius: {s(12)}px; border: none; }}
            QPushButton:hover {{ background: #15803d; }}
            QPushButton:disabled {{ background: #d1fae5; color: #86efac; }}
        """)
        self.btn_confirm.clicked.connect(self._process_checkout)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_confirm, 2)
        left_layout.addLayout(btn_layout)

        main_h_layout.addWidget(left_widget, 1)

        # ── RIGHT PANEL — Numpad + Quick amounts ─────────────
        right_widget = QWidget()
        right_widget.setStyleSheet(f"background: #f8fafc; border-radius: {s(14)}px;")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(s(12), s(12), s(12), s(12))
        right_layout.setSpacing(s(10))

        numpad_lbl = QLabel("MIQDOR KIRITING")
        numpad_lbl.setStyleSheet(f"font-size: {font(10)}px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        right_layout.addWidget(numpad_lbl)

        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self._on_numpad_clicked)
        right_layout.addWidget(self.numpad)

        quick_lbl = QLabel("TEZKOR SUMMA")
        quick_lbl.setStyleSheet(f"font-size: {font(10)}px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        right_layout.addWidget(quick_lbl)

        quick_layout = QGridLayout()
        quick_layout.setSpacing(s(6))
        amounts = [1000, 5000, 10000, 20000, 50000, 100000, "MAX"]
        r, c = 0, 0
        for amt in amounts:
            display_text = f"{amt:,}".replace(",", " ") if isinstance(amt, int) else "MAX"
            btn = QPushButton(display_text)
            btn.setFixedSize(s(100), s(48))
            if amt == "MAX":
                btn.setStyleSheet(f"""
                    QPushButton {{ background: #3b82f6; color: white;
                        font-weight: 700; font-size: {font(13)}px; border-radius: {s(8)}px; border: none; }}
                    QPushButton:hover {{ background: #2563eb; }}
                """)
                btn.clicked.connect(self._fill_max)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: white; color: #334155;
                        font-weight: 600; font-size: {font(12)}px;
                        border-radius: {s(8)}px; border: 1px solid #e2e8f0; }}
                    QPushButton:hover {{ background: #f1f5f9; }}
                """)
                btn.clicked.connect(lambda checked, a=amt: self._add_quick_amount(a))
            quick_layout.addWidget(btn, r, c)
            c += 1
            if c > 2:
                c = 0
                r += 1
        right_layout.addLayout(quick_layout)
        main_h_layout.addWidget(right_widget)
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
        if remaining > 0:
            self.lbl_remaining.setText(f"Qolgan summa: {remaining:,.0f} UZS".replace(",", " "))
            self.lbl_remaining.setStyleSheet(f"color: #dc2626; font-weight: bold; font-size: {font(18)}px;")
            self.btn_confirm.setEnabled(False)
        else:
            if remaining == 0:
                self.lbl_remaining.setText("To'lov yopildi")
            else:
                self.lbl_remaining.setText(f"QAYTIM: {abs(remaining):,.0f} UZS")
            color = "#16a34a" if remaining == 0 else "#2563eb"
            self.lbl_remaining.setStyleSheet(f"color: {color}; font-weight: bold; font-size: {font(18)}px;")
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
            "mode_of_payment": payments[0]["mode_of_payment"] if payments else "Cash",
            "customer": str(self.order_data.get("customer", "guest")),
            "no_of_pax": 1,
            "last_invoice": "",
            "waiter": str(config.get("cashier", "Administrator")),  # server API talab qiladi
            "pos_profile": str(config.get("pos_profile", "")),
            "order_type": str(self.order_data.get("order_type", "Shu yerda")),
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
        }

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
