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
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont

from core.api import FrappeAPI
from core.logger import get_logger
from database.models import Room, RestaurantTable, db
from ui.components.dialogs import InfoDialog, ConfirmDialog
from ui.scale import s, font

logger = get_logger(__name__)


# ── Elite palette ───────────────────────────────────────
_GOLD = "#c89968"
_GOLD_LIGHT = "#e6c693"
_GOLD_DEEP = "#a07a44"
_SLATE_900 = "#0f172a"
_SLATE_800 = "#1e293b"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748b"
_SLATE_400 = "#94a3b8"
_SLATE_300 = "#cbd5e1"
_SLATE_200 = "#e2e8f0"
_SLATE_100 = "#f1f5f9"
_SLATE_50 = "#f8fafc"
_EMERALD_600 = "#059669"
_EMERALD_700 = "#047857"
_EMERALD_200 = "#a7f3d0"
_EMERALD_50 = "#ecfdf5"
_RED_700 = "#b91c1c"
_RED_500 = "#ef4444"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"


# ── Stol qutisi rangları (elite tones) ─────────────────
_FREE_BG = "white"
_FREE_BORDER = _EMERALD_200
_FREE_TEXT = _EMERALD_700

_OCC_BG = _RED_50
_OCC_BORDER = _RED_200
_OCC_TEXT = _RED_700

_SELECTED_BG = "#fff7ed"
_SELECTED_BORDER = _GOLD
_SELECTED_TEXT = _GOLD_DEEP


def _no_frame_label(text: str, color: str, px_size: int, weight: QFont.Weight,
                    letter_spacing: float = 0) -> QLabel:
    """QLabel ramkasiz va outline'siz."""
    lbl = QLabel(text)
    lbl.setFrameShape(QFrame.Shape.NoFrame)
    lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    f = QFont()
    f.setPixelSize(font(px_size))
    f.setWeight(weight)
    if letter_spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    lbl.setFont(f)
    lbl.setStyleSheet(
        f"color: {color}; background: transparent;"
        f" border: none; outline: none; padding: 0; margin: 0;"
    )
    return lbl


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
    """Stolni qo'lda bo'shatish workeri (freeTable API).

    Server tomon Ofitsant rolini rad etadi — active_cashier_role uzatamiz.
    """
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI, table: str, reason: str,
                 active_cashier: str = "", active_cashier_role: str = "Kassir"):
        super().__init__()
        self.api = api
        self.table = table
        self.reason = reason
        self.active_cashier = active_cashier
        self.active_cashier_role = active_cashier_role

    def run(self):
        try:
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.freeTable",
                {
                    "table": self.table,
                    "reason": self.reason,
                    "active_cashier": self.active_cashier,
                    "active_cashier_role": self.active_cashier_role,
                },
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


class _RoomCard(QFrame):
    """Xona kartasi — elite kompakt dizayn.

    Layout:
      ┌────────────────────────────────────────────┐
      │ │ DEFAULT SMART              2  BO'SH    →│
      │ │ 2 stol  ·  0 band                       │
      └────────────────────────────────────────────┘
       ↑ 4px aksent chizig'i (gold yashil = bo'sh bor, red = to'liq band)

    Asosiy diqqat — kassirga "bo'sh stollar" ko'rsatkichi (eng muhim).
    """

    clicked = pyqtSignal()

    def __init__(self, room_name: str, total: int, free: int, busy: int,
                 parent=None):
        super().__init__(parent)
        self.setFixedHeight(s(110))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Holatga qarab aksent rang
        all_busy = (free == 0 and total > 0)
        if all_busy:
            accent = _RED_700
            accent_border = _RED_200
            hover_bg = _RED_50
            accent_bar = "#ef4444"
        else:
            accent = _EMERALD_700
            accent_border = _EMERALD_200
            hover_bg = _EMERALD_50
            accent_bar = _GOLD

        self._accent = accent
        self._accent_border = accent_border
        self._hover_bg = hover_bg
        self._accent_bar = accent_bar
        self._apply_idle()

        # Asosiy layout — horizontal split
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(20), s(14), s(20), s(14))
        layout.setSpacing(s(16))

        # Chap blok: xona nomi + qisqa stat
        left = QVBoxLayout()
        left.setSpacing(s(4))
        left.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = _no_frame_label(
            room_name.upper(), _SLATE_900, 16, QFont.Weight.Black, 2.5
        )
        left.addWidget(title)

        # Inline stat — "N stol · M band"
        substat = _no_frame_label(
            f"{total} stol  ·  {busy} band",
            _SLATE_500, 11, QFont.Weight.DemiBold, 0.5,
        )
        left.addWidget(substat)

        layout.addLayout(left, stretch=1)

        # O'ng blok: katta BO'SH ko'rsatkich + arrow
        right = QHBoxLayout()
        right.setSpacing(s(14))
        right.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Katta BO'SH counter
        free_block = QVBoxLayout()
        free_block.setSpacing(s(0))
        free_block.setAlignment(Qt.AlignmentFlag.AlignCenter)
        free_num = _no_frame_label(
            str(free), accent, 32, QFont.Weight.Black, 0
        )
        free_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        free_block.addWidget(free_num)
        free_lbl = _no_frame_label(
            "BO'SH" if not all_busy else "TO'LIQ BAND",
            accent, 9, QFont.Weight.Black, 2,
        )
        free_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        free_block.addWidget(free_lbl)
        right.addLayout(free_block)

        # Chevron arrow — clickable signal
        arrow = QLabel("›")
        arrow.setFrameShape(QFrame.Shape.NoFrame)
        arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        arf = QFont()
        arf.setPixelSize(font(28))
        arf.setWeight(QFont.Weight.Light)
        arrow.setFont(arf)
        arrow.setStyleSheet(
            f"color: {_SLATE_300}; background: transparent;"
            f" border: none; outline: none;"
        )
        arrow.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        right.addWidget(arrow)

        layout.addLayout(right)

    def _apply_idle(self):
        self.setStyleSheet(f"""
            _RoomCard {{
                background: white;
                border: 1px solid {_SLATE_200};
                border-left: 4px solid {self._accent_bar};
                border-radius: {s(12)}px;
            }}
        """)

    def _apply_hover(self):
        self.setStyleSheet(f"""
            _RoomCard {{
                background: {self._hover_bg};
                border: 1px solid {self._accent_border};
                border-left: 4px solid {self._accent_bar};
                border-radius: {s(12)}px;
            }}
        """)

    def enterEvent(self, event):
        self._apply_hover()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_idle()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
        self.setCursor(_Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
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
        layout.setContentsMargins(s(10), s(14), s(10), s(14))
        layout.setSpacing(s(6))
        layout.setAlignment(_Qt.AlignmentFlag.AlignCenter)

        # Asosiy nom — katta (no_frame label, letter-spacing bilan)
        self._name_lbl = _no_frame_label(
            self.table_doc.name, _SLATE_900, 20, QFont.Weight.Black, 1
        )
        self._name_lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._name_lbl)

        # O'rin soni — emoji yo'q, sof tipografiya
        seats = self.table_doc.no_of_seats or 0
        if seats:
            self._seats_lbl = _no_frame_label(
                f"{seats} o'rin", _SLATE_500, 11, QFont.Weight.DemiBold, 0.3
            )
            self._seats_lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._seats_lbl)

        # Holat badge — band bo'lsa, refined pill
        if self.table_doc.occupied:
            self._status_lbl = QLabel("BAND")
            self._status_lbl.setFrameShape(QFrame.Shape.NoFrame)
            self._status_lbl.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
            self._status_lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            badge_font = QFont()
            badge_font.setPixelSize(font(9))
            badge_font.setWeight(QFont.Weight.Black)
            badge_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
            self._status_lbl.setFont(badge_font)
            self._status_lbl.setStyleSheet(
                f"color: white; background: {_RED_500};"
                f" border-radius: {s(4)}px; border: none; outline: none;"
                f" padding: {s(2)}px {s(10)}px;"
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
                border: 1.5px solid {border};
                border-radius: {s(12)}px;
                outline: none;
            }}
            TableButton:hover {{
                border: 1.5px solid {color};
                background: {_SLATE_50 if not self._selected else _SELECTED_BG};
            }}
            TableButton:pressed {{
                background: {border};
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

    def __init__(self, parent, api: FrappeAPI, current_table: str = "",
                 active_cashier: str = "", active_cashier_role: str = "Kassir"):
        super().__init__(parent)
        self.api = api
        self.selected_table: dict | None = None
        self._current_table = current_table
        self._active_cashier = active_cashier
        self._active_cashier_role = active_cashier_role or "Kassir"
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
        root.setContentsMargins(s(28), s(20), s(28), s(20))
        root.setSpacing(s(14))

        # ── Header ────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(s(12))

        self._back_btn = QPushButton("← Xonalar")
        self._back_btn.setFixedHeight(s(36))
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._back_btn.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {_SLATE_700};
                font-size: {font(12)}px;
                font-weight: 600;
                padding: 0 {s(14)}px;
                border-radius: {s(8)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        self._back_btn.clicked.connect(self._show_rooms_view)
        self._back_btn.setVisible(False)
        hdr.addWidget(self._back_btn)

        # Title block (caps + subtitle)
        title_block = QVBoxLayout()
        title_block.setSpacing(s(2))
        self._title_label = _no_frame_label(
            "XONANI TANLANG", _SLATE_900, 14, QFont.Weight.Black, 2
        )
        title_block.addWidget(self._title_label)
        self._subtitle_label = _no_frame_label(
            "Stol band yoki bo'sh holatini ko'ring",
            _SLATE_500, 11, QFont.Weight.Medium, 0,
        )
        title_block.addWidget(self._subtitle_label)
        hdr.addLayout(title_block)

        hdr.addStretch()

        refresh_btn = QPushButton("Yangilash")
        refresh_btn.setFixedHeight(s(36))
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {_SLATE_700};
                font-size: {font(12)}px;
                font-weight: 600;
                padding: 0 {s(16)}px;
                border-radius: {s(8)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        refresh_btn.clicked.connect(self._load_data)
        hdr.addWidget(refresh_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(36), s(36))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_SLATE_400};
                font-weight: 700;
                font-size: {font(14)}px;
                border-radius: {s(8)}px;
                border: 1px solid transparent;
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                color: {_SLATE_900};
                border: 1px solid {_SLATE_200};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        close_btn.clicked.connect(self.reject)
        hdr.addWidget(close_btn)
        root.addLayout(hdr)

        # Hairline
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_SLATE_100}; border: none;")
        root.addWidget(sep)

        # ── 2 view'li stacked: 0=xonalar ro'yxati, 1=stollar ─────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"""
            QStackedWidget {{
                background: white;
                border: none;
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
        bottom.setSpacing(s(10))
        self._info_label = _no_frame_label(
            "Stol tanlanmagan", _SLATE_500, 14, QFont.Weight.DemiBold, 0
        )
        bottom.addWidget(self._info_label)
        bottom.addStretch()

        # Qo'lda bo'shatish — band stol tanlanganda paydo bo'ladi
        self._free_btn = QPushButton("Stolni bo'shatish")
        self._free_btn.setFixedHeight(s(46))
        self._free_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._free_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._free_btn.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {_RED_700};
                font-weight: 700;
                font-size: {font(13)}px;
                letter-spacing: 0.5px;
                padding: 0 {s(20)}px;
                border-radius: {s(10)}px;
                border: 1px solid {_RED_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_RED_50};
                border-color: #fca5a5;
            }}
            QPushButton:pressed {{ background: #fee2e2; }}
        """)
        self._free_btn.clicked.connect(self._on_free_table)
        self._free_btn.setVisible(False)
        bottom.addWidget(self._free_btn)

        cancel_btn = QPushButton("Bekor")
        cancel_btn.setFixedHeight(s(46))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: {_SLATE_700};
                font-weight: 600;
                font-size: {font(13)}px;
                letter-spacing: 0.5px;
                padding: 0 {s(24)}px;
                border-radius: {s(10)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_50};
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        self._select_btn = QPushButton("Tanlash")
        self._select_btn.setFixedHeight(s(46))
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_SLATE_900};
                color: white;
                font-weight: 800;
                font-size: {font(13)}px;
                letter-spacing: 1.5px;
                padding: 0 {s(32)}px;
                border-radius: {s(10)}px;
                border: 1px solid {_SLATE_900};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_800};
                border-color: {_SLATE_800};
            }}
            QPushButton:pressed {{ background: #0b1220; }}
            QPushButton:disabled {{
                background: {_SLATE_100};
                color: {_SLATE_400};
                border-color: {_SLATE_200};
            }}
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
        self._title_label.setText("XONANI TANLANG")
        if hasattr(self, "_subtitle_label"):
            self._subtitle_label.setText("Stol band yoki bo'sh holatini ko'ring")
        # Tanlangan stolni tozalash (boshqa xonaga o'tilganda)
        self._selected_doc = None
        self._info_label.setText("Stol tanlanmagan")
        self._info_label.setStyleSheet(
            f"color: {_SLATE_500}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        self._select_btn.setEnabled(False)
        self._free_btn.setVisible(False)
        self._render_rooms_cards()

    def _show_tables_view(self, room: str):
        """Bosqich 2: tanlangan xonadagi stollar."""
        self._stack.setCurrentIndex(1)
        # Back tugma har doim ko'rinadi — xonalar ro'yxatiga qaytish
        self._back_btn.setVisible(True)
        room_label = (room if room else "STOLLAR").upper()
        self._title_label.setText(room_label)
        if hasattr(self, "_subtitle_label"):
            self._subtitle_label.setText("Stol tanlang yoki band stolni bo'shating")
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

        # Adaptive ustun soni: 1 xona — 1 col (full width), 2-3 xona — 2 col,
        # 4+ xona — 3 col. Kartochka kompaktroq bo'lgani uchun ko'p sig'adi.
        room_count = len(all_room_names)
        if room_count <= 1:
            cols = 1
        elif room_count <= 4:
            cols = 2
        else:
            cols = 3

        for i, rn in enumerate(all_room_names):
            total = room_table_count.get(rn, 0)
            busy = room_occupied.get(rn, 0)
            free = total - busy
            card = self._make_room_card(rn, total, free, busy)
            grid.addWidget(card, i // cols, i % cols)

        grid.setRowStretch(grid.rowCount(), 1)

    def _make_room_card(self, room_name: str, total: int, free: int, busy: int) -> QWidget:
        """Xona kartochkasi — clickable QFrame, ichida elite typography."""
        # Kartochka tugma o'rniga QFrame + click event
        card = _RoomCard(room_name, total, free, busy)
        card.clicked.connect(lambda r=room_name: self._show_tables_view(r))
        return card

    def _show_empty_state(self):
        # Rooms view'ga o'tib u yerda xabar ko'rsatamiz
        self._stack.setCurrentIndex(0)
        self._back_btn.setVisible(False)
        self._title_label.setText("STOL TANLANG")
        if self._rooms_canvas.layout() is not None:
            self._clear_layout(self._rooms_canvas.layout())
            QWidget().setLayout(self._rooms_canvas.layout())
        v = QVBoxLayout(self._rooms_canvas)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(s(8))

        title = _no_frame_label(
            "Stollar topilmadi", _SLATE_900, 15, QFont.Weight.Bold, 0.5
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(title)

        sub = _no_frame_label(
            "ERPNext da URY Table yarating va sinxronlang",
            _SLATE_500, 12, QFont.Weight.Medium, 0,
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(sub)


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
        seats = f" · {t.no_of_seats} o'rin" if t.no_of_seats else ""
        status = "  ·  BAND" if t.occupied else ""
        self._info_label.setText(
            f"Tanlangan: {room_label}{t.name}{seats}{status}"
        )
        color = _RED_700 if t.occupied else _SLATE_900
        self._info_label.setStyleSheet(
            f"color: {color}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        # Faqat bo'sh stol tanlash mumkin (lekin band stolni ko'rsatishga ruxsat)
        self._select_btn.setEnabled(not t.occupied)
        # Bo'shatish tugmasi — faqat kassir uchun va band stol bo'lsa
        is_kassir = self._active_cashier_role != "Ofitsant"
        self._free_btn.setVisible(bool(t.occupied) and is_kassir)
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

        # Ofitsant stol bo'shata olmaydi (UI darajasida ham, server ham bloklaydi)
        if self._active_cashier_role == "Ofitsant":
            InfoDialog(
                self, "Ruxsat yo'q",
                "Ofitsant stolni bo'shata olmaydi.\nKassirga murojaat qiling.",
                kind="info",
            ).exec()
            return

        dlg = FreeReasonDialog(self, t.name)
        dlg.exec()
        reason = dlg.reason
        if not reason:
            return

        self._free_btn.setEnabled(False)
        self._free_btn.setText("Bo'shatilmoqda...")
        self._worker = FreeTableWorker(
            self.api, t.name, reason,
            active_cashier=self._active_cashier,
            active_cashier_role=self._active_cashier_role,
        )
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
QUICK_FREE_REASONS = [
    "Mijoz to'lamay ketdi",
    "Buyurtma bekor qilindi",
    "Boshqa stolga ko'chirildi",
    "Stol tashlab ketildi",
    "Texnik sabab",
]


class FreeReasonDialog(QDialog):
    """Stol bo'shatish sababi — tezkor sabablar + sensor klaviatura.

    History dagi CancelReasonDialog modeliga o'xshash (consistent UX).
    """

    def __init__(self, parent, table_name: str):
        super().__init__(parent)
        self.reason: str = ""
        self.table_name = table_name
        self.setWindowTitle("Stol bo'shatish sababi")
        self.setModal(True)
        self.setFixedSize(s(660), s(560))
        self.setStyleSheet("background: white;")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(20), s(16), s(20), s(16))
        layout.setSpacing(s(10))

        # Title
        title = QLabel(f"🔓  {self.table_name}  —  Bo'shatish sababi")
        title.setStyleSheet(f"font-size: {font(16)}px; font-weight: 800; color: #0f172a;")
        layout.addWidget(title)

        # Quick reason chips
        quick_lbl = QLabel("TEZKOR SABABLAR:")
        quick_lbl.setStyleSheet(
            f"font-size: {font(10)}px; color: #94a3b8;"
            f" font-weight: 700; letter-spacing: 1px;"
        )
        layout.addWidget(quick_lbl)

        chips_row1 = QHBoxLayout()
        chips_row1.setSpacing(s(6))
        chips_row2 = QHBoxLayout()
        chips_row2.setSpacing(s(6))
        for i, reason in enumerate(QUICK_FREE_REASONS):
            btn = QPushButton(reason)
            btn.setFixedHeight(s(38))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #f1f5f9; color: #334155;
                    font-size: {font(11)}px; font-weight: 600;
                    border-radius: {s(8)}px; border: 1.5px solid #e2e8f0;
                    padding: 0 {s(10)}px;
                }}
                QPushButton:hover {{
                    background: #fff7ed; color: #c2410c; border-color: #fdba74;
                }}
                QPushButton:pressed {{ background: #ffedd5; }}
            """)
            btn.clicked.connect(lambda _, r=reason: self._fill_reason(r))
            if i < 3:
                chips_row1.addWidget(btn)
            else:
                chips_row2.addWidget(btn)
        chips_row2.addStretch()
        layout.addLayout(chips_row1)
        layout.addLayout(chips_row2)

        # Input display
        self.input = QLineEdit()
        self.input.setPlaceholderText("Sabab yozing yoki yuqoridan tanlang...")
        self.input.setFixedHeight(s(48))
        self.input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {font(14)}px; color: #1e293b;
                background: white;
                border: 2px solid #3b82f6;
                border-radius: {s(10)}px; padding: {s(8)}px {s(14)}px;
            }}
        """)
        layout.addWidget(self.input)

        # Sensor klaviatura
        rows = [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['A','S','D','F','G','H','J','K','L','CLR'],
            ['Z','X','C','V','B','N','M','SPACE'],
        ]
        for row_keys in rows:
            row_w = QHBoxLayout()
            row_w.setSpacing(s(4))
            for k in row_keys:
                row_w.addWidget(self._make_key(k))
            layout.addLayout(row_w)

        # Tugmalar
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Bekor")
        cancel_btn.setFixedHeight(s(44))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: #f1f5f9; color: #64748b;
                font-weight: 700; border-radius: {s(10)}px; border: none; }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("🔓  Bo'shatish")
        confirm_btn.setFixedHeight(s(44))
        confirm_btn.setStyleSheet(f"""
            QPushButton {{ background: #ea580c; color: white;
                font-weight: 700; font-size: {font(14)}px;
                border-radius: {s(10)}px; border: none; }}
            QPushButton:hover {{ background: #c2410c; }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

    def _fill_reason(self, reason: str):
        self.input.setText(reason)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {font(14)}px; color: #1e293b;
                background: white;
                border: 2px solid #3b82f6;
                border-radius: {s(10)}px; padding: {s(8)}px {s(14)}px;
            }}
        """)

    def _make_key(self, key):
        label = '␣' if key == 'SPACE' else ('TOZALASH' if key == 'CLR' else key)
        btn = QPushButton(label)
        btn.setFixedHeight(s(44))
        if key == '⌫':
            style = f"background:#fee2e2; color:#ef4444; font-size:{font(15)}px; font-weight:bold;"
        elif key == 'CLR':
            style = f"background:#fff7ed; color:#ea580c; font-size:{font(10)}px; font-weight:bold;"
        elif key == 'SPACE':
            style = f"background:#eff6ff; color:#3b82f6; font-size:{font(13)}px; font-weight:bold;"
            btn.setMinimumWidth(s(80))
        elif key.isdigit():
            style = f"background:#f1f5f9; color:#334155; font-size:{font(13)}px; font-weight:700;"
        else:
            style = f"background:white; color:#1e293b; font-size:{font(13)}px; font-weight:600;"
        btn.setStyleSheet(f"""
            QPushButton {{ {style} border:1px solid #e2e8f0; border-radius:{s(6)}px; }}
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
        txt = self.input.text().strip()
        if not txt:
            self.input.setStyleSheet(f"""
                QLineEdit {{
                    font-size: {font(14)}px; color: #1e293b;
                    background: #fff5f5;
                    border: 2px solid #ef4444;
                    border-radius: {s(10)}px; padding: {s(8)}px {s(14)}px;
                }}
            """)
            return
        self.reason = txt
        self.accept()
