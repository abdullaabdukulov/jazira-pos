"""Offline navbat paneli — elite inline drawer.

Ko'rinishi:
  ┌────────────────────────────────────────────────────────┐
  │  OFFLINE NAVBAT           [3]    Yangilash      ✕     │
  │  Internet tiklanishi bilan avtomatik yuboriladi       │
  ├────────────────────────────────────────────────────────┤
  │  VAQT     MIJOZ           SUMMA          TUR          │
  │  ...                                                   │
  └────────────────────────────────────────────────────────┘

Empty: custom-painted cloud-check icon + "Navbat bo'sh" subtitle.
"""
import json

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPainterPath,
)
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScroller,
    QScrollerProperties, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from core.logger import get_logger
from database.models import PendingInvoice, db
from ui.scale import font, s

logger = get_logger(__name__)


# ── Palette ──────────────────────────────────────────────
_GOLD = "#c89968"
_GOLD_LIGHT = "#e6c693"
_GOLD_DEEP = "#a07a44"
_SLATE_900 = "#0f172a"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748b"
_SLATE_400 = "#94a3b8"
_SLATE_300 = "#cbd5e1"
_SLATE_200 = "#e2e8f0"
_SLATE_100 = "#f1f5f9"
_SLATE_50 = "#f8fafc"
_EMERALD_600 = "#059669"
_EMERALD_50 = "#ecfdf5"
_EMERALD_200 = "#a7f3d0"


def _touch_scroll(table):
    scroller = QScroller.scroller(table.viewport())
    scroller.grabGesture(
        table.viewport(),
        QScroller.ScrollerGestureType.LeftMouseButtonGesture,
    )
    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
    scroller.setScrollerProperties(props)


# ═══════════════════════════════════════════════════════════
#  EmptyIllustration — custom-painted gold check-mark on cloud
# ═══════════════════════════════════════════════════════════
class EmptyIllustration(QWidget):
    """Gold gradient halqa + ichida emerald check belgisi."""

    def __init__(self, size: int = 84, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - w * 0.08

        # Soft gold halo (ambient glow)
        halo = QColor(200, 153, 104, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QRectF(0, 0, w, h))

        # Outer gold ring
        ring_grad = QLinearGradient(0, 0, 0, h)
        ring_grad.setColorAt(0.0, QColor(_GOLD_LIGHT))
        ring_grad.setColorAt(1.0, QColor(_GOLD_DEEP))
        pen = QPen(QBrush(ring_grad), w * 0.045)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Inner emerald fill
        inner_r = r * 0.72
        p.setPen(Qt.PenStyle.NoPen)
        emerald_bg = QColor(_EMERALD_50)
        p.setBrush(QBrush(emerald_bg))
        p.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))

        # Check-mark stroke
        check_pen = QPen(QColor(_EMERALD_600), w * 0.07)
        check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(check_pen)
        path = QPainterPath()
        path.moveTo(cx - w * 0.13, cy + w * 0.01)
        path.lineTo(cx - w * 0.03, cy + w * 0.11)
        path.lineTo(cx + w * 0.16, cy - w * 0.10)
        p.drawPath(path)


# ═══════════════════════════════════════════════════════════
#  Counter pill — gold when > 0, muted when 0
# ═══════════════════════════════════════════════════════════
class CountPill(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(12), s(4), s(12), s(4))
        layout.setSpacing(0)
        self._label = QLabel("0")
        f = QFont()
        f.setPixelSize(font(13))
        f.setWeight(QFont.Weight.Black)
        self._label.setFont(f)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self.setFixedHeight(s(28))
        self.setMinimumWidth(s(38))
        self.set_count(0)

    def set_count(self, n: int):
        self._count = int(n)
        self._label.setText(str(self._count))
        if self._count > 0:
            self.setStyleSheet(f"""
                QFrame {{
                    background: {_GOLD};
                    border-radius: {s(12)}px;
                    border: none;
                }}
            """)
            self._label.setStyleSheet(
                "color: white; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background: {_SLATE_100};
                    border-radius: {s(12)}px;
                    border: none;
                }}
            """)
            self._label.setStyleSheet(
                f"color: {_SLATE_500}; background: transparent; border: none;"
            )


# ═══════════════════════════════════════════════════════════
#  OfflineQueueWindow
# ═══════════════════════════════════════════════════════════
class OfflineQueueWindow(QWidget):
    """Inline panel — embed in main_window, show/hide via toggle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(28), s(18), s(28), s(20))
        root.setSpacing(s(14))

        # ── Header ───────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(s(14))

        # Title block
        title_block = QVBoxLayout()
        title_block.setSpacing(s(2))

        title = QLabel("OFFLINE NAVBAT")
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

        subtitle = QLabel("Internet tiklanishi bilan avtomatik yuboriladi")
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
        header.addSpacing(s(12))

        # Count pill
        self.count_badge = CountPill()
        header.addWidget(self.count_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        header.addStretch()

        # Refresh + close action group
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
        refresh_btn.clicked.connect(self.load_pending)
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

        # ── Hairline separator ───────────────────────
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_SLATE_100}; border: none;")
        root.addWidget(sep)

        # ── Table ────────────────────────────────────
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["VAQT", "MIJOZ", "SUMMA", "TUR"]
        )
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
                color: #c2410c;
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

        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, s(120))   # Vaqt
        self.table.setColumnWidth(2, s(160))   # Summa
        self.table.setColumnWidth(3, s(160))   # Tur

        # Summa o'ng tomonda
        right_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self.table.horizontalHeaderItem(2).setTextAlignment(right_align)

        root.addWidget(self.table)
        _touch_scroll(self.table)

        # ── Empty state ──────────────────────────────
        self.empty_widget = QWidget()
        self.empty_widget.setStyleSheet(
            "background: white; border: none; outline: none;"
        )
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setSpacing(s(14))
        empty_layout.setContentsMargins(0, s(24), 0, s(24))
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        illus_row = QHBoxLayout()
        illus_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        illus_row.addWidget(EmptyIllustration(s(72)))
        empty_layout.addLayout(illus_row)

        empty_title = QLabel("Navbat bo'sh")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setFrameShape(QFrame.Shape.NoFrame)
        empty_title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        etf = QFont()
        etf.setPixelSize(font(15))
        etf.setWeight(QFont.Weight.Bold)
        etf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        empty_title.setFont(etf)
        empty_title.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        empty_layout.addWidget(empty_title)

        empty_sub = QLabel("Barcha cheklar serverga muvaffaqiyatli yuborilgan")
        empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_sub.setFrameShape(QFrame.Shape.NoFrame)
        empty_sub.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        esf = QFont()
        esf.setPixelSize(font(12))
        esf.setWeight(QFont.Weight.Medium)
        empty_sub.setFont(esf)
        empty_sub.setStyleSheet(
            f"color: {_SLATE_500}; background: transparent;"
            f" border: none; outline: none;"
        )
        empty_layout.addWidget(empty_sub)

        self.empty_widget.setVisible(False)
        root.addWidget(self.empty_widget)

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
            self.count_badge.set_count(count)

            if count == 0:
                self.table.setVisible(False)
                self.empty_widget.setVisible(True)
                return

            self.table.setVisible(True)
            self.empty_widget.setVisible(False)

            for row_idx, inv in enumerate(items):
                self.table.insertRow(row_idx)
                self.table.setRowHeight(row_idx, s(50))

                data = {}
                try:
                    data = json.loads(inv.invoice_data)
                except (json.JSONDecodeError, ValueError):
                    pass

                customer = data.get("customer", "—")
                total = data.get("total_amount", 0.0)
                order_type = data.get("order_type", "—")

                time_item = QTableWidgetItem(
                    inv.created_at.strftime("%H:%M:%S")
                )
                time_item.setForeground(QBrush(QColor(_SLATE_500)))
                self.table.setItem(row_idx, 0, time_item)

                cust_item = QTableWidgetItem(str(customer))
                cust_font = QFont()
                cust_font.setPixelSize(font(13))
                cust_font.setWeight(QFont.Weight.DemiBold)
                cust_item.setFont(cust_font)
                cust_item.setForeground(QBrush(QColor(_SLATE_900)))
                self.table.setItem(row_idx, 1, cust_item)

                amt_str = f"{total:,.0f} UZS".replace(",", " ")
                amt_item = QTableWidgetItem(amt_str)
                amt_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                )
                amt_font = QFont()
                amt_font.setPixelSize(font(13))
                amt_font.setWeight(QFont.Weight.Bold)
                amt_item.setFont(amt_font)
                amt_item.setForeground(QBrush(QColor(_SLATE_900)))
                self.table.setItem(row_idx, 2, amt_item)

                type_item = QTableWidgetItem(str(order_type))
                type_item.setForeground(QBrush(QColor(_SLATE_700)))
                self.table.setItem(row_idx, 3, type_item)

        except Exception as e:
            logger.error("Oflayn cheklar yuklashda xatolik: %s", e)
