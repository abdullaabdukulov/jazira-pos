"""Jazira POS — elite kassir kirish ekrani.

Dizayn falsafasi:
- Restoran-warm: oltin (#d4a574) aksent, navy/midnight fon
- Touch-first: 78px circular numpad tugmalari, jonli pressed/hover holatlar
- Hayot belgilari: real-time soat, kun-bo'yicha salom, server status pulse
- Animatsiyalar: PIN doti glow + xato shake, success flash
- Trust signals: xavfsiz ulanish indikatori, footer status

API sirti: oldingicha — login_successful (object) signali, AutoLoginWorker.
"""

from datetime import datetime

from PyQt6.QtCore import (
    Qt, QTimer, QThread, QPropertyAnimation, QAbstractAnimation,
    QRect, QRectF, pyqtSignal, pyqtProperty,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.api import FrappeAPI
from core.config import get_cashiers, load_config, save_config, verify_pin
from core.logger import get_logger
from ui.scale import font, s

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
#  Design tokens
# ═══════════════════════════════════════════════════════════
GOLD = "#d4a574"
GOLD_LIGHT = "#ebc999"
ACTIVE = "#7dd3fc"
ACTIVE_DEEP = "#38bdf8"
ERROR = "#fb7185"
SUCCESS = "#34d399"
WARN = "#fbbf24"

TEXT_PRIMARY = "#f8fafc"
TEXT_SECONDARY = "rgba(248,250,252,0.62)"
TEXT_MUTED = "rgba(248,250,252,0.34)"
TEXT_DIM = "rgba(248,250,252,0.18)"

BG_TOP = "#0a1224"
BG_MID = "#101a32"
BG_BOTTOM = "#050a18"


_MONTHS_UZ = (
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
)
_WEEKDAYS_UZ = (
    "Dushanba", "Seshanba", "Chorshanba", "Payshanba",
    "Juma", "Shanba", "Yakshanba",
)


def _greeting() -> str:
    h = datetime.now().hour
    if 5 <= h < 12:
        return "Xayrli tong"
    if 12 <= h < 17:
        return "Xayrli kun"
    if 17 <= h < 22:
        return "Xayrli kech"
    return "Xayrli tun"


# ═══════════════════════════════════════════════════════════
#  BrandLogo — custom-painted oltin "J" monogrammasi
# ═══════════════════════════════════════════════════════════
class BrandLogo(QWidget):
    """Aylana shakldagi oltin halqa va italik 'J' harfi."""

    def __init__(self, size: int = 88, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - w * 0.07

        # ── Ambient gold halo ───────────────────
        glow = QRadialGradient(cx, cy, radius * 1.7)
        glow.setColorAt(0.30, QColor(212, 165, 116, 60))
        glow.setColorAt(0.65, QColor(212, 165, 116, 14))
        glow.setColorAt(1.00, QColor(212, 165, 116, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawRect(self.rect())

        # ── Outer ring (gold gradient) ─────────
        ring_grad = QLinearGradient(0, 0, 0, h)
        ring_grad.setColorAt(0.0, QColor(GOLD_LIGHT))
        ring_grad.setColorAt(1.0, QColor(GOLD).darker(120))
        pen = QPen(QBrush(ring_grad), max(2.0, w * 0.04))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # ── Inner subtle fill (glass) ──────────
        inner_grad = QRadialGradient(cx, cy - radius * 0.35, radius)
        inner_grad.setColorAt(0.0, QColor(255, 255, 255, 22))
        inner_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(inner_grad))
        inner_margin = w * 0.05
        p.drawEllipse(QRectF(
            cx - radius + inner_margin, cy - radius + inner_margin,
            (radius - inner_margin) * 2, (radius - inner_margin) * 2,
        ))

        # ── J monogram (italic Georgia) ────────
        f = QFont("Georgia", int(w * 0.50))
        f.setWeight(QFont.Weight.Bold)
        f.setItalic(True)
        p.setFont(f)
        p.setPen(QColor(GOLD_LIGHT))
        # Vizual markazlash uchun ozgina yuqori (J quyrug'ini kompensatsiya)
        text_rect = QRect(0, int(-h * 0.05), w, h)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "J")


# ═══════════════════════════════════════════════════════════
#  TopBar — xavfsiz badge + real-time soat
# ═══════════════════════════════════════════════════════════
class TopBar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(s(88))
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(40), s(24), s(40), s(12))
        layout.setSpacing(0)

        # Chap: xavfsiz ulanish belgisi
        self._secure = QLabel("◆  XAVFSIZ  ULANISH")
        sec_font = QFont()
        sec_font.setPixelSize(font(11))
        sec_font.setWeight(QFont.Weight.Bold)
        sec_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        self._secure.setFont(sec_font)
        self._secure.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        layout.addWidget(self._secure)

        layout.addStretch()

        # O'ng: vaqt va sana
        right = QVBoxLayout()
        right.setSpacing(s(2))
        right.setContentsMargins(0, 0, 0, 0)

        self._time = QLabel("--:--")
        self._time.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._time.setWordWrap(False)
        # PIXEL size (font() pixels qaytaradi). Raqamlarga letter-spacing yo'q —
        # ular tabular ko'rinishi kerak. StyleHint=TypeWriter monospace kabi.
        time_font = QFont("DejaVu Sans Mono", -1)
        time_font.setPixelSize(font(26))
        time_font.setWeight(QFont.Weight.Light)
        time_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self._time.setFont(time_font)
        self._time.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        right.addWidget(self._time)

        self._date = QLabel("")
        self._date.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._date.setWordWrap(False)
        date_font = QFont()
        date_font.setPixelSize(font(11))
        date_font.setWeight(QFont.Weight.Medium)
        date_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        self._date.setFont(date_font)
        self._date.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        right.addWidget(self._date)

        layout.addLayout(right)

    def _tick(self):
        now = datetime.now()
        self._time.setText(now.strftime("%H:%M"))
        wd = _WEEKDAYS_UZ[now.weekday()]
        self._date.setText(f"{wd}   ·   {now.day} {_MONTHS_UZ[now.month - 1]}")


# ═══════════════════════════════════════════════════════════
#  PinDots — 4 doti, glow + shake
# ═══════════════════════════════════════════════════════════
class PinDots(QWidget):

    DOT = 22
    GAP = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filled = 0
        self._error = False
        self._success = False
        self._shake = 0
        total_w = 4 * self.DOT + 3 * self.GAP + 60
        self.setFixedSize(s(total_w), s(48))

    # ── Public ────────────────────────────────────────
    def set_filled(self, n: int):
        self._filled = max(0, min(4, n))
        self._error = False
        self._success = False
        self.update()

    def set_error(self):
        self._error = True
        self._success = False
        self.update()
        self._animate_shake()

    def set_success(self):
        self._success = True
        self._error = False
        self.update()

    # ── Shake animation property ──────────────────────
    def _animate_shake(self):
        anim = QPropertyAnimation(self, b"shake_offset", self)
        anim.setDuration(420)
        anim.setKeyValueAt(0.00, 0)
        anim.setKeyValueAt(0.15, -14)
        anim.setKeyValueAt(0.30, 12)
        anim.setKeyValueAt(0.45, -9)
        anim.setKeyValueAt(0.60, 6)
        anim.setKeyValueAt(0.80, -3)
        anim.setKeyValueAt(1.00, 0)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _get_shake(self) -> int:
        return self._shake

    def _set_shake(self, v: int):
        self._shake = int(v)
        self.update()

    shake_offset = pyqtProperty(int, _get_shake, _set_shake)

    # ── Paint ─────────────────────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        dot = s(self.DOT)
        gap = s(self.GAP)
        total = 4 * dot + 3 * gap
        x0 = (w - total) // 2 + self._shake
        cy = (h - dot) // 2

        if self._error:
            base = QColor(ERROR)
        elif self._success:
            base = QColor(SUCCESS)
        else:
            base = QColor(ACTIVE)

        for i in range(4):
            cx = x0 + i * (dot + gap)
            filled = i < self._filled

            if filled or self._error:
                # Halo (glow)
                halo = QColor(base)
                halo.setAlpha(70 if filled else 40)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                pad = s(7)
                p.drawEllipse(cx - pad, cy - pad, dot + 2 * pad, dot + 2 * pad)
                # To'liq
                p.setBrush(base)
                p.drawEllipse(cx, cy, dot, dot)
            else:
                # Bo'sh halqa
                pen = QPen(QColor(255, 255, 255, 70))
                pen.setWidth(max(2, int(s(2))))
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(cx, cy, dot, dot)


# ═══════════════════════════════════════════════════════════
#  Numpad button styles
# ═══════════════════════════════════════════════════════════
_DIGIT_STYLE = """
    QPushButton {{
        background: rgba(255,255,255,0.05);
        color: {TEXT_PRIMARY};
        font-size: {fs}px;
        font-weight: 300;
        border-radius: {r}px;
        border: 1px solid rgba(255,255,255,0.10);
    }}
    QPushButton:hover {{
        background: rgba(212,165,116,0.16);
        border: 1px solid {GOLD};
        color: {GOLD_LIGHT};
    }}
    QPushButton:pressed {{
        background: rgba(125,211,252,0.22);
        border: 1px solid {ACTIVE};
        color: {ACTIVE};
    }}
"""

_CLEAR_STYLE = """
    QPushButton {{
        background: rgba(251,113,133,0.06);
        color: rgba(251,113,133,0.70);
        font-size: {fs}px;
        font-weight: 700;
        border-radius: {r}px;
        border: 1px solid rgba(251,113,133,0.20);
    }}
    QPushButton:hover {{
        background: rgba(251,113,133,0.18);
        border: 1px solid {ERROR};
        color: {ERROR};
    }}
    QPushButton:pressed {{ background: rgba(251,113,133,0.32); }}
"""

_BACK_STYLE = """
    QPushButton {{
        background: rgba(255,255,255,0.02);
        color: rgba(255,255,255,0.48);
        font-size: {fs}px;
        font-weight: 400;
        border-radius: {r}px;
        border: 1px solid rgba(255,255,255,0.07);
    }}
    QPushButton:hover {{
        background: rgba(255,255,255,0.09);
        border: 1px solid rgba(255,255,255,0.20);
        color: rgba(255,255,255,0.90);
    }}
    QPushButton:pressed {{ background: rgba(255,255,255,0.15); }}
"""


def _make_button(text: str, kind: str = "digit") -> QPushButton:
    size = 80
    btn = QPushButton(text)
    btn.setFixedSize(s(size), s(size))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    r = s(size // 2)
    tokens = dict(
        TEXT_PRIMARY=TEXT_PRIMARY, GOLD=GOLD, GOLD_LIGHT=GOLD_LIGHT,
        ACTIVE=ACTIVE, ERROR=ERROR,
        r=r,
    )
    if kind == "clear":
        btn.setStyleSheet(_CLEAR_STYLE.format(fs=font(20), **tokens))
    elif kind == "back":
        btn.setStyleSheet(_BACK_STYLE.format(fs=font(22), **tokens))
    else:
        btn.setStyleSheet(_DIGIT_STYLE.format(fs=font(28), **tokens))
    return btn


# ═══════════════════════════════════════════════════════════
#  AutoLoginWorker — o'zgarmagan (API saqlanadi)
# ═══════════════════════════════════════════════════════════
class AutoLoginWorker(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        cfg = load_config()
        url = cfg.get("url", "")
        user = cfg.get("user", "")
        pwd = cfg.get("password", "")
        site = cfg.get("site", "")
        if not (url and user and pwd):
            self.result_ready.emit(False, "Credentials topilmadi")
            return
        try:
            ok, msg = self.api.login(url, user, pwd, site)
            if ok:
                self._sync_cashiers()
            self.result_ready.emit(ok, msg)
        except Exception as e:
            self.result_ready.emit(False, str(e))

    def _sync_cashiers(self):
        """Serverdan kassirlarni olish va config.json ga saqlash."""
        try:
            success, data = self.api.call_method("ury.ury_pos.api.get_pos_cashiers")
            if not success or not isinstance(data, list):
                return
            existing = {
                (c.get("full_name") or c.get("name", "")).lower(): c
                for c in load_config().get("cashiers", [])
            }
            merged = []
            for sc in data:
                full_name = sc.get("full_name") or sc.get("name", "")
                server_pin = sc.get("pin", "")
                local = existing.get(full_name.lower(), {})
                merged.append({
                    "name": full_name,
                    "full_name": full_name,
                    "user": sc.get("user", ""),
                    "pin": server_pin if server_pin else local.get("pin", ""),
                })
            save_config({"cashiers": merged})
            logger.info("Kassirlar sinxronizatsiya qilindi: %d ta", len(merged))
        except Exception as e:
            logger.warning("Kassirlarni sinxronlashda xatolik: %s", e)


# ═══════════════════════════════════════════════════════════
#  LoginWindow
# ═══════════════════════════════════════════════════════════
class LoginWindow(QWidget):
    login_successful = pyqtSignal(object)  # active_cashier dict yoki None

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self._api_ready = False
        self._digits = ""

        self._build_ui()
        self._start_auto_login()

    # ── Custom gradient + ambient gold ───────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Asosiy diagonal gradient (chuqur navy)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0.00, QColor(BG_TOP))
        g.setColorAt(0.55, QColor(BG_MID))
        g.setColorAt(1.00, QColor(BG_BOTTOM))
        p.fillRect(self.rect(), QBrush(g))

        # Yuqori-markazda oltin radial yorug'lik
        radial = QRadialGradient(
            self.width() / 2, self.height() * 0.22, self.width() * 0.55,
        )
        radial.setColorAt(0.00, QColor(212, 165, 116, 46))
        radial.setColorAt(0.55, QColor(212, 165, 116, 10))
        radial.setColorAt(1.00, QColor(212, 165, 116, 0))
        p.fillRect(self.rect(), QBrush(radial))

        # Pastki vinyetka — chuqurroq qora
        vignette = QRadialGradient(
            self.width() / 2, self.height() * 1.05, self.width() * 0.85,
        )
        vignette.setColorAt(0.0, QColor(0, 0, 0, 90))
        vignette.setColorAt(0.7, QColor(0, 0, 0, 20))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(vignette))

    # ── Asosiy UI ─────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("Jazira POS — Kirish")
        self.setMinimumSize(s(520), s(740))
        self.showMaximized()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar (clock + secure badge)
        root.addWidget(TopBar())

        root.addStretch(1)

        # Markaziy ustun
        center = QVBoxLayout()
        center.setSpacing(0)
        center.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Brand logo
        logo_row = QHBoxLayout()
        logo_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        logo_row.addWidget(BrandLogo(s(92)))
        center.addLayout(logo_row)

        center.addSpacing(s(22))

        # Wordmark — POS Profile dan kelgan brand_name (caps).
        # Fallback: config'da company nomi, oxirgi chora — "POS"
        cfg_brand = (
            load_config().get("brand_name")
            or load_config().get("company")
            or ""
        )
        brand_text = str(cfg_brand).strip().upper() or "POS"

        wm_container = QWidget()
        wm_container.setStyleSheet("background: transparent;")
        wm_layout = QHBoxLayout(wm_container)
        wm_layout.setContentsMargins(0, 0, 0, 0)
        wm_layout.setSpacing(0)
        wm_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._wordmark = QLabel(brand_text)
        self._wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wm_font = QFont()
        wm_font.setPixelSize(font(48))
        wm_font.setWeight(QFont.Weight.Thin)
        wm_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 16)
        self._wordmark.setFont(wm_font)
        self._wordmark.setStyleSheet(
            f"color: {TEXT_PRIMARY}; background: transparent;"
        )
        # Trailing letter-spacing kompensatsiyasi (chap padding=letter-spacing)
        self._wordmark.setContentsMargins(s(16), 0, 0, 0)
        wm_layout.addWidget(self._wordmark)
        center.addWidget(wm_container)

        center.addSpacing(s(10))

        # Tagline — POINT OF SALE
        tagline = QLabel("POINT  ·  OF  ·  SALE")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tg_font = QFont()
        tg_font.setPixelSize(font(11))
        tg_font.setWeight(QFont.Weight.Bold)
        tg_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)
        tagline.setFont(tg_font)
        tagline.setStyleSheet(f"color: {GOLD}; background: transparent;")
        tagline.setContentsMargins(s(5), 0, 0, 0)
        center.addWidget(tagline)

        center.addSpacing(s(48))

        # Salom — kun bo'yicha
        self._greeting = QLabel(_greeting())
        self._greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gr_font = QFont()
        gr_font.setPixelSize(font(18))
        gr_font.setWeight(QFont.Weight.Light)
        self._greeting.setFont(gr_font)
        self._greeting.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent;"
        )
        center.addWidget(self._greeting)

        center.addSpacing(s(8))

        # Hint
        self._hint = QLabel("PIN  KIRITING")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_font = QFont()
        hint_font.setPixelSize(font(11))
        hint_font.setWeight(QFont.Weight.DemiBold)
        hint_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        self._hint.setFont(hint_font)
        self._hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._hint.setContentsMargins(s(4), 0, 0, 0)
        center.addWidget(self._hint)

        center.addSpacing(s(22))

        # PIN doti
        dots_row = QHBoxLayout()
        dots_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._dots = PinDots()
        dots_row.addWidget(self._dots)
        center.addLayout(dots_row)

        center.addSpacing(s(4))

        # Status (xato yoki muvaffaqiyat)
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setFixedHeight(s(28))
        self._status.setStyleSheet(
            f"font-size: {font(12)}px; font-weight: 600; color: {ERROR};"
            f" background: transparent;"
        )
        center.addWidget(self._status)

        center.addSpacing(s(28))

        # Numpad
        center.addLayout(self._build_numpad())

        root.addLayout(center)
        root.addStretch(1)

        # Pastki strip — server status
        root.addWidget(self._build_bottom_strip())

    # ── Numpad ────────────────────────────────────────
    def _build_numpad(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(s(14))
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.setContentsMargins(0, 0, 0, 0)

        rows = [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
            ["✕", "0", "⌫"],
        ]
        for keys in rows:
            row = QHBoxLayout()
            row.setSpacing(s(16))
            row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            for k in keys:
                kind = "digit"
                if k == "✕":
                    kind = "clear"
                elif k == "⌫":
                    kind = "back"
                btn = _make_button(k, kind)
                btn.clicked.connect(lambda _, key=k: self._on_key(key))
                row.addWidget(btn)
            v.addLayout(row)
        return v

    # ── Pastki status strip ──────────────────────────
    def _build_bottom_strip(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(s(58))
        h = QHBoxLayout(w)
        h.setContentsMargins(s(36), s(8), s(36), s(22))

        # Chap: server status
        self._conn_label = QLabel("●   Aloqa tekshirilmoqda")
        conn_font = QFont()
        conn_font.setPixelSize(font(11))
        conn_font.setWeight(QFont.Weight.DemiBold)
        conn_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        self._conn_label.setFont(conn_font)
        self._conn_label.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        h.addWidget(self._conn_label)

        h.addStretch()

        # O'ng: versiya — TEXT_MUTED (TEXT_DIM ko'rinmas darajada edi)
        version = QLabel("v1.0   ·   POWERED  BY  URY")
        version.setAlignment(Qt.AlignmentFlag.AlignRight)
        vfont = QFont()
        vfont.setPixelSize(font(10))
        vfont.setWeight(QFont.Weight.Medium)
        vfont.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        version.setFont(vfont)
        version.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h.addWidget(version)
        return w

    # ── Numpad input ──────────────────────────────────
    def _on_key(self, key: str):
        if key == "✕":
            self._digits = ""
        elif key == "⌫":
            self._digits = self._digits[:-1]
        elif len(self._digits) < 4:
            self._digits += key

        self._dots.set_filled(len(self._digits))
        # Yangi kiritishda eski xato matnini tozalash
        if self._status.text() and self._digits:
            self._status.setText("")

        if len(self._digits) == 4:
            QTimer.singleShot(160, self._on_complete)

    def _on_complete(self):
        pin = self._digits
        self._verify_pin(pin)

    def _reset_input(self):
        self._digits = ""
        self._dots.set_filled(0)

    # ── PIN tekshirish ────────────────────────────────
    def _verify_pin(self, pin: str):
        cashiers = get_cashiers()
        if cashiers:
            for c in cashiers:
                if c.get("pin") == pin:
                    logger.info(
                        "Kassir aniqlandi: %s",
                        c.get("full_name") or c.get("name"),
                    )
                    self._on_success(c)
                    return
            self._on_wrong_pin()
            return

        # Fallback: qurilma PIN
        if verify_pin(pin):
            logger.info("Qurilma PIN tasdiqlandi")
            self._on_success(None)
        else:
            self._on_wrong_pin()

    # ── Success / error oqimi ────────────────────────
    def _on_success(self, cashier):
        self._dots.set_success()
        name = ""
        if isinstance(cashier, dict):
            name = (cashier.get("full_name") or cashier.get("name") or "").strip()
        msg = f"Xush kelibsiz, {name}" if name else "Xush kelibsiz"
        self._status.setStyleSheet(
            f"font-size: {font(12)}px; font-weight: 700; color: {SUCCESS};"
            f" background: transparent;"
        )
        self._status.setText(msg)
        QTimer.singleShot(280, lambda: self._finish(cashier))

    def _finish(self, cashier):
        self.login_successful.emit(cashier)
        self.close()

    def _on_wrong_pin(self):
        self._dots.set_error()
        self._show_error("Noto'g'ri PIN. Qaytadan urinib ko'ring")
        QTimer.singleShot(750, self._reset_input)

    def _show_error(self, text: str):
        self._status.setStyleSheet(
            f"font-size: {font(12)}px; font-weight: 700; color: {ERROR};"
            f" background: transparent;"
        )
        self._status.setText(text)
        QTimer.singleShot(2400, self._clear_status_if_idle)

    def _show_status(self, text: str, color: str = ACTIVE):
        self._status.setStyleSheet(
            f"font-size: {font(12)}px; font-weight: 600; color: {color};"
            f" background: transparent;"
        )
        self._status.setText(text)

    def _clear_status_if_idle(self):
        # Foydalanuvchi yangi PIN kiritmagan bo'lsa tozalaymiz
        if not self._digits:
            self._status.setText("")

    # ── Background auto-login ─────────────────────────
    def _start_auto_login(self):
        self._auto_worker = AutoLoginWorker(self.api)
        self._auto_worker.result_ready.connect(self._on_auto_login)
        self._auto_worker.start()

    def _on_auto_login(self, success: bool, message: str):
        self._api_ready = success
        if success:
            logger.info("Background auto-login muvaffaqiyatli")
            self.api.reload_settings()
            # Server brand_name'ni yangilagan bo'lishi mumkin — wordmark'ni refresh
            self._refresh_wordmark()
            self._set_conn_state("online")
            self._show_status("✓  Tizim tayyor", SUCCESS)
            QTimer.singleShot(1500, lambda: self._clear_status_if_idle())
        else:
            logger.warning("Background auto-login xatosi: %s", message)
            cached = get_cashiers()
            if cached:
                self._set_conn_state("offline_cached")
            else:
                self._set_conn_state("offline_empty")

    def _refresh_wordmark(self):
        """Auto-login dan keyin yoki config yangilangach brand_name'ni qo'llash."""
        if not hasattr(self, "_wordmark"):
            return
        try:
            cfg = load_config()
        except Exception:
            return
        new_text = (
            cfg.get("brand_name") or cfg.get("company") or ""
        )
        new_text = str(new_text).strip().upper() or "POS"
        if self._wordmark.text() != new_text:
            self._wordmark.setText(new_text)

    def _set_conn_state(self, state: str):
        """Pastki strip dagi server status indikatori."""
        if state == "online":
            text = "●   Online   ·   Server bilan aloqa o'rnatildi"
            color = SUCCESS
        elif state == "offline_cached":
            text = "●   Oflayn rejim   ·   Saqlangan ma'lumotlar bilan"
            color = WARN
        elif state == "offline_empty":
            text = "●   Server bilan aloqa yo'q"
            color = ERROR
        else:
            text = "●   Aloqa tekshirilmoqda"
            color = TEXT_MUTED

        self._conn_label.setText(text)
        font_obj = QFont()
        font_obj.setPixelSize(font(11))
        font_obj.setWeight(QFont.Weight.DemiBold)
        font_obj.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        self._conn_label.setFont(font_obj)
        self._conn_label.setStyleSheet(
            f"color: {color}; background: transparent;"
        )
