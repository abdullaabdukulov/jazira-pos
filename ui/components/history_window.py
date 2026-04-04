import json
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFrame, QLineEdit,
    QScroller, QScrollerProperties,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import HISTORY_FETCH_LIMIT
from ui.scale import s, font
from database.models import PendingInvoice

logger = get_logger(__name__)


def _touch_scroll(table):
    scroller = QScroller.scroller(table.viewport())
    scroller.grabGesture(table.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
    scroller.setScrollerProperties(props)


# ─────────────────────────────────────
#  Worker threads
# ─────────────────────────────────────
class FetchHistoryWorker(QThread):
    result_ready = pyqtSignal(bool, list)

    def __init__(self, api: FrappeAPI, opening_entry: str = "", pos_profile: str = "", cashier: str = ""):
        super().__init__()
        self.api = api
        self.opening_entry = opening_entry
        self.pos_profile = pos_profile
        self.cashier = cashier

    def run(self):
        fields = json.dumps(["name", "customer", "grand_total", "posting_date", "posting_time", "status", "docstatus", "creation"])

        # Avval pos_opening_entry bo'yicha qidir
        if self.opening_entry:
            filters = json.dumps([["POS Invoice", "pos_opening_entry", "=", self.opening_entry]])
            data = self.api.fetch_data("POS Invoice", fields=fields, filters=filters, limit=HISTORY_FETCH_LIMIT)
            if data:
                data.sort(key=lambda x: x.get("creation", ""), reverse=True)
                self.result_ready.emit(True, data)
                return

        # pos_opening_entry bo'sh yoki natija yo'q — pos_profile + cashier + bugungi sana bo'yicha qidir
        if self.pos_profile:
            from datetime import date
            today = date.today().isoformat()
            filters_list = [
                ["POS Invoice", "pos_profile", "=", self.pos_profile],
                ["POS Invoice", "posting_date", "=", today],
            ]
            if self.cashier:
                filters_list.append(["POS Invoice", "cashier", "=", self.cashier])
            filters = json.dumps(filters_list)
            data = self.api.fetch_data("POS Invoice", fields=fields, filters=filters, limit=HISTORY_FETCH_LIMIT)
            if data is not None:
                data.sort(key=lambda x: x.get("creation", ""), reverse=True)
                self.result_ready.emit(True, data)
                return

        self.result_ready.emit(True, [])


class FetchDetailsWorker(QThread):
    result_ready = pyqtSignal(bool, dict)

    def __init__(self, api: FrappeAPI, invoice_id: str):
        super().__init__()
        self.invoice_id = invoice_id
        self.api = api

    def run(self):
        success, doc = self.api.call_method(
            "frappe.client.get", {"doctype": "POS Invoice", "name": self.invoice_id}
        )
        self.result_ready.emit(success and isinstance(doc, dict), doc if isinstance(doc, dict) else {})


class CancelOrderWorker(QThread):
    # (success, message, order_data_for_print)
    result_ready = pyqtSignal(bool, str, dict)

    def __init__(self, api: FrappeAPI, invoice_id: str, reason: str):
        super().__init__()
        self.invoice_id = invoice_id
        self.reason = reason
        self.api = api

    def run(self):
        # 1. Invoice tafsilotlarini olish (production print uchun)
        order_data = {}
        try:
            ok, doc = self.api.call_method(
                "frappe.client.get", {"doctype": "POS Invoice", "name": self.invoice_id}
            )
            if ok and isinstance(doc, dict):
                order_data = {
                    "items": [
                        {
                            "item_code": it.get("item_code", ""),
                            "item": it.get("item_code", ""),
                            "item_name": it.get("item_name", ""),
                            "name": it.get("item_name", ""),
                            "qty": it.get("qty", 1),
                        }
                        for it in doc.get("items", [])
                    ],
                    "order_type": doc.get("order_type", ""),
                    "ticket_number": doc.get("ticket_number", ""),
                    "customer": doc.get("customer", ""),
                    "cancel_reason": self.reason,
                }
        except Exception:
            pass  # Print bo'lmasa ham bekor qilishni davom ettiramiz

        # 2. Bekor qilish
        success, response = self.api.call_method(
            "ury.ury.doctype.ury_order.ury_order.cancel_order",
            {"invoice_id": self.invoice_id, "reason": self.reason},
        )
        if success:
            self.result_ready.emit(True, "Chek muvaffaqiyatli bekor qilindi!", order_data)
        else:
            self.result_ready.emit(False, f"Xatolik: {response}", {})


class PrintTypeDialog(QDialog):
    """Chop etish turini tanlash: Mijoz / Oshxona / Hammasi."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Chop etish turi")
        self.setFixedSize(s(480), s(280))
        self.setStyleSheet("background: white;")
        self.print_type = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(24), s(20), s(24), s(24))
        layout.setSpacing(s(12))

        title = QLabel("Qayerga chop etasiz?")
        title.setStyleSheet(f"font-size: {font(17)}px; font-weight: 800; color: #1e293b;")
        layout.addWidget(title)

        hint = QLabel("Printer sozlangan bo'lsa, tanlangan yo'nalishga yuboriladi.")
        hint.setStyleSheet(f"font-size: {font(12)}px; color: #94a3b8;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(10))

        for label, ptype, bg, hover, border in [
            ("Mijoz cheki", "customer", "#eff6ff", "#dbeafe", "#93c5fd"),
            ("Oshxona / Bar", "production", "#f0fdf4", "#dcfce7", "#86efac"),
            ("Hammasi", "all", "#faf5ff", "#f3e8ff", "#c4b5fd"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(s(60))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {bg}; color: #1e293b;
                    font-weight: 700; font-size: {font(14)}px;
                    border-radius: {s(10)}px; border: 2px solid {border};
                }}
                QPushButton:hover {{ background: {hover}; }}
                QPushButton:pressed {{ background: {border}; }}
            """)
            btn.clicked.connect(lambda _, pt=ptype: self._select(pt))
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

        cancel_btn = QPushButton("Bekor qilish")
        cancel_btn.setFixedHeight(s(40))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 600; font-size: {font(12)}px;
                border-radius: {s(8)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _select(self, print_type: str):
        self.print_type = print_type
        self.accept()


class ReprintWorker(QThread):
    """Invoice tafsilotlarini olib, chek qayta chop etish."""
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, invoice_id: str, print_type: str = "customer"):
        super().__init__()
        self.api = api
        self.invoice_id = invoice_id
        self.print_type = print_type  # "customer" | "production" | "all"

    def run(self):
        try:
            success, doc = self.api.call_method(
                "frappe.client.get", {"doctype": "POS Invoice", "name": self.invoice_id}
            )
            if not success or not isinstance(doc, dict):
                self.result_ready.emit(False, "Chek ma'lumotlarini olishda xatolik")
                return

            # order_data va payments_list qayta qurish
            order_data = {
                "items": [
                    {
                        "item_code": it.get("item_code", ""),
                        "item": it.get("item_code", ""),
                        "name": it.get("item_name", ""),
                        "item_name": it.get("item_name", ""),
                        "qty": it.get("qty", 1),
                        "rate": it.get("rate", 0),
                        "price": it.get("rate", 0),
                        "amount": it.get("amount", 0),
                    }
                    for it in doc.get("items", [])
                ],
                "total_amount": doc.get("grand_total", 0),
                "customer": doc.get("customer", ""),
            }
            payments_list = [
                {"mode_of_payment": p.get("mode_of_payment", ""), "amount": float(p.get("amount", 0))}
                for p in doc.get("payments", [])
                if float(p.get("amount", 0)) > 0
            ]

            from core import printer as _printer
            pt = self.print_type

            if pt == "customer":
                ok = _printer.reprint_customer(order_data, payments_list)
                if ok:
                    self.result_ready.emit(True, "Mijoz cheki chop etildi!")
                else:
                    self.result_ready.emit(False, "Mijoz printeri xatosi yoki sozlanmagan.")

            elif pt == "production":
                results = _printer.reprint_production(order_data)
                if not results:
                    self.result_ready.emit(False, "Hech qanday production printer topilmadi yoki mahsulot yo'q.")
                    return
                failed = [u for u, ok in results.items() if not ok]
                if not failed:
                    units = ", ".join(results.keys())
                    self.result_ready.emit(True, f"Oshxona/Bar chopi yuborildi: {units}")
                else:
                    self.result_ready.emit(False, f"Xato bo'lgan unitlar: {', '.join(failed)}")

            else:  # "all"
                results = _printer.reprint_all(order_data, payments_list)
                cust_ok = results.pop("customer", None)
                prod_failed = [u for u, ok in results.items() if not ok]
                if cust_ok and not prod_failed:
                    self.result_ready.emit(True, "Barcha printerga chopi yuborildi!")
                elif cust_ok:
                    self.result_ready.emit(True, f"Mijoz chopi OK. Xato unitlar: {', '.join(prod_failed)}")
                elif not prod_failed and results:
                    self.result_ready.emit(True, f"Oshxona/Bar OK. Mijoz printeri xato.")
                else:
                    self.result_ready.emit(False, "Printer xatosi yoki printerlar sozlanmagan.")

        except Exception as e:
            logger.error("Reprint xatosi: %s", e)
            self.result_ready.emit(False, f"Xatolik: {e}")


class OfflineReprintWorker(QThread):
    """Oflayn invoice_data dan chek chop etish (server kerak emas)."""
    result_ready = pyqtSignal(bool, str)

    def __init__(self, invoice_data_json: str, print_type: str = "customer"):
        super().__init__()
        self.invoice_data_json = invoice_data_json
        self.print_type = print_type

    def run(self):
        try:
            data = json.loads(self.invoice_data_json)
        except Exception as e:
            self.result_ready.emit(False, f"Ma'lumot xatosi: {e}")
            return

        items = data.get("items", [])
        order_data = {
            "items": [
                {
                    "item_code": it.get("item", it.get("item_code", "")),
                    "item":      it.get("item", it.get("item_code", "")),
                    "item_name": it.get("item_name", ""),
                    "name":      it.get("item_name", ""),
                    "qty":       it.get("qty", 1),
                    "rate":      it.get("rate", 0),
                    "price":     it.get("rate", 0),
                    "amount":    float(it.get("rate", 0)) * float(it.get("qty", 1)),
                }
                for it in items
            ],
            "total_amount": float(data.get("total_amount", 0)),
            "customer":     data.get("customer", ""),
            "order_type":   data.get("order_type", ""),
            "ticket_number": data.get("ticket_number", ""),
        }
        payments_list = [
            {"mode_of_payment": p.get("mode_of_payment", ""), "amount": float(p.get("amount", 0))}
            for p in (data.get("_payments") or [])
            if float(p.get("amount", 0)) > 0
        ]

        try:
            from core import printer as _printer
            pt = self.print_type
            if pt == "customer":
                ok = _printer.reprint_customer(order_data, payments_list)
                self.result_ready.emit(ok, "Mijoz cheki chop etildi!" if ok else "Printer xatosi yoki sozlanmagan.")
            elif pt == "production":
                results = _printer.reprint_production(order_data)
                if not results:
                    self.result_ready.emit(False, "Production printer topilmadi yoki mahsulot yo'q.")
                    return
                failed = [u for u, ok in results.items() if not ok]
                if not failed:
                    self.result_ready.emit(True, f"Oshxona/Bar chopi yuborildi: {', '.join(results)}")
                else:
                    self.result_ready.emit(False, f"Xato unitlar: {', '.join(failed)}")
            else:  # all
                results = _printer.reprint_all(order_data, payments_list)
                cust_ok = results.pop("customer", None)
                prod_failed = [u for u, ok in results.items() if not ok]
                if cust_ok and not prod_failed:
                    self.result_ready.emit(True, "Barcha printerga yuborildi!")
                elif cust_ok:
                    self.result_ready.emit(True, f"Mijoz OK. Xato unitlar: {', '.join(prod_failed)}")
                else:
                    self.result_ready.emit(False, "Printer xatosi.")
        except Exception as e:
            logger.error("Oflayn reprint xatosi: %s", e)
            self.result_ready.emit(False, f"Xatolik: {e}")


# ─────────────────────────────────────
#  Inline detail panel (replaces dialog)
# ─────────────────────────────────────
class TransactionDetailDialog(QDialog):
    """Still kept as QDialog so double-click flow works unchanged."""

    def __init__(self, parent, api: FrappeAPI, invoice_id: str):
        super().__init__(parent)
        self.api = api
        self.invoice_id = invoice_id
        self.setWindowTitle(f"Chek: {invoice_id}")
        self.setFixedSize(s(520), s(560))
        self.setStyleSheet("background: white;")
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(20), s(20), s(20), s(20))
        layout.setSpacing(s(12))

        # Header
        hdr = QLabel(f"Chek  #{self.invoice_id}")
        hdr.setStyleSheet(f"font-size: {font(18)}px; font-weight: 800; color: #1e293b;")
        layout.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(sep)

        # Items table
        lbl = QLabel("MAHSULOTLAR")
        lbl.setStyleSheet(f"font-size: {font(10)}px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        layout.addWidget(lbl)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Mahsulot", "Soni", "Summa"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet(f"""
            QTableWidget {{ border: none; font-size: {font(13)}px; background: white; }}
            QTableWidget::item {{ padding: {s(6)}px; }}
            QTableWidget::item:selected {{ background: #dbeafe; color: #1e40af; }}
            QHeaderView::section {{
                background: #f8fafc; color: #94a3b8;
                font-size: {font(11)}px; font-weight: 700;
                padding: {s(6)}px; border: none;
                border-bottom: 1px solid #e2e8f0;
            }}
        """)
        layout.addWidget(self.table)
        _touch_scroll(self.table)

        # Payments
        pay_lbl = QLabel("TO'LOV TURLARI")
        pay_lbl.setStyleSheet(f"font-size: {font(10)}px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        layout.addWidget(pay_lbl)

        self.payments_frame = QFrame()
        self.payments_frame.setStyleSheet(
            f"background: #f8fafc; border-radius: {s(10)}px; padding: {s(2)}px;"
        )
        self.payments_layout = QVBoxLayout(self.payments_frame)
        self.payments_layout.setContentsMargins(s(12), s(8), s(12), s(8))
        layout.addWidget(self.payments_frame)

        layout.addStretch()

        close_btn = QPushButton("Yopish")
        close_btn.setFixedHeight(s(44))
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #475569;
                font-weight: 700; border-radius: {s(10)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _load(self):
        self.worker = FetchDetailsWorker(self.api, self.invoice_id)
        self.worker.result_ready.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, success: bool, doc: dict):
        if not success:
            QMessageBox.warning(self, "Xato", "Tafsilotlarni yuklab bo'lmadi.")
            return

        items = doc.get("items", [])
        self.table.setRowCount(0)
        for i, item in enumerate(items):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(item.get("item_name", "")))
            self.table.setItem(i, 1, QTableWidgetItem(str(item.get("qty", 0))))
            self.table.setItem(i, 2, QTableWidgetItem(
                f"{item.get('amount', 0):,.0f}".replace(",", " ")
            ))

        # clear payments
        for i in reversed(range(self.payments_layout.count())):
            w = self.payments_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        payments = [p for p in doc.get("payments", []) if float(p.get("amount", 0)) > 0]
        if payments:
            for p in payments:
                row_w = QWidget()
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, s(2), 0, s(2))
                mode = QLabel(p.get("mode_of_payment", ""))
                mode.setStyleSheet(f"font-weight: 600; color: #374151; font-size: {font(13)}px;")
                amt = QLabel(f"{float(p.get('amount', 0)):,.0f} UZS".replace(",", " "))
                amt.setStyleSheet(f"color: #16a34a; font-weight: 700; font-size: {font(13)}px;")
                row_l.addWidget(mode)
                row_l.addStretch()
                row_l.addWidget(amt)
                self.payments_layout.addWidget(row_w)
        else:
            no = QLabel("To'lov ma'lumotlari mavjud emas.")
            no.setStyleSheet(f"color: #94a3b8; font-size: {font(12)}px;")
            self.payments_layout.addWidget(no)


# ─────────────────────────────────────
#  Cancel reason dialog with keyboard
# ─────────────────────────────────────
QUICK_CANCEL_REASONS = [
    "Mijoz buyurtmani o'zgartirdi",
    "Noto'g'ri buyurtma kiritildi",
    "Mijoz rad etdi / ketdi",
    "Test / sinov buyurtma",
    "Texnik sabab",
]


class CancelReasonDialog(QDialog):
    def __init__(self, parent, invoice_id: str):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle("Bekor qilish sababi")
        self.setFixedSize(s(660), s(560))
        self.setStyleSheet("background: white;")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(20), s(16), s(20), s(16))
        layout.setSpacing(s(10))

        # Title
        title = QLabel(f"#{self.invoice_id}  —  Bekor qilish sababi")
        title.setStyleSheet(f"font-size: {font(16)}px; font-weight: 800; color: #1e293b;")
        layout.addWidget(title)

        # Quick reason chips
        quick_lbl = QLabel("TEZKOR SABABLAR:")
        quick_lbl.setStyleSheet(f"font-size: {font(10)}px; color: #94a3b8; font-weight: 700; letter-spacing: 1px;")
        layout.addWidget(quick_lbl)

        chips_row1 = QHBoxLayout()
        chips_row1.setSpacing(s(6))
        chips_row2 = QHBoxLayout()
        chips_row2.setSpacing(s(6))
        for i, reason in enumerate(QUICK_CANCEL_REASONS):
            btn = QPushButton(reason)
            btn.setFixedHeight(s(38))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #f1f5f9; color: #334155;
                    font-size: {font(11)}px; font-weight: 600;
                    border-radius: {s(8)}px; border: 1.5px solid #e2e8f0;
                    padding: 0 {s(10)}px;
                }}
                QPushButton:hover {{ background: #fee2e2; color: #b91c1c; border-color: #fca5a5; }}
                QPushButton:pressed {{ background: #fecaca; }}
            """)
            btn.clicked.connect(lambda _, r=reason: self._fill_reason(r))
            if i < 3:
                chips_row1.addWidget(btn)
            else:
                chips_row2.addWidget(btn)
        chips_row2.addStretch()
        layout.addLayout(chips_row1)
        layout.addLayout(chips_row2)

        # Input display
        self.input = QLineEdit()
        self.input.setPlaceholderText("Sabab yozing yoki yuqoridan tanlang...")
        self.input.setFixedHeight(s(48))
        self.input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {font(14)}px; color: #1e293b;
                background: white;
                border: 2px solid #3b82f6;
                border-radius: {s(10)}px; padding: {s(8)}px {s(14)}px;
            }}
        """)
        layout.addWidget(self.input)

        # Keyboard rows
        rows = [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['A','S','D','F','G','H','J','K','L','CLR'],
            ['Z','X','C','V','B','N','M','SPACE'],
        ]
        for row_keys in rows:
            row_w = QHBoxLayout()
            row_w.setSpacing(s(4))
            for k in row_keys:
                row_w.addWidget(self._make_key(k))
            layout.addLayout(row_w)

        # Buttons
        btn_row = QHBoxLayout()

        cancel_btn = QPushButton("Bekor")
        cancel_btn.setFixedHeight(s(44))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; border-radius: {s(10)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("✓  Tasdiqlash")
        confirm_btn.setFixedHeight(s(44))
        confirm_btn.setStyleSheet(f"""
            QPushButton {{ background: #ef4444; color: white;
                font-weight: 700; font-size: {font(14)}px;
                border-radius: {s(10)}px; border: none; }}
            QPushButton:hover {{ background: #dc2626; }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

    def _fill_reason(self, reason: str):
        self.input.setText(reason)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {font(14)}px; color: #1e293b;
                background: white;
                border: 2px solid #3b82f6;
                border-radius: {s(10)}px; padding: {s(8)}px {s(14)}px;
            }}
        """)

    def _make_key(self, key):
        label = '␣' if key == 'SPACE' else ('TOZALASH' if key == 'CLR' else key)
        btn = QPushButton(label)
        btn.setFixedHeight(s(44))
        if key == '⌫':
            style = f"background:#fee2e2; color:#ef4444; font-size:{font(15)}px; font-weight:bold;"
        elif key == 'CLR':
            style = f"background:#fff7ed; color:#ea580c; font-size:{font(10)}px; font-weight:bold;"
        elif key == 'SPACE':
            style = f"background:#eff6ff; color:#3b82f6; font-size:{font(13)}px; font-weight:bold;"
            btn.setMinimumWidth(s(80))
        elif key.isdigit():
            style = f"background:#f1f5f9; color:#334155; font-size:{font(13)}px; font-weight:700;"
        else:
            style = f"background:white; color:#1e293b; font-size:{font(13)}px; font-weight:600;"
        btn.setStyleSheet(f"""
            QPushButton {{ {style} border:1px solid #e2e8f0; border-radius:{s(6)}px; }}
            QPushButton:pressed {{ background:#dbeafe; }}
        """)
        btn.clicked.connect(lambda _, k=key: self._on_key(k))
        return btn

    def _on_key(self, key):
        cur = self.input.text()
        if key == '⌫':
            self.input.setText(cur[:-1])
        elif key == 'CLR':
            self.input.clear()
        elif key == 'SPACE':
            self.input.setText(cur + ' ')
        else:
            self.input.setText(cur + key)

    def _on_confirm(self):
        if self.input.text().strip():
            self.accept()
        else:
            self.input.setStyleSheet(f"""
                QLineEdit {{
                    font-size: {font(15)}px; color: #1e293b;
                    background: #fff5f5;
                    border: 2px solid #ef4444;
                    border-radius: {s(10)}px; padding: {s(8)}px {s(14)}px;
                }}
            """)

    def get_reason(self) -> str:
        return self.input.text().strip()


# ─────────────────────────────────────
#  Main History Panel (inline widget)
# ─────────────────────────────────────
class HistoryWindow(QWidget):
    """Inline panel — embed in main_window, show/hide via toggle."""

    def __init__(self, api: FrappeAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.opening_entry = ""
        self.pos_profile = ""
        self.cashier = ""
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(16), s(12), s(16), s(12))
        layout.setSpacing(s(10))

        # ── Header row ──────────────────────
        hdr_row = QHBoxLayout()

        title = QLabel("So'nggi tranzaksiyalar")
        title.setStyleSheet(f"font-size: {font(18)}px; font-weight: 800; color: #1e293b;")
        hdr_row.addWidget(title)

        hint = QLabel("(2× bosing — tafsilot)")
        hint.setStyleSheet(f"font-size: {font(11)}px; color: #94a3b8; font-style: italic;")
        hdr_row.addWidget(hint)
        hdr_row.addStretch()

        refresh_btn = QPushButton("⟳  Yangilash")
        refresh_btn.setFixedHeight(s(44))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                padding: 0 {s(16)}px; background: #f1f5f9; color: #475569;
                font-weight: 600; font-size: {font(13)}px;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        refresh_btn.clicked.connect(self.load_history)
        hdr_row.addWidget(refresh_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(44), s(44))
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: #fee2e2; color: #b91c1c;
                font-weight: 700; font-size: {font(14)}px; border-radius: {s(8)}px; border: none; }}
            QPushButton:hover {{ background: #fecaca; }}
        """)
        close_btn.clicked.connect(self.hide)
        hdr_row.addWidget(close_btn)

        layout.addLayout(hdr_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #e2e8f0; max-height: 1px;")
        layout.addWidget(sep)

        # ── Table ────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "Sana", "Vaqt", "Mijoz", "Summa", "Bekor", "Chop etish"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border: none; background: white; font-size: {font(13)}px;
            }}
            QTableWidget::item {{ padding: {s(5)}px {s(8)}px; border-bottom: 1px solid #f1f5f9; }}
            QTableWidget::item:selected {{ background: #dbeafe; color: #1e40af; }}
            QHeaderView::section {{
                background: #f8fafc; color: #94a3b8;
                font-size: {font(11)}px; font-weight: 700; letter-spacing: 0.5px;
                padding: {s(8)}px {s(8)}px; border: none;
                border-bottom: 1px solid #e2e8f0;
            }}
        """)
        self.table.itemDoubleClicked.connect(self._show_details)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, s(110))
        self.table.setColumnWidth(6, s(110))
        layout.addWidget(self.table)
        _touch_scroll(self.table)

    def load_history(self):
        self.table.setRowCount(0)
        self.worker = FetchHistoryWorker(self.api, self.opening_entry, self.pos_profile, self.cashier)
        self.worker.result_ready.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, success: bool, data: list):
        if not success:
            return
        self.table.setRowCount(0)
        for i, item in enumerate(data):
            self.table.insertRow(i)
            self.table.setRowHeight(i, s(46))
            inv_name = item.get("name", "")
            status = item.get("status", "")

            self.table.setItem(i, 0, QTableWidgetItem(inv_name))
            self.table.setItem(i, 1, QTableWidgetItem(item.get("posting_date", "")))
            self.table.setItem(i, 2, QTableWidgetItem(item.get("posting_time", "")[:5]))
            self.table.setItem(i, 3, QTableWidgetItem(item.get("customer", "")))
            amt = QTableWidgetItem(f"{item.get('grand_total', 0):,.0f} UZS".replace(",", " "))
            amt.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(i, 4, amt)

            if status != "Cancelled":
                cancel_btn = QPushButton("Bekor")
                cancel_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #fff7ed; color: #ea580c;
                        font-weight: 600; font-size: {font(12)}px;
                        border-radius: {s(6)}px; border: 1px solid #fed7aa;
                        padding: {s(4)}px {s(8)}px;
                    }}
                    QPushButton:hover {{ background: #ffedd5; }}
                """)
                cancel_btn.clicked.connect(lambda _, inv=inv_name: self._confirm_cancel(inv))
                self.table.setCellWidget(i, 5, cancel_btn)
            else:
                lbl = QLabel("Bekor qilingan")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(f"color: #ef4444; font-weight: 600; font-size: {font(11)}px;")
                self.table.setCellWidget(i, 5, lbl)

            # Qayta chop etish tugmasi (barcha cheklar uchun)
            reprint_btn = QPushButton("🖨 Chop")
            reprint_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #f0fdf4; color: #15803d;
                    font-weight: 600; font-size: {font(12)}px;
                    border-radius: {s(6)}px; border: 1px solid #bbf7d0;
                    padding: {s(4)}px {s(8)}px;
                }}
                QPushButton:hover {{ background: #dcfce7; }}
                QPushButton:disabled {{ background: #f1f5f9; color: #94a3b8; border-color: #e2e8f0; }}
            """)
            reprint_btn.clicked.connect(lambda _, inv=inv_name, btn=reprint_btn: self._reprint(inv, btn))
            self.table.setCellWidget(i, 6, reprint_btn)

        self._add_offline_rows()

    def _add_offline_rows(self):
        """Oflayn (sinxronlanmagan) orderlarni jadvalga qo'shish."""
        try:
            pending_list = list(
                PendingInvoice.select()
                .where(PendingInvoice.status.in_(["Pending", "CancelPending", "Failed", "Cancelled"]))
                .order_by(PendingInvoice.created_at.desc())
                .limit(50)
            )
        except Exception as e:
            logger.warning("Oflayn orderlarni yuklab bo'lmadi: %s", e)
            return

        for inv in pending_list:
            try:
                data = json.loads(inv.invoice_data)
            except Exception:
                data = {}

            customer = data.get("customer", "—")
            total = float(data.get("total_amount", 0))
            if not total and data.get("items"):
                total = sum(
                    float(it.get("rate", 0)) * float(it.get("qty", 1))
                    for it in data.get("items", [])
                )
            created = inv.created_at.strftime("%Y-%m-%d") if inv.created_at else ""
            created_time = inv.created_at.strftime("%H:%M") if inv.created_at else ""

            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setRowHeight(i, s(46))

            # ID ustuni — "OFLAYN" belgisi bilan
            id_item = QTableWidgetItem(f"OFLAYN")
            id_item.setForeground(Qt.GlobalColor.darkBlue)
            id_item.setToolTip(str(inv.offline_id or inv.id))
            self.table.setItem(i, 0, id_item)
            self.table.setItem(i, 1, QTableWidgetItem(created))
            self.table.setItem(i, 2, QTableWidgetItem(created_time))
            self.table.setItem(i, 3, QTableWidgetItem(customer))
            amt_item = QTableWidgetItem(f"{total:,.0f} UZS".replace(",", " "))
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(i, 4, amt_item)

            # Bekor qilish / holat ustuni (5-ustun)
            if inv.status in ("CancelPending", "Cancelled"):
                lbl = QLabel("Bekor qilingan")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if inv.status == "CancelPending":
                    lbl.setToolTip("Serverga sinxronlanishi kutilmoqda")
                lbl.setStyleSheet(f"color: #ef4444; font-weight: 600; font-size: {font(11)}px;")
                self.table.setCellWidget(i, 5, lbl)
            elif inv.status == "Pending":
                cancel_btn = QPushButton("Bekor")
                cancel_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #fef3c7; color: #b45309;
                        font-weight: 600; font-size: {font(12)}px;
                        border-radius: {s(6)}px; border: 1px solid #fde68a;
                        padding: {s(4)}px {s(8)}px;
                    }}
                    QPushButton:hover {{ background: #fde68a; }}
                """)
                cancel_btn.clicked.connect(
                    lambda _, pid=inv.id, idata=inv.invoice_data: self._confirm_cancel_offline(pid, idata)
                )
                self.table.setCellWidget(i, 5, cancel_btn)
            else:
                # Failed
                lbl = QLabel("Xato")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(f"color: #dc2626; font-weight: 600; font-size: {font(11)}px;")
                self.table.setCellWidget(i, 5, lbl)

            # Chop etish ustuni — oflayn orderlar uchun chop etish tugmasi
            print_btn = QPushButton("🖨 Chop")
            print_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #f0fdf4; color: #15803d;
                    font-weight: 600; font-size: {font(12)}px;
                    border-radius: {s(6)}px; border: 1px solid #bbf7d0;
                    padding: {s(4)}px {s(8)}px;
                }}
                QPushButton:hover {{ background: #dcfce7; }}
                QPushButton:disabled {{ background: #f1f5f9; color: #94a3b8; border-color: #e2e8f0; }}
            """)
            print_btn.clicked.connect(
                lambda _, idata=inv.invoice_data, btn=print_btn: self._reprint_offline(idata, btn)
            )
            self.table.setCellWidget(i, 6, print_btn)

    def _show_details(self, item):
        invoice_id = self.table.item(item.row(), 0).text()
        if invoice_id == "OFLAYN":
            return  # Oflayn orderlar uchun tafsilot oynasi yo'q
        TransactionDetailDialog(self, self.api, invoice_id).exec()

    def _reprint_offline(self, invoice_data_json: str, btn: QPushButton):
        dlg = PrintTypeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        print_type = dlg.print_type or "customer"
        btn.setEnabled(False)
        btn.setText("Chop etilmoqda...")
        self.offline_reprint_worker = OfflineReprintWorker(invoice_data_json, print_type)
        self.offline_reprint_worker.result_ready.connect(
            lambda ok, msg, b=btn: self._on_reprint_finished(ok, msg, b)
        )
        self.offline_reprint_worker.start()

    def _confirm_cancel(self, invoice_id: str):
        dlg = CancelReasonDialog(self, invoice_id)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            reason = dlg.get_reason()
            self.cancel_worker = CancelOrderWorker(self.api, invoice_id, reason)
            self.cancel_worker.result_ready.connect(self._on_cancel_finished)
            self.cancel_worker.start()

    def _on_cancel_finished(self, success: bool, message: str, order_data: dict):
        if success:
            msg = (
                "Bekor so'rovi yuborildi!\n\n"
                "Oshxona/bar xabardor qilindi.\n"
                "Manager ERPNext da ko'rib tasdiqlaydi."
            )
            QMessageBox.information(self, "So'rov yuborildi", msg)
            # Production unitlarga "QAYTARILDI" stikeri
            if order_data.get("items"):
                try:
                    from core.printer import print_cancel_production
                    results = print_cancel_production(order_data, order_data.get("cancel_reason", ""))
                    if results:
                        failed = [u for u, ok in results.items() if not ok]
                        if failed:
                            logger.warning("Bekor stikeri yuborilmadi: %s", ", ".join(failed))
                except Exception as e:
                    logger.error("Bekor stikeri chop etishda xatolik: %s", e)
        else:
            QMessageBox.warning(self, "Xatolik", message)
        self.load_history()

    def _confirm_cancel_offline(self, pending_id: int, invoice_data_json: str):
        """Oflayn orderni bekor qilish — server API siz, faqat local DB."""
        try:
            data = json.loads(invoice_data_json)
        except Exception:
            data = {}
        display_id = f"OFLAYN-{pending_id}"
        dlg = CancelReasonDialog(self, display_id)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        reason = dlg.get_reason()
        try:
            raw = json.loads(invoice_data_json)
            raw["_cancel_reason"] = reason
            PendingInvoice.update(
                status="CancelPending",
                invoice_data=json.dumps(raw),
                error_message=f"Bekor kutilmoqda: {reason}",
            ).where(PendingInvoice.id == pending_id).execute()
        except Exception as e:
            QMessageBox.warning(self, "Xatolik", f"Oflayn bekor qilishda xatolik: {e}")
            return

        # Production unitlarga QAYTARILDI stikeri
        items = data.get("items", [])
        if items:
            order_data = {
                "items": [
                    {
                        "item_code": it.get("item", it.get("item_code", "")),
                        "item_name": it.get("item_name", ""),
                        "name": it.get("item_name", ""),
                        "qty": it.get("qty", 1),
                    }
                    for it in items
                ],
                "order_type": data.get("order_type", ""),
                "ticket_number": data.get("ticket_number", ""),
                "customer": data.get("customer", ""),
                "cancel_reason": reason,
            }
            try:
                from core.printer import print_cancel_production
                results = print_cancel_production(order_data, reason)
                if results:
                    failed = [u for u, ok in results.items() if not ok]
                    if failed:
                        logger.warning("Bekor stikeri yuborilmadi: %s", ", ".join(failed))
            except Exception as e:
                logger.error("Bekor stikeri chop etishda xatolik: %s", e)

        QMessageBox.information(self, "Bekor qilindi", "Oflayn buyurtma bekor qilindi.\nOshxona xabardor qilindi.")
        self.load_history()

    def _reprint(self, invoice_id: str, btn: QPushButton):
        dlg = PrintTypeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        print_type = dlg.print_type or "customer"

        btn.setEnabled(False)
        btn.setText("Chop etilmoqda...")
        self.reprint_worker = ReprintWorker(self.api, invoice_id, print_type)
        self.reprint_worker.result_ready.connect(
            lambda ok, msg, b=btn: self._on_reprint_finished(ok, msg, b)
        )
        self.reprint_worker.start()

    def _on_reprint_finished(self, success: bool, message: str, btn: QPushButton):
        try:
            btn.setEnabled(True)
            btn.setText("🖨 Chop")
        except RuntimeError:
            pass  # Widget allaqachon o'chirilgan
        QMessageBox.information(self, "Chop etish natijasi", message)
