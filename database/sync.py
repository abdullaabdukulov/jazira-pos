from PyQt6.QtCore import QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import load_config, save_config
from core.logger import get_logger
from core.constants import CUSTOMER_SYNC_LIMIT, DEFAULT_CURRENCY, DEFAULT_CUSTOMER, DEFAULT_UOM
from database.models import Item, Customer, ItemPrice, PendingInvoice, db
from database.invoice_processor import process_pending_invoice

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
            self._sync_production_units()
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

    def _sync_production_units(self):
        """Serverdan production unitlarni sinxronizatsiya qilish.

        Har bir unit o'z item_groups va printer sozlamalariga ega.
        Lokal printer_device sozlamalari saqlanadi.
        """
        config = load_config()
        pos_profile = config.get("pos_profile")
        if not pos_profile:
            logger.warning("POS profile topilmadi — production unit sinx o'tkazib yuborildi")
            return

        self.progress_update.emit("Production unitlar yuklanmoqda...")

        success, units = self.api.call_method("frappe.client.get_list", {
            "doctype": "URY Production Unit",
            "filters": {"pos_profile": pos_profile},
            "fields": ["name", "production"],
            "limit_page_length": 50,
        })

        if not success or not isinstance(units, list):
            logger.warning("Production unitlarni olib bo'lmadi")
            return

        if not units:
            logger.info("Bu filialda production unit yo'q")
            return

        # Mavjud lokal printer sozlamalarini saqlash (device/win_name)
        existing = config.get("production_units", [])
        existing_printers = {
            u.get("name", ""): {
                "printer_device": u.get("printer_device", ""),
                "printer_win_name": u.get("printer_win_name", ""),
            }
            for u in existing
        }

        production_units = []
        for unit in units:
            unit_name = unit.get("production", unit.get("name", ""))

            # Har bir unit uchun item_groups olish
            success2, unit_doc = self.api.call_method(
                "frappe.client.get",
                {"doctype": "URY Production Unit", "name": unit["name"]}
            )
            item_groups = []
            if success2 and isinstance(unit_doc, dict):
                item_groups = [
                    ig.get("item_group", "")
                    for ig in unit_doc.get("item_groups", [])
                    if ig.get("item_group")
                ]

            existing_printer = existing_printers.get(unit_name, {})
            production_units.append({
                "name": unit_name,
                "item_groups": item_groups,
                "printer_device": existing_printer.get("printer_device", ""),
                "printer_win_name": existing_printer.get("printer_win_name", ""),
            })

        save_config({"production_units": production_units})
        logger.info("%d ta production unit sinxronizatsiya qilindi", len(production_units))
