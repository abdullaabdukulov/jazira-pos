from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QPushButton, QLabel, QHBoxLayout, QMessageBox, 
                             QComboBox, QLineEdit, QGroupBox, QGridLayout)
from PyQt6.QtCore import pyqtSignal, Qt
from database.models import Customer, db
from core.config import load_config
from ui.components.keyboard import TouchKeyboard

class QtyLabel(QLabel):
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        self.clicked.emit()

class CartWidget(QWidget):
    checkout_requested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.items = {} 
        self.ticket_order_types = ["Shu yerda", "Saboy"]
        self.total_amount = 0.0
        self.current_order_type = "Shu yerda"
        self.order_type_buttons = {} # text: button_obj
        self.init_ui()
        self.load_customers()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)

        # --- Touch Friendly Order Details ---
        details_group = QGroupBox("Buyurtma ma'lumotlari")
        details_group.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 10px; margin-top: 5px; background: #f9fafb; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #6b7280; }
        """)
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(10, 15, 10, 10)
        details_layout.setSpacing(12)

        # 1. Order Type Buttons (Big & Tapable)
        type_label = QLabel("BUYURTMA TURI:")
        type_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: bold;")
        details_layout.addWidget(type_label)

        types_layout = QHBoxLayout()
        types_layout.setSpacing(5)
        order_types = ["Shu yerda", "Saboy", "Dastavka", "Dastavka Saboy"]
        
        for t in order_types:
            btn = QPushButton(t)
            btn.setFixedHeight(50)
            btn.setCheckable(True)
            btn.setStyleSheet(self.get_order_type_style(False))
            btn.clicked.connect(lambda checked, val=t: self.set_order_type(val))
            types_layout.addWidget(btn, 1)
            self.order_type_buttons[t] = btn
        
        # Select default
        self.order_type_buttons["Shu yerda"].setChecked(True)
        self.order_type_buttons["Shu yerda"].setStyleSheet(self.get_order_type_style(True))
        
        details_layout.addLayout(types_layout)

        # 2. Middle Row: Sticker and Customer
        middle_row = QHBoxLayout()
        middle_row.setSpacing(10)

        # Sticker
        sticker_vbox = QVBoxLayout()
        sticker_label = QLabel("STIKER:")
        sticker_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: bold;")
        self.ticket_input = QLineEdit()
        self.ticket_input.setReadOnly(True)
        self.ticket_input.setPlaceholderText("—")
        self.ticket_input.setFixedHeight(55)
        self.ticket_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ticket_input.setStyleSheet(self.get_input_style())
        self.ticket_input.mousePressEvent = self.open_ticket_numpad
        sticker_vbox.addWidget(sticker_label)
        sticker_vbox.addWidget(self.ticket_input)
        middle_row.addLayout(sticker_vbox, 1)

        # Customer
        customer_vbox = QVBoxLayout()
        customer_label = QLabel("MIJOZ:")
        customer_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: bold;")
        self.customer_combo = QComboBox()
        self.customer_combo.setEditable(True)
        self.customer_combo.setFixedHeight(55)
        self.customer_combo.setStyleSheet(self.get_input_style())
        customer_vbox.addWidget(customer_label)
        customer_vbox.addWidget(self.customer_combo)
        middle_row.addLayout(customer_vbox, 3)

        details_layout.addLayout(middle_row)

        # 3. Comment
        comment_label = QLabel("IZOH:")
        comment_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: bold;")
        self.comment_input = QLineEdit()
        self.comment_input.setReadOnly(True)
        self.comment_input.setPlaceholderText("Buyurtma izohi...")
        self.comment_input.setFixedHeight(50)
        self.comment_input.setStyleSheet(self.get_input_style())
        self.comment_input.mousePressEvent = self.open_comment_keyboard
        details_layout.addWidget(comment_label)
        details_layout.addWidget(self.comment_input)

        main_layout.addWidget(details_group)

        # --- Cart Table ---
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nomi", "Miqdor", "Narx", "Summa"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 160) # Slightly wider for safety

        main_layout.addWidget(self.table)

        # --- Totals Area ---
        totals_layout = QHBoxLayout()
        self.total_label = QLabel("0 UZS")
        self.total_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #111827;")
        totals_layout.addWidget(self.total_label)
        
        self.clear_btn = QPushButton("Tozalash")
        self.clear_btn.setFixedSize(100, 50)
        self.clear_btn.setStyleSheet("""
            QPushButton { background-color: #fee2e2; color: #b91c1c; font-weight: bold; border-radius: 8px; }
            QPushButton:pressed { background-color: #fecaca; }
        """)
        self.clear_btn.clicked.connect(self.clear_cart)
        totals_layout.addWidget(self.clear_btn)
        
        main_layout.addLayout(totals_layout)

        # --- Checkout Button ---
        self.checkout_btn = QPushButton("TO'LOV QILISH (F12)")
        self.checkout_btn.setFixedHeight(75)
        self.checkout_btn.setStyleSheet("""
            QPushButton { background-color: #10b981; color: white; font-size: 24px; font-weight: bold; border-radius: 12px; }
            QPushButton:hover { background-color: #059669; }
            QPushButton:pressed { background-color: #047857; }
        """)
        self.checkout_btn.clicked.connect(self.handle_checkout)
        main_layout.addWidget(self.checkout_btn)

        self.setLayout(main_layout)
        self.set_order_type("Shu yerda")

    def get_order_type_style(self, is_active):
        if is_active:
            return """
                QPushButton { 
                    background-color: #3b82f6; color: white; border: none; 
                    border-radius: 8px; font-weight: bold; font-size: 13px; 
                }
            """
        return """
            QPushButton { 
                background-color: white; color: #374151; border: 1px solid #d1d5db; 
                border-radius: 8px; font-weight: 500; font-size: 13px; 
            }
        """

    def get_input_style(self):
        return """
            QLineEdit, QComboBox {
                padding: 10px; font-size: 16px; border: 1px solid #d1d5db; 
                border-radius: 8px; background-color: white; color: #111827;
            }
            QComboBox::drop-down { border: none; }
        """

    def set_order_type(self, order_type):
        self.current_order_type = order_type
        for t, btn in self.order_type_buttons.items():
            active = (t == order_type)
            btn.setChecked(active)
            btn.setStyleSheet(self.get_order_type_style(active))
        
        # Logic for sticker input
        needs_ticket = order_type in self.ticket_order_types
        self.ticket_input.setEnabled(needs_ticket)
        if not needs_ticket:
            self.ticket_input.clear()
            self.ticket_input.setStyleSheet(self.get_input_style() + "background-color: #f3f4f6;")
        else:
            self.ticket_input.setStyleSheet(self.get_input_style() + "border: 2px solid #3b82f6;")

    def open_ticket_numpad(self, event):
        if not self.ticket_input.isEnabled(): return
        kb = TouchKeyboard(self, initial_text=self.ticket_input.text(), title="Stiker raqami", is_numeric=True)
        kb.text_confirmed.connect(self.ticket_input.setText)
        kb.exec()

    def open_comment_keyboard(self, event):
        kb = TouchKeyboard(self, initial_text=self.comment_input.text(), title="Buyurtma izohi", is_numeric=False)
        kb.text_confirmed.connect(self.comment_input.setText)
        kb.exec()

    def load_customers(self):
        try:
            db.connect(reuse_if_open=True)
            customers = ["guest"]
            customers.extend([c.name for c in Customer.select()])
            self.customer_combo.addItems(customers)
        except: pass
        finally:
            if not db.is_closed(): db.close()

    def add_item(self, item_code, item_name, price, currency):
        if item_code in self.items:
            self.items[item_code]['qty'] = int(self.items[item_code]['qty'] + 1)
        else:
            self.items[item_code] = {'name': item_name, 'price': price, 'qty': 1, 'currency': currency}
        self.refresh_table()

    def update_qty(self, item_code, change):
        if item_code in self.items:
            self.items[item_code]['qty'] = int(self.items[item_code]['qty'] + change)
            if self.items[item_code]['qty'] <= 0:
                del self.items[item_code]
            self.refresh_table()

    def update_qty_absolute(self, item_code, new_qty_str):
        try:
            # Strictly convert to integer
            new_qty = int(float(new_qty_str))
            if new_qty > 0:
                self.items[item_code]['qty'] = new_qty
            else:
                del self.items[item_code]
            self.refresh_table()
        except: pass

    def refresh_table(self):
        self.table.setRowCount(0)
        total_amount = 0.0
        currency = "UZS"
        for row_idx, (code, data) in enumerate(self.items.items()):
            self.table.insertRow(row_idx)
            self.table.setRowHeight(row_idx, 65)
            
            name_item = QTableWidgetItem(data['name'])
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.table.setItem(row_idx, 0, name_item)
            
            qty_widget = QWidget()
            qty_layout = QHBoxLayout(qty_widget)
            qty_layout.setContentsMargins(5, 5, 5, 5)
            qty_layout.setSpacing(5)
            
            btn_style = "QPushButton { font-size: 22px; font-weight: bold; background: #f3f4f6; border-radius: 8px; color: #374151; }"
            btn_minus = QPushButton("-")
            btn_minus.setFixedSize(45, 45)
            btn_minus.setStyleSheet(btn_style)
            btn_minus.clicked.connect(lambda checked, c=code: self.update_qty(c, -1))
            
            # Using integer formatted string
            qty_label = QtyLabel(str(int(data['qty'])))
            qty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_label.setFixedWidth(60)
            qty_label.setStyleSheet("""
                font-size: 18px; 
                font-weight: bold; 
                color: #1f2937; 
                background-color: #f3f4f6; 
                border-radius: 6px;
                padding: 5px;
            """)
            qty_label.clicked.connect(lambda c=code, q=str(int(data['qty'])): self.open_qty_numpad(c, q))
            
            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(45, 45)
            btn_plus.setStyleSheet(btn_style)
            btn_plus.clicked.connect(lambda checked, c=code: self.update_qty(c, 1))
            
            qty_layout.addWidget(btn_minus)
            qty_layout.addWidget(qty_label)
            qty_layout.addWidget(btn_plus)
            self.table.setCellWidget(row_idx, 1, qty_widget)
            
            price_item = QTableWidgetItem(f"{data['price']:,.0f}".replace(',', ' '))
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(row_idx, 2, price_item)
            
            amount = int(data['qty']) * data['price']
            total_amount += amount
            currency = data['currency']
            
            amount_item = QTableWidgetItem(f"{amount:,.0f}".replace(',', ' '))
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(row_idx, 3, amount_item)

        self.total_label.setText(f"{total_amount:,.0f} {currency}".replace(',', ' '))
        self.total_amount = total_amount

    def open_qty_numpad(self, item_code, current_qty):
        kb = TouchKeyboard(self, initial_text=current_qty, title="Miqdorni kiriting", is_numeric=True)
        kb.text_confirmed.connect(lambda val: self.update_qty_absolute(item_code, val))
        kb.exec()

    def clear_cart(self):
        self.items.clear()
        self.ticket_input.clear()
        self.comment_input.clear()
        self.refresh_table()

    def handle_checkout(self):
        if not self.items:
            QMessageBox.warning(self, "Xatolik", "Savat bo'sh!")
            return
        
        ticket_number = self.ticket_input.text().strip()
        selected_customer = self.customer_combo.currentText().strip() or "guest"

        if self.current_order_type in self.ticket_order_types and not ticket_number:
            QMessageBox.warning(self, "Xatolik", "Stiker raqamini kiriting!")
            return

        order_data = {
            'items': [{'item_code': k, **v} for k, v in self.items.items()],
            'total_amount': self.total_amount,
            'order_type': self.current_order_type,
            'ticket_number': ticket_number,
            'customer': selected_customer,
            'comment': self.comment_input.text().strip()
        }
        self.checkout_requested.emit(order_data)
