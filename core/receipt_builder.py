"""ESC/POS chek ma'lumotlarini yaratish — faqat baytlar, I/O yo'q.

Bu modul printer.py dan ajratilgan: chek formatini tayyorlaydi,
lekin printerga yuborish boshqa modulda (printer.py).
"""

from datetime import datetime
from database.models import Item, db
from core.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────
#  ESC/POS buyruqlari
# ──────────────────────────────────────────────────
ESC = b'\x1b'
GS = b'\x1d'

CMD_INIT = ESC + b'\x40'
CMD_ALIGN_CENTER = ESC + b'\x61\x01'
CMD_ALIGN_LEFT = ESC + b'\x61\x00'
CMD_BOLD_ON = ESC + b'\x45\x01'
CMD_BOLD_OFF = ESC + b'\x45\x00'
CMD_DOUBLE_ON = GS + b'\x21\x11'
CMD_DOUBLE_OFF = GS + b'\x21\x00'
CMD_FONT_B = ESC + b'\x4d\x01'
CMD_FONT_A = ESC + b'\x4d\x00'
CMD_CUT = GS + b'\x56\x41\x03'
CMD_FEED = ESC + b'\x64\x04'
CMD_OPEN_DRAWER = ESC + b'\x70\x00\x19\xfa'

CHARS_PER_LINE = 48
CHARS_DOUBLE = 24

ORDER_TYPE_LABELS = {
    "Shu yerda": "Xarid cheki",
    "Saboy": "Olib ketish cheki",
    "Dastavka": "Dastavka cheki",
    "Dastavka Saboy": "Dastavka cheki",
}


# ──────────────────────────────────────────────────
#  Matn formatlash
# ──────────────────────────────────────────────────
def _encode(text: str) -> bytes:
    try:
        return text.encode("cp866")
    except UnicodeEncodeError:
        return text.encode("utf-8", errors="replace")


def _line(left: str, right: str = "", fill: str = " ", width: int = CHARS_PER_LINE) -> bytes:
    if not right:
        return _encode(left[:width] + "\n")
    space = width - len(left) - len(right)
    if space < 1:
        space = 1
    return _encode(left + fill * space + right + "\n")


def _center_text(text: str) -> bytes:
    return CMD_ALIGN_CENTER + _encode(text + "\n") + CMD_ALIGN_LEFT


def _separator(char: str = "-", width: int = CHARS_PER_LINE) -> bytes:
    return _encode(char * width + "\n")


def _format_amount(amount) -> str:
    return f"{float(amount):,.0f}"


def _order_type_label(order_type: str) -> str:
    return ORDER_TYPE_LABELS.get(order_type, "Chek")


# ──────────────────────────────────────────────────
#  Item groups mapping (lokal DB)
# ──────────────────────────────────────────────────
def get_item_groups_map(items: list) -> dict:
    """Lokal DB dan itemlarning item_group ini oladi."""
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


# ──────────────────────────────────────────────────
#  Chek yaratish
# ──────────────────────────────────────────────────
def build_customer_receipt(order_data: dict, payments_list: list, config: dict) -> bytes:
    """Mijoz uchun to'liq chek — turiga qarab sarlavha o'zgaradi."""
    items_list = order_data.get("items", [])
    total_amount = order_data.get("total_amount", 0.0)
    order_type = order_data.get("order_type", "")
    ticket_number = order_data.get("ticket_number", "")
    comment = order_data.get("comment", "")
    customer = order_data.get("customer", "")

    company = config.get("company", "JAZIRA POS")

    total_paid = sum(float(p.get("amount", 0)) for p in payments_list)
    change = max(0, total_paid - total_amount)
    date_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

    data = bytearray()
    data += CMD_INIT

    # Sarlavha
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(company + "\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode(_order_type_label(order_type) + "\n")
    data += _encode(date_str + "\n")
    data += CMD_ALIGN_LEFT

    # Dastavka → mijoz nomi
    if order_type in ("Dastavka", "Dastavka Saboy") and customer and customer != "guest":
        data += _separator()
        data += CMD_BOLD_ON
        data += _line("Mijoz:", customer)
        data += CMD_BOLD_OFF

    # Stiker raqami
    if ticket_number:
        data += _encode("\n")
        data += _separator("=")
        data += CMD_ALIGN_CENTER + CMD_BOLD_ON + CMD_DOUBLE_ON
        data += _encode(f"STIKER: {ticket_number}\n")
        data += CMD_DOUBLE_OFF + CMD_BOLD_OFF + CMD_ALIGN_LEFT
        data += _separator("=")

    # Tovarlar
    data += _encode("\n")
    data += CMD_BOLD_ON
    data += _line("Nomi", "Soni   Summa")
    data += CMD_BOLD_OFF
    data += _separator()

    for item in items_list:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        price = float(item.get("price", item.get("rate", 0)))
        line_total = qty * price
        qty_str = str(qty)
        total_str = _format_amount(line_total)
        right_part = f"{qty_str:>4}  {total_str:>10}"

        if len(name) + len(right_part) + 1 > CHARS_PER_LINE:
            data += _encode(name[:CHARS_PER_LINE] + "\n")
            data += _encode(right_part.rjust(CHARS_PER_LINE) + "\n")
        else:
            data += _line(name, right_part)

    # Jami
    data += _separator("=")
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _line("JAMI:", f"{_format_amount(total_amount)} UZS", width=CHARS_DOUBLE)
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _separator("=")

    # To'lovlar
    data += _encode("\n")
    data += CMD_BOLD_ON
    data += _encode("TO'LOVLAR:\n")
    data += CMD_BOLD_OFF
    for p in payments_list:
        if float(p.get("amount", 0)) > 0:
            data += _line(f"  {p['mode_of_payment']}:", f"{_format_amount(p['amount'])} UZS")

    # Qaytim
    if change > 0:
        data += _separator()
        data += CMD_BOLD_ON
        data += _line("QAYTIM:", f"{_format_amount(change)} UZS")
        data += CMD_BOLD_OFF

    # Izoh
    if comment:
        data += _encode(f"\nIzoh: {comment}\n")

    # Pastki qism
    data += _encode("\n")
    data += _center_text("Xaridingiz uchun rahmat!")
    data += CMD_FEED
    data += CMD_CUT

    return bytes(data)


def build_production_receipt(order_data: dict, unit_items: list, unit_name: str) -> bytes:
    """Production unit uchun chek — turiga qarab format o'zgaradi."""
    order_type = order_data.get("order_type", "")
    ticket_number = order_data.get("ticket_number", "")
    comment = order_data.get("comment", "")
    customer = order_data.get("customer", "")
    date_str = datetime.now().strftime("%H:%M:%S")

    data = bytearray()
    data += CMD_INIT

    # Sarlavha
    data += CMD_ALIGN_CENTER + CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(f"--- {unit_name} ---\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF

    # Buyurtma turi + vaqt
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(f"{order_type}\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode(date_str + "\n")

    # Stiker
    if ticket_number:
        data += _encode("\n")
        data += CMD_BOLD_ON + CMD_DOUBLE_ON
        data += _encode(f"# {ticket_number}\n")
        data += CMD_DOUBLE_OFF + CMD_BOLD_OFF

    # Dastavka → mijoz nomi
    if order_type in ("Dastavka", "Dastavka Saboy") and customer and customer != "guest":
        data += CMD_BOLD_ON
        data += _encode(f"Mijoz: {customer}\n")
        data += CMD_BOLD_OFF

    data += CMD_ALIGN_LEFT
    data += _separator("=")

    # Tovarlar — katta shrift
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    for item in unit_items:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        right = f"x{qty}"
        if len(name) + len(right) + 1 > CHARS_DOUBLE:
            name = name[:CHARS_DOUBLE - len(right) - 1]
        data += _line(name, right, width=CHARS_DOUBLE)
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF

    data += _separator("=")

    # Izoh
    if comment:
        data += CMD_BOLD_ON
        data += _encode(f"IZOH: {comment}\n")
        data += CMD_BOLD_OFF

    data += CMD_FEED
    data += CMD_CUT

    return bytes(data)


def build_test_receipt(printer_name: str = "Test") -> bytes:
    """Sinov cheki."""
    data = bytearray()
    data += CMD_INIT
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode("SINOV CHEKI\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode(f"Printer: {printer_name}\n")
    data += _encode(datetime.now().strftime("%Y-%m-%d  %H:%M:%S") + "\n")
    data += _separator()
    data += _center_text("Printer ishlayapti!")
    data += CMD_FEED
    data += CMD_CUT
    return bytes(data)


def build_cash_drawer_command() -> bytes:
    """Cash drawer ochish buyrug'i."""
    return CMD_INIT + CMD_OPEN_DRAWER



# ──────────────────────────────────────────────────
#  Z-Otchyot (Smena hisoboti)
# ──────────────────────────────────────────────────
def build_z_report_receipt(report_data: dict) -> bytes:
    """Smena yopilish Z-otchyoti cheki.

    report_data kalitlari:
      terminal_name  — restoran/filial nomi
      shift_id       — POS Opening Entry nomi
      cashier        — kassir ismi
      opened_at      — smena ochilgan vaqt (str)
      closed_at      — smena yopilgan vaqt (str)
      payments       — list of {mode_of_payment, expected_amount, closing_amount}
      total_invoices — jami cheklar soni
      total_sales    — jami sotuv summasi
      expected_cash  — kassada bo'lishi kerak (kassirga yashirilgan)
      actual_cash    — kassir sanagan haqiqiy naqd pul
      cash_diff      — farq (actual - expected)
    """
    terminal = report_data.get("terminal_name", "JAZIRA POS")
    shift_id = report_data.get("shift_id", "—")
    cashier = report_data.get("cashier", "—")
    opened_at = report_data.get("opened_at", "—")
    closed_at = report_data.get("closed_at", "—")
    payments = report_data.get("payments", [])
    total_invoices = report_data.get("total_invoices", 0)
    total_sales = float(report_data.get("total_sales", 0))
    expected_cash = float(report_data.get("expected_cash", 0))
    actual_cash = float(report_data.get("actual_cash", 0))
    cash_diff = float(report_data.get("cash_diff", 0))

    data = bytearray()
    data += CMD_INIT

    # ── Sarlavha ───────────────────────────────────
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(terminal[:CHARS_DOUBLE] + "\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode("Z-OTCHYOT\n")
    data += CMD_ALIGN_LEFT
    data += _separator("=")

    # ── Smena ma'lumotlari ─────────────────────────
    data += _line("Smena:", shift_id[-20:])
    data += _line("Kassir:", cashier)
    data += _line("Ochildi:", opened_at)
    data += _line("Yopildi:", closed_at)
    data += _line("Jami cheklar:", str(total_invoices))
    data += _separator("=")

    # ── To'lov turlari bo'yicha tushum ────────────
    data += CMD_ALIGN_CENTER + CMD_BOLD_ON
    data += _encode("TO'LOV TURLARI\n")
    data += CMD_BOLD_OFF + CMD_ALIGN_LEFT
    data += _separator("-")

    _CASH_KEYS = {"cash", "naqd", "naqd pul"}

    for p in payments:
        mop = p.get("mode_of_payment", "")
        expected = float(p.get("expected_amount", 0))
        is_cash = mop.lower().strip() in _CASH_KEYS

        data += CMD_BOLD_ON
        data += _encode(f"{mop}:\n")
        data += CMD_BOLD_OFF
        data += _line("  Sotuv:", f"{_format_amount(expected)} UZS")
        if is_cash:
            data += _line("  Qaytarish:", "0 UZS")

    data += _separator("-")
    data += CMD_BOLD_ON
    data += _line("JAMI SOTUV:", f"{_format_amount(total_sales)} UZS")
    data += CMD_BOLD_OFF
    data += _separator("=")

    # ── Nazorat sanog'i ────────────────────────────
    # Kassirga ekranda KO'RSATILMAGAN, lekin chekda TO'LIQ chiqadi
    data += CMD_ALIGN_CENTER + CMD_BOLD_ON
    data += _encode("NAZORAT SANOG'I\n")
    data += CMD_BOLD_OFF + CMD_ALIGN_LEFT
    data += _separator("-")

    data += _line("Kassada bo'lishi kerak:", f"{_format_amount(expected_cash)} UZS")
    data += _separator("-")
    data += CMD_BOLD_ON
    data += _line("Kassir sanagan summa:", f"{_format_amount(actual_cash)} UZS")
    data += CMD_BOLD_OFF
    data += _separator("-")

    if abs(cash_diff) < 1:
        data += CMD_BOLD_ON
        data += _line("Farq:", "0 UZS  OK")
        data += CMD_BOLD_OFF
    elif cash_diff < 0:
        # Kamomad — kassir kam topshirdi
        data += CMD_BOLD_ON
        data += _line("KAMOMAD:", f"-{_format_amount(abs(cash_diff))} UZS !")
        data += CMD_BOLD_OFF
    else:
        # Ortiqcha — kassir ko'p topshirdi
        data += _line("Ortiqcha:", f"+{_format_amount(cash_diff)} UZS")

    data += _separator("=")

    # ── Naqd pul yechish ──────────────────────────
    data += CMD_ALIGN_CENTER + CMD_BOLD_ON
    data += _encode("NAQD PUL YECHISH\n")
    data += CMD_BOLD_OFF + CMD_ALIGN_LEFT
    data += _separator("-")
    data += _line("Tur:", "Smena yopilishi")
    data += CMD_BOLD_ON
    data += _line("Summa:", f"{_format_amount(actual_cash)} UZS")
    data += CMD_BOLD_OFF
    data += _line("Kassir:", cashier)
    data += _separator("=")

    # ── Yakuniy xabar ──────────────────────────────
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON
    data += _encode("Smena muvaffaqiyatli\n")
    data += _encode("yopildi!\n")
    data += CMD_BOLD_OFF
    data += _encode(closed_at + "\n")
    data += CMD_ALIGN_LEFT

    data += CMD_FEED
    data += CMD_CUT

    return bytes(data)
