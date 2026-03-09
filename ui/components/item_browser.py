import requests
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QGridLayout, QLabel, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QPixmap, QImage
from database.models import Item, ItemPrice, db
from core.config import load_config
from core.logger import get_logger
from core.constants import ITEM_LOAD_LIMIT, ITEM_GRID_COLUMNS, IMAGE_TIMEOUT
from ui.components.keyboard import TouchKeyboard

logger = get_logger(__name__)


class ItemButton(QPushButton):
    def __init__(self, item_code, item_name, price, currency, image_url=None, parent=None):
        super().__init__(parent)
        self.item_code = item_code
        self.item_name = item_name
        self.price = price
        self.currency = currency

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        self.image_label = QLabel()
        self.image_label.setFixedSize(80, 80)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: none; background: transparent;")

        if image_url:
            self._load_image(image_url)
        else:
            self.image_label.setText("--")
            self.image_label.setStyleSheet("font-size: 30px; border: none;")

        name_label = QLabel(item_name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; border: none; color: #111827; background: transparent;"
        )

        price_str = f"{price:,.0f} {currency}".replace(",", " ")
        price_label = QLabel(price_str)
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price_label.setStyleSheet(
            "font-size: 12px; font-weight: bold; border: none; color: #2563eb; background: transparent;"
        )

        layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)
        layout.addWidget(price_label)

        self.setMinimumSize(QSize(160, 160))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            QPushButton {
                background-color: #ffffff; border: 2px solid #e5e7eb; border-radius: 12px;
            }
            QPushButton:hover { background-color: #f0fdf4; border: 2px solid #3b82f6; }
            QPushButton:pressed { background-color: #dbeafe; }
        """)

    def _load_image(self, url: str):
        config = load_config()
        base_url = config.get("url", "").rstrip("/")
        full_url = url if url.startswith("http") else f"{base_url}{url}"

        try:
            headers = {"Authorization": f"token {config.get('api_key')}:{config.get('api_secret')}"}
            response = requests.get(full_url, headers=headers, timeout=IMAGE_TIMEOUT)
            if response.status_code == 200:
                image = QImage()
                image.loadFromData(response.content)
                pixmap = QPixmap.fromImage(image)
                self.image_label.setPixmap(
                    pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
        except requests.exceptions.RequestException:
            self.image_label.setText("--")


class ItemBrowser(QWidget):
    item_selected = pyqtSignal(str, str, float, str)

    def __init__(self):
        super().__init__()
        self.current_category = None
        self.kb = None
        self.init_ui()
        self.load_categories()
        self.load_items()

    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(15)

        # Categories sidebar
        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setFixedWidth(220)
        self.category_scroll.setStyleSheet(
            "QScrollArea { border: none; border-right: 1px solid #e5e7eb; background: #ffffff; }"
        )

        self.category_container = QWidget()
        self.category_layout = QVBoxLayout(self.category_container)
        self.category_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.category_layout.setSpacing(8)
        self.category_layout.setContentsMargins(10, 10, 10, 10)
        self.category_scroll.setWidget(self.category_container)

        main_layout.addWidget(self.category_scroll)

        # Right area
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 10, 10, 10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tovarni izlash uchun bosing...")
        self.search_input.setReadOnly(True)
        self.search_input.mousePressEvent = self._open_search_keyboard
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 15px; font-size: 18px; border: 2px solid #d1d5db;
                border-radius: 10px; background-color: #f9fafb; color: #111827;
            }
            QLineEdit:focus { border: 2px solid #3b82f6; background-color: #ffffff; }
        """)
        self.search_input.textChanged.connect(self.filter_items)
        right_layout.addWidget(self.search_input)

        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.items_container = QWidget()
        self.items_grid = QGridLayout(self.items_container)
        self.items_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.items_grid.setSpacing(12)
        self.items_scroll.setWidget(self.items_container)

        right_layout.addWidget(self.items_scroll)
        main_layout.addLayout(right_layout, stretch=1)

        self.setLayout(main_layout)

    def _open_search_keyboard(self, event):
        if self.kb and self.kb.isVisible():
            self.kb.activateWindow()
            return

        self.kb = TouchKeyboard(self, initial_text=self.search_input.text(), title="Tovarni izlash")
        self.kb.text_changed.connect(self.search_input.setText)
        self.kb.text_confirmed.connect(self.search_input.setText)
        self.kb.show()

        geo = self.window().geometry()
        self.kb.move(geo.center().x() - self.kb.width() // 2, geo.bottom() - self.kb.height() - 50)

    def load_categories(self):
        for i in reversed(range(self.category_layout.count())):
            self.category_layout.itemAt(i).widget().setParent(None)

        try:
            db.connect(reuse_if_open=True)
            categories = [
                row.item_group
                for row in Item.select(Item.item_group).distinct()
                if row.item_group
            ]

            self._add_category_button("Barchasi", is_all=True)
            for cat in sorted(categories):
                self._add_category_button(cat)
        except Exception as e:
            logger.error("Kategoriyalarni yuklashda xatolik: %s", e)
        finally:
            if not db.is_closed():
                db.close()

    def _add_category_button(self, name: str, is_all: bool = False):
        btn = QPushButton(name)
        btn.setFixedHeight(55)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6; border: 1px solid transparent; font-size: 15px;
                font-weight: bold; color: #374151; text-align: left; padding-left: 20px; border-radius: 8px;
            }
            QPushButton:hover { background-color: #e5e7eb; }
            QPushButton:checked { background-color: #3b82f6; color: #ffffff; border: 1px solid #2563eb; }
        """)
        btn.setCheckable(True)
        if is_all:
            btn.setChecked(True)

        btn.clicked.connect(lambda checked, c=name, a=is_all: self._on_category_clicked(btn, c, a))
        self.category_layout.addWidget(btn)

    def _on_category_clicked(self, clicked_btn, category, is_all):
        for i in range(self.category_layout.count()):
            widget = self.category_layout.itemAt(i).widget()
            if isinstance(widget, QPushButton) and widget != clicked_btn:
                widget.setChecked(False)

        clicked_btn.setChecked(True)
        self.current_category = None if is_all else category
        self.load_items(self.search_input.text())

    def load_items(self, search_query: str = ""):
        for i in reversed(range(self.items_grid.count())):
            widget = self.items_grid.itemAt(i).widget()
            if widget:
                self.items_grid.removeWidget(widget)
                widget.setParent(None)

        try:
            db.connect(reuse_if_open=True)
            query = Item.select()

            if self.current_category:
                query = query.where(Item.item_group == self.current_category)

            if search_query:
                query = query.where(
                    (Item.item_name.contains(search_query))
                    | (Item.item_code.contains(search_query))
                    | (Item.barcode.contains(search_query))
                )

            query = query.limit(ITEM_LOAD_LIMIT)

            row, col = 0, 0
            for item_row in query.execute():
                price_record = ItemPrice.get_or_none(ItemPrice.item_code == item_row.item_code)
                price = price_record.price_list_rate if price_record else 0.0
                currency = price_record.currency if price_record else "UZS"

                btn = ItemButton(
                    item_row.item_code, item_row.item_name, price, currency, image_url=item_row.image
                )
                btn.clicked.connect(
                    lambda checked, c=item_row.item_code, n=item_row.item_name, p=price, cur=currency:
                    self.item_selected.emit(c, n, float(p), cur)
                )
                self.items_grid.addWidget(btn, row, col)

                col += 1
                if col >= ITEM_GRID_COLUMNS:
                    col = 0
                    row += 1
        except Exception as e:
            logger.error("Tovarlarni yuklashda xatolik: %s", e)
        finally:
            if not db.is_closed():
                db.close()

    def filter_items(self, text: str):
        self.load_items(text)

    def select_first_item(self):
        if self.items_grid.count() > 0:
            first_widget = self.items_grid.itemAt(0).widget()
            if isinstance(first_widget, ItemButton):
                self.item_selected.emit(
                    first_widget.item_code, first_widget.item_name, first_widget.price, first_widget.currency
                )
                self.search_input.clear()
