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
from ui.scale import s, font

logger = get_logger(__name__)


class ConnectivityCheckWorker(QThread):
    """Server bilan aloqani tekshirish — background thread'da."""
    result_ready = pyqtSignal(bool)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        try:
            success, _ = self.api.call_method("frappe.auth.get_logged_user")
            self.result_ready.emit(success)
        except Exception:
            self.result_ready.emit(False)


class PosOpeningCheckWorker(QThread):
    """Serverdan ochiq kassa borligini tekshirish.

    Mantiq:
    1. Server bilan aloqa bor → server javobiga ishonish (lokal bazani sinxronlash)
    2. Server bilan aloqa yo'q → faqat shu holda lokal bazaga qarash
    """
    result_ready = pyqtSignal(bool, str)  # has_opening, opening_entry_name

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        try:
            success, response = self.api.call_method("ury.ury_pos.api.checkPosOpening")

            if success and isinstance(response, dict):
                status = response.get("status")
                if status == "open":
                    opening_entry = response.get("opening_entry", "")
                    self._sync_local_shift(opening_entry)
                    self.result_ready.emit(True, opening_entry)
                else:
                    self._close_local_shifts()
                    self.result_ready.emit(False, "")
            else:
                try:
                    shift = PosShift.select().where(PosShift.status == "Open").first()
                    if shift:
                        self.result_ready.emit(True, shift.opening_entry or "")
                    else:
                        self.result_ready.emit(False, "")
                except Exception:
                    self.result_ready.emit(False, "")
        finally:
            if not db.is_closed():
                db.close()

    def _sync_local_shift(self, opening_entry: str):
        try:
            existing = PosShift.select().where(
                (PosShift.status == "Open") & (PosShift.opening_entry == opening_entry)
            ).first()
            if not existing:
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

    def _close_local_shifts(self):
        try:
            import datetime
            PosShift.update(
                status="Closed", closed_at=datetime.datetime.now()
            ).where(PosShift.status == "Open").execute()
        except Exception as e:
            logger.debug("Lokal shiftlarni yopish: %s", e)


class MainWindow(QMainWindow):
    logout_requested = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.opening_entry = None
        self.setWindowTitle("Jazira POS")

        initialize_db()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Bar ---
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(s(10), s(4), s(10), s(4))
        top_bar.setSpacing(s(12))

        # ── Jazira Brand Logo ──────────────────
        logo_widget = QWidget()
        logo_widget.setFixedWidth(s(200))
        logo_widget.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border-left: {s(4)}px solid #f59e0b;
                padding-left: {s(10)}px;
            }}
        """)
        logo_layout = QVBoxLayout(logo_widget)
        logo_layout.setContentsMargins(s(10), s(2), 0, s(2))
        logo_layout.setSpacing(0)

        brand_name = QLabel("Jazira°")
        brand_name.setStyleSheet(f"""
            font-size: {font(26)}px;
            font-weight: 900;
            font-style: italic;
            color: #d97706;
            background: transparent;
        """)

        brand_sub = QLabel("DONER & SHAWERMA")
        brand_sub.setStyleSheet(f"""
            font-size: {font(8)}px;
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
        _dot = s(12)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(_dot, _dot)
        self.status_dot.setStyleSheet(f"background-color: #94a3b8; border-radius: {_dot // 2}px;")

        self.status_text = QLabel("Checking...")
        self.status_text.setStyleSheet(f"font-weight: bold; color: #64748b; font-size: {font(13)}px;")

        top_bar.addWidget(self.status_dot)
        top_bar.addWidget(self.status_text)
        top_bar.addStretch()

        # ── helper for consistent top-bar button style ──────────
        def _tb_btn(label: str, bg: str, color: str = "white",
                    hover: str = "", border: str = "none") -> QPushButton:
            b = QPushButton(label)
            b.setFixedHeight(s(48))
            h = hover or bg
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {bg}; color: {color};
                    font-weight: 700; font-size: {font(13)}px;
                    border-radius: {s(10)}px; border: {border};
                    padding: 0 {s(16)}px;
                }}
                QPushButton:hover {{ background: {h}; }}
                QPushButton:pressed {{ opacity: 0.85; }}
                QPushButton:disabled {{ background: #f1f5f9; color: #94a3b8; }}
            """)
            return b

        # Offline Queue Button
        self.offline_btn = _tb_btn(
            "Offline: 0", "#f1f5f9", "#374151",
            hover="#e2e8f0", border="1px solid #e2e8f0",
        )
        self.offline_btn.clicked.connect(self.show_offline_queue)
        top_bar.addWidget(self.offline_btn)

        # New Sale Button
        self.add_sale_btn = _tb_btn(
            "+  Yangi sotuv", "#22c55e", hover="#16a34a",
        )
        self.add_sale_btn.clicked.connect(self.add_new_sale_tab)
        top_bar.addWidget(self.add_sale_btn)

        # History Button
        self.history_btn = _tb_btn(
            "Tarix", "#6366f1", hover="#4338ca",
        )
        self.history_btn.clicked.connect(self.show_history)
        top_bar.addWidget(self.history_btn)

        # Sync Button
        self.sync_btn = _tb_btn(
            "Sinxronlash", "#3b82f6", hover="#2563eb",
        )
        self.sync_btn.clicked.connect(self.start_sync)
        top_bar.addWidget(self.sync_btn)

        # Kassa tarixi Button
        self.shifts_btn = _tb_btn(
            "Kassa tarixi", "#475569", hover="#334155",
        )
        self.shifts_btn.clicked.connect(self.show_shifts_history)
        top_bar.addWidget(self.shifts_btn)

        # Kassa ochish Button
        self.open_shift_btn = _tb_btn(
            "Kassa ochish", "#16a34a", hover="#15803d",
        )
        self.open_shift_btn.clicked.connect(self._show_pos_opening_dialog)
        self.open_shift_btn.setVisible(False)
        top_bar.addWidget(self.open_shift_btn)

        # Kassa yopish Button
        self.close_shift_btn = _tb_btn(
            "Kassa yopish", "#dc2626", hover="#b91c1c",
        )
        self.close_shift_btn.clicked.connect(self.show_pos_closing)
        top_bar.addWidget(self.close_shift_btn)

        # Logout Button
        self.logout_btn = _tb_btn(
            "Chiqish", "#f59e0b", hover="#d97706",
        )
        self.logout_btn.clicked.connect(self.request_logout)
        top_bar.addWidget(self.logout_btn)

        # Exit Button
        self.exit_btn = _tb_btn(
            "Dasturdan chiqish", "#ef4444", hover="#dc2626",
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
        self.sales_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: #ffffff;
                border-radius: {s(12)}px;
                margin-top: -1px;
            }}

            QTabBar::tab {{
                background: #f1f5f9;
                color: #64748b;
                padding: {s(11)}px {s(22)}px;
                font-weight: 600;
                font-size: {font(13)}px;
                border-radius: {s(10)}px {s(10)}px 0 0;
                margin-right: {s(4)}px;
                border: 1px solid #e2e8f0;
                border-bottom: none;
                min-width: {s(95)}px;
            }}
            QTabBar::tab:selected {{
                background: #ffffff;
                color: #1d4ed8;
                border-color: #bfdbfe;
                border-bottom: 3px solid #3b82f6;
                font-weight: 700;
            }}
            QTabBar::tab:hover:!selected {{
                background: #e8f0fe;
                color: #1d4ed8;
            }}
        """)

        splitter.addWidget(self.sales_tabs)
        splitter.setSizes([s(600), s(500)])

        main_layout.addWidget(splitter, stretch=1)

        # ── Inline History Panel (hidden by default) ──
        self.history_panel = HistoryWindow(self.api, self)
        self.history_panel.setVisible(False)
        self.history_panel.setMinimumHeight(s(360))
        self.history_panel.setMaximumHeight(s(500))
        self.history_panel.setStyleSheet("""
            background: white;
            border-top: 2px solid #e2e8f0;
        """)
        main_layout.addWidget(self.history_panel)

        # ── Inline Shifts Panel (hidden by default) ──
        self.shifts_panel = PosShiftsWindow(self.api, self)
        self.shifts_panel.setVisible(False)
        self.shifts_panel.setMinimumHeight(s(300))
        self.shifts_panel.setMaximumHeight(s(450))
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

        # Workers — kechiktirilgan ishga tushirish (GUI to'liq tayyor bo'lishi uchun)
        QTimer.singleShot(500, self._start_background_workers)

    def _start_background_workers(self):
        self.sync_worker = SyncWorker(self.api)
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self._auto_sync = True
        self.sync_worker.start()

        self.offline_sync_worker = OfflineSyncWorker(self.api)
        self.offline_sync_worker.sync_status.connect(self.update_status)
        self.offline_sync_worker.start()

        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.monitor_system)
        self.monitor_timer.start(MONITOR_INTERVAL_MS)

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
        self.company_badge.setText(display)
        self.company_badge.setStyleSheet(f"""
            font-size: {font(12)}px; font-weight: 700; color: #1e40af;
            background: #eff6ff; border: 1.5px solid #bfdbfe;
            border-radius: {s(8)}px; padding: {s(4)}px {s(12)}px;
        """)

    def monitor_system(self):
        self._check_server_status()
        self._update_offline_queue_count()

    def _check_server_status(self):
        if hasattr(self, '_connectivity_worker') and self._connectivity_worker.isRunning():
            return
        self._connectivity_worker = ConnectivityCheckWorker(self.api)
        self._connectivity_worker.result_ready.connect(self._update_connectivity_ui)
        self._connectivity_worker.start()

    def _update_connectivity_ui(self, is_online: bool):
        _dot = s(12)
        if is_online:
            self.status_dot.setStyleSheet(f"background-color: #10b981; border-radius: {_dot // 2}px;")
            self.status_text.setText("ONLINE")
            self.status_text.setStyleSheet(f"font-weight: bold; color: #10b981; font-size: {font(13)}px;")
        else:
            self.status_dot.setStyleSheet(f"background-color: #ef4444; border-radius: {_dot // 2}px;")
            self.status_text.setText("OFFLINE")
            self.status_text.setStyleSheet(f"font-weight: bold; color: #ef4444; font-size: {font(13)}px;")

    def _update_offline_queue_count(self):
        try:
            count = PendingInvoice.select().where(PendingInvoice.status == "Pending").count()
            self.offline_btn.setText(f"Offline: {count}")

            if count > 0:
                self.offline_btn.setStyleSheet(f"""
                    QPushButton {{ padding: {s(12)}px {s(20)}px; background-color: #fff7ed; color: #ea580c;
                    font-weight: bold; font-size: {font(14)}px; border-radius: {s(8)}px; border: 2px solid #f97316; }}
                """)
            else:
                self.offline_btn.setStyleSheet(f"""
                    QPushButton {{ padding: {s(12)}px {s(20)}px; background-color: #f3f4f6; color: #374151;
                    font-weight: bold; font-size: {font(14)}px; border-radius: {s(8)}px; border: 1px solid #d1d5db; }}
                """)
        except Exception as e:
            logger.debug("Offline queue count xatosi: %s", e)

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
        dialog = CheckoutWindow(self, order_data, self.api)
        dialog.checkout_completed.connect(self.on_checkout_completed)
        dialog.exec()

    def on_checkout_completed(self):
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.clear_cart()
        self._update_offline_queue_count()

    def show_shifts_history(self):
        visible = self.shifts_panel.isVisible()
        if visible:
            self.shifts_panel.setVisible(False)
        else:
            self.history_panel.setVisible(False)
            self.shifts_panel.setVisible(True)
            self.shifts_panel.load_shifts()

    def show_history(self):
        self.shifts_panel.setVisible(False)
        visible = self.history_panel.isVisible()
        if visible:
            self.history_panel.setVisible(False)
            self.history_btn.setStyleSheet(f"""
                padding: {s(12)}px {s(20)}px; background-color: #6366f1; color: white;
                font-weight: bold; border-radius: {s(8)}px; margin-left: {s(10)}px;
            """)
        else:
            self.history_panel.opening_entry = self.opening_entry or ""
            self.history_panel.setVisible(True)
            self.history_panel.load_history()
            self.history_btn.setStyleSheet(f"""
                padding: {s(12)}px {s(20)}px; background-color: #4338ca; color: white;
                font-weight: bold; border-radius: {s(8)}px; margin-left: {s(10)}px;
                border: 2px solid #818cf8;
            """)

    def start_sync(self):
        if hasattr(self, 'sync_worker') and self.sync_worker.isRunning():
            self.status_label.setText("Sinxronizatsiya hali davom etmoqda...")
            return
        self.sync_btn.setEnabled(False)
        self._auto_sync = False
        self.status_label.setText("Sinxronizatsiya boshlandi...")
        # QThread qayta ishlatilmaydi — yangi instance yaratamiz
        self.sync_worker = SyncWorker(self.api)
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self.sync_worker.start()

    def update_status(self, message: str):
        self.status_label.setText(message)

    def on_sync_finished(self, success: bool, message: str):
        self.sync_btn.setEnabled(True)
        cfg = load_config()
        self._update_company_badge(cfg.get("company", ""), cfg.get("pos_profile", ""))
        if success:
            self.item_browser.load_items()
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
        self._set_pos_enabled(False)
        self.opening_check_worker = PosOpeningCheckWorker(self.api)
        self.opening_check_worker.result_ready.connect(self._on_opening_check_done)
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
        self.close()

    def _on_opening_logout(self):
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

        InfoDialog(
            self, "Kassa yopildi",
            "Kassa muvaffaqiyatli yopildi.\nDavom etish uchun yangi kassa oching.",
            kind="success",
        ).exec()

        self._show_pos_opening_dialog()

    def _set_pos_enabled(self, enabled: bool):
        self.add_sale_btn.setEnabled(enabled)
        self.close_shift_btn.setEnabled(enabled)
        self.open_shift_btn.setVisible(not enabled)
        if hasattr(self, 'item_browser'):
            self.item_browser.setEnabled(enabled)
        if hasattr(self, 'sales_tabs'):
            self.sales_tabs.setEnabled(enabled)

    def closeEvent(self, event):
        if hasattr(self, 'monitor_timer'):
            self.monitor_timer.stop()
        if hasattr(self, 'offline_sync_worker'):
            self.offline_sync_worker.stop()
            self.offline_sync_worker.wait(3000)
        if hasattr(self, 'sync_worker') and self.sync_worker.isRunning():
            self.sync_worker.quit()
            self.sync_worker.wait(3000)
        if hasattr(self, '_connectivity_worker') and self._connectivity_worker.isRunning():
            self._connectivity_worker.quit()
            self._connectivity_worker.wait(2000)
        if hasattr(self, 'opening_check_worker') and self.opening_check_worker.isRunning():
            self.opening_check_worker.quit()
            self.opening_check_worker.wait(2000)
        # DB ni yopish — ilova hayoti tugadi
        if not db.is_closed():
            db.close()
        super().closeEvent(event)
