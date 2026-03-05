from PyQt6.QtCore import QThread, pyqtSignal
from core.api import FrappeAPI
from core.config import save_config
from database.models import Item, Customer, ItemPrice, db
import json

class SyncWorker(QThread):
    progress_update = pyqtSignal(str)
    sync_finished = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.api = FrappeAPI()

    def run(self):
        try:
            self.progress_update.emit("Ma'lumotlar bazasi tekshirilmoqda...")
            db.connect(reuse_if_open=True)
            
            # 0. Get current logged in user (to use as owner)
            self.progress_update.emit("Foydalanuvchi ma'lumotlari olinmoqda...")
            success_user, user_data = self.api.call_method("frappe.auth.get_logged_user")
            logged_user = user_data if success_user else "Administrator"

            # 1. POS Profilini olish (Filial va kassa ma'lumotlari)
            self.progress_update.emit("Filial va POS sozlamalari olinmoqda...")
            success, pos_profile_data = self.api.call_method("ury.ury_pos.api.getPosProfile")
            
            if not success or not isinstance(pos_profile_data, dict):
                raise Exception(f"POS profilini olib bo'lmadi: {pos_profile_data}")

            pos_profile_name = pos_profile_data.get("pos_profile")
            
            # Fetch full POS Profile to get Payment Methods and Default Customer
            success_detail, profile_doc = self.api.call_method("frappe.client.get", {
                "doctype": "POS Profile",
                "name": pos_profile_name
            })
            
            payment_methods = []
            default_customer = "guest" # Default fallback
            if success_detail and isinstance(profile_doc, dict):
                payments = profile_doc.get("payments", [])
                payment_methods = [p.get("mode_of_payment") for p in payments]
                default_customer = profile_doc.get("customer") or "guest"

            save_config({
                "pos_profile": pos_profile_name,
                "cashier": pos_profile_data.get("cashier") or logged_user,
                "owner": logged_user,
                "company": pos_profile_data.get("company"),
                "currency": pos_profile_data.get("currency", "UZS"),
                "payment_methods": payment_methods,
                "default_customer": default_customer
            })

            # 2. Shu profilga tegishli MENU ni va TOVARLARNI olish
            self.progress_update.emit(f"'{pos_profile_name}' profilidagi tovarlar yuklanmoqda...")
            success, menu_data = self.api.call_method("ury.ury_pos.api.getRestaurantMenu", {"pos_profile": pos_profile_name})
            
            if success and isinstance(menu_data, dict):
                items = menu_data.get("items", [])
                if items:
                    with db.atomic():
                        # Clear old items
                        Item.delete().execute()
                        ItemPrice.delete().execute()
                        
                        for item_data in items:
                            item_code = item_data.get('item')
                            Item.insert(
                                item_code=item_code,
                                item_name=item_data.get('item_name'),
                                item_group=item_data.get('course') or 'Barchasi',
                                image=item_data.get('item_image'),
                                uom="Dona"
                            ).on_conflict_replace().execute()
                            
                            ItemPrice.insert(
                                name=f"Price-{item_code}",
                                item_code=item_code,
                                price_list="Standard", 
                                price_list_rate=float(item_data.get('rate') or 0),
                                currency="UZS"
                            ).on_conflict_replace().execute()

            # 3. Mijozlarni yuklash
            self.progress_update.emit("Mijozlar yuklanmoqda...")
            fields = '["name", "customer_name", "customer_group", "mobile_no"]'
            customers = self.api.fetch_data("Customer", fields=fields, limit=1000)
            if customers:
                with db.atomic():
                    for cust_data in customers:
                        Customer.insert(
                            name=cust_data.get('name'),
                            customer_name=cust_data.get('customer_name'),
                            customer_group=cust_data.get('customer_group'),
                            phone=cust_data.get('mobile_no')
                        ).on_conflict_replace().execute()

            self.sync_finished.emit(True, "Sinxronizatsiya muvaffaqiyatli yakunlandi!")
        except Exception as e:
            self.sync_finished.emit(False, str(e))
        finally:
            if not db.is_closed():
                db.close()
