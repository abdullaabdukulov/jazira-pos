import time
from PyQt6.QtCore import QThread, pyqtSignal
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import OFFLINE_SYNC_INTERVAL
from database.models import PendingInvoice, db
from database.invoice_processor import process_pending_invoice

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
                status, message = process_pending_invoice(self.api, invoice)
                invoice.status = status
                invoice.error_message = message
                invoice.save()

                if status == "Synced":
                    self.sync_status.emit(f"Chek #{invoice.id} muvaffaqiyatli serverga yuborildi.")
                elif status == "Failed":
                    self.sync_status.emit(f"Chek #{invoice.id} server xatosi (qayta urinilmaydi): {message}")
                else:
                    self.sync_status.emit(f"Chek #{invoice.id} da xatolik: {message}")

        except Exception as e:
            logger.error("Oflayn sinxronizatsiya xatosi: %s", e)
            self.sync_status.emit(f"Oflayn sinxronizatsiyada xatolik: {e}")
        finally:
            if not db.is_closed():
                db.close()

    def stop(self):
        self.running = False
