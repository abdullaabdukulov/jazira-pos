import json
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFrame, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import HISTORY_FETCH_LIMIT
from ui.scale import s, font

logger = get_logger(__name__)


# ─────────────────────────────────────
#  Worker threads
# ─────────────────────────────────────
class FetchHistoryWorker(QThread):
    result_ready = pyqtSignal(bool, list)

    def __init__(self, api: FrappeAPI, opening_entry: str = ""):
        super().__init__()
        self.api = api
        self.opening_entry = opening_entry

    def run(self):
        if not self.opening_entry:
            self.result_ready.emit(True, [])
            return

        fields = json.dumps(["name", "customer", "grand_total", "posting_date", "posting_time", "status", "docstatus"])
        filters = json.dumps([["POS Invoice", "pos_opening_entry", "=", self.opening_entry]])

        data = self.api.fetch_data(
            "POS Invoice", fields=fields, filters=filters, limit=HISTORY_FETCH_LIMIT,
        )
        if data is not None:
            data.sort(key=lambda x: x.get("creation", ""), reverse=True)
            self.result_ready.emit(True, data)
        else:
            self.result_ready.emit(False, [])


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
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, invoice_id: str, reason: str):
        super().__init__()
        self.invoice_id = invoice_id
        self.reason = reason
        self.api = api

    def run(self):
        success, response = self.api.call_method(
            "ury.ury.doctype.ury_order.ury_order.cancel_order",
            {"invoice_id": self.invoice_id, "reason": self.reason},
        )
        if success:
            self.result_ready.emit(True, "Chek muvaffaqiyatli bekor qilindi!")
        else:
            self.result_ready.emit(False, f"Xatolik: {response}")


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
class CancelReasonDialog(QDialog):
    def __init__(self, parent, invoice_id: str):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle("Bekor qilish sababi")
        self.setFixedSize(s(620), s(480))
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

        # Input display
        self.input = QLineEdit()
        self.input.setPlaceholderText("Sabab yozing...")
        self.input.setFixedHeight(s(46))
        self.input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {font(15)}px; color: #1e293b;
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
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Sana", "Vaqt", "Mijoz", "Summa", "Amal"])
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
        self.table.setColumnWidth(5, s(130))
        layout.addWidget(self.table)

    def load_history(self):
        self.table.setRowCount(0)
        self.worker = FetchHistoryWorker(self.api, self.opening_entry)
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
                btn = QPushButton("Bekor qilish")
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #fff7ed; color: #ea580c;
                        font-weight: 600; font-size: {font(12)}px;
                        border-radius: {s(6)}px; border: 1px solid #fed7aa;
                        padding: {s(4)}px {s(10)}px;
                    }}
                    QPushButton:hover {{ background: #ffedd5; }}
                """)
                btn.clicked.connect(lambda _, inv=inv_name: self._confirm_cancel(inv))
                self.table.setCellWidget(i, 5, btn)
            else:
                lbl = QLabel("Bekor qilingan")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(f"color: #ef4444; font-weight: 600; font-size: {font(11)}px;")
                self.table.setCellWidget(i, 5, lbl)

    def _show_details(self, item):
        invoice_id = self.table.item(item.row(), 0).text()
        TransactionDetailDialog(self, self.api, invoice_id).exec()

    def _confirm_cancel(self, invoice_id: str):
        dlg = CancelReasonDialog(self, invoice_id)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            reason = dlg.get_reason()
            self.cancel_worker = CancelOrderWorker(self.api, invoice_id, reason)
            self.cancel_worker.result_ready.connect(self._on_cancel_finished)
            self.cancel_worker.start()

    def _on_cancel_finished(self, success: bool, message: str):
        QMessageBox.information(self, "Natija", message)
        self.load_history()
