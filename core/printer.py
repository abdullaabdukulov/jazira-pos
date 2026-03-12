import os
import platform
from datetime import datetime
from core.logger import get_logger
from core.config import load_config

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
CMD_OPEN_DRAWER = ESC + b'\x70\x00\x19\xfa'  # Cash drawer ochish

CHARS_PER_LINE = 48


# ──────────────────────────────────────────────────
#  Printer ro'yxatini config'dan yuklash
# ──────────────────────────────────────────────────
def get_printers() -> list[dict]:
    """Config'dan printerlar ro'yxatini qaytaradi.

    config.json misol:
    {
      "printers": [
        {"name": "Mijoz",   "device": "/dev/usb/lp0", "type": "customer"},
        {"name": "Oshxona", "device": "/dev/usb/lp1", "type": "kitchen"},
        {"name": "Barista", "device": "/dev/usb/lp2", "type": "bar"}
      ]
    }

    Agar printers bo'lmasa, standart 1 ta printer qaytariladi.
    """
    config = load_config()
    printers = config.get("printers", None)

    if not printers:
        # Backward-compatible: eski config uchun bitta printer
        device = config.get("printer_device", "/dev/usb/lp0")
        win_name = config.get("printer_name", "XP-365B")
        return [{"name": "Mijoz", "device": device, "type": "customer", "win_name": win_name}]

    return printers


def get_printers_by_type(printer_type: str) -> list[dict]:
    """Turi bo'yicha printerlarni qaytaradi (customer/kitchen/bar)"""
    return [p for p in get_printers() if p.get("type") == printer_type]


def is_printer_available(device: str) -> bool:
    """Printer ulangan/mavjudligini tekshiradi"""
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


def _line(left: str, right: str = "", fill: str = " ") -> bytes:
    if not right:
        return _encode(left + "\n")
    space = CHARS_PER_LINE - len(left) - len(right)
    if space < 1:
        space = 1
    return _encode(left + fill * space + right + "\n")


def _center_text(text: str) -> bytes:
    return CMD_ALIGN_CENTER + _encode(text + "\n") + CMD_ALIGN_LEFT


def _separator(char: str = "-") -> bytes:
    return _encode(char * CHARS_PER_LINE + "\n")


def _format_amount(amount) -> str:
    return f"{float(amount):,.0f}"


# ──────────────────────────────────────────────────
#  Chek ma'lumotlarini yaratish
# ──────────────────────────────────────────────────
def _build_customer_receipt(order_data: dict, payments_list: list) -> bytes:
    """Mijoz uchun to'liq chek (narxlar, to'lov, qaytim)"""
    items_list = order_data.get("items", [])
    total_amount = order_data.get("total_amount", 0.0)
    order_type = order_data.get("order_type", "")
    ticket_number = order_data.get("ticket_number", "")
    comment = order_data.get("comment", "")

    config = load_config()
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
    data += _encode("Xarid cheki\n")
    data += _encode(date_str + "\n")
    data += CMD_BOLD_ON
    data += _encode(f"Tur: {order_type}\n")
    data += CMD_BOLD_OFF
    data += CMD_ALIGN_LEFT

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
    data += _line("JAMI:", f"{_format_amount(total_amount)} UZS")
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


def _build_kitchen_receipt(order_data: dict, printer_type: str = "kitchen") -> bytes:
    """Oshxona/Barista uchun chek — faqat buyurtma tafsilotlari, narxsiz"""
    items_list = order_data.get("items", [])
    order_type = order_data.get("order_type", "")
    ticket_number = order_data.get("ticket_number", "")
    comment = order_data.get("comment", "")
    date_str = datetime.now().strftime("%H:%M:%S")

    label = "OSHXONA" if printer_type == "kitchen" else "BAR"

    data = bytearray()
    data += CMD_INIT

    # Sarlavha
    data += CMD_ALIGN_CENTER + CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _encode(f"--- {label} ---\n")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _encode(f"{date_str}  |  {order_type}\n")

    # Stiker
    if ticket_number:
        data += CMD_BOLD_ON + CMD_DOUBLE_ON
        data += _encode(f"STIKER: {ticket_number}\n")
        data += CMD_DOUBLE_OFF + CMD_BOLD_OFF

    data += CMD_ALIGN_LEFT
    data += _separator("=")

    # Tovarlar — faqat nom va miqdor
    for item in items_list:
        name = item.get("name", item.get("item_name", ""))
        qty = int(item.get("qty", 0))
        data += CMD_BOLD_ON
        data += _line(name, f"x{qty}")
        data += CMD_BOLD_OFF

    data += _separator("=")

    # Izoh
    if comment:
        data += CMD_BOLD_ON
        data += _encode(f"IZOH: {comment}\n")
        data += CMD_BOLD_OFF

    data += CMD_FEED
    data += CMD_CUT

    return bytes(data)


# ──────────────────────────────────────────────────
#  Printerga yuborish
# ──────────────────────────────────────────────────
def _send_to_device(data: bytes, device: str) -> bool:
    """Ma'lumotni printerga yuborish (Linux USB)"""
    try:
        if not os.path.exists(device):
            logger.warning("Printer topilmadi: %s", device)
            return False
        with open(device, "wb") as printer:
            printer.write(data)
            printer.flush()
        return True
    except PermissionError:
        logger.error("Printer ruxsati yo'q: %s (sudo usermod -aG lp $USER)", device)
        return False
    except Exception as e:
        logger.error("Printer xatosi (%s): %s", device, e)
        return False


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

    Qaytaradi: {"customer": True/False, "kitchen": True/False, "bar": True/False}
    """
    results = {}
    printers = get_printers()

    for p_config in printers:
        p_type = p_config.get("type", "customer")
        p_name = p_config.get("name", p_type)

        try:
            if p_type == "customer":
                receipt_data = _build_customer_receipt(order_data, payments_list)
            elif p_type in ("kitchen", "bar"):
                receipt_data = _build_kitchen_receipt(order_data, printer_type=p_type)
            else:
                logger.warning("Noma'lum printer turi: %s (%s)", p_type, p_name)
                continue

            success = _send_data(receipt_data, p_config)
            results[p_type] = success

            if success:
                logger.info("Chek chop etildi: %s (%s)", p_name, p_type)
            else:
                logger.warning("Chek chop etilmadi: %s (%s)", p_name, p_type)

        except Exception as e:
            logger.error("Printer xatosi %s: %s", p_name, e)
            results[p_type] = False

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


def reprint_receipt(order_data: dict, payments_list: list) -> bool:
    """Faqat mijoz printeriga qayta chop etish"""
    customer_printers = get_printers_by_type("customer")
    if not customer_printers:
        logger.warning("Mijoz printeri topilmadi — qayta chop etib bo'lmaydi")
        return False

    receipt_data = _build_customer_receipt(order_data, payments_list)
    return _send_data(receipt_data, customer_printers[0])
