import json
import time
from PyQt6.QtCore import QThread, pyqtSignal
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import OFFLINE_SYNC_INTERVAL
from database.models import PendingInvoice, db

logger = get_logger(__name__)


class OfflineSyncWorker(QThread):
    sync_status = pyqtSignal(str)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.running = True

    def run(self):
        while self.running:
            self._sync_pending_invoices()
            for _ in range(OFFLINE_SYNC_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

    def _sync_pending_invoices(self):
        try:
            db.connect(reuse_if_open=True)
            pending = PendingInvoice.select().where(PendingInvoice.status == "Pending")

            if not pending.exists():
                return

            count = pending.count()
            self.sync_status.emit(f"Oflayn cheklar topildi: {count} ta. Yuborilmoqda...")

            for invoice in pending:
                try:
                    payload = json.loads(invoice.invoice_data)
                    # To'lovlarni ajratib olish (sync_order ga yubormaslik kerak)
                    saved_payments = payload.pop("_payments", None)
                    self._ensure_mandatory_fields(payload)

                    success, response = self.api.call_method(
                        "ury.ury.doctype.ury_order.ury_order.sync_order", payload
                    )

                    if success and isinstance(response, dict) and response.get("status") != "Failure":
                        invoice_name = response.get("name")
                        # make_invoice chaqirish (to'lovlar bilan)
                        if invoice_name and saved_payments:
                            self._submit_invoice(payload, invoice_name, saved_payments)
                        invoice.status = "Synced"
                        invoice.error_message = "Muvaffaqiyatli"
                        invoice.save()
                        self.sync_status.emit(f"Chek #{invoice.id} muvaffaqiyatli serverga yuborildi.")
                    else:
                        error_str = str(response)
                        invoice.error_message = error_str
                        # Server validation xatosi — qayta urinish befoyda
                        if self._is_permanent_error(error_str):
                            invoice.status = "Failed"
                            invoice.save()
                            self.sync_status.emit(f"Chek #{invoice.id} server xatosi (qayta urinilmaydi): {error_str}")
                        else:
                            invoice.save()
                            self.sync_status.emit(f"Chek #{invoice.id} da xatolik: {response}")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error("Chek #%d JSON xatosi: %s", invoice.id, e)
                    self.sync_status.emit(f"Chek #{invoice.id} ma'lumotlarida xatolik: {e}")
                except Exception as e:
                    logger.error("Chek #%d sinxronizatsiya xatosi: %s", invoice.id, e)
                    self.sync_status.emit(f"Chek #{invoice.id} ni yuborishda xato: {e}")

        except Exception as e:
            logger.error("Oflayn sinxronizatsiya xatosi: %s", e)
            self.sync_status.emit(f"Oflayn sinxronizatsiyada xatolik: {e}")
        finally:
            if not db.is_closed():
                db.close()

    def _submit_invoice(self, payload: dict, invoice_name: str, payments: list):
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
            success, response = self.api.call_method(
                "ury.ury.doctype.ury_order.ury_order.make_invoice", payment_payload
            )
            if success:
                logger.info("make_invoice muvaffaqiyatli: %s", invoice_name)
                # Lokal printer orqali chop etish
                self._print_invoice(invoice_name, payload, payments)
            else:
                logger.error("make_invoice xatosi (%s): %s", invoice_name, response)
        except Exception as e:
            logger.error("make_invoice chaqiruvida xatolik (%s): %s", invoice_name, e)

    def _print_invoice(self, invoice_name: str, payload: dict, payments: list):
        """Lokal printer orqali chop etish"""
        try:
            from core.printer import print_receipt
            
            order_data = payload.copy()
            total_amount = sum(float(item.get("qty", 0)) * float(item.get("rate", 0)) for item in payload.get("items", []))
            order_data["total_amount"] = total_amount
            
            success = print_receipt(None, order_data, payments)
            if success:
                logger.info("Invoice %s lokal printer orqali chop etildi", invoice_name)
            else:
                logger.warning("Invoice %s lokal print qilinmadi", invoice_name)
        except Exception as e:
            logger.error("Lokal print xatosi: %s", e)

    def stop(self):
        self.running = False

    @staticmethod
    def _is_permanent_error(error_msg: str) -> bool:
        permanent_keywords = [
            "validationerror",
            "permissionerror",
            "doesnotexisterror",
            "mandatoryerror",
            "invalidcolumnname",
            "server xatosi (417)",
            "server xatosi (403)",
            "server xatosi (404)",
        ]
        msg_lower = error_msg.lower()
        return any(kw in msg_lower for kw in permanent_keywords)

    @staticmethod
    def _ensure_mandatory_fields(payload: dict):
        defaults = {
            "mode_of_payment": "Cash",
            "no_of_pax": 1,
            "last_invoice": "",
            "waiter": payload.get("cashier") or "Administrator",
            "room": "",
            "aggregator_id": "",
            "items": [],
        }
        for field, default in defaults.items():
            if field not in payload:
                payload[field] = default
