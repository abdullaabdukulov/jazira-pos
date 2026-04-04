"""Shared invoice processing logic for sync and offline_sync workers."""
import json
from core.logger import get_logger
from core.constants import ORDER_TYPE_MAP

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
    saved_payments = payload.get("_payments") or []
    default_mop = saved_payments[0]["mode_of_payment"] if saved_payments else "Cash"
    defaults = {
        "mode_of_payment": default_mop,
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
#  Submit invoice (make_invoice)
# ──────────────────────────────────────────────────
def submit_invoice(api, payload: dict, invoice_name: str, payments: list) -> tuple[bool, str]:
    """sync_order dan keyin make_invoice chaqirish.

    Returns: (success, error_message)
    """
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
            return True, ""
        else:
            logger.error("make_invoice xatosi (%s): %s", invoice_name, response)
            return False, str(response)
    except Exception as e:
        logger.error("make_invoice chaqiruvida xatolik (%s): %s", invoice_name, e)
        return False, str(e)


# ──────────────────────────────────────────────────
#  Process a cancel-pending invoice
# ──────────────────────────────────────────────────
def process_cancel_pending_invoice(api, invoice) -> tuple[str, str]:
    """CancelPending: serverda yaratib submit qilib, so'ng bekor qilish.

    Returns: (status, message)
        status: 'Cancelled' | 'Failed' | 'CancelPending' (retry)
    """
    try:
        payload = json.loads(invoice.invoice_data)
        cancel_reason = payload.pop("_cancel_reason", "Oflayn bekor qilindi")
        saved_payments = payload.pop("_payments", None)
        existing_order_name = payload.pop("_sync_order_name", None)
        ensure_mandatory_fields(payload)
        if "order_type" in payload:
            payload["order_type"] = ORDER_TYPE_MAP.get(payload["order_type"], payload["order_type"])

        # Step 1: sync_order (agar hali serverda yaratilmagan bo'lsa)
        if not existing_order_name:
            success, response = api.call_method(
                "ury.ury.doctype.ury_order.ury_order.sync_order", payload
            )
            if not success or not isinstance(response, dict) or response.get("status") == "Failure":
                error_str = str(response)
                if is_permanent_error(error_str):
                    return "Failed", error_str
                return "CancelPending", error_str
            existing_order_name = response.get("name")
            if not existing_order_name:
                return "CancelPending", "Invoice name qaytmadi"
            # Keyingi urinish uchun order name saqlash
            try:
                raw = json.loads(invoice.invoice_data)
                raw["_sync_order_name"] = existing_order_name
                invoice.invoice_data = json.dumps(raw)
                invoice.save()
            except Exception as save_err:
                logger.error("_sync_order_name saqlashda xatolik: %s", save_err)

        # Step 2: make_invoice (submit)
        if saved_payments:
            ok, err = submit_invoice(api, payload, existing_order_name, saved_payments)
            if not ok:
                # make_invoice muvaffaqiyatsiz — keyingi urinishda qayta
                return "CancelPending", f"make_invoice xatosi: {err}"

        # Step 3: cancel_order
        ok, response = api.call_method(
            "ury.ury.doctype.ury_order.ury_order.cancel_order",
            {"invoice_id": existing_order_name, "reason": cancel_reason},
        )
        if ok:
            return "Cancelled", f"Serverda bekor qilindi: {existing_order_name}"
        else:
            return "CancelPending", f"cancel_order xatosi: {response}"

    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Chek #%d JSON xatosi: %s", invoice.id, e)
        return "Failed", str(e)
    except Exception as e:
        logger.error("Chek #%d bekor sinxron xatosi: %s", invoice.id, e)
        return "CancelPending", str(e)


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
        existing_order_name = payload.pop("_sync_order_name", None)
        ensure_mandatory_fields(payload)
        if "order_type" in payload:
            payload["order_type"] = ORDER_TYPE_MAP.get(payload["order_type"], payload["order_type"])

        # Agar sync_order allaqachon muvaffaqiyatli bo'lgan bo'lsa (faqat make_invoice xato qilgan),
        # qayta sync_order qilmasdan to'g'ridan-to'g'ri submit_invoice qilamiz
        if existing_order_name and saved_payments:
            ok, err = submit_invoice(api, payload, existing_order_name, saved_payments)
            if ok:
                return "Synced", "Muvaffaqiyatli (faqat make_invoice qayta yuborildi)"
            return "Pending", f"make_invoice qayta urinish xatosi: {err}"

        success, response = api.call_method(
            "ury.ury.doctype.ury_order.ury_order.sync_order", payload
        )

        if success and isinstance(response, dict) and response.get("status") != "Failure":
            invoice_name = response.get("name")
            if invoice_name and saved_payments:
                ok, err = submit_invoice(api, payload, invoice_name, saved_payments)
                if ok:
                    return "Synced", "Muvaffaqiyatli"
                # sync_order OK lekin make_invoice xato — keyingi urinishda faqat make_invoice
                try:
                    raw = json.loads(invoice.invoice_data)
                    raw["_sync_order_name"] = invoice_name
                    invoice.invoice_data = json.dumps(raw)
                    invoice.save()
                except Exception as save_err:
                    logger.error("_sync_order_name saqlashda xatolik: %s", save_err)
                return "Pending", f"sync_order OK, make_invoice xatosi (retry): {err}"
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
