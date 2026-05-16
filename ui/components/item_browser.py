import requests
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QThread, QObject, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QGridLayout, QLabel, QSizePolicy, QFrame,
    QScroller, QScrollerProperties, QDialog,
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPainterPath
from database.models import Item, ItemPrice, db
from core.api import FrappeAPI
from core.config import load_config, save_config
from core.logger import get_logger
from core.constants import ITEM_LOAD_LIMIT, IMAGE_TIMEOUT
from ui.components.keyboard import TouchKeyboard
from ui.components.loading import LoadingOverlay
from ui.scale import s, font

# Slot tartibi → rim raqami (kassir o'zi sozlagan tezkor itemlar uchun)
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI"}

logger = get_logger(__name__)


def _enable_touch_scroll(scroll_area: QScrollArea):
    """QScrollArea ga sensorli ekran uchun kinetic scroll qo'shish.
    Barmaq bilan surish (swipe) ishlaydi — tezlik bilan davom etadi."""
    scroller = QScroller.scroller(scroll_area.viewport())
    scroller.grabGesture(scroll_area.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance, 0.004)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.OvershootDragDistanceFactor, 0.1)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.OvershootScrollDistanceFactor, 0.1)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.85)
    scroller.setScrollerProperties(props)

    # Touch-friendly scrollbar — kattaroq
    scroll_area.setStyleSheet(scroll_area.styleSheet() + f"""
        QScrollBar:vertical {{
            width: {s(10)}px;
            background: transparent;
            border: none;
            margin: {s(4)}px 0;
        }}
        QScrollBar::handle:vertical {{
            background: #cbd5e1;
            border-radius: {s(5)}px;
            min-height: {s(40)}px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #94a3b8;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
    """)


class ImageLoader(QThread):
    """Rasmlarni fonda yuklash uchun maxsus thread.

    MUHIM: QPixmap faqat GUI threadda yaratilishi mumkin.
    Shuning uchun QImage yuboramiz, QPixmap ga main threadda aylantiriladi.

    _cache — class-level in-memory kesh. Bir marta yuklangan rasm qayta
    serverga so'rov yubormasdan darhol qaytariladi.
    """
    image_loaded = pyqtSignal(QImage)
    _cache: dict = {}   # url → QImage  (barcha instancelar uchun umumiy)

    def __init__(self, url, api):
        super().__init__()
        self.url = url
        self.api = api

    def run(self):
        # Keshda bor — darhol qaytarish, server so'rovi yo'q
        cached = ImageLoader._cache.get(self.url)
        if cached is not None:
            if not cached.isNull():
                self.image_loaded.emit(cached)
            return
        try:
            full_url = self.url if self.url.startswith("http") else f"{self.api.url}{self.url}"
            session = self.api._get_session()
            response = session.get(full_url, timeout=IMAGE_TIMEOUT)
            if response.status_code == 200:
                image = QImage()
                if image.loadFromData(response.content):
                    ImageLoader._cache[self.url] = image   # keshga yozish
                    self.image_loaded.emit(image)
        except Exception:
            pass


class ItemButton(QFrame):
    """Kassir-friendly kartochka: KATTA nom + kichik narx."""
    clicked = pyqtSignal()

    def __init__(self, item_code, item_name, price, currency,
                 image_url=None, api=None, parent=None):
        super().__init__(parent)
        self.item_code = item_code
        self.item_name = item_name
        self.price = price
        self.currency = currency
        self.api = api
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Card balandligi — rasm olib tashlangan (eski 155+infor ≈ 240),
        # endi yarmiga yaqin
        self.setFixedHeight(s(130))
        self._apply_normal_style()

        # ── ASOSIY layout (vertikal) — nom markazda, narx pastda ──
        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(10), s(12), s(10), s(10))
        layout.setSpacing(s(6))
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Nom — KATTA, bold, markazda
        display_name = item_name if len(item_name) <= 30 else item_name[:28] + "…"
        self.name_label = QLabel(display_name)
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setToolTip(item_name)
        self.name_label.setStyleSheet(f"""
            font-size: {font(18)}px;
            font-weight: 800;
            color: #0f172a;
            background: transparent;
            border: none;
            line-height: 1.25;
            letter-spacing: 0.2px;
        """)

        # Narx — kichikroq, kulrang (asosiy diqqat tortmaydi)
        price_str = f"{price:,.0f}".replace(",", " ") + f" {currency}"
        self.price_label = QLabel(price_str)
        self.price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.price_label.setStyleSheet(f"""
            font-size: {font(12)}px;
            font-weight: 600;
            color: #64748b;
            background: transparent;
            border: none;
        """)

        layout.addStretch()
        layout.addWidget(self.name_label)
        layout.addWidget(self.price_label)
        layout.addStretch()

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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_pressed_style()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_normal_style()
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class QuickSlotButton(QFrame):
    """Tezkor sotuv slotini ifodalovchi tugma.

    Bo'sh holatda: rim raqami + "+ Tezkor" placeholder, bosilganda picker ochiladi.
    Sozlangan holatda: rim raqami badge + item nomi + narxi, bosilganda sotiladi.
    Sozlash uchun yuqori-o'ngda kichik ⚙ tugmasi joylashgan.
    """
    activated = pyqtSignal(str, str, float, str)   # item tanlangan (kassir bosgan)
    configure_requested = pyqtSignal(int)          # ⚙ bosildi (slot raqami)

    def __init__(self, slot_index: int, parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        self.item_code = None
        self.item_name = None
        self.price = 0.0
        self.currency = "UZS"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(s(58))
        self.setMinimumWidth(s(160))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style(filled=False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(8), s(6), s(40), s(6))
        layout.setSpacing(s(8))

        # Rim raqami badge (chap) — kattaroq, ko'rinarli
        self.badge = QLabel(ROMAN.get(slot_index, str(slot_index)))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedSize(s(34), s(46))
        self.badge.setStyleSheet(f"""
            font-size: {font(15)}px;
            font-weight: 900;
            color: #1d4ed8;
            background: #eff6ff;
            border: 1.5px solid #bfdbfe;
            border-radius: {s(8)}px;
            letter-spacing: 0.5px;
        """)
        layout.addWidget(self.badge)

        # Markaziy ustun — nom (yuqori) + narx (past)
        center_col = QVBoxLayout()
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(s(1))
        center_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.name_label = QLabel("Sozlash uchun bosing")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.name_label.setStyleSheet(f"""
            font-size: {font(12)}px;
            font-weight: 700;
            color: #94a3b8;
            background: transparent;
            border: none;
        """)

        self.price_label = QLabel("")
        self.price_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.price_label.setStyleSheet(f"""
            font-size: {font(10)}px;
            font-weight: 600;
            color: #64748b;
            background: transparent;
            border: none;
        """)
        self.price_label.setVisible(False)

        center_col.addWidget(self.name_label)
        center_col.addWidget(self.price_label)
        layout.addLayout(center_col, 1)

        # ⚙ sozlash tugmasi — o'ng tomonda balandlikka teng vertikal qism
        # (overlay sifatida joylashtiriladi — resizeEvent da pozitsiyalanadi)
        self.cfg_btn = QPushButton("⚙", self)
        self.cfg_btn.setFixedSize(s(30), s(46))
        self.cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cfg_btn.setToolTip("Tezkor itemni sozlash")
        self.cfg_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {font(14)}px;
                color: #475569;
                background: #f1f5f9;
                border: 1px solid #e2e8f0;
                border-radius: {s(6)}px;
            }}
            QPushButton:hover {{ background: #e0e7ff; color: #1d4ed8; border-color: #c7d2fe; }}
            QPushButton:pressed {{ background: #c7d2fe; }}
        """)
        self.cfg_btn.clicked.connect(lambda: self.configure_requested.emit(self.slot_index))

    def _apply_style(self, filled: bool):
        _r = s(10)
        if filled:
            self.setStyleSheet(f"""
                QFrame {{
                    background: white;
                    border: 1.5px solid #3b82f6;
                    border-radius: {_r}px;
                }}
                QFrame:hover {{ background: #f0f7ff; }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background: #f8fafc;
                    border: 1.5px dashed #cbd5e1;
                    border-radius: {_r}px;
                }}
                QFrame:hover {{ background: #f1f5f9; }}
            """)

    def set_item(self, item_code, item_name, price, currency):
        self.item_code = item_code
        self.item_name = item_name
        self.price = float(price or 0)
        self.currency = currency or "UZS"
        display = item_name if len(item_name) <= 16 else item_name[:15] + "…"
        self.name_label.setText(display)
        self.name_label.setToolTip(item_name)
        self.name_label.setStyleSheet(f"""
            font-size: {font(13)}px;
            font-weight: 800;
            color: #0f172a;
            background: transparent;
            border: none;
        """)
        price_str = f"{self.price:,.0f}".replace(",", " ") + f" {self.currency}"
        self.price_label.setText(price_str)
        self.price_label.setVisible(True)
        self._apply_style(filled=True)

    def clear_item(self):
        self.item_code = None
        self.item_name = None
        self.price = 0.0
        self.name_label.setText("Sozlash uchun bosing")
        self.name_label.setToolTip("")
        self.name_label.setStyleSheet(f"""
            font-size: {font(12)}px;
            font-weight: 700;
            color: #94a3b8;
            background: transparent;
            border: none;
        """)
        self.price_label.setText("")
        self.price_label.setVisible(False)
        self._apply_style(filled=False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # ⚙ tugmasini o'ng chetga, vertikal markazlangan holatda joylash
        self.cfg_btn.move(self.width() - self.cfg_btn.width() - s(5),
                          (self.height() - self.cfg_btn.height()) // 2)
        self.cfg_btn.raise_()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # ⚙ bosilsa, alohida ishlov beriladi — markaziy hudud uchun:
        if self.cfg_btn.geometry().contains(event.pos()):
            return
        if self.item_code:
            self.activated.emit(self.item_code, self.item_name, self.price, self.currency)
        else:
            self.configure_requested.emit(self.slot_index)


class QuickItemPickerDialog(QDialog):
    """Tezkor slot uchun item tanlash dialogi.

    - Yuqorida qidiruv inputi
    - Pastda DB dan kelgan itemlar ro'yxati (tap → tanlash)
    - "O'chirish" tugmasi — slotni bo'shatish (None qaytaradi)
    """
    def __init__(self, parent, slot_index: int, has_current: bool):
        super().__init__(parent)
        self.selected = None   # dict yoki "CLEAR"
        self.setWindowTitle(f"Tezkor slot {ROMAN.get(slot_index, slot_index)} — item tanlash")
        self.setMinimumSize(s(520), s(560))
        self.setStyleSheet("background: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(s(18), s(16), s(18), s(16))
        layout.setSpacing(s(10))

        title = QLabel(f"Tezkor sotuv slot — {ROMAN.get(slot_index, slot_index)}")
        title.setStyleSheet(f"font-size:{font(15)}px; font-weight:800; color:#0f172a;")
        layout.addWidget(title)

        hint = QLabel("Tez-tez sotiladigan mahsulotni tanlang. Kassir bu tugmani bossa, item to'g'ridan-to'g'ri savatga qo'shiladi.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:{font(11)}px; color:#64748b;")
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Mahsulot nomini yozing...")
        self.search.setFixedHeight(s(42))
        self.search.setStyleSheet(f"""
            QLineEdit {{
                padding: {s(8)}px {s(14)}px;
                font-size: {font(13)}px;
                border-radius: {s(8)}px;
                border: 1.5px solid #e2e8f0;
                background: white;
                color: #334155;
            }}
            QLineEdit:focus {{ border: 1.5px solid #3b82f6; }}
        """)
        self.search.textChanged.connect(self._reload)
        layout.addWidget(self.search)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setStyleSheet("QScrollArea { border: 1px solid #e2e8f0; background: white; border-radius: 8px; }")
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(s(4), s(4), s(4), s(4))
        self.list_layout.setSpacing(s(4))
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_scroll.setWidget(self.list_container)
        layout.addWidget(self.list_scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(8))

        if has_current:
            clear_btn = QPushButton("Slotni bo'shatish")
            clear_btn.setFixedHeight(s(44))
            clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #fef2f2; color: #dc2626; font-weight: 700;
                    font-size: {font(12)}px;
                    border: 1.5px solid #fecaca; border-radius: {s(8)}px;
                    padding: 0 {s(14)}px;
                }}
                QPushButton:hover {{ background: #fee2e2; }}
            """)
            clear_btn.clicked.connect(self._on_clear)
            btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        cancel = QPushButton("Bekor qilish")
        cancel.setFixedHeight(s(44))
        cancel.setStyleSheet(f"""
            QPushButton {{
                background: #f1f5f9; color: #475569; font-weight: 700;
                font-size: {font(12)}px;
                border: 1.5px solid #e2e8f0; border-radius: {s(8)}px;
                padding: 0 {s(20)}px;
            }}
            QPushButton:hover {{ background: #e2e8f0; }}
        """)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        layout.addLayout(btn_row)
        self._reload("")

    def _reload(self, text=""):
        # Eskilarni tozalash
        while self.list_layout.count():
            it = self.list_layout.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

        try:
            query = Item.select()
            t = (text or "").strip()
            if t:
                query = query.where(Item.item_name.contains(t) | Item.item_code.contains(t))
            query = query.order_by(Item.item_name.asc()).limit(200)

            for it in query:
                price_rec = ItemPrice.get_or_none(ItemPrice.item_code == it.item_code)
                p = price_rec.price_list_rate if price_rec else 0
                cur = price_rec.currency if price_rec else "UZS"
                self.list_layout.addWidget(self._make_row(it.item_code, it.item_name, p, cur))
        except Exception as e:
            logger.error("Picker yuklashda xato: %s", e)

    def _make_row(self, item_code, item_name, price, currency):
        row = QPushButton()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setFixedHeight(s(48))
        price_str = f"{price:,.0f}".replace(",", " ") + f" {currency}"
        row.setText(f"{item_name}   •   {price_str}")
        row.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 0 {s(14)}px;
                font-size: {font(13)}px;
                font-weight: 600;
                color: #1e293b;
                background: white;
                border: 1px solid #e2e8f0;
                border-radius: {s(6)}px;
            }}
            QPushButton:hover {{ background: #eff6ff; border-color: #3b82f6; color: #1d4ed8; }}
        """)
        row.clicked.connect(lambda _, ic=item_code, n=item_name, pr=float(price), c=currency:
                            self._on_pick(ic, n, pr, c))
        return row

    def _on_pick(self, item_code, item_name, price, currency):
        self.selected = {
            "item_code": item_code,
            "item_name": item_name,
            "price": float(price),
            "currency": currency,
        }
        self.accept()

    def _on_clear(self):
        self.selected = "CLEAR"
        self.accept()


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
        # Loaderlar hali ishlayotganda o'chirishni kechiktirish uchun
        # (GC'dan himoya — "QThread destroyed while running" xatosini oldini olish)
        self._pending_delete: list = []
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

        # --- Kategoriyalar paneli (kassirga qulay — kengroq, yiriklashtirilgan) ---
        cat_frame = QFrame()
        cat_frame.setFixedWidth(s(170))
        cat_frame.setStyleSheet("""
            QFrame {
                background: #f8fafc;
                border: none;
                border-right: 1.5px solid #e2e8f0;
            }
        """)
        cat_outer = QVBoxLayout(cat_frame)
        cat_outer.setContentsMargins(0, s(10), 0, s(10))
        cat_outer.setSpacing(s(4))

        # Sarlavha
        cat_title = QLabel("KATEGORIYALAR")
        cat_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cat_title.setStyleSheet(f"""
            font-size: {font(11)}px;
            font-weight: 800;
            color: #475569;
            letter-spacing: 2px;
            padding: 0 {s(8)}px {s(10)}px {s(8)}px;
        """)
        cat_outer.addWidget(cat_title)

        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.category_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                width: {s(6)}px; background: transparent; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #cbd5e1; border-radius: {s(3)}px; min-height: {s(30)}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        self.category_container = QWidget()
        self.category_container.setStyleSheet("background: transparent;")
        self.category_layout = QVBoxLayout(self.category_container)
        self.category_layout.setContentsMargins(s(6), s(4), s(6), s(4))
        self.category_layout.setSpacing(s(4))
        self.category_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.category_scroll.setWidget(self.category_container)
        cat_outer.addWidget(self.category_scroll)
        # Touch scroll — kategoriyalar
        _enable_touch_scroll(self.category_scroll)

        main_layout.addWidget(cat_frame)

        # --- O'ng panel: qidiruv + grid + keyboard ---
        right_panel = QWidget()
        right_panel.setStyleSheet("background: #f8fafc;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(s(12), s(10), s(12), 0)
        right_layout.setSpacing(s(10))

        # Qidiruv inputi — alohida qator (cart kengligini siqib qo'ymaslik uchun)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Mahsulot qidirish...")
        self.search_input.mousePressEvent = self._open_search_keyboard
        self.search_input.setFixedHeight(s(52))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                padding: {s(10)}px {s(18)}px;
                font-size: {font(15)}px;
                font-weight: 600;
                border-radius: {s(10)}px;
                border: 1.5px solid #e2e8f0;
                background: white;
                color: #334155;
            }}
            QLineEdit:focus {{ border: 1.5px solid #3b82f6; }}
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        right_layout.addWidget(self.search_input)

        # Tezkor slotlar — qidiruv tagida alohida qator, hammasi teng kenglikda
        quick_row = QHBoxLayout()
        quick_row.setSpacing(s(8))
        cfg = load_config()
        slots_count = int(cfg.get("quick_slots_count") or 3)
        slots_count = max(1, min(slots_count, 6))
        self.quick_slots: list[QuickSlotButton] = []
        for idx in range(1, slots_count + 1):
            slot = QuickSlotButton(idx)
            slot.activated.connect(self._on_quick_activated)
            slot.configure_requested.connect(self._on_quick_configure)
            self.quick_slots.append(slot)
            quick_row.addWidget(slot, stretch=1)

        right_layout.addLayout(quick_row)
        self._load_quick_items()

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
        self.items_grid.setSpacing(s(14))
        self.items_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        outer_layout.addLayout(self.items_grid)
        outer_layout.addStretch()

        self.items_scroll.setWidget(self.items_container)
        right_layout.addWidget(self.items_scroll, stretch=1)
        # Touch scroll — tovarlar gridi
        _enable_touch_scroll(self.items_scroll)

        # Loading overlay — items_scroll ustida
        self._loading = LoadingOverlay(self.items_scroll, text="Tovarlar yuklanmoqda...", size=44)

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
        # Avval mavjud barcha kategoriya tugmalarini tozalash
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self.current_category = None  # "Barchasi" ga qaytarish

        try:
            # Har bir kategoriya bo'yicha item soni — kassirga foydali ko'rsatkich
            counts: dict[str, int] = {}
            total = 0
            for it in Item.select(Item.course):
                total += 1
                if it.course:
                    counts[it.course] = counts.get(it.course, 0) + 1

            self._add_cat_btn("Barchasi", count=total, is_all=True)
            for c in sorted(counts.keys()):
                self._add_cat_btn(c, count=counts[c])
        except Exception as e:
            logger.debug("Kategoriyalar yuklanmadi: %s", e)

    def _add_cat_btn(self, name, count: int = 0, is_all: bool = False):
        """Kategoriya tugmasi — chap aksent chiziq, kategoriya nomi va item soni.

        Touchscreen uchun yiriklashtirilgan (70px) va bo'sh joy ko'p (padding).
        Tanlanganda chap tomondan ko'k chiziq paydo bo'ladi.
        """
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setChecked(is_all)
        btn.setFixedHeight(s(74))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: {s(10)}px {s(8)}px {s(10)}px {s(12)}px;
                border-radius: {s(10)}px;
                background: transparent;
                border: 1.5px solid transparent;
                border-left: {s(4)}px solid transparent;
            }}
            QPushButton:checked {{
                background: #eff6ff;
                border: 1.5px solid #bfdbfe;
                border-left: {s(4)}px solid #2563eb;
            }}
            QPushButton:hover:!checked {{
                background: #f1f5f9;
                border-left: {s(4)}px solid #cbd5e1;
            }}
        """)

        # Inner layout — nom (yuqori) + count badge (past)
        inner = QVBoxLayout(btn)
        inner.setContentsMargins(s(6), 0, s(4), 0)
        inner.setSpacing(s(2))
        inner.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"""
            font-size: {font(16)}px;
            font-weight: 800;
            color: #1e293b;
            background: transparent;
            border: none;
        """)
        name_lbl.setWordWrap(True)
        inner.addWidget(name_lbl)

        if count > 0:
            count_lbl = QLabel(f"{count} ta")
            count_lbl.setStyleSheet(f"""
                font-size: {font(11)}px;
                font-weight: 700;
                color: #64748b;
                background: transparent;
                border: none;
            """)
            inner.addWidget(count_lbl)

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
        """Ekran kengligiga qarab ustunlar soni.
        15.6" (1920px) → 4 ta,  24"+ → 5-6 ta,  kichik → 3 ta.
        POS Profile da custom_item_columns sozlansa, u ustunlik qiladi."""
        from core.config import load_config as _lc
        forced = int(_lc().get("item_columns") or 0)
        if 2 <= forced <= 6:
            return forced

        available = self.items_scroll.viewport().width()
        if available <= 0:
            available = s(600)
        spacing = self.items_grid.spacing()
        # Rasm olib tashlandi — card lar ixchamroq, ko'proq sig'adi
        min_card_width = s(180)
        cols = max(2, (available + spacing) // (min_card_width + spacing))
        return min(cols, 6)

    def _cleanup_pending(self, widget):
        """Loader tugagach widget'ni xavfsiz o'chirish (GUI threadga qaytib keladi)."""
        try:
            self._pending_delete.remove(widget)
        except ValueError:
            pass
        widget.deleteLater()

    def shutdown(self):
        """App yopilganda barcha ImageLoader threadlarini to'xtatish."""
        # Pending delete ro'yxatidagi — loaderlar allaqachon disconnect qilingan,
        # shunchaki tugashini kutamiz
        for widget in list(self._pending_delete):
            if hasattr(widget, 'loader') and widget.loader.isRunning():
                widget.loader.wait(3000)
            widget.deleteLater()
        self._pending_delete.clear()

        # Hozirgi grid dagi loaderlarni to'xtatish
        for i in range(self.items_grid.count()):
            child = self.items_grid.itemAt(i)
            if not child:
                continue
            widget = child.widget()
            if widget and hasattr(widget, 'loader') and widget.loader.isRunning():
                try:
                    widget.loader.image_loaded.disconnect()
                except RuntimeError:
                    pass
                widget.loader.wait(3000)

    def load_items(self, search=""):
        # Loading ko'rsatish
        self._loading.show_loading()

        # Eski kartalarni tozalash — yangi layoutda rasm yo'q, oddiy delete kifoya
        while self.items_grid.count():
            child = self.items_grid.takeAt(0)
            widget = child.widget()
            if widget:
                # Legacy loader (eski kod paydo bo'lsa) — xavfsiz cleanup
                loader = getattr(widget, "loader", None)
                if loader is not None and hasattr(loader, "isRunning") and loader.isRunning():
                    try:
                        loader.image_loaded.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                    self._pending_delete.append(widget)
                    loader.finished.connect(lambda w=widget: self._cleanup_pending(w))
                else:
                    widget.deleteLater()

        columns = self._calc_grid_columns()
        self._last_columns = columns

        try:
            query = Item.select()
            if self.current_category:
                query = query.where(Item.course == self.current_category)
            if search:
                query = query.where(Item.item_name.contains(search) | Item.item_code.contains(search))

            # URY Menu Item.idx (admin drag-drop tartibi) → alfavit fallback
            query = query.order_by(Item.display_idx.asc(), Item.item_name.asc())

            row, col = 0, 0
            for item in query.limit(ITEM_LOAD_LIMIT):
                price_rec = ItemPrice.get_or_none(ItemPrice.item_code == item.item_code)
                p = price_rec.price_list_rate if price_rec else 0
                cur = price_rec.currency if price_rec else "UZS"

                card = ItemButton(
                    item.item_code, item.item_name, p, cur,
                    image_url=None, api=self.api,
                )
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

        # Loading yashirish
        self._loading.hide_loading()

        # Agar hech narsa topilmagan bo'lsa
        if self.items_grid.count() == 0 and not search:
            self._loading.set_text("Tovarlar topilmadi.\nSinxronizatsiya qiling.")
            self._loading.show_loading()
            self._loading._spinner.stop()  # faqat matn, spinner yo'q

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize_done(self):
        new_cols = self._calc_grid_columns()
        if new_cols != self._last_columns:
            self.load_items(self.search_input.text())

    def filter_items(self, t):
        self.load_items(t)

    # ── Tezkor slotlar (kassir o'zi qo'lda sozlaydi) ──────────────────
    def _load_quick_items(self):
        """config.json dan tezkor itemlarni o'qib, slotlarga joylash.

        Saqlash sxemasi: config["quick_items"] = [{item_code, item_name, price, currency}, ...]
        Tartib slot indeksiga mos keladi (1-slot = ro'yxat[0]).
        Item DB dan tekshiriladi — agar o'chirilgan bo'lsa, narx/nom yangilanadi.
        """
        cfg = load_config()
        stored = cfg.get("quick_items") or []
        for idx, slot in enumerate(self.quick_slots):
            data = stored[idx] if idx < len(stored) else None
            if not data or not data.get("item_code"):
                slot.clear_item()
                continue
            # Local DB dan narx/nom yangilash — sinxronizatsiyadan keyin tezroq aks etadi
            try:
                it = Item.get_or_none(Item.item_code == data["item_code"])
                if it is None:
                    slot.clear_item()
                    continue
                price_rec = ItemPrice.get_or_none(ItemPrice.item_code == it.item_code)
                p = price_rec.price_list_rate if price_rec else float(data.get("price") or 0)
                cur = price_rec.currency if price_rec else data.get("currency", "UZS")
                slot.set_item(it.item_code, it.item_name, p, cur)
            except Exception as e:
                logger.debug("Tezkor item yuklashda xato: %s", e)
                slot.set_item(data["item_code"], data.get("item_name", data["item_code"]),
                              float(data.get("price") or 0), data.get("currency", "UZS"))

    def _save_quick_items(self):
        payload = []
        for slot in self.quick_slots:
            if slot.item_code:
                payload.append({
                    "item_code": slot.item_code,
                    "item_name": slot.item_name,
                    "price": float(slot.price),
                    "currency": slot.currency,
                })
            else:
                payload.append(None)
        save_config({"quick_items": payload})

    def _on_quick_activated(self, item_code, item_name, price, currency):
        self.item_selected.emit(item_code, item_name, float(price), currency)

    def _on_quick_configure(self, slot_index: int):
        slot = self.quick_slots[slot_index - 1]
        dlg = QuickItemPickerDialog(self, slot_index, has_current=bool(slot.item_code))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.selected == "CLEAR":
            slot.clear_item()
        elif isinstance(dlg.selected, dict):
            slot.set_item(
                dlg.selected["item_code"], dlg.selected["item_name"],
                dlg.selected["price"], dlg.selected["currency"],
            )
        self._save_quick_items()
