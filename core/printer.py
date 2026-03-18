import os
import platform
import threading
from datetime import datetime
from core.logger import get_logger
from core.config import load_config
from database.models import Item, db

logger = get_logger(__name__)

# ESC/POS buyruqlari
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
CHARS_DOUBLE = 24  # CMD_DOUBLE_ON da 2x kenglik → yarmi sig'adi
PRINTER_TIMEOUT = 3.0

ORDER_TYPE_LABELS = {
    "Shu yerda": "Xarid cheki",
    "Saboy": "Olib ketish cheki",
    "Dastavka": "Dastavka cheki",
    "Dastavka Saboy": "Dastavka cheki",
}


# ──────────────────────────────────────────────────
#  Printer ro'yxatini config'dan yuklash
# ──────────────────────────────────────────────────
def get_printers() -> list[dict]:
    config = load_config()
    printers = config.get("printers", None)

    if not printers:
        device = config.get("printer_device", "/dev/usb/lp0")
        win_name = config.get("printer_name", "XP-365B")
        return [{"name": "Mijoz", "device": device, "type": "customer", "win_name": win_name}]

    return printers


def get_printers_by_type(printer_type: str) -> list[dict]:
    return [p for p in get_printers() if p.get("type") == printer_type]


def is_printer_available(device: str) -> bool:
    if platform.system() == "Windows":
        try:
            import win32print
            printers = [p[2] for p in win32print.EnumPrinters(2)]
            return device in printers
        except ImportError:
            return False
    else:
        return os.path.exists(device)


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
#  Chek ma'lumotlarini yaratish
# ──────────────────────────────────────────────────
def _build_customer_receipt(order_data: dict, payments_list: list, config: dict) -> bytes:
    """Mijoz uchun to'liq chek — turiga qarab sarlavha o'zgaradi"""
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

    # Sarlavha — turiga qarab
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


def _build_production_receipt(order_data: dict, unit_items: list, unit_name: str) -> bytes:
    """Production unit uchun chek — turiga qarab format o'zgaradi"""
    order_type = order_data.get("order_type", "")
    ticket_number = order_data.get("ticket_number", "")
    comment = order_data.get("comment", "")
    customer = order_data.get("customer", "")
    date_str = datetime.now().strftime("%H:%M:%S")

    data = bytearray()
    data += CMD_INIT

    # Sarlavha — unit nomi katta
    data += CMD_ALIGN_CENTER + CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(f"--- {unit_name} ---\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF

    # Buyurtma turi + vaqt
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(f"{order_type}\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode(date_str + "\n")

    # Stiker — eng muhim qism
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

    # Tovarlar — katta shrift, faqat nom va miqdor
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    for item in unit_items:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        right = f"x{qty}"
        # DOUBLE_ON = 24 belgi sig'adi
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


def _get_item_groups_map(items: list) -> dict:
    """Lokal DB dan itemlarning item_group ini oladi."""
    item_codes = [
        item.get("item_code", item.get("item", ""))
        for item in items
        if item.get("item_code") or item.get("item")
    ]
    if not item_codes:
        return {}

    try:
        db.connect(reuse_if_open=True)
        rows = Item.select(Item.item_code, Item.item_group).where(
            Item.item_code.in_(item_codes)
        )
        return {row.item_code: row.item_group or "" for row in rows}
    except Exception as e:
        logger.error("Item group olishda xatolik: %s", e)
        return {}
    finally:
        if not db.is_closed():
            db.close()


# ──────────────────────────────────────────────────
#  Printerga yuborish (timeout bilan)
# ──────────────────────────────────────────────────
def _send_to_device(data: bytes, device: str) -> bool:
    """Ma'lumotni printerga yuborish (Linux USB) — timeout bilan"""
    if not os.path.exists(device):
        logger.warning("Printer topilmadi: %s", device)
        return False

    result = [False]
    error = [None]

    def _write():
        try:
            with open(device, "wb") as printer:
                printer.write(data)
                printer.flush()
            result[0] = True
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    t.join(timeout=PRINTER_TIMEOUT)

    if t.is_alive():
        logger.error("Printer timeout (%.0f sek): %s", PRINTER_TIMEOUT, device)
        return False

    if error[0]:
        if isinstance(error[0], PermissionError):
            logger.error("Printer ruxsati yo'q: %s (sudo usermod -aG lp $USER)", device)
        else:
            logger.error("Printer xatosi (%s): %s", device, error[0])
        return False

    return result[0]


def _send_win32(data: bytes, printer_name: str) -> bool:
    """Windows'da win32print orqali yuborish"""
    try:
        import win32print
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            hJob = win32print.StartDocPrinter(hPrinter, 1, ("POS Receipt", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, data)
                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        return True
    except ImportError:
        logger.error("win32print topilmadi. 'pip install pywin32' qiling.")
        return False
    except Exception as e:
        logger.error("Windows print xatosi (%s): %s", printer_name, e)
        return False


def _send_data(data: bytes, printer_config: dict) -> bool:
    """Platformaga mos tarzda printerga yuborish"""
    if platform.system() == "Windows":
        name = printer_config.get("win_name", printer_config.get("name", "XP-365B"))
        return _send_win32(data, name)
    else:
        device = printer_config.get("device", "/dev/usb/lp0")
        return _send_to_device(data, device)


# ──────────────────────────────────────────────────
#  Umumiy API
# ──────────────────────────────────────────────────
def print_receipt(parent_widget, order_data: dict, payments_list: list) -> dict:
    """Barcha sozlangan printerlarga chek yuborish.

    1. Mijoz cheki — barcha itemlar + narxlar (customer printer)
    2. Production unit cheklari — har bir unit uchun faqat o'z item_group itemlari

    Qaytaradi: {"customer": True/False, "Unit nomi": True/False, ...}
    """
    results = {}
    config = load_config()

    # 1. Mijoz cheki (customer printer) — doim
    customer_printers = get_printers_by_type("customer")
    if customer_printers:
        try:
            receipt_data = _build_customer_receipt(order_data, payments_list, config)
            success = _send_data(receipt_data, customer_printers[0])
            results["customer"] = success
            if success:
                logger.info("Mijoz cheki chop etildi")
            else:
                logger.warning("Mijoz cheki chop etilmadi")
        except Exception as e:
            logger.error("Mijoz printer xatosi: %s", e)
            results["customer"] = False
    else:
        logger.warning("Mijoz printeri sozlanmagan")

    # 2. Production unit cheklari
    prod_units = config.get("production_units", [])
    if not prod_units:
        return results

    # Item → item_group mapping (lokal DB) — 1 marta query
    items_list = order_data.get("items", [])
    item_groups_map = _get_item_groups_map(items_list)

    for unit in prod_units:
        unit_name = unit.get("name", "")
        device = unit.get("printer_device", "")
        win_name = unit.get("printer_win_name", "")

        # Platformaga qarab printer sozlanganligini tekshirish
        if platform.system() == "Windows":
            if not win_name:
                logger.info("'%s' uchun printer_win_name sozlanmagan, o'tkazib yuborildi", unit_name)
                continue
        else:
            if not device:
                logger.info("'%s' uchun printer_device sozlanmagan, o'tkazib yuborildi", unit_name)
                continue

        # Faqat shu unitga tegishli itemlarni filtrlash
        unit_item_groups = set(unit.get("item_groups", []))
        unit_items = [
            item for item in items_list
            if item_groups_map.get(
                item.get("item_code", item.get("item", ""))
            ) in unit_item_groups
        ]

        if not unit_items:
            continue

        try:
            receipt_data = _build_production_receipt(order_data, unit_items, unit_name)
            printer_config = {"device": device, "win_name": win_name}
            success = _send_data(receipt_data, printer_config)
            results[unit_name] = success

            if success:
                logger.info("Production chek chop etildi: %s", unit_name)
            else:
                logger.warning("Production chek chop etilmadi: %s", unit_name)
        except Exception as e:
            logger.error("Production printer xatosi (%s): %s", unit_name, e)
            results[unit_name] = False

    return results


def open_cash_drawer() -> bool:
    """Cash drawer ochish (birinchi customer printerga)"""
    customer_printers = get_printers_by_type("customer")
    if not customer_printers:
        logger.warning("Mijoz printeri topilmadi — cash drawer ochib bo'lmaydi")
        return False

    p = customer_printers[0]
    data = CMD_INIT + CMD_OPEN_DRAWER
    return _send_data(data, p)


def send_test_print(printer_config: dict) -> bool:
    """Sinov cheki — printer ishlayotganligini tekshirish."""
    data = bytearray()
    data += CMD_INIT
    data += CMD_ALIGN_CENTER
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode("SINOV CHEKI\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode(f"Printer: {printer_config.get('name', 'Test')}\n")
    data += _encode(datetime.now().strftime("%Y-%m-%d  %H:%M:%S") + "\n")
    data += _separator()
    data += _center_text("Printer ishlayapti!")
    data += CMD_FEED
    data += CMD_CUT
    return _send_data(bytes(data), printer_config)


def reprint_receipt(order_data: dict, payments_list: list) -> bool:
    """Faqat mijoz printeriga qayta chop etish"""
    customer_printers = get_printers_by_type("customer")
    if not customer_printers:
        logger.warning("Mijoz printeri topilmadi — qayta chop etib bo'lmaydi")
        return False

    config = load_config()
    receipt_data = _build_customer_receipt(order_data, payments_list, config)
    return _send_data(receipt_data, customer_printers[0])
