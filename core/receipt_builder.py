"""TSPL (Stiker) formatida chek ma'lumotlarini yaratish.

Printer stiker (TSPL) rejimida turgani uchun kod ESC/POS o'rniga 
avtomatik tarzda TSPL buyruqlarini yaratadi. (Rus harflari uchun CP1251 va Font 3)
"""

from datetime import datetime
from database.models import Item, db
from core.logger import get_logger

logger = get_logger(__name__)

ORDER_TYPE_LABELS = {
    "Shu yerda": "Xarid cheki",
    "Saboy": "Olib ketish cheki",
    "Dastavka": "Dastavka cheki",
    "Dastavka Saboy": "Dastavka cheki",
}

# ──────────────────────────────────────────────────
#  TSPL Formatlash Dvigateli (Helper Class)
# ──────────────────────────────────────────────────
class TSPLReceipt:
    def __init__(self, width_mm=58):
        self.width_dots = 450  # 58mm qog'oz uchun kenglik
        self.data = bytearray()
        self.y = 10
        self.lines = []

    def add_text(self, text, x=10, font="3", step=35):
        """Oddiy matn qo'shish (Standart 3-shrift rus harflarini qo'llaydi)"""
        safe_text = str(text).replace('"', "'")
        self.lines.append(f'TEXT {x},{self.y},"{font}",0,1,1,"{safe_text}"\r\n')
        self.y += step

    def add_center(self, text, font="3", step=35):
        """O'rtaga to'g'irlab matn qo'shish"""
        safe_text = str(text).replace('"', "'")
        char_width = 16 if font == "3" else (24 if font == "4" else 12)
        text_width = len(safe_text) * char_width
        x = max(10, (self.width_dots - text_width) // 2)
        self.add_text(safe_text, x=x, font=font, step=step)

    def add_line(self, left, right, font="3", step=35):
        """Chap va o'ng tomonga ajratilgan qator (Nomi --- Summa)"""
        safe_left = str(left).replace('"', "'")
        safe_right = str(right).replace('"', "'")
        max_chars = 26 if font == "3" else 32  # 3-shrift uchun qator sig'imi
        spaces = max_chars - len(safe_left) - len(safe_right)
        if spaces < 1:
            spaces = 1
        combined = safe_left + " " * spaces + safe_right
        self.add_text(combined, x=10, font=font, step=step)

    def add_separator(self, char="-", step=35):
        """Chiziq tortish"""
        count = 26 if char == "-" else 14
        self.add_text(char * count, x=10, font="3", step=step)

    def build(self, is_continuous=True):
        """Yig'ilgan ma'lumotlarni TSPL baytlariga aylantirish"""
        height_mm = max(20, int((self.y + 40) / 8))
        gap_cmd = "GAP 0 mm,0 mm" if is_continuous else "GAP 2 mm,0 mm"
        
        # CODEPAGE 1251 - Xprinter uchun eng yaxshi Krill (Rus) kodirovkasi
        header = (
            f"SIZE 58 mm,{height_mm} mm\r\n"
            f"{gap_cmd}\r\n"
            f"DIRECTION 1\r\n"
            f"CODEPAGE 1251\r\n" 
            f"CLS\r\n"
        )
        
        body = bytearray()
        
        # Baytga aylantirishda CP1251 ishlatamiz
        body += header.encode('cp1251', errors='replace')
        for line in self.lines:
            body += line.encode('cp1251', errors='replace')
            
        footer = b"PRINT 1\r\n"
        return bytes(body + footer)


# ──────────────────────────────────────────────────
#  Yordamchi funksiyalar
# ──────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────
#  Chek Yaratish (TSPL formatida)
# ──────────────────────────────────────────────────
def build_customer_receipt(order_data: dict, payments_list: list, config: dict) -> bytes:
    """Mijoz uchun TSPL (Stiker) cheki"""
    r = TSPLReceipt()
    
    company = config.get("company", "JAZIRA POS")
    r.add_center(company, font="4", step=45)
    
    order_type = order_data.get("order_type", "")
    r.add_center(_order_type_label(order_type), font="3")
    r.add_center(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
    
    customer = order_data.get("customer", "")
    if order_type in ("Dastavka", "Dastavka Saboy") and customer and customer != "guest":
        r.add_separator("-")
        r.add_text(f"Mijoz: {customer}")
        
    ticket_number = order_data.get("ticket_number", "")
    if ticket_number:
        r.add_separator("=")
        r.add_center(f"STIKER: {ticket_number}", font="4", step=45)
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
        
        # 3-shrift sig'imiga qarab qatorni ajratish
        if len(name) + len(right_part) > 25:
            r.add_text(name[:25])
            r.add_line("", right_part)
        else:
            r.add_line(name, right_part)
            
    r.add_separator("=")
    r.add_line("JAMI:", f"{_format_amount(total_amount)} UZS", font="3", step=40)
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
        
    r.add_center("Xaridingiz uchun rahmat!", step=40)
    
    return r.build(is_continuous=True)


def build_production_receipt(order_data: dict, unit_items: list, unit_name: str) -> bytes:
    """Oshxona/Bar uchun stiker"""
    r = TSPLReceipt()
    r.add_center(f"--- {unit_name} ---", font="3", step=40)
    
    order_type = order_data.get("order_type", "")
    r.add_center(order_type, font="3", step=40)
    r.add_center(datetime.now().strftime("%H:%M:%S"))
    
    ticket_number = order_data.get("ticket_number", "")
    if ticket_number:
        r.add_center(f"# {ticket_number}", font="4", step=45)
        
    customer = order_data.get("customer", "")
    if order_type in ("Dastavka", "Dastavka Saboy") and customer and customer != "guest":
        r.add_text(f"Mijoz: {customer}", font="3", step=40)
        
    r.add_separator("=")
    
    for item in unit_items:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        r.add_line(name[:20], f"x{qty}", font="3", step=40)
        
    r.add_separator("=")
    
    comment = order_data.get("comment", "")
    if comment:
        r.add_text(f"IZOH: {comment}", font="3", step=40)
        
    return r.build(is_continuous=True)


def build_test_receipt(printer_name: str = "Test") -> bytes:
    """Sinov cheki (TSPL)"""
    r = TSPLReceipt()
    r.add_center("SINOV CHEKI", font="4", step=50)
    r.add_center(f"Printer: {printer_name}", font="3")
    r.add_center(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
    r.add_separator("=")
    r.add_center("Stiker rejimida ulandi!", font="3")
    return r.build(is_continuous=True)


def build_cash_drawer_command() -> bytes:
    """Kassa tortmasini ochish buyrug'i"""
    return b'\x1b\x70\x00\x19\xfa'


def build_z_report_receipt(report_data: dict) -> bytes:
    """Z-otchyot TSPL formatida"""
    r = TSPLReceipt()
    
    terminal = report_data.get("terminal_name", "JAZIRA POS")
    r.add_center(terminal, font="3", step=40)
    r.add_center("Z-OTCHYOT", font="4", step=45)
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
    
    return r.build(is_continuous=True)