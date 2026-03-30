"""QZ Tray orqali chop etish moduli.

QZ Tray — lokal WebSocket server (ws://localhost:8182) orqali
ESC/POS ma'lumotlarini printerlarga yuboradi.

Offline rejimda: chek ma'lumotlari config.json dagi printer sozlamalaridan
foydalanib yaratiladi va QZ Tray ga yuboriladi.
"""

import json
import base64
import threading
from core.config import load_config
from core.logger import get_logger
from core.receipt_builder import (
    build_customer_receipt,
    build_production_receipt,
    build_cash_drawer_command,
    get_item_groups_map,
)

logger = get_logger(__name__)

QZ_TIMEOUT = 5.0  # sekund


# ──────────────────────────────────────────────────
#  QZ Tray WebSocket bilan aloqa
# ──────────────────────────────────────────────────
def _send_to_qz(printer_name: str, raw_data: bytes, qz_host: str = "localhost") -> bool:
    """QZ Tray ga WebSocket orqali ESC/POS ma'lumot yuborish.

    QZ Tray API:
    1. WebSocket ulanish: ws://{host}:8182
    2. JSON xabar yuborish: {"call": "qz.print", "params": {...}}
    3. Javob kutish
    """
    if not printer_name:
        logger.warning("Printer nomi ko'rsatilmagan — chop etib bo'lmaydi")
        return False

    try:
        import websocket
    except ImportError:
        logger.error("websocket-client o'rnatilmagan. 'pip install websocket-client' qiling.")
        return False

    result = [False]
    error = [None]

    def _do_send():
        ws = None
        try:
            ws_url = f"ws://{qz_host}:8182"
            ws = websocket.create_connection(ws_url, timeout=QZ_TIMEOUT)

            # QZ Tray raw print buyrug'i
            b64_data = base64.b64encode(raw_data).decode("ascii")
            print_msg = json.dumps({
                "call": "qz.print",
                "promise": {"callId": "pos-print"},
                "params": {
                    "printer": printer_name,
                    "options": {"encoding": "base64"},
                    "data": [b64_data],
                }
            })

            ws.send(print_msg)

            # Javob kutish
            resp_raw = ws.recv()
            resp = json.loads(resp_raw) if resp_raw else {}

            if resp.get("error"):
                error[0] = resp["error"]
            else:
                result[0] = True

        except Exception as e:
            error[0] = e
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass

    t = threading.Thread(target=_do_send, daemon=True)
    t.start()
    t.join(timeout=QZ_TIMEOUT + 2)

    if t.is_alive():
        logger.error("QZ Tray timeout (%s): %s", printer_name, qz_host)
        return False

    if error[0]:
        logger.error("QZ Tray xatosi (%s): %s", printer_name, error[0])
        return False

    if result[0]:
        logger.info("QZ Tray orqali chop etildi: %s", printer_name)

    return result[0]


def _get_qz_config() -> dict:
    """Config dan QZ Tray sozlamalarini olish."""
    config = load_config()
    return {
        "qz_print": config.get("qz_print", 0),
        "qz_host": config.get("qz_host", "localhost"),
        "customer_qz_printer": config.get("customer_qz_printer", ""),
        "production_units": config.get("production_units", []),
        "company": config.get("company", ""),
    }


# ──────────────────────────────────────────────────
#  Umumiy API — eski printer.py bilan bir xil interfeys
# ──────────────────────────────────────────────────
def print_receipt(parent_widget, order_data: dict, payments_list: list) -> dict:
    """Barcha sozlangan printerlarga chek yuborish (QZ Tray orqali).

    1. Mijoz cheki — customer_qz_printer ga
    2. Production unit cheklari — har bir unit o'z qz_printer_name iga

    Qaytaradi: {"customer": True/False, "Unit nomi": True/False, ...}
    """
    results = {}
    qz_cfg = _get_qz_config()

    if not qz_cfg.get("qz_print", 0):
        return results  # QZ Tray o'chirilgan — chop etmaslik

    qz_host = qz_cfg["qz_host"]

    # 1. Mijoz cheki
    customer_printer = qz_cfg["customer_qz_printer"]
    if customer_printer:
        try:
            config = {"company": qz_cfg["company"]}
            receipt_data = build_customer_receipt(order_data, payments_list, config)
            success = _send_to_qz(customer_printer, receipt_data, qz_host)
            results["customer"] = success
            if success:
                logger.info("Mijoz cheki chop etildi (QZ)")
            else:
                logger.warning("Mijoz cheki chop etilmadi (QZ)")
        except Exception as e:
            logger.error("Mijoz printer xatosi (QZ): %s", e)
            results["customer"] = False
    else:
        logger.warning("Mijoz QZ printeri sozlanmagan")

    # 2. Production unit cheklari
    prod_units = qz_cfg["production_units"]
    if not prod_units:
        return results

    items_list = order_data.get("items", [])
    item_groups_map = get_item_groups_map(items_list)

    for unit in prod_units:
        unit_name = unit.get("name", "")
        qz_printer = unit.get("qz_printer_name", "")

        if not qz_printer:
            logger.info("'%s' uchun qz_printer_name sozlanmagan, o'tkazib yuborildi", unit_name)
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
            receipt_data = build_production_receipt(order_data, unit_items, unit_name)
            success = _send_to_qz(qz_printer, receipt_data, qz_host)
            results[unit_name] = success

            if success:
                logger.info("Production chek chop etildi (QZ): %s", unit_name)
            else:
                logger.warning("Production chek chop etilmadi (QZ): %s", unit_name)
        except Exception as e:
            logger.error("Production printer xatosi (QZ) (%s): %s", unit_name, e)
            results[unit_name] = False

    return results


def open_cash_drawer() -> bool:
    """Cash drawer ochish (QZ Tray orqali, customer printerga)."""
    qz_cfg = _get_qz_config()
    if not qz_cfg.get("qz_print", 0):
        return False
    customer_printer = qz_cfg["customer_qz_printer"]
    if not customer_printer:
        logger.warning("Mijoz QZ printeri topilmadi — cash drawer ochib bo'lmaydi")
        return False

    data = build_cash_drawer_command()
    return _send_to_qz(customer_printer, data, qz_cfg["qz_host"])


def reprint_receipt(order_data: dict, payments_list: list) -> bool:
    """Faqat mijoz printeriga qayta chop etish (QZ Tray)."""
    qz_cfg = _get_qz_config()
    if not qz_cfg.get("qz_print", 0):
        return False
    customer_printer = qz_cfg["customer_qz_printer"]
    if not customer_printer:
        logger.warning("Mijoz QZ printeri topilmadi — qayta chop etib bo'lmaydi")
        return False

    config = {"company": qz_cfg["company"]}
    receipt_data = build_customer_receipt(order_data, payments_list, config)
    return _send_to_qz(customer_printer, receipt_data, qz_cfg["qz_host"])
