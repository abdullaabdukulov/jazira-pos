"""Adaptive chek yaratuvchi — ESC/POS va TSPL protokollarini qo'llaydi.

Har bir printer uchun alohida driver (ESC/POS yoki TSPL) va qog'oz kengligi
(width_mm) sozlash mumkin. Yangi protokol qo'shish uchun `BaseReceipt`
dan meros olib `_render()` ni amalga oshirish yetarli.

Public API:
    build_customer_receipt(order, payments, config, printer_cfg) -> bytes
    build_production_receipt(order, items, unit_name, printer_cfg) -> bytes
    build_cancel_production_receipt(order, items, unit_name, reason, printer_cfg) -> bytes
    build_test_receipt(printer_name, printer_cfg) -> bytes
    build_z_report_receipt(report_data, printer_cfg) -> bytes
    build_cash_drawer_command(printer_cfg) -> bytes

printer_cfg = {"driver": "escpos"|"tspl", "width_mm": 58|80|...}
"""

from datetime import datetime
from database.models import Item
from core.logger import get_logger

logger = get_logger(__name__)

ORDER_TYPE_LABELS = {
    "Shu yerda": "Xarid cheki",
    "Saboy": "Olib ketish cheki",
    "Dastavka": "Dastavka cheki",
    "Dastavka Saboy": "Dastavka cheki",
}

# Default printer config — ko'rsatilmasa shu ishlatiladi
DEFAULT_PRINTER_CFG = {"driver": "escpos", "width_mm": 58, "codepage": "cp1251"}


# ==========================================================
#  Adaptive Receipt Interface
# ==========================================================
class BaseReceipt:
    """Chek yaratuvchi uchun umumiy interfeys.

    Konkret protokol klassi (`ESCPOSReceipt`, `TSPLReceipt`)
    quyidagilarni amalga oshiradi:
      - add_text(), add_center(), add_line(), add_separator()
      - build() -> bytes
    """

    def __init__(self, width_mm: int = 58):
        self.width_mm = width_mm
        # Qog'oz kengligi bo'yicha qator sig'imi (small font)
        # Empirik: 58mm ≈ 32 char, 80mm ≈ 48 char (1mm ≈ 0.55 char)
        self.line_chars = max(20, int(width_mm * 0.55))

    def add_text(self, text: str): raise NotImplementedError
    def add_center(self, text: str, big: bool = False): raise NotImplementedError
    def add_line(self, left: str, right: str): raise NotImplementedError
    def add_separator(self, char: str = "-"): raise NotImplementedError
    def build(self) -> bytes: raise NotImplementedError


# ==========================================================
#  ESC/POS Implementation (XP-58 IIH va shunga o'xshash chek printerlari)
# ==========================================================
class ESCPOSReceipt(BaseReceipt):
    """ESC/POS protokolida chek (raw baytlar).

    Standart ESC/POS buyruqlari (Epson uyg'unligi):
      ESC @       - initialize
      ESC a n     - alignment (0=left, 1=center, 2=right)
      ESC ! n     - print mode (n=0x10/0x20: double-height/width)
      ESC d n     - feed n lines
      GS V m      - paper cut (m=0 full, 1 partial)
      ESC t n     - codepage select (n=17 PC866, 46 WPC1251)
      ESC R n     - international char set (7 = Russia, 0 = USA)

    Codepage matn kodirovkasi:
      cp866 — DOS/PC866 (CIS Cyrillic, ESC t 17)
      cp1251 — Windows-1251 (Russian, ESC t 46)

    Default cp1251 — XP-58 IIH va shunga o'xshash chek printerlari uchun
    eng keng tarqalgan.
    """

    INIT       = b"\x1b\x40"           # ESC @ — reset
    ALIGN_L    = b"\x1b\x61\x00"       # ESC a 0
    ALIGN_C    = b"\x1b\x61\x01"       # ESC a 1
    BOLD_ON    = b"\x1b\x45\x01"       # ESC E 1
    BOLD_OFF   = b"\x1b\x45\x00"       # ESC E 0
    # GS ! n — Character Size: yuqori 4 bit width-1, past 4 bit height-1
    # 0x11 = 2x width + 2x height (eng keng tarqalgan double)
    # GS ! Xprinter modellarida ESC ! ga qaraganda yaxshiroq qo'llaniladi
    # va belgilarni yopishtirib qo'ymaydi
    DBL_ON     = b"\x1d\x21\x11"       # GS ! 0x11 — 2x w + 2x h
    DBL_OFF    = b"\x1d\x21\x00"       # GS ! 0 — normal size
    # ESC SP n — character right-spacing in dots (default 0)
    # Big modeda biroz spacing qo'yamiz — belgilar yopishib qolmasin
    CHAR_SP_N  = b"\x1b\x20\x00"       # 0 dots — normal modda
    CHAR_SP_W  = b"\x1b\x20\x02"       # 2 dots — big modda
    CUT        = b"\x1d\x56\x42\x00"   # GS V B 0 — partial cut + feed
    FEED3      = b"\x1b\x64\x03"       # ESC d 3 — feed 3 lines
    INTL_RU    = b"\x1b\x52\x07"       # ESC R 7 — Russia char set

    # CRITICAL: Xitoyda ishlab chiqarilgan Xprinter, Goojprt va boshqa
    # modellarda Kanji (CJK) mode default yoqilgan — bytelarni GBK deb
    # interpret qilib xitoy belgilarga aylantiradi. ESC t (codepage) shu
    # rejimda inkor etiladi. Quyidagi buyruqlar Kanji ni o'chirish uchun:
    KANJI_OFF  = b"\x1c\x2e"           # FS . — Cancel Kanji (CJK) mode
    KANJI_OFF2 = b"\x1c\x21\x00"       # FS ! 0 — Kanji print mode = 0
    USERDEF_ON = b"\x1b\x25\x01"       # ESC % 1 — enable user-defined chars

    # Codepage table: encoding -> ESC t buyruq kodi
    CODEPAGE_TABLE = {
        "cp1251": b"\x1b\x74\x2e",     # ESC t 46 — Windows-1251 Russian
        "cp866":  b"\x1b\x74\x11",     # ESC t 17 — PC866 Cyrillic (DOS)
        "cp437":  b"\x1b\x74\x00",     # ESC t 0  — USA (default, no cyrillic)
    }

    def __init__(self, width_mm: int = 58, codepage: str = "cp1251"):
        super().__init__(width_mm)
        self.codepage = (codepage or "cp1251").lower()
        cp_cmd = self.CODEPAGE_TABLE.get(self.codepage, self.CODEPAGE_TABLE["cp1251"])
        self.buf = bytearray()
        # Init order matters:
        # 1. ESC @ — reset printer
        # 2. FS . — cancel Kanji mode (Xprinter/Goojprt da default yoqilgan!)
        # 3. FS ! 0 — kanji print mode off
        # 4. ESC R 7 — international char set Russia
        # 5. ESC t N — codepage tanlash (CP1251 yoki CP866)
        self.buf += (
            self.INIT
            + self.KANJI_OFF
            + self.KANJI_OFF2
            + self.INTL_RU
            + cp_cmd
        )

    def _encode(self, text: str) -> bytes:
        """Matnni tanlangan codepage ga aylantirish."""
        return str(text).encode(self.codepage, errors="replace")

    def add_text(self, text: str):
        self.buf += self.ALIGN_L + self._encode(str(text)) + b"\n"

    def add_center(self, text: str, big: bool = False):
        if big:
            # Big mode: char spacing qo'shamiz — belgilar yopishmasin
            self.buf += self.ALIGN_C + self.CHAR_SP_W + self.DBL_ON + self.BOLD_ON
            self.buf += self._encode(str(text)) + b"\n"
            self.buf += self.DBL_OFF + self.BOLD_OFF + self.CHAR_SP_N + self.ALIGN_L
        else:
            self.buf += self.ALIGN_C + self.BOLD_ON
            self.buf += self._encode(str(text)) + b"\n"
            self.buf += self.BOLD_OFF + self.ALIGN_L

    def add_line(self, left: str, right: str):
        """Chap-o'ng ajratilgan qator (Nomi ........ Summa)."""
        left, right = str(left), str(right)
        spaces = self.line_chars - len(left) - len(right)
        if spaces < 1:
            # Sig'masa — nom yangi qatorga
            self.buf += self._encode(left) + b"\n"
            spaces = self.line_chars - len(right)
            line = " " * max(1, spaces) + right
        else:
            line = left + " " * spaces + right
        self.buf += self.ALIGN_L + self._encode(line) + b"\n"

    def add_separator(self, char: str = "-"):
        self.buf += self.ALIGN_L + self._encode(char * self.line_chars) + b"\n"

    def build(self) -> bytes:
        # Oxirida feed + cut
        return bytes(self.buf + self.FEED3 + self.CUT)


# ==========================================================
#  TSPL Implementation (XP-365B label/stiker printerlari)
# ==========================================================
class TSPLReceipt(BaseReceipt):
    """TSPL (Stiker) formatida chek.

    Ishlatish: SIZE, GAP, DIRECTION, CODEPAGE, CLS, TEXT x,y,...
    Font 3 — kirill rus harflari, CP1251.
    """

    # Dots/mm: TSPL standart 8 dot/mm (203 DPI)
    DOTS_PER_MM = 8

    # Font 3 belgi kengligi (dots) — taxminiy
    FONT3_CHAR_W = 16

    def __init__(self, width_mm: int = 58):
        super().__init__(width_mm)
        self.width_dots = width_mm * self.DOTS_PER_MM
        # TSPL char sig'imi font3 ga qarab
        self.line_chars = max(16, self.width_dots // self.FONT3_CHAR_W - 2)
        self.lines = []
        self.y = 10
        self.step = 35

    @staticmethod
    def _safe(text: str) -> str:
        return str(text).replace('"', "'")

    def add_text(self, text: str):
        self.lines.append(f'TEXT 10,{self.y},"3",0,1,1,"{self._safe(text)}"\r\n')
        self.y += self.step

    def add_center(self, text: str, big: bool = False):
        font = "4" if big else "3"
        char_w = 24 if big else 16
        text_str = self._safe(text)
        x = max(10, (self.width_dots - len(text_str) * char_w) // 2)
        step = 45 if big else self.step
        self.lines.append(f'TEXT {x},{self.y},"{font}",0,1,1,"{text_str}"\r\n')
        self.y += step

    def add_line(self, left: str, right: str):
        left, right = self._safe(left), self._safe(right)
        spaces = self.line_chars - len(left) - len(right)
        if spaces < 1:
            spaces = 1
        combined = left + " " * spaces + right
        self.lines.append(f'TEXT 10,{self.y},"3",0,1,1,"{combined}"\r\n')
        self.y += self.step

    def add_separator(self, char: str = "-"):
        self.lines.append(f'TEXT 10,{self.y},"3",0,1,1,"{char * self.line_chars}"\r\n')
        self.y += self.step

    def build(self) -> bytes:
        height_mm = max(20, int((self.y + 40) / self.DOTS_PER_MM))
        header = (
            f"SIZE {self.width_mm} mm,{height_mm} mm\r\n"
            f"GAP 0 mm,0 mm\r\n"
            f"DIRECTION 1\r\n"
            f"CODEPAGE 1251\r\n"
            f"CLS\r\n"
        )
        body = bytearray(header.encode("cp1251", errors="replace"))
        for line in self.lines:
            body += line.encode("cp1251", errors="replace")
        body += b"PRINT 1\r\n"
        return bytes(body)


# ==========================================================
#  Factory — printer_cfg ga qarab to'g'ri receipt klassni qaytaradi
# ==========================================================
def _make_receipt(printer_cfg: dict = None) -> BaseReceipt:
    cfg = {**DEFAULT_PRINTER_CFG, **(printer_cfg or {})}
    driver = (cfg.get("driver") or "escpos").lower()
    width = int(cfg.get("width_mm") or 58)
    codepage = (cfg.get("codepage") or "cp1251").lower()

    if driver == "tspl":
        return TSPLReceipt(width_mm=width)
    # default va noma'lum driver — ESC/POS (eng keng tarqalgan)
    if driver != "escpos":
        logger.warning("Noma'lum driver '%s' — ESC/POS ishlatildi", driver)
    return ESCPOSReceipt(width_mm=width, codepage=codepage)


# ==========================================================
#  Yordamchi funksiyalar
# ==========================================================
def _format_amount(amount) -> str:
    return f"{float(amount):,.0f}"


def _order_type_label(order_type: str) -> str:
    return ORDER_TYPE_LABELS.get(order_type, "Chek")


def get_item_groups_map(items: list) -> dict:
    item_codes = [
        item.get("item_code", item.get("item", ""))
        for item in items
        if item.get("item_code") or item.get("item")
    ]
    if not item_codes:
        return {}
    try:
        rows = Item.select(Item.item_code, Item.item_group).where(
            Item.item_code.in_(item_codes)
        )
        return {row.item_code: row.item_group or "" for row in rows}
    except Exception as e:
        logger.error("Item group olishda xatolik: %s", e)
        return {}


def _get_receipt_footer() -> str:
    try:
        from core.config import load_config
        return load_config().get("receipt_footer", "") or ""
    except Exception:
        return ""


# ==========================================================
#  Public API — barcha funksiyalar `printer_cfg` qabul qiladi
# ==========================================================
def build_customer_receipt(
    order_data: dict,
    payments_list: list,
    config: dict,
    printer_cfg: dict = None,
) -> bytes:
    """Mijoz cheki — driver/width adaptive."""
    r = _make_receipt(printer_cfg)

    company = config.get("company", "JAZIRA POS")
    r.add_center(company, big=True)

    order_type = order_data.get("order_type", "")
    r.add_center(_order_type_label(order_type))
    r.add_text(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    customer = order_data.get("customer", "")
    if order_type in ("Dastavka", "Dastavka Saboy") and customer and customer != "guest":
        r.add_separator("-")
        r.add_text(f"Mijoz: {customer}")

    ticket_number = order_data.get("ticket_number", "")
    if ticket_number:
        r.add_separator("=")
        r.add_center(f"Stiker raqami: {ticket_number}")
        r.add_separator("=")

    r.add_line("Nomi", "Soni Summa")
    r.add_separator("-")

    items_list = order_data.get("items", [])
    total_amount = order_data.get("total_amount", 0.0)

    for item in items_list:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        price = float(item.get("price", item.get("rate", 0)))
        right_part = f"{qty}  {_format_amount(qty * price)}"

        if len(name) + len(right_part) > r.line_chars - 1:
            r.add_text(name[:r.line_chars])
            r.add_line("", right_part)
        else:
            r.add_line(name, right_part)

    r.add_separator("=")
    r.add_line("JAMI:", f"{_format_amount(total_amount)} UZS")
    r.add_separator("=")

    r.add_text("TO'LOVLAR:")
    for p in payments_list:
        if float(p.get("amount", 0)) > 0:
            r.add_line(f"  {p['mode_of_payment']}:", f"{_format_amount(p['amount'])} UZS")

    total_paid = sum(float(p.get("amount", 0)) for p in payments_list)
    change = max(0, total_paid - total_amount)
    if change > 0:
        r.add_separator("-")
        r.add_line("QAYTIM:", f"{_format_amount(change)} UZS")

    comment = order_data.get("comment", "")
    if comment:
        r.add_text(f"Izoh: {comment}")

    footer = _get_receipt_footer()
    r.add_center(footer if footer else "Xaridingiz uchun rahmat!")

    return r.build()


def build_production_receipt(
    order_data: dict,
    unit_items: list,
    unit_name: str,
    printer_cfg: dict = None,
) -> bytes:
    """Oshxona/Bar uchun chek."""
    r = _make_receipt(printer_cfg)
    r.add_center(f"--- {unit_name} ---")

    order_type = order_data.get("order_type", "")
    r.add_center(order_type)
    r.add_center(datetime.now().strftime("%H:%M:%S"))

    ticket_number = order_data.get("ticket_number", "")
    if ticket_number:
        r.add_center(f"Stiker №{ticket_number}")

    customer = order_data.get("customer", "")
    if order_type in ("Dastavka", "Dastavka Saboy") and customer and customer != "guest":
        r.add_text(f"Mijoz: {customer}")

    r.add_separator("=")

    for item in unit_items:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        # Nom uzun bo'lsa qisqartirish
        max_name_len = max(10, r.line_chars - 6)
        r.add_line(name[:max_name_len], f"x{qty}")

    r.add_separator("=")

    comment = order_data.get("comment", "")
    if comment:
        r.add_text(f"IZOH: {comment}")

    return r.build()


def build_cancel_production_receipt(
    order_data: dict,
    unit_items: list,
    unit_name: str,
    cancel_reason: str,
    printer_cfg: dict = None,
) -> bytes:
    """Bekor qilingan buyurtma uchun production stiker."""
    r = _make_receipt(printer_cfg)
    r.add_center(f"--- {unit_name} ---")
    r.add_separator("*")
    r.add_center("!! QAYTARILDI !!", big=True)
    r.add_separator("*")

    order_type = order_data.get("order_type", "")
    r.add_center(order_type)
    r.add_center(datetime.now().strftime("%H:%M:%S"))

    ticket_number = order_data.get("ticket_number", "")
    if ticket_number:
        r.add_center(f"Stiker №{ticket_number}")

    r.add_separator("=")

    for item in unit_items:
        name = item.get("item_name", item.get("name", ""))
        qty = int(item.get("qty", 0))
        max_name_len = max(10, r.line_chars - 6)
        r.add_line(name[:max_name_len], f"x{qty}")

    r.add_separator("=")

    if cancel_reason:
        r.add_text("SABAB:")
        chunk = max(15, r.line_chars - 4)
        for i in range(0, len(cancel_reason), chunk):
            r.add_text("  " + cancel_reason[i:i + chunk])

    r.add_separator("-")
    return r.build()


def build_test_receipt(printer_name: str = "Test", printer_cfg: dict = None) -> bytes:
    r = _make_receipt(printer_cfg)
    r.add_center("SINOV CHEKI", big=True)
    r.add_center(f"Printer: {printer_name}")
    r.add_center(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
    r.add_separator("=")
    cfg = {**DEFAULT_PRINTER_CFG, **(printer_cfg or {})}
    r.add_text(f"Driver: {cfg.get('driver')}")
    r.add_text(f"Kenglik: {cfg.get('width_mm')} mm")
    r.add_separator("=")
    r.add_center("OK!")
    return r.build()


def build_cash_drawer_command(printer_cfg: dict = None) -> bytes:
    """Kassa tortmasini ochish — ESC p 0 (universal)."""
    return b"\x1b\x70\x00\x19\xfa"


def build_z_report_receipt(report_data: dict, printer_cfg: dict = None) -> bytes:
    """Z-otchyot (smena yopilishi)."""
    r = _make_receipt(printer_cfg)

    terminal = report_data.get("terminal_name", "JAZIRA POS")
    r.add_center(terminal)
    r.add_center("Z-OTCHYOT", big=True)
    r.add_separator("=")

    r.add_line("Smena:", str(report_data.get("shift_id", "—"))[-20:])
    r.add_line("Kassir:", report_data.get("cashier", "—"))
    r.add_line("Ochildi:", report_data.get("opened_at", "—"))
    r.add_line("Yopildi:", report_data.get("closed_at", "—"))
    r.add_line("Cheklar:", str(report_data.get("total_invoices", 0)))
    r.add_separator("=")

    r.add_center("TO'LOV TURLARI")
    r.add_separator("-")

    _CASH_KEYS = {"cash", "naqd", "naqd pul"}
    for p in report_data.get("payments", []):
        mop = p.get("mode_of_payment", "")
        expected = float(p.get("expected_amount", 0))
        is_cash = mop.lower().strip() in _CASH_KEYS
        r.add_text(f"{mop}:")
        r.add_line("  Sotuv:", f"{_format_amount(expected)} UZS")
        if is_cash:
            r.add_line("  Qaytarish:", "0 UZS")

    r.add_separator("-")
    r.add_line("SOTUV:", f"{_format_amount(report_data.get('total_sales', 0))} UZS")
    r.add_separator("=")

    r.add_center("NAZORAT SANOG'I")
    r.add_separator("-")

    expected_cash = float(report_data.get("expected_cash", 0))
    actual_cash = float(report_data.get("actual_cash", 0))
    cash_diff = float(report_data.get("cash_diff", 0))

    r.add_line("Kassada kerak:", f"{_format_amount(expected_cash)}")
    r.add_line("Sanaldi:", f"{_format_amount(actual_cash)}")
    r.add_separator("-")

    if abs(cash_diff) < 1:
        r.add_line("Farq:", "0  OK")
    elif cash_diff < 0:
        r.add_line("KAMOMAD:", f"-{_format_amount(abs(cash_diff))} !")
    else:
        r.add_line("Ortiqcha:", f"+{_format_amount(cash_diff)}")

    r.add_separator("=")
    r.add_center("PUL YECHISH")
    r.add_separator("-")
    r.add_line("Tur:", "Smena yopilishi")
    r.add_line("Summa:", f"{_format_amount(actual_cash)} UZS")
    r.add_line("Kassir:", report_data.get("cashier", "—"))
    r.add_separator("=")

    r.add_center("Smena yopildi!")
    r.add_center(report_data.get("closed_at", "—"))

    return r.build()
