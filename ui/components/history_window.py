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

logger = get_logger(__name__)


# ─────────────────────────────────────
#  Worker threads
# ─────────────────────────────────────
class FetchHistoryWorker(QThread):
    finished = pyqtSignal(bool, list)

    def __init__(self, api: FrappeAPI, opening_entry: str = ""):
        super().__init__()
        self.api = api
        self.opening_entry = opening_entry

    def run(self):
        if not self.opening_entry:
            self.finished.emit(True, [])
            return

        fields = json.dumps(["name", "customer", "grand_total", "posting_date", "posting_time", "status", "docstatus"])
        filters = json.dumps([["POS Invoice", "pos_opening_entry", "=", self.opening_entry]])

        data = self.api.fetch_data(
            "POS Invoice", fields=fields, filters=filters, limit=HISTORY_FETCH_LIMIT,
        )
        if data is not None:
            data.sort(key=lambda x: x.get("creation", ""), reverse=True)
            self.finished.emit(True, data)
        else:
            self.finished.emit(False, [])


class FetchDetailsWorker(QThread):
    finished = pyqtSignal(bool, dict)

    def __init__(self, api: FrappeAPI, invoice_id: str):
        super().__init__()
        self.invoice_id = invoice_id
        self.api = api

    def run(self):
        success, doc = self.api.call_method(
            "frappe.client.get", {"doctype": "POS Invoice", "name": self.invoice_id}
        )
        self.finished.emit(success and isinstance(doc, dict), doc if isinstance(doc, dict) else {})


class CancelOrderWorker(QThread):
    finished = pyqtSignal(bool, str)

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
            self.finished.emit(True, "Chek muvaffaqiyatli bekor qilindi!")
        else:
            self.finished.emit(False, f"Xatolik: {response}")


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
        self.setFixedSize(520, 560)
        self.setStyleSheet("background: white;")
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        hdr = QLabel(f"Chek  #{self.invoice_id}")
        hdr.setStyleSheet("font-size: 18px; font-weight: 800; color: #1e293b;")
        layout.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(sep)

        # Items table
        lbl = QLabel("MAHSULOTLAR")
        lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        layout.addWidget(lbl)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Mahsulot", "Soni", "Summa"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet("""
            QTableWidget { border: none; font-size: 13px; background: white; }
            QTableWidget::item { padding: 6px; }
            QTableWidget::item:selected { background: #dbeafe; color: #1e40af; }
            QHeaderView::section {
                background: #f8fafc; color: #94a3b8;
                font-size: 11px; font-weight: 700;
                padding: 6px; border: none;
                border-bottom: 1px solid #e2e8f0;
            }
        """)
        layout.addWidget(self.table)

        # Payments
        pay_lbl = QLabel("TO'LOV TURLARI")
        pay_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 1px;")
        layout.addWidget(pay_lbl)

        self.payments_frame = QFrame()
        self.payments_frame.setStyleSheet(
            "background: #f8fafc; border-radius: 10px; padding: 2px;"
        )
        self.payments_layout = QVBoxLayout(self.payments_frame)
        self.payments_layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.payments_frame)

        layout.addStretch()

        close_btn = QPushButton("Yopish")
        close_btn.setFixedHeight(44)
        close_btn.setStyleSheet("""
            QPushButton { background: #f1f5f9; color: #475569;
                font-weight: 700; border-radius: 10px; border: none; }
            QPushButton:hover { background: #e2e8f0; }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _load(self):
        self.worker = FetchDetailsWorker(self.api, self.invoice_id)
        self.worker.finished.connect(self._on_loaded)
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
                row_l.setContentsMargins(0, 2, 0, 2)
                mode = QLabel(p.get("mode_of_payment", ""))
                mode.setStyleSheet("font-weight: 600; color: #374151; font-size: 13px;")
                amt = QLabel(f"{float(p.get('amount', 0)):,.0f} UZS".replace(",", " "))
                amt.setStyleSheet("color: #16a34a; font-weight: 700; font-size: 13px;")
                row_l.addWidget(mode)
                row_l.addStretch()
                row_l.addWidget(amt)
                self.payments_layout.addWidget(row_w)
        else:
            no = QLabel("To'lov ma'lumotlari mavjud emas.")
            no.setStyleSheet("color: #94a3b8; font-size: 12px;")
            self.payments_layout.addWidget(no)


# ─────────────────────────────────────
#  Cancel reason dialog with keyboard
# ─────────────────────────────────────
class CancelReasonDialog(QDialog):
    def __init__(self, parent, invoice_id: str):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle("Bekor qilish sababi")
        self.setFixedSize(620, 480)
        self.setStyleSheet("background: white;")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Title
        title = QLabel(f"#{self.invoice_id}  —  Bekor qilish sababi")
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #1e293b;")
        layout.addWidget(title)

        # Input display
        self.input = QLineEdit()
        self.input.setReadOnly(True)
        self.input.setPlaceholderText("Sabab yozing...")
        self.input.setFixedHeight(46)
        self.input.setStyleSheet("""
            QLineEdit {
                font-size: 15px; color: #1e293b;
                background: white;
                border: 2px solid #3b82f6;
                border-radius: 10px; padding: 8px 14px;
            }
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
            row_w.setSpacing(4)
            for k in row_keys:
                row_w.addWidget(self._make_key(k))
            layout.addLayout(row_w)

        # Buttons
        btn_row = QHBoxLayout()

        cancel_btn = QPushButton("Bekor")
        cancel_btn.setFixedHeight(44)
        cancel_btn.setStyleSheet("""
            QPushButton { background: #f1f5f9; color: #64748b;
                font-weight: 700; border-radius: 10px; border: none; }
            QPushButton:hover { background: #e2e8f0; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("✓  Tasdiqlash")
        confirm_btn.setFixedHeight(44)
        confirm_btn.setStyleSheet("""
            QPushButton { background: #ef4444; color: white;
                font-weight: 700; font-size: 14px;
                border-radius: 10px; border: none; }
            QPushButton:hover { background: #dc2626; }
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

    def _make_key(self, key):
        label = '␣' if key == 'SPACE' else ('TOZALASH' if key == 'CLR' else key)
        btn = QPushButton(label)
        btn.setFixedHeight(44)
        if key == '⌫':
            style = "background:#fee2e2; color:#ef4444; font-size:15px; font-weight:bold;"
        elif key == 'CLR':
            style = "background:#fff7ed; color:#ea580c; font-size:10px; font-weight:bold;"
        elif key == 'SPACE':
            style = "background:#eff6ff; color:#3b82f6; font-size:13px; font-weight:bold;"
            btn.setMinimumWidth(80)
        elif key.isdigit():
            style = "background:#f1f5f9; color:#334155; font-size:13px; font-weight:700;"
        else:
            style = "background:white; color:#1e293b; font-size:13px; font-weight:600;"
        btn.setStyleSheet(f"""
            QPushButton {{ {style} border:1px solid #e2e8f0; border-radius:6px; }}
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
            self.input.setStyleSheet("""
                QLineEdit {
                    font-size: 15px; color: #1e293b;
                    background: #fff5f5;
                    border: 2px solid #ef4444;
                    border-radius: 10px; padding: 8px 14px;
                }
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
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # ── Header row ──────────────────────
        hdr_row = QHBoxLayout()

        title = QLabel("So'nggi tranzaksiyalar")
        title.setStyleSheet("font-size: 18px; font-weight: 800; color: #1e293b;")
        hdr_row.addWidget(title)

        hint = QLabel("(2× bosing — tafsilot)")
        hint.setStyleSheet("font-size: 11px; color: #94a3b8; font-style: italic;")
        hdr_row.addWidget(hint)
        hdr_row.addStretch()

        refresh_btn = QPushButton("⟳  Yangilash")
        refresh_btn.setFixedHeight(44)
        refresh_btn.setStyleSheet("""
            QPushButton {
                padding: 0 16px; background: #f1f5f9; color: #475569;
                font-weight: 600; font-size: 13px;
                border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #e2e8f0; }
        """)
        refresh_btn.clicked.connect(self.load_history)
        hdr_row.addWidget(refresh_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(44, 44)
        close_btn.setStyleSheet("""
            QPushButton { background: #fee2e2; color: #b91c1c;
                font-weight: 700; font-size: 14px; border-radius: 8px; border: none; }
            QPushButton:hover { background: #fecaca; }
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
        self.table.setStyleSheet("""
            QTableWidget {
                border: none; background: white; font-size: 13px;
            }
            QTableWidget::item { padding: 5px 8px; border-bottom: 1px solid #f1f5f9; }
            QTableWidget::item:selected { background: #dbeafe; color: #1e40af; }
            QHeaderView::section {
                background: #f8fafc; color: #94a3b8;
                font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
                padding: 8px 8px; border: none;
                border-bottom: 1px solid #e2e8f0;
            }
        """)
        self.table.itemDoubleClicked.connect(self._show_details)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 130)
        layout.addWidget(self.table)

    def load_history(self):
        self.table.setRowCount(0)
        self.worker = FetchHistoryWorker(self.api, self.opening_entry)
        self.worker.finished.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, success: bool, data: list):
        if not success:
            return
        self.table.setRowCount(0)
        for i, item in enumerate(data):
            self.table.insertRow(i)
            self.table.setRowHeight(i, 46)
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
                btn.setStyleSheet("""
                    QPushButton {
                        background: #fff7ed; color: #ea580c;
                        font-weight: 600; font-size: 12px;
                        border-radius: 6px; border: 1px solid #fed7aa;
                        padding: 4px 10px;
                    }
                    QPushButton:hover { background: #ffedd5; }
                """)
                btn.clicked.connect(lambda _, inv=inv_name: self._confirm_cancel(inv))
                self.table.setCellWidget(i, 5, btn)
            else:
                lbl = QLabel("Bekor qilingan")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 11px;")
                self.table.setCellWidget(i, 5, lbl)

    def _show_details(self, item):
        invoice_id = self.table.item(item.row(), 0).text()
        TransactionDetailDialog(self, self.api, invoice_id).exec()

    def _confirm_cancel(self, invoice_id: str):
        dlg = CancelReasonDialog(self, invoice_id)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            reason = dlg.get_reason()
            self.cancel_worker = CancelOrderWorker(self.api, invoice_id, reason)
            self.cancel_worker.finished.connect(self._on_cancel_finished)
            self.cancel_worker.start()

    def _on_cancel_finished(self, success: bool, message: str):
        QMessageBox.information(self, "Natija", message)
        self.load_history()
