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
    QLineEdit, QStackedWidget,
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


class RefreshTablesWorker(QThread):
    """Server'dan stollar va xonalarni qayta yuklash workeri (realtime refresh)."""
    result_ready = pyqtSignal(bool, list, list)  # success, tables, rooms

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        try:
            ok_t, tables = self.api.call_method("ury.ury_pos.api.getTables")
            ok_r, rooms = self.api.call_method("ury.ury_pos.api.getRoomsForBranch")
            if ok_t and isinstance(tables, list):
                self.result_ready.emit(
                    True,
                    tables,
                    rooms if (ok_r and isinstance(rooms, list)) else [],
                )
            else:
                self.result_ready.emit(False, [], [])
        except Exception as e:
            logger.debug("RefreshTablesWorker xato: %s", e)
            self.result_ready.emit(False, [], [])
        finally:
            if not db.is_closed():
                db.close()


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
        from PyQt6.QtCore import Qt as _Qt
        # Tugma bo'sh — content QVBoxLayout orqali joylashtiriladi
        self.setText("")
        self.setCheckable(True)
        self.setMinimumSize(s(120), s(110))

        # Eski layoutni tozalash (rebuild paytida)
        old_layout = self.layout()
        if old_layout is not None:
            while old_layout.count():
                it = old_layout.takeAt(0)
                w = it.widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(10), s(12), s(10), s(12))
        layout.setSpacing(s(4))
        layout.setAlignment(_Qt.AlignmentFlag.AlignCenter)

        # Asosiy nom — katta
        self._name_lbl = QLabel(self.table_doc.name)
        self._name_lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setStyleSheet(
            f"font-size: {font(18)}px; font-weight: 900; background: transparent;"
        )
        layout.addWidget(self._name_lbl)

        # O'rin soni — kichikroq
        seats = self.table_doc.no_of_seats or 0
        if seats:
            self._seats_lbl = QLabel(f"👤 {seats} o'rin")
            self._seats_lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            self._seats_lbl.setStyleSheet(
                f"font-size: {font(11)}px; font-weight: 600;"
                f"background: transparent; letter-spacing: 0.3px;"
            )
            layout.addWidget(self._seats_lbl)

        # Holat badge — band bo'lsa
        if self.table_doc.occupied:
            self._status_lbl = QLabel("BAND")
            self._status_lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            self._status_lbl.setStyleSheet(
                f"font-size: {font(9)}px; font-weight: 800; color: white;"
                f"background: #dc2626; border-radius: {s(4)}px;"
                f"padding: {s(2)}px {s(8)}px; letter-spacing: 1px;"
            )
            layout.addWidget(self._status_lbl, alignment=_Qt.AlignmentFlag.AlignCenter)

        self._apply_style()

    def _apply_style(self):
        if self._selected:
            bg, border, color = _SELECTED_BG, _SELECTED_BORDER, _SELECTED_TEXT
        elif self.table_doc.occupied:
            bg, border, color = _OCC_BG, _OCC_BORDER, _OCC_TEXT
        else:
            bg, border, color = _FREE_BG, _FREE_BORDER, _FREE_TEXT

        self.setStyleSheet(f"""
            TableButton {{
                background: {bg};
                color: {color};
                border: 2px solid {border};
                border-radius: {s(14)}px;
            }}
            TableButton:hover {{
                border: 3px solid {border};
                background: white;
            }}
            TableButton:pressed {{
                background: {border};
            }}
            QLabel {{ color: {color}; }}
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

        # ── Header (back tugma stollar view'da, title view'ga qarab o'zgaradi) ──
        hdr = QHBoxLayout()
        self._back_btn = QPushButton("← Xonalar")
        self._back_btn.setFixedHeight(s(40))
        self._back_btn.setStyleSheet(f"""
            QPushButton {{
                background: #f1f5f9; color: #1d4ed8;
                font-size: {font(13)}px; font-weight: 700;
                padding: 0 {s(14)}px; border-radius: {s(8)}px; border: none;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        self._back_btn.clicked.connect(self._show_rooms_view)
        self._back_btn.setVisible(False)
        hdr.addWidget(self._back_btn)

        self._title_label = QLabel("Xonani tanlang")
        self._title_label.setStyleSheet(f"font-size: {font(20)}px; font-weight: 800; color: #0f172a;")
        hdr.addWidget(self._title_label)
        hdr.addStretch()

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

        # ── 2 view'li stacked: 0=xonalar ro'yxati, 1=stollar ─────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"""
            QStackedWidget {{
                background: #f8fafc; border: 1px solid #e2e8f0;
                border-radius: {s(12)}px;
            }}
        """)

        # View 0 — Xonalar ro'yxati (cards)
        self._rooms_scroll = QScrollArea()
        self._rooms_scroll.setWidgetResizable(True)
        self._rooms_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._rooms_canvas = QWidget()
        self._rooms_canvas.setStyleSheet("background: transparent;")
        self._rooms_scroll.setWidget(self._rooms_canvas)
        self._stack.addWidget(self._rooms_scroll)

        # View 1 — Stollar (canvas)
        tables_scroll = QScrollArea()
        tables_scroll.setWidgetResizable(True)
        tables_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._canvas = QWidget()
        self._canvas.setStyleSheet("background: transparent;")
        tables_scroll.setWidget(self._canvas)
        self._stack.addWidget(tables_scroll)

        root.addWidget(self._stack, stretch=1)

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
    def refresh_tables(self):
        """Server'dan eng yangi stol holatlarini olib lokal DB ni yangilaydi va UI ni
        qayta chizadi. Realtime event larida chaqiriladi (table_occupied/freed)."""
        if hasattr(self, "_refresh_worker") and self._refresh_worker.isRunning():
            return
        self._refresh_worker = RefreshTablesWorker(self.api)
        self._refresh_worker.result_ready.connect(self._on_refresh_done)
        self._refresh_worker.start()

    def _on_refresh_done(self, success: bool, tables: list, rooms: list):
        if not success:
            return
        try:
            db.connect(reuse_if_open=True)
            with db.atomic():
                for t in tables:
                    RestaurantTable.insert(
                        name=t.get("name"),
                        restaurant_room=t.get("restaurant_room") or "",
                        no_of_seats=int(t.get("no_of_seats") or 0),
                        occupied=bool(t.get("occupied")),
                        is_take_away=bool(t.get("is_take_away")),
                        latest_invoice_time=str(t.get("latest_invoice_time") or ""),
                        layout_x=float(t.get("layout_x") or 0),
                        layout_y=float(t.get("layout_y") or 0),
                        layout_width=float(t.get("layout_width") or 0),
                        layout_height=float(t.get("layout_height") or 0),
                        table_shape=t.get("table_shape") or "",
                    ).on_conflict_replace().execute()

            # Foydalanuvchi qaysi view'da bo'lganini saqlaymiz
            was_tables_view = self._stack.currentIndex() == 1
            active_room = getattr(self, "_active_room", "")

            # Lokal DB ni qayta yuklab cache yangilash
            self._all_rooms = list(Room.select().order_by(Room.name))
            self._all_tables = list(RestaurantTable.select().order_by(
                RestaurantTable.restaurant_room, RestaurantTable.name
            ))

            if was_tables_view:
                # Foydalanuvchi stollar view'da edi — shu xonadagi stollar
                self._show_tables_view(active_room)
            else:
                # Xonalar ro'yxati view'da edi — qayta ko'rsatamiz
                self._render_rooms_cards()
        except Exception as e:
            logger.debug("Stol picker refresh xatosi: %s", e)

    def _load_data(self):
        """Lokal DB dan xona va stollarni o'qish va UI ni yangilash.

        Avval xonalar ro'yxati ko'rsatiladi. Xona tanlangach uning stollari
        ochiladi. Agar bitta xona bo'lsa, to'g'ridan-to'g'ri stollarga o'tadi.
        """
        try:
            db.connect(reuse_if_open=True)
            self._all_rooms = list(Room.select().order_by(Room.name))
            self._all_tables = list(RestaurantTable.select().order_by(
                RestaurantTable.restaurant_room, RestaurantTable.name
            ))

            if not self._all_tables:
                self._show_empty_state()
                return

            # Har doim avval xonalar ro'yxati (foydalanuvchi talab qildi:
            # avval room select keyin ichida shu roomga tegishli tables).
            # Bitta xona bo'lsa ham 1 qadam tap-through bo'ladi — bir xil UX.
            self._show_rooms_view()

        except Exception as e:
            logger.error("Stol picker yuklashda xato: %s", e)
            InfoDialog(self, "Xatolik", f"Stollarni yuklab bo'lmadi: {e}", kind="info").exec()

    def _show_rooms_view(self):
        """Bosqich 1: xonalar ro'yxati cards bilan."""
        self._stack.setCurrentIndex(0)
        self._back_btn.setVisible(False)
        self._title_label.setText("Xonani tanlang")
        # Tanlangan stolni tozalash (boshqa xonaga o'tilganda)
        self._selected_doc = None
        self._info_label.setText("Xonani tanlang")
        self._info_label.setStyleSheet(
            f"font-size: {font(15)}px; font-weight: 700; color: #64748b;"
        )
        self._select_btn.setEnabled(False)
        self._free_btn.setVisible(False)
        self._render_rooms_cards()

    def _show_tables_view(self, room: str):
        """Bosqich 2: tanlangan xonadagi stollar."""
        self._stack.setCurrentIndex(1)
        # Back tugma har doim ko'rinadi — xonalar ro'yxatiga qaytish
        self._back_btn.setVisible(True)
        room_label = room if room else "Stollar"
        self._title_label.setText(f"{room_label} — stol tanlang")
        self._active_room = room
        # Tanlangan xonadagi stollar
        filtered = (
            [t for t in self._all_tables if t.restaurant_room == room]
            if room else self._all_tables
        )
        self._render_tables(filtered)

    def _render_rooms_cards(self):
        """Xonalar cards (5 ustun grid)."""
        # Eski canvasni tozalash
        if self._rooms_canvas.layout() is not None:
            self._clear_layout(self._rooms_canvas.layout())
            QWidget().setLayout(self._rooms_canvas.layout())

        grid = QGridLayout(self._rooms_canvas)
        grid.setSpacing(s(12))
        grid.setContentsMargins(s(20), s(20), s(20), s(20))

        # Stollarini Room nomi bo'yicha aniqlaymiz (Room recordi bo'lmasligi mumkin)
        room_table_count = {}
        room_occupied = {}
        for t in self._all_tables:
            rn = t.restaurant_room or "(xonasiz)"
            room_table_count[rn] = room_table_count.get(rn, 0) + 1
            if t.occupied:
                room_occupied[rn] = room_occupied.get(rn, 0) + 1

        # Ro'yxat (Room records + orphan rooms)
        all_room_names = list({r.name for r in self._all_rooms} | set(room_table_count.keys()))
        all_room_names.sort()
        all_room_names = [r for r in all_room_names if r in room_table_count]

        cols = 4
        for i, rn in enumerate(all_room_names):
            total = room_table_count.get(rn, 0)
            busy = room_occupied.get(rn, 0)
            free = total - busy
            card = self._make_room_card(rn, total, free, busy)
            grid.addWidget(card, i // cols, i % cols)

        grid.setRowStretch(grid.rowCount(), 1)

    def _make_room_card(self, room_name: str, total: int, free: int, busy: int) -> QPushButton:
        """Xona kartochkasi — bosilsa stollarga o'tadi."""
        card = QPushButton()
        card.setFixedHeight(s(140))
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Rangi — bo'sh stollar borligi bo'yicha
        if free > 0:
            border = "#bbf7d0"
            bg = "#f0fdf4"
            badge_bg = "#16a34a"
        else:
            border = "#fecaca"
            bg = "#fef2f2"
            badge_bg = "#dc2626"
        card.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: #0f172a;
                border: 2px solid {border};
                border-radius: {s(14)}px;
                padding: {s(14)}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: white;
                border-color: #93c5fd;
            }}
            QPushButton:pressed {{ background: #eff6ff; }}
        """)
        # Layout o'rniga matn (button label) — multi-line
        card.setText(
            f"🏠  {room_name}\n\n"
            f"  📋 Jami:  {total} stol\n"
            f"  ✓ Bo'sh:  {free}\n"
            f"  • Band:  {busy}"
        )
        card.setStyleSheet(card.styleSheet() + f"""
            QPushButton {{ font-size: {font(14)}px; font-weight: 700; }}
        """)
        card.clicked.connect(lambda _=None, r=room_name: self._show_tables_view(r))
        return card

    def _show_empty_state(self):
        # Rooms view'ga o'tib u yerda xabar ko'rsatamiz
        self._stack.setCurrentIndex(0)
        self._back_btn.setVisible(False)
        self._title_label.setText("Stol tanlang")
        if self._rooms_canvas.layout() is not None:
            self._clear_layout(self._rooms_canvas.layout())
            QWidget().setLayout(self._rooms_canvas.layout())
        v = QVBoxLayout(self._rooms_canvas)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg = QLabel("🚫  Stollar topilmadi\n\n"
                     "ERPNext da URY Table yarating va sinxronlang.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"font-size: {font(15)}px; color: #94a3b8; padding: {s(40)}px;")
        v.addWidget(msg)


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
        grid.setSpacing(s(14))
        grid.setContentsMargins(s(20), s(20), s(20), s(20))
        cols = 5
        for i, t in enumerate(tables):
            btn = TableButton(t)
            btn.setFixedSize(s(140), s(120))
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
