import json
import requests
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QInputDialog, QFrame, QWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import load_config
from core.logger import get_logger
from core.constants import HISTORY_FETCH_LIMIT, API_TIMEOUT_LONG

logger = get_logger(__name__)


class FetchHistoryWorker(QThread):
    finished = pyqtSignal(bool, list)

    def __init__(self):
        super().__init__()
        self.api = FrappeAPI()

    def run(self):
        config = load_config()
        cashier = config.get("cashier")
        if not cashier:
            self.finished.emit(False, [])
            return

        fields = '["name", "customer", "grand_total", "posting_date", "posting_time", "status", "docstatus"]'
        endpoint = f"{self.api.url}/api/resource/POS Invoice"
        params = {
            "fields": fields,
            "filters": json.dumps([["POS Invoice", "cashier", "=", cashier]]),
            "order_by": "creation desc",
            "limit_page_length": HISTORY_FETCH_LIMIT,
        }

        try:
            response = requests.get(
                endpoint, headers=self.api.get_headers(is_json=False),
                params=params, timeout=API_TIMEOUT_LONG,
            )
            if response.status_code == 200:
                data = response.json().get("data", [])
                self.finished.emit(True, data)
            else:
                logger.warning("Tarix yuklashda xatolik: status %d", response.status_code)
                self.finished.emit(False, [])
        except requests.exceptions.RequestException as e:
            logger.error("Tarix yuklashda xatolik: %s", e)
            self.finished.emit(False, [])


class FetchDetailsWorker(QThread):
    finished = pyqtSignal(bool, dict)

    def __init__(self, invoice_id: str):
        super().__init__()
        self.invoice_id = invoice_id
        self.api = FrappeAPI()

    def run(self):
        success, doc = self.api.call_method(
            "frappe.client.get", {"doctype": "POS Invoice", "name": self.invoice_id}
        )
        if success and isinstance(doc, dict):
            self.finished.emit(True, doc)
        else:
            self.finished.emit(False, {})


class CancelOrderWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, invoice_id: str, reason: str):
        super().__init__()
        self.invoice_id = invoice_id
        self.reason = reason
        self.api = FrappeAPI()

    def run(self):
        payload = {"invoice_id": self.invoice_id, "reason": self.reason}
        success, response = self.api.call_method(
            "ury.ury.doctype.ury_order.ury_order.cancel_order", payload
        )
        if success:
            self.finished.emit(True, "Chek muvaffaqiyatli bekor qilindi!")
        else:
            self.finished.emit(False, f"Xatolik: {response}")


class TransactionDetailDialog(QDialog):
    def __init__(self, parent, invoice_id: str):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle(f"Chek tafsilotlari: {invoice_id}")
        self.setFixedSize(550, 600)
        self.init_ui()
        self._load_details()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header = QLabel(f"Chek #{self.invoice_id}")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #1f2937;")
        layout.addWidget(header)

        layout.addWidget(QLabel("Mahsulotlar:"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Mahsulot", "Soni", "Summa"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet("border: 1px solid #d1d5db; border-radius: 4px;")
        layout.addWidget(self.table)

        layout.addSpacing(15)
        layout.addWidget(QLabel("TO'LOV TURLARI:"))
        self.payments_area = QFrame()
        self.payments_area.setStyleSheet(
            "background: #f9fafb; border: 1px dashed #d1d5db; border-radius: 8px; padding: 10px;"
        )
        self.payments_layout = QVBoxLayout(self.payments_area)
        layout.addWidget(self.payments_area)

        layout.addStretch()

        close_btn = QPushButton("YOPISH")
        close_btn.setFixedHeight(50)
        close_btn.setStyleSheet("background-color: #f3f4f6; font-weight: bold; border-radius: 8px;")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _load_details(self):
        self.worker = FetchDetailsWorker(self.invoice_id)
        self.worker.finished.connect(self._on_details_loaded)
        self.worker.start()

    def _on_details_loaded(self, success: bool, doc: dict):
        if not success:
            QMessageBox.warning(self, "Xato", "Tafsilotlarni yuklab bo'lmadi.")
            return

        # Fill Items Table
        items = doc.get("items", [])
        self.table.setRowCount(0)
        for row_idx, item in enumerate(items):
            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, QTableWidgetItem(item.get("item_name", "")))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(item.get("qty", 0))))
            self.table.setItem(row_idx, 2, QTableWidgetItem(
                f"{item.get('amount', 0):,.0f}".replace(",", " ")
            ))

        # Fill Payments
        self._clear_layout(self.payments_layout)
        payments = doc.get("payments", [])
        found = False
        for p in payments:
            amount = float(p.get("amount", 0))
            if amount > 0:
                p_row_widget = QWidget()
                p_row = QHBoxLayout(p_row_widget)
                p_row.setContentsMargins(0, 2, 0, 2)

                p_mode = QLabel(f"  {p.get('mode_of_payment')}:")
                p_mode.setStyleSheet("font-weight: bold; color: #374151; font-size: 14px;")

                p_amt = QLabel(f"{amount:,.0f} UZS".replace(",", " "))
                p_amt.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 14px;")

                p_row.addWidget(p_mode)
                p_row.addStretch()
                p_row.addWidget(p_amt)
                self.payments_layout.addWidget(p_row_widget)
                found = True

        if not found:
            self.payments_layout.addWidget(QLabel("To'lov ma'lumotlari mavjud emas."))

    @staticmethod
    def _clear_layout(layout):
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().setParent(None)


class HistoryWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_history()

    def init_ui(self):
        self.setWindowTitle("Tranzaksiyalar Tarixi")
        self.setFixedSize(900, 650)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("So'nggi tranzaksiyalar")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #1f2937;")
        header_layout.addWidget(title)

        hint = QLabel("(Tafsilotlar uchun qator ustiga 2 marta bosing)")
        hint.setStyleSheet("color: gray; font-style: italic;")
        header_layout.addWidget(hint)

        header_layout.addStretch()
        refresh_btn = QPushButton("Yangilash")
        refresh_btn.setStyleSheet(
            "padding: 8px 15px; background: white; border: 1px solid #d1d5db; border-radius: 6px;"
        )
        refresh_btn.clicked.connect(self.load_history)
        header_layout.addWidget(refresh_btn)
        layout.addLayout(header_layout)

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Sana", "Vaqt", "Mijoz", "Summa", "Amal"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("font-size: 14px; border: 1px solid #d1d5db; border-radius: 8px;")
        self.table.itemDoubleClicked.connect(self._show_details)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 130)
        layout.addWidget(self.table)

        close_btn = QPushButton("YOPISH")
        close_btn.setFixedHeight(50)
        close_btn.setStyleSheet(
            "background-color: #ef4444; color: white; font-weight: bold; border-radius: 8px;"
        )
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def load_history(self):
        self.table.setRowCount(0)
        self.worker = FetchHistoryWorker()
        self.worker.finished.connect(self._on_history_loaded)
        self.worker.start()

    def _on_history_loaded(self, success: bool, data: list):
        if not success:
            return
        for row_idx, item in enumerate(data):
            self.table.insertRow(row_idx)
            self.table.setRowHeight(row_idx, 50)
            inv_name = item.get("name", "")
            status = item.get("status", "")

            self.table.setItem(row_idx, 0, QTableWidgetItem(inv_name))
            self.table.setItem(row_idx, 1, QTableWidgetItem(item.get("posting_date", "")))
            self.table.setItem(row_idx, 2, QTableWidgetItem(item.get("posting_time", "")))
            self.table.setItem(row_idx, 3, QTableWidgetItem(item.get("customer", "")))
            self.table.setItem(row_idx, 4, QTableWidgetItem(
                f"{item.get('grand_total', 0):,.0f} UZS".replace(",", " ")
            ))

            if status != "Cancelled":
                cancel_btn = QPushButton("Bekor qilish")
                cancel_btn.setStyleSheet(
                    "background-color: #f97316; color: white; font-weight: bold; "
                    "border-radius: 4px; padding: 5px;"
                )
                cancel_btn.clicked.connect(lambda checked, inv=inv_name: self._confirm_cancel(inv))
                self.table.setCellWidget(row_idx, 5, cancel_btn)
            else:
                lbl = QLabel("BEKOR QILINGAN")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 11px;")
                self.table.setCellWidget(row_idx, 5, lbl)

    def _show_details(self, item):
        invoice_id = self.table.item(item.row(), 0).text()
        TransactionDetailDialog(self, invoice_id).exec()

    def _confirm_cancel(self, invoice_id: str):
        reason, ok = QInputDialog.getText(
            self, "Bekor qilish", f"#{invoice_id} chekni bekor qilish sababi:"
        )
        if ok and reason.strip():
            self.cancel_worker = CancelOrderWorker(invoice_id, reason.strip())
            self.cancel_worker.finished.connect(
                lambda s, m: (QMessageBox.information(self, "Natija", m), self.load_history())
            )
            self.cancel_worker.start()
