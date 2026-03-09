import subprocess
import os
import platform
from datetime import datetime
from core.logger import get_logger
from core.config import load_config

logger = get_logger(__name__)

# XP-365B: 80mm termal printer, ~48 belgi (Font A)
USB_DEVICE_LINUX = "/dev/usb/lp0"
DEFAULT_PRINTER_WINDOWS = "XP-365B"
CHARS_PER_LINE = 48

# ESC/POS buyruqlari
ESC = b'\x1b'
GS = b'\x1d'

CMD_INIT = ESC + b'\x40'                  # Printer reset
CMD_ALIGN_CENTER = ESC + b'\x61\x01'      # Markazga tekislash
CMD_ALIGN_LEFT = ESC + b'\x61\x00'        # Chapga tekislash
CMD_BOLD_ON = ESC + b'\x45\x01'           # Bold yoqish
CMD_BOLD_OFF = ESC + b'\x45\x00'          # Bold o'chirish
CMD_DOUBLE_ON = GS + b'\x21\x11'          # 2x katta shrift
CMD_DOUBLE_OFF = GS + b'\x21\x00'         # Normal shrift
CMD_FONT_B = ESC + b'\x4d\x01'            # Kichik shrift (Font B)
CMD_FONT_A = ESC + b'\x4d\x00'            # Normal shrift (Font A)
CMD_CUT = GS + b'\x56\x41\x03'            # Qog'oz kesish (partial cut, 3 dot feed)
CMD_FEED = ESC + b'\x64\x04'              # 4 qator bo'sh joy


def _encode(text: str) -> bytes:
    """Matnni printer kodlashiga o'tkazish"""
    try:
        return text.encode("cp866")
    except UnicodeEncodeError:
        return text.encode("utf-8", errors="replace")


def _line(left: str, right: str = "", fill: str = " ") -> bytes:
    """Chapga va o'ngga tekislangan qator"""
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


def _build_receipt(order_data: dict, payments_list: list) -> bytes:
    """ESC/POS formatidagi chek ma'lumotlarini yaratish"""
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

    # Printer reset
    data += CMD_INIT

    # === Sarlavha ===
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

    # === Bilet raqami ===
    if ticket_number:
        data += _encode("\n")
        data += _separator("=")
        data += CMD_ALIGN_CENTER + CMD_BOLD_ON + CMD_DOUBLE_ON
        data += _encode(f"STIKER: {ticket_number}\n")
        data += CMD_DOUBLE_OFF + CMD_BOLD_OFF + CMD_ALIGN_LEFT
        data += _separator("=")

    # === Tovarlar ===
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

    # === Jami ===
    data += _separator("=")
    data += CMD_BOLD_ON + CMD_DOUBLE_ON
    data += _line("JAMI:", f"{_format_amount(total_amount)} UZS")
    data += CMD_DOUBLE_OFF + CMD_BOLD_OFF
    data += _separator("=")

    # === To'lovlar ===
    data += _encode("\n")
    data += CMD_BOLD_ON
    data += _encode("TO'LOVLAR:\n")
    data += CMD_BOLD_OFF
    for p in payments_list:
        if float(p.get("amount", 0)) > 0:
            data += _line(
                f"  {p['mode_of_payment']}:",
                f"{_format_amount(p['amount'])} UZS"
            )

    # === Qaytim ===
    if change > 0:
        data += _separator()
        data += CMD_BOLD_ON
        data += _line("QAYTIM:", f"{_format_amount(change)} UZS")
        data += CMD_BOLD_OFF

    # === Izoh ===
    if comment:
        data += _encode(f"\nIzoh: {comment}\n")

    # === Pastki qism ===
    data += _encode("\n")
    data += _center_text("Xaridingiz uchun rahmat!")
    data += CMD_FEED
    data += CMD_CUT

    return bytes(data)


def _send_usb_linux(data: bytes) -> bool:
    """Linux'da USB orqali to'g'ridan-to'g'ri yuborish"""
    try:
        with open(USB_DEVICE_LINUX, "wb") as printer:
            printer.write(data)
            printer.flush()
        return True
    except Exception as e:
        logger.error("Linux USB print xatosi: %s", e)
        return False


def _send_win32_print(data: bytes) -> bool:
    """Windows'da win32print orqali yuborish"""
    try:
        import win32print
        config = load_config()
        printer_name = config.get("printer_name", DEFAULT_PRINTER_WINDOWS)
        
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
        logger.error("win32print moduli topilmadi. 'pip install pywin32' qiling.")
        return False
    except Exception as e:
        logger.error("Windows print xatosi: %s", e)
        return False


def print_receipt(parent_widget, order_data: dict, payments_list: list) -> bool:
    """ESC/POS chek chop etish (Linux va Windows)"""
    try:
        receipt_data = _build_receipt(order_data, payments_list)
        
        current_os = platform.system()
        
        if current_os == "Windows":
            return _send_win32_print(receipt_data)
        else:
            # Default to Linux/Unix USB
            return _send_usb_linux(receipt_data)

    except Exception as e:
        logger.error("Chek chop etishda kutilmagan xatolik: %s", e)
        return False
