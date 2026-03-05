import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QMessageBox, QScrollArea, QWidget, QFrame, QGridLayout)
from PyQt6.QtCore import pyqtSignal, Qt, QThread, QTimer, QEvent
from PyQt6.QtGui import QDoubleValidator
from core.api import FrappeAPI
from database.models import PendingInvoice, db
from core.printer import print_receipt
from core.config import load_config
from ui.components.numpad import TouchNumpad

class ClickableLineEdit(QLineEdit):
    clicked = pyqtSignal(object)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self)

class CheckoutWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, invoice_data, payments):
        super().__init__()
        self.invoice_data = invoice_data
        self.payments = payments
        self.api = FrappeAPI()

    def run(self):
        # Step 1: Create Draft POS Invoice via sync_order
        success, response = self.api.call_method("ury.ury.doctype.ury_order.ury_order.sync_order", self.invoice_data)
        
        if success and isinstance(response, dict):
            if response.get("status") == "Failure":
                self.save_offline(response)
                return
            
            invoice_name = response.get("name")
            if not invoice_name:
                self.save_offline("Chek raqami (invoice name) qaytmadi")
                return

            # Step 2: Submit the invoice and apply multiple payments via make_invoice
            payment_payload = {
                "customer": self.invoice_data.get("customer"),
                "payments": self.payments,
                "cashier": self.invoice_data.get("cashier"),
                "pos_profile": self.invoice_data.get("pos_profile"),
                "owner": self.invoice_data.get("owner"),
                "additionalDiscount": 0,
                "table": None,
                "invoice": invoice_name
            }

            submit_success, submit_response = self.api.call_method("ury.ury.doctype.ury_order.ury_order.make_invoice", payment_payload)

            if submit_success:
                self.finished.emit(True, "To'lov muvaffaqiyatli yakunlandi!")
            else:
                self.save_offline(f"To'lovda xatolik (make_invoice): {submit_response}")
        else:
            self.save_offline(response)

    def save_offline(self, error):
        try:
            db.connect(reuse_if_open=True)
            PendingInvoice.create(
                invoice_data=json.dumps(self.invoice_data),
                status="Pending",
                error_message=str(error)
            )
            self.finished.emit(False, f"Xato: {error}. Chek oflayn saqlandi!")
        except Exception as e:
            self.finished.emit(False, f"Oflayn saqlashda xatolik: {e}")
        finally:
            if not db.is_closed():
                db.close()

class CheckoutWindow(QDialog):
    checkout_completed = pyqtSignal()

    def __init__(self, parent, order_data):
        super().__init__(parent)
        self.order_data = order_data
        self.total_amount = float(order_data.get('total_amount', 0.0))
        self.payment_inputs = {} # mode_name: QLineEdit
        self.active_input = None
        self._is_calculating = False
        self.init_ui()
        QTimer.singleShot(50, self.center_on_parent)

    def center_on_parent(self):
        if self.parent():
            p_geo = self.parent().frameGeometry()
            c_geo = self.frameGeometry()
            c_geo.moveCenter(p_geo.center())
            self.move(c_geo.topLeft())

    def init_ui(self):
        self.setWindowTitle("To'lov")
        self.setFixedSize(850, 600) # Wider for Numpad
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(20, 20, 20, 20)
        main_h_layout.setSpacing(20)

        # --- LEFT SIDE: Payment Methods ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Total Header
        total_box = QFrame()
        total_box.setStyleSheet("background-color: #1f2937; border-radius: 10px; padding: 15px;")
        total_layout = QVBoxLayout(total_box)
        lbl_title = QLabel("JAMI SUMMA")
        lbl_title.setStyleSheet("color: #9ca3af; font-size: 12px; font-weight: bold;")
        total_layout.addWidget(lbl_title, alignment=Qt.AlignmentFlag.AlignCenter)
        self.lbl_total = QLabel(f"{self.total_amount:,.0f} UZS".replace(',', ' '))
        self.lbl_total.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold;")
        total_layout.addWidget(self.lbl_total, alignment=Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(total_box)

        # Payment Methods List
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(10)

        config = load_config()
        payment_methods = config.get("payment_methods", ["Cash"])

        for idx, mode in enumerate(payment_methods):
            row = QHBoxLayout()
            lbl = QLabel(mode)
            lbl.setStyleSheet("font-size: 16px; font-weight: 500;")
            
            input_field = ClickableLineEdit()
            input_field.setValidator(QDoubleValidator(0.0, 999999999.0, 2))
            input_field.setPlaceholderText("0")
            
            if idx == 0:
                input_field.setText(str(int(self.total_amount)))
                self.active_input = input_field
                input_field.setFocus()
                input_field.setStyleSheet("padding: 10px; font-size: 18px; font-weight: bold; border: 2px solid #3b82f6; border-radius: 6px; background: #eff6ff;")
            else:
                input_field.setStyleSheet("padding: 10px; font-size: 18px; font-weight: bold; border: 1px solid #d1d5db; border-radius: 6px; background: white;")

            input_field.setFixedWidth(180)
            input_field.setAlignment(Qt.AlignmentFlag.AlignRight)
            
            input_field.clicked.connect(self.set_active_input)
            input_field.textChanged.connect(self.calculate_remaining)

            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(input_field)
            
            self.payment_inputs[mode] = input_field
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)

        # Status Label
        self.lbl_remaining = QLabel("To'lov summasi to'liq yopildi ✅")
        self.lbl_remaining.setStyleSheet("font-size: 18px; font-weight: bold; color: #16a34a; padding: 10px;")
        left_layout.addWidget(self.lbl_remaining, alignment=Qt.AlignmentFlag.AlignCenter)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("BEKOR QILISH")
        btn_cancel.setFixedHeight(55)
        btn_cancel.setStyleSheet("background-color: #f3f4f6; color: #374151; font-weight: bold; border-radius: 10px;")
        btn_cancel.clicked.connect(self.reject)
        
        self.btn_confirm = QPushButton("TASDIQLASH")
        self.btn_confirm.setFixedHeight(55)
        self.btn_confirm.setEnabled(True)
        self.btn_confirm.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; border-radius: 10px; font-size: 16px;")
        self.btn_confirm.clicked.connect(self.process_checkout)
        
        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(self.btn_confirm, 2)
        left_layout.addLayout(btn_layout)

        main_h_layout.addWidget(left_widget, 1)

        # --- RIGHT SIDE: Numpad ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        self.numpad = TouchNumpad()
        self.numpad.digit_clicked.connect(self.on_numpad_clicked)
        right_layout.addWidget(self.numpad)
        
        # Quick amounts
        quick_layout = QGridLayout()
        quick_layout.setSpacing(8)
        amounts = [1000, 5000, 10000, 20000, 50000, 100000, "MAX"]
        r, c = 0, 0
        for amt in amounts:
            display_text = f"{amt:,}".replace(',', ' ') if isinstance(amt, int) else str(amt)
            btn = QPushButton(display_text)
            btn.setFixedSize(100, 50)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #f3f4f6;
                    color: #374151;
                    font-weight: bold;
                    font-size: 14px;
                    border: 1px solid #d1d5db;
                    border-radius: 8px;
                }
                QPushButton:pressed { background-color: #e5e7eb; }
            """)
            if amt == "MAX":
                btn.clicked.connect(self.fill_max)
                btn.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold; border-radius: 8px;")
            else:
                btn.clicked.connect(lambda checked, a=amt: self.add_quick_amount(a))
            
            quick_layout.addWidget(btn, r, c)
            c += 1
            if c > 2:
                c = 0
                r += 1
        
        right_layout.addLayout(quick_layout)
        main_h_layout.addWidget(right_widget)
        
        self.calculate_remaining()

    def set_active_input(self, widget):
        if self.active_input == widget: return
        self.active_input = widget
        for inp in self.payment_inputs.values():
            if inp == widget:
                inp.setStyleSheet("padding: 10px; font-size: 18px; font-weight: bold; border: 2px solid #3b82f6; border-radius: 6px; background: #eff6ff;")
            else:
                inp.setStyleSheet("padding: 10px; font-size: 18px; font-weight: bold; border: 2px solid #d1d5db; border-radius: 6px; background: white;")
        widget.setFocus()

    def on_numpad_clicked(self, action):
        if not self.active_input: return
        
        current_text = self.active_input.text()
        if action == 'CLEAR':
            self.active_input.clear()
        elif action == 'BACKSPACE':
            self.active_input.setText(current_text[:-1])
        elif action == '.':
            if '.' not in current_text:
                self.active_input.setText(current_text + '.')
        else:
            self.active_input.setText(current_text + action)
        
        self.calculate_remaining()

    def add_quick_amount(self, amount):
        if not self.active_input: return
        try:
            current = float(self.active_input.text() or 0)
            self.active_input.setText(str(int(current + amount)))
            self.calculate_remaining()
        except: pass

    def fill_max(self):
        if not self.active_input: return
        current_paid_others = 0.0
        for inp in self.payment_inputs.values():
            if inp != self.active_input:
                try: current_paid_others += float(inp.text() or 0)
                except: pass
        
        needed = max(0, self.total_amount - current_paid_others)
        self.active_input.setText(str(int(needed)))
        self.calculate_remaining()

    def calculate_remaining(self):
        if self._is_calculating:
            return
        self._is_calculating = True

        try:
            payment_methods = list(self.payment_inputs.keys())
            if not payment_methods: return
            
            remainder_field = self.payment_inputs[payment_methods[0]]
            
            if self.active_input and self.active_input != remainder_field:
                other_sum = 0.0
                for mode, inp in self.payment_inputs.items():
                    if inp != remainder_field:
                        try:
                            val = float(inp.text().replace(' ', '') or 0)
                            other_sum += val
                        except: pass
                
                new_cash = max(0, self.total_amount - other_sum)
                remainder_field.setText(str(int(new_cash)))

            total_paid = 0.0
            for inp in self.payment_inputs.values():
                try:
                    total_paid += float(inp.text().replace(' ', '') or 0)
                except: pass
            
            remaining = self.total_amount - total_paid
            
            if remaining > 0:
                self.lbl_remaining.setText(f"Qolgan summa: {remaining:,.0f} UZS".replace(',', ' '))
                self.lbl_remaining.setStyleSheet("color: #dc2626; font-weight: bold; font-size: 18px;")
                self.btn_confirm.setEnabled(False)
                self.btn_confirm.setStyleSheet("background-color: #d1d5db; color: #9ca3af; font-weight: bold; border-radius: 10px;")
            elif remaining == 0:
                self.lbl_remaining.setText("To'lov summasi yopildi ✅")
                self.lbl_remaining.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 18px;")
                self.btn_confirm.setEnabled(True)
                self.btn_confirm.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; border-radius: 10px;")
            else:
                self.lbl_remaining.setText(f"QAYTIM: {abs(remaining):,.0f} UZS".replace(',', ' '))
                self.lbl_remaining.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 22px;")
                self.btn_confirm.setEnabled(True)
                self.btn_confirm.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; border-radius: 10px;")
        finally:
            self._is_calculating = False

    def process_checkout(self):
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.setText("Yuborilmoqda...")

        payments = []
        for mode, inp in self.payment_inputs.items():
            try:
                amt = float(inp.text().replace(' ', '') or 0)
                if amt > 0:
                    payments.append({"mode_of_payment": mode, "amount": amt})
            except: pass

        config = load_config()
        payload = {
            "items": [{"item": str(i['item_code']), "item_name": str(i['name']), "qty": float(i['qty']), "rate": float(i['price']), "comment": ""} for i in self.order_data['items']],
            "cashier": str(config.get("cashier", "Administrator")),
            "owner": str(config.get("owner", "Administrator")),
            "mode_of_payment": payments[0]['mode_of_payment'] if payments else "Cash",
            "customer": str(self.order_data.get('customer', 'guest')),
            "no_of_pax": 1,
            "last_invoice": "",
            "waiter": str(config.get("waiter", config.get("cashier", "Administrator"))),
            "pos_profile": str(config.get("pos_profile", "")),
            "order_type": str(self.order_data.get('order_type', 'Shu yerda')),
            "ticket_number": int(self.order_data.get('ticket_number', 0)) if self.order_data.get('ticket_number') else 0,
            "comments": str(self.order_data.get('comment', '')),
            "room": "",
            "aggregator_id": "",
            "expected_amount": float(self.total_amount)
        }

        self.worker = CheckoutWorker(payload, payments)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self, success, message):
        if success:
            QMessageBox.information(self, "Muvaffaqiyatli", message)
            
            # Extract final payments list for the printer
            final_payments = []
            for mode, inp in self.payment_inputs.items():
                try:
                    amt = float(inp.text().replace(' ', '') or 0)
                    if amt > 0:
                        final_payments.append({"mode_of_payment": mode, "amount": amt})
                except: pass

            # Receipt printing with full payments list breakdown
            try:
                print_receipt(self, self.order_data, final_payments)
            except Exception as e:
                QMessageBox.warning(self, "Printer Xatosi", f"Chek chiqarishda xatolik: {e}")

            self.checkout_completed.emit()
            self.accept()
        else:
            QMessageBox.warning(self, "Xatolik", message)
            self.btn_confirm.setEnabled(True)
            self.btn_confirm.setText("TASDIQLASH")
