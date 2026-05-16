"""TablePickerDialog — Stol rejimida URY Table dan tanlash.

TZ 4.1.6 ga muvofiq:
- Layout x/y asosida visual joylashuv (yoki fallback grid)
- Ko'p xona bo'lsa yuqorida tabs
- Band stollar qizil/o'chgan
- Qo'lda bo'shatish tugmasi (4.1.4 — freeTable API)
- SocketIO orqali real-time refresh (Phase 2 da qo'shiladi)
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QScrollArea, QGridLayout, QSizePolicy,
    QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush

from core.api import FrappeAPI
from core.logger import get_logger
from database.models import Room, RestaurantTable, db
from ui.components.dialogs import InfoDialog, ConfirmDialog
from ui.scale import s, font

logger = get_logger(__name__)


# ── Stol qutisi rangları ───────────────────────────────
_FREE_BG = "#f0fdf4"        # och yashil
_FREE_BORDER = "#86efac"    # yashil
_FREE_TEXT = "#15803d"      # to'q yashil

_OCC_BG = "#fef2f2"         # och qizil
_OCC_BORDER = "#fca5a5"     # qizil
_OCC_TEXT = "#b91c1c"       # to'q qizil

_SELECTED_BG = "#dbeafe"    # och ko'k
_SELECTED_BORDER = "#3b82f6"
_SELECTED_TEXT = "#1e40af"


class FreeTableWorker(QThread):
    """Stolni qo'lda bo'shatish workeri (freeTable API)."""
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, table: str, reason: str):
        super().__init__()
        self.api = api
        self.table = table
        self.reason = reason

    def run(self):
        try:
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.freeTable",
                {"table": self.table, "reason": self.reason},
            )
            if ok and isinstance(resp, dict) and resp.get("status") == "ok":
                self.result_ready.emit(True, "Stol bo'shatildi")
            else:
                self.result_ready.emit(False, str(resp))
        except Exception as e:
            self.result_ready.emit(False, str(e))
        finally:
            if not db.is_closed():
                db.close()


class TableButton(QPushButton):
    """Stol qutisi — tanlash uchun, band/bo'sh holat farqli."""

    def __init__(self, table_doc: RestaurantTable, parent=None):
        super().__init__(parent)
        self.table_doc = table_doc
        self._selected = False
        self._build()

    def _build(self):
        seats_txt = f"{self.table_doc.no_of_seats}o'rin" if self.table_doc.no_of_seats else ""
        # Label: "5\n4o'rin"
        self.setText(f"{self.table_doc.name}\n{seats_txt}")
        self.setCheckable(True)
        self.setMinimumSize(s(80), s(70))
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            bg, border, color = _SELECTED_BG, _SELECTED_BORDER, _SELECTED_TEXT
        elif self.table_doc.occupied:
            bg, border, color = _OCC_BG, _OCC_BORDER, _OCC_TEXT
        else:
            bg, border, color = _FREE_BG, _FREE_BORDER, _FREE_TEXT

        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {color};
                border: 2px solid {border};
                border-radius: {s(10)}px;
                font-size: {font(13)}px;
                font-weight: 700;
                padding: {s(4)}px;
            }}
            QPushButton:hover {{
                border-width: 3px;
            }}
            QPushButton:pressed {{
                background: {border};
                color: white;
            }}
        """)

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style()

    def update_doc(self, new_doc: RestaurantTable):
        self.table_doc = new_doc
        self._build()


class TablePickerDialog(QDialog):
    """Stol tanlash dialogi.

    Result: self.selected_table -> dict yoki None
        {"name": "T-001", "room": "Zal 1", "seats": 4, "is_take_away": 0}
    """
    table_freed_signal = pyqtSignal(str)  # qo'lda bo'shatish bo'lganda

    def __init__(self, parent, api: FrappeAPI, current_table: str = ""):
        super().__init__(parent)
        self.api = api
        self.selected_table: dict | None = None
        self._current_table = current_table
        self._room_buttons: dict[str, QPushButton] = {}
        self._table_buttons: dict[str, TableButton] = {}
        self._active_room: str = ""
        self._init_ui()
        self._load_data()

    # ──────────────────────────────────────────────────
    def _init_ui(self):
        self.setWindowTitle("Stol tanlang")
        self.setMinimumSize(s(900), s(640))
        self.resize(s(1100), s(720))
        self.setModal(True)
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(18), s(14), s(18), s(14))
        root.setSpacing(s(10))

        # ── Header ───────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Stol tanlang")
        title.setStyleSheet(f"font-size: {font(20)}px; font-weight: 800; color: #0f172a;")
        hdr.addWidget(title)
        hdr.addStretch()

        # Refresh tugma
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(s(40), s(40))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: #f1f5f9; color: #475569;
                font-size: {font(16)}px; font-weight: 700;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        refresh_btn.clicked.connect(self._load_data)
        hdr.addWidget(refresh_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(40), s(40))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: #fee2e2; color: #b91c1c;
                font-size: {font(16)}px; font-weight: 700;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #fecaca; }}
        """)
        close_btn.clicked.connect(self.reject)
        hdr.addWidget(close_btn)
        root.addLayout(hdr)

        # ── Room tabs ────────────────────────────
        self._rooms_row = QHBoxLayout()
        self._rooms_row.setSpacing(s(6))
        self._rooms_row.addStretch()
        rooms_widget = QWidget()
        rooms_widget.setLayout(self._rooms_row)
        rooms_widget.setStyleSheet("background: transparent;")
        root.addWidget(rooms_widget)

        # ── Stol canvas (scrollable) ─────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: #f8fafc; border: 1px solid #e2e8f0;
                border-radius: {s(12)}px;
            }}
        """)
        self._canvas = QWidget()
        self._canvas.setStyleSheet("background: transparent;")
        scroll.setWidget(self._canvas)
        root.addWidget(scroll, stretch=1)

        # ── Selected info + buttons ─────────────
        bottom = QHBoxLayout()
        self._info_label = QLabel("Stol tanlanmagan")
        self._info_label.setStyleSheet(
            f"font-size: {font(15)}px; font-weight: 700; color: #64748b;"
        )
        bottom.addWidget(self._info_label)
        bottom.addStretch()

        # Qo'lda bo'shatish — band stol tanlanganda paydo bo'ladi
        self._free_btn = QPushButton("🔓 Stolni bo'shatish")
        self._free_btn.setFixedHeight(s(48))
        self._free_btn.setStyleSheet(f"""
            QPushButton {{
                background: #fff7ed; color: #c2410c;
                font-weight: 700; font-size: {font(13)}px;
                padding: 0 {s(16)}px; border-radius: {s(10)}px;
                border: 1.5px solid #fdba74;
            }}
            QPushButton:hover {{ background: #ffedd5; }}
        """)
        self._free_btn.clicked.connect(self._on_free_table)
        self._free_btn.setVisible(False)
        bottom.addWidget(self._free_btn)

        cancel_btn = QPushButton("Bekor")
        cancel_btn.setFixedHeight(s(48))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: #f1f5f9; color: #475569;
                font-weight: 700; font-size: {font(13)}px;
                padding: 0 {s(20)}px; border-radius: {s(10)}px;
                border: none;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        self._select_btn = QPushButton("✓  Tanlash")
        self._select_btn.setFixedHeight(s(48))
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet(f"""
            QPushButton {{
                background: #1d4ed8; color: white;
                font-weight: 800; font-size: {font(14)}px;
                padding: 0 {s(28)}px; border-radius: {s(10)}px;
                border: none;
            }}
            QPushButton:hover {{ background: #1e40af; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #94a3b8; }}
        """)
        self._select_btn.clicked.connect(self._on_select)
        bottom.addWidget(self._select_btn)

        root.addLayout(bottom)

    # ──────────────────────────────────────────────────
    def _load_data(self):
        """Lokal DB dan xona va stollarni o'qish va UI ni yangilash."""
        try:
            db.connect(reuse_if_open=True)
            rooms = list(Room.select().order_by(Room.name))
            tables = list(RestaurantTable.select().order_by(
                RestaurantTable.restaurant_room, RestaurantTable.name
            ))

            if not tables:
                self._show_empty_state()
                return

            self._render_room_tabs(rooms, tables)
            # Birinchi xonani avto tanlash (yoki "Hammasi")
            if rooms:
                # Default — birinchi mavjud xona
                first_room = next(
                    (r.name for r in rooms if any(t.restaurant_room == r.name for t in tables)),
                    rooms[0].name,
                )
                self._select_room(first_room, tables)
            else:
                # Xonalar yo'q — barcha stollar bitta canvasda
                self._select_room("", tables)

        except Exception as e:
            logger.error("Stol picker yuklashda xato: %s", e)
            InfoDialog(self, "Xatolik", f"Stollarni yuklab bo'lmadi: {e}", kind="error").exec()

    def _show_empty_state(self):
        # Canvasni tozalash
        if self._canvas.layout() is not None:
            self._clear_layout(self._canvas.layout())
        v = QVBoxLayout(self._canvas)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg = QLabel("Stollar topilmadi.\nERPNext da URY Table yarating va sinxronlang.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"font-size: {font(15)}px; color: #94a3b8; padding: {s(40)}px;")
        v.addWidget(msg)

    def _render_room_tabs(self, rooms, tables):
        # Eski tugmalarni tozalash
        while self._rooms_row.count() > 0:
            item = self._rooms_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._room_buttons.clear()

        # "Hammasi" tab — birlashtirilgan ko'rinish (faqat 1+ xona bo'lsa)
        if len(rooms) > 1:
            self._add_room_button("", "Hammasi", len(tables), tables)

        # Har bir xona
        for r in rooms:
            count = sum(1 for t in tables if t.restaurant_room == r.name)
            if count > 0:
                self._add_room_button(r.name, r.name, count, tables)

        self._rooms_row.addStretch()

    def _add_room_button(self, room_key: str, label: str, count: int, tables):
        btn = QPushButton(f"{label}  ({count})")
        btn.setFixedHeight(s(40))
        btn.setCheckable(True)
        btn.setStyleSheet(self._room_btn_style(False))
        btn.clicked.connect(lambda: self._select_room(room_key, tables))
        self._rooms_row.insertWidget(self._rooms_row.count() - 1, btn)
        self._room_buttons[room_key] = btn

    @staticmethod
    def _room_btn_style(active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: #1d4ed8; color: white;
                    font-weight: 800; font-size: {font(13)}px;
                    padding: 0 {s(18)}px; border-radius: {s(10)}px;
                    border: none;
                }}
            """
        return f"""
            QPushButton {{
                background: white; color: #475569;
                font-weight: 700; font-size: {font(13)}px;
                padding: 0 {s(18)}px; border-radius: {s(10)}px;
                border: 1.5px solid #e2e8f0;
            }}
            QPushButton:hover {{
                background: #eff6ff; color: #1d4ed8; border-color: #93c5fd;
            }}
        """

    def _select_room(self, room: str, tables):
        self._active_room = room
        # Tab visual aktiv holat
        for k, btn in self._room_buttons.items():
            btn.setChecked(k == room)
            btn.setStyleSheet(self._room_btn_style(k == room))

        # Canvasni tiklash
        filtered = tables if not room else [t for t in tables if t.restaurant_room == room]
        self._render_tables(filtered)

    def _render_tables(self, tables: list):
        # Eski canvasni tozalash
        if self._canvas.layout() is not None:
            self._clear_layout(self._canvas.layout())
            QWidget().setLayout(self._canvas.layout())  # detach
        self._table_buttons.clear()

        # Layout x/y mavjudligini tekshirish
        has_layout = any(
            (t.layout_x or t.layout_y or t.layout_width or t.layout_height) for t in tables
        )

        if has_layout:
            self._render_absolute_layout(tables)
        else:
            self._render_grid_layout(tables)

    def _render_absolute_layout(self, tables):
        """layout_x/y asosida absolute positioning."""
        # QGridLayout dan foydalanmasdan, QWidget ichida absolute moveTo
        from PyQt6.QtWidgets import QFrame as _F
        canvas = QWidget(self._canvas)
        # Canvas hajmini hisoblash
        max_x = max((t.layout_x + (t.layout_width or 100) for t in tables), default=800)
        max_y = max((t.layout_y + (t.layout_height or 80) for t in tables), default=600)
        canvas.setMinimumSize(s(int(max_x) + 40), s(int(max_y) + 40))

        for t in tables:
            btn = TableButton(t)
            btn.setParent(canvas)
            w = s(int(t.layout_width)) if t.layout_width else s(100)
            h = s(int(t.layout_height)) if t.layout_height else s(80)
            btn.setFixedSize(w, h)
            btn.move(s(int(t.layout_x or 0)), s(int(t.layout_y or 0)))
            btn.clicked.connect(lambda checked, b=btn: self._on_table_clicked(b))
            self._table_buttons[t.name] = btn
            if t.name == self._current_table:
                btn.set_selected(True)
                self._update_selection_info(t)

        # Canvasga layout qo'shish (parent layout uchun)
        wrap = QVBoxLayout(self._canvas)
        wrap.setContentsMargins(s(8), s(8), s(8), s(8))
        wrap.addWidget(canvas)
        wrap.addStretch()

    def _render_grid_layout(self, tables):
        """Layout yo'q bo'lsa — 5 ustunli grid (fallback)."""
        grid = QGridLayout(self._canvas)
        grid.setSpacing(s(10))
        grid.setContentsMargins(s(12), s(12), s(12), s(12))
        cols = 5
        for i, t in enumerate(tables):
            btn = TableButton(t)
            btn.setFixedSize(s(120), s(90))
            btn.clicked.connect(lambda checked, b=btn: self._on_table_clicked(b))
            self._table_buttons[t.name] = btn
            grid.addWidget(btn, i // cols, i % cols)
            if t.name == self._current_table:
                btn.set_selected(True)
                self._update_selection_info(t)
        # Pastga bo'sh joy
        grid.setRowStretch(grid.rowCount(), 1)

    # ──────────────────────────────────────────────────
    def _on_table_clicked(self, btn: TableButton):
        # Boshqalarini deselect
        for name, b in self._table_buttons.items():
            b.set_selected(b is btn)
        self._update_selection_info(btn.table_doc)

    def _update_selection_info(self, t: RestaurantTable):
        room_label = f"{t.restaurant_room} / " if t.restaurant_room else ""
        seats = f"({t.no_of_seats}o'rin)" if t.no_of_seats else ""
        status = " — BAND" if t.occupied else ""
        self._info_label.setText(f"Tanlangan: {room_label}{t.name} {seats}{status}")
        self._info_label.setStyleSheet(
            f"font-size: {font(15)}px; font-weight: 700;"
            f" color: {'#b91c1c' if t.occupied else '#0f172a'};"
        )
        # Faqat bo'sh stol tanlash mumkin (lekin band stolni ko'rsatishga ruxsat)
        self._select_btn.setEnabled(not t.occupied)
        self._free_btn.setVisible(bool(t.occupied))
        self._selected_doc = t

    def _on_select(self):
        t: RestaurantTable = getattr(self, "_selected_doc", None)
        if not t:
            return
        if t.occupied:
            InfoDialog(self, "Diqqat", "Bu stol band. Avval bo'shating.", kind="warning").exec()
            return
        self.selected_table = {
            "name": t.name,
            "room": t.restaurant_room or "",
            "seats": int(t.no_of_seats or 0),
            "is_take_away": bool(t.is_take_away),
        }
        self.accept()

    def _on_free_table(self):
        t: RestaurantTable = getattr(self, "_selected_doc", None)
        if not t:
            return
        dlg = FreeReasonDialog(self, t.name)
        dlg.exec()
        reason = dlg.reason
        if not reason:
            return

        self._free_btn.setEnabled(False)
        self._free_btn.setText("Bo'shatilmoqda...")
        self._worker = FreeTableWorker(self.api, t.name, reason)
        self._worker.result_ready.connect(self._on_free_done)
        self._worker.start()

    def _on_free_done(self, success: bool, message: str):
        self._free_btn.setEnabled(True)
        self._free_btn.setText("🔓 Stolni bo'shatish")
        if success:
            InfoDialog(self, "Bajarildi", message, kind="success").exec()
            self.table_freed_signal.emit(getattr(self, "_selected_doc", None).name)
            # Lokal DBdagi stolni yangilash
            try:
                RestaurantTable.update(occupied=False, latest_invoice_time=None).where(
                    RestaurantTable.name == self._selected_doc.name
                ).execute()
            except Exception:
                pass
            self._load_data()
        else:
            InfoDialog(self, "Xatolik", message, kind="error").exec()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                TablePickerDialog._clear_layout(item.layout())


# ═══════════════════════════════════════════════════════════════
#  FreeReasonDialog — qo'lda bo'shatish sababini kiritish
# ═══════════════════════════════════════════════════════════════
class FreeReasonDialog(QDialog):
    """Sodda sabab kiritish dialogi."""

    def __init__(self, parent, table_name: str):
        super().__init__(parent)
        self.reason: str = ""
        self.setWindowTitle("Stol bo'shatish sababi")
        self.setModal(True)
        self.setFixedSize(s(480), s(280))
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(20), s(20), s(20), s(20))
        root.setSpacing(s(14))

        title = QLabel(f"Stol {table_name} — bo'shatish")
        title.setStyleSheet(f"font-size: {font(16)}px; font-weight: 800; color: #0f172a;")
        root.addWidget(title)

        hint = QLabel("Iltimos sababni qisqacha yozing:")
        hint.setStyleSheet(f"font-size: {font(12)}px; color: #64748b;")
        root.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Masalan: Mijoz to'lamadi va ketib qoldi")
        self._input.setFixedHeight(s(44))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {font(13)}px; padding: 0 {s(12)}px;
                border: 1.5px solid #e2e8f0; border-radius: {s(8)}px;
                color: #0f172a;
            }}
            QLineEdit:focus {{ border-color: #3b82f6; }}
        """)
        root.addWidget(self._input)

        root.addStretch()

        # Tugmalar
        row = QHBoxLayout()
        cancel_btn = QPushButton("Bekor")
        cancel_btn.setFixedHeight(s(44))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: #f1f5f9; color: #475569; padding: 0 {s(18)}px;
                font-weight: 700; font-size: {font(13)}px;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("✓  Bo'shatish")
        ok_btn.setFixedHeight(s(44))
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background: #dc2626; color: white; padding: 0 {s(24)}px;
                font-weight: 800; font-size: {font(13)}px;
                border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #b91c1c; }}
        """)
        ok_btn.clicked.connect(self._accept)

        row.addWidget(cancel_btn, 1)
        row.addWidget(ok_btn, 2)
        root.addLayout(row)

    def _accept(self):
        txt = self._input.text().strip()
        if not txt:
            InfoDialog(self, "Diqqat", "Iltimos sababni kiriting!", kind="warning").exec()
            return
        self.reason = txt
        self.accept()
