"""POS Opening Entry ro'yxati — filialga tegishli barcha kassa ochish/yopish tarixi."""
import json
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import load_config
from core.logger import get_logger

logger = get_logger(__name__)


class FetchShiftsWorker(QThread):
    finished = pyqtSignal(bool, list)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        config = load_config()
        pos_profile = config.get("pos_profile", "")
        if not pos_profile:
            self.finished.emit(False, [])
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
            self.finished.emit(True, data)
        else:
            self.finished.emit(False, [])


class FetchShiftDetailWorker(QThread):
    finished = pyqtSignal(bool, dict, list)  # success, opening_doc, payments

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
            self.finished.emit(False, {}, [])
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

        self.finished.emit(True, doc, payments)


class ShiftDetailDialog(QDialog):
    def __init__(self, parent, api: FrappeAPI, opening_name: str):
        super().__init__(parent)
        self.api = api
        self.opening_name = opening_name
        self.setWindowTitle("Smena tafsilotlari")
        self.setFixedSize(650, 700)
        self.setStyleSheet("""
            QDialog { background: #f8fafc; }
            QLabel { background: transparent; border: none; }
            QFrame { border: none; }
            QScrollArea { border: none; background: transparent; }
            QWidget#ScrollContent { background: transparent; }
        """)
        self._init_ui()
        self._load()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- Header Card ---
        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_card.setStyleSheet("""
            QFrame#HeaderCard {
                background: white;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            }
        """)
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(20, 20, 20, 20)

        # Top row: ID and Status
        top_row = QHBoxLayout()
        self.id_lbl = QLabel(f"Smena: {self.opening_name}")
        self.id_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #64748b;")
        top_row.addWidget(self.id_lbl)
        
        top_row.addStretch()
        
        self.status_lbl = QLabel("Yuklanmoqda...")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("""
            QLabel {
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                background: #e2e8f0;
                color: #475569;
            }
        """)
        top_row.addWidget(self.status_lbl)
        header_layout.addLayout(top_row)

        header_layout.addSpacing(10)

        # Bottom row: User and Date
        bot_row = QHBoxLayout()
        self.user_lbl = QLabel("...")
        self.user_lbl.setStyleSheet("font-size: 24px; font-weight: 900; color: #0f172a;")
        bot_row.addWidget(self.user_lbl)

        bot_row.addStretch()

        self.date_lbl = QLabel("...")
        self.date_lbl.setStyleSheet("font-size: 16px; font-weight: 500; color: #475569;")
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
        self.content_layout.setSpacing(15)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        scroll.setWidget(self.content)
        main_layout.addWidget(scroll, 1)

        # --- Footer ---
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        
        close_btn = QPushButton("Yopish")
        close_btn.setFixedSize(150, 45)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton { 
                background: #cbd5e1; color: #334155;
                font-weight: bold; font-size: 16px;
                border-radius: 8px; border: none; 
            }
            QPushButton:hover { background: #94a3b8; color: white; }
        """)
        close_btn.clicked.connect(self.close)
        footer_layout.addWidget(close_btn)
        
        main_layout.addLayout(footer_layout)

    def _load(self):
        self.worker = FetchShiftDetailWorker(self.api, self.opening_name)
        self.worker.finished.connect(self._on_loaded)
        self.worker.start()

    def _fmt(self, val):
        return f"{float(val):,.0f} UZS".replace(",", " ")

    def _create_section_card(self, title: str):
        card = QFrame()
        card.setObjectName("SectionCard")
        card.setStyleSheet("""
            QFrame#SectionCard {
                background: white;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #94a3b8; letter-spacing: 1px; text-transform: uppercase;")
        layout.addWidget(lbl)
        
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #f1f5f9; border: none;")
        layout.addWidget(line)
        
        return card, layout

    def _add_opening_row(self, layout, mop, amt):
        row = QWidget()
        row.setObjectName("RowWidget")
        row.setStyleSheet("QWidget#RowWidget { border: none; }")
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0, 5, 0, 5)
        
        icon = QLabel("💰" if "Naqd" in mop or "Cash" in mop else "💳")
        icon.setStyleSheet("font-size: 18px; border: none;")
        row_l.addWidget(icon)
        
        lbl = QLabel(mop)
        lbl.setStyleSheet("font-size: 16px; font-weight: 600; color: #334155; border: none;")
        row_l.addWidget(lbl)
        
        row_l.addStretch()
        
        val = QLabel(self._fmt(amt))
        val.setStyleSheet("font-size: 18px; font-weight: bold; color: #0f172a; border: none;")
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

        self.user_lbl.setText(user.split("@")[0] if "@" in user else user)
        self.date_lbl.setText(f"📅 {date}  ⏱ {time_str}")

        if status == "Open":
            self.status_lbl.setText("🟢 OCHIQ")
            self.status_lbl.setStyleSheet("""
                QLabel { padding: 6px 12px; border-radius: 6px; font-size: 14px; font-weight: bold; background: #dcfce7; color: #16a34a; border: none; }
            """)
        else:
            self.status_lbl.setText("🔴 YOPILGAN")
            self.status_lbl.setStyleSheet("""
                QLabel { padding: 6px 12px; border-radius: 6px; font-size: 14px; font-weight: bold; background: #f1f5f9; color: #64748b; border: none; }
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
                ("Dasturda", Qt.AlignmentFlag.AlignRight, 120),
                ("Kassada", Qt.AlignmentFlag.AlignRight, 120),
                ("Farq", Qt.AlignmentFlag.AlignRight, 100),
            ]:
                lbl = QLabel(text)
                lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #64748b; border: none;")
                lbl.setAlignment(align)
                if width:
                    lbl.setFixedWidth(width)
                hdr_l.addWidget(lbl)
            
            p_lyt.addWidget(hdr)
            
            line = QFrame()
            line.setFixedHeight(1)
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
                row_l.setContentsMargins(0, 8, 0, 8)

                mop_lbl = QLabel(mop)
                mop_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #334155; border: none;")
                row_l.addWidget(mop_lbl)

                exp_lbl = QLabel(self._fmt(expected))
                exp_lbl.setFixedWidth(120)
                exp_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                exp_lbl.setStyleSheet("font-size: 15px; color: #475569; border: none;")
                row_l.addWidget(exp_lbl)

                clos_lbl = QLabel(self._fmt(closing))
                clos_lbl.setFixedWidth(120)
                clos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                clos_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #0f172a; border: none;")
                row_l.addWidget(clos_lbl)

                diff_lbl = QLabel(self._fmt(diff))
                diff_lbl.setFixedWidth(100)
                diff_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                if diff < 0:
                    diff_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #ef4444; border: none;") # Qizil (Kamo'mad)
                elif diff > 0:
                    diff_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #10b981; border: none;") # Yashil (Ortiqcha)
                else:
                    diff_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #94a3b8; border: none;") # Kulrang
                row_l.addWidget(diff_lbl)

                p_lyt.addWidget(row)

            self.content_layout.addWidget(p_card)

        elif status == "Open":
            card = QFrame()
            card.setObjectName("OpenCard")
            card.setStyleSheet("QFrame#OpenCard { background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; }")
            l = QVBoxLayout(card)
            l.setContentsMargins(20, 30, 20, 30)
            msg = QLabel("⚠️ Smena hali ochiq. Yopilish hisoboti mavjud emas.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet("font-size: 16px; font-weight: bold; color: #d97706; border: none;")
            l.addWidget(msg)
            self.content_layout.addWidget(card)


class PosShiftsWindow(QWidget):
    """Inline panel — filialga tegishli POS Opening Entry lar ro'yxati."""

    def __init__(self, api: FrappeAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # Header
        hdr_row = QHBoxLayout()

        title = QLabel("Kassa tarixi")
        title.setStyleSheet("font-size: 18px; font-weight: 800; color: #1e293b;")
        hdr_row.addWidget(title)

        hint = QLabel("(2× bosing — batafsil)")
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
        refresh_btn.clicked.connect(self.load_shifts)
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

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Kassir", "Sana", "Vaqt", "Holat"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                border: none; background: white; font-size: 14px;
            }
            QTableWidget::item { padding: 10px 8px; border-bottom: 1px solid #f1f5f9; }
            QTableWidget::item:selected { background: #dbeafe; color: #1e40af; }
            QHeaderView::section {
                background: #f8fafc; color: #64748b;
                font-size: 12px; font-weight: bold; letter-spacing: 0.5px;
                padding: 12px 8px; border: none;
                border-bottom: 2px solid #e2e8f0;
                text-align: left;
            }
        """)
        self.table.itemDoubleClicked.connect(self._show_details)

        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch) 
        
        layout.addWidget(self.table)


    def load_shifts(self):
        self.table.setRowCount(0)
        self.worker = FetchShiftsWorker(self.api)
        self.worker.finished.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, success: bool, data: list):
        if not success:
            return
        self.table.setRowCount(0)
        for i, item in enumerate(data):
            self.table.insertRow(i)
            # Make rows taller for better touch/click experience
            self.table.setRowHeight(i, 50)

            # Center/Left Alignments properly configured
            id_item = QTableWidgetItem(item.get("name", ""))
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
            
            # Align status to left for better look, matching header
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 4, status_item)

    def _show_details(self, item):
        opening_name = self.table.item(item.row(), 0).text()
        ShiftDetailDialog(self, self.api, opening_name).exec()
