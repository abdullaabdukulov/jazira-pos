"""SaveOrderWorker — to'lovsiz buyurtmani serverga yuborish.

TZ 4.2.2 ga muvofiq:
- sync_order chaqiriladi (lekin make_invoice yo'q)
- Draft POS Invoice yaratiladi
- KOT avto chiqadi (sync_order ichida kot_execute)
- Stol rejimida URY Table.occupied=1 avto
- Tarmoq xatosi → PendingInvoice ga (kassir uchun)
- Ofitsant rolida tarmoq xatosi bo'lsa — MainWindow blok overlay chaqiradi (Phase 2)
"""
import json
import uuid
from PyQt6.QtCore import QThread, pyqtSignal

from core.api import FrappeAPI
from core.config import load_config
from core.constants import ORDER_TYPE_MAP
from core.logger import get_logger
from database.models import PendingInvoice, db
from database.invoice_processor import is_permanent_error

logger = get_logger(__name__)


class SaveOrderWorker(QThread):
    """sync_order chaqiriladi, make_invoice chaqirilmaydi → Draft qoladi."""

    # signal: (success, message, invoice_name)
    result_ready = pyqtSignal(bool, str, str)

    def __init__(self, order_data: dict, api: FrappeAPI, role: str = "Kassir"):
        super().__init__()
        self.order_data = dict(order_data)
        self.api = api
        self.role = role
        self.offline_id = str(uuid.uuid4())

    def run(self):
        try:
            config = load_config()

            # KPI uchun (TZ Phase 3):
            # - waiter = zakazni qabul qilgan foydalanuvchi (Ofitsant yoki Kassir).
            #   Aktiv URY POS Cashier'ning email'i (`user`).
            # - cashier = to'lov qabul qiluvchi kassir. SaveOrderWorker payti hali
            #   to'lov yo'q — placeholder sifatida config.cashier (POS Profile default).
            #   make_invoice paytida haqiqiy kassirga yangilanadi.
            active_user = str(self.order_data.get("active_cashier_user") or "")
            default_cashier = str(config.get("cashier", "Administrator"))

            if self.role == "Ofitsant":
                waiter_user = active_user or default_cashier
                cashier_user = default_cashier  # placeholder — kassir keyin to'laydi
            else:
                # Kassir o'zi yozadi va to'laydi
                waiter_user = active_user or default_cashier
                cashier_user = active_user or default_cashier

            payload = {
                "items": [
                    {
                        "item": str(i["item_code"]),
                        "item_name": str(i["name"]),
                        "qty": float(i["qty"]),
                        "rate": float(i["price"]),
                        "comment": "",
                    }
                    for i in self.order_data["items"]
                ],
                "cashier": cashier_user,
                "owner": str(config.get("owner", "Administrator")),
                "mode_of_payment": (config.get("payment_methods") or ["Cash"])[0],
                "customer": str(self.order_data.get("customer") or config.get("default_customer", "")),
                "no_of_pax": 1,
                "last_invoice": "",
                "waiter": waiter_user,
                "pos_profile": str(config.get("pos_profile", "")),
                "order_type": ORDER_TYPE_MAP.get(
                    self.order_data.get("order_type", "Shu yerda"), "Dine In"
                ),
                "ticket_number": (
                    int(self.order_data.get("ticket_number", 0))
                    if self.order_data.get("ticket_number") else 0
                ),
                "comments": str(self.order_data.get("comment") or ""),
                "table": str(self.order_data.get("restaurant_table", "")) or None,
                "room": "",
                "aggregator_id": "",
                "active_cashier": str(self.order_data.get("active_cashier", "")),
                "active_cashier_role": self.role,
                "client_ref": self.offline_id,
            }

            ok, response = self.api.call_method(
                "ury.ury.doctype.ury_order.ury_order.sync_order", payload
            )

            if ok and isinstance(response, dict):
                if response.get("status") == "Failure":
                    err = str(response.get("message") or response)
                    self._handle_failure(err, payload)
                    return
                invoice_name = response.get("name", "")
                self.result_ready.emit(True, "Buyurtma saqlandi", invoice_name)
            else:
                self._handle_failure(str(response), payload)

        except Exception as e:
            logger.error("SaveOrderWorker xato: %s", e)
            self._handle_failure(str(e), {})
        finally:
            if not db.is_closed():
                db.close()

    def _handle_failure(self, error: str, payload: dict):
        """Tarmoq xatosi → kassir uchun PendingInvoice; ofitsant uchun xato qaytariladi (blok overlay)."""
        # Ofitsant rolida lokal saqlash YO'Q — TZ 4.7.4
        if self.role == "Ofitsant":
            self.result_ready.emit(False, f"Tarmoq xatosi: {error}", "")
            return

        if is_permanent_error(error):
            self.result_ready.emit(False, f"Server rad etdi: {error}", "")
            return

        # Kassir — lokal saqlash (Phase 1 da bu yo'l ham PendingInvoice uchun)
        try:
            save_data = dict(payload)
            save_data["_save_only"] = True   # invoice_processor uchun belgi
            PendingInvoice.create(
                offline_id=self.offline_id,
                invoice_data=json.dumps(save_data),
                status="Pending",
                error_message=str(error),
            )
            self.result_ready.emit(
                True,
                "Tarmoq yo'q — buyurtma oflayn saqlandi. Internet tiklangach yuboriladi.",
                "",
            )
        except Exception as e:
            logger.error("SaveOrderWorker oflayn saqlash xatosi: %s", e)
            self.result_ready.emit(False, f"Oflayn saqlashda xato: {e}", "")
