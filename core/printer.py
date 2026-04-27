"""To'g'ridan-to'g'ri OS printer orqali raw chop etish.

Adaptive: har bir printer uchun alohida driver (ESC/POS yoki TSPL) va
qog'oz kengligi (width_mm) sozlanadi.

Config formati:
    customer_printer = {
        "name": "XP-58 IIH",
        "driver": "escpos",      # "escpos" | "tspl"
        "width_mm": 58,
    }
    production_units = [
        {
            "name": "Oshxona",
            "printer_name": "XP-365B",
            "driver": "tspl",
            "width_mm": 80,
            "item_groups": [...]
        },
        ...
    ]

Backward compat: agar `customer_printer` string bo'lsa,
default driver=escpos, width_mm=58 deb qabul qilinadi.
"""

import platform
import subprocess
from core.config import load_config
from core.logger import get_logger
from core.receipt_builder import (
    build_customer_receipt,
    build_production_receipt,
    build_cancel_production_receipt,
    build_cash_drawer_command,
    build_z_report_receipt,
    build_test_receipt,
    get_item_groups_map,
    DEFAULT_PRINTER_CFG,
)

logger = get_logger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


# ──────────────────────────────────────────────────
#  Printer config normalization (backward compat)
# ──────────────────────────────────────────────────
def _normalize_printer(raw) -> dict:
    """Eski (string) yoki yangi (dict) format ni dict ga keltirish.

    Qaytaradi: {"name": str, "driver": str, "width_mm": int} yoki bo'sh nom bilan.
    """
    if not raw:
        return {"name": "", **DEFAULT_PRINTER_CFG}

    # Eski format: shunchaki printer nomi (string)
    if isinstance(raw, str):
        return {"name": raw, **DEFAULT_PRINTER_CFG}

    # Yangi format: dict
    if isinstance(raw, dict):
        return {
            "name": raw.get("name", "") or raw.get("printer_name", ""),
            "driver": (raw.get("driver") or DEFAULT_PRINTER_CFG["driver"]).lower(),
            "width_mm": int(raw.get("width_mm") or DEFAULT_PRINTER_CFG["width_mm"]),
        }

    return {"name": "", **DEFAULT_PRINTER_CFG}


def _normalize_unit(raw: dict) -> dict:
    """Production unitni normalize qilish — backward compat bilan."""
    if not isinstance(raw, dict):
        return {}
    return {
        "name": raw.get("name", ""),
        "printer_name": raw.get("printer_name", "") or "",
        "driver": (raw.get("driver") or DEFAULT_PRINTER_CFG["driver"]).lower(),
        "width_mm": int(raw.get("width_mm") or DEFAULT_PRINTER_CFG["width_mm"]),
        "item_groups": raw.get("item_groups", []) or [],
    }


# ──────────────────────────────────────────────────
#  OS printerga raw bayt yuborish
# ──────────────────────────────────────────────────
def _send_raw(printer_name: str, data: bytes) -> bool:
    if not printer_name:
        logger.warning("Printer nomi ko'rsatilmagan")
        return False
    try:
        if _IS_WINDOWS:
            return _send_raw_windows(printer_name, data)
        return _send_raw_linux(printer_name, data)
    except Exception as e:
        logger.error("Printer xatosi (%s): %s", printer_name, e)
        return False


def _send_raw_windows(printer_name: str, data: bytes) -> bool:
    try:
        import win32print
    except ImportError:
        logger.error("pywin32 o'rnatilmagan. 'pip install pywin32' qiling.")
        return False

    printers = [p[2] for p in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    )]
    if printer_name not in printers:
        logger.error(
            "'%s' printer topilmadi. Mavjud: %s",
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
    try:
        result = subprocess.run(
            ["lp", "-d", printer_name, "-o", "raw"],
            input=data, capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("Chop etildi: %s", printer_name)
            return True
        stderr = result.stderr.decode(errors="replace").strip()
        logger.error("lp xatosi (%s): %s", printer_name, stderr)
        return False
    except FileNotFoundError:
        logger.error("'lp' buyrug'i topilmadi. CUPS o'rnatilganini tekshiring.")
        return False


# ──────────────────────────────────────────────────
#  Config wrapper
# ──────────────────────────────────────────────────
def _get_printer_config() -> dict:
    config = load_config()

    customer = _normalize_printer(config.get("customer_printer"))

    raw_units = config.get("production_units", []) or []
    units = [_normalize_unit(u) for u in raw_units if isinstance(u, dict)]

    return {
        "customer_printer": customer,
        "production_units": units,
        "company": config.get("company", ""),
    }


def _printer_cfg(printer: dict) -> dict:
    """Printer dict dan receipt builder uchun config ajratish."""
    return {"driver": printer["driver"], "width_mm": printer["width_mm"]}


# ──────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────
def print_receipt(parent_widget, order_data: dict, payments_list: list) -> dict:
    """Mijoz cheki + barcha production unit cheklari."""
    results = {}
    cfg = _get_printer_config()

    customer = cfg["customer_printer"]
    has_prod_units = any(u.get("printer_name") for u in cfg["production_units"])

    if not customer["name"] and not has_prod_units:
        logger.info("Hech qanday printer sozlanmagan — chop etish o'tkazib yuborildi")
        return results

    logger.info(
        "print_receipt: customer='%s' (%s/%dmm), units=%d",
        customer["name"], customer["driver"], customer["width_mm"],
        len(cfg["production_units"])
    )

    # 1. Mijoz cheki
    if customer["name"]:
        try:
            data = build_customer_receipt(
                order_data, payments_list,
                {"company": cfg["company"]},
                printer_cfg=_printer_cfg(customer),
            )
            results["customer"] = _send_raw(customer["name"], data)
        except Exception as e:
            logger.error("Mijoz cheki xatosi: %s", e)
            results["customer"] = False

    # 2. Production unit cheklari
    if not cfg["production_units"]:
        return results

    items_list = order_data.get("items", [])
    item_groups_map = get_item_groups_map(items_list)

    for unit in cfg["production_units"]:
        unit_name = unit["name"]
        unit_printer = unit["printer_name"]
        if not unit_printer:
            continue

        unit_groups = set(unit["item_groups"])
        unit_items = [
            item for item in items_list
            if item_groups_map.get(item.get("item_code", item.get("item", ""))) in unit_groups
        ]
        if not unit_items:
            continue

        try:
            data = build_production_receipt(
                order_data, unit_items, unit_name,
                printer_cfg=_printer_cfg(unit),
            )
            results[unit_name] = _send_raw(unit_printer, data)
        except Exception as e:
            logger.error("Production chek xatosi (%s): %s", unit_name, e)
            results[unit_name] = False

    return results


def open_cash_drawer() -> bool:
    cfg = _get_printer_config()
    customer = cfg["customer_printer"]
    if not customer["name"]:
        return False
    return _send_raw(customer["name"], build_cash_drawer_command(_printer_cfg(customer)))


def reprint_receipt(order_data: dict, payments_list: list) -> bool:
    return reprint_customer(order_data, payments_list)


def reprint_customer(order_data: dict, payments_list: list) -> bool:
    cfg = _get_printer_config()
    customer = cfg["customer_printer"]
    if not customer["name"]:
        return False
    try:
        data = build_customer_receipt(
            order_data, payments_list,
            {"company": cfg["company"]},
            printer_cfg=_printer_cfg(customer),
        )
        return _send_raw(customer["name"], data)
    except Exception as e:
        logger.error("Mijoz reprint xatosi: %s", e)
        return False


def reprint_production(order_data: dict, items_list: list = None) -> dict:
    results = {}
    cfg = _get_printer_config()

    if items_list is None:
        items_list = order_data.get("items", [])

    item_groups_map = get_item_groups_map(items_list)

    for unit in cfg["production_units"]:
        unit_name = unit["name"]
        unit_printer = unit["printer_name"]
        if not unit_printer:
            continue
        unit_groups = set(unit["item_groups"])
        unit_items = [
            item for item in items_list
            if item_groups_map.get(item.get("item_code", item.get("item", ""))) in unit_groups
        ]
        if not unit_items:
            continue
        try:
            data = build_production_receipt(
                order_data, unit_items, unit_name,
                printer_cfg=_printer_cfg(unit),
            )
            results[unit_name] = _send_raw(unit_printer, data)
        except Exception as e:
            logger.error("Production reprint xatosi (%s): %s", unit_name, e)
            results[unit_name] = False
    return results


def reprint_all(order_data: dict, payments_list: list) -> dict:
    results = {"customer": reprint_customer(order_data, payments_list)}
    results.update(reprint_production(order_data))
    return results


def print_cancel_production(order_data: dict, cancel_reason: str) -> dict:
    results = {}
    cfg = _get_printer_config()
    if not cfg["production_units"]:
        return results

    items_list = order_data.get("items", [])
    item_groups_map = get_item_groups_map(items_list)

    for unit in cfg["production_units"]:
        unit_name = unit["name"]
        unit_printer = unit["printer_name"]
        if not unit_printer:
            continue
        unit_groups = set(unit["item_groups"])
        unit_items = [
            item for item in items_list
            if item_groups_map.get(item.get("item_code", item.get("item", ""))) in unit_groups
        ]
        if not unit_items:
            continue
        try:
            data = build_cancel_production_receipt(
                order_data, unit_items, unit_name, cancel_reason,
                printer_cfg=_printer_cfg(unit),
            )
            results[unit_name] = _send_raw(unit_printer, data)
        except Exception as e:
            logger.error("Bekor stikeri xatosi (%s): %s", unit_name, e)
            results[unit_name] = False
    return results


def print_z_report(report_data: dict) -> bool:
    cfg = _get_printer_config()
    customer = cfg["customer_printer"]
    if not customer["name"]:
        logger.info("Mijoz printeri sozlanmagan — Z-report chop etilmadi")
        return False
    try:
        data = build_z_report_receipt(report_data, printer_cfg=_printer_cfg(customer))
        result = _send_raw(customer["name"], data)
        if result:
            logger.info("Z-report chop etildi: %s", report_data.get("shift_id", ""))
        return result
    except Exception as e:
        logger.error("Z-report xatosi: %s", e)
        return False


def print_test_receipt(printer: dict = None) -> bool:
    """Belgilangan printerda sinov cheki — UI tugmasi uchun."""
    p = _normalize_printer(printer) if printer else _get_printer_config()["customer_printer"]
    if not p["name"]:
        return False
    try:
        data = build_test_receipt(p["name"], printer_cfg=_printer_cfg(p))
        return _send_raw(p["name"], data)
    except Exception as e:
        logger.error("Sinov cheki xatosi: %s", e)
        return False
