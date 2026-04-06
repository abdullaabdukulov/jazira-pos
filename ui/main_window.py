from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QSplitter, QTabWidget, QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
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
from ui.components.pos_opening import PosOpeningPage
from ui.components.pos_closing import PosClosingDialog
from ui.components.pos_shifts_window import PosShiftsWindow
from ui.components.dialogs import InfoDialog, ConfirmDialog
from ui.components.loading import InlineSpinner
from ui.icons import (
    icon_plus, icon_sync, icon_history, icon_clock,
    icon_lock, icon_signal, icon_loading,
    icon_wifi, icon_building, icon_user,
)
from ui.scale import s, font

logger = get_logger(__name__)


class ConnectivityCheckWorker(QThread):
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
    result_ready = pyqtSignal(bool, str)

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


# ── Yagona top-bar tugma stili ──────────────────────
_BTN_STYLE = """
    QPushButton {{
        background: {bg}; color: {fg};
        font-weight: 700; font-size: {fs}px;
        border-radius: {r}px; border: {border};
        padding: 0 {px}px;
    }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:pressed {{ opacity: 0.85; }}
    QPushButton:disabled {{ background: #f1f5f9; color: #94a3b8; border: none; }}
"""


def _tb_btn(label: str, kind: str = "neutral") -> QPushButton:
    """
    kind:
      neutral  — quyuq slate, ko'pgina tugmalar uchun
      primary  — ko'k, asosiy harakat (Yangi sotuv)
      danger   — qizil (Kassa yopish)
      ghost    — oq fon, chegara bilan (Offline counter)
    """
    styles = {
        "neutral": dict(bg="#334155", fg="white", hover="#1e293b", border="none"),
        "primary": dict(bg="#1d4ed8", fg="white", hover="#1e40af", border="none"),
        "danger":  dict(bg="#dc2626", fg="white", hover="#b91c1c", border="none"),
        "ghost":   dict(bg="#f8fafc", fg="#475569", hover="#e2e8f0", border="1px solid #e2e8f0"),
    }
    st = styles.get(kind, styles["neutral"])
    b = QPushButton(label)
    b.setFixedHeight(s(44))
    b.setIconSize(QSize(s(18), s(18)))
    b.setStyleSheet(_BTN_STYLE.format(
        bg=st["bg"], fg=st["fg"], hover=st["hover"], border=st["border"],
        fs=font(13), r=s(10), px=s(16),
    ))
    return b


class MainWindow(QMainWindow):

    def __init__(self, api: FrappeAPI, active_cashier: dict = None):
        super().__init__()
        self.api = api
        self.opening_entry = None
        self.active_cashier = active_cashier   # {"name": ..., "full_name": ..., "pin_hash": ...}
        self.setWindowTitle("Jazira POS")

        initialize_db()

        # ── QStackedWidget: 0=ochish sahifasi, 1=asosiy kontent ──
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Sahifa 0 — Kassa ochish (to'liq oyna)
        self._pos_opening_page = PosOpeningPage(self.api)
        self._pos_opening_page.opening_completed.connect(self._on_pos_opened)
        self._pos_opening_page.exit_requested.connect(self.close)
        self._stack.addWidget(self._pos_opening_page)

        # Sahifa 1 — Asosiy kontent
        main_page = self._build_main_page()
        self._stack.addWidget(main_page)

        # ── Lokal DB dan tezkor tekshirish (synchronous, flash yo'q) ──
        # Agar kassa local DB da ochiq bo'lsa — bevosita asosiy sahifaga o'tamiz
        # Keyin network check ham ishlaydi (tasdiqlash/yangilash uchun)
        try:
            from database.models import PosShift
            local_shift = PosShift.select().where(PosShift.status == "Open").first()
            if local_shift:
                self.opening_entry = local_shift.opening_entry or ""
                self._stack.setCurrentIndex(1)   # Asosiy kontent — flash yo'q
                self._set_pos_enabled(True)
                self.status_label.setText("Kassa ochiq (server tekshirilmoqda...)")
            else:
                self._stack.setCurrentIndex(0)   # Kassa ochish sahifasi
        except Exception as e:
            logger.warning("Local DB kassa tekshiruvi xatosi: %s", e)
            self._stack.setCurrentIndex(0)

        # Startup da mavjud config dan sozlamalarni qo'llash
        self._apply_pos_settings()

        # Badge ni yangilash (active_cashier mavjud bo'lsa uning full_name chiqadi)
        self._update_cashier_badge()

        # Background workers — darhol (kechiktirmasdan)
        QTimer.singleShot(0, self._start_background_workers)

    # ── Asosiy kontent sahifasini qurish ─────────────
    def _build_main_page(self) -> QWidget:
        page = QWidget()
        main_layout = QVBoxLayout(page)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─ Top Bar ─────────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(s(10), s(4), s(10), s(4))
        top_bar.setSpacing(s(8))

        # Brand logo — clean minimal
        logo_lbl = QLabel("Jazira POS")
        logo_lbl.setStyleSheet(f"""
            font-size: {font(20)}px; font-weight: 900;
            color: #d97706; background: transparent;
            padding: 0 {s(8)}px;
        """)
        top_bar.addWidget(logo_lbl)

        # Separator
        sep1 = QLabel("")
        sep1.setFixedSize(s(1), s(28))
        sep1.setStyleSheet("background: #e2e8f0;")
        top_bar.addWidget(sep1)

        config = load_config()
        company_name = config.get("company", "")
        cashier = config.get("cashier", config.get("user", ""))

        # Connection status — icon + text
        self._wifi_icon = QLabel()
        self._wifi_icon.setFixedSize(s(20), s(20))
        self._wifi_icon.setPixmap(icon_wifi("#94a3b8").pixmap(s(18), s(18)))
        top_bar.addWidget(self._wifi_icon)

        self.status_text = QLabel("Tekshirilmoqda")
        self.status_text.setStyleSheet(f"""
            font-weight: 700; color: #94a3b8; font-size: {font(12)}px;
            background: transparent;
        """)
        top_bar.addWidget(self.status_text)

        top_bar.addSpacing(s(12))

        # Company badge — icon + text
        _comp_icon = QLabel()
        _comp_icon.setFixedSize(s(20), s(20))
        _comp_icon.setPixmap(icon_building("#64748b").pixmap(s(18), s(18)))
        top_bar.addWidget(_comp_icon)

        self.company_badge = QLabel(company_name or "—")
        self.company_badge.setStyleSheet(f"""
            font-size: {font(13)}px; font-weight: 700; color: #334155;
            background: transparent;
        """)
        top_bar.addWidget(self.company_badge)

        top_bar.addSpacing(s(12))

        # Cashier badge — icon + text
        _user_icon = QLabel()
        _user_icon.setFixedSize(s(20), s(20))
        _user_icon.setPixmap(icon_user("#0369a1").pixmap(s(18), s(18)))
        top_bar.addWidget(_user_icon)

        self.cashier_badge = QLabel()
        self._update_cashier_badge(cashier)
        top_bar.addWidget(self.cashier_badge)

        top_bar.addStretch()

        # Tashqi tugmalar
        self.offline_btn = _tb_btn("Offline: 0", "ghost")
        self.offline_btn.setIcon(icon_signal("#475569"))
        self.offline_btn.clicked.connect(self.show_offline_queue)
        top_bar.addWidget(self.offline_btn)

        self.add_sale_btn = _tb_btn("Yangi sotuv", "primary")
        self.add_sale_btn.setIcon(icon_plus())
        self.add_sale_btn.clicked.connect(self.add_new_sale_tab)
        top_bar.addWidget(self.add_sale_btn)

        self.history_btn = _tb_btn("Tarix", "neutral")
        self.history_btn.setIcon(icon_history())
        self.history_btn.clicked.connect(self.show_history)
        top_bar.addWidget(self.history_btn)

        self.sync_btn = _tb_btn("Sinxronlash", "neutral")
        self.sync_btn.setIcon(icon_sync())
        self.sync_btn.clicked.connect(self.start_sync)
        top_bar.addWidget(self.sync_btn)

        self.shifts_btn = _tb_btn("Kassa tarixi", "neutral")
        self.shifts_btn.setIcon(icon_clock())
        self.shifts_btn.clicked.connect(self.show_shifts_history)
        top_bar.addWidget(self.shifts_btn)

        self.close_shift_btn = _tb_btn("Kassa yopish", "danger")
        self.close_shift_btn.setIcon(icon_lock())
        self.close_shift_btn.clicked.connect(self.show_pos_closing)
        top_bar.addWidget(self.close_shift_btn)

        top_bar_widget = QWidget()
        top_bar_widget.setStyleSheet("background: white; border-bottom: 1px solid #e2e8f0;")
        top_bar_widget.setLayout(top_bar)
        main_layout.addWidget(top_bar_widget)

        # ─ Main Content Splitter ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.item_browser = ItemBrowser(self.api)
        self.item_browser.item_selected.connect(self.add_item_to_active_cart)
        splitter.addWidget(self.item_browser)

        # Sales tabs
        self.sales_tabs = QTabWidget()
        self.sales_tabs.setTabsClosable(True)
        self.sales_tabs.setMovable(True)
        self.sales_tabs.tabCloseRequested.connect(self.close_sale_tab)
        self.sales_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none; background: #ffffff;
                border-radius: {s(12)}px; margin-top: -1px;
            }}
            QTabBar::tab {{
                background: #f1f5f9; color: #64748b;
                padding: {s(10)}px {s(20)}px; font-weight: 600;
                font-size: {font(13)}px;
                border-radius: {s(10)}px {s(10)}px 0 0;
                margin-right: {s(4)}px;
                border: 1px solid #e2e8f0; border-bottom: none;
                min-width: {s(90)}px;
            }}
            QTabBar::tab:selected {{
                background: #ffffff; color: #1d4ed8;
                border-color: #bfdbfe; border-bottom: 3px solid #3b82f6;
                font-weight: 700;
            }}
            QTabBar::tab:hover:!selected {{ background: #e8f0fe; color: #1d4ed8; }}
        """)

        splitter.addWidget(self.sales_tabs)
        splitter.setSizes([s(600), s(500)])

        main_layout.addWidget(splitter, stretch=1)

        # ─ Inline History Panel ─────────────────────
        self.history_panel = HistoryWindow(self.api, self)
        self.history_panel.setVisible(False)
        self.history_panel.setMinimumHeight(s(360))
        self.history_panel.setMaximumHeight(s(500))
        self.history_panel.setStyleSheet("background: white; border-top: 2px solid #e2e8f0;")
        main_layout.addWidget(self.history_panel)

        # ─ Inline Shifts Panel ──────────────────────
        self.shifts_panel = PosShiftsWindow(self.api, self)
        self.shifts_panel.setVisible(False)
        self.shifts_panel.setMinimumHeight(s(300))
        self.shifts_panel.setMaximumHeight(s(450))
        self.shifts_panel.setStyleSheet("background: white; border-top: 2px solid #e2e8f0;")
        main_layout.addWidget(self.shifts_panel)

        # ─ Inline Offline Queue Panel ─────────────
        self.offline_panel = OfflineQueueWindow(self)
        self.offline_panel.setVisible(False)
        self.offline_panel.setMinimumHeight(s(280))
        self.offline_panel.setMaximumHeight(s(400))
        self.offline_panel.setStyleSheet("background: white; border-top: 2px solid #e2e8f0;")
        main_layout.addWidget(self.offline_panel)

        # Status bar
        status_bar = self.statusBar()
        self._sync_spinner = InlineSpinner(size=16, color="#3b82f6", parent=self)
        status_bar.addWidget(self._sync_spinner)
        self.status_label = QLabel("Tayyor.")
        status_bar.addWidget(self.status_label)

        # Birinchi sotuv tab
        self.add_new_sale_tab()

        return page

    # ── Company / Cashier badge ──────────────────────
    def _update_company_badge(self, company: str = "", pos_profile: str = ""):
        display = company if company else "—"
        self.company_badge.setText(display)
        self.company_badge.setStyleSheet(f"""
            font-size: {font(13)}px; font-weight: 700; color: #334155;
            background: transparent;
        """)

    def _update_cashier_badge(self, cashier: str = ""):
        # active_cashier mavjud bo'lsa — uning full_name ni ko'rsat
        if self.active_cashier:
            display = self.active_cashier.get("full_name") or self.active_cashier.get("name", "")
        elif cashier:
            # Fallback: ERPNext foydalanuvchi nomi (kassirlar yo'q holatda)
            display = cashier.split('@')[0].replace('.', ' ').replace('_', ' ').title()
        else:
            display = "—"
        self.cashier_badge.setText(display)
        self.cashier_badge.setStyleSheet(f"""
            font-size: {font(13)}px; font-weight: 800; color: #0369a1;
            background: transparent;
        """)

    def get_active_cashier_name(self) -> str:
        """Checkout uchun faol kassir ismini qaytarish."""
        if self.active_cashier:
            return self.active_cashier.get("full_name") or self.active_cashier.get("name", "")
        return ""

    # ── Background workers ───────────────────────────
    def _start_background_workers(self):
        self.sync_worker = SyncWorker(self.api)
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self._auto_sync = True
        self._sync_spinner.start()
        self.status_label.setText("Sinxronizatsiya...")
        self.sync_worker.start()

        self.offline_sync_worker = OfflineSyncWorker(self.api)
        self.offline_sync_worker.sync_status.connect(self.update_status)
        self.offline_sync_worker.start()

        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.monitor_system)
        self.monitor_timer.start(MONITOR_INTERVAL_MS)

        self._check_pos_opening()

    # ── System monitor ───────────────────────────────
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
        if is_online:
            self._wifi_icon.setPixmap(icon_wifi("#10b981").pixmap(s(18), s(18)))
            self.status_text.setText("Online")
            self.status_text.setStyleSheet(f"""
                font-weight: 700; color: #10b981; font-size: {font(12)}px;
                background: transparent;
            """)
        else:
            self._wifi_icon.setPixmap(icon_wifi("#ef4444").pixmap(s(18), s(18)))
            self.status_text.setText("Offline")
            self.status_text.setStyleSheet(f"""
                font-weight: 700; color: #ef4444; font-size: {font(12)}px;
                background: transparent;
            """)

    def _update_offline_queue_count(self):
        try:
            count = PendingInvoice.select().where(PendingInvoice.status == "Pending").count()
            self.offline_btn.setText(f"Offline: {count}")
            if count > 0:
                self.offline_btn.setStyleSheet(f"""
                    QPushButton {{ background: #fff7ed; color: #ea580c; font-weight: 700;
                        font-size: {font(13)}px; border-radius: {s(10)}px;
                        border: 2px solid #f97316; padding: 0 {s(16)}px; }}
                    QPushButton:hover {{ background: #ffedd5; }}
                """)
            else:
                self.offline_btn.setStyleSheet(_BTN_STYLE.format(
                    bg="#f8fafc", fg="#475569", hover="#e2e8f0",
                    border="1px solid #e2e8f0", fs=font(13), r=s(10), px=s(16),
                ))
        except Exception as e:
            logger.debug("Offline queue count xatosi: %s", e)

    # ── Sale tabs ────────────────────────────────────
    def show_offline_queue(self):
        visible = self.offline_panel.isVisible()
        if visible:
            self.offline_panel.setVisible(False)
        else:
            self.history_panel.setVisible(False)
            self.shifts_panel.setVisible(False)
            self.offline_panel.setVisible(True)
            self.offline_panel.load_pending()

    def add_new_sale_tab(self):
        tab_count = self.sales_tabs.count()
        new_cart = CartWidget()
        new_cart.checkout_requested.connect(self.on_checkout)
        new_cart.apply_settings()
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
        order_data["active_cashier"] = self.get_active_cashier_name()
        dialog = CheckoutWindow(self, order_data, self.api)
        dialog.checkout_completed.connect(self.on_checkout_completed)
        dialog.exec()

    def on_checkout_completed(self):
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.clear_cart()
        self._update_offline_queue_count()

    # ── History / Shifts ─────────────────────────────
    def show_shifts_history(self):
        visible = self.shifts_panel.isVisible()
        if visible:
            self.shifts_panel.setVisible(False)
        else:
            self.history_panel.setVisible(False)
            self.offline_panel.setVisible(False)
            self.shifts_panel.setVisible(True)
            self.shifts_panel.load_shifts()

    def show_history(self):
        self.shifts_panel.setVisible(False)
        self.offline_panel.setVisible(False)
        visible = self.history_panel.isVisible()
        if visible:
            self.history_panel.setVisible(False)
        else:
            from core.config import load_config
            _cfg = load_config()
            self.history_panel.opening_entry = self.opening_entry or ""
            self.history_panel.pos_profile = _cfg.get("pos_profile", "")
            self.history_panel.cashier = _cfg.get("cashier", "")
            self.history_panel.setVisible(True)
            self.history_panel.load_history()

    # ── Sync ─────────────────────────────────────────
    def start_sync(self):
        if hasattr(self, 'sync_worker') and self.sync_worker.isRunning():
            self.status_label.setText("Sinxronizatsiya hali davom etmoqda...")
            return
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("Sinxronizatsiya...")
        self.sync_btn.setIcon(icon_loading())
        self._sync_spinner.start()
        self._auto_sync = False
        self.sync_worker = SyncWorker(self.api)
        self.sync_worker.progress_update.connect(self.update_status)
        self.sync_worker.sync_finished.connect(self.on_sync_finished)
        self.sync_worker.start()

    def update_status(self, message: str):
        self.status_label.setText(message)

    def on_sync_finished(self, success: bool, message: str):
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("Sinxronlash")
        self.sync_btn.setIcon(icon_sync())
        self._sync_spinner.stop()
        cfg = load_config()
        self._update_company_badge(cfg.get("company", ""), cfg.get("pos_profile", ""))
        self._update_cashier_badge(cfg.get("cashier", cfg.get("user", "")))
        self._apply_pos_settings(cfg)
        if success:
            # Sidebar kategoriyalarini va itemlarni yangilash
            self.item_browser.load_categories()
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

    def _apply_pos_settings(self, cfg: dict = None):
        """Startup va sinxrondan keyin POS sozlamalarini UIga qo'llash."""
        if cfg is None:
            cfg = load_config()
        show_history = bool(cfg.get("show_history", 1))
        show_shifts  = bool(cfg.get("show_shifts", 1))
        self.history_btn.setVisible(show_history)
        self.shifts_btn.setVisible(show_shifts)
        if not show_history:
            self.history_panel.setVisible(False)
        if not show_shifts:
            self.shifts_panel.setVisible(False)

        # Barcha ochiq cart tab'larni yangilash
        for i in range(self.sales_tabs.count()):
            cart = self.sales_tabs.widget(i)
            if cart and hasattr(cart, "apply_settings"):
                cart.apply_settings()

    # ── POS Opening / Closing ────────────────────────
    def _check_pos_opening(self):
        self._set_pos_enabled(False)
        self.opening_check_worker = PosOpeningCheckWorker(self.api)
        self.opening_check_worker.result_ready.connect(self._on_opening_check_done)
        self.opening_check_worker.start()

    def _on_opening_check_done(self, has_opening: bool, opening_entry: str):
        if has_opening:
            self.opening_entry = opening_entry
            self._set_pos_enabled(True)
            # Faqat hali ochish sahifasida bo'lsak o'tkazamiz (lokal DB allaqachon to'g'ri o'rnatgan bo'lsa — qo'zg'amiz)
            if self._stack.currentIndex() != 1:
                self._stack.setCurrentIndex(1)
            self.status_label.setText("Kassa ochiq.")
        else:
            # Server: kassa yopiq — lokal DB noto'g'ri bo'lgan (muvofiqlashtirish)
            self.opening_entry = None
            self._set_pos_enabled(False)
            if self._stack.currentIndex() != 0:
                self._stack.setCurrentIndex(0)
                self.status_label.setText("Kassa yopiq. Iltimos kassani oching.")

    def _on_pos_opened(self, opening_entry: str):
        self.opening_entry = opening_entry
        self._set_pos_enabled(True)
        self._stack.setCurrentIndex(1)    # Main content
        self.status_label.setText("Kassa ochildi!")

    def show_pos_closing(self):
        if not self.opening_entry:
            InfoDialog(self, "Kassa topilmadi", "Ochiq kassa topilmadi.", kind="warning").exec()
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

        # Kassa ochish sahifasiga qaytish
        self._pos_opening_page.refresh()
        self._stack.setCurrentIndex(0)

    def _set_pos_enabled(self, enabled: bool):
        if hasattr(self, 'add_sale_btn'):
            self.add_sale_btn.setEnabled(enabled)
        if hasattr(self, 'close_shift_btn'):
            self.close_shift_btn.setEnabled(enabled)
        if hasattr(self, 'item_browser'):
            self.item_browser.setEnabled(enabled)
        if hasattr(self, 'sales_tabs'):
            self.sales_tabs.setEnabled(enabled)

    # ── Close event ──────────────────────────────────
    def closeEvent(self, event):
        # 1. Timerni to'xtatish — yangi worker yaratilmasin
        if hasattr(self, 'monitor_timer'):
            self.monitor_timer.stop()

        # 2. Worker signallarini uzish — yopilish jarayonida UI yangilanmasin
        for attr, signals in (
            ('sync_worker',          ('sync_finished', 'progress_update')),
            ('_connectivity_worker', ('result_ready',)),
            ('opening_check_worker', ('result_ready',)),
        ):
            if hasattr(self, attr):
                worker = getattr(self, attr)
                for sig_name in signals:
                    try:
                        getattr(worker, sig_name).disconnect()
                    except RuntimeError:
                        pass

        # 3. Barcha HTTP so'rovlarni darhol to'xtatish.
        #    Bloklangan session.get/post → ConnectionError → thread except'da ushlab chiqadi.
        self.api.abort_all()

        # 4. Image loader threadlarini to'xtatish
        if hasattr(self, 'item_browser'):
            self.item_browser.shutdown()

        # 5. Offline sync worker — o'z loop'i bor, to'xtatish ishorasi beriladi
        if hasattr(self, 'offline_sync_worker'):
            self.offline_sync_worker.stop()
            self.offline_sync_worker.wait(2000)

        # 6. Qolgan workerlar — abort_all() dan keyin tez chiqadi
        for attr in ('sync_worker', '_connectivity_worker', 'opening_check_worker'):
            if hasattr(self, attr):
                worker = getattr(self, attr)
                if worker.isRunning():
                    worker.wait(3000)

        # 7. DB ni yopish
        if not db.is_closed():
            db.close()

        super().closeEvent(event)
