import requests
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QThread, QObject, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QScrollArea, QGridLayout, QLabel, QSizePolicy, QFrame,
    QScroller, QScrollerProperties, QDialog,
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPainterPath, QFont, QFontMetrics
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


class _SaveItemOrderWorker(QThread):
    """Menu item tartibini server'ga (URY Menu Item.idx) saqlash."""
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, api, pos_profile: str, items: list):
        super().__init__()
        self.api = api
        self.pos_profile = pos_profile
        self.items = items

    def run(self):
        try:
            if not self.pos_profile:
                self.finished_signal.emit(False, "POS Profile yo'q")
                return
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.saveMenuItemOrder",
                {"pos_profile": self.pos_profile, "items": self.items},
            )
            if ok and isinstance(resp, dict) and resp.get("status") == "ok":
                self.finished_signal.emit(True, f"updated={resp.get('updated')}")
            else:
                self.finished_signal.emit(False, str(resp))
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class _SaveMenuOrderWorker(QThread):
    """Menu course tartibini server'ga (URY Menu Course.custom_serving_priority) saqlash."""
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, api, orders: list):
        super().__init__()
        self.api = api
        self.orders = orders

    def run(self):
        try:
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.saveMenuCourseOrder",
                {"orders": self.orders},
            )
            if ok and isinstance(resp, dict) and resp.get("status") == "ok":
                self.finished_signal.emit(True, f"updated={resp.get('updated')}")
            else:
                self.finished_signal.emit(False, str(resp))
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class _SaveQuickItemsWorker(QThread):
    """Tezkor itemlarni server'ga (POS Profile.custom_quick_items) saqlash.

    Lokal save_config darhol bo'ladi — bu worker shunchaki best-effort
    sync, foydalanuvchini bloklamaydi.
    """
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, api, pos_profile: str, items: list, slots_count: int):
        super().__init__()
        self.api = api
        self.pos_profile = pos_profile
        self.items = items
        self.slots_count = slots_count

    def run(self):
        try:
            if not self.pos_profile:
                self.finished_signal.emit(False, "POS Profile yo'q")
                return
            ok, resp = self.api.call_method(
                "ury.ury_pos.api.save_pos_quick_items",
                {
                    "pos_profile": self.pos_profile,
                    "items": self.items,
                    "slots_count": int(self.slots_count),
                },
            )
            if ok and isinstance(resp, dict) and resp.get("status") == "ok":
                self.finished_signal.emit(True, f"saved={resp.get('saved_count')}")
            else:
                self.finished_signal.emit(False, str(resp))
        except Exception as e:
            self.finished_signal.emit(False, str(e))


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
    """Tezkor slot uchun item tanlash dialogi — elite + RU/EN klaviatura.

    Layout:
      ┌──────────────────────────────────────────────────────┐
      │  TEZKOR SOTUV SLOT  ·  IV                       ✕   │
      │  Kassir bu tugmani bossa, item savatga qo'shiladi   │
      ├──────────────────────────────────────────────────────┤
      │  [Mahsulot nomini yozing...]                          │
      │  ┌────────────────────────────────────────────────┐ │
      │  │ 7 UP 1,5л   ·   13 000 UZS                     │ │
      │  │ 7 UP 1л    ·   10 000 UZS                      │ │
      │  │ ...                                             │ │
      │  └────────────────────────────────────────────────┘ │
      ├──────────────────────────────────────────────────────┤
      │  [1][2][3]...[0][⌫]                                  │
      │  [Q W E R T Y U I O P]                               │
      │  ...    [LANG]                                        │
      └──────────────────────────────────────────────────────┘
    """
    # ── RU/EN klaviatura layoutlari ───────────────────────
    _KB_LAYOUTS = {
        "EN": [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['CAPS','A','S','D','F','G','H','J','K','L','CLR'],
            ['LANG','Z','X','C','V','B','N','M','SPACE'],
        ],
        "RU": [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Й','Ц','У','К','Е','Н','Г','Ш','Щ','З','Х'],
            ['CAPS','Ф','Ы','В','А','П','Р','О','Л','Д','CLR'],
            ['LANG','Я','Ч','С','М','И','Т','Ь','Б','Ю','SPACE'],
        ],
    }

    def __init__(self, parent, slot_index: int, has_current: bool):
        super().__init__(parent)
        self.selected = None   # dict yoki "CLEAR"
        self._kb_lang = "EN"
        self._caps = False
        self._kb_letter_buttons: list[QPushButton] = []
        self.setWindowTitle(
            f"Tezkor slot {ROMAN.get(slot_index, slot_index)} — item tanlash"
        )
        self.setMinimumSize(s(720), s(820))
        self.setStyleSheet("background: white;")

        root = QVBoxLayout(self)
        root.setContentsMargins(s(28), s(20), s(28), s(20))
        root.setSpacing(s(14))

        # ── Header ────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(s(12))

        title_block = QVBoxLayout()
        title_block.setSpacing(s(2))

        title = QLabel(f"TEZKOR SOTUV SLOT  ·  {ROMAN.get(slot_index, slot_index)}")
        title.setFrameShape(QFrame.Shape.NoFrame)
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tf = QFont()
        tf.setPixelSize(font(14))
        tf.setWeight(QFont.Weight.Black)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        title.setFont(tf)
        title.setStyleSheet(
            "color: #0f172a; background: transparent;"
            " border: none; outline: none; padding: 0; margin: 0;"
        )
        title_block.addWidget(title)

        hint = QLabel(
            "Tez-tez sotiladigan mahsulotni tanlang — "
            "kassir bu tugmani bossa savatga qo'shiladi"
        )
        hint.setFrameShape(QFrame.Shape.NoFrame)
        hint.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hf = QFont()
        hf.setPixelSize(font(11))
        hf.setWeight(QFont.Weight.Medium)
        hint.setFont(hf)
        hint.setStyleSheet(
            "color: #64748b; background: transparent;"
            " border: none; outline: none;"
        )
        title_block.addWidget(hint)
        header.addLayout(title_block)
        header.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(36), s(36))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #94a3b8;
                font-weight: 700;
                font-size: {font(14)}px;
                border-radius: {s(8)}px;
                border: 1px solid transparent;
                outline: none;
            }}
            QPushButton:hover {{
                background: #f8fafc; color: #0f172a;
                border: 1px solid #e2e8f0;
            }}
            QPushButton:pressed {{ background: #f1f5f9; }}
        """)
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        root.addLayout(header)

        # Hairline
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #f1f5f9; border: none;")
        root.addWidget(sep)

        # ── Search input ──────────────────────────
        self.search = QLineEdit()
        self.search.setPlaceholderText("Mahsulot nomini yozing...")
        self.search.setFixedHeight(s(50))
        self.search.setStyleSheet(f"""
            QLineEdit {{
                padding: 0 {s(18)}px;
                font-size: {font(15)}px;
                font-weight: 600;
                color: #0f172a;
                background: white;
                border: 1px solid #e2e8f0;
                border-radius: {s(10)}px;
                outline: none;
            }}
            QLineEdit:focus {{ border: 1px solid #c89968; }}
        """)
        self.search.textChanged.connect(self._reload)
        root.addWidget(self.search)

        # ── Results list ──────────────────────────
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                width: {s(6)}px; background: transparent; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #cbd5e1; border-radius: {s(3)}px;
                min-height: {s(30)}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(s(4))
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_scroll.setWidget(self.list_container)
        root.addWidget(self.list_scroll, stretch=1)

        # ── Bottom: clear/cancel/keyboard toggle ─────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(s(10))

        if has_current:
            clear_btn = QPushButton("Slotni bo'shatish")
            clear_btn.setFixedHeight(s(44))
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background: white;
                    color: #b91c1c;
                    font-weight: 700;
                    font-size: {font(12)}px;
                    letter-spacing: 0.5px;
                    border: 1px solid #fecaca;
                    border-radius: {s(8)}px;
                    padding: 0 {s(20)}px;
                    outline: none;
                }}
                QPushButton:hover {{
                    background: #fef2f2; border-color: #fca5a5;
                }}
                QPushButton:pressed {{ background: #fee2e2; }}
            """)
            clear_btn.clicked.connect(self._on_clear)
            btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        cancel = QPushButton("Bekor qilish")
        cancel.setFixedHeight(s(44))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: #334155;
                font-weight: 700;
                font-size: {font(12)}px;
                letter-spacing: 0.5px;
                border: 1px solid #e2e8f0;
                border-radius: {s(8)}px;
                padding: 0 {s(24)}px;
                outline: none;
            }}
            QPushButton:hover {{
                background: #f8fafc; color: #0f172a;
                border-color: #cbd5e1;
            }}
            QPushButton:pressed {{ background: #f1f5f9; }}
        """)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        root.addLayout(btn_row)

        # ── Klaviatura paneli ─────────────────────
        self._kb_panel = self._build_keyboard_panel()
        root.addWidget(self._kb_panel)

        self._reload("")

    def _build_keyboard_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: #f8fafc;"
            " border-top: 1px solid #e2e8f0; border-radius: 0px; }"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(s(12), s(12), s(12), s(12))
        v.setSpacing(s(6))

        self._kb_rows_container = QVBoxLayout()
        self._kb_rows_container.setSpacing(s(5))
        self._kb_rows_container.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self._kb_rows_container)

        self._render_kb_rows()
        return panel

    def _render_kb_rows(self):
        while self._kb_rows_container.count():
            it = self._kb_rows_container.takeAt(0)
            if it is None:
                continue
            sub = it.layout()
            if sub is not None:
                while sub.count():
                    w = sub.takeAt(0).widget()
                    if w:
                        w.deleteLater()

        self._kb_letter_buttons = []
        rows = self._KB_LAYOUTS.get(self._kb_lang, self._KB_LAYOUTS["EN"])
        for row_keys in rows:
            r = QHBoxLayout()
            r.setSpacing(s(5))
            for key in row_keys:
                r.addWidget(self._make_kb_key(key))
            self._kb_rows_container.addLayout(r)

    def _make_kb_key(self, key: str) -> QPushButton:
        if key == 'SPACE': label = 'PROBEL'
        elif key == 'CLR': label = 'TOZALASH'
        elif key == 'CAPS': label = 'Aa'
        elif key == 'LANG': label = ('RU' if self._kb_lang == "EN" else 'EN')
        else: label = key

        btn = QPushButton(label)
        btn.setFixedHeight(s(42))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        if key == '⌫':
            base = f"""
                background: white; color: #b91c1c;
                font-size: {font(15)}px; font-weight: 700;
                border: 1px solid #fecaca;
            """
            hover = "background: #fef2f2; border: 1px solid #fca5a5;"
        elif key == 'CLR':
            base = f"""
                background: white; color: #64748b;
                font-size: {font(9)}px; font-weight: 800;
                letter-spacing: 1.5px;
                border: 1px solid #e2e8f0;
            """
            hover = "background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a;"
        elif key == 'CAPS':
            base = f"""
                background: white; color: #334155;
                font-size: {font(13)}px; font-weight: 800;
                border: 1px solid #e2e8f0;
            """
            hover = "background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a;"
        elif key == 'LANG':
            base = f"""
                background: #fff7ed; color: #a07a44;
                font-size: {font(10)}px; font-weight: 800;
                letter-spacing: 1px;
                border: 1px solid #e6c693;
            """
            hover = "background: #ffedd5; border: 1px solid #c89968; color: #0f172a;"
        elif key == 'SPACE':
            base = f"""
                background: white; color: #334155;
                font-size: {font(10)}px; font-weight: 800;
                letter-spacing: 2px;
                border: 1px solid #e2e8f0;
            """
            hover = "background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a;"
            btn.setMinimumWidth(s(120))
        elif key.isdigit():
            base = f"""
                background: white; color: #0f172a;
                font-size: {font(14)}px; font-weight: 700;
                border: 1px solid #e2e8f0;
            """
            hover = "background: #f8fafc; border: 1px solid #cbd5e1;"
        else:
            base = f"""
                background: white; color: #0f172a;
                font-size: {font(13)}px; font-weight: 600;
                border: 1px solid #e2e8f0;
            """
            hover = "background: #f8fafc; border: 1px solid #cbd5e1;"

        btn.setStyleSheet(f"""
            QPushButton {{ {base} border-radius: {s(7)}px; outline: none; }}
            QPushButton:hover {{ {hover} }}
            QPushButton:pressed {{ background: #f1f5f9; }}
        """)
        btn.clicked.connect(lambda checked=False, k=key: self._on_kb_key(k))
        if len(key) == 1 and key.isalpha():
            self._kb_letter_buttons.append(btn)
        return btn

    def _on_kb_key(self, key: str):
        if key == 'CAPS':
            self._caps = not self._caps
            for b in self._kb_letter_buttons:
                txt = b.text()
                b.setText(txt.upper() if self._caps else txt.lower())
            return
        if key == 'LANG':
            self._kb_lang = "RU" if self._kb_lang == "EN" else "EN"
            self._caps = False
            self._render_kb_rows()
            return
        current = self.search.text()
        if key == '⌫':
            new_text = current[:-1]
        elif key == 'CLR':
            new_text = ''
        elif key == 'SPACE':
            new_text = current + ' '
        else:
            char = key.lower() if not self._caps else key.upper()
            new_text = current + char
        self.search.setText(new_text)

    def _reload(self, text=""):
        # Eskilarni tozalash
        while self.list_layout.count():
            it = self.list_layout.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

        try:
            # FAQAT joriy menyu item'lari — course belgilangan bo'lishi shart.
            # Bu sotilmaydigan (raw ingredients, polufabrikat) yoki eski
            # sinxron qoldiqlarini chiqarib tashlaydi.
            query = Item.select().where(
                (Item.course.is_null(False)) & (Item.course != "")
            )
            t = (text or "").strip()
            if t:
                query = query.where(
                    Item.item_name.contains(t) | Item.item_code.contains(t)
                )
            # Menyu tartibida (display_idx asc) ko'rsatish — admin tartibi
            query = query.order_by(
                Item.display_idx.asc(), Item.item_name.asc()
            ).limit(300)

            count = 0
            for it in query:
                price_rec = ItemPrice.get_or_none(ItemPrice.item_code == it.item_code)
                p = price_rec.price_list_rate if price_rec else 0
                cur = price_rec.currency if price_rec else "UZS"
                # Narxsiz item'larni o'tkazib yuborish — sotilmaydi
                if not p or p <= 0:
                    continue
                self.list_layout.addWidget(
                    self._make_row(it.item_code, it.item_name, p, cur)
                )
                count += 1

            # Bo'sh holat
            if count == 0:
                empty = QLabel(
                    "Hech narsa topilmadi\n\n"
                    "Iltimos, qidiruv matnini o'zgartiring"
                    if t else "Menyuda item'lar topilmadi.\nSinxronlash qiling."
                )
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet(f"""
                    font-size: {font(13)}px;
                    font-weight: 600;
                    color: #94a3b8;
                    padding: {s(40)}px;
                """)
                self.list_layout.addWidget(empty)
        except Exception as e:
            logger.error("Picker yuklashda xato: %s", e)

    def _make_row(self, item_code, item_name, price, currency):
        row = QPushButton()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.setFixedHeight(s(52))
        price_str = f"{price:,.0f}".replace(",", " ") + f" {currency}"
        row.setText(f"{item_name}     ·     {price_str}")
        row.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 0 {s(18)}px;
                font-size: {font(13)}px;
                font-weight: 600;
                color: #0f172a;
                background: white;
                border: 1px solid #f1f5f9;
                border-radius: {s(8)}px;
                outline: none;
            }}
            QPushButton:hover {{
                background: #fff7ed;
                border: 1px solid #c89968;
                color: #a07a44;
            }}
            QPushButton:pressed {{ background: #ffedd5; }}
        """)
        row.clicked.connect(
            lambda checked=False, ic=item_code, n=item_name,
                   pr=float(price), c=currency:
            self._on_pick(ic, n, pr, c)
        )
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

        # Sarlavha — pencil oddiy joyini search bar yonida saqlaymiz
        self._edit_mode = False
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

        # Search bar + edit pencil yonida (kassir aniq ko'rishi uchun)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(s(8))
        search_row.addWidget(self.search_input, stretch=1)

        # Edit pencil — items_edit_btn (search bar yonida)
        self.items_edit_btn = QPushButton("✎")
        self.items_edit_btn.setFixedSize(s(52), s(52))
        self.items_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.items_edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.items_edit_btn.setToolTip(
            "Menyu itemlari va kategoriyalarni tartibga keltirish"
        )
        self.items_edit_btn.clicked.connect(self._toggle_edit_mode)
        self._apply_items_edit_btn_style()
        search_row.addWidget(self.items_edit_btn)
        right_layout.addLayout(search_row)

        # Tezkor slotlar — qidiruv tagida alohida qator, hammasi teng kenglikda
        quick_row = QHBoxLayout()
        quick_row.setSpacing(s(8))
        cfg = load_config()
        slots_count = int(cfg.get("quick_slots_count") or 3)
        # Maks 4 ga cheklangan — 5+ slot cart paneli kichik bo'lib qoldiradi
        slots_count = max(3, min(slots_count, 4))
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

    # ── EN / RU klaviatura layoutlari (search uchun) ──────
    _KB_LAYOUTS = {
        "EN": [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['CAPS','A','S','D','F','G','H','J','K','L','CLR'],
            ['LANG','Z','X','C','V','B','N','M','SPACE'],
        ],
        "RU": [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Й','Ц','У','К','Е','Н','Г','Ш','Щ','З','Х'],
            ['CAPS','Ф','Ы','В','А','П','Р','О','Л','Д','CLR'],
            ['LANG','Я','Ч','С','М','И','Т','Ь','Б','Ю','SPACE'],
        ],
    }

    def _build_keyboard_panel(self):
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: #f8fafc;"
            f" border-top: 1px solid #e2e8f0; border-radius: 0px; }}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(s(14), s(12), s(14), s(14))
        panel_layout.setSpacing(s(6))

        # Display + close row
        top_row = QHBoxLayout()
        top_row.setSpacing(s(10))

        self.kb_display = QLabel("Qidiruv...")
        self.kb_display.setFrameShape(QFrame.Shape.NoFrame)
        self.kb_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        kb_font = QFont()
        kb_font.setPixelSize(font(15))
        kb_font.setWeight(QFont.Weight.DemiBold)
        self.kb_display.setFont(kb_font)
        self.kb_display.setStyleSheet(
            "color: #334155; background: white;"
            f" border: 1px solid #e2e8f0; border-radius: {s(10)}px;"
            f" padding: 0 {s(14)}px; outline: none;"
        )
        self.kb_display.setFixedHeight(s(42))

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(42), s(42))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #94a3b8;
                font-weight: 700;
                font-size: {font(14)}px;
                border-radius: {s(10)}px;
                border: 1px solid #e2e8f0;
                outline: none;
            }}
            QPushButton:hover {{
                background: white;
                color: #0f172a;
                border-color: #cbd5e1;
            }}
            QPushButton:pressed {{ background: #f1f5f9; }}
        """)
        close_btn.clicked.connect(self._close_keyboard)

        top_row.addWidget(self.kb_display, stretch=1)
        top_row.addWidget(close_btn)
        panel_layout.addLayout(top_row)

        # State
        self._kb_lang = "EN"
        self._letter_buttons = []
        self._kb_rows_container = QVBoxLayout()
        self._kb_rows_container.setSpacing(s(5))
        self._kb_rows_container.setContentsMargins(0, 0, 0, 0)
        panel_layout.addLayout(self._kb_rows_container)

        self._render_kb_rows()
        return panel

    def _render_kb_rows(self):
        # Eski rowlarni tozalash
        while self._kb_rows_container.count():
            it = self._kb_rows_container.takeAt(0)
            if it is None:
                continue
            sub = it.layout()
            if sub is not None:
                while sub.count():
                    w = sub.takeAt(0).widget()
                    if w:
                        w.deleteLater()

        self._letter_buttons = []
        rows = self._KB_LAYOUTS.get(self._kb_lang, self._KB_LAYOUTS["EN"])
        for row_keys in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(s(5))
            for key in row_keys:
                btn = self._make_key(key)
                row_layout.addWidget(btn)
            self._kb_rows_container.addLayout(row_layout)

    def _make_key(self, key):
        # Display matni
        if key == 'SPACE': label = 'PROBEL'
        elif key == 'CLR': label = 'TOZALASH'
        elif key == 'CAPS': label = 'Aa'
        elif key == 'LANG': label = ('RU' if self._kb_lang == "EN" else 'EN')
        else: label = key

        btn = QPushButton(label)
        btn.setFixedHeight(s(44))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        if key == '⌫':
            base = """
                background: white;
                color: #b91c1c;
                font-size: {fs}px;
                font-weight: 700;
                border: 1px solid #fecaca;
            """.format(fs=font(16))
            hover = "background: #fef2f2; border: 1px solid #fca5a5;"
        elif key == 'CLR':
            base = """
                background: white;
                color: #64748b;
                font-size: {fs}px;
                font-weight: 800;
                letter-spacing: 1.5px;
                border: 1px solid #e2e8f0;
            """.format(fs=font(9))
            hover = "background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a;"
        elif key == 'CAPS':
            base = """
                background: white;
                color: #334155;
                font-size: {fs}px;
                font-weight: 800;
                border: 1px solid #e2e8f0;
            """.format(fs=font(14))
            hover = "background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a;"
        elif key == 'LANG':
            base = """
                background: #fff7ed;
                color: #a07a44;
                font-size: {fs}px;
                font-weight: 800;
                letter-spacing: 1px;
                border: 1px solid #e6c693;
            """.format(fs=font(11))
            hover = "background: #ffedd5; border: 1px solid #c89968; color: #0f172a;"
        elif key == 'SPACE':
            base = """
                background: white;
                color: #334155;
                font-size: {fs}px;
                font-weight: 800;
                letter-spacing: 2px;
                border: 1px solid #e2e8f0;
            """.format(fs=font(10))
            hover = "background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a;"
            btn.setMinimumWidth(s(140))
        elif key.isdigit():
            base = """
                background: white;
                color: #0f172a;
                font-size: {fs}px;
                font-weight: 700;
                border: 1px solid #e2e8f0;
            """.format(fs=font(15))
            hover = "background: #f8fafc; border: 1px solid #cbd5e1;"
        else:
            base = """
                background: white;
                color: #0f172a;
                font-size: {fs}px;
                font-weight: 600;
                border: 1px solid #e2e8f0;
            """.format(fs=font(14))
            hover = "background: #f8fafc; border: 1px solid #cbd5e1;"

        btn.setStyleSheet(f"""
            QPushButton {{ {base} border-radius: {s(8)}px; outline: none; }}
            QPushButton:hover {{ {hover} }}
            QPushButton:pressed {{ background: #f1f5f9; }}
        """)
        btn.clicked.connect(lambda _, k=key: self._on_key(k))

        if len(key) == 1 and key.isalpha():
            self._letter_buttons.append(btn)

        return btn

    def _on_key(self, key):
        if key == 'CAPS':
            self._caps = not self._caps
            for btn in self._letter_buttons:
                txt = btn.text()
                btn.setText(txt.upper() if self._caps else txt.lower())
            return
        if key == 'LANG':
            # EN ↔ RU almashinuv
            self._kb_lang = "RU" if self._kb_lang == "EN" else "EN"
            self._caps = False
            self._render_kb_rows()
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

            # Server tartibi config dan
            cfg = load_config()
            order_list = cfg.get("menu_course_order") or []
            # Server tartibida bo'lgan + counts > 0 bo'lganlar
            ordered_names = [
                o.get("name") for o in order_list if o.get("name") in counts
            ]
            # Server tartibida YO'Q lekin DB'da bor — alfabit oxirida
            extras = sorted(
                [c for c in counts.keys() if c not in ordered_names]
            )
            sorted_courses = ordered_names + extras
            self._sorted_courses_cache = list(sorted_courses)  # edit mode uchun

            self._add_cat_btn("Barchasi", count=total, is_all=True)
            for c in sorted_courses:
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
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # Tugma balandligini o'ralgan nom bo'yicha hisoblaymiz — ikki qatorli
        # kategoriya nomlari ("Газлив напитки") kesilib qolmasligi uchun. Panel
        # kengligi s(170); nom uchun mavjud kenglik ~ s(110) (chetlar+padding+scrollbar).
        _name_font = QFont(btn.font())
        _name_font.setPixelSize(font(16))
        _name_font.setBold(True)
        _name_h = QFontMetrics(_name_font).boundingRect(
            0, 0, s(110), 10000, int(Qt.TextFlag.TextWordWrap), name
        ).height()
        _count_h = 0
        if count > 0:
            _count_font = QFont(btn.font())
            _count_font.setPixelSize(font(11))
            _count_h = QFontMetrics(_count_font).height() + s(2)  # +inner spacing
        # css padding (10*2) + kontent + nafas oladigan joy; min s(74) (1 qatorli)
        _btn_h = s(10) * 2 + _name_h + _count_h + s(8)
        btn.setFixedHeight(max(s(74), _btn_h))
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
        # QLabel wordWrap layout ichida faqat 1 qator band qiladi (heightForWidth
        # avtomatik yoqilmaydi) — o'ralgan matn balandligini eksplicit beramiz,
        # aks holda 2-qator ("напитки") kesilib qoladi.
        name_lbl.setMinimumHeight(_name_h)
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

        # Edit mode'da kategoriya tugmasi yonida ↑↓ controls (Barchasi'dan tashqari)
        if getattr(self, "_edit_mode", False) and not is_all:
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(s(4))
            row_layout.addWidget(btn, stretch=1)

            arrows_col = QVBoxLayout()
            arrows_col.setContentsMargins(0, 0, 0, 0)
            arrows_col.setSpacing(s(2))

            up_btn = self._make_arrow_btn(
                "▲", lambda checked=False, c=name: self._move_category(c, -1)
            )
            down_btn = self._make_arrow_btn(
                "▼", lambda checked=False, c=name: self._move_category(c, +1)
            )

            # Boundary disable
            order = getattr(self, "_sorted_courses_cache", [])
            if name in order:
                idx = order.index(name)
                if idx == 0:
                    up_btn.setEnabled(False)
                if idx == len(order) - 1:
                    down_btn.setEnabled(False)

            arrows_col.addWidget(up_btn)
            arrows_col.addWidget(down_btn)
            row_layout.addLayout(arrows_col)

            self.category_layout.addWidget(row_widget)
        else:
            self.category_layout.addWidget(btn)

    def _make_arrow_btn(self, label: str, on_click) -> QPushButton:
        """Edit mode'dagi nozik ↑/↓ tugmasi."""
        b = QPushButton(label)
        b.setFixedSize(s(28), s(28))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: #64748b;
                font-size: {font(10)}px;
                font-weight: 800;
                border: 1px solid #e2e8f0;
                border-radius: {s(6)}px;
                outline: none;
            }}
            QPushButton:hover {{
                background: #fff7ed;
                color: #a07a44;
                border-color: #c89968;
            }}
            QPushButton:pressed {{ background: #fde8c8; }}
            QPushButton:disabled {{
                background: #f8fafc;
                color: #cbd5e1;
                border-color: #f1f5f9;
            }}
        """)
        b.clicked.connect(on_click)
        return b

    def _on_cat_click(self, btn, cat, is_all):
        # Edit mode'da ham kategoriya tanlash MUMKIN — kassir qaysi
        # kategoriya item'larini tartiblash kerakligini tanlay olishi uchun
        for i in range(self.category_layout.count()):
            w = self.category_layout.itemAt(i).widget()
            # Tahrir rejimida QPushButton row_widget ichida — itni topish
            if w is None:
                continue
            inner_btn = None
            if isinstance(w, QPushButton):
                inner_btn = w
            else:
                # Edit mode'da row_widget — chap qismda QPushButton bor
                for child in w.findChildren(QPushButton):
                    if child.isCheckable():
                        inner_btn = child
                        break
            if inner_btn is not None:
                inner_btn.setChecked(inner_btn is btn)
        self.current_category = None if is_all else cat
        self.load_items(self.search_input.text())

    # ── Kategoriya tartibi tahrir rejimi ────────────────────────────
    def _apply_edit_btn_style(self):
        # Sidebar pencil olib tashlangan — no-op placeholder qoldiriladi
        pass

    def _apply_items_edit_btn_style(self):
        """Search bar yonidagi pencil tugmasi stili."""
        if not hasattr(self, "items_edit_btn"):
            return
        if getattr(self, "_edit_mode", False):
            bg, color, border = "#fff7ed", "#a07a44", "#c89968"
            hover_bg = "#ffedd5"
        else:
            bg, color, border = "white", "#64748b", "#e2e8f0"
            hover_bg = "#f8fafc"
        self.items_edit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {color};
                font-size: {font(20)}px;
                font-weight: 700;
                border: 1.5px solid {border};
                border-radius: {s(10)}px;
                outline: none;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border-color: #c89968;
                color: #a07a44;
            }}
            QPushButton:pressed {{ background: #fde8c8; }}
        """)

    def _toggle_edit_mode(self):
        self._edit_mode = not self._edit_mode
        self._apply_edit_btn_style()
        self._apply_items_edit_btn_style()
        # Kategoriyalarni ham, itemlarni ham qayta render —
        # ↑↓ tugmalar paydo bo'lishi / yo'qolishi uchun
        self.load_categories()
        self.load_items(self.search_input.text())

    def _move_category(self, course_name: str, direction: int):
        """Kategoriyani yuqori (-1) yoki past (+1) ga ko'chiradi.

        Lokal cache yangilanadi → save_config → server'ga POST.
        """
        logger.info("_move_category: course=%s direction=%d cache_len=%d",
                    course_name, direction,
                    len(getattr(self, "_sorted_courses_cache", [])))
        order = list(getattr(self, "_sorted_courses_cache", []))
        if course_name not in order:
            logger.warning("_move_category: '%s' cache'da yo'q, cache=%s",
                           course_name, order)
            return
        idx = order.index(course_name)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(order):
            logger.info("_move_category: boundary (idx=%d new=%d len=%d)",
                        idx, new_idx, len(order))
            return
        logger.info("_move_category: swap idx %d <-> %d", idx, new_idx)
        order[idx], order[new_idx] = order[new_idx], order[idx]
        self._sorted_courses_cache = order

        # Lokal config'da menu_course_order'ni yangilash
        cfg = load_config()
        existing = {
            o.get("name"): o for o in (cfg.get("menu_course_order") or [])
        }
        new_list = []
        for prio, name in enumerate(order, start=1):
            base = existing.get(name) or {"name": name}
            base["priority"] = prio
            new_list.append(base)
        save_config({"menu_course_order": new_list})

        # Serverga POST — best-effort, foydalanuvchini bloklamaydi
        worker = _SaveMenuOrderWorker(
            api=self.api,
            orders=[{"name": o["name"], "priority": o["priority"]}
                    for o in new_list],
        )
        worker.finished_signal.connect(self._on_menu_order_saved)
        worker.start()
        self._save_menu_order_worker = worker

        # UI qayta-render
        self.load_categories()

    def _on_menu_order_saved(self, success: bool, msg: str):
        if success:
            logger.info("Kategoriya tartibi server'ga saqlandi: %s", msg)
        else:
            logger.warning("Kategoriya tartibi saqlanmadi: %s", msg)

    def _move_item(self, item_code: str, direction: int):
        """Item'ni kategoriya ichida tartibda yuqori (-1) yoki past (+1) ga ko'chiradi.

        Lokal DB Item.display_idx yangilanadi → server URY Menu Item.idx ham.
        """
        logger.info("_move_item: item=%s direction=%d cache_len=%d",
                    item_code, direction,
                    len(getattr(self, "_sorted_items_cache", [])))
        order = list(getattr(self, "_sorted_items_cache", []))
        codes = [o["item_code"] for o in order]
        if item_code not in codes:
            logger.warning("_move_item: '%s' cache'da yo'q (first 5 codes=%s)",
                           item_code, codes[:5])
            return
        idx = codes.index(item_code)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(order):
            logger.info("_move_item: boundary (idx=%d new=%d len=%d)",
                        idx, new_idx, len(order))
            return
        logger.info("_move_item: swap %s ↔ %s", codes[idx], codes[new_idx])
        order[idx], order[new_idx] = order[new_idx], order[idx]
        self._sorted_items_cache = order

        # Lokal DB — har item.display_idx ni yangi pozitsiyaga
        try:
            with db.atomic():
                for prio, o in enumerate(order, start=1):
                    Item.update(display_idx=prio).where(
                        Item.item_code == o["item_code"]
                    ).execute()
        except Exception as e:
            logger.error("Item display_idx yangilashda xatolik: %s", e)

        # Server'ga POST — best-effort
        cfg = load_config()
        payload = [
            {"item_code": o["item_code"], "idx": prio}
            for prio, o in enumerate(order, start=1)
        ]
        worker = _SaveItemOrderWorker(
            api=self.api,
            pos_profile=cfg.get("pos_profile", ""),
            items=payload,
        )
        worker.finished_signal.connect(self._on_item_order_saved)
        worker.start()
        self._save_item_order_worker = worker

        # Re-render
        self.load_items(self.search_input.text())

    def _on_item_order_saved(self, success: bool, msg: str):
        if success:
            logger.info("Item tartibi server'ga saqlandi: %s", msg)
        else:
            logger.warning("Item tartibi saqlanmadi: %s", msg)

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

            # Edit mode + kategoriya tanlangan — items vertikal qatorda ↑↓ bilan
            in_edit_mode_no_cat = (
                getattr(self, "_edit_mode", False)
                and self.current_category is None
                and not search
            )
            in_edit_items_mode = (
                getattr(self, "_edit_mode", False)
                and self.current_category is not None
                and not search
            )

            # Edit mode + "Barchasi" tanlangan — kategoriya tanlash kerakligi haqida xabar
            if in_edit_mode_no_cat:
                hint = QLabel(
                    "Item tartibini o'zgartirish uchun\n"
                    "chap tomondan KATEGORIYA tanlang"
                )
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hint.setStyleSheet(f"""
                    font-size: {font(15)}px;
                    font-weight: 700;
                    color: #a07a44;
                    background: #fff7ed;
                    border: 1px solid #c89968;
                    border-radius: {s(12)}px;
                    padding: {s(28)}px;
                """)
                self.items_grid.addWidget(hint, 0, 0, 1, max(1, columns))
                self._loading.hide_loading()
                return

            if in_edit_items_mode:
                items_list = list(query.limit(ITEM_LOAD_LIMIT))
                self._sorted_items_cache = [
                    {"item_code": it.item_code, "item_name": it.item_name}
                    for it in items_list
                ]
                # Bitta ustun, har qatorda card + ↑↓
                for row_idx, item in enumerate(items_list):
                    price_rec = ItemPrice.get_or_none(ItemPrice.item_code == item.item_code)
                    p = price_rec.price_list_rate if price_rec else 0
                    cur = price_rec.currency if price_rec else "UZS"

                    row_wrap = QWidget()
                    row_wrap.setStyleSheet("background: transparent;")
                    row_layout = QHBoxLayout(row_wrap)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(s(8))

                    card = ItemButton(
                        item.item_code, item.item_name, p, cur,
                        image_url=None, api=self.api,
                    )
                    # Edit mode'da kassirga tovar qo'shilmasligi uchun click bog'lanmaydi
                    row_layout.addWidget(card, stretch=1)

                    arrows = QVBoxLayout()
                    arrows.setContentsMargins(0, 0, 0, 0)
                    arrows.setSpacing(s(4))
                    up_btn = self._make_arrow_btn(
                        "▲",
                        lambda checked=False, c=item.item_code: self._move_item(c, -1),
                    )
                    down_btn = self._make_arrow_btn(
                        "▼",
                        lambda checked=False, c=item.item_code: self._move_item(c, +1),
                    )
                    up_btn.setFixedSize(s(48), s(48))
                    down_btn.setFixedSize(s(48), s(48))
                    if row_idx == 0:
                        up_btn.setEnabled(False)
                    if row_idx == len(items_list) - 1:
                        down_btn.setEnabled(False)
                    arrows.addWidget(up_btn)
                    arrows.addWidget(down_btn)
                    arrows.addStretch()
                    row_layout.addLayout(arrows)

                    # Bitta ustunda (col=0) tegrid orqali (column spanning bilan)
                    self.items_grid.addWidget(row_wrap, row_idx, 0, 1, max(1, columns))
            else:
                self._sorted_items_cache = []
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
        # Server uchun faqat to'ldirilgan slotlar (item_code + slot_idx)
        server_items = []
        for idx, slot in enumerate(self.quick_slots, start=1):
            if slot.item_code:
                payload.append({
                    "item_code": slot.item_code,
                    "item_name": slot.item_name,
                    "price": float(slot.price),
                    "currency": slot.currency,
                })
                server_items.append({
                    "item_code": slot.item_code,
                    "slot_idx": idx,
                })
            else:
                payload.append(None)
        save_config({"quick_items": payload})

        # Server'ga ham POST — boshqa qurilmalarga sinxron bo'lsin (best-effort)
        QThread.currentThread()
        worker = _SaveQuickItemsWorker(
            api=self.api,
            pos_profile=load_config().get("pos_profile", ""),
            items=server_items,
            slots_count=len(self.quick_slots),
        )
        worker.finished_signal.connect(self._on_quick_saved)
        worker.start()
        # Threadni saqlab qo'yamiz, GC qilmasin
        self._save_quick_worker = worker

    def _on_quick_saved(self, success: bool, msg: str):
        if success:
            logger.info("Tezkor itemlar server'ga saqlandi: %s", msg)
        else:
            logger.warning("Tezkor itemlar server'ga saqlanmadi: %s", msg)

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
