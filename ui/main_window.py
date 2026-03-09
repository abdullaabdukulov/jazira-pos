from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QMessageBox, QSplitter, QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from database.sync import SyncWorker
from database.offline_sync import OfflineSyncWorker
from database.migrations import initialize_db
from database.models import PendingInvoice, db
from core.api import FrappeAPI
from core.logger import get_logger
from core.constants import MONITOR_INTERVAL_MS
from ui.components.item_browser import ItemBrowser
from ui.components.cart_widget import CartWidget
from ui.components.checkout_window import CheckoutWindow
from ui.components.history_window import HistoryWindow
from ui.components.offline_queue_window import OfflineQueueWindow

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    logout_requested = pyqtSignal()

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api
        self.setWindowTitle("Jazira POS")
        self.showMaximized()

        initialize_db()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Bar ---
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(10, 5, 10, 5)

        self.title_label = QLabel("Jazira POS")
        self.title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #1e293b;")
        top_bar.addWidget(self.title_label)
        top_bar.addSpacing(20)

        # Connection Status
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet("background-color: #94a3b8; border-radius: 6px;")

        self.status_text = QLabel("Checking...")
        self.status_text.setStyleSheet("font-weight: bold; color: #64748b; font-size: 13px;")

        top_bar.addWidget(self.status_dot)
        top_bar.addWidget(self.status_text)
        top_bar.addStretch()

        # Offline Queue Button
        self.offline_btn = QPushButton("Offline: 0")
        self.offline_btn.setStyleSheet("""
            QPushButton {
                padding: 12px 20px; background-color: #f3f4f6; color: #374151;
                font-weight: bold; font-size: 14px; border-radius: 8px; border: 1px solid #d1d5db;
            }
            QPushButton:hover { background-color: #e5e7eb; }
        """)
        self.offline_btn.clicked.connect(self.show_offline_queue)
        top_bar.addWidget(self.offline_btn)

        # New Sale Button
        self.add_sale_btn = QPushButton("+ Yangi Sotuv")
        self.add_sale_btn.setStyleSheet("""
            QPushButton { padding: 12px 20px; background-color: #10b981; color: white;
            font-weight: bold; font-size: 14px; border-radius: 8px; margin-left: 10px; }
            QPushButton:hover { background-color: #059669; }
        """)
        self.add_sale_btn.clicked.connect(self.add_new_sale_tab)
        top_bar.addWidget(self.add_sale_btn)

        # History Button
        self.history_btn = QPushButton("Tarix")
        self.history_btn.setStyleSheet(
            "padding: 12px 20px; background-color: #6366f1; color: white; "
            "font-weight: bold; border-radius: 8px; margin-left: 10px;"
        )
        self.history_btn.clicked.connect(self.show_history)
        top_bar.addWidget(self.history_btn)

        # Sync Button
        self.sync_btn = QPushButton("Sinxronizatsiya")
        self.sync_btn.setStyleSheet(
            "padding: 12px 20px; background-color: #2196F3; color: white; "
            "font-weight: bold; border-radius: 8px; margin-left: 10px;"
        )
        self.sync_btn.clicked.connect(self.start_sync)
        top_bar.addWidget(self.sync_btn)

        # Logout Button
        self.logout_btn = QPushButton("Tizimdan chiqish")
        self.logout_btn.setStyleSheet(
            "padding: 12px 20px; background-color: #f59e0b; color: white; "
            "font-weight: bold; border-radius: 8px; margin-left: 10px;"
        )
        self.logout_btn.clicked.connect(self.request_logout)
        top_bar.addWidget(self.logout_btn)

        # Exit Button
        self.exit_btn = QPushButton("Chiqish")
        self.exit_btn.setStyleSheet(
            "padding: 12px 20px; background-color: #ef4444; color: white; "
            "font-weight: bold; border-radius: 8px; margin-left: 10px;"
        )
        self.exit_btn.clicked.connect(self.request_exit)
        top_bar.addWidget(self.exit_btn)

        main_layout.addLayout(top_bar)

        # --- Main Content Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.item_browser = ItemBrowser(self.api)
        self.item_browser.item_selected.connect(self.add_item_to_active_cart)
        splitter.addWidget(self.item_browser)

        self.sales_tabs = QTabWidget()
        self.sales_tabs.setTabsClosable(True)
        self.sales_tabs.setMovable(True)
        self.sales_tabs.tabCloseRequested.connect(self.close_sale_tab)
        self.sales_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #d1d5db; background: white; border-radius: 8px; }
            QTabBar::tab {
                background: #f3f4f6; padding: 15px 30px; font-weight: bold; font-size: 14px;
                border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px;
            }
            QTabBar::tab:selected { background: white; border: 1px solid #d1d5db; border-bottom: none; color: #3b82f6; }
        """)
        splitter.addWidget(self.sales_tabs)

        splitter.setSizes([600, 500])
        main_layout.addWidget(splitter, stretch=1)

        # Footer
        self.status_label = QLabel("Tayyor.")
        self.statusBar().addWidget(self.status_label)

        # Initial Sale Tab
        self.add_new_sale_tab()

        # Workers - Shared API beriladi
        self.sync_worker = SyncWorker(self.api)
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)

        self.offline_sync_worker = OfflineSyncWorker(self.api)
        self.offline_sync_worker.sync_status.connect(self.update_status)
        self.offline_sync_worker.start()

        # Monitor timer
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.monitor_system)
        self.monitor_timer.start(MONITOR_INTERVAL_MS)
        self.monitor_system()

    def request_exit(self):
        res = QMessageBox.question(
            self, "Chiqish",
            "Dasturdan chiqishni xohlaysizmi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self.close()

    def request_logout(self):
        res = QMessageBox.question(
            self, "Tizimdan chiqish",
            "Tizimdan chiqishni xohlaysizmi?\nBarcha hisob ma'lumotlari tozalanadi.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self.logout_requested.emit()

    def monitor_system(self):
        self._check_server_status()
        self._update_offline_queue_count()

    def _check_server_status(self):
        try:
            # Shared API orqali tekshiriladi
            success, _ = self.api.call_method("frappe.auth.get_logged_user")
            self._update_connectivity_ui(success)
        except Exception:
            self._update_connectivity_ui(False)

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
                res = QMessageBox.question(
                    self, "Vkladkani yopish",
                    "Savatda tovarlar bor. Baribir yopmoqchimisiz?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if res == QMessageBox.StandardButton.No:
                    return
            self.sales_tabs.removeTab(index)
        else:
            QMessageBox.warning(self, "Diqqat", "Kamida bitta sotuv oynasi ochiq bo'lishi kerak.")

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

    def show_history(self):
        HistoryWindow(self).exec()

    def start_sync(self):
        # Connectivity check shared API bilan
        success, _ = self.api.call_method("frappe.auth.get_logged_user")
        if not success:
            QMessageBox.warning(
                self, "Internet yo'q",
                "Hozirda server bilan aloqa mavjud emas.\n"
                "Internet ulangandan so'ng sinxronizatsiya qilishingiz mumkin.",
            )
            return

        self.sync_btn.setEnabled(False)
        self.status_label.setText("Sinxronizatsiya boshlandi...")
        self.sync_worker.start()

    def update_status(self, message: str):
        self.status_label.setText(message)

    def on_sync_finished(self, success: bool, message: str):
        self.sync_btn.setEnabled(True)
        if success:
            self.item_browser.load_items()
            QMessageBox.information(self, "Muvaffaqiyatli", message)
        else:
            QMessageBox.critical(self, "Xatolik", message)

    def closeEvent(self, event):
        self.offline_sync_worker.stop()
        self.offline_sync_worker.wait()
        super().closeEvent(event)
