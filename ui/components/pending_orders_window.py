"""PendingOrdersWindow — to'lov kutilayotgan Draft POS Invoicelar paneli.

TZ 4.2.4 ga muvofiq:
- Filter chiplari (order_type bo'yicha + countlar)
- Jadval: Vaqt, #N/Stol, Tur, Mijoz, Kim urdi, Summa, Amallar
- Amallar: "To'lov" (CheckoutWindow), "Bekor" (sabab bilan)
- Ofitsant rolida: faqat o'zinikini ko'radi, amallar yashirin
- Real-time refresh (Phase 2)

Elite UI: uppercase tabular headers, gold count pills, subtle action buttons.
"""
from PyQt6.QtCore import Qt, QRectF, QThread, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QScroller, QScrollerProperties, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.api import FrappeAPI
from core.config import load_config
from core.constants import ORDER_TYPES, ORDER_TYPE_MAP
from core.logger import get_logger
from database.models import db
from ui.components.dialogs import InfoDialog
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
_EMERALD_700 = "#047857"
_EMERALD_50 = "#ecfdf5"
_RED_700 = "#b91c1c"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"
_AMBER = "#c2410c"


# Frappe order_type ↔ UI Uzbek nomi (display uchun teskari xarita)
_ORDER_TYPE_LABEL = {
    "Dine In": "Shu yerda",
    "Take Away": "Saboy",
    "Delivery": "Dastavka",
}


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


# ═══════════════════════════════════════════════════════════════════════════
#  Workers (mantiq saqlanadi — UI ga aloqasi yo'q)
# ═══════════════════════════════════════════════════════════════════════════

class FetchPendingWorker(QThread):
    """getPendingOrders va getPendingOrderCounts ni parallel chaqiradi."""
    result_ready = pyqtSignal(bool, list, dict)

    def __init__(self, api: FrappeAPI, order_type: str = "",
                 only_mine: bool = False, mine_name: str = ""):
        super().__init__()
        self.api = api
        self.order_type = order_type
        self.only_mine = only_mine
        self.mine_name = mine_name

    def run(self):
        try:
            args = {
                "only_mine": 1 if self.only_mine else 0,
                "mine_cashier_name": self.mine_name or "",
                "limit": 100,
                "limit_start": 0,
            }
            if self.order_type:
                args["order_type"] = self.order_type

            ok_rows, rows = self.api.call_method(
                "ury.ury_pos.api.getPendingOrders", args
            )
            ok_counts, counts = self.api.call_method(
                "ury.ury_pos.api.getPendingOrderCounts",
                {"only_mine": 1 if self.only_mine else 0,
                 "mine_cashier_name": self.mine_name or ""}
            )

            if ok_rows:
                self.result_ready.emit(
                    True,
                    rows if isinstance(rows, list) else [],
                    counts if isinstance(counts, dict) else {},
                )
            else:
                self.result_ready.emit(False, [], {})
        except Exception as e:
            logger.error("FetchPendingWorker xato: %s", e)
            self.result_ready.emit(False, [], {})
        finally:
            if not db.is_closed():
                db.close()


class FetchPendingCountWorker(QThread):
    result_ready = pyqtSignal(bool, dict)

    def __init__(self, api: FrappeAPI, only_mine: bool = False, mine_name: str = ""):
        super().__init__()
        self.api = api
        self.only_mine = only_mine
        self.mine_name = mine_name

    def run(self):
        try:
            ok, counts = self.api.call_method(
                "ury.ury_pos.api.getPendingOrderCounts",
                {"only_mine": 1 if self.only_mine else 0,
                 "mine_cashier_name": self.mine_name or ""},
            )
            if ok and isinstance(counts, dict):
                self.result_ready.emit(True, counts)
            else:
                self.result_ready.emit(False, {})
        except Exception as e:
            logger.debug("FetchPendingCountWorker xato: %s", e)
            self.result_ready.emit(False, {})


class CancelPendingWorker(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, invoice: str, reason: str,
                 cashier_user: str = "", active_cashier: str = "",
                 active_cashier_role: str = "Kassir"):
        super().__init__()
        self.api = api
        self.invoice = invoice
        self.reason = reason
        self.cashier_user = cashier_user
        self.active_cashier = active_cashier
        self.active_cashier_role = active_cashier_role

    def run(self):
        try:
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.cancelPendingOrder",
                {
                    "invoice": self.invoice,
                    "reason": self.reason,
                    "cashier": self.cashier_user,
                    "active_cashier": self.active_cashier,
                    "active_cashier_role": self.active_cashier_role,
                },
            )
            if ok and isinstance(resp, dict) and resp.get("status") == "ok":
                self.result_ready.emit(True, "Buyurtma bekor qilindi")
            else:
                self.result_ready.emit(False, str(resp))
        except Exception as e:
            self.result_ready.emit(False, str(e))
        finally:
            if not db.is_closed():
                db.close()


class FetchOrderDetailWorker(QThread):
    result_ready = pyqtSignal(bool, dict)

    def __init__(self, api: FrappeAPI, invoice: str):
        super().__init__()
        self.api = api
        self.invoice = invoice

    def run(self):
        try:
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.getPendingOrderDetail",
                {"invoice": self.invoice},
            )
            if ok and isinstance(resp, dict):
                self.result_ready.emit(True, resp)
            else:
                self.result_ready.emit(False, {})
        except Exception as e:
            logger.error("FetchOrderDetailWorker xato: %s", e)
            self.result_ready.emit(False, {})
        finally:
            if not db.is_closed():
                db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Reusable UI atoms
# ═══════════════════════════════════════════════════════════════════════════

class CountPill(QFrame):
    """Gold pill > 0, muted slate pill = 0."""

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
            self.setStyleSheet(
                f"QFrame {{ background: {_GOLD}; border-radius: {s(12)}px; border: none; }}"
            )
            self._label.setStyleSheet(
                "color: white; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background: {_SLATE_100}; border-radius: {s(12)}px; border: none; }}"
            )
            self._label.setStyleSheet(
                f"color: {_SLATE_500}; background: transparent; border: none;"
            )


class EmptyIllustration(QWidget):
    """Gold halqa + emerald check belgisi."""

    def __init__(self, size: int = 72, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - w * 0.08

        # Ambient halo
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(200, 153, 104, 18))
        p.drawEllipse(QRectF(0, 0, w, h))

        # Gold ring
        ring_grad = QLinearGradient(0, 0, 0, h)
        ring_grad.setColorAt(0.0, QColor(_GOLD_LIGHT))
        ring_grad.setColorAt(1.0, QColor(_GOLD_DEEP))
        pen = QPen(QBrush(ring_grad), w * 0.045)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Emerald disk
        inner_r = r * 0.72
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_EMERALD_50))
        p.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))

        # Check
        check_pen = QPen(QColor(_EMERALD_600), w * 0.07)
        check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(check_pen)
        path = QPainterPath()
        path.moveTo(cx - w * 0.13, cy + w * 0.01)
        path.lineTo(cx - w * 0.03, cy + w * 0.11)
        path.lineTo(cx + w * 0.16, cy - w * 0.10)
        p.drawPath(path)


def _header_button(label: str, on_click) -> QPushButton:
    btn = QPushButton(label)
    btn.setFixedHeight(s(36))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"""
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
    btn.clicked.connect(on_click)
    return btn


def _close_button(on_click) -> QPushButton:
    btn = QPushButton("✕")
    btn.setFixedSize(s(36), s(36))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"""
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
    btn.clicked.connect(on_click)
    return btn


# ═══════════════════════════════════════════════════════════════════════════
#  Asosiy panel
# ═══════════════════════════════════════════════════════════════════════════

class PendingOrdersWindow(QWidget):
    """Inline panel — main_window'da embed bo'ladi, show/hide toggle."""

    pay_requested = pyqtSignal(dict)
    count_changed = pyqtSignal(int)

    def __init__(self, api: FrappeAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.active_order_type = ""
        self._role = "Kassir"
        self._mine_name = ""
        self._mine_user = ""
        self._chip_buttons: dict[str, QPushButton] = {}
        self._init_ui()

    # ──────────────────────────────────────────
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

        title = QLabel("TO'LOV KUTILMOQDA")
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

        subtitle = QLabel("Buyurtmani 2 marta bosing — tafsilot · 'To'lov' — yakunlash")
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

        self.count_badge = CountPill()
        header.addWidget(self.count_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        header.addStretch()
        header.addWidget(_header_button("Yangilash", self.load_pending))
        header.addWidget(_close_button(self.hide))
        root.addLayout(header)

        # Hairline
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_SLATE_100}; border: none;")
        root.addWidget(sep)

        # ── Filter chiplari ────────────────────
        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(s(8))
        self._chips_row.setContentsMargins(0, s(2), 0, s(2))
        self._chips_row.addStretch()
        chips_widget = QWidget()
        chips_widget.setStyleSheet("background: transparent;")
        chips_widget.setLayout(self._chips_row)
        root.addWidget(chips_widget)

        self._render_chips({})

        # ── Jadval ────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "VAQT", "#N / STOL", "TUR", "MIJOZ", "KIM URDI", "SUMMA", "AMALLAR",
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
            }}
            QTableWidget::item {{
                padding: {s(10)}px {s(18)}px;
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
                color: {_AMBER};
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
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, s(100))   # Vaqt
        self.table.setColumnWidth(1, s(140))   # #N / Stol
        self.table.setColumnWidth(2, s(120))   # Tur
        self.table.setColumnWidth(4, s(180))   # Kim urdi
        self.table.setColumnWidth(5, s(150))   # Summa
        self.table.setColumnWidth(6, s(180))   # Amallar

        # Summa o'ng tomonda, Amallar markazda
        right_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        center_align = Qt.AlignmentFlag.AlignCenter
        self.table.horizontalHeaderItem(5).setTextAlignment(right_align)
        self.table.horizontalHeaderItem(6).setTextAlignment(center_align)

        root.addWidget(self.table)
        _touch_scroll(self.table)

        # ── Empty state ──────────────────────
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

        self.empty_title = QLabel("To'lov kutayotgan buyurtma yo'q")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setFrameShape(QFrame.Shape.NoFrame)
        self.empty_title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        etf = QFont()
        etf.setPixelSize(font(15))
        etf.setWeight(QFont.Weight.Bold)
        etf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        self.empty_title.setFont(etf)
        self.empty_title.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        empty_layout.addWidget(self.empty_title)

        self.empty_sub = QLabel("Yangi buyurtma kelishi bilan bu yerda paydo bo'ladi")
        self.empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_sub.setFrameShape(QFrame.Shape.NoFrame)
        self.empty_sub.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        esf = QFont()
        esf.setPixelSize(font(12))
        esf.setWeight(QFont.Weight.Medium)
        self.empty_sub.setFont(esf)
        self.empty_sub.setStyleSheet(
            f"color: {_SLATE_500}; background: transparent;"
            f" border: none; outline: none;"
        )
        empty_layout.addWidget(self.empty_sub)

        self.empty_widget.setVisible(False)
        root.addWidget(self.empty_widget)

    # ── Filter chiplari render ─────────────────
    # Display chiplari — UI label (chip_key) + Frappe order_type uchun map.
    # "Dastavka" va "Dastavka Saboy" server tomondan bir xil "Delivery"ga
    # tushgani uchun bitta birlashgan chip qilamiz.
    _CHIP_DEFS = [
        ("Shu yerda", "Shu yerda", "Dine In"),
        ("Saboy", "Saboy", "Take Away"),
        ("Dastavka", "Dastavka", "Delivery"),  # Dastavka + Dastavka Saboy birga
    ]

    def _render_chips(self, counts: dict):
        while self._chips_row.count() > 1:
            item = self._chips_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._chip_buttons.clear()

        all_count = counts.get("all", 0)
        self._add_chip("", "Hammasi", all_count)
        for chip_key, label, frappe_ot in self._CHIP_DEFS:
            cnt = counts.get(frappe_ot, 0)
            self._add_chip(chip_key, label, cnt)

    def _add_chip(self, chip_key: str, label: str, count: int):
        """chip_key — UI label ("Dastavka", "Dastavka Saboy") UNIQUE identifier.

        Server uchun ORDER_TYPE_MAP orqali Frappe order_type'ga aylantiriladi.
        """
        text = f"{label}   {count}" if count > 0 else label
        btn = QPushButton(text)
        btn.setFixedHeight(s(36))
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setChecked(self.active_order_type == chip_key)
        btn.setStyleSheet(self._chip_style(
            active=(self.active_order_type == chip_key),
            has_items=(count > 0),
        ))
        btn.clicked.connect(lambda checked, ot=chip_key: self._select_chip(ot))
        self._chips_row.insertWidget(self._chips_row.count() - 1, btn)
        self._chip_buttons[chip_key] = btn

    @staticmethod
    def _chip_style(active: bool, has_items: bool) -> str:
        r = s(18)
        fs = font(12)
        if active:
            return f"""
                QPushButton {{
                    background: {_SLATE_900};
                    color: white;
                    font-weight: 700;
                    font-size: {fs}px;
                    letter-spacing: 0.5px;
                    padding: 0 {s(18)}px;
                    border-radius: {r}px;
                    border: 1px solid {_SLATE_900};
                }}
                QPushButton:hover {{ background: #1e293b; }}
            """
        if has_items:
            return f"""
                QPushButton {{
                    background: white;
                    color: {_AMBER};
                    font-weight: 700;
                    font-size: {fs}px;
                    letter-spacing: 0.5px;
                    padding: 0 {s(18)}px;
                    border-radius: {r}px;
                    border: 1px solid #fdba74;
                }}
                QPushButton:hover {{
                    background: #fff7ed;
                    border-color: #f97316;
                }}
            """
        return f"""
            QPushButton {{
                background: white;
                color: {_SLATE_500};
                font-weight: 600;
                font-size: {fs}px;
                letter-spacing: 0.5px;
                padding: 0 {s(18)}px;
                border-radius: {r}px;
                border: 1px solid {_SLATE_200};
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                border-color: {_SLATE_300};
                color: {_SLATE_700};
            }}
        """

    def _select_chip(self, chip_key: str):
        """chip_key — UI label ("Dastavka", "Dastavka Saboy", "") yoki bo'sh."""
        self.active_order_type = chip_key
        self.load_pending()

    # ── Role boshqaruvi ───────────────────────
    def set_role_and_name(self, role: str, name: str, user: str = ""):
        self._role = role or "Kassir"
        self._mine_name = name or ""
        self._mine_user = user or ""

    # ── Yuklash ───────────────────────────────
    def load_pending(self):
        only_mine = (self._role == "Ofitsant")
        # UI label → Frappe order_type (server filter uchun).
        # "" (Hammasi) → "" (filter yo'q).
        # "Dastavka" → "Delivery", "Dastavka Saboy" → "Delivery" (server bir xil
        # qaytaradi, lekin chip darajasida ajraladi).
        frappe_ot = ORDER_TYPE_MAP.get(self.active_order_type, self.active_order_type)
        self.worker = FetchPendingWorker(
            self.api,
            order_type=frappe_ot,
            only_mine=only_mine,
            mine_name=self._mine_name,
        )
        self.worker.result_ready.connect(self._on_loaded)
        self.worker.start()

    def refresh_count(self):
        only_mine = (self._role == "Ofitsant")
        self._count_worker = FetchPendingCountWorker(
            self.api, only_mine=only_mine, mine_name=self._mine_name,
        )
        self._count_worker.result_ready.connect(self._on_count_only)
        self._count_worker.start()

    def _on_count_only(self, success: bool, counts: dict):
        if success:
            self.count_changed.emit(int(counts.get("all", 0)))

    def _on_loaded(self, success: bool, rows: list, counts: dict):
        if not success:
            self.table.setRowCount(0)
            self.empty_title.setText("Yuklashda xatolik")
            self.empty_sub.setText("Tarmoq ulanishini tekshiring va qaytadan urinib ko'ring")
            self.empty_widget.setVisible(True)
            self.table.setVisible(False)
            return

        self._render_chips(counts)
        self.count_badge.set_count(int(counts.get("all", 0)))
        self.count_changed.emit(int(counts.get("all", 0)))

        self.table.setRowCount(0)
        if not rows:
            self.empty_title.setText("To'lov kutayotgan buyurtma yo'q")
            self.empty_sub.setText("Yangi buyurtma kelishi bilan bu yerda paydo bo'ladi")
            self.empty_widget.setVisible(True)
            self.table.setVisible(False)
            return

        self.empty_widget.setVisible(False)
        self.table.setVisible(True)

        is_waiter = (self._role == "Ofitsant")

        for i, r in enumerate(rows):
            self.table.insertRow(i)
            self.table.setRowHeight(i, s(68))

            # Vaqt
            posting_time = str(r.get("posting_time") or "")[:8]
            time_item = QTableWidgetItem(posting_time)
            time_item.setForeground(QBrush(QColor(_SLATE_500)))
            self.table.setItem(i, 0, time_item)

            # #N / Stol
            if r.get("restaurant_table"):
                room = r.get("room", "")
                table_disp = f"{room} / {r['restaurant_table']}" if room else str(r["restaurant_table"])
            elif r.get("custom_ticket_number"):
                table_disp = f"№{r['custom_ticket_number']}"
            else:
                table_disp = "—"
            ts_item = QTableWidgetItem(table_disp)
            ts_font = QFont()
            ts_font.setPixelSize(font(13))
            ts_font.setWeight(QFont.Weight.Bold)
            ts_item.setFont(ts_font)
            ts_item.setForeground(QBrush(QColor(_SLATE_900)))
            self.table.setItem(i, 1, ts_item)

            # Tur
            ot = r.get("order_type") or ""
            ot_uz = _ORDER_TYPE_LABEL.get(ot, ot)
            type_item = QTableWidgetItem(ot_uz)
            type_item.setForeground(QBrush(QColor(_SLATE_700)))
            self.table.setItem(i, 2, type_item)

            # Mijoz
            cust_item = QTableWidgetItem(str(r.get("customer", "")))
            cust_item.setForeground(QBrush(QColor(_SLATE_900)))
            self.table.setItem(i, 3, cust_item)

            # Ofitsant/Kassir
            casher = str(r.get("custom_active_cashier", "") or "")
            role_tag = str(r.get("custom_active_cashier_role", "") or "")
            if role_tag and casher:
                casher_disp = f"{casher} · {role_tag}"
            else:
                casher_disp = casher or "—"
            who_item = QTableWidgetItem(casher_disp)
            who_item.setForeground(QBrush(QColor(_SLATE_500)))
            self.table.setItem(i, 4, who_item)

            # Summa
            grand = float(r.get("grand_total") or r.get("rounded_total") or 0)
            amt = QTableWidgetItem(f"{grand:,.0f} UZS".replace(",", " "))
            amt.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
            )
            amt_font = QFont()
            amt_font.setPixelSize(font(13))
            amt_font.setWeight(QFont.Weight.Bold)
            amt.setFont(amt_font)
            amt.setForeground(QBrush(QColor(_SLATE_900)))
            self.table.setItem(i, 5, amt)

            # Amallar (faqat kassir uchun)
            if is_waiter:
                self.table.setItem(i, 6, QTableWidgetItem(""))
            else:
                cell = QWidget()
                cell.setStyleSheet("background: transparent;")
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(s(6), s(4), s(10), s(4))
                cell_layout.setSpacing(s(6))

                inv_name = r.get("name", "")

                pay_btn = QPushButton("To'lov")
                pay_btn.setFixedHeight(s(34))
                pay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                pay_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_EMERALD_600};
                        color: white;
                        padding: 0 {s(16)}px;
                        font-weight: 700;
                        font-size: {font(12)}px;
                        letter-spacing: 0.5px;
                        border-radius: {s(7)}px;
                        border: 1px solid {_EMERALD_600};
                    }}
                    QPushButton:hover {{
                        background: {_EMERALD_700};
                        border-color: {_EMERALD_700};
                    }}
                    QPushButton:pressed {{ background: #065f46; }}
                """)
                pay_btn.clicked.connect(lambda checked, n=inv_name: self._on_pay(n))

                cancel_btn = QPushButton("✕")
                cancel_btn.setFixedSize(s(34), s(34))
                cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                cancel_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: white;
                        color: {_RED_700};
                        font-weight: 700;
                        font-size: {font(13)}px;
                        border-radius: {s(7)}px;
                        border: 1px solid {_RED_200};
                    }}
                    QPushButton:hover {{
                        background: {_RED_50};
                        border-color: #fca5a5;
                    }}
                    QPushButton:pressed {{ background: #fee2e2; }}
                """)
                cancel_btn.clicked.connect(lambda checked, n=inv_name: self._on_cancel(n))

                cell_layout.addWidget(pay_btn)
                cell_layout.addWidget(cancel_btn)
                cell_layout.addStretch()
                self.table.setCellWidget(i, 6, cell)

    # ── Pay action ────────────────────────────
    def _on_pay(self, invoice: str):
        if not invoice:
            return
        self._pay_worker = FetchOrderDetailWorker(self.api, invoice)
        self._pay_worker.result_ready.connect(self._on_pay_detail)
        self._pay_worker.start()

    def _on_pay_detail(self, success: bool, detail: dict):
        if not success or not detail:
            InfoDialog(
                self, "Xatolik",
                "Buyurtma ma'lumotlarini olib bo'lmadi",
                kind="error",
            ).exec()
            return
        self.pay_requested.emit(detail)

    # ── Cancel action ─────────────────────────
    def _on_cancel(self, invoice: str):
        if not invoice:
            return

        if self._role == "Ofitsant":
            return

        from ui.components.history_window import CancelReasonDialog
        dlg = CancelReasonDialog(self, invoice)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        reason = dlg.get_reason()
        if not reason:
            return

        self._cancel_worker = CancelPendingWorker(
            self.api, invoice, reason,
            cashier_user=self._mine_user,
            active_cashier=self._mine_name,
            active_cashier_role=self._role,
        )
        self._cancel_worker.result_ready.connect(self._on_cancel_done)
        self._cancel_worker.start()

    def _on_cancel_done(self, success: bool, message: str):
        if success:
            InfoDialog(self, "Bajarildi", message, kind="success").exec()
            self.load_pending()
        else:
            InfoDialog(self, "Xatolik", message, kind="info").exec()
