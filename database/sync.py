from PyQt6.QtCore import QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import load_config, save_config
from core.logger import get_logger
from core.constants import CUSTOMER_SYNC_LIMIT, DEFAULT_CURRENCY, DEFAULT_CUSTOMER, DEFAULT_UOM
from database.models import Item, Customer, ItemPrice, PendingInvoice, db
from database.invoice_processor import process_pending_invoice, process_cancel_pending_invoice

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

            self._sync_pending_invoices()
            logged_user = self._get_logged_user()
            self._sync_pos_profile(logged_user)
            self._sync_printer_config()
            items_ok = self._sync_items()
            customers_ok = self._sync_customers()

            warnings = []
            config = load_config()
            if not config.get("pos_profile"):
                warnings.append("POS profil topilmadi")
            if not items_ok:
                warnings.append("Tovarlar yangilanmadi")
            if not customers_ok:
                warnings.append("Mijozlar yangilanmadi")

            if warnings:
                self.sync_finished.emit(True, "Sinxronizatsiya yakunlandi (ogohlantirishlar: " + "; ".join(warnings) + ")")
            else:
                self.sync_finished.emit(True, "Sinxronizatsiya muvaffaqiyatli yakunlandi!")
        except Exception as e:
            logger.error("Sinxronizatsiya xatosi: %s", e)
            self.sync_finished.emit(False, str(e))
        finally:
            # Worker thread tugayotganda o'z DB ulanishini yopish
            # (boshqa threadlarga ta'sir qilmaydi — har bir thread o'z ulanishiga ega)
            if not db.is_closed():
                db.close()

    def _sync_pending_invoices(self):
        self.progress_update.emit("Oflayn cheklar yuborilmoqda...")
        pending = PendingInvoice.select().where(
            PendingInvoice.status.in_(["Pending", "CancelPending"])
        )

        if not pending.exists():
            return

        count = pending.count()
        for i, inv in enumerate(pending):
            self.progress_update.emit(f"Oflayn chek yuborilmoqda: {i + 1}/{count}")
            if inv.status == "CancelPending":
                status, message = process_cancel_pending_invoice(self.api, inv)
            else:
                status, message = process_pending_invoice(self.api, inv)
            inv.status = status
            inv.error_message = message
            inv.save()

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

        # default_customer: getPosProfile dan, yo'q bo'lsa DEFAULT_CUSTOMER
        default_customer = pos_data.get("default_customer") or DEFAULT_CUSTOMER

        # Payment methods — endi getPosProfile dan keladi (alohida API chaqiruvi shart emas)
        # Server bo'sh ro'yxat qaytarsa, eski cache ni saqlash (yo'qolib qolmasin)
        server_payments = pos_data.get("payment_methods")
        if isinstance(server_payments, list) and server_payments:
            payment_methods = [p for p in server_payments if p]
        else:
            payment_methods = load_config().get("payment_methods", [])

        # Faol buyurtma turlarini aniqlash
        _ot_map = [
            (pos_data.get("order_type_dine_in", 1),        "Shu yerda"),
            (pos_data.get("order_type_take_away", 1),       "Saboy"),
            (pos_data.get("order_type_delivery", 0),        "Dastavka"),
            (pos_data.get("order_type_delivery_saboy", 0),  "Dastavka Saboy"),
        ]
        enabled_order_types = [name for flag, name in _ot_map if flag]
        if not enabled_order_types:
            enabled_order_types = ["Shu yerda", "Saboy"]  # fallback

        # Kassirlar ro'yxati: server pin_hash ni ustunlik bilan qabul qilish
        server_cashiers = pos_data.get("cashiers")
        local_cashiers = {
            (c.get("full_name") or c.get("name", "")).lower(): c
            for c in load_config().get("cashiers", []) if c.get("name")
        }
        if isinstance(server_cashiers, list) and server_cashiers:
            cashiers_to_save = []
            for sc in server_cashiers:
                full_name = sc.get("full_name") or sc.get("name", "")
                server_pin = sc.get("pin", "")
                local = local_cashiers.get(full_name.lower(), {})
                pin = server_pin if server_pin else local.get("pin", "")
                cashiers_to_save.append({
                    "name": full_name,
                    "full_name": full_name,
                    "user": sc.get("user", ""),
                    "pin": pin,
                })
        else:
            cashiers_to_save = load_config().get("cashiers", [])

        save_config({
            "pos_profile": pos_profile_name,
            "cashier": pos_data.get("cashier") or logged_user,
            "owner": logged_user,
            "company": pos_data.get("company"),
            "currency": pos_data.get("currency", DEFAULT_CURRENCY),
            "payment_methods": payment_methods,
            "default_customer": default_customer,
            # Desktop POS customization
            "show_comment":  pos_data.get("show_comment", 1),
            "show_ticket":   pos_data.get("show_ticket", 1),
            "show_customer": pos_data.get("show_customer", 1),
            "show_history":  pos_data.get("show_history", 1),
            "show_shifts":   pos_data.get("show_shifts", 1),
            "enabled_order_types": enabled_order_types,
            "item_columns":    pos_data.get("item_columns", 0),
            "company_logo":    pos_data.get("company_logo", ""),
            "receipt_footer":  pos_data.get("receipt_footer", ""),
            "cashiers": cashiers_to_save,
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
            self.progress_update.emit("Tovarlar olinmadi — o'tkazib yuborildi")
            return False

        items = menu_data.get("items", [])
        if not items:
            return True

        # Har bir item uchun item_group ni olish (batch)
        item_codes = [it.get("item") for it in items if it.get("item")]
        item_groups_map = {}
        if item_codes:
            success_ig, ig_data = self.api.call_method(
                "frappe.client.get_list", {
                    "doctype": "Item",
                    "filters": {"name": ["in", item_codes]},
                    "fields": ["name", "item_group"],
                    "limit_page_length": len(item_codes),
                }
            )
            if success_ig and isinstance(ig_data, list):
                item_groups_map = {d["name"]: d.get("item_group", "") for d in ig_data}

        # Serverdan kelgan item kodlari
        server_item_codes = set()

        with db.atomic():
            for item_data in items:
                item_code = item_data.get("item")
                server_item_codes.add(item_code)

                Item.insert(
                    item_code=item_code,
                    item_name=item_data.get("item_name"),
                    item_group=item_groups_map.get(item_code, ""),
                    course=item_data.get("course", ""),
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

            # Serverda yo'q bo'lgan eski itemlarni tozalash
            if server_item_codes:
                Item.delete().where(Item.item_code.not_in(server_item_codes)).execute()
                ItemPrice.delete().where(ItemPrice.item_code.not_in(server_item_codes)).execute()

        logger.info("%d ta tovar sinxronizatsiya qilindi", len(items))
        return True

    def _sync_customers(self):
        self.progress_update.emit("Mijozlar yuklanmoqda...")
        fields = '["name", "customer_name", "customer_group", "mobile_no"]'
        customers = self.api.fetch_data("Customer", fields=fields, limit=CUSTOMER_SYNC_LIMIT)
        if not customers:
            return False

        with db.atomic():
            for cust_data in customers:
                Customer.insert(
                    name=cust_data.get("name"),
                    customer_name=cust_data.get("customer_name"),
                    customer_group=cust_data.get("customer_group"),
                    phone=cust_data.get("mobile_no"),
                ).on_conflict_replace().execute()

        logger.info("%d ta mijoz sinxronizatsiya qilindi", len(customers))
        return True

    def _sync_printer_config(self):
        """Serverdan printer konfiguratsiyasini sinxronizatsiya qilish.

        Bitta API chaqiruv orqali:
        - print_enabled (chop etish yoqilganmi)
        - customer_printer (mijoz cheki printeri device nomi)
        - Production unitlar (har biri printer_name va item_groups bilan)
        """
        config = load_config()
        pos_profile = config.get("pos_profile")
        if not pos_profile:
            logger.warning("POS profile topilmadi — printer config sinx o'tkazib yuborildi")
            return

        self.progress_update.emit("Printer sozlamalari yuklanmoqda...")

        success, result = self.api.call_method(
            "ury.ury_pos.api.get_printer_config",
            {"pos_profile": pos_profile}
        )

        if not success or not isinstance(result, dict):
            logger.warning("Printer konfiguratsiyasini olib bo'lmadi")
            return

        printer_config = {
            "customer_printer": result.get("customer_printer", ""),
            "production_units": result.get("production_units", []),
        }

        save_config(printer_config)
        units_count = len(printer_config["production_units"])
        logger.info(
            "Printer config sinxronizatsiya qilindi: %d ta production unit, "
            "customer_printer='%s'",
            units_count,
            printer_config["customer_printer"],
        )


