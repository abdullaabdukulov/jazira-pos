import json
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QLineEdit,
    QScroller, QScrollerProperties,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import HISTORY_FETCH_LIMIT
from ui.scale import s, font
from database.models import PendingInvoice
from ui.components.dialogs import InfoDialog

logger = get_logger(__name__)


# ── Elite palette ────────────────────────────────────────
_GOLD = "#c89968"
_SLATE_900 = "#0f172a"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748b"
_SLATE_400 = "#94a3b8"
_SLATE_300 = "#cbd5e1"
_SLATE_200 = "#e2e8f0"
_SLATE_100 = "#f1f5f9"
_SLATE_50 = "#f8fafc"
_RED_700 = "#b91c1c"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"
_AMBER_700 = "#c2410c"
_AMBER_200 = "#fed7aa"
_AMBER_50 = "#fff7ed"
_EMERALD_700 = "#047857"
_EMERALD_200 = "#a7f3d0"
_EMERALD_50 = "#ecfdf5"


def _row_cell(button: QPushButton) -> QWidget:
    """Markazlangan jadval qator cell — subtle padding, NO border."""
    cell = QWidget()
    cell.setStyleSheet("background: transparent; border: none;")
    cell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(s(12), 0, s(12), 0)
    layout.setSpacing(0)
    layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    layout.addStretch()
    return cell


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
            InfoDialog(self, "Yuklab bo'lmadi",
                       "Buyurtma tafsilotlarini yuklab bo'lmadi.\n"
                       "Tarmoqni tekshiring va qaytadan urinib ko'ring.",
                       kind="info").exec()
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
        self._locally_cancelled: set = set()  # server qaytmaguncha mahalliy kuzatish
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(28), s(18), s(28), s(20))
        root.setSpacing(s(14))

        # ── Header ─────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(s(14))

        title_block = QVBoxLayout()
        title_block.setSpacing(s(2))

        title = QLabel("SO'NGGI TRANZAKSIYALAR")
        title.setFrameShape(QFrame.Shape.NoFrame)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tf = QFont()
        tf.setPixelSize(font(15))
        tf.setWeight(QFont.Weight.Black)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        title.setFont(tf)
        title.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        title_block.addWidget(title)

        subtitle = QLabel("Buyurtmani 2 marta bosing — tafsilot")
        subtitle.setFrameShape(QFrame.Shape.NoFrame)
        subtitle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sf = QFont()
        sf.setPixelSize(font(11))
        sf.setWeight(QFont.Weight.Medium)
        subtitle.setFont(sf)
        subtitle.setStyleSheet(
            f"color: {_SLATE_500}; background: transparent;"
            f" border: none; outline: none;"
        )
        title_block.addWidget(subtitle)

        header.addLayout(title_block)
        header.addStretch()

        refresh_btn = QPushButton("Yangilash")
        refresh_btn.setFixedHeight(s(36))
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {_SLATE_700};
                font-weight: 600;
                font-size: {font(12)}px;
                border-radius: {s(8)}px;
                border: 1px solid {_SLATE_200};
                padding: 0 {s(16)}px;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                border-color: {_SLATE_300};
                color: {_SLATE_900};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        refresh_btn.clicked.connect(self.load_history)
        header.addWidget(refresh_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(36), s(36))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_SLATE_400};
                font-weight: 700;
                font-size: {font(14)}px;
                border-radius: {s(8)}px;
                border: 1px solid transparent;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                color: {_SLATE_900};
                border: 1px solid {_SLATE_200};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)

        root.addLayout(header)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_SLATE_100}; border: none;")
        root.addWidget(sep)

        # ── Table ────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "ID", "SANA", "VAQT", "MIJOZ", "SUMMA", "BEKOR", "CHOP ETISH",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border: none;
                background: white;
                font-size: {font(13)}px;
                color: {_SLATE_900};
                outline: none;
                gridline-color: transparent;
                show-decoration-selected: 1;
            }}
            QTableWidget::item {{
                padding: {s(14)}px {s(18)}px;
                border: none;
                border-right: 1px solid {_SLATE_100};
            }}
            QTableWidget::item:last {{
                border-right: none;
            }}
            QTableWidget::item:alternate {{
                background: {_SLATE_50};
            }}
            QTableWidget::item:hover {{
                background: #fffbeb;
            }}
            QTableWidget::item:selected {{
                background: #fff7ed;
                color: {_AMBER_700};
            }}
            QHeaderView {{ background: transparent; border: none; }}
            QHeaderView::section {{
                background: white;
                color: {_SLATE_400};
                font-size: {font(10)}px;
                font-weight: 800;
                letter-spacing: 2px;
                padding: {s(12)}px {s(18)}px;
                border: none;
                border-bottom: 2px solid {_SLATE_200};
                border-right: 1px solid {_SLATE_100};
            }}
            QHeaderView::section:last {{
                border-right: none;
            }}
        """)
        self.table.itemDoubleClicked.connect(self._show_details)

        hdr = self.table.horizontalHeader()
        # Default header alignment — chap, qiymat alignmentiga mos
        hdr.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, s(170))   # ID — SK-2026-00029 sig'adi
        self.table.setColumnWidth(1, s(130))   # Sana
        self.table.setColumnWidth(2, s(100))   # Vaqt
        self.table.setColumnWidth(4, s(160))   # Summa — "30 000 UZS" to'liq sig'adi
        self.table.setColumnWidth(5, s(130))   # Bekor
        self.table.setColumnWidth(6, s(140))   # Chop

        # Summa va Bekor / Chop ustun sarlavhalari — markazga (qiymatlari ham mos)
        right_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        center_align = Qt.AlignmentFlag.AlignCenter
        self.table.horizontalHeaderItem(4).setTextAlignment(right_align)
        self.table.horizontalHeaderItem(5).setTextAlignment(center_align)
        self.table.horizontalHeaderItem(6).setTextAlignment(center_align)

        root.addWidget(self.table)
        _touch_scroll(self.table)

    def _row_button(self, text: str, color: str, border: str, hover_bg: str) -> QPushButton:
        """Jadval ichidagi minimal text tugma — borderless, hover'da subtle tint."""
        btn = QPushButton(text)
        btn.setFixedHeight(s(30))
        btn.setMinimumWidth(s(80))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {color};
                font-weight: 700;
                font-size: {font(12)}px;
                letter-spacing: 0.5px;
                border-radius: {s(6)}px;
                border: 1px solid transparent;
                padding: 0 {s(14)}px;
                outline: none;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border: 1px solid {border};
            }}
            QPushButton:pressed {{
                background: {hover_bg};
                border: 1px solid {color};
            }}
            QPushButton:disabled {{
                background: transparent;
                color: {_SLATE_400};
                border: 1px solid transparent;
            }}
        """)
        return btn

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
            self.table.setRowHeight(i, s(58))
            inv_name = item.get("name", "")
            status = item.get("status", "")

            id_item = QTableWidgetItem(inv_name)
            id_font = QFont()
            id_font.setPixelSize(font(12))
            id_font.setWeight(QFont.Weight.DemiBold)
            id_item.setFont(id_font)
            id_item.setForeground(QBrush(QColor(_SLATE_700)))
            self.table.setItem(i, 0, id_item)

            date_item = QTableWidgetItem(item.get("posting_date", ""))
            date_item.setForeground(QBrush(QColor(_SLATE_500)))
            self.table.setItem(i, 1, date_item)

            time_item = QTableWidgetItem(item.get("posting_time", "")[:5])
            time_item.setForeground(QBrush(QColor(_SLATE_500)))
            self.table.setItem(i, 2, time_item)

            cust_item = QTableWidgetItem(item.get("customer", ""))
            cust_font = QFont()
            cust_font.setPixelSize(font(13))
            cust_font.setWeight(QFont.Weight.DemiBold)
            cust_item.setFont(cust_font)
            cust_item.setForeground(QBrush(QColor(_SLATE_900)))
            self.table.setItem(i, 3, cust_item)

            amt = QTableWidgetItem(f"{item.get('grand_total', 0):,.0f} UZS".replace(",", " "))
            amt.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            amt_font = QFont()
            amt_font.setPixelSize(font(13))
            amt_font.setWeight(QFont.Weight.Bold)
            amt.setFont(amt_font)
            amt.setForeground(QBrush(QColor(_SLATE_900)))
            self.table.setItem(i, 4, amt)

            is_cancelled = status == "Cancelled" or inv_name in self._locally_cancelled
            if is_cancelled:
                if status == "Cancelled":
                    self._locally_cancelled.discard(inv_name)
                lbl = QLabel("Bekor qilingan")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    f"color: {_RED_700}; font-weight: 700; font-size: {font(11)}px;"
                    f" letter-spacing: 0.5px;"
                )
                self.table.setCellWidget(i, 5, lbl)
            else:
                cancel_btn = self._row_button(
                    "Bekor",
                    color=_RED_700,
                    border=_RED_200,
                    hover_bg=_RED_50,
                )
                cancel_btn.clicked.connect(lambda _, inv=inv_name: self._confirm_cancel(inv))
                self.table.setCellWidget(i, 5, _row_cell(cancel_btn))

            # Qayta chop etish tugmasi (barcha cheklar uchun)
            reprint_btn = self._row_button(
                "Chop",
                color=_EMERALD_700,
                border=_EMERALD_200,
                hover_bg=_EMERALD_50,
            )
            reprint_btn.clicked.connect(lambda _, inv=inv_name, btn=reprint_btn: self._reprint(inv, btn))
            self.table.setCellWidget(i, 6, _row_cell(reprint_btn))

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
            self.table.setRowHeight(i, s(58))

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
                lbl.setStyleSheet(
                    f"color: {_RED_700}; font-weight: 700; font-size: {font(11)}px;"
                    f" letter-spacing: 0.5px;"
                )
                self.table.setCellWidget(i, 5, lbl)
            elif inv.status == "Pending":
                cancel_btn = self._row_button(
                    "Bekor",
                    color=_AMBER_700,
                    border=_AMBER_200,
                    hover_bg=_AMBER_50,
                )
                cancel_btn.clicked.connect(
                    lambda _, pid=inv.id, idata=inv.invoice_data: self._confirm_cancel_offline(pid, idata)
                )
                self.table.setCellWidget(i, 5, _row_cell(cancel_btn))
            else:
                # Failed
                lbl = QLabel("Xato")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    f"color: {_RED_700}; font-weight: 700; font-size: {font(11)}px;"
                    f" letter-spacing: 0.5px;"
                )
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
            self.cancel_worker.result_ready.connect(
                lambda ok, msg, od, _inv=invoice_id: self._on_cancel_finished(ok, msg, od, _inv)
            )
            self.cancel_worker.start()

    def _on_cancel_finished(self, success: bool, message: str, order_data: dict, invoice_id: str = ""):
        if success:
            if invoice_id:
                self._locally_cancelled.add(invoice_id)
            msg = (
                "Bekor so'rovi yuborildi!\n\n"
                "Oshxona/bar xabardor qilindi.\n"
                "Manager ERPNext da ko'rib tasdiqlaydi."
            )
            InfoDialog(self, "So'rov yuborildi", msg, kind="success").exec()
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
            InfoDialog(self, "Bekor qilinmadi", message, kind="info").exec()
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
            InfoDialog(self, "Xatolik",
                       f"Oflayn buyurtmani bekor qilishda muammo:\n{e}",
                       kind="info").exec()
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

        InfoDialog(
            self, "Bekor qilindi",
            "Oflayn buyurtma bekor qilindi ✓\nOshxona xabardor qilindi.",
            kind="success",
        ).exec()
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
        # Tugmani qaytarish (widget o'chirilgan bo'lishi mumkin)
        try:
            btn.setEnabled(True)
            btn.setText("🖨 Chop")
        except RuntimeError:
            pass

        # Worker QThread tugashini kutmasdan dialog ko'rsatsak segfault bo'lishi
        # mumkin (SocketIO thread + modal dialog race). QTimer orqali keyingi
        # event loop iteratsiyasiga kechiktiramiz.
        QTimer.singleShot(0, lambda: self._show_reprint_result(success, message))

    def _show_reprint_result(self, success: bool, message: str):
        try:
            if success:
                InfoDialog(self, "Chop etildi", message, kind="success").exec()
            else:
                InfoDialog(self, "Printer ulanmagan", message,
                           kind="info", icon="🖨️").exec()
        except RuntimeError:
            # Widget destroyed — info dialog yo'q
            logger.debug("Reprint natija dialog widget destroyed: %s", message)
