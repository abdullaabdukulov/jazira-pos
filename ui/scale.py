"""Markaziy responsive scaling moduli.

Barcha UI komponentlari bu moduldan foydalanib o'lchamlarni
ekran hajmiga mos ravishda hisoblaydi.

Baza: 1920×1080 (Full HD) — 1.0x scale
Katta ekran: 2560×1440 → 1.0x (element o'lchami o'zgarmaydi, ko'proq joy bo'ladi)
Kichik ekran: 1366×768 → ~0.71x (kichikroq elementlar)

MUHIM: Scale faqat PASTGA ishlaydi (kichik ekranlar uchun).
Katta resolutsiyali ekranlarda (2K, 4K) elementlar 1:1 qoladi —
bu ko'proq ishchi maydoni beradi va 15.6" noutbuklarda ham yaxshi ko'rinadi.
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication
from core.logger import get_logger

logger = get_logger(__name__)

_scale_factor: float | None = None
_font_scale: float | None = None

BASE_WIDTH = 1920
BASE_HEIGHT = 1080


def _init_scale():
    global _scale_factor, _font_scale
    if _scale_factor is not None:
        return

    try:
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w, h = geo.width(), geo.height()
            sx = w / BASE_WIDTH
            sy = h / BASE_HEIGHT
            raw = min(sx, sy)
            # Katta resolutsiyalarda 1.0 dan oshirmaymiz —
            # 2560x1440 noutbukda elementlar kattalashmasligi kerak
            _scale_factor = min(raw, 1.0)
            _font_scale = max(0.75, min(raw, 1.0))
            logger.info("Ekran: %dx%d, scale: %.2f, font_scale: %.2f", w, h, _scale_factor, _font_scale)
        else:
            _scale_factor = 1.0
            _font_scale = 1.0
    except Exception:
        _scale_factor = 1.0
        _font_scale = 1.0


def s(px: int) -> int:
    """Pixel qiymatini ekran hajmiga moslash.

    Ishlatish: setFixedHeight(s(48)), setContentsMargins(s(10), s(4), s(10), s(4))
    """
    _init_scale()
    return max(1, round(px * _scale_factor))


def sf(px: int) -> float:
    """Float qaytaruvchi scaling — splitter va boshqa float kerak joylar uchun."""
    _init_scale()
    return px * _scale_factor


def font(px: int) -> int:
    """Font o'lchamini ekranga moslash.

    Ishlatish: f"font-size: {font(16)}px"
    Minimum 9px — 13.6" kichik ekranlarda ham o'qilishi uchun.
    """
    _init_scale()
    return max(9, round(px * _font_scale))


def css(template: str) -> str:
    """CSS stringdagi px qiymatlarini avtomatik scale qilish.

    Ishlatish:
        css("padding: {10}px {20}px; font-size: {16}px; border-radius: {8}px;")

    Har bir {N} → s(N) ga almashadi.
    """
    import re

    def _replace(m):
        val = int(m.group(1))
        return str(s(val))

    return re.sub(r'\{(\d+)\}', _replace, template)


def screen_ratio() -> float:
    """Joriy scale faktorni qaytarish (diagnostika uchun)."""
    _init_scale()
    return _scale_factor
