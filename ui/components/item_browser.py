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
from ui.scale import s, font

logger = get_logger(__name__)


class ImageLoader(QThread):
    """Rasmlarni fonda yuklash uchun maxsus thread.

    MUHIM: QPixmap faqat GUI threadda yaratilishi mumkin.
    Shuning uchun QImage yuboramiz, QPixmap ga main threadda aylantiriladi.
    """
    image_loaded = pyqtSignal(QImage)

    def __init__(self, url, api):
        super().__init__()
        self.url = url
        self.api = api

    def run(self):
        try:
            full_url = self.url if self.url.startswith("http") else f"{self.api.url}{self.url}"
            session = self.api._get_session()
            response = session.get(full_url, timeout=IMAGE_TIMEOUT)
            if response.status_code == 200:
                image = QImage()
                if image.loadFromData(response.content):
                    self.image_loaded.emit(image)
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

        # --- Rasm qismi ---
        self.image_container = QWidget()
        self.image_container.setFixedHeight(s(130))
        _r = s(14)
        self.image_container.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #f0f4ff, stop:1 #e8f0fe);
            border-top-left-radius: {_r}px;
            border-top-right-radius: {_r}px;
        """)

        img_inner = QVBoxLayout(self.image_container)
        img_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        _img = s(90)
        self.image_label = QLabel()
        self.image_label.setFixedSize(_img, _img)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(f"""
            background: rgba(255,255,255,0.7);
            border-radius: {s(10)}px;
            color: #94a3b8;
            font-size: {font(28)}px;
        """)
        self.image_label.setText("🍽")

        if image_url and api:
            self.loader = ImageLoader(image_url, api)
            self.loader.image_loaded.connect(self._set_pixmap)
            self.loader.start()

        img_inner.addWidget(self.image_label)
        layout.addWidget(self.image_container)

        # --- Ma'lumot qismi ---
        _r = s(14)
        info_container = QWidget()
        info_container.setStyleSheet(f"""
            background: white;
            border-bottom-left-radius: {_r}px;
            border-bottom-right-radius: {_r}px;
        """)
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(s(10), s(10), s(10), s(12))
        info_layout.setSpacing(s(6))

        display_name = item_name if len(item_name) <= 22 else item_name[:20] + "..."
        name_label = QLabel(display_name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setToolTip(item_name)
        name_label.setStyleSheet(f"""
            font-size: {font(13)}px;
            font-weight: 700;
            color: #1e293b;
            background: transparent;
            border: none;
            line-height: 1.3;
        """)
        name_label.setFixedHeight(s(36))

        price_str = f"{price:,.0f}".replace(",", " ") + f" {currency}"
        price_label = QLabel(price_str)
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price_label.setStyleSheet(f"""
            font-size: {font(13)}px;
            font-weight: 800;
            color: white;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #6366f1);
            border-radius: {s(8)}px;
            padding: {s(4)}px {s(8)}px;
            border: none;
        """)
        price_label.setFixedHeight(s(28))

        info_layout.addWidget(name_label)
        info_layout.addWidget(price_label)
        layout.addWidget(info_container)

    def _apply_normal_style(self):
        _r = s(14)
        self.setStyleSheet(f"""
            QFrame {{
                background: white;
                border-radius: {_r}px;
                border: 1.5px solid #e2e8f0;
            }}
        """)

    def _apply_hover_style(self):
        _r = s(14)
        self.setStyleSheet(f"""
            QFrame {{
                background: white;
                border-radius: {_r}px;
                border: 2px solid #3b82f6;
            }}
        """)

    def _apply_pressed_style(self):
        _r = s(14)
        self.setStyleSheet(f"""
            QFrame {{
                background: #f0f7ff;
                border-radius: {_r}px;
                border: 2px solid #2563eb;
            }}
        """)

    def _set_pixmap(self, image: QImage):
        """QImage ni main threadda QPixmap ga aylantirish va ko'rsatish."""
        try:
            _sz = s(82)
            pixmap = QPixmap.fromImage(image)
            scaled = pixmap.scaled(_sz, _sz, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled)
            self.image_label.setText("")
        except RuntimeError:
            pass  # Widget allaqachon o'chirilgan

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
        cat_frame.setFixedWidth(s(120))
        cat_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: none;
                border-right: 1px solid #e2e8f0;
            }
        """)
        cat_outer = QVBoxLayout(cat_frame)
        cat_outer.setContentsMargins(0, s(8), 0, s(8))
        cat_outer.setSpacing(s(4))

        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.category_container = QWidget()
        self.category_container.setStyleSheet("background: transparent;")
        self.category_layout = QVBoxLayout(self.category_container)
        self.category_layout.setContentsMargins(s(6), s(4), s(6), s(4))
        self.category_layout.setSpacing(s(4))
        self.category_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.category_scroll.setWidget(self.category_container)
        cat_outer.addWidget(self.category_scroll)

        main_layout.addWidget(cat_frame)

        # --- O'ng panel: qidiruv + grid + keyboard ---
        right_panel = QWidget()
        right_panel.setStyleSheet("background: #f8fafc;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(s(12), s(10), s(12), 0)
        right_layout.setSpacing(s(10))

        # Qidiruv input — fizik va ekrandagi klaviatura bilan ishlaydi
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Mahsulot qidirish...")
        self.search_input.mousePressEvent = self._open_search_keyboard
        self.search_input.setFixedHeight(s(46))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                padding: {s(10)}px {s(16)}px;
                font-size: {font(15)}px;
                border-radius: {s(10)}px;
                border: 1.5px solid #e2e8f0;
                background: white;
                color: #334155;
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        right_layout.addWidget(self.search_input)

        # Mahsulotlar gridi
        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.items_container = QWidget()
        self.items_container.setStyleSheet("background: transparent;")

        outer_layout = QVBoxLayout(self.items_container)
        outer_layout.setContentsMargins(s(4), s(4), s(4), s(4))
        outer_layout.setSpacing(0)

        self.items_grid = QGridLayout()
        self.items_grid.setSpacing(s(12))
        self.items_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        outer_layout.addLayout(self.items_grid)
        outer_layout.addStretch()

        self.items_scroll.setWidget(self.items_container)
        right_layout.addWidget(self.items_scroll, stretch=1)

        # --- Inline Keyboard Panel ---
        self.keyboard_panel = self._build_keyboard_panel()
        self.keyboard_panel.setVisible(False)
        right_layout.addWidget(self.keyboard_panel)

        main_layout.addWidget(right_panel, stretch=1)

    def _build_keyboard_panel(self):
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: #f1f5f9;
                border-top: 2px solid #e2e8f0;
                border-radius: 0px;
            }
        """)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(s(10), s(8), s(10), s(10))
        panel_layout.setSpacing(s(6))

        top_row = QHBoxLayout()

        self.kb_display = QLabel("Qidiruv...")
        self.kb_display.setStyleSheet(f"""
            font-size: {font(16)}px;
            font-weight: 600;
            color: #334155;
            background: white;
            border: 1.5px solid #3b82f6;
            border-radius: {s(8)}px;
            padding: {s(6)}px {s(12)}px;
        """)
        self.kb_display.setFixedHeight(s(40))

        _cb = s(40)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(_cb, _cb)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: #ef4444;
                color: white;
                font-weight: bold;
                font-size: {font(16)}px;
                border-radius: {s(8)}px;
                border: none;
            }}
            QPushButton:hover {{ background: #dc2626; }}
        """)
        close_btn.clicked.connect(self._close_keyboard)

        top_row.addWidget(self.kb_display, stretch=1)
        top_row.addWidget(close_btn)
        panel_layout.addLayout(top_row)

        self._letter_buttons = []
        rows = [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['CAPS','A','S','D','F','G','H','J','K','L','CLR'],
            ['Z','X','C','V','B','N','M',' SPACE '],
        ]
        for row_keys in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(s(5))
            for key in row_keys:
                btn = self._make_key(key)
                row_layout.addWidget(btn)
            panel_layout.addLayout(row_layout)

        return panel

    def _make_key(self, key):
        label = key.strip()
        if label == 'SPACE': label = 'PROBEL'
        elif label == 'CLR': label = 'TOZALASH'
        elif label == 'CAPS': label = '⇧ Aa'

        btn = QPushButton(label)
        btn.setFixedHeight(s(44))

        if key.strip() == '⌫':
            style = f"background:#fee2e2; color:#ef4444; font-size:{font(18)}px; font-weight:bold;"
        elif key.strip() == 'CLR':
            style = f"background:#fff7ed; color:#ea580c; font-size:{font(11)}px; font-weight:bold;"
        elif key.strip() == 'CAPS':
            style = f"background:#e0e7ff; color:#4338ca; font-size:{font(13)}px; font-weight:bold;"
        elif 'SPACE' in key:
            style = f"background:#eff6ff; color:#3b82f6; font-size:{font(14)}px; font-weight:bold;"
            btn.setMinimumWidth(s(120))
        elif key.strip().isdigit():
            style = f"background:#e0e7ff; color:#3730a3; font-size:{font(16)}px; font-weight:bold;"
        else:
            style = f"background:white; color:#1e293b; font-size:{font(15)}px; font-weight:600;"

        btn.setStyleSheet(f"""
            QPushButton {{
                {style}
                border: 1px solid #e2e8f0;
                border-radius: {s(7)}px;
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
        self.kb_display.setText(new_text if new_text else "Qidiruv...")

    def _on_search_text_changed(self, text):
        """Fizik klaviatura yoki ekrandagi keyboard — ikkalasi ham shu signalni ishlatadi."""
        if self.keyboard_panel.isVisible():
            self.kb_display.setText(text if text else "Qidiruv...")
        self.filter_items(text)

    def _open_search_keyboard(self, event):
        self.keyboard_panel.setVisible(True)
        self.kb_display.setText(self.search_input.text() or "Qidiruv...")
        self.search_input.setFocus()

    def _close_keyboard(self):
        self.keyboard_panel.setVisible(False)

    def load_categories(self):
        try:
            cats = [r.item_group for row in Item.select(Item.item_group).distinct() if (r := row).item_group]
            self._add_cat_btn("Barchasi", True)
            for c in sorted(cats):
                self._add_cat_btn(c)
        except Exception as e:
            logger.debug("Kategoriyalar yuklanmadi: %s", e)

    def _add_cat_btn(self, name, is_all=False):
        btn = QPushButton(name)
        btn.setCheckable(True)
        btn.setChecked(is_all)
        btn.setFixedHeight(s(52))
        btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {font(11)}px;
                font-weight: 700;
                text-align: center;
                padding: {s(6)}px {s(4)}px;
                border-radius: {s(10)}px;
                background: transparent;
                color: #64748b;
                border: none;
            }}
            QPushButton:checked {{
                background: #eff6ff;
                color: #2563eb;
            }}
            QPushButton:hover:!checked {{
                background: #f1f5f9;
                color: #334155;
            }}
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
        available = self.items_scroll.viewport().width()
        if available <= 0:
            available = s(600)
        spacing = self.items_grid.spacing()
        min_card_width = s(170)
        cols = max(2, (available + spacing) // (min_card_width + spacing))
        return cols

    def load_items(self, search=""):
        # Eski kartalarni xavfsiz tozalash — ImageLoader threadlarini to'xtatish
        while self.items_grid.count():
            child = self.items_grid.takeAt(0)
            widget = child.widget()
            if widget:
                # ImageLoader ishlayotgan bo'lsa — signal uzib, kutish
                if hasattr(widget, 'loader') and widget.loader.isRunning():
                    widget.loader.image_loaded.disconnect()
                    widget.loader.wait(500)
                widget.deleteLater()

        columns = self._calc_grid_columns()
        self._last_columns = columns

        try:
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
        except Exception as e:
            logger.error("Tovarlarni yuklashda xatolik: %s", e)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize_done(self):
        new_cols = self._calc_grid_columns()
        if new_cols != self._last_columns:
            self.load_items(self.search_input.text())

    def filter_items(self, t):
        self.load_items(t)
