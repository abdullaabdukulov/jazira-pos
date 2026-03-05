from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from core.api import FrappeAPI
from database.models import PendingInvoice, db
import json
import time

class OfflineSyncWorker(QThread):
    sync_status = pyqtSignal(str) # Emits log messages

    def __init__(self):
        super().__init__()
        self.api = FrappeAPI()
        self.running = True

    def run(self):
        while self.running:
            self.sync_pending_invoices()
            
            # Sleep for 30 seconds before checking again
            for _ in range(30):
                if not self.running:
                    break
                time.sleep(1)

    def sync_pending_invoices(self):
        try:
            db.connect(reuse_if_open=True)
            pending_invoices = PendingInvoice.select().where(PendingInvoice.status == "Pending")
            
            if not pending_invoices:
                return

            self.sync_status.emit(f"Oflayn cheklar topildi: {len(pending_invoices)} ta. Yuborilmoqda...")

            for invoice in pending_invoices:
                try:
                    payload = json.loads(invoice.invoice_data)
                    success, response = self.api.call_method("ury.ury.doctype.ury_order.ury_order.sync_order", payload)
                    
                    if success and isinstance(response, dict) and response.get("status") != "Failure":
                        invoice.status = "Synced"
                        invoice.error_message = "Muvaffaqiyatli"
                        invoice.save()
                        self.sync_status.emit(f"Chek #{invoice.id} muvaffaqiyatli serverga yuborildi.")
                    else:
                        invoice.error_message = str(response)
                        invoice.save()
                        self.sync_status.emit(f"Chek #{invoice.id} da xatolik: {str(response)}")
                except Exception as e:
                    self.sync_status.emit(f"Chek #{invoice.id} ni yuborishda xato: {e}")
                    
        except Exception as e:
            self.sync_status.emit(f"Oflayn sinxronizatsiyada xatolik: {e}")
        finally:
            if not db.is_closed():
                db.close()

    def stop(self):
        self.running = False
