"""To'g'ridan-to'g'ri USB printer orqali ESC/POS chop etish.

OS printer API orqali raw baytlarni printerga yuboradi:
- Windows: win32print (pywin32)
- Linux: lp buyrug'i (subprocess)

QZ Tray, WebSocket, sertifikat — hech biri kerak emas.
"""

import platform
import subprocess
from core.config import load_config
from core.logger import get_logger
from core.receipt_builder import (
    build_customer_receipt,
    build_production_receipt,
    build_cash_drawer_command,
    build_z_report_receipt,
    get_item_groups_map,
)

logger = get_logger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


# ──────────────────────────────────────────────────
#  OS printerga raw ESC/POS yuborish
# ──────────────────────────────────────────────────
def _send_raw(printer_name: str, data: bytes) -> bool:
    """Printer ga raw ESC/POS baytlar yuborish."""
    if not printer_name:
        logger.warning("Printer nomi ko'rsatilmagan")
        return False

    try:
        if _IS_WINDOWS:
            return _send_raw_windows(printer_name, data)
        else:
            return _send_raw_linux(printer_name, data)
    except Exception as e:
        logger.error("Printer xatosi (%s): %s", printer_name, e)
        return False


def _send_raw_windows(printer_name: str, data: bytes) -> bool:
    """Windows: win32print orqali RAW chop etish."""
    try:
        import win32print
    except ImportError:
        logger.error("pywin32 o'rnatilmagan. 'pip install pywin32' qiling.")
        return False

    # Printer mavjudligini tekshirish
    printers = [p[2] for p in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    )]
    if printer_name not in printers:
        logger.error(
            "'%s' printer topilmadi. Mavjud printerlar: %s",
            printer_name, ", ".join(printers)
        )
        return False

    handle = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(handle, 1, ("POS Receipt", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, data)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        logger.info("Chop etildi: %s", printer_name)
        return True
    except Exception as e:
        logger.error("WritePrinter xatosi (%s): %s", printer_name, e)
        return False
    finally:
        win32print.ClosePrinter(handle)


def _send_raw_linux(printer_name: str, data: bytes) -> bool:
    """Linux: lp buyrug'i orqali RAW chop etish."""
    try:
        result = subprocess.run(
            ["lp", "-d", printer_name, "-o", "raw"],
            input=data,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("Chop etildi: %s", printer_name)
            return True
        else:
            stderr = result.stderr.decode(errors="replace").strip()
            logger.error("lp xatosi (%s): %s", printer_name, stderr)
            return False
    except FileNotFoundError:
        logger.error("'lp' buyrug'i topilmadi. CUPS o'rnatilganini tekshiring.")
        return False


# ──────────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────────
def _get_printer_config() -> dict:
    config = load_config()
    return {
        "qz_print": config.get("qz_print", 0),
        "customer_printer": config.get("customer_qz_printer", ""),
        "production_units": config.get("production_units", []),
        "company": config.get("company", ""),
    }


# ──────────────────────────────────────────────────
#  Umumiy API
# ──────────────────────────────────────────────────
def print_receipt(parent_widget, order_data: dict, payments_list: list) -> dict:
    """Barcha sozlangan printerlarga chek yuborish.

    1. Mijoz cheki — customer_printer ga
    2. Production unit cheklari — har bir unit o'z printeriga

    Qaytaradi: {"customer": True/False, "Unit nomi": True/False, ...}
    """
    results = {}
    cfg = _get_printer_config()

    if not cfg.get("qz_print", 0):
        return results

    # 1. Mijoz cheki
    customer_printer = cfg["customer_printer"]
    if customer_printer:
        try:
            receipt_data = build_customer_receipt(
                order_data, payments_list, {"company": cfg["company"]}
            )
            results["customer"] = _send_raw(customer_printer, receipt_data)
        except Exception as e:
            logger.error("Mijoz cheki xatosi: %s", e)
            results["customer"] = False

    # 2. Production unit cheklari
    prod_units = cfg["production_units"]
    if not prod_units:
        return results

    items_list = order_data.get("items", [])
    item_groups_map = get_item_groups_map(items_list)

    for unit in prod_units:
        unit_name = unit.get("name", "")
        unit_printer = unit.get("qz_printer_name", "")

        if not unit_printer:
            continue

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
            receipt_data = build_production_receipt(order_data, unit_items, unit_name)
            results[unit_name] = _send_raw(unit_printer, receipt_data)
        except Exception as e:
            logger.error("Production chek xatosi (%s): %s", unit_name, e)
            results[unit_name] = False

    return results


def open_cash_drawer() -> bool:
    """Cash drawer ochish (mijoz printeri orqali)."""
    cfg = _get_printer_config()
    if not cfg.get("qz_print", 0):
        return False
    customer_printer = cfg["customer_printer"]
    if not customer_printer:
        return False
    return _send_raw(customer_printer, build_cash_drawer_command())


def reprint_receipt(order_data: dict, payments_list: list) -> bool:
    """Faqat mijoz printeriga qayta chop etish (backward compat alias)."""
    return reprint_customer(order_data, payments_list)


def reprint_customer(order_data: dict, payments_list: list) -> bool:
    """Faqat mijoz chekini qayta chop etish."""
    cfg = _get_printer_config()
    if not cfg.get("qz_print", 0):
        return False
    customer_printer = cfg["customer_printer"]
    if not customer_printer:
        return False
    try:
        receipt_data = build_customer_receipt(
            order_data, payments_list, {"company": cfg["company"]}
        )
        return _send_raw(customer_printer, receipt_data)
    except Exception as e:
        logger.error("Mijoz reprint xatosi: %s", e)
        return False


def reprint_production(order_data: dict, items_list: list = None) -> dict:
    """Faqat production (oshxona/bar) unitlarga qayta chop etish.

    Qaytaradi: {unit_name: True/False, ...}
    """
    results = {}
    cfg = _get_printer_config()
    if not cfg.get("qz_print", 0):
        return results

    prod_units = cfg["production_units"]
    if not prod_units:
        return results

    if items_list is None:
        items_list = order_data.get("items", [])

    item_groups_map = get_item_groups_map(items_list)

    for unit in prod_units:
        unit_name = unit.get("name", "")
        unit_printer = unit.get("qz_printer_name", "")
        if not unit_printer:
            continue
        unit_item_groups = set(unit.get("item_groups", []))
        unit_items = [
            item for item in items_list
            if item_groups_map.get(item.get("item_code", item.get("item", ""))) in unit_item_groups
        ]
        if not unit_items:
            continue
        try:
            receipt_data = build_production_receipt(order_data, unit_items, unit_name)
            results[unit_name] = _send_raw(unit_printer, receipt_data)
        except Exception as e:
            logger.error("Production reprint xatosi (%s): %s", unit_name, e)
            results[unit_name] = False

    return results


def reprint_all(order_data: dict, payments_list: list) -> dict:
    """Mijoz cheki + barcha production unitlar.

    Qaytaradi: {"customer": True/False, unit_name: True/False, ...}
    """
    results = {}
    results["customer"] = reprint_customer(order_data, payments_list)
    results.update(reprint_production(order_data))
    return results


def print_z_report(report_data: dict) -> bool:
    """Z-otchyot (smena hisoboti) ni mijoz printeriga chop etish."""
    cfg = _get_printer_config()
    if not cfg.get("qz_print", 0):
        logger.info("Printer yoqilmagan — Z-report chop etilmadi")
        return False
    customer_printer = cfg["customer_printer"]
    if not customer_printer:
        logger.warning("Mijoz printeri sozlanmagan — Z-report chop etilmadi")
        return False
    try:
        receipt_data = build_z_report_receipt(report_data)
        result = _send_raw(customer_printer, receipt_data)
        if result:
            logger.info("Z-report chop etildi: %s", report_data.get("shift_id", ""))
        return result
    except Exception as e:
        logger.error("Z-report chop etishda xatolik: %s", e)
        return False
