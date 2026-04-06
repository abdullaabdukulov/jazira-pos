"""
Kassir PIN kiritish dialogi — avtomatik aniqlash.

Foydalanuvchi 4 ta raqam kiritadi, tizim qaysi kassirga tegishli ekanini
o'zi aniqlaydi va o'sha kassirni faol qiladi.

Ishlatish:
    dlg = CashierLoginDialog(parent, cashiers)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        active = dlg.selected_cashier  # {"name": ..., "full_name": ..., ...}
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QPushButton, QWidget, QGridLayout, QScrollArea,
)
from PyQt6.QtCore import Qt
from core.config import load_config, save_config
from core.logger import get_logger
from ui.scale import s, font

logger = get_logger(__name__)


_BTN = """
QPushButton {{
    background: {bg}; color: {fg};
    font-size: {fs}px; font-weight: 700;
    border-radius: {r}px; border: {border};
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ opacity: 0.8; }}
"""


def _make_btn(label: str, kind: str = "ghost") -> QPushButton:
    styles = {
        "ghost":   dict(bg="#f1f5f9", fg="#334155", hover="#e2e8f0", border="1px solid #e2e8f0"),
        "danger":  dict(bg="#dc2626", fg="white",   hover="#b91c1c", border="none"),
        "primary": dict(bg="#1d4ed8", fg="white",   hover="#1e40af", border="none"),
        "muted":   dict(bg="transparent", fg="#94a3b8", hover="#f1f5f9", border="none"),
    }
    st = styles.get(kind, styles["ghost"])
    b = QPushButton(label)
    b.setStyleSheet(_BTN.format(
        bg=st["bg"], fg=st["fg"], hover=st["hover"], border=st["border"],
        fs=font(14), r=s(10),
    ))
    return b


class CashierLoginDialog(QDialog):
    """
    Faqat PIN pad — kassir avtomatik aniqlanadi.
    Pastda "PIN o'rnatish" tugmasi: tanlov + yangi PIN belgilash.
    """

    def __init__(self, parent=None, cashiers: list = None, setup_only: bool = False):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(s(380), s(560))
        self.setStyleSheet("background: white; border-radius: 16px;")
        self._setup_only = setup_only

        self._cashiers = cashiers or []
        self.selected_cashier = None

        self._mode = "login"   # "login" | "select" | "set_pin"
        self._pin = ""
        self._setup_cashier = None   # Tanlangan kassir (set_pin uchun)
        self._new_pin = ""           # Birinchi kiritish (tasdiqlash uchun)

        self._build_ui()
        if setup_only:
            self._enter_select_mode()
        else:
            self._enter_login_mode()

    # ── UI qurish ────────────────────────────────────
    def _build_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(s(28), s(24), s(28), s(20))
        self._root.setSpacing(s(12))

        # Sarlavha
        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            f"font-size: {font(19)}px; font-weight: 900; color: #0f172a;"
        )
        self._root.addWidget(self._title)

        # Xato/info xabari
        self._msg_lbl = QLabel("")
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet(
            f"font-size: {font(13)}px; color: #dc2626; font-weight: 700; min-height: {s(18)}px;"
        )
        self._root.addWidget(self._msg_lbl)

        # ── Sahifa A: PIN pad ──────────────────────────
        self._pin_page = QWidget()
        pin_layout = QVBoxLayout(self._pin_page)
        pin_layout.setContentsMargins(0, 0, 0, 0)
        pin_layout.setSpacing(s(12))

        # PIN ko'rsatkich
        self._pin_display = QLabel()
        self._pin_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pin_display.setFixedHeight(s(72))
        pin_layout.addWidget(self._pin_display)

        # Raqam tugmalari (3×4 joylanish)
        grid = QGridLayout()
        grid.setSpacing(s(9))
        digits = ["1","2","3","4","5","6","7","8","9","","0","⌫"]
        positions = [(r, c) for r in range(4) for c in range(3)]
        for pos, d in zip(positions, digits):
            if not d:
                continue
            btn = QPushButton(d)
            btn.setFixedHeight(s(58))
            if d == "⌫":
                btn.setStyleSheet(_BTN.format(
                    bg="#fee2e2", fg="#dc2626", hover="#fecaca",
                    border="none", fs=font(20), r=s(10)
                ))
                btn.clicked.connect(self._on_backspace)
            else:
                btn.setStyleSheet(_BTN.format(
                    bg="#f1f5f9", fg="#0f172a", hover="#e2e8f0",
                    border="none", fs=font(20), r=s(10)
                ))
                btn.clicked.connect(lambda _, digit=d: self._on_digit(digit))
            grid.addWidget(btn, pos[0], pos[1])
        pin_layout.addLayout(grid)

        # "PIN o'rnatish" + orqaga tugmalari
        self._setup_btn = _make_btn("PIN o'rnatish →", "muted")
        self._setup_btn.setFixedHeight(s(36))
        self._setup_btn.clicked.connect(self._enter_select_mode)
        pin_layout.addWidget(self._setup_btn)

        self._back_btn = _make_btn("← Orqaga", "ghost")
        self._back_btn.setFixedHeight(s(40))
        self._back_btn.clicked.connect(self._enter_login_mode)
        self._back_btn.hide()
        pin_layout.addWidget(self._back_btn)

        self._root.addWidget(self._pin_page, stretch=1)

        # ── Sahifa B: Kassir tanlash (faqat set_pin uchun) ──
        self._select_page = QWidget()
        sel_layout = QVBoxLayout(self._select_page)
        sel_layout.setContentsMargins(0, 0, 0, 0)
        sel_layout.setSpacing(s(8))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(scroll_content)
        self._list_layout.setSpacing(s(8))
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_content)
        sel_layout.addWidget(scroll, stretch=1)

        back2 = _make_btn("← Ortga", "ghost")
        back2.setFixedHeight(s(40))
        back2.clicked.connect(self._enter_login_mode if not self._setup_only else super().reject)
        sel_layout.addWidget(back2)

        self._select_page.hide()
        self._root.addWidget(self._select_page, stretch=1)

    # ── Rejimlar ─────────────────────────────────────
    def _enter_login_mode(self):
        self._mode = "login"
        self._pin = ""
        self._new_pin = ""
        self._setup_cashier = None
        self._title.setText("PIN kiriting")
        self._clear_msg()
        self._update_pin_display()
        self._setup_btn.show()
        self._back_btn.hide()
        self._pin_page.show()
        self._select_page.hide()

    def _enter_select_mode(self):
        """Kassir tanlash sahifasi (PIN o'rnatish uchun)."""
        self._mode = "select"
        self._title.setText("Kassirni tanlang")
        self._clear_msg()
        self._pin_page.hide()
        self._select_page.show()
        self._populate_list()

    def _enter_set_pin_mode(self, cashier: dict):
        """Tanlangan kassir uchun yangi PIN belgilash."""
        self._mode = "set_pin"
        self._setup_cashier = cashier
        self._pin = ""
        self._new_pin = ""
        name = cashier.get("full_name") or cashier.get("name", "")
        self._title.setText(f"Yangi PIN: {name}")
        self._show_msg(f"{name} uchun yangi PIN kiriting", color="#1d4ed8")
        self._update_pin_display()
        self._setup_btn.hide()
        self._back_btn.show()
        self._select_page.hide()
        self._pin_page.show()

    # ── Kassir ro'yxati ──────────────────────────────
    def _populate_list(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._cashiers:
            msg = QLabel("Kassirlar topilmadi.\nSinxronizatsiya qiling.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet(f"color: #94a3b8; font-size: {font(14)}px;")
            self._list_layout.addWidget(msg)
            return

        for cashier in self._cashiers:
            name = cashier.get("full_name") or cashier.get("name", "Noma'lum")
            has_pin = bool(cashier.get("pin"))
            label = name if has_pin else f"{name}  (PIN yo'q)"
            btn = QPushButton(label)
            btn.setFixedHeight(s(50))
            btn.setStyleSheet(_BTN.format(
                bg="#eff6ff", fg="#1d4ed8", hover="#dbeafe",
                border="1px solid #bfdbfe", fs=font(15), r=s(10)
            ))
            btn.clicked.connect(lambda _, c=cashier: self._enter_set_pin_mode(c))
            self._list_layout.addWidget(btn)

        self._list_layout.addStretch()

    # ── PIN logikasi ──────────────────────────────────
    def _on_digit(self, digit: str):
        if len(self._pin) >= 4:
            return
        self._pin += digit
        self._update_pin_display()
        if len(self._pin) == 4:
            self._handle_full_pin()

    def _on_backspace(self):
        if self._pin:
            self._pin = self._pin[:-1]
            self._update_pin_display()
            self._clear_msg()
        elif self._mode == "set_pin" and self._new_pin:
            # Tasdiqlash bosqichida orqaga — birinchi kiritmani tashlaymiz
            self._new_pin = ""
            name = self._setup_cashier.get("full_name") or ""
            self._title.setText(f"Yangi PIN: {name}")
            self._show_msg(f"{name} uchun yangi PIN kiriting", color="#1d4ed8")

    def _update_pin_display(self):
        dots = ["●" if i < len(self._pin) else "○" for i in range(4)]
        self._pin_display.setText("  ".join(dots))
        color = "#1d4ed8" if self._pin else "#cbd5e1"
        self._pin_display.setStyleSheet(
            f"font-size: {font(34)}px; font-weight: 900; color: {color}; "
            f"background: #f8fafc; border-radius: {s(12)}px;"
        )

    def _handle_full_pin(self):
        if self._mode == "login":
            self._try_login()
        elif self._mode == "set_pin":
            self._handle_set_pin()

    # ── Login: avtomatik kassirni topish ─────────────
    def _try_login(self):
        match = None
        for c in self._cashiers:
            if c.get("pin") == self._pin:
                match = c
                break

        if match:
            self.selected_cashier = match
            self.accept()
        else:
            self._pin = ""
            self._update_pin_display()
            self._show_msg("Noto'g'ri PIN. Qaytadan urinib ko'ring.")

    # ── PIN o'rnatish ─────────────────────────────────
    def _handle_set_pin(self):
        if not self._new_pin:
            # Birinchi kiritish — saqlash va tasdiqlashni so'rash
            self._new_pin = self._pin
            self._pin = ""
            self._update_pin_display()
            name = self._setup_cashier.get("full_name") or ""
            self._title.setText("PIN ni tasdiqlang")
            self._show_msg("Xuddi shu PINni qaytadan kiriting", color="#1d4ed8")
        else:
            # Ikkinchi kiritish — tasdiqlash
            if self._pin == self._new_pin:
                self._persist_pin(self._pin)
                if self._setup_only:
                    super().accept()
                    return
                self._enter_login_mode()
                name = self._setup_cashier.get("full_name") or ""
                self._show_msg(f"{name} uchun PIN saqlandi!", color="#16a34a")
            else:
                self._new_pin = ""
                self._pin = ""
                self._update_pin_display()
                self._show_msg("PINlar mos kelmadi. Qaytadan kiriting.")

    def _persist_pin(self, pin: str):
        """Yangi PIN ni config.json ga saqlash."""
        cashier_name = (
            self._setup_cashier.get("full_name") or self._setup_cashier.get("name", "")
        )
        cashiers = load_config().get("cashiers", [])
        updated = False
        for c in cashiers:
            ident = c.get("full_name") or c.get("name", "")
            if ident.lower() == cashier_name.lower():
                c["pin"] = pin
                updated = True
                break
        if not updated:
            cashiers.append({"name": cashier_name, "full_name": cashier_name, "pin": pin})

        # In-memory ham yangilansin
        for c in self._cashiers:
            ident = c.get("full_name") or c.get("name", "")
            if ident.lower() == cashier_name.lower():
                c["pin"] = pin
                break

        save_config({"cashiers": cashiers})

    # ── Xabar ────────────────────────────────────────
    def _show_msg(self, text: str, color: str = "#dc2626"):
        self._msg_lbl.setStyleSheet(
            f"font-size: {font(13)}px; color: {color}; font-weight: 700; min-height: {s(18)}px;"
        )
        self._msg_lbl.setText(text)

    def _clear_msg(self):
        self._msg_lbl.setText("")

    def reject(self):
        if self._setup_only:
            super().reject()   # Setup dialogini yopishga ruxsat
        # Login dialogini yopib bo'lmaydi (majburiy)
