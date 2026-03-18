from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLabel, QHBoxLayout,
    QComboBox, QLineEdit, QGroupBox, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt
from database.models import Customer, db
from core.logger import get_logger
from core.constants import TICKET_ORDER_TYPES, ORDER_TYPES
from ui.components.keyboard import TouchKeyboard
from ui.components.dialogs import InfoDialog

logger = get_logger(__name__)


class QtyLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()


class CartWidget(QWidget):
    checkout_requested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.items = {}
        self.total_amount = 0.0
        self.current_order_type = ORDER_TYPES[0]
        self.order_type_buttons = {}
        self._numpad_mode = "ticket"   # "ticket" | "qty"
        self._active_qty_item = None
        self.init_ui()
        self.load_customers()

    # ─────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ── Order Details Card ────────────────
        details_group = QGroupBox("Buyurtma ma'lumotlari")
        details_group.setStyleSheet("""
            QGroupBox {
                font-weight: 700; font-size: 12px;
                border: 1.5px solid #e2e8f0;
                border-radius: 12px;
                margin-top: 6px;
                background: #f8fafc;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px;
                padding: 0 6px; color: #64748b;
                font-size: 11px; font-weight: 600;
            }
        """)
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(10, 12, 10, 10)
        details_layout.setSpacing(8)

        # Order Type
        type_label = QLabel("BUYURTMA TURI")
        type_label.setStyleSheet("""
            font-size: 10px; color: #94a3b8; font-weight: 700;
            letter-spacing: 1px; margin-bottom: 2px;
        """)
        details_layout.addWidget(type_label)

        types_layout = QHBoxLayout()
        types_layout.setSpacing(5)
        for t in ORDER_TYPES:
            btn = QPushButton(t)
            btn.setFixedHeight(50)
            btn.setCheckable(True)
            btn.setStyleSheet(self._order_type_style(False))
            btn.clicked.connect(lambda checked, val=t: self.set_order_type(val))
            types_layout.addWidget(btn, 1)
            self.order_type_buttons[t] = btn

        self.order_type_buttons[ORDER_TYPES[0]].setChecked(True)
        self.order_type_buttons[ORDER_TYPES[0]].setStyleSheet(self._order_type_style(True))
        details_layout.addLayout(types_layout)

        # Sticker + Customer row
        middle_row = QHBoxLayout()
        middle_row.setSpacing(10)

        sticker_vbox = QVBoxLayout()
        sticker_label = QLabel("STIKER")
        sticker_label.setStyleSheet("""
            font-size: 10px; color: #94a3b8; font-weight: 700; letter-spacing: 1px;
        """)
        self.ticket_input = QLineEdit()
        self.ticket_input.setReadOnly(True)
        self.ticket_input.setPlaceholderText("—")
        self.ticket_input.setFixedHeight(55)
        self.ticket_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ticket_input.setStyleSheet(self._input_style())
        self.ticket_input.mousePressEvent = self._open_ticket_numpad
        sticker_vbox.addWidget(sticker_label)
        sticker_vbox.addWidget(self.ticket_input)
        middle_row.addLayout(sticker_vbox, 1)

        customer_vbox = QVBoxLayout()
        customer_label = QLabel("MIJOZ")
        customer_label.setStyleSheet("""
            font-size: 10px; color: #94a3b8; font-weight: 700; letter-spacing: 1px;
        """)
        self.customer_combo = QComboBox()
        self.customer_combo.setEditable(True)
        self.customer_combo.setFixedHeight(55)
        self.customer_combo.setStyleSheet(self._input_style())
        customer_vbox.addWidget(customer_label)
        customer_vbox.addWidget(self.customer_combo)
        middle_row.addLayout(customer_vbox, 3)

        details_layout.addLayout(middle_row)

        # Comment
        comment_label = QLabel("IZOH")
        comment_label.setStyleSheet("""
            font-size: 10px; color: #94a3b8; font-weight: 700; letter-spacing: 1px;
        """)
        self.comment_input = QLineEdit()
        self.comment_input.setReadOnly(True)
        self.comment_input.setPlaceholderText("Buyurtma izohi...")
        self.comment_input.setFixedHeight(50)
        self.comment_input.setStyleSheet(self._input_style())
        self.comment_input.mousePressEvent = self._open_comment_keyboard
        details_layout.addWidget(comment_label)
        details_layout.addWidget(self.comment_input)

        main_layout.addWidget(details_group)

        # ── Cart Table ───────────────────────
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nomi", "Miqdor", "Narx", "Summa"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                border: none;
                background: white;
                font-size: 13px;
            }
            QTableWidget::item { padding: 4px 6px; }
            QTableWidget::item:selected { background: #dbeafe; color: #1e40af; }
            QHeaderView::section {
                background: #f8fafc;
                color: #94a3b8;
                font-weight: 700;
                font-size: 11px;
                letter-spacing: 0.5px;
                padding: 8px 6px;
                border: none;
                border-bottom: 1px solid #e2e8f0;
            }
        """)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 160)
        main_layout.addWidget(self.table)

        # ── Totals ───────────────────────────
        totals_layout = QHBoxLayout()
        totals_layout.setContentsMargins(4, 4, 4, 4)

        total_title = QLabel("Jami:")
        total_title.setStyleSheet("font-size: 13px; color: #64748b; font-weight: 600;")
        self.total_label = QLabel("0 UZS")
        self.total_label.setStyleSheet("font-size: 26px; font-weight: 800; color: #111827;")
        totals_layout.addWidget(total_title)
        totals_layout.addWidget(self.total_label)
        totals_layout.addStretch()

        self.clear_btn = QPushButton("Tozalash")
        self.clear_btn.setFixedSize(110, 48)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: #fee2e2; color: #b91c1c;
                font-weight: 600; font-size: 13px;
                border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #fecaca; }
            QPushButton:pressed { background: #fca5a5; }
        """)
        self.clear_btn.clicked.connect(self.clear_cart)
        totals_layout.addWidget(self.clear_btn)
        main_layout.addLayout(totals_layout)

        # ── Checkout Button ──────────────────
        self.checkout_btn = QPushButton("✓  TO'LOV QILISH  (F12)")
        self.checkout_btn.setFixedHeight(72)
        self.checkout_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #22c55e, stop:1 #16a34a);
                color: white; font-size: 20px;
                font-weight: 800; border-radius: 14px;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #16a34a, stop:1 #15803d);
            }
            QPushButton:pressed { background: #15803d; }
        """)
        self.checkout_btn.clicked.connect(self.handle_checkout)
        main_layout.addWidget(self.checkout_btn)

        # ── Inline bottom panels ─────────────
        self.numpad_panel = self._build_numpad_panel()
        self.numpad_panel.setVisible(False)
        main_layout.addWidget(self.numpad_panel)

        self.keyboard_panel = self._build_keyboard_panel()
        self.keyboard_panel.setVisible(False)
        main_layout.addWidget(self.keyboard_panel)

        self.setLayout(main_layout)
        self.set_order_type(ORDER_TYPES[0])

    # ─────────────────────────────────────────
    #  INLINE NUMPAD  (Stiker uchun)
    # ─────────────────────────────────────────
    def _build_numpad_panel(self):
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame { background: #f1f5f9; border-top: 2px solid #e2e8f0; }
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        # Display + close
        top = QHBoxLayout()
        self.numpad_display = QLabel("—")
        self.numpad_display.setFixedHeight(42)
        self.numpad_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.numpad_display.setStyleSheet("""
            font-size: 22px; font-weight: 700; color: #1e293b;
            background: white; border: 1.5px solid #3b82f6;
            border-radius: 8px; padding: 4px 12px;
        """)
        np_close = QPushButton("✕")
        np_close.setFixedSize(42, 42)
        np_close.setStyleSheet("""
            QPushButton { background:#ef4444; color:white; font-weight:bold;
                font-size:16px; border-radius:8px; border:none; }
            QPushButton:hover { background:#dc2626; }
        """)
        np_close.clicked.connect(self._close_panels)
        top.addWidget(self.numpad_display, stretch=1)
        top.addWidget(np_close)
        layout.addLayout(top)

        # Number grid (3x4)
        keys = [['7','8','9'], ['4','5','6'], ['1','2','3'], ['CLR','0','⌫']]
        for row_keys in keys:
            row = QHBoxLayout()
            row.setSpacing(6)
            for k in row_keys:
                row.addWidget(self._make_numpad_key(k))
            layout.addLayout(row)

        return panel

    def _make_numpad_key(self, key):
        label = 'TOZALASH' if key == 'CLR' else key
        btn = QPushButton(label)
        btn.setFixedHeight(52)
        if key == '⌫':
            style = "background:#fee2e2; color:#ef4444; font-size:20px; font-weight:bold;"
        elif key == 'CLR':
            style = "background:#fff7ed; color:#ea580c; font-size:11px; font-weight:bold;"
        else:
            style = "background:white; color:#1e293b; font-size:20px; font-weight:700;"
        btn.setStyleSheet(f"""
            QPushButton {{ {style} border:1px solid #e2e8f0; border-radius:8px; }}
            QPushButton:pressed {{ background:#dbeafe; }}
        """)
        btn.clicked.connect(lambda _, k=key: self._on_numpad_key(k))
        return btn

    def _on_numpad_key(self, key):
        if self._numpad_mode == "qty":
            cur = self.numpad_display.text()
            if cur == "—":
                cur = ""
            if key == '⌫':
                new = cur[:-1]
            elif key == 'CLR':
                new = ''
            else:
                new = cur + key
            self.numpad_display.setText(new or "—")
            # Darhol yangilaymiz
            if new and self._active_qty_item:
                self.update_qty_absolute(self._active_qty_item, new)
        else:
            cur = self.ticket_input.text()
            if key == '⌫':
                new = cur[:-1]
            elif key == 'CLR':
                new = ''
            else:
                new = cur + key
            self.ticket_input.setText(new)
            self.numpad_display.setText(new or "—")

    # ─────────────────────────────────────────
    #  INLINE KEYBOARD  (Izoh uchun)
    # ─────────────────────────────────────────
    def _build_keyboard_panel(self):
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame { background: #f1f5f9; border-top: 2px solid #e2e8f0; }
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(5)

        # Display + close
        top = QHBoxLayout()
        self.kb_display = QLabel("Izoh...")
        self.kb_display.setFixedHeight(38)
        self.kb_display.setStyleSheet("""
            font-size: 15px; font-weight: 600; color: #334155;
            background: white; border: 1.5px solid #3b82f6;
            border-radius: 8px; padding: 4px 12px;
        """)
        kb_close = QPushButton("✕")
        kb_close.setFixedSize(38, 38)
        kb_close.setStyleSheet("""
            QPushButton { background:#ef4444; color:white; font-weight:bold;
                font-size:14px; border-radius:8px; border:none; }
            QPushButton:hover { background:#dc2626; }
        """)
        kb_close.clicked.connect(self._close_panels)
        top.addWidget(self.kb_display, stretch=1)
        top.addWidget(kb_close)
        layout.addLayout(top)

        # Keyboard rows
        rows = [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['A','S','D','F','G','H','J','K','L','CLR'],
            ['Z','X','C','V','B','N','M','SPACE'],
        ]
        for row_keys in rows:
            row = QHBoxLayout()
            row.setSpacing(4)
            for k in row_keys:
                row.addWidget(self._make_kb_key(k))
            layout.addLayout(row)

        return panel

    def _make_kb_key(self, key):
        label = '␣' if key == 'SPACE' else ('TOZALASH' if key == 'CLR' else key)
        btn = QPushButton(label)
        btn.setFixedHeight(40)
        if key == '⌫':
            style = "background:#fee2e2; color:#ef4444; font-size:16px; font-weight:bold;"
        elif key == 'CLR':
            style = "background:#fff7ed; color:#ea580c; font-size:10px; font-weight:bold;"
        elif key == 'SPACE':
            style = "background:#eff6ff; color:#3b82f6; font-size:14px; font-weight:bold;"
            btn.setMinimumWidth(100)
        elif key.isdigit():
            style = "background:#e0e7ff; color:#3730a3; font-size:14px; font-weight:bold;"
        else:
            style = "background:white; color:#1e293b; font-size:13px; font-weight:600;"
        btn.setStyleSheet(f"""
            QPushButton {{ {style} border:1px solid #e2e8f0; border-radius:6px; }}
            QPushButton:pressed {{ background:#dbeafe; }}
        """)
        btn.clicked.connect(lambda _, k=key: self._on_kb_key(k))
        return btn

    def _on_kb_key(self, key):
        cur = self.comment_input.text()
        if key == '⌫':
            new = cur[:-1]
        elif key == 'CLR':
            new = ''
        elif key == 'SPACE':
            new = cur + ' '
        else:
            new = cur + key
        self.comment_input.setText(new)
        self.kb_display.setText(new or "Izoh...")

    # ─────────────────────────────────────────
    #  Panel open / close
    # ─────────────────────────────────────────
    def _open_ticket_numpad(self, event):
        if not self.ticket_input.isEnabled():
            return
        self.keyboard_panel.setVisible(False)
        self._numpad_mode = "ticket"
        self._active_qty_item = None
        self.numpad_display.setText(self.ticket_input.text() or "—")
        self.numpad_panel.setVisible(True)

    def _open_comment_keyboard(self, event):
        self.numpad_panel.setVisible(False)
        self.kb_display.setText(self.comment_input.text() or "Izoh...")
        self.keyboard_panel.setVisible(True)

    def _close_panels(self):
        self._numpad_mode = "ticket"
        self._active_qty_item = None
        self.numpad_panel.setVisible(False)
        self.keyboard_panel.setVisible(False)

    # ─────────────────────────────────────────
    #  Styles
    # ─────────────────────────────────────────
    @staticmethod
    def _order_type_style(is_active: bool) -> str:
        if is_active:
            return """
                QPushButton {
                    background: #3b82f6; color: white;
                    border: none; border-radius: 10px;
                    font-weight: 700; font-size: 13px;
                }
            """
        return """
            QPushButton {
                background: white; color: #475569;
                border: 1.5px solid #e2e8f0;
                border-radius: 10px; font-weight: 600; font-size: 13px;
            }
            QPushButton:hover { background: #eff6ff; color: #2563eb; border-color: #bfdbfe; }
        """

    @staticmethod
    def _input_style() -> str:
        return """
            QLineEdit, QComboBox {
                padding: 10px 14px;
                font-size: 15px;
                border: 1.5px solid #e2e8f0;
                border-radius: 10px;
                background: white;
                color: #1e293b;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #93c5fd;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { width: 14px; height: 14px; }
        """

    # ─────────────────────────────────────────
    #  Business logic
    # ─────────────────────────────────────────
    def set_order_type(self, order_type: str):
        self.current_order_type = order_type
        for t, btn in self.order_type_buttons.items():
            active = t == order_type
            btn.setChecked(active)
            btn.setStyleSheet(self._order_type_style(active))

        needs_ticket = order_type in TICKET_ORDER_TYPES
        self.ticket_input.setEnabled(needs_ticket)
        if not needs_ticket:
            self.ticket_input.clear()
            self.ticket_input.setStyleSheet(self._input_style() + "background-color: #f3f4f6;")
            self.numpad_panel.setVisible(False)
        else:
            self.ticket_input.setStyleSheet(self._input_style() + "border: 2px solid #3b82f6;")

    def load_customers(self):
        try:
            db.connect(reuse_if_open=True)
            customers = ["guest"]
            customers.extend([c.name for c in Customer.select()])
            self.customer_combo.addItems(customers)
        except Exception as e:
            logger.debug("Mijozlar yuklanmadi: %s", e)
        finally:
            if not db.is_closed():
                db.close()

    def add_item(self, item_code: str, item_name: str, price: float, currency: str):
        if item_code in self.items:
            self.items[item_code]["qty"] = int(self.items[item_code]["qty"] + 1)
        else:
            self.items[item_code] = {"name": item_name, "price": price, "qty": 1, "currency": currency}
        self.refresh_table()

    def update_qty(self, item_code: str, change: int):
        if item_code in self.items:
            self.items[item_code]["qty"] = int(self.items[item_code]["qty"] + change)
            if self.items[item_code]["qty"] <= 0:
                del self.items[item_code]
            self.refresh_table()

    def update_qty_absolute(self, item_code: str, new_qty_str: str):
        try:
            new_qty = int(float(new_qty_str))
            if new_qty > 0:
                self.items[item_code]["qty"] = new_qty
            else:
                del self.items[item_code]
            self.refresh_table()
        except (ValueError, KeyError):
            pass

    def refresh_table(self):
        self.table.setRowCount(0)
        total_amount = 0.0
        currency = "UZS"

        for row_idx, (code, data) in enumerate(self.items.items()):
            self.table.insertRow(row_idx)
            self.table.setRowHeight(row_idx, 65)

            name_item = QTableWidgetItem(data["name"])
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.table.setItem(row_idx, 0, name_item)

            qty_widget = QWidget()
            qty_widget.setStyleSheet("background: transparent;")
            qty_layout = QHBoxLayout(qty_widget)
            qty_layout.setContentsMargins(4, 6, 4, 6)
            qty_layout.setSpacing(0)
            qty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            btn_minus = QPushButton("−")
            btn_minus.setFixedSize(44, 44)
            btn_minus.setStyleSheet("""
                QPushButton {
                    font-size: 20px; font-weight: bold; color: #dc2626;
                    background: #fef2f2;
                    border: none;
                    border-top-left-radius: 10px;
                    border-bottom-left-radius: 10px;
                    border-top-right-radius: 0px;
                    border-bottom-right-radius: 0px;
                }
                QPushButton:pressed { background: #fecaca; }
            """)
            btn_minus.clicked.connect(lambda checked, c=code: self.update_qty(c, -1))

            qty_label = QtyLabel(str(int(data["qty"])))
            qty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_label.setFixedSize(48, 44)
            qty_label.setStyleSheet("""
                font-size: 17px; font-weight: 800; color: #1e293b;
                background: #f8fafc; border: none;
                border-top: 1px solid #e2e8f0;
                border-bottom: 1px solid #e2e8f0;
            """)
            qty_label.clicked.connect(lambda c=code, q=str(int(data["qty"])): self._open_qty_numpad(c, q))

            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(44, 44)
            btn_plus.setStyleSheet("""
                QPushButton {
                    font-size: 20px; font-weight: bold; color: #16a34a;
                    background: #f0fdf4;
                    border: none;
                    border-top-right-radius: 10px;
                    border-bottom-right-radius: 10px;
                    border-top-left-radius: 0px;
                    border-bottom-left-radius: 0px;
                }
                QPushButton:pressed { background: #dcfce7; }
            """)
            btn_plus.clicked.connect(lambda checked, c=code: self.update_qty(c, 1))

            qty_layout.addWidget(btn_minus)
            qty_layout.addWidget(qty_label)
            qty_layout.addWidget(btn_plus)
            self.table.setCellWidget(row_idx, 1, qty_widget)



            price_item = QTableWidgetItem(f"{data['price']:,.0f}".replace(",", " "))
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(row_idx, 2, price_item)

            amount = int(data["qty"]) * data["price"]
            total_amount += amount
            currency = data["currency"]

            amount_item = QTableWidgetItem(f"{amount:,.0f}".replace(",", " "))
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(row_idx, 3, amount_item)

        self.total_label.setText(f"{total_amount:,.0f} {currency}".replace(",", " "))
        self.total_amount = total_amount

    def _open_qty_numpad(self, item_code: str, current_qty: str):
        """Inline numpad panel yordamida miqdorni o'zgartirish."""
        self._active_qty_item = item_code
        self.keyboard_panel.setVisible(False)
        self.numpad_display.setText(current_qty or "—")
        # Numpad input stiker o'rniga qty ga bog'laymiz
        self._numpad_mode = "qty"
        self.numpad_panel.setVisible(True)

    def clear_cart(self):
        self.items.clear()
        self.ticket_input.clear()
        self.comment_input.clear()
        self._close_panels()
        self.refresh_table()

    def handle_checkout(self):
        if not self.items:
            InfoDialog(self, "Xatolik", "Savat bo'sh!", kind="warning").exec()
            return

        ticket_number = self.ticket_input.text().strip()
        selected_customer = self.customer_combo.currentText().strip() or "guest"

        if self.current_order_type in TICKET_ORDER_TYPES and not ticket_number:
            InfoDialog(self, "Xatolik", "Stiker raqamini kiriting!", kind="warning").exec()
            return

        order_data = {
            "items": [{"item_code": k, **v} for k, v in self.items.items()],
            "total_amount": self.total_amount,
            "order_type": self.current_order_type,
            "ticket_number": ticket_number,
            "customer": selected_customer,
            "comment": self.comment_input.text().strip(),
        }
        self.checkout_requested.emit(order_data)
