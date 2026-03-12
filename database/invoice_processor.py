"""Shared invoice processing logic for sync and offline_sync workers."""
import json
from core.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────
#  Permanent error detection
# ──────────────────────────────────────────────────
PERMANENT_KEYWORDS = [
    "validationerror",
    "permissionerror",
    "doesnotexisterror",
    "mandatoryerror",
    "invalidcolumnname",
    "server xatosi (417)",
    "server xatosi (403)",
    "server xatosi (404)",
]


def is_permanent_error(error_msg: str) -> bool:
    msg_lower = error_msg.lower()
    return any(kw in msg_lower for kw in PERMANENT_KEYWORDS)


# ──────────────────────────────────────────────────
#  Mandatory field defaults
# ──────────────────────────────────────────────────
def ensure_mandatory_fields(payload: dict):
    defaults = {
        "mode_of_payment": "Cash",
        "no_of_pax": 1,
        "last_invoice": "",
        "waiter": payload.get("cashier") or "Administrator",  # server API talab qiladi
        "room": "",
        "aggregator_id": "",
        "items": [],
    }
    for field, default in defaults.items():
        if field not in payload:
            payload[field] = default


# ──────────────────────────────────────────────────
#  Submit invoice (make_invoice + print)
# ──────────────────────────────────────────────────
def submit_invoice(api, payload: dict, invoice_name: str, payments: list):
    """sync_order dan keyin make_invoice chaqirish va chop etish"""
    try:
        payment_payload = {
            "customer": payload.get("customer"),
            "payments": payments,
            "cashier": payload.get("cashier"),
            "pos_profile": payload.get("pos_profile"),
            "owner": payload.get("owner"),
            "additionalDiscount": 0,
            "table": None,
            "invoice": invoice_name,
        }
        success, response = api.call_method(
            "ury.ury.doctype.ury_order.ury_order.make_invoice", payment_payload
        )
        if success:
            logger.info("make_invoice muvaffaqiyatli: %s", invoice_name)
            print_invoice(invoice_name, payload, payments)
        else:
            logger.error("make_invoice xatosi (%s): %s", invoice_name, response)
    except Exception as e:
        logger.error("make_invoice chaqiruvida xatolik (%s): %s", invoice_name, e)


def print_invoice(invoice_name: str, payload: dict, payments: list):
    """Lokal printer orqali chop etish"""
    try:
        from core.printer import print_receipt

        order_data = payload.copy()
        total_amount = sum(
            float(item.get("qty", 0)) * float(item.get("rate", 0))
            for item in payload.get("items", [])
        )
        order_data["total_amount"] = total_amount

        results = print_receipt(None, order_data, payments)
        for p_type, success in results.items():
            if success:
                logger.info("Invoice %s — %s printer chop etildi", invoice_name, p_type)
            else:
                logger.warning("Invoice %s — %s printer chop etilmadi", invoice_name, p_type)
    except Exception as e:
        logger.error("Lokal print xatosi: %s", e)


# ──────────────────────────────────────────────────
#  Process a single pending invoice
# ──────────────────────────────────────────────────
def process_pending_invoice(api, invoice) -> tuple[str, str]:
    """Bitta pending invoiceni serverga yuborish.

    Returns: (status, message)
        status: 'Synced' | 'Failed' | 'Pending' (retry)
    """
    try:
        payload = json.loads(invoice.invoice_data)
        saved_payments = payload.pop("_payments", None)
        ensure_mandatory_fields(payload)

        success, response = api.call_method(
            "ury.ury.doctype.ury_order.ury_order.sync_order", payload
        )

        if success and isinstance(response, dict) and response.get("status") != "Failure":
            invoice_name = response.get("name")
            if invoice_name and saved_payments:
                submit_invoice(api, payload, invoice_name, saved_payments)
            return "Synced", "Muvaffaqiyatli"
        else:
            error_str = str(response)
            if is_permanent_error(error_str):
                return "Failed", error_str
            return "Pending", error_str

    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Chek #%d JSON xatosi: %s", invoice.id, e)
        return "Failed", str(e)
    except Exception as e:
        logger.error("Chek #%d sinxronizatsiya xatosi: %s", invoice.id, e)
        return "Pending", str(e)
