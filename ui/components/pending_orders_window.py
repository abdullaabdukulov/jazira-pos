"""PendingOrdersWindow — to'lov kutilayotgan Draft POS Invoicelar paneli.

TZ 4.2.4 ga muvofiq:
- Filter chiplari (order_type bo'yicha + countlar)
- Jadval: Vaqt, #N/Stol, Tur, Mijoz, Ofitsant, Summa, Amallar
- Amallar: "💰 To'lov" (CheckoutWindow), "✕ Bekor" (sabab bilan)
- Ofitsant rolida: faqat o'zinikini ko'radi, amallar yashirin
- Real-time refresh (Phase 2)
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QScroller, QScrollerProperties, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from core.api import FrappeAPI
from core.config import load_config
from core.constants import ORDER_TYPES, ORDER_TYPE_MAP
from core.logger import get_logger
from database.models import db
from ui.components.dialogs import InfoDialog
from ui.scale import s, font

logger = get_logger(__name__)


# Frappe order_type ↔ UI Uzbek nomi (display uchun teskari xarita)
_ORDER_TYPE_LABEL = {
    "Dine In": "Shu yerda",
    "Take Away": "Saboy",
    "Delivery": "Dastavka",
}


def _touch_scroll(table):
    scroller = QScroller.scroller(table.viewport())
    scroller.grabGesture(table.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
    scroller.setScrollerProperties(props)


# ═══════════════════════════════════════════════════════════════════════════
#  Workers
# ═══════════════════════════════════════════════════════════════════════════

class FetchPendingWorker(QThread):
    """getPendingOrders va getPendingOrderCounts ni parallel chaqiradi."""
    result_ready = pyqtSignal(bool, list, dict)  # success, rows, counts

    def __init__(self, api: FrappeAPI, order_type: str = "",
                 only_mine: bool = False, mine_name: str = ""):
        super().__init__()
        self.api = api
        self.order_type = order_type  # Frappe nomi ("Dine In", "" = barchasi)
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


class CancelPendingWorker(QThread):
    """cancelPendingOrder ni chaqiradi."""
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, invoice: str, reason: str):
        super().__init__()
        self.api = api
        self.invoice = invoice
        self.reason = reason

    def run(self):
        try:
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.cancelPendingOrder",
                {"invoice": self.invoice, "reason": self.reason},
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
    """getPendingOrderDetail — to'lov uchun items va ma'lumotlar."""
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
#  CancelReasonDialog
# ═══════════════════════════════════════════════════════════════════════════

class CancelReasonDialog(QFrame):
    """Sodda inline sabab dialog (modal QDialog emas, QFrame overlay)."""
    pass  # ishlatilmaydi — QInputDialog kerak emas, oddiy InfoDialog + input ishlatamiz


# ═══════════════════════════════════════════════════════════════════════════
#  Asosiy panel
# ═══════════════════════════════════════════════════════════════════════════

class PendingOrdersWindow(QWidget):
    """Inline panel — main_window'da embed bo'ladi, show/hide toggle."""

    # MainWindow ushlab oladi → CheckoutWindow ochadi
    pay_requested = pyqtSignal(dict)   # order detail dict
    count_changed = pyqtSignal(int)    # top-bar tugmasini yangilash uchun

    def __init__(self, api: FrappeAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.active_order_type = ""    # "" = hammasi, "Dine In", "Take Away", ...
        self._role = "Kassir"
        self._mine_name = ""           # active_cashier.full_name
        self._chip_buttons: dict[str, QPushButton] = {}
        self._init_ui()

    # ──────────────────────────────────────────
    def _init_ui(self):
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(16), s(12), s(16), s(12))
        layout.setSpacing(s(10))

        # ── Header ─────────────────────────────
        hdr_row = QHBoxLayout()
        title = QLabel("To'lov kutilmoqda")
        title.setStyleSheet(f"font-size: {font(18)}px; font-weight: 800; color: #1e293b;")
        hdr_row.addWidget(title)

        hint = QLabel("(2× bosing — tafsilot, '💰 To'lov' — yakunlash)")
        hint.setStyleSheet(f"font-size: {font(11)}px; color: #94a3b8; font-style: italic;")
        hdr_row.addWidget(hint)
        hdr_row.addStretch()

        refresh_btn = QPushButton("⟳  Yangilash")
        refresh_btn.setFixedHeight(s(40))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                padding: 0 {s(14)}px; background: #f1f5f9; color: #475569;
                font-weight: 600; font-size: {font(13)}px;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        refresh_btn.clicked.connect(self.load_pending)
        hdr_row.addWidget(refresh_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(40), s(40))
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: #fee2e2; color: #b91c1c;
                font-weight: 700; font-size: {font(14)}px;
                border-radius: {s(8)}px; border: none; }}
            QPushButton:hover {{ background: #fecaca; }}
        """)
        close_btn.clicked.connect(self.hide)
        hdr_row.addWidget(close_btn)
        layout.addLayout(hdr_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #e2e8f0; max-height: 1px;")
        layout.addWidget(sep)

        # ── Filter chiplari ────────────────────
        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(s(6))
        self._chips_row.addStretch()
        chips_widget = QWidget()
        chips_widget.setStyleSheet("background: transparent;")
        chips_widget.setLayout(self._chips_row)
        layout.addWidget(chips_widget)

        self._render_chips({})  # boshlang'ich (bo'sh count)

        # ── Jadval ────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Vaqt", "#N / Stol", "Tur", "Mijoz", "Ofitsant", "Summa", "Amallar"
        ])
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
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, s(110))
        self.table.setColumnWidth(6, s(180))

        layout.addWidget(self.table)
        _touch_scroll(self.table)

        # ── Empty state ──────────────────────
        self.empty_label = QLabel("✅  To'lov kutayotgan zakaz yo'q")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            font-size: {font(14)}px; font-weight: 600; color: #94a3b8;
            padding: {s(30)}px;
        """)
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

    # ── Filter chiplari render ─────────────────
    def _render_chips(self, counts: dict):
        # Eskilarni tozalash (stretch dan tashqari)
        while self._chips_row.count() > 1:
            item = self._chips_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._chip_buttons.clear()

        # Hammasi chip
        all_count = counts.get("all", 0)
        self._add_chip("", "Hammasi", all_count)
        # Order types
        for ot_label in ORDER_TYPES:
            frappe_ot = ORDER_TYPE_MAP.get(ot_label, ot_label)
            cnt = counts.get(frappe_ot, 0)
            # Faqat 1+ marta sodir bo'ladiganlarni doim ko'rsatamiz
            self._add_chip(frappe_ot, ot_label, cnt)

    def _add_chip(self, frappe_order_type: str, label: str, count: int):
        btn = QPushButton(f"{label}  {count}" if count > 0 else label)
        btn.setFixedHeight(s(36))
        btn.setCheckable(True)
        btn.setChecked(self.active_order_type == frappe_order_type)
        btn.setStyleSheet(self._chip_style(
            active=(self.active_order_type == frappe_order_type),
            has_items=(count > 0),
        ))
        btn.clicked.connect(lambda checked, ot=frappe_order_type: self._select_chip(ot))
        # stretch dan oldin qo'shamiz
        self._chips_row.insertWidget(self._chips_row.count() - 1, btn)
        self._chip_buttons[frappe_order_type] = btn

    @staticmethod
    def _chip_style(active: bool, has_items: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: #1d4ed8; color: white;
                    font-weight: 800; font-size: {font(12)}px;
                    padding: 0 {s(16)}px; border-radius: {s(18)}px;
                    border: none;
                }}
            """
        bg = "#fff7ed" if has_items else "white"
        color = "#c2410c" if has_items else "#64748b"
        border = "#fdba74" if has_items else "#e2e8f0"
        return f"""
            QPushButton {{
                background: {bg}; color: {color};
                font-weight: 700; font-size: {font(12)}px;
                padding: 0 {s(16)}px; border-radius: {s(18)}px;
                border: 1.5px solid {border};
            }}
            QPushButton:hover {{
                background: #eff6ff; color: #1d4ed8; border-color: #93c5fd;
            }}
        """

    def _select_chip(self, frappe_order_type: str):
        self.active_order_type = frappe_order_type
        self.load_pending()

    # ── Role boshqaruvi ───────────────────────
    def set_role_and_name(self, role: str, name: str):
        """Ofitsant rolida only_mine=True, action tugmalari yashirin."""
        self._role = role or "Kassir"
        self._mine_name = name or ""

    # ── Yuklash ───────────────────────────────
    def load_pending(self):
        only_mine = (self._role == "Ofitsant")
        self.worker = FetchPendingWorker(
            self.api,
            order_type=self.active_order_type,
            only_mine=only_mine,
            mine_name=self._mine_name,
        )
        self.worker.result_ready.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, success: bool, rows: list, counts: dict):
        if not success:
            self.table.setRowCount(0)
            self.empty_label.setText("⚠  Yuklashda xato — tarmoqni tekshiring")
            self.empty_label.setVisible(True)
            self.table.setVisible(False)
            return

        # Chiplari yangilash
        self._render_chips(counts)

        # Count o'zgarganini bildirish
        self.count_changed.emit(int(counts.get("all", 0)))

        # Jadvalni to'ldirish
        self.table.setRowCount(0)
        if not rows:
            self.empty_label.setText("✅  To'lov kutayotgan zakaz yo'q")
            self.empty_label.setVisible(True)
            self.table.setVisible(False)
            return

        self.empty_label.setVisible(False)
        self.table.setVisible(True)

        is_waiter = (self._role == "Ofitsant")

        for i, r in enumerate(rows):
            self.table.insertRow(i)
            self.table.setRowHeight(i, s(48))

            # Vaqt
            posting_time = str(r.get("posting_time") or "")[:8]
            self.table.setItem(i, 0, QTableWidgetItem(posting_time))

            # #N / Stol
            if r.get("restaurant_table"):
                room = r.get("room", "")
                table_disp = f"🪑 {room} / {r['restaurant_table']}" if room else f"🪑 {r['restaurant_table']}"
            elif r.get("custom_ticket_number"):
                table_disp = f"#{r['custom_ticket_number']}"
            else:
                table_disp = "—"
            self.table.setItem(i, 1, QTableWidgetItem(table_disp))

            # Tur (UI label)
            ot = r.get("order_type") or ""
            ot_uz = _ORDER_TYPE_LABEL.get(ot, ot)
            self.table.setItem(i, 2, QTableWidgetItem(ot_uz))

            # Mijoz
            self.table.setItem(i, 3, QTableWidgetItem(str(r.get("customer", ""))))

            # Ofitsant/Kassir
            casher = str(r.get("custom_active_cashier", "") or "")
            role_tag = str(r.get("custom_active_cashier_role", "") or "")
            if role_tag and casher:
                casher_disp = f"{casher} · {role_tag}"
            else:
                casher_disp = casher
            self.table.setItem(i, 4, QTableWidgetItem(casher_disp))

            # Summa
            grand = float(r.get("grand_total") or r.get("rounded_total") or 0)
            amt = QTableWidgetItem(f"{grand:,.0f} UZS".replace(",", " "))
            amt.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            self.table.setItem(i, 5, amt)

            # Amallar (faqat kassir uchun)
            if is_waiter:
                self.table.setItem(i, 6, QTableWidgetItem(""))
            else:
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(s(4), s(4), s(4), s(4))
                cell_layout.setSpacing(s(6))

                pay_btn = QPushButton("💰 To'lov")
                pay_btn.setFixedHeight(s(36))
                pay_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #16a34a; color: white; padding: 0 {s(10)}px;
                        font-weight: 700; font-size: {font(11)}px;
                        border-radius: {s(6)}px; border: none;
                    }}
                    QPushButton:hover {{ background: #15803d; }}
                """)
                inv_name = r.get("name", "")
                pay_btn.clicked.connect(lambda checked, n=inv_name: self._on_pay(n))

                cancel_btn = QPushButton("✕")
                cancel_btn.setFixedSize(s(36), s(36))
                cancel_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #fee2e2; color: #b91c1c;
                        font-weight: 700; font-size: {font(12)}px;
                        border-radius: {s(6)}px; border: none;
                    }}
                    QPushButton:hover {{ background: #fecaca; }}
                """)
                cancel_btn.clicked.connect(lambda checked, n=inv_name: self._on_cancel(n))

                cell_layout.addWidget(pay_btn)
                cell_layout.addWidget(cancel_btn)
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
            InfoDialog(self, "Xatolik", "Buyurtma ma'lumotlarini olib bo'lmadi", kind="error").exec()
            return
        # MainWindow CheckoutWindow ni mavjud invoice bilan ochadi
        self.pay_requested.emit(detail)

    # ── Cancel action ─────────────────────────
    def _on_cancel(self, invoice: str):
        if not invoice:
            return

        # Sabab dialog
        from PyQt6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(
            self, "Bekor qilish sababi",
            f"{invoice} buyurtmasini bekor qilish sababi:",
            QLineEdit.EchoMode.Normal, "",
        )
        if not ok or not reason.strip():
            return

        self._cancel_worker = CancelPendingWorker(self.api, invoice, reason.strip())
        self._cancel_worker.result_ready.connect(self._on_cancel_done)
        self._cancel_worker.start()

    def _on_cancel_done(self, success: bool, message: str):
        if success:
            InfoDialog(self, "Bajarildi", message, kind="success").exec()
            self.load_pending()
        else:
            InfoDialog(self, "Xatolik", message, kind="error").exec()
