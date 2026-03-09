import json
from PyQt6.QtCore import QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import load_config, save_config
from core.logger import get_logger
from core.constants import CUSTOMER_SYNC_LIMIT, DEFAULT_CURRENCY, DEFAULT_CUSTOMER, DEFAULT_UOM
from database.models import Item, Customer, ItemPrice, PendingInvoice, db

logger = get_logger(__name__)


class SyncWorker(QThread):
    progress_update = pyqtSignal(str)
    sync_finished = pyqtSignal(bool, str)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        try:
            self.progress_update.emit("Ma'lumotlar bazasi tekshirilmoqda...")
            db.connect(reuse_if_open=True)

            self._sync_pending_invoices()
            logged_user = self._get_logged_user()
            self._sync_pos_profile(logged_user)
            self._sync_items()
            self._sync_customers()

            self.sync_finished.emit(True, "Sinxronizatsiya muvaffaqiyatli yakunlandi!")
        except Exception as e:
            logger.error("Sinxronizatsiya xatosi: %s", e)
            self.sync_finished.emit(False, str(e))
        finally:
            if not db.is_closed():
                db.close()

    def _sync_pending_invoices(self):
        self.progress_update.emit("Oflayn cheklar yuborilmoqda...")
        pending = PendingInvoice.select().where(PendingInvoice.status == "Pending")

        if not pending.exists():
            return

        count = pending.count()
        for i, inv in enumerate(pending):
            self.progress_update.emit(f"Oflayn chek yuborilmoqda: {i + 1}/{count}")
            try:
                payload = json.loads(inv.invoice_data)
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
                    inv.status = "Synced"
                    inv.error_message = "Muvaffaqiyatli"
                    inv.save()
                else:
                    error_str = str(response)
                    inv.error_message = error_str
                    if self._is_permanent_error(error_str):
                        inv.status = "Failed"
                    inv.save()
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("Chek #%d JSON xatosi: %s", inv.id, e)
            except Exception as e:
                logger.error("Chek #%d sinxronizatsiya xatosi: %s", inv.id, e)

    def _get_logged_user(self) -> str:
        self.progress_update.emit("Foydalanuvchi ma'lumotlari olinmoqda...")
        success, user_data = self.api.call_method("frappe.auth.get_logged_user")
        return user_data if success else "Administrator"

    def _sync_pos_profile(self, logged_user: str):
        self.progress_update.emit("Filial va POS sozlamalari olinmoqda...")
        success, pos_data = self.api.call_method("ury.ury_pos.api.getPosProfile")

        if not success or not isinstance(pos_data, dict):
            raise Exception(f"POS profilini olib bo'lmadi: {pos_data}")

        pos_profile_name = pos_data.get("pos_profile")

        success_detail, profile_doc = self.api.call_method(
            "frappe.client.get", {"doctype": "POS Profile", "name": pos_profile_name}
        )

        payment_methods = []
        default_customer = DEFAULT_CUSTOMER
        if success_detail and isinstance(profile_doc, dict):
            payments = profile_doc.get("payments", [])
            payment_methods = [p.get("mode_of_payment") for p in payments]
            default_customer = profile_doc.get("customer") or DEFAULT_CUSTOMER

        save_config({
            "pos_profile": pos_profile_name,
            "cashier": pos_data.get("cashier") or logged_user,
            "owner": logged_user,
            "company": pos_data.get("company"),
            "currency": pos_data.get("currency", DEFAULT_CURRENCY),
            "payment_methods": payment_methods,
            "default_customer": default_customer,
        })

    def _sync_items(self):
        config = load_config()
        pos_profile_name = config.get("pos_profile")
        self.progress_update.emit(f"'{pos_profile_name}' profilidagi tovarlar yuklanmoqda...")

        success, menu_data = self.api.call_method(
            "ury.ury_pos.api.getRestaurantMenu", {"pos_profile": pos_profile_name}
        )

        if not success or not isinstance(menu_data, dict):
            logger.warning("Menu ma'lumotlari olinmadi")
            return

        items = menu_data.get("items", [])
        if not items:
            return

        with db.atomic():
            Item.delete().execute()
            ItemPrice.delete().execute()

            for item_data in items:
                item_code = item_data.get("item")
                Item.insert(
                    item_code=item_code,
                    item_name=item_data.get("item_name"),
                    item_group=item_data.get("course") or "Barchasi",
                    image=item_data.get("item_image"),
                    uom=DEFAULT_UOM,
                ).on_conflict_replace().execute()

                ItemPrice.insert(
                    name=f"Price-{item_code}",
                    item_code=item_code,
                    price_list=DEFAULT_CURRENCY,
                    price_list_rate=float(item_data.get("rate") or 0),
                    currency=DEFAULT_CURRENCY,
                ).on_conflict_replace().execute()

        logger.info("%d ta tovar sinxronizatsiya qilindi", len(items))

    def _sync_customers(self):
        self.progress_update.emit("Mijozlar yuklanmoqda...")
        fields = '["name", "customer_name", "customer_group", "mobile_no"]'
        customers = self.api.fetch_data("Customer", fields=fields, limit=CUSTOMER_SYNC_LIMIT)
        if not customers:
            return

        with db.atomic():
            for cust_data in customers:
                Customer.insert(
                    name=cust_data.get("name"),
                    customer_name=cust_data.get("customer_name"),
                    customer_group=cust_data.get("customer_group"),
                    phone=cust_data.get("mobile_no"),
                ).on_conflict_replace().execute()

        logger.info("%d ta mijoz sinxronizatsiya qilindi", len(customers))

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
