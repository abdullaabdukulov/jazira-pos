from PyQt6.QtWidgets import (QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget, 
                             QPushButton, QMessageBox, QSplitter, QTabWidget, QTabBar)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut, QKeySequence
from database.sync import SyncWorker
from database.offline_sync import OfflineSyncWorker
from database.models import initialize_db, Item, db

from ui.components.item_browser import ItemBrowser
from ui.components.cart_widget import CartWidget
from ui.components.checkout_window import CheckoutWindow
from ui.components.history_window import HistoryWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jazira POS")
        self.showMaximized()

        # Initialize SQLite
        initialize_db()

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top Bar ---
        top_bar = QHBoxLayout()
        self.title_label = QLabel("Jazira POS")
        self.title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        top_bar.addWidget(self.title_label)

        top_bar.addStretch()

        # Add New Sale Button
        self.add_sale_btn = QPushButton("+ Yangi Sotuv")
        self.add_sale_btn.setStyleSheet("""
            QPushButton { padding: 10px 20px; background-color: #10b981; color: white; font-weight: bold; font-size: 14px; border-radius: 6px; }
            QPushButton:hover { background-color: #059669; }
        """)
        self.add_sale_btn.clicked.connect(self.add_new_sale_tab)
        top_bar.addWidget(self.add_sale_btn)

        # History Button
        self.history_btn = QPushButton("⏱️ Tarix")
        self.history_btn.setStyleSheet("padding: 10px 20px; background-color: #6366f1; color: white; font-weight: bold; border-radius: 6px; margin-left: 10px;")
        self.history_btn.clicked.connect(self.show_history)
        top_bar.addWidget(self.history_btn)

        # Sync Button
        self.sync_btn = QPushButton("🔄 Sinxronizatsiya")
        self.sync_btn.setStyleSheet("padding: 10px 20px; background-color: #2196F3; color: white; font-weight: bold; border-radius: 6px; margin-left: 10px;")
        self.sync_btn.clicked.connect(self.start_sync)
        top_bar.addWidget(self.sync_btn)

        # Exit Button
        self.exit_btn = QPushButton("Chiqish")
        self.exit_btn.setStyleSheet("padding: 10px 20px; background-color: #f44336; color: white; font-weight: bold; border-radius: 6px; margin-left: 10px;")
        self.exit_btn.clicked.connect(self.close)
        top_bar.addWidget(self.exit_btn)

        main_layout.addLayout(top_bar)

        # --- Main Content Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Item Browser
        self.item_browser = ItemBrowser()
        self.item_browser.item_selected.connect(self.add_item_to_active_cart)
        splitter.addWidget(self.item_browser)

        # Right: Sales Tab Widget
        self.sales_tabs = QTabWidget()
        self.sales_tabs.setTabsClosable(True)
        self.sales_tabs.setMovable(True)
        self.sales_tabs.tabCloseRequested.connect(self.close_sale_tab)
        self.sales_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #d1d5db; background: white; border-radius: 8px; }
            QTabBar::tab { 
                background: #f3f4f6; padding: 12px 25px; font-weight: bold; font-size: 14px;
                border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px;
            }
            QTabBar::tab:selected { background: white; border: 1px solid #d1d5db; border-bottom: none; color: #3b82f6; }
        """)
        splitter.addWidget(self.sales_tabs)
        
        splitter.setSizes([600, 500])
        main_layout.addWidget(splitter, stretch=1)

        # Footer Status
        self.status_label = QLabel("Tayyor.")
        self.statusBar().addWidget(self.status_label)

        # Initial Sale Tab
        self.add_new_sale_tab()

        # Workers
        self.sync_worker = SyncWorker()
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)

        self.offline_sync_worker = OfflineSyncWorker()
        self.offline_sync_worker.sync_status.connect(self.update_status)
        self.offline_sync_worker.start()

    def add_new_sale_tab(self):
        tab_count = self.sales_tabs.count()
        new_cart = CartWidget()
        new_cart.checkout_requested.connect(self.on_checkout)
        
        tab_index = self.sales_tabs.addTab(new_cart, f"Sotuv {tab_count + 1}")
        self.sales_tabs.setCurrentIndex(tab_index)

    def close_sale_tab(self, index):
        if self.sales_tabs.count() > 1:
            # Check if cart is empty before closing
            cart = self.sales_tabs.widget(index)
            if cart and cart.items:
                res = QMessageBox.question(self, "Vkladkani yopish", 
                                         "Savatda tovarlar bor. Baribir yopmoqchimisiz?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if res == QMessageBox.StandardButton.No:
                    return
            self.sales_tabs.removeTab(index)
        else:
            QMessageBox.warning(self, "Diqqat", "Kamida bitta sotuv oynasi ochiq bo'lishi kerak.")

    def add_item_to_active_cart(self, item_code, item_name, price, currency):
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.add_item(item_code, item_name, price, currency)

    def on_checkout(self, order_data):
        dialog = CheckoutWindow(self, order_data)
        dialog.checkout_completed.connect(self.on_checkout_completed)
        dialog.exec()

    def on_checkout_completed(self):
        # Clear the current active cart and keep tab open for next customer
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.clear_cart()

    def show_history(self):
        HistoryWindow(self).exec()

    def start_sync(self):
        self.sync_btn.setEnabled(False)
        self.sync_worker.start()

    def update_status(self, message):
        self.status_label.setText(message)

    def on_sync_finished(self, success, message):
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
