import requests
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QGridLayout, QLabel, QSizePolicy, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QThread, QObject, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPainterPath
from database.models import Item, ItemPrice, db
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import ITEM_LOAD_LIMIT, IMAGE_TIMEOUT
from ui.components.keyboard import TouchKeyboard

logger = get_logger(__name__)


class ImageLoader(QThread):
    """Rasmlarni fonda yuklash uchun maxsus thread"""
    image_loaded = pyqtSignal(QPixmap)

    def __init__(self, url, api):
        super().__init__()
        self.url = url
        self.api = api

    def run(self):
        try:
            full_url = self.url if self.url.startswith("http") else f"{self.api.url}{self.url}"
            response = self.api.session.get(full_url, timeout=IMAGE_TIMEOUT)
            if response.status_code == 200:
                image = QImage()
                if image.loadFromData(response.content):
                    pixmap = QPixmap.fromImage(image)
                    self.image_loaded.emit(pixmap)
        except Exception:
            pass


class ItemButton(QFrame):
    """Premium karta ko'rinishidagi mahsulot kartochkasi"""
    clicked = pyqtSignal()

    def __init__(self, item_code, item_name, price, currency, image_url=None, api=None, parent=None):
        super().__init__(parent)
        self.item_code = item_code
        self.item_name = item_name
        self.price = price
        self.currency = currency
        self.api = api
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_normal_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Rasm qismi (karta yuqori qismi) ---
        self.image_container = QWidget()
        self.image_container.setFixedHeight(130)
        self.image_container.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #f0f4ff, stop:1 #e8f0fe);
            border-top-left-radius: 14px;
            border-top-right-radius: 14px;
        """)

        img_inner = QVBoxLayout(self.image_container)
        img_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setFixedSize(90, 90)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("""
            background: rgba(255,255,255,0.7);
            border-radius: 10px;
            color: #94a3b8;
            font-size: 28px;
        """)
        self.image_label.setText("🍽")

        if image_url and api:
            self.loader = ImageLoader(image_url, api)
            self.loader.image_loaded.connect(self._set_pixmap)
            self.loader.start()

        img_inner.addWidget(self.image_label)
        layout.addWidget(self.image_container)

        # --- Ma'lumot qismi (karta pastki qismi) ---
        info_container = QWidget()
        info_container.setStyleSheet("""
            background: white;
            border-bottom-left-radius: 14px;
            border-bottom-right-radius: 14px;
        """)
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(10, 10, 10, 12)
        info_layout.setSpacing(6)

        # Mahsulot nomi
        # Uzun nomlarni qisqartirish
        display_name = item_name if len(item_name) <= 22 else item_name[:20] + "…"
        name_label = QLabel(display_name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setToolTip(item_name)
        name_label.setStyleSheet("""
            font-size: 13px;
            font-weight: 700;
            color: #1e293b;
            background: transparent;
            border: none;
            line-height: 1.3;
        """)
        name_label.setFixedHeight(36)

        # Narx badge
        price_str = f"{price:,.0f}".replace(",", " ") + f" {currency}"
        price_label = QLabel(price_str)
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price_label.setStyleSheet("""
            font-size: 13px;
            font-weight: 800;
            color: white;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #6366f1);
            border-radius: 8px;
            padding: 4px 8px;
            border: none;
        """)
        price_label.setFixedHeight(28)

        info_layout.addWidget(name_label)
        info_layout.addWidget(price_label)
        layout.addWidget(info_container)

    def _apply_normal_style(self):
        self.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 14px;
                border: 1.5px solid #e2e8f0;
            }
        """)

    def _apply_hover_style(self):
        self.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 14px;
                border: 2px solid #3b82f6;
            }
        """)

    def _apply_pressed_style(self):
        self.setStyleSheet("""
            QFrame {
                background: #f0f7ff;
                border-radius: 14px;
                border: 2px solid #2563eb;
            }
        """)

    def _set_pixmap(self, pixmap):
        scaled = pixmap.scaled(82, 82, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_pressed_style()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_normal_style()
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ItemBrowser(QWidget):
    item_selected = pyqtSignal(str, str, float, str)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.current_category = None
        self.kb = None
        self._last_columns = 0
        self._caps = False
        self._letter_buttons = []
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._on_resize_done)
        self.init_ui()
        self.load_categories()
        self.load_items()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Kategoriyalar paneli ---
        cat_frame = QFrame()
        cat_frame.setFixedWidth(120)
        cat_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: none;
                border-right: 1px solid #e2e8f0;
            }
        """)
        cat_outer = QVBoxLayout(cat_frame)
        cat_outer.setContentsMargins(0, 8, 0, 8)
        cat_outer.setSpacing(4)

        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.category_container = QWidget()
        self.category_container.setStyleSheet("background: transparent;")
        self.category_layout = QVBoxLayout(self.category_container)
        self.category_layout.setContentsMargins(6, 4, 6, 4)
        self.category_layout.setSpacing(4)
        self.category_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.category_scroll.setWidget(self.category_container)
        cat_outer.addWidget(self.category_scroll)

        main_layout.addWidget(cat_frame)

        # --- O'ng panel: qidiruv + grid + keyboard ---
        right_panel = QWidget()
        right_panel.setStyleSheet("background: #f8fafc;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 10, 12, 0)
        right_layout.setSpacing(10)

        # Qidiruv input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍  Mahsulot qidirish...")
        self.search_input.setReadOnly(True)
        self.search_input.mousePressEvent = self._open_search_keyboard
        self.search_input.setFixedHeight(46)
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 10px 16px;
                font-size: 15px;
                border-radius: 10px;
                border: 1.5px solid #e2e8f0;
                background: white;
                color: #334155;
            }
        """)
        self.search_input.textChanged.connect(self.filter_items)
        right_layout.addWidget(self.search_input)

        # Mahsulotlar gridi
        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.items_container = QWidget()
        self.items_container.setStyleSheet("background: transparent;")

        outer_layout = QVBoxLayout(self.items_container)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(0)

        self.items_grid = QGridLayout()
        self.items_grid.setSpacing(12)
        self.items_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        outer_layout.addLayout(self.items_grid)
        outer_layout.addStretch()

        self.items_scroll.setWidget(self.items_container)
        right_layout.addWidget(self.items_scroll, stretch=1)

        # --- Inline Keyboard Panel (pastdan) ---
        self.keyboard_panel = self._build_keyboard_panel()
        self.keyboard_panel.setVisible(False)
        right_layout.addWidget(self.keyboard_panel)

        main_layout.addWidget(right_panel, stretch=1)

    def _build_keyboard_panel(self):
        """Pastdan chiqadigan inline klaviatura paneli"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: #f1f5f9;
                border-top: 2px solid #e2e8f0;
                border-radius: 0px;
            }
        """)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 10)
        panel_layout.setSpacing(6)

        # Yuqori qator: yozilgan matn + yopish tugmasi
        top_row = QHBoxLayout()

        self.kb_display = QLabel("Qidiruv...")
        self.kb_display.setStyleSheet("""
            font-size: 16px;
            font-weight: 600;
            color: #334155;
            background: white;
            border: 1.5px solid #3b82f6;
            border-radius: 8px;
            padding: 6px 12px;
        """)
        self.kb_display.setFixedHeight(40)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(40, 40)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #ef4444;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover { background: #dc2626; }
        """)
        close_btn.clicked.connect(self._close_keyboard)

        top_row.addWidget(self.kb_display, stretch=1)
        top_row.addWidget(close_btn)
        panel_layout.addLayout(top_row)

        # Klaviatura qatorlari
        self._letter_buttons = []
        rows = [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['CAPS','A','S','D','F','G','H','J','K','L','CLR'],
            ['Z','X','C','V','B','N','M',' SPACE '],
        ]
        for row_keys in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(5)
            for key in row_keys:
                btn = self._make_key(key)
                row_layout.addWidget(btn)
            panel_layout.addLayout(row_layout)

        return panel

    def _make_key(self, key):
        label = key.strip()
        if label == 'SPACE': label = '␣'
        elif label == 'CLR': label = 'TOZALASH'
        elif label == 'CAPS': label = '⇧ Aa'

        btn = QPushButton(label)
        btn.setFixedHeight(44)

        if key.strip() == '⌫':
            style = "background:#fee2e2; color:#ef4444; font-size:18px; font-weight:bold;"
        elif key.strip() == 'CLR':
            style = "background:#fff7ed; color:#ea580c; font-size:11px; font-weight:bold;"
        elif key.strip() == 'CAPS':
            style = "background:#e0e7ff; color:#4338ca; font-size:13px; font-weight:bold;"
        elif 'SPACE' in key:
            style = "background:#eff6ff; color:#3b82f6; font-size:14px; font-weight:bold;"
            btn.setMinimumWidth(120)
        elif key.strip().isdigit():
            style = "background:#e0e7ff; color:#3730a3; font-size:16px; font-weight:bold;"
        else:
            style = "background:white; color:#1e293b; font-size:15px; font-weight:600;"

        btn.setStyleSheet(f"""
            QPushButton {{
                {style}
                border: 1px solid #e2e8f0;
                border-radius: 7px;
            }}
            QPushButton:pressed {{ background: #dbeafe; }}
        """)
        btn.clicked.connect(lambda _, k=key.strip(): self._on_key(k))

        if len(key.strip()) == 1 and key.strip().isalpha():
            self._letter_buttons.append(btn)

        return btn

    def _on_key(self, key):
        if key == 'CAPS':
            self._caps = not self._caps
            for btn in self._letter_buttons:
                txt = btn.text()
                btn.setText(txt.upper() if self._caps else txt.lower())
            return
        current = self.search_input.text()
        if key == '⌫':
            new_text = current[:-1]
        elif key == 'CLR':
            new_text = ''
        elif key == 'SPACE':
            new_text = current + ' '
        else:
            char = key.lower() if not self._caps else key.upper()
            new_text = current + char
        self.search_input.setText(new_text)
        # Display yangilash
        self.kb_display.setText(new_text if new_text else "Qidiruv...")

    def _open_search_keyboard(self, event):
        self.keyboard_panel.setVisible(True)
        self.kb_display.setText(self.search_input.text() or "Qidiruv...")

    def _close_keyboard(self):
        self.keyboard_panel.setVisible(False)

    def load_categories(self):
        try:
            db.connect(reuse_if_open=True)
            cats = [r.item_group for row in Item.select(Item.item_group).distinct() if (r := row).item_group]
            self._add_cat_btn("Barchasi", True)
            for c in sorted(cats):
                self._add_cat_btn(c)
        finally:
            db.close()

    def _add_cat_btn(self, name, is_all=False):
        btn = QPushButton(name)
        btn.setCheckable(True)
        btn.setChecked(is_all)
        btn.setFixedHeight(52)
        btn.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                font-weight: 700;
                text-align: center;
                padding: 6px 4px;
                border-radius: 10px;
                background: transparent;
                color: #64748b;
                border: none;
            }
            QPushButton:checked {
                background: #eff6ff;
                color: #2563eb;
            }
            QPushButton:hover:!checked {
                background: #f1f5f9;
                color: #334155;
            }
        """)
        btn.clicked.connect(lambda: self._on_cat_click(btn, name, is_all))
        self.category_layout.addWidget(btn)

    def _on_cat_click(self, btn, cat, is_all):
        for i in range(self.category_layout.count()):
            w = self.category_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(w == btn)
        self.current_category = None if is_all else cat
        self.load_items(self.search_input.text())

    def _calc_grid_columns(self):
        """Mavjud kenglikka qarab ustunlar sonini hisoblash"""
        available = self.items_scroll.viewport().width()
        if available <= 0:
            available = 600
        spacing = self.items_grid.spacing()
        min_card_width = 170
        cols = max(2, (available + spacing) // (min_card_width + spacing))
        return cols

    def load_items(self, search=""):
        # Gridni tozalash
        while self.items_grid.count():
            child = self.items_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        columns = self._calc_grid_columns()
        self._last_columns = columns

        try:
            db.connect(reuse_if_open=True)
            query = Item.select()
            if self.current_category:
                query = query.where(Item.item_group == self.current_category)
            if search:
                query = query.where(Item.item_name.contains(search) | Item.item_code.contains(search))

            row, col = 0, 0
            for item in query.limit(ITEM_LOAD_LIMIT):
                price_rec = ItemPrice.get_or_none(ItemPrice.item_code == item.item_code)
                p = price_rec.price_list_rate if price_rec else 0
                cur = price_rec.currency if price_rec else "UZS"

                card = ItemButton(item.item_code, item.item_name, p, cur, item.image, self.api)
                card.clicked.connect(
                    lambda i=item, pr=p, c=cur: self.item_selected.emit(i.item_code, i.item_name, float(pr), c)
                )
                self.items_grid.addWidget(card, row, col)
                col += 1
                if col >= columns:
                    col = 0
                    row += 1
        finally:
            db.close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize_done(self):
        new_cols = self._calc_grid_columns()
        if new_cols != self._last_columns:
            self.load_items(self.search_input.text())

    def filter_items(self, t):
        self.load_items(t)

