"""POS Opening Entry ro'yxati — filialga tegishli barcha kassa ochish/yopish tarixi."""
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QScrollArea, QGridLayout, QMessageBox,
    QScroller, QScrollerProperties,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import load_config
from core.logger import get_logger
from ui.scale import s, font

logger = get_logger(__name__)


def _touch_scroll(widget):
    """Sensorli ekran uchun kinetic scroll."""
    viewport = widget.viewport()
    scroller = QScroller.scroller(viewport)
    scroller.grabGesture(viewport, QScroller.ScrollerGestureType.LeftMouseButtonGesture)
    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
    scroller.setScrollerProperties(props)


class FetchShiftsWorker(QThread):
    result_ready = pyqtSignal(bool, list)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        config = load_config()
        pos_profile = config.get("pos_profile", "")
        if not pos_profile:
            self.result_ready.emit(False, [])
            return

        data = self.api.fetch_data(
            "POS Opening Entry",
            fields=json.dumps([
                "name", "user", "posting_date", "creation",
                "status", "docstatus",
            ]),
            filters=json.dumps([["POS Opening Entry", "pos_profile", "=", pos_profile]]),
            limit=50,
        )

        if data is not None:
            data.sort(key=lambda x: x.get("creation", ""), reverse=True)
            self.result_ready.emit(True, data)
        else:
            self.result_ready.emit(False, [])


class FetchShiftDetailWorker(QThread):
    result_ready = pyqtSignal(bool, dict, list)  # success, opening_doc, payments

    def __init__(self, api: FrappeAPI, opening_name: str):
        super().__init__()
        self.api = api
        self.opening_name = opening_name

    def run(self):
        success, doc = self.api.call_method(
            "frappe.client.get",
            {"doctype": "POS Opening Entry", "name": self.opening_name},
        )
        if not success or not isinstance(doc, dict):
            self.result_ready.emit(False, {}, [])
            return

        # Closing entry bormi tekshirish
        closing_data = self.api.fetch_data(
            "POS Closing Entry",
            fields=json.dumps(["name", "posting_date"]),
            filters=json.dumps([
                ["POS Closing Entry", "pos_opening_entry", "=", self.opening_name],
                ["POS Closing Entry", "docstatus", "=", 1],
            ]),
            limit=1,
        )

        payments = []
        if closing_data:
            closing_success, closing_doc = self.api.call_method(
                "frappe.client.get",
                {"doctype": "POS Closing Entry", "name": closing_data[0]["name"]},
            )
            if closing_success and isinstance(closing_doc, dict):
                payments = closing_doc.get("payment_reconciliation", [])

        self.result_ready.emit(True, doc, payments)


class FetchZReportDataWorker(QThread):
    """Smena uchun Z-otchyot ma'lumotlarini serverdan olish."""
    result_ready = pyqtSignal(bool, dict)

    def __init__(self, api: FrappeAPI, opening_name: str):
        super().__init__()
        self.api = api
        self.opening_name = opening_name

    def run(self):
        try:
            # 1. Opening Entry
            ok, opening_doc = self.api.call_method(
                "frappe.client.get",
                {"doctype": "POS Opening Entry", "name": self.opening_name},
            )
            if not ok or not isinstance(opening_doc, dict):
                self.result_ready.emit(False, {})
                return

            # 2. Closing Entry
            closing_list = self.api.fetch_data(
                "POS Closing Entry",
                fields=json.dumps(["name", "posting_date", "posting_time"]),
                filters=json.dumps([
                    ["POS Closing Entry", "pos_opening_entry", "=", self.opening_name],
                    ["POS Closing Entry", "docstatus", "=", 1],
                ]),
                limit=1,
            )

            payment_reconciliation = []
            closed_at = "—"
            total_invoices = 0

            if closing_list:
                ok2, closing_doc = self.api.call_method(
                    "frappe.client.get",
                    {"doctype": "POS Closing Entry", "name": closing_list[0]["name"]},
                )
                if ok2 and isinstance(closing_doc, dict):
                    payment_reconciliation = closing_doc.get("payment_reconciliation", [])
                    total_invoices = int(closing_doc.get("total_quantity", 0))
                    p_date = closing_doc.get("posting_date", "")
                    p_time = str(closing_doc.get("posting_time", ""))[:5]
                    closed_at = f"{p_date}  {p_time}"

            cfg = load_config()

            # Ochilish vaqti
            creation = str(opening_doc.get("creation", ""))
            opened_at = creation[:10] + "  " + creation[11:16] if len(creation) >= 16 else creation

            # Naqd pul ajratish
            _CASH_KEYS = {"cash", "naqd", "naqd pul"}
            expected_cash = 0.0
            actual_cash = 0.0
            total_sales = sum(float(p.get("expected_amount", 0)) for p in payment_reconciliation)

            for p in payment_reconciliation:
                if p.get("mode_of_payment", "").lower().strip() in _CASH_KEYS:
                    expected_cash = float(p.get("expected_amount", 0))
                    actual_cash = float(p.get("closing_amount", 0))
            # Agar hech biri "naqd" bo'lmasa — birinchisi
            if expected_cash == 0 and payment_reconciliation:
                expected_cash = float(payment_reconciliation[0].get("expected_amount", 0))
                actual_cash = float(payment_reconciliation[0].get("closing_amount", 0))

            cashier = opening_doc.get("user", "—")
            if "@" in cashier:
                cashier = cashier.split("@")[0]

            report_data = {
                "terminal_name": cfg.get("company", "JAZIRA POS"),
                "pos_profile": cfg.get("pos_profile", ""),
                "shift_id": self.opening_name,
                "cashier": cashier,
                "opened_at": opened_at,
                "closed_at": closed_at,
                "payments": payment_reconciliation,
                "total_invoices": total_invoices,
                "total_sales": total_sales,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "cash_diff": actual_cash - expected_cash,
            }

            self.result_ready.emit(True, report_data)

        except Exception as e:
            logger.error("FetchZReportDataWorker xatosi: %s", e)
            self.result_ready.emit(False, {})


class ShiftDetailDialog(QDialog):
    def __init__(self, parent, api: FrappeAPI, opening_name: str):
        super().__init__(parent)
        self.api = api
        self.opening_name = opening_name
        self.setWindowTitle("Smena tafsilotlari")
        self.setFixedSize(s(650), s(700))
        self.setStyleSheet(f"""
            QDialog {{ background: #f8fafc; }}
            QLabel {{ background: transparent; border: none; }}
            QFrame {{ border: none; }}
            QScrollArea {{ border: none; background: transparent; }}
            QWidget#ScrollContent {{ background: transparent; }}
        """)
        self._init_ui()
        self._load()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(s(20), s(20), s(20), s(20))
        main_layout.setSpacing(s(15))

        # --- Header Card ---
        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_card.setStyleSheet(f"""
            QFrame#HeaderCard {{
                background: white;
                border-radius: {s(12)}px;
                border: 1px solid #e2e8f0;
            }}
        """)
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(s(20), s(20), s(20), s(20))

        # Top row: ID and Status
        top_row = QHBoxLayout()
        self.id_lbl = QLabel(f"Smena: {self.opening_name}")
        self.id_lbl.setStyleSheet(f"font-size: {font(16)}px; font-weight: bold; color: #64748b;")
        top_row.addWidget(self.id_lbl)

        top_row.addStretch()

        self.status_lbl = QLabel("Yuklanmoqda...")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet(f"""
            QLabel {{
                padding: {s(6)}px {s(12)}px;
                border-radius: {s(6)}px;
                font-size: {font(14)}px;
                font-weight: bold;
                background: #e2e8f0;
                color: #475569;
            }}
        """)
        top_row.addWidget(self.status_lbl)
        header_layout.addLayout(top_row)

        header_layout.addSpacing(s(10))

        # Bottom row: User and Date
        bot_row = QHBoxLayout()
        self.user_lbl = QLabel("...")
        self.user_lbl.setStyleSheet(f"font-size: {font(24)}px; font-weight: 900; color: #0f172a;")
        bot_row.addWidget(self.user_lbl)

        bot_row.addStretch()

        self.date_lbl = QLabel("...")
        self.date_lbl.setStyleSheet(f"font-size: {font(16)}px; font-weight: 500; color: #475569;")
        bot_row.addWidget(self.date_lbl)
        header_layout.addLayout(bot_row)

        main_layout.addWidget(header_card)

        # --- Scrollable Content ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("MainScroll")

        self.content = QWidget()
        self.content.setObjectName("ScrollContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(s(15))
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.content)
        main_layout.addWidget(scroll, 1)
        _touch_scroll(scroll)

        # --- Footer ---
        footer_layout = QHBoxLayout()

        self.z_print_btn = QPushButton("🖨  Z-Chop etish")
        self.z_print_btn.setFixedHeight(s(45))
        self.z_print_btn.setEnabled(False)
        self.z_print_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.z_print_btn.setStyleSheet(f"""
            QPushButton {{
                background: #1d4ed8; color: white;
                font-weight: bold; font-size: {font(14)}px;
                border-radius: {s(8)}px; border: none;
                padding: 0 {s(20)}px;
            }}
            QPushButton:hover {{ background: #1e40af; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #94a3b8; }}
        """)
        self.z_print_btn.clicked.connect(self._z_print)
        footer_layout.addWidget(self.z_print_btn)

        footer_layout.addStretch()

        close_btn = QPushButton("Yopish")
        close_btn.setFixedSize(s(150), s(45))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: #cbd5e1; color: #334155;
                font-weight: bold; font-size: {font(16)}px;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #94a3b8; color: white; }}
        """)
        close_btn.clicked.connect(self.close)
        footer_layout.addWidget(close_btn)

        main_layout.addLayout(footer_layout)

    def _load(self):
        self.worker = FetchShiftDetailWorker(self.api, self.opening_name)
        self.worker.result_ready.connect(self._on_loaded)
        self.worker.start()

    def _fmt(self, val):
        return f"{float(val):,.0f} UZS".replace(",", " ")

    def _create_section_card(self, title: str):
        card = QFrame()
        card.setObjectName("SectionCard")
        card.setStyleSheet(f"""
            QFrame#SectionCard {{
                background: white;
                border-radius: {s(12)}px;
                border: 1px solid #e2e8f0;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(s(20), s(20), s(20), s(20))
        layout.setSpacing(s(10))

        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size: {font(14)}px; font-weight: bold; color: #94a3b8; letter-spacing: 1px; text-transform: uppercase;")
        layout.addWidget(lbl)

        line = QFrame()
        line.setFixedHeight(s(1))
        line.setStyleSheet("background: #f1f5f9; border: none;")
        layout.addWidget(line)

        return card, layout

    def _add_opening_row(self, layout, mop, amt):
        row = QWidget()
        row.setObjectName("RowWidget")
        row.setStyleSheet("QWidget#RowWidget { border: none; }")
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0, s(5), 0, s(5))

        icon = QLabel("💰" if "Naqd" in mop or "Cash" in mop else "💳")
        icon.setStyleSheet(f"font-size: {font(18)}px; border: none;")
        row_l.addWidget(icon)

        lbl = QLabel(mop)
        lbl.setStyleSheet(f"font-size: {font(16)}px; font-weight: 600; color: #334155; border: none;")
        row_l.addWidget(lbl)

        row_l.addStretch()

        val = QLabel(self._fmt(amt))
        val.setStyleSheet(f"font-size: {font(18)}px; font-weight: bold; color: #0f172a; border: none;")
        row_l.addWidget(val)

        layout.addWidget(row)

    def _on_loaded(self, success: bool, doc: dict, payments: list):
        if not success:
            self.user_lbl.setText("Xatolik")
            self.status_lbl.setText("Ma'lumot topilmadi")
            return

        user = doc.get("user", "")
        date = doc.get("posting_date", "")
        creation = str(doc.get("creation", ""))
        time_str = creation[11:16] if len(creation) > 16 else ""
        status = doc.get("status", "")

        # Z-Chop tugmasini yopilgan smena uchun yoqish
        if status != "Open" and payments:
            self.z_print_btn.setEnabled(True)

        self.user_lbl.setText(user.split("@")[0] if "@" in user else user)
        self.date_lbl.setText(f"📅 {date}  ⏱ {time_str}")

        if status == "Open":
            self.status_lbl.setText("🟢 OCHIQ")
            self.status_lbl.setStyleSheet(f"""
                QLabel {{ padding: {s(6)}px {s(12)}px; border-radius: {s(6)}px; font-size: {font(14)}px; font-weight: bold; background: #dcfce7; color: #16a34a; border: none; }}
            """)
        else:
            self.status_lbl.setText("🔴 YOPILGAN")
            self.status_lbl.setStyleSheet(f"""
                QLabel {{ padding: {s(6)}px {s(12)}px; border-radius: {s(6)}px; font-size: {font(14)}px; font-weight: bold; background: #f1f5f9; color: #64748b; border: none; }}
            """)

        # Ochilish summalari Card
        balance = doc.get("balance_details", [])
        if balance:
            card, lyt = self._create_section_card("Ochilish summalari (Baza)")
            for bd in balance:
                self._add_opening_row(lyt, bd.get("mode_of_payment", ""), float(bd.get("opening_amount", 0)))
            self.content_layout.addWidget(card)

        # Yopilish hisobi Card
        if payments:
            p_card, p_lyt = self._create_section_card("Smena yakunidagi hisobot")

            # Header
            hdr = QWidget()
            hdr.setObjectName("HdrWidget")
            hdr.setStyleSheet("QWidget#HdrWidget { border: none; }")
            hdr_l = QHBoxLayout(hdr)
            hdr_l.setContentsMargins(0, 0, 0, 0)

            for text, align, width in [
                ("To'lov turi", Qt.AlignmentFlag.AlignLeft, 0),
                ("Dasturda", Qt.AlignmentFlag.AlignRight, s(120)),
                ("Kassada", Qt.AlignmentFlag.AlignRight, s(120)),
                ("Farq", Qt.AlignmentFlag.AlignRight, s(100)),
            ]:
                lbl = QLabel(text)
                lbl.setStyleSheet(f"font-size: {font(12)}px; font-weight: bold; color: #64748b; border: none;")
                lbl.setAlignment(align)
                if width:
                    lbl.setFixedWidth(width)
                hdr_l.addWidget(lbl)

            p_lyt.addWidget(hdr)

            line = QFrame()
            line.setFixedHeight(s(1))
            line.setStyleSheet("background: #f1f5f9; border: none;")
            p_lyt.addWidget(line)

            for p in payments:
                mop = p.get("mode_of_payment", "")
                expected = float(p.get("expected_amount", 0))
                closing = float(p.get("closing_amount", 0))
                diff = float(p.get("difference", 0))

                row = QWidget()
                row.setObjectName("RowWidget")
                row.setStyleSheet("QWidget#RowWidget { border: none; }")
                row_l = QHBoxLayout(row)
                row_l.setContentsMargins(0, s(8), 0, s(8))

                mop_lbl = QLabel(mop)
                mop_lbl.setStyleSheet(f"font-size: {font(15)}px; font-weight: 600; color: #334155; border: none;")
                row_l.addWidget(mop_lbl)

                exp_lbl = QLabel(self._fmt(expected))
                exp_lbl.setFixedWidth(s(120))
                exp_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                exp_lbl.setStyleSheet(f"font-size: {font(15)}px; color: #475569; border: none;")
                row_l.addWidget(exp_lbl)

                clos_lbl = QLabel(self._fmt(closing))
                clos_lbl.setFixedWidth(s(120))
                clos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                clos_lbl.setStyleSheet(f"font-size: {font(15)}px; font-weight: bold; color: #0f172a; border: none;")
                row_l.addWidget(clos_lbl)

                diff_lbl = QLabel(self._fmt(diff))
                diff_lbl.setFixedWidth(s(100))
                diff_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                if diff < 0:
                    diff_lbl.setStyleSheet(f"font-size: {font(15)}px; font-weight: bold; color: #ef4444; border: none;")
                elif diff > 0:
                    diff_lbl.setStyleSheet(f"font-size: {font(15)}px; font-weight: bold; color: #10b981; border: none;")
                else:
                    diff_lbl.setStyleSheet(f"font-size: {font(15)}px; font-weight: bold; color: #94a3b8; border: none;")
                row_l.addWidget(diff_lbl)

                p_lyt.addWidget(row)

            self.content_layout.addWidget(p_card)

        elif status == "Open":
            card = QFrame()
            card.setObjectName("OpenCard")
            card.setStyleSheet(f"QFrame#OpenCard {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: {s(12)}px; }}")
            l = QVBoxLayout(card)
            l.setContentsMargins(s(20), s(30), s(20), s(30))
            msg = QLabel("⚠️ Smena hali ochiq. Yopilish hisoboti mavjud emas.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet(f"font-size: {font(16)}px; font-weight: bold; color: #d97706; border: none;")
            l.addWidget(msg)
            self.content_layout.addWidget(card)

    def _z_print(self):
        """Z-otchyotni serverdan olib printerga chop etish."""
        self.z_print_btn.setEnabled(False)
        self.z_print_btn.setText("⏳  Yuklanmoqda...")
        self._z_worker = FetchZReportDataWorker(self.api, self.opening_name)
        self._z_worker.result_ready.connect(self._on_z_data_ready)
        self._z_worker.start()

    def _on_z_data_ready(self, success: bool, report_data: dict):
        self.z_print_btn.setEnabled(True)
        self.z_print_btn.setText("🖨  Z-Chop etish")
        if not success:
            QMessageBox.warning(self, "Xatolik", "Z-otchyot ma'lumotlarini olishda xatolik.")
            return
        try:
            from core.printer import print_z_report
            ok = print_z_report(report_data)
            if ok:
                QMessageBox.information(self, "Muvaffaqiyatli", "Z-otchyot chop etildi!")
            else:
                QMessageBox.warning(
                    self, "Printer",
                    "Printer sozlanmagan yoki ulanmagan.\nPrinter guide ni tekshiring."
                )
        except Exception as e:
            QMessageBox.critical(self, "Xatolik", f"Chop etishda xatolik:\n{e}")


class PosShiftsWindow(QWidget):
    """Inline panel — filialga tegishli POS Opening Entry lar ro'yxati."""

    def __init__(self, api: FrappeAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(16), s(12), s(16), s(12))
        layout.setSpacing(s(10))

        # Header
        hdr_row = QHBoxLayout()

        title = QLabel("Kassa tarixi")
        title.setStyleSheet(f"font-size: {font(18)}px; font-weight: 800; color: #1e293b;")
        hdr_row.addWidget(title)

        hint = QLabel("(2× bosing — batafsil)")
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
        refresh_btn.clicked.connect(self.load_shifts)
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

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Kassir", "Sana", "Vaqt", "Holat", "Z-Otchyot"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border: none; background: white; font-size: {font(14)}px;
            }}
            QTableWidget::item {{ padding: {s(10)}px {s(8)}px; border-bottom: 1px solid #f1f5f9; }}
            QTableWidget::item:selected {{ background: #dbeafe; color: #1e40af; }}
            QHeaderView::section {{
                background: #f8fafc; color: #64748b;
                font-size: {font(12)}px; font-weight: bold; letter-spacing: 0.5px;
                padding: {s(12)}px {s(8)}px; border: none;
                border-bottom: 2px solid #e2e8f0;
                text-align: left;
            }}
        """)
        self.table.itemDoubleClicked.connect(self._show_details)

        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, s(120))

        layout.addWidget(self.table)
        _touch_scroll(self.table)


    def load_shifts(self):
        self.table.setRowCount(0)
        self.worker = FetchShiftsWorker(self.api)
        self.worker.result_ready.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, success: bool, data: list):
        if not success:
            return
        self.table.setRowCount(0)
        for i, item in enumerate(data):
            self.table.insertRow(i)
            self.table.setRowHeight(i, s(50))

            opening_name = item.get("name", "")

            id_item = QTableWidgetItem(opening_name)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 0, id_item)

            user_item = QTableWidgetItem(item.get("user", "").split('@')[0])
            user_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 1, user_item)

            date_item = QTableWidgetItem(item.get("posting_date", ""))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 2, date_item)

            creation = str(item.get("creation", ""))
            time_str = creation[11:16] if len(creation) > 16 else ""
            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 3, time_item)

            status = item.get("status", "")
            status_item = QTableWidgetItem("🟢 Ochiq" if status == "Open" else "🔴 Yopilgan")
            if status == "Open":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                status_item.setForeground(Qt.GlobalColor.darkGray)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 4, status_item)

            # Z-Chop tugmasi (faqat yopilgan smena uchun)
            if status != "Open":
                z_btn = QPushButton("🖨 Z-Chop")
                z_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #eff6ff; color: #1d4ed8;
                        font-weight: 600; font-size: {font(12)}px;
                        border-radius: {s(6)}px; border: 1px solid #bfdbfe;
                        padding: {s(4)}px {s(8)}px;
                    }}
                    QPushButton:hover {{ background: #dbeafe; }}
                    QPushButton:disabled {{ background: #f1f5f9; color: #94a3b8; border-color: #e2e8f0; }}
                """)
                z_btn.clicked.connect(
                    lambda _, nm=opening_name, b=z_btn: self._reprint_z(nm, b)
                )
                self.table.setCellWidget(i, 5, z_btn)
            else:
                lbl = QLabel("—")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(f"color: #94a3b8; font-size: {font(12)}px;")
                self.table.setCellWidget(i, 5, lbl)

    def _show_details(self, item):
        opening_name = self.table.item(item.row(), 0).text()
        ShiftDetailDialog(self, self.api, opening_name).exec()

    def _reprint_z(self, opening_name: str, btn: QPushButton):
        btn.setEnabled(False)
        btn.setText("⏳...")
        worker = FetchZReportDataWorker(self.api, opening_name)
        worker.result_ready.connect(lambda ok, data, b=btn: self._on_z_ready(ok, data, b))
        # Worker ni saqlash (GC dan himoya)
        if not hasattr(self, '_z_workers'):
            self._z_workers = []
        self._z_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._z_workers.remove(w) if w in self._z_workers else None)
        worker.start()

    def _on_z_ready(self, success: bool, report_data: dict, btn: QPushButton):
        try:
            btn.setEnabled(True)
            btn.setText("🖨 Z-Chop")
        except RuntimeError:
            pass

        if not success:
            QMessageBox.warning(self, "Xatolik", "Z-otchyot ma'lumotlarini olishda xatolik.")
            return

        try:
            from core.printer import print_z_report
            ok = print_z_report(report_data)
            if ok:
                QMessageBox.information(self, "Muvaffaqiyatli", "Z-otchyot chop etildi!")
            else:
                QMessageBox.warning(
                    self, "Printer",
                    "Printer sozlanmagan yoki ulanmagan.\n"
                    "POS Profile da printerni sozlang."
                )
        except Exception as e:
            QMessageBox.critical(self, "Xatolik", f"Chop etishda xatolik:\n{e}")
