"""Offline navbat paneli — inline widget (dialog emas)."""
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QScroller, QScrollerProperties,
)
from PyQt6.QtCore import Qt
from database.models import PendingInvoice, db
from core.logger import get_logger
from ui.scale import s, font

logger = get_logger(__name__)


def _touch_scroll(table):
    scroller = QScroller.scroller(table.viewport())
    scroller.grabGesture(table.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
    scroller.setScrollerProperties(props)


class OfflineQueueWindow(QWidget):
    """Inline panel — embed in main_window, show/hide via toggle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(16), s(12), s(16), s(12))
        layout.setSpacing(s(10))

        # ── Header row ──────────────────────
        hdr_row = QHBoxLayout()

        title = QLabel("Offline navbat")
        title.setStyleSheet(f"font-size: {font(18)}px; font-weight: 800; color: #1e293b;")
        hdr_row.addWidget(title)

        hint = QLabel("Internet tiklanishi bilan avtomatik yuboriladi")
        hint.setStyleSheet(f"font-size: {font(11)}px; color: #94a3b8; font-style: italic;")
        hdr_row.addWidget(hint)
        hdr_row.addStretch()

        self.count_badge = QLabel("0")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_badge.setFixedSize(s(36), s(28))
        self.count_badge.setStyleSheet(f"""
            background: #fef2f2; color: #dc2626;
            font-weight: 800; font-size: {font(13)}px;
            border-radius: {s(6)}px; border: 1px solid #fecaca;
        """)
        hdr_row.addWidget(self.count_badge)

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
        refresh_btn.clicked.connect(self.load_pending)
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
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Vaqt", "Mijoz", "Summa", "Buyurtma turi"])
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

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)
        _touch_scroll(self.table)

        # ── Empty state ──────────────────────
        self.empty_label = QLabel("✅  Barcha cheklar yuborilgan — navbat bo'sh")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            font-size: {font(14)}px; font-weight: 600; color: #94a3b8;
            padding: {s(30)}px;
        """)
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

    def load_pending(self):
        self.table.setRowCount(0)
        try:
            db.connect(reuse_if_open=True)
            pending = (
                PendingInvoice.select()
                .where(PendingInvoice.status == "Pending")
                .order_by(PendingInvoice.created_at.desc())
            )
            items = list(pending)
            count = len(items)
            self.count_badge.setText(str(count))

            if count == 0:
                self.table.setVisible(False)
                self.empty_label.setVisible(True)
                self.count_badge.setStyleSheet(f"""
                    background: #f0fdf4; color: #16a34a;
                    font-weight: 800; font-size: {font(13)}px;
                    border-radius: {s(6)}px; border: 1px solid #bbf7d0;
                """)
            else:
                self.table.setVisible(True)
                self.empty_label.setVisible(False)
                self.count_badge.setStyleSheet(f"""
                    background: #fef2f2; color: #dc2626;
                    font-weight: 800; font-size: {font(13)}px;
                    border-radius: {s(6)}px; border: 1px solid #fecaca;
                """)

            for row_idx, inv in enumerate(items):
                self.table.insertRow(row_idx)
                self.table.setRowHeight(row_idx, s(46))

                data = {}
                try:
                    data = json.loads(inv.invoice_data)
                except (json.JSONDecodeError, ValueError):
                    pass

                customer = data.get("customer", "—")
                total = data.get("total_amount", 0.0)
                order_type = data.get("order_type", "—")

                self.table.setItem(row_idx, 0, QTableWidgetItem(
                    inv.created_at.strftime("%H:%M:%S")
                ))
                self.table.setItem(row_idx, 1, QTableWidgetItem(str(customer)))

                amt = QTableWidgetItem(f"{total:,.0f} UZS".replace(",", " "))
                amt.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
                self.table.setItem(row_idx, 2, amt)

                self.table.setItem(row_idx, 3, QTableWidgetItem(str(order_type)))

        except Exception as e:
            logger.error("Oflayn cheklar yuklashda xatolik: %s", e)
