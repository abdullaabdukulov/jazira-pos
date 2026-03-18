from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QSplitter, QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from database.sync import SyncWorker
from database.offline_sync import OfflineSyncWorker
from database.migrations import initialize_db
from database.models import PendingInvoice, PosShift, db
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import MONITOR_INTERVAL_MS
from core.config import load_config
from ui.components.item_browser import ItemBrowser
from ui.components.cart_widget import CartWidget
from ui.components.checkout_window import CheckoutWindow
from ui.components.history_window import HistoryWindow
from ui.components.offline_queue_window import OfflineQueueWindow
from ui.components.pos_opening import PosOpeningDialog
from ui.components.pos_closing import PosClosingDialog
from ui.components.pos_shifts_window import PosShiftsWindow
from ui.components.dialogs import InfoDialog, ConfirmDialog

logger = get_logger(__name__)


class ConnectivityCheckWorker(QThread):
    """Server bilan aloqani tekshirish — background thread'da."""
    finished = pyqtSignal(bool)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        try:
            success, _ = self.api.call_method("frappe.auth.get_logged_user")
            self.finished.emit(success)
        except Exception:
            self.finished.emit(False)


class PosOpeningCheckWorker(QThread):
    """Serverdan ochiq kassa borligini tekshirish.

    Mantiq:
    1. Server bilan aloqa bor → server javobiga ishonish (lokal bazani sinxronlash)
    2. Server bilan aloqa yo'q → faqat shu holda lokal bazaga qarash
    """
    finished = pyqtSignal(bool, str)  # has_opening, opening_entry_name

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        success, response = self.api.call_method("ury.ury_pos.api.checkPosOpening")

        if success and isinstance(response, dict):
            # Server javob berdi — unga ishonish kerak
            status = response.get("status")
            if status == "open":
                opening_entry = response.get("opening_entry", "")
                self._sync_local_shift(opening_entry)
                self.finished.emit(True, opening_entry)
            else:
                # Server: kassa yopiq — lokal bazani ham tozalash
                self._close_local_shifts()
                self.finished.emit(False, "")
        else:
            # Server bilan aloqa yo'q — faqat lokal bazaga qarash
            try:
                db.connect(reuse_if_open=True)
                shift = PosShift.select().where(PosShift.status == "Open").first()
                if shift:
                    self.finished.emit(True, shift.opening_entry or "")
                else:
                    self.finished.emit(False, "")
            except Exception:
                self.finished.emit(False, "")
            finally:
                if not db.is_closed():
                    db.close()

    def _sync_local_shift(self, opening_entry: str):
        """Server ochiq desa — lokal bazada ham ochiq shift bo'lishini ta'minlash."""
        try:
            db.connect(reuse_if_open=True)
            existing = PosShift.select().where(
                (PosShift.status == "Open") & (PosShift.opening_entry == opening_entry)
            ).first()
            if not existing:
                # Eski ochiq shiftlarni yopish + yangi yaratish
                PosShift.update(status="Closed").where(PosShift.status == "Open").execute()
                PosShift.create(
                    opening_entry=opening_entry,
                    pos_profile="",
                    company="",
                    user=self.api.user or "",
                    status="Open",
                )
        except Exception as e:
            logger.debug("Lokal shift sinxronlash: %s", e)
        finally:
            if not db.is_closed():
                db.close()

    def _close_local_shifts(self):
        """Server yopiq desa — lokal bazadagi barcha ochiq shiftlarni yopish."""
        try:
            import datetime
            db.connect(reuse_if_open=True)
            PosShift.update(
                status="Closed", closed_at=datetime.datetime.now()
            ).where(PosShift.status == "Open").execute()
        except Exception as e:
            logger.debug("Lokal shiftlarni yopish: %s", e)
        finally:
            if not db.is_closed():
                db.close()


class MainWindow(QMainWindow):
    logout_requested = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.opening_entry = None  # Ochiq kassa nomi
        self.setWindowTitle("Jazira POS")
        self.showMaximized()

        initialize_db()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Bar ---
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(10, 4, 10, 4)
        top_bar.setSpacing(12)

        # ── Jazira Brand Logo ──────────────────
        logo_widget = QWidget()
        logo_widget.setFixedWidth(200)
        logo_widget.setStyleSheet("""
            QWidget {
                background: transparent;
                border-left: 4px solid #f59e0b;
                padding-left: 10px;
            }
        """)
        logo_layout = QVBoxLayout(logo_widget)
        logo_layout.setContentsMargins(10, 2, 0, 2)
        logo_layout.setSpacing(0)

        brand_name = QLabel("Jazira°")
        brand_name.setStyleSheet("""
            font-size: 26px;
            font-weight: 900;
            font-style: italic;
            color: #d97706;
            background: transparent;
        """)

        brand_sub = QLabel("DONER & SHAWERMA")
        brand_sub.setStyleSheet("""
            font-size: 8px;
            font-weight: 700;
            color: #92400e;
            background: transparent;
            letter-spacing: 2px;
        """)

        logo_layout.addWidget(brand_name)
        logo_layout.addWidget(brand_sub)
        top_bar.addWidget(logo_widget)

        # ── Filial / Company badge ──────────────
        config = load_config()
        company_name = config.get("company", "")
        pos_profile = config.get("pos_profile", "")

        self.company_badge = QLabel()
        self._update_company_badge(company_name, pos_profile)
        top_bar.addWidget(self.company_badge)

        # Connection Status
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet("background-color: #94a3b8; border-radius: 6px;")

        self.status_text = QLabel("Checking...")
        self.status_text.setStyleSheet("font-weight: bold; color: #64748b; font-size: 13px;")

        top_bar.addWidget(self.status_dot)
        top_bar.addWidget(self.status_text)
        top_bar.addStretch()

        # ── helper for consistent top-bar button style ──────────
        def _tb_btn(label: str, bg: str, color: str = "white",
                    hover: str = "", border: str = "none") -> QPushButton:
            b = QPushButton(label)
            b.setFixedHeight(48)
            h = hover or bg
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {bg}; color: {color};
                    font-weight: 700; font-size: 13px;
                    border-radius: 10px; border: {border};
                    padding: 0 16px;
                }}
                QPushButton:hover {{ background: {h}; }}
                QPushButton:pressed {{ opacity: 0.85; }}
                QPushButton:disabled {{ background: #f1f5f9; color: #94a3b8; }}
            """)
            return b

        # Offline Queue Button — neutral pill
        self.offline_btn = _tb_btn(
            "📦  Offline: 0", "#f1f5f9", "#374151",
            hover="#e2e8f0", border="1px solid #e2e8f0",
        )
        self.offline_btn.clicked.connect(self.show_offline_queue)
        top_bar.addWidget(self.offline_btn)

        # New Sale Button — green accent
        self.add_sale_btn = _tb_btn(
            "＋  Yangi sotuv", "#22c55e", hover="#16a34a",
        )
        self.add_sale_btn.clicked.connect(self.add_new_sale_tab)
        top_bar.addWidget(self.add_sale_btn)

        # History Button — indigo pill
        self.history_btn = _tb_btn(
            "🕐  Tarix", "#6366f1", hover="#4338ca",
        )
        self.history_btn.clicked.connect(self.show_history)
        top_bar.addWidget(self.history_btn)

        # Sync Button — blue
        self.sync_btn = _tb_btn(
            "⟳  Sinxronlash", "#3b82f6", hover="#2563eb",
        )
        self.sync_btn.clicked.connect(self.start_sync)
        top_bar.addWidget(self.sync_btn)

        # Printer Settings Button — slate
        self.printer_btn = _tb_btn(
            "Printer", "#475569", hover="#334155",
        )
        self.printer_btn.clicked.connect(self.show_printer_settings)
        top_bar.addWidget(self.printer_btn)

        # Kassa tarixi Button — slate
        self.shifts_btn = _tb_btn(
            "Kassa tarixi", "#475569", hover="#334155",
        )
        self.shifts_btn.clicked.connect(self.show_shifts_history)
        top_bar.addWidget(self.shifts_btn)

        # Kassa ochish Button — green (kassa ochilmagan holatda ko'rinadi)
        self.open_shift_btn = _tb_btn(
            "Kassa ochish", "#16a34a", hover="#15803d",
        )
        self.open_shift_btn.clicked.connect(self._show_pos_opening_dialog)
        self.open_shift_btn.setVisible(False)
        top_bar.addWidget(self.open_shift_btn)

        # Kassa yopish Button — orange/red
        self.close_shift_btn = _tb_btn(
            "Kassa yopish", "#dc2626", hover="#b91c1c",
        )
        self.close_shift_btn.clicked.connect(self.show_pos_closing)
        top_bar.addWidget(self.close_shift_btn)

        # Logout Button — amber
        self.logout_btn = _tb_btn(
            "🔓  Chiqish", "#f59e0b", hover="#d97706",
        )
        self.logout_btn.clicked.connect(self.request_logout)
        top_bar.addWidget(self.logout_btn)

        # Exit Button — red
        self.exit_btn = _tb_btn(
            "✕  Dasturdan chiqish", "#ef4444", hover="#dc2626",
        )
        self.exit_btn.clicked.connect(self.request_exit)
        top_bar.addWidget(self.exit_btn)

        main_layout.addLayout(top_bar)

        # --- Main Content Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.item_browser = ItemBrowser(self.api)
        self.item_browser.item_selected.connect(self.add_item_to_active_cart)
        splitter.addWidget(self.item_browser)

        # ── Sales Tabs ──────────────────
        self.sales_tabs = QTabWidget()
        self.sales_tabs.setTabsClosable(True)
        self.sales_tabs.setMovable(True)
        self.sales_tabs.tabCloseRequested.connect(self.close_sale_tab)
        self.sales_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: #ffffff;
                border-radius: 12px;
                margin-top: -1px;
            }

            QTabBar::tab {
                background: #f1f5f9;
                color: #64748b;
                padding: 11px 22px;
                font-weight: 600;
                font-size: 13px;
                border-radius: 10px 10px 0 0;
                margin-right: 4px;
                border: 1px solid #e2e8f0;
                border-bottom: none;
                min-width: 95px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #1d4ed8;
                border-color: #bfdbfe;
                border-bottom: 3px solid #3b82f6;
                font-weight: 700;
            }
            QTabBar::tab:hover:!selected {
                background: #e8f0fe;
                color: #1d4ed8;
            }
        """)


        splitter.addWidget(self.sales_tabs)

        splitter.setSizes([600, 500])

        main_layout.addWidget(splitter, stretch=1)

        # ── Inline History Panel (hidden by default) ──
        self.history_panel = HistoryWindow(self.api, self)
        self.history_panel.setVisible(False)
        self.history_panel.setMinimumHeight(360)
        self.history_panel.setMaximumHeight(500)
        self.history_panel.setStyleSheet("""
            background: white;
            border-top: 2px solid #e2e8f0;
        """)
        main_layout.addWidget(self.history_panel)

        # ── Inline Shifts Panel (hidden by default) ──
        self.shifts_panel = PosShiftsWindow(self.api, self)
        self.shifts_panel.setVisible(False)
        self.shifts_panel.setMinimumHeight(300)
        self.shifts_panel.setMaximumHeight(450)
        self.shifts_panel.setStyleSheet("""
            background: white;
            border-top: 2px solid #e2e8f0;
        """)
        main_layout.addWidget(self.shifts_panel)

        # Footer
        self.status_label = QLabel("Tayyor.")
        self.statusBar().addWidget(self.status_label)

        # Initial Sale Tab
        self.add_new_sale_tab()


        # Workers - Shared API beriladi
        self.sync_worker = SyncWorker(self.api)
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self._auto_sync = True  # birinchi sinxronizatsiya dialog ko'rsatmasin
        self.sync_worker.start()  # Login dan keyin avtomatik sinxronizatsiya

        self.offline_sync_worker = OfflineSyncWorker(self.api)
        self.offline_sync_worker.sync_status.connect(self.update_status)
        self.offline_sync_worker.start()

        # Monitor timer
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.monitor_system)
        self.monitor_timer.start(MONITOR_INTERVAL_MS)
        self.monitor_system()

        # POS Opening check — kassa ochiqligini tekshirish
        self._check_pos_opening()

    def request_exit(self):
        dlg = ConfirmDialog(
            self, "Chiqish", "Dasturdan chiqishni xohlaysizmi?",
            icon="🚪", yes_text="Chiqish", yes_color="#ef4444",
        )
        dlg.exec()
        if dlg.result_accepted:
            self.close()

    def request_logout(self):
        dlg = ConfirmDialog(
            self, "Tizimdan chiqish",
            "Tizimdan chiqishni xohlaysizmi?\nBarcha hisob ma'lumotlari tozalanadi.",
            icon="🔓", yes_text="Chiqish", yes_color="#f59e0b",
        )
        dlg.exec()
        if dlg.result_accepted:
            self.logout_requested.emit()

    def _update_company_badge(self, company: str = "", pos_profile: str = ""):
        display = company or pos_profile or "—"
        self.company_badge.setText(f"🏢  {display}")
        self.company_badge.setStyleSheet("""
            font-size: 12px; font-weight: 700; color: #1e40af;
            background: #eff6ff; border: 1.5px solid #bfdbfe;
            border-radius: 8px; padding: 4px 12px;
        """)

    def monitor_system(self):
        self._check_server_status()
        self._update_offline_queue_count()

    def _check_server_status(self):
        # Background thread'da tekshirish — GUI muzlamasligi uchun
        if hasattr(self, '_connectivity_worker') and self._connectivity_worker.isRunning():
            return  # oldingi tekshiruv hali tugamagan
        self._connectivity_worker = ConnectivityCheckWorker(self.api)
        self._connectivity_worker.finished.connect(self._update_connectivity_ui)
        self._connectivity_worker.start()

    def _update_connectivity_ui(self, is_online: bool):
        if is_online:
            self.status_dot.setStyleSheet("background-color: #10b981; border-radius: 6px;")
            self.status_text.setText("ONLINE")
            self.status_text.setStyleSheet("font-weight: bold; color: #10b981; font-size: 13px;")
        else:
            self.status_dot.setStyleSheet("background-color: #ef4444; border-radius: 6px;")
            self.status_text.setText("OFFLINE")
            self.status_text.setStyleSheet("font-weight: bold; color: #ef4444; font-size: 13px;")

    def _update_offline_queue_count(self):
        try:
            db.connect(reuse_if_open=True)
            count = PendingInvoice.select().where(PendingInvoice.status == "Pending").count()
            self.offline_btn.setText(f"Offline: {count}")

            if count > 0:
                self.offline_btn.setStyleSheet("""
                    QPushButton { padding: 12px 20px; background-color: #fff7ed; color: #ea580c;
                    font-weight: bold; font-size: 14px; border-radius: 8px; border: 2px solid #f97316; }
                """)
            else:
                self.offline_btn.setStyleSheet("""
                    QPushButton { padding: 12px 20px; background-color: #f3f4f6; color: #374151;
                    font-weight: bold; font-size: 14px; border-radius: 8px; border: 1px solid #d1d5db; }
                """)
        except Exception as e:
            logger.debug("Offline queue count xatosi: %s", e)
        finally:
            if not db.is_closed():
                db.close()

    def show_offline_queue(self):
        dialog = OfflineQueueWindow(self)
        dialog.exec()
        self._update_offline_queue_count()

    def add_new_sale_tab(self):
        tab_count = self.sales_tabs.count()
        new_cart = CartWidget()
        new_cart.checkout_requested.connect(self.on_checkout)
        tab_index = self.sales_tabs.addTab(new_cart, f"Sotuv {tab_count + 1}")
        self.sales_tabs.setCurrentIndex(tab_index)

    def close_sale_tab(self, index: int):
        if self.sales_tabs.count() > 1:
            cart = self.sales_tabs.widget(index)
            if cart and cart.items:
                dlg = ConfirmDialog(
                    self, "Vkladkani yopish",
                    "Savatda tovarlar bor. Baribir yopmoqchimisiz?",
                    icon="⚠️", yes_text="Ha, yopish", yes_color="#ef4444",
                )
                dlg.exec()
                if not dlg.result_accepted:
                    return
            self.sales_tabs.removeTab(index)
        else:
            InfoDialog(self, "Diqqat", "Kamida bitta sotuv oynasi ochiq bo'lishi kerak.", kind="warning").exec()

    def add_item_to_active_cart(self, item_code: str, item_name: str, price: float, currency: str):
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.add_item(item_code, item_name, price, currency)

    def on_checkout(self, order_data: dict):
        # CheckoutWindow ham shared API ishlatadi
        dialog = CheckoutWindow(self, order_data, self.api)
        dialog.checkout_completed.connect(self.on_checkout_completed)
        dialog.exec()

    def on_checkout_completed(self):
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.clear_cart()
        self._update_offline_queue_count()

    def show_printer_settings(self):
        from ui.components.printer_settings import PrinterSettingsDialog
        dlg = PrinterSettingsDialog(self, self.api)
        dlg.exec()

    def show_shifts_history(self):
        visible = self.shifts_panel.isVisible()
        if visible:
            self.shifts_panel.setVisible(False)
        else:
            # Tarix panelini yopish (ikkalasi bir vaqtda ochilmasin)
            self.history_panel.setVisible(False)
            self.shifts_panel.setVisible(True)
            self.shifts_panel.load_shifts()

    def show_history(self):
        # Kassa tarixi panelini yopish
        self.shifts_panel.setVisible(False)
        visible = self.history_panel.isVisible()
        if visible:
            self.history_panel.setVisible(False)
            self.history_btn.setStyleSheet(
                "padding: 12px 20px; background-color: #6366f1; color: white; "
                "font-weight: bold; border-radius: 8px; margin-left: 10px;"
            )
        else:
            self.history_panel.opening_entry = self.opening_entry or ""
            self.history_panel.setVisible(True)
            self.history_panel.load_history()
            self.history_btn.setStyleSheet(
                "padding: 12px 20px; background-color: #4338ca; color: white; "
                "font-weight: bold; border-radius: 8px; margin-left: 10px;"
                "border: 2px solid #818cf8;"
            )

    def start_sync(self):
        self.sync_btn.setEnabled(False)
        self._auto_sync = False  # qo'lda bosdi — dialog ko'rsatilsin
        self.status_label.setText("Sinxronizatsiya boshlandi...")
        self.sync_worker.start()

    def update_status(self, message: str):
        self.status_label.setText(message)

    def on_sync_finished(self, success: bool, message: str):
        self.sync_btn.setEnabled(True)
        # Filial nomini yangilash
        cfg = load_config()
        self._update_company_badge(cfg.get("company", ""), cfg.get("pos_profile", ""))
        if success:
            self.item_browser.load_items()
        # Avtomatik sinxronizatsiyada dialog ko'rsatmaymiz
        if self._auto_sync:
            self._auto_sync = False
            if not success:
                self.status_label.setText(f"Sinxronizatsiya xatosi: {message}")
            else:
                self.status_label.setText("Sinxronizatsiya muvaffaqiyatli!")
        else:
            if success:
                InfoDialog(self, "Muvaffaqiyatli", message, kind="success").exec()
            else:
                InfoDialog(self, "Xatolik", message, kind="error").exec()

    # ── POS Opening / Closing ──────────────────────────────
    def _check_pos_opening(self):
        """Login dan keyin kassa ochiqligini tekshirish."""
        self._set_pos_enabled(False)
        self.opening_check_worker = PosOpeningCheckWorker(self.api)
        self.opening_check_worker.finished.connect(self._on_opening_check_done)
        self.opening_check_worker.start()

    def _on_opening_check_done(self, has_opening: bool, opening_entry: str):
        if has_opening:
            self.opening_entry = opening_entry
            self._set_pos_enabled(True)
            self.status_label.setText("Kassa ochiq.")
        else:
            self._show_pos_opening_dialog()

    def _show_pos_opening_dialog(self):
        dlg = PosOpeningDialog(self, self.api)
        dlg.opening_completed.connect(self._on_pos_opened)
        dlg.exit_requested.connect(self._on_opening_exit)
        dlg.logout_requested.connect(self._on_opening_logout)
        dlg.exec()

    def _on_opening_exit(self):
        """Kassa ochish dialogidan chiqish — dasturni yopish."""
        self.close()

    def _on_opening_logout(self):
        """Kassa ochish dialogidan logout — boshqa kassir kirishi uchun."""
        self.logout_requested.emit()

    def _on_pos_opened(self, opening_entry: str):
        self.opening_entry = opening_entry
        self._set_pos_enabled(True)
        self.status_label.setText("Kassa ochildi!")

    def show_pos_closing(self):
        if not self.opening_entry:
            InfoDialog(
                self, "Kassa topilmadi",
                "Ochiq kassa topilmadi.",
                kind="warning",
            ).exec()
            return

        dlg = ConfirmDialog(
            self, "Kassani yopish",
            "Kassani yopmoqchimisiz?\nBarcha to'lovlar hisoblanadi.",
            icon="🔒", yes_text="Ha, yopish", yes_color="#dc2626",
        )
        dlg.exec()
        if not dlg.result_accepted:
            return

        closing_dlg = PosClosingDialog(self, self.api, self.opening_entry)
        closing_dlg.closing_completed.connect(self._on_pos_closed)
        closing_dlg.exec()

    def _on_pos_closed(self):
        self.opening_entry = None
        self._set_pos_enabled(False)
        self.status_label.setText("Kassa yopildi.")

        # Muvaffaqiyat xabari
        InfoDialog(
            self, "Kassa yopildi",
            "Kassa muvaffaqiyatli yopildi.\nDavom etish uchun yangi kassa oching.",
            kind="success",
        ).exec()

        # Yangi kassa ochish dialogini ko'rsatish
        self._show_pos_opening_dialog()

    def _set_pos_enabled(self, enabled: bool):
        """Kassa ochiq/yopiq holatiga qarab UI elementlarini boshqarish."""
        self.add_sale_btn.setEnabled(enabled)
        self.close_shift_btn.setEnabled(enabled)
        self.open_shift_btn.setVisible(not enabled)
        if hasattr(self, 'item_browser'):
            self.item_browser.setEnabled(enabled)
        if hasattr(self, 'sales_tabs'):
            self.sales_tabs.setEnabled(enabled)

    def closeEvent(self, event):
        self.monitor_timer.stop()
        self.offline_sync_worker.stop()
        self.offline_sync_worker.wait(2000)  # max 2 sek kutish
        super().closeEvent(event)
