import requests
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QGridLayout, QLabel, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QThread, QObject
from PyQt6.QtGui import QPixmap, QImage
from database.models import Item, ItemPrice, db
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import ITEM_LOAD_LIMIT, ITEM_GRID_COLUMNS, IMAGE_TIMEOUT
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

class ItemButton(QPushButton):
    def __init__(self, item_code, item_name, price, currency, image_url=None, api=None, parent=None):
        super().__init__(parent)
        self.item_code = item_code
        self.item_name = item_name
        self.price = price
        self.currency = currency
        self.api = api

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        self.image_label = QLabel()
        self.image_label.setFixedSize(100, 100)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: #f3f4f6; border-radius: 8px;")
        self.image_label.setText("...")

        if image_url and api:
            self.loader = ImageLoader(image_url, api)
            self.loader.image_loaded.connect(self._set_pixmap)
            self.loader.start()
        else:
            self.image_label.setText("--")

        name_label = QLabel(item_name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1f2937; border: none;")

        price_str = f"{price:,.0f} {currency}".replace(",", " ")
        price_label = QLabel(price_str)
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #2563eb; border: none;")

        layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)
        layout.addWidget(price_label)

        self.setMinimumSize(QSize(180, 200))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            QPushButton { background-color: white; border: 1px solid #e5e7eb; border-radius: 12px; }
            QPushButton:hover { border: 2px solid #3b82f6; background-color: #f8fafc; }
        """)

    def _set_pixmap(self, pixmap):
        self.image_label.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.image_label.setText("")

class ItemBrowser(QWidget):
    item_selected = pyqtSignal(str, str, float, str)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.current_category = None
        self.kb = None
        self.init_ui()
        self.load_categories()
        self.load_items()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        # Categories
        self.category_scroll = QScrollArea()
        self.category_scroll.setFixedWidth(200)
        self.category_scroll.setWidgetResizable(True)
        self.category_container = QWidget()
        self.category_layout = QVBoxLayout(self.category_container)
        self.category_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.category_scroll.setWidget(self.category_container)
        main_layout.addWidget(self.category_scroll)

        # Items area
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Qidirish...")
        self.search_input.setReadOnly(True)
        self.search_input.mousePressEvent = self._open_search_keyboard
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet("padding: 10px; font-size: 18px; border-radius: 8px; border: 2px solid #d1d5db;")
        self.search_input.textChanged.connect(self.filter_items)
        right_layout.addWidget(self.search_input)

        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_container = QWidget()
        self.items_grid = QGridLayout(self.items_container)
        self.items_grid.setSpacing(10)
        self.items_scroll.setWidget(self.items_container)
        right_layout.addWidget(self.items_scroll)

        main_layout.addWidget(right_panel, stretch=1)

    def _open_search_keyboard(self, event):
        self.kb = TouchKeyboard(self, initial_text=self.search_input.text())
        self.kb.text_changed.connect(self.search_input.setText)
        self.kb.show()

    def load_categories(self):
        try:
            db.connect(reuse_if_open=True)
            cats = [r.item_group for row in Item.select(Item.item_group).distinct() if (r := row).item_group]
            self._add_cat_btn("Barchasi", True)
            for c in sorted(cats): self._add_cat_btn(c)
        finally: db.close()

    def _add_cat_btn(self, name, is_all=False):
        btn = QPushButton(name)
        btn.setCheckable(True)
        btn.setFixedHeight(50)
        btn.setChecked(is_all)
        btn.setStyleSheet("QPushButton { font-weight: bold; text-align: left; padding-left: 15px; border-radius: 5px; background: #f3f4f6; } QPushButton:checked { background: #3b82f6; color: white; }")
        btn.clicked.connect(lambda: self._on_cat_click(btn, name, is_all))
        self.category_layout.addWidget(btn)

    def _on_cat_click(self, btn, cat, is_all):
        for i in range(self.category_layout.count()):
            w = self.category_layout.itemAt(i).widget()
            if isinstance(w, QPushButton): w.setChecked(w == btn)
        self.current_category = None if is_all else cat
        self.load_items(self.search_input.text())

    def load_items(self, search=""):
        # Clear grid
        while self.items_grid.count():
            child = self.items_grid.takeAt(0)
            if child.widget(): child.widget().deleteLater()

        try:
            db.connect(reuse_if_open=True)
            query = Item.select()
            if self.current_category: query = query.where(Item.item_group == self.current_category)
            if search: query = query.where(Item.item_name.contains(search) | Item.item_code.contains(search))
            
            row, col = 0, 0
            for item in query.limit(ITEM_LOAD_LIMIT):
                price_rec = ItemPrice.get_or_none(ItemPrice.item_code == item.item_code)
                p = price_rec.price_list_rate if price_rec else 0
                cur = price_rec.currency if price_rec else "UZS"
                
                btn = ItemButton(item.item_code, item.item_name, p, cur, item.image, self.api)
                btn.clicked.connect(lambda checked, i=item, pr=p, c=cur: self.item_selected.emit(i.item_code, i.item_name, float(pr), c))
                self.items_grid.addWidget(btn, row, col)
                col += 1
                if col >= ITEM_GRID_COLUMNS: col = 0; row += 1
        finally: db.close()

    def filter_items(self, t): self.load_items(t)
