#type: ignore
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLabel, QHBoxLayout,
    QComboBox, QLineEdit, QGroupBox, QFrame,
    QScroller, QScrollerProperties,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont
from database.models import Customer, db
from core.logger import get_logger
from core.config import load_config
from core.constants import (
    TICKET_ORDER_TYPES, TABLE_ORDER_TYPES, ORDER_TYPES,
    ORDER_NUMBER_TYPE_STICKER, ORDER_NUMBER_TYPE_TABLE,
)
from ui.components.keyboard import TouchKeyboard
from ui.components.dialogs import InfoDialog
from ui.scale import s, font

logger = get_logger(__name__)


# ── Elite palette ────────────────────────────────────────
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
_RED_700 = "#b91c1c"
_RED_200 = "#fecaca"
_RED_50 = "#fef2f2"


def _no_frame_label(text: str, color: str, px_size: int, weight: QFont.Weight,
                    letter_spacing: float = 0) -> QLabel:
    """QLabel ramkasiz va outline'siz — global QSS ta'sirini bekor qiladi."""
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


class QtyLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()


class CartWidget(QWidget):
    checkout_requested = pyqtSignal(dict)
    save_requested = pyqtSignal(dict)          # TZ 4.2 — To'lovsiz saqlash
    table_pick_requested = pyqtSignal()        # MainWindow stol pickerni ochishi uchun

    def __init__(self):
        super().__init__()
        self.items = {}
        self.total_amount = 0.0
        self.current_order_type = ORDER_TYPES[0]
        self.order_type_buttons = {}
        self._numpad_mode = "ticket"
        self._active_qty_item = None
        self.selected_table: dict | None = None    # {"name", "room", "seats", "is_take_away"}
        self._role = "Kassir"                       # Default rol, set_role() bilan yangilanadi
        self.init_ui()
        self.load_customers()

    def init_ui(self):
        cfg = load_config()
        _show_comment  = bool(cfg.get("show_comment", 1))
        _show_ticket   = bool(cfg.get("show_ticket", 1))
        _show_customer = bool(cfg.get("show_customer", 1))
        _order_types   = cfg.get("enabled_order_types") or ORDER_TYPES

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(s(8), s(8), s(8), s(8))
        main_layout.setSpacing(s(8))

        # ── Order Details Section (no frame) ──
        details_group = QWidget()
        details_group.setStyleSheet(
            f"background: {_SLATE_50}; border: 1px solid {_SLATE_200};"
            f" border-radius: {s(12)}px;"
        )
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(s(16), s(14), s(16), s(14))
        details_layout.setSpacing(s(10))

        # Section title — elite caps wordmark
        section_title = _no_frame_label(
            "BUYURTMA MA'LUMOTLARI", _SLATE_900, 12, QFont.Weight.Black, 2
        )
        details_layout.addWidget(section_title)

        # Sub-section: order type
        type_label = _no_frame_label(
            "BUYURTMA TURI", _SLATE_500, 9, QFont.Weight.Black, 2
        )
        details_layout.addWidget(type_label)

        # Barcha buyurtma turi tugmalari (doim yaratiladi, visibility bilan boshqariladi)
        types_layout = QHBoxLayout()
        types_layout.setSpacing(s(5))
        for t in ORDER_TYPES:
            btn = QPushButton(t)
            btn.setFixedHeight(s(56))
            btn.setCheckable(True)
            btn.setStyleSheet(self._order_type_style(False))
            btn.clicked.connect(lambda checked, val=t: self.set_order_type(val))
            types_layout.addWidget(btn, 1)
            self.order_type_buttons[t] = btn

        first_type = _order_types[0] if _order_types else ORDER_TYPES[0]
        self.order_type_buttons[first_type].setChecked(True)
        self.order_type_buttons[first_type].setStyleSheet(self._order_type_style(True))
        self.current_order_type = first_type
        details_layout.addLayout(types_layout)

        # Sticker + Customer row — container widget'larga o'ralgan (toggle uchun)
        middle_row = QHBoxLayout()
        middle_row.setSpacing(s(10))

        # Stiker container (Stiker rejimi uchun)
        self._ticket_container = QWidget()
        self._ticket_container.setStyleSheet("background: transparent; border: none;")
        sticker_vbox = QVBoxLayout(self._ticket_container)
        sticker_vbox.setContentsMargins(0, 0, 0, 0)
        sticker_vbox.setSpacing(s(4))
        sticker_label = _no_frame_label(
            "STIKER", _SLATE_500, 9, QFont.Weight.Black, 2
        )
        self.ticket_input = QLineEdit()
        self.ticket_input.setMaxLength(6)
        self.ticket_input.setPlaceholderText("—")
        self.ticket_input.setFixedHeight(s(55))
        self.ticket_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ticket_input.setStyleSheet(self._input_style())
        self.ticket_input.mousePressEvent = self._open_ticket_numpad
        self.ticket_input.textChanged.connect(self._on_ticket_text_changed)
        sticker_vbox.addWidget(sticker_label)
        sticker_vbox.addWidget(self.ticket_input)
        middle_row.addWidget(self._ticket_container, 1)

        # Stol container (Stol rejimi uchun) — TZ 4.1.7
        self._table_container = QWidget()
        self._table_container.setStyleSheet("background: transparent; border: none;")
        table_vbox = QVBoxLayout(self._table_container)
        table_vbox.setContentsMargins(0, 0, 0, 0)
        table_vbox.setSpacing(s(4))
        table_label = _no_frame_label(
            "STOL", _SLATE_500, 9, QFont.Weight.Black, 2
        )
        self.table_button = QPushButton("Stol tanlash...")
        self.table_button.setFixedHeight(s(55))
        self.table_button.setStyleSheet(self._table_btn_style(False))
        self.table_button.clicked.connect(lambda: self.table_pick_requested.emit())
        table_vbox.addWidget(table_label)
        table_vbox.addWidget(self.table_button)
        middle_row.addWidget(self._table_container, 1)
        self._table_container.setVisible(False)  # default Stiker — apply_settings ochadi

        # Mijoz container
        self._customer_container = QWidget()
        self._customer_container.setStyleSheet("background: transparent; border: none;")
        customer_vbox = QVBoxLayout(self._customer_container)
        customer_vbox.setContentsMargins(0, 0, 0, 0)
        customer_vbox.setSpacing(s(4))
        customer_label = _no_frame_label(
            "MIJOZ", _SLATE_500, 9, QFont.Weight.Black, 2
        )
        self.customer_combo = QComboBox()
        self.customer_combo.setEditable(True)
        self.customer_combo.setFixedHeight(s(55))
        self.customer_combo.setStyleSheet(self._input_style())
        customer_vbox.addWidget(customer_label)
        customer_vbox.addWidget(self.customer_combo)
        middle_row.addWidget(self._customer_container, 3)

        details_layout.addLayout(middle_row)

        # Izoh container
        self._comment_container = QWidget()
        self._comment_container.setStyleSheet("background: transparent; border: none;")
        comment_vbox = QVBoxLayout(self._comment_container)
        comment_vbox.setContentsMargins(0, 0, 0, 0)
        comment_vbox.setSpacing(s(4))
        comment_label = _no_frame_label(
            "IZOH", _SLATE_500, 9, QFont.Weight.Black, 2
        )
        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Buyurtma izohi...")
        self.comment_input.setFixedHeight(s(50))
        self.comment_input.setStyleSheet(self._input_style())
        self.comment_input.mousePressEvent = self._open_comment_keyboard
        self.comment_input.textChanged.connect(self._on_comment_text_changed)
        comment_vbox.addWidget(comment_label)
        comment_vbox.addWidget(self.comment_input)
        details_layout.addWidget(self._comment_container)

        # Boshlang'ich visibility — config dan
        self.apply_settings(show_comment=_show_comment,
                            show_ticket=_show_ticket,
                            show_customer=_show_customer,
                            enabled_order_types=_order_types)

        main_layout.addWidget(details_group)

        # ── Cart Table ───────────────────────
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["MAHSULOT", "MIQDOR", "NARX", "SUMMA"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border: none;
                background: white;
                font-size: {font(14)}px;
                font-weight: 600;
                color: {_SLATE_900};
                outline: none;
                gridline-color: transparent;
            }}
            QTableWidget::item {{
                padding: {s(6)}px {s(14)}px;
                border: none;
                border-right: 1px solid {_SLATE_100};
            }}
            QTableWidget::item:last {{ border-right: none; }}
            QTableWidget::item:alternate {{ background: {_SLATE_50}; }}
            QTableWidget::item:hover {{ background: #fffbeb; }}
            QTableWidget::item:selected {{ background: #fff7ed; color: {_GOLD_DEEP}; }}
            QHeaderView {{ background: transparent; border: none; }}
            QHeaderView::section {{
                background: white;
                color: {_SLATE_400};
                font-weight: 800;
                font-size: {font(10)}px;
                letter-spacing: 2px;
                padding: {s(12)}px {s(14)}px;
                border: none;
                border-bottom: 2px solid {_SLATE_200};
                border-right: 1px solid {_SLATE_100};
            }}
            QHeaderView::section:last {{ border-right: none; }}
            QScrollBar:vertical {{
                width: {s(6)}px; background: transparent; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {_SLATE_300}; border-radius: {s(3)}px;
                min-height: {s(30)}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, s(176))
        self.table.setColumnWidth(2, s(140))
        self.table.setColumnWidth(3, s(150))

        # MIQDOR markazda, NARX va SUMMA o'ngda
        center_align = Qt.AlignmentFlag.AlignCenter
        right_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self.table.horizontalHeaderItem(1).setTextAlignment(center_align)
        self.table.horizontalHeaderItem(2).setTextAlignment(right_align)
        self.table.horizontalHeaderItem(3).setTextAlignment(right_align)

        main_layout.addWidget(self.table)

        # Touch scroll — sensorli ekranda barmaq bilan surish
        scroller = QScroller.scroller(self.table.viewport())
        scroller.grabGesture(self.table.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        props = scroller.scrollerProperties()
        props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
        props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
        scroller.setScrollerProperties(props)

        # ── Totals Card ───────────────────────
        totals_card = QFrame()
        totals_card.setStyleSheet(f"""
            QFrame {{
                background: {_SLATE_50};
                border: 1px solid {_SLATE_200};
                border-radius: {s(12)}px;
            }}
        """)
        totals_layout = QHBoxLayout(totals_card)
        totals_layout.setContentsMargins(s(18), s(12), s(14), s(12))

        total_title = _no_frame_label(
            "JAMI", _SLATE_500, 11, QFont.Weight.Black, 2.5
        )
        self.total_label = _no_frame_label(
            "0 UZS", _SLATE_900, 32, QFont.Weight.Black, 0.5
        )
        self.total_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        totals_layout.addWidget(total_title)
        totals_layout.addStretch()
        totals_layout.addWidget(self.total_label)

        self.clear_btn = QPushButton("Tozalash")
        self.clear_btn.setFixedSize(s(120), s(40))
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_RED_700};
                font-weight: 700;
                font-size: {font(12)}px;
                letter-spacing: 0.5px;
                border-radius: {s(8)}px;
                border: 1px solid transparent;
                outline: none;
            }}
            QPushButton:hover {{
                background: {_RED_50};
                border: 1px solid {_RED_200};
            }}
            QPushButton:pressed {{ background: #fee2e2; }}
        """)
        self.clear_btn.clicked.connect(self.clear_cart)
        totals_layout.addWidget(self.clear_btn)
        main_layout.addWidget(totals_card)

        # ── Action Buttons (Saqlash + Checkout) ──
        actions_row = QHBoxLayout()
        actions_row.setSpacing(s(8))

        # Saqlash tugmasi — to'lovsiz buyurtma (TZ 4.2.1)
        self.save_btn = QPushButton("SAQLASH")
        self.save_btn.setFixedHeight(s(72))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_SLATE_900};
                color: white;
                font-size: {font(16)}px;
                font-weight: 800;
                letter-spacing: 2px;
                border-radius: {s(14)}px;
                border: 1px solid {_SLATE_900};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_SLATE_800};
                border-color: {_SLATE_800};
            }}
            QPushButton:pressed {{ background: #0b1220; }}
        """)
        self.save_btn.clicked.connect(self.handle_save)
        actions_row.addWidget(self.save_btn, 2)

        self.checkout_btn = QPushButton("TO'LOV QILISH    F12")
        self.checkout_btn.setFixedHeight(s(72))
        self.checkout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkout_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.checkout_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_EMERALD_600};
                color: white;
                font-size: {font(18)}px;
                font-weight: 800;
                letter-spacing: 1.5px;
                border-radius: {s(14)}px;
                border: 1px solid {_EMERALD_600};
                outline: none;
            }}
            QPushButton:hover {{
                background: {_EMERALD_700};
                border-color: {_EMERALD_700};
            }}
            QPushButton:pressed {{ background: #065f46; }}
        """)
        self.checkout_btn.clicked.connect(self.handle_checkout)
        actions_row.addWidget(self.checkout_btn, 3)

        main_layout.addLayout(actions_row)

        # ── Inline bottom panels ─────────────
        self.numpad_panel = self._build_numpad_panel()
        self.numpad_panel.setVisible(False)
        main_layout.addWidget(self.numpad_panel)

        self.keyboard_panel = self._build_keyboard_panel()
        self.keyboard_panel.setVisible(False)
        main_layout.addWidget(self.keyboard_panel)

        self.setLayout(main_layout)
        self.set_order_type(ORDER_TYPES[0])

    # ─────────────────────────────────────────
    #  INLINE NUMPAD — elite
    # ─────────────────────────────────────────
    def _build_numpad_panel(self):
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {_SLATE_50};"
            f" border-top: 1px solid {_SLATE_200}; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(s(14), s(12), s(14), s(14))
        layout.setSpacing(s(8))

        top = QHBoxLayout()
        top.setSpacing(s(10))
        self.numpad_display = QLabel("—")
        self.numpad_display.setFixedHeight(s(46))
        self.numpad_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.numpad_display.setFrameShape(QFrame.Shape.NoFrame)
        self.numpad_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        np_font = QFont()
        np_font.setPixelSize(font(22))
        np_font.setWeight(QFont.Weight.Black)
        np_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.numpad_display.setFont(np_font)
        self.numpad_display.setStyleSheet(
            f"color: {_SLATE_900}; background: white;"
            f" border: 1px solid {_SLATE_200}; border-radius: {s(10)}px;"
            f" padding: 0 {s(14)}px; outline: none;"
        )
        np_close = QPushButton("✕")
        np_close.setFixedSize(s(46), s(46))
        np_close.setCursor(Qt.CursorShape.PointingHandCursor)
        np_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        np_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_SLATE_400};
                font-weight: 700;
                font-size: {font(15)}px;
                border-radius: {s(10)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: white;
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        np_close.clicked.connect(self._close_panels)
        top.addWidget(self.numpad_display, stretch=1)
        top.addWidget(np_close)
        layout.addLayout(top)

        keys = [['7','8','9'], ['4','5','6'], ['1','2','3'], ['CLR','0','⌫']]
        for row_keys in keys:
            row = QHBoxLayout()
            row.setSpacing(s(8))
            for k in row_keys:
                row.addWidget(self._make_numpad_key(k))
            layout.addLayout(row)

        return panel

    def _make_numpad_key(self, key):
        label = 'TOZALASH' if key == 'CLR' else key
        btn = QPushButton(label)
        btn.setFixedHeight(s(56))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if key == '⌫':
            base = f"""
                background: white;
                color: {_RED_700};
                font-size: {font(20)}px;
                font-weight: 700;
                border: 1px solid {_RED_200};
            """
            hover = f"background: {_RED_50}; border: 1px solid #fca5a5;"
        elif key == 'CLR':
            base = f"""
                background: white;
                color: {_SLATE_500};
                font-size: {font(10)}px;
                font-weight: 800;
                letter-spacing: 1.5px;
                border: 1px solid {_SLATE_200};
            """
            hover = f"background: {_SLATE_50}; border: 1px solid {_SLATE_300}; color: {_SLATE_900};"
        else:
            base = f"""
                background: white;
                color: {_SLATE_900};
                font-size: {font(22)}px;
                font-weight: 700;
                border: 1px solid {_SLATE_200};
            """
            hover = f"background: {_SLATE_50}; border: 1px solid {_SLATE_300};"
        btn.setStyleSheet(f"""
            QPushButton {{ {base} border-radius: {s(10)}px; outline: none; }}
            QPushButton:hover {{ {hover} }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        btn.clicked.connect(lambda _, k=key: self._on_numpad_key(k))
        return btn

    def _on_numpad_key(self, key):
        if self._numpad_mode == "qty":
            cur = self.numpad_display.text()
            if cur == "—":
                cur = ""
            if key == '⌫':
                new = cur[:-1]
            elif key == 'CLR':
                new = ''
            else:
                new = cur + key
            self.numpad_display.setText(new or "—")
            if new and self._active_qty_item:
                self.update_qty_absolute(self._active_qty_item, new)
        else:
            cur = self.ticket_input.text()
            if key == '⌫':
                new = cur[:-1]
            elif key == 'CLR':
                new = ''
            else:
                if len(cur) >= 6:
                    return
                new = cur + key
            self.ticket_input.setText(new)
            self.numpad_display.setText(new or "—")

    # ─────────────────────────────────────────
    #  INLINE KEYBOARD — elite
    # ─────────────────────────────────────────
    def _build_keyboard_panel(self):
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {_SLATE_50};"
            f" border-top: 1px solid {_SLATE_200}; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(s(14), s(12), s(14), s(14))
        layout.setSpacing(s(6))

        top = QHBoxLayout()
        top.setSpacing(s(10))
        self.kb_display = QLabel("Izoh...")
        self.kb_display.setFixedHeight(s(42))
        self.kb_display.setFrameShape(QFrame.Shape.NoFrame)
        self.kb_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        kb_font = QFont()
        kb_font.setPixelSize(font(14))
        kb_font.setWeight(QFont.Weight.DemiBold)
        self.kb_display.setFont(kb_font)
        self.kb_display.setStyleSheet(
            f"color: {_SLATE_700}; background: white;"
            f" border: 1px solid {_SLATE_200}; border-radius: {s(10)}px;"
            f" padding: 0 {s(14)}px; outline: none;"
        )
        kb_close = QPushButton("✕")
        kb_close.setFixedSize(s(42), s(42))
        kb_close.setCursor(Qt.CursorShape.PointingHandCursor)
        kb_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        kb_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_SLATE_400};
                font-weight: 700;
                font-size: {font(14)}px;
                border-radius: {s(10)}px;
                border: 1px solid {_SLATE_200};
                outline: none;
            }}
            QPushButton:hover {{
                background: white;
                color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        kb_close.clicked.connect(self._close_panels)
        top.addWidget(self.kb_display, stretch=1)
        top.addWidget(kb_close)
        layout.addLayout(top)

        rows = [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['A','S','D','F','G','H','J','K','L','CLR'],
            ['Z','X','C','V','B','N','M','SPACE'],
        ]
        for row_keys in rows:
            row = QHBoxLayout()
            row.setSpacing(s(5))
            for k in row_keys:
                row.addWidget(self._make_kb_key(k))
            layout.addLayout(row)

        return panel

    def _make_kb_key(self, key):
        label = 'PROBEL' if key == 'SPACE' else ('TOZALASH' if key == 'CLR' else key)
        btn = QPushButton(label)
        btn.setFixedHeight(s(44))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        if key == '⌫':
            base = f"""
                background: white;
                color: {_RED_700};
                font-size: {font(16)}px;
                font-weight: 700;
                border: 1px solid {_RED_200};
            """
            hover = f"background: {_RED_50}; border: 1px solid #fca5a5;"
        elif key == 'CLR':
            base = f"""
                background: white;
                color: {_SLATE_500};
                font-size: {font(9)}px;
                font-weight: 800;
                letter-spacing: 1.5px;
                border: 1px solid {_SLATE_200};
            """
            hover = f"background: {_SLATE_50}; border: 1px solid {_SLATE_300}; color: {_SLATE_900};"
        elif key == 'SPACE':
            base = f"""
                background: white;
                color: {_SLATE_700};
                font-size: {font(10)}px;
                font-weight: 800;
                letter-spacing: 2px;
                border: 1px solid {_SLATE_200};
            """
            hover = f"background: {_SLATE_50}; border: 1px solid {_SLATE_300}; color: {_SLATE_900};"
            btn.setMinimumWidth(s(140))
        elif key.isdigit():
            base = f"""
                background: white;
                color: {_SLATE_900};
                font-size: {font(15)}px;
                font-weight: 700;
                border: 1px solid {_SLATE_200};
            """
            hover = f"background: {_SLATE_50}; border: 1px solid {_SLATE_300};"
        else:
            base = f"""
                background: white;
                color: {_SLATE_900};
                font-size: {font(13)}px;
                font-weight: 600;
                border: 1px solid {_SLATE_200};
            """
            hover = f"background: {_SLATE_50}; border: 1px solid {_SLATE_300};"
        btn.setStyleSheet(f"""
            QPushButton {{ {base} border-radius: {s(8)}px; outline: none; }}
            QPushButton:hover {{ {hover} }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """)
        btn.clicked.connect(lambda _, k=key: self._on_kb_key(k))
        return btn

    def _on_kb_key(self, key):
        cur = self.comment_input.text()
        if key == '⌫':
            new = cur[:-1]
        elif key == 'CLR':
            new = ''
        elif key == 'SPACE':
            new = cur + ' '
        else:
            new = cur + key
        self.comment_input.setText(new)
        self.kb_display.setText(new or "Izoh...")

    # ─────────────────────────────────────────
    #  Fizik klaviatura sinxronlash
    # ─────────────────────────────────────────
    def _on_ticket_text_changed(self, text):
        """Fizik klaviatura bilan yozilganda numpad display ni yangilash."""
        if self.numpad_panel.isVisible() and self._numpad_mode == "ticket":
            self.numpad_display.setText(text or "—")

    def _on_comment_text_changed(self, text):
        """Fizik klaviatura bilan yozilganda keyboard display ni yangilash."""
        if self.keyboard_panel.isVisible():
            self.kb_display.setText(text or "Izoh...")

    # ─────────────────────────────────────────
    #  Panel open / close
    # ─────────────────────────────────────────
    def _open_ticket_numpad(self, event):
        if not self.ticket_input.isEnabled():
            return
        self.keyboard_panel.setVisible(False)
        self._numpad_mode = "ticket"
        self._active_qty_item = None
        self.numpad_display.setText(self.ticket_input.text() or "—")
        self.numpad_panel.setVisible(True)

    def _open_comment_keyboard(self, event):
        self.numpad_panel.setVisible(False)
        self.kb_display.setText(self.comment_input.text() or "Izoh...")
        self.keyboard_panel.setVisible(True)

    def _close_panels(self):
        self._numpad_mode = "ticket"
        self._active_qty_item = None
        self.numpad_panel.setVisible(False)
        self.keyboard_panel.setVisible(False)

    # ─────────────────────────────────────────
    #  Styles
    # ─────────────────────────────────────────
    @staticmethod
    def _order_type_style(is_active: bool) -> str:
        _r = s(10)
        _fs = font(15)
        if is_active:
            return f"""
                QPushButton {{
                    background: {_SLATE_900};
                    color: white;
                    border: 1px solid {_SLATE_900};
                    border-radius: {_r}px;
                    font-weight: 700;
                    font-size: {_fs}px;
                    letter-spacing: 0.3px;
                }}
                QPushButton:hover {{ background: {_SLATE_800}; border-color: {_SLATE_800}; }}
            """
        return f"""
            QPushButton {{
                background: white; color: {_SLATE_700};
                border: 1px solid {_SLATE_200};
                border-radius: {_r}px; font-weight: 600; font-size: {_fs}px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{
                background: {_SLATE_50}; color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
            QPushButton:pressed {{ background: {_SLATE_100}; }}
        """

    @staticmethod
    def _table_btn_style(selected: bool) -> str:
        if selected:
            return f"""
                QPushButton {{
                    padding: {s(10)}px {s(14)}px; font-size: {font(15)}px;
                    font-weight: 700; border-radius: {s(10)}px;
                    background: #fff7ed; color: {_GOLD_DEEP};
                    border: 1px solid {_GOLD};
                    text-align: left;
                }}
                QPushButton:hover {{ background: #ffedd5; border-color: {_GOLD_DEEP}; }}
            """
        return f"""
            QPushButton {{
                padding: {s(10)}px {s(14)}px; font-size: {font(15)}px;
                font-weight: 600; border-radius: {s(10)}px;
                background: white; color: {_SLATE_500};
                border: 1px solid {_SLATE_200};
                text-align: left;
            }}
            QPushButton:hover {{
                background: {_SLATE_50}; color: {_SLATE_900};
                border-color: {_SLATE_300};
            }}
        """

    @staticmethod
    def _input_style() -> str:
        return f"""
            QLineEdit, QComboBox {{
                padding: {s(10)}px {s(14)}px;
                font-size: {font(15)}px;
                font-weight: 600;
                border: 1px solid {_SLATE_200};
                border-radius: {s(10)}px;
                background: white;
                color: {_SLATE_900};
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {_GOLD};
                background: white;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox::down-arrow {{ width: {s(14)}px; height: {s(14)}px; }}
        """

    # ─────────────────────────────────────────
    #  Business logic
    # ─────────────────────────────────────────
    def apply_settings(self, show_comment=None, show_ticket=None,
                       show_customer=None, enabled_order_types=None):
        """Config o'zgarganda yoki startup da visibility qo'llash."""
        cfg = load_config()
        if show_comment is None:
            show_comment = bool(cfg.get("show_comment", 1))
        if show_ticket is None:
            show_ticket = bool(cfg.get("show_ticket", 1))
        if show_customer is None:
            show_customer = bool(cfg.get("show_customer", 1))
        if enabled_order_types is None:
            enabled_order_types = cfg.get("enabled_order_types") or ORDER_TYPES

        self._customer_container.setVisible(show_customer)
        self._comment_container.setVisible(show_comment)
        self._show_ticket_setting = show_ticket  # set_order_type ishlatadi

        # Buyurtma turi tugmalari
        for t, btn in self.order_type_buttons.items():
            btn.setVisible(t in enabled_order_types)

        # Faol order type enabled_order_types ichida bo'lishi shart
        if self.current_order_type not in enabled_order_types and enabled_order_types:
            self.set_order_type(enabled_order_types[0])
        else:
            # Stiker/Stol container visibility ni hozirgi order_type bo'yicha yangilash
            self.set_order_type(self.current_order_type)

    def set_order_type(self, order_type: str):
        self.current_order_type = order_type
        for t, btn in self.order_type_buttons.items():
            active = t == order_type
            btn.setChecked(active)
            btn.setStyleSheet(self._order_type_style(active))

        cfg = load_config()
        order_number_type = cfg.get("order_number_type", ORDER_NUMBER_TYPE_STICKER)
        show_ticket_cfg = getattr(self, "_show_ticket_setting",
                                  bool(cfg.get("show_ticket", 1)))

        # Stol rejimi: Stol tugmasi faqat Shu yerda uchun, Saboy stolsiz (TZ 4.1.1)
        if order_number_type == ORDER_NUMBER_TYPE_TABLE:
            needs_table = order_type in TABLE_ORDER_TYPES
            self._ticket_container.setVisible(False)
            self._table_container.setVisible(needs_table and show_ticket_cfg)
            # Stol rejimida sticker input tozalanadi
            self.ticket_input.clear()
        else:
            # Stiker rejimi (default)
            needs_ticket = order_type in TICKET_ORDER_TYPES
            self._ticket_container.setVisible(show_ticket_cfg)
            self._table_container.setVisible(False)
            self.ticket_input.setEnabled(needs_ticket)
            if not needs_ticket:
                self.ticket_input.clear()
                self.ticket_input.setStyleSheet(self._input_style() + "background-color: #f3f4f6;")
                self.numpad_panel.setVisible(False)
            else:
                self.ticket_input.setStyleSheet(self._input_style() + "border: 2px solid #3b82f6;")

    # ── Role boshqaruvi (TZ 4.3) ─────────────
    def set_role(self, role: str):
        """Ofitsant rolida 'TO'LOV QILISH' yashirin, faqat 'Saqlash' ko'rinadi."""
        self._role = role or "Kassir"
        if self._role == "Ofitsant":
            self.checkout_btn.setVisible(False)
        else:
            self.checkout_btn.setVisible(True)

    # ── Stol tanlangach (TablePickerDialog dan) ─────
    def set_selected_table(self, table: dict | None):
        self.selected_table = table
        if table:
            room = table.get("room", "")
            seats = table.get("seats", 0)
            label = f"{room} / " if room else ""
            seats_txt = f"  ({seats}o'rin)" if seats else ""
            self.table_button.setText(f"🪑  {label}{table['name']}{seats_txt}")
            self.table_button.setStyleSheet(self._table_btn_style(True))
        else:
            self.table_button.setText("Stol tanlash...")
            self.table_button.setStyleSheet(self._table_btn_style(False))

    def load_customers(self):
        cfg = load_config()
        if not cfg.get("show_customer", 1):
            return
        try:
            cfg = load_config()
            default_customer = cfg.get("default_customer", "") or ""

            self.customer_combo.clear()
            customers = []
            if default_customer:
                customers.append(default_customer)
            customers.extend([
                c.name for c in Customer.select()
                if c.name not in customers
            ])
            self.customer_combo.addItems(customers)
            # Default customerni tanlash
            idx = self.customer_combo.findText(default_customer)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)
        except Exception as e:
            logger.debug("Mijozlar yuklanmadi: %s", e)

    def add_item(self, item_code: str, item_name: str, price: float, currency: str):
        if item_code in self.items:
            self.items[item_code]["qty"] = int(self.items[item_code]["qty"] + 1)
        else:
            self.items[item_code] = {"name": item_name, "price": price, "qty": 1, "currency": currency}
        self.refresh_table()

    def update_qty(self, item_code: str, change: int):
        if item_code in self.items:
            self.items[item_code]["qty"] = int(self.items[item_code]["qty"] + change)
            if self.items[item_code]["qty"] <= 0:
                del self.items[item_code]
            self.refresh_table()

    def update_qty_absolute(self, item_code: str, new_qty_str: str):
        try:
            new_qty = int(float(new_qty_str))
            if new_qty > 0:
                self.items[item_code]["qty"] = new_qty
            else:
                del self.items[item_code]
            self.refresh_table()
        except (ValueError, KeyError):
            pass

    def refresh_table(self):
        self.table.setRowCount(0)
        total_amount = 0.0
        currency = "UZS"

        _btn_sz = s(38)
        _qty_w = s(56)
        _qty_h = s(38)
        _r = s(8)

        for row_idx, (code, data) in enumerate(self.items.items()):
            self.table.insertRow(row_idx)
            self.table.setRowHeight(row_idx, s(76))

            name_item = QTableWidgetItem(data["name"])
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            f = name_item.font()
            f.setWeight(800)
            f.setPointSize(font(16))
            name_item.setFont(f)
            self.table.setItem(row_idx, 0, name_item)

            qty_widget = QWidget()
            qty_widget.setStyleSheet("background: transparent;")
            qty_layout = QHBoxLayout(qty_widget)
            qty_layout.setContentsMargins(s(8), s(4), s(8), s(4))
            qty_layout.setSpacing(0)
            qty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            btn_minus = QPushButton("−")
            btn_minus.setFixedSize(_btn_sz, _btn_sz)
            btn_minus.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_minus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn_minus.setStyleSheet(f"""
                QPushButton {{
                    font-size: {font(20)}px; font-weight: 700;
                    color: {_RED_700}; background: white;
                    border: 1px solid {_RED_200};
                    border-top-left-radius: {_r}px;
                    border-bottom-left-radius: {_r}px;
                    border-top-right-radius: 0px;
                    border-bottom-right-radius: 0px;
                    outline: none;
                }}
                QPushButton:hover {{ background: {_RED_50}; border-color: #fca5a5; }}
                QPushButton:pressed {{ background: #fee2e2; }}
            """)
            btn_minus.clicked.connect(lambda checked, c=code: self.update_qty(c, -1))

            qty_label = QtyLabel(str(int(data["qty"])))
            qty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_label.setFixedSize(_qty_w, _qty_h)
            qty_label.setFrameShape(QFrame.Shape.NoFrame)
            qty_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            ql_font = QFont()
            ql_font.setPixelSize(font(18))
            ql_font.setWeight(QFont.Weight.Black)
            qty_label.setFont(ql_font)
            qty_label.setStyleSheet(
                f"color: {_SLATE_900}; background: white;"
                f" border-top: 1px solid {_SLATE_200};"
                f" border-bottom: 1px solid {_SLATE_200};"
                f" outline: none; padding: 0; margin: 0;"
            )
            qty_label.clicked.connect(
                lambda c=code, q=str(int(data["qty"])): self._open_qty_numpad(c, q)
            )

            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(_btn_sz, _btn_sz)
            btn_plus.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn_plus.setStyleSheet(f"""
                QPushButton {{
                    font-size: {font(20)}px; font-weight: 700;
                    color: {_EMERALD_700}; background: white;
                    border: 1px solid #a7f3d0;
                    border-top-right-radius: {_r}px;
                    border-bottom-right-radius: {_r}px;
                    border-top-left-radius: 0px;
                    border-bottom-left-radius: 0px;
                    outline: none;
                }}
                QPushButton:hover {{ background: #ecfdf5; border-color: #6ee7b7; }}
                QPushButton:pressed {{ background: #d1fae5; }}
            """)
            btn_plus.clicked.connect(lambda checked, c=code: self.update_qty(c, 1))

            qty_layout.addWidget(btn_minus)
            qty_layout.addWidget(qty_label)
            qty_layout.addWidget(btn_plus)
            self.table.setCellWidget(row_idx, 1, qty_widget)

            price_item = QTableWidgetItem(f"{data['price']:,.0f}".replace(",", " "))
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            price_item.setForeground(QColor("#475569"))
            fp = price_item.font()
            fp.setWeight(700)
            fp.setPointSize(font(15))
            price_item.setFont(fp)
            self.table.setItem(row_idx, 2, price_item)

            amount = int(data["qty"]) * data["price"]
            total_amount += amount
            currency = data["currency"]

            amount_item = QTableWidgetItem(f"{amount:,.0f}".replace(",", " "))
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            f2 = amount_item.font()
            f2.setWeight(900)
            f2.setPointSize(font(16))
            amount_item.setFont(f2)
            amount_item.setForeground(QColor("#0f172a"))
            self.table.setItem(row_idx, 3, amount_item)

        self.total_label.setText(f"{total_amount:,.0f} {currency}".replace(",", " "))
        self.total_amount = total_amount

    def _open_qty_numpad(self, item_code: str, current_qty: str):
        self._active_qty_item = item_code
        self.keyboard_panel.setVisible(False)
        self.numpad_display.setText(current_qty or "—")
        self._numpad_mode = "qty"
        self.numpad_panel.setVisible(True)

    def clear_cart(self):
        self.items.clear()
        self.ticket_input.clear()
        self.comment_input.clear()
        self.set_selected_table(None)
        self._close_panels()
        self.refresh_table()

    def _build_order_data(self) -> dict | None:
        """Saqlash/Checkout uchun order_data ni hozirlash + validatsiya.

        Returns None — agar validatsiya muvaffaqiyatsiz bo'lsa (dialog ko'rsatilgan).
        """
        if not self.items:
            InfoDialog(self, "Xatolik", "Savat bo'sh!", kind="warning").exec()
            return None

        cfg = load_config()
        order_number_type = cfg.get("order_number_type", ORDER_NUMBER_TYPE_STICKER)
        ticket_number = self.ticket_input.text().strip()
        restaurant_table = ""
        restaurant_room = ""

        # Validatsiya — order_number_type ga qarab
        if order_number_type == ORDER_NUMBER_TYPE_TABLE:
            # Stol rejimi — faqat Shu yerda stol talab qiladi
            if self.current_order_type in TABLE_ORDER_TYPES:
                if not self.selected_table or not self.selected_table.get("name"):
                    InfoDialog(self, "Xatolik", "Stolni tanlang!", kind="warning").exec()
                    return None
                restaurant_table = self.selected_table["name"]
                restaurant_room = self.selected_table.get("room", "") or ""
            # Saboy va boshqalar — raqamsiz, OK
            ticket_number = ""
        else:
            # Stiker rejimi (default)
            if self.current_order_type in TICKET_ORDER_TYPES and not ticket_number:
                InfoDialog(self, "Xatolik", "Stiker raqamini kiriting!", kind="warning").exec()
                return None

        _default_cust = cfg.get("default_customer", "")
        selected_customer = self.customer_combo.currentText().strip() or _default_cust

        return {
            "items": [{"item_code": k, **v} for k, v in self.items.items()],
            "total_amount": self.total_amount,
            "order_type": self.current_order_type,
            "ticket_number": ticket_number,
            "restaurant_table": restaurant_table,
            "restaurant_room": restaurant_room,
            "customer": selected_customer,
            "comment": self.comment_input.text().strip(),
        }

    def handle_checkout(self):
        data = self._build_order_data()
        if data is not None:
            self.checkout_requested.emit(data)

    def handle_save(self):
        """To'lovsiz saqlash — TZ 4.2."""
        data = self._build_order_data()
        if data is not None:
            self.save_requested.emit(data)
