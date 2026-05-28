from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QSplitter, QTabWidget, QStackedWidget, QFrame,
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, pyqtProperty, QSize, QRect,
    QPropertyAnimation, QEasingCurve, QAbstractAnimation,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient,
)
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
from ui.components.pending_orders_window import PendingOrdersWindow
from ui.components.table_picker import TablePickerDialog
from ui.components.save_order_worker import SaveOrderWorker
from ui.components.pos_opening import PosOpeningPage
from ui.components.pos_closing import PosClosingDialog
from ui.components.pos_shifts_window import PosShiftsWindow
from ui.components.dialogs import InfoDialog, ConfirmDialog
from ui.components.loading import InlineSpinner
from ui.components.offline_block_overlay import OfflineBlockOverlay
from core.realtime import RealtimeClient
from core.connection_monitor import ConnectionMonitor, STATE_ONLINE, STATE_OFFLINE
from ui.icons import (
    icon_plus, icon_clock, icon_signal, icon_building,
)
from ui.scale import s, font

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
#  Elite identity strip — brand mark, status, company, cashier
# ═══════════════════════════════════════════════════════════
_GOLD = "#c89968"
_GOLD_LIGHT = "#e6c693"
_GOLD_DEEP = "#a07a44"
_SLATE_900 = "#0f172a"
_SLATE_700 = "#334155"
_SLATE_500 = "#64748b"
_SLATE_400 = "#94a3b8"
_SLATE_300 = "#cbd5e1"
_SLATE_200 = "#e2e8f0"
_SLATE_100 = "#f1f5f9"
_SLATE_50 = "#f8fafc"


class BrandMark(QWidget):
    """Oltin gradient disc + oq italik 'J' — top bar brand belgisi."""

    def __init__(self, size: int = 34, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Oltin gradient fill
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(_GOLD_LIGHT))
        grad.setColorAt(1.0, QColor(_GOLD_DEEP))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(_GOLD_DEEP), 1))
        p.drawEllipse(1, 1, w - 2, h - 2)

        # J monogrammasi (italik, oq)
        f = QFont("Georgia", -1)
        f.setPixelSize(int(w * 0.55))
        f.setWeight(QFont.Weight.Bold)
        f.setItalic(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(
            QRect(0, int(-h * 0.04), w, h),
            Qt.AlignmentFlag.AlignCenter,
            "J",
        )


class AvatarDisc(QWidget):
    """Kassir avatar — outer slate ring + ichki oltin gradient disc + initiallar."""

    def __init__(self, size: int = 38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._initials = "—"

    def set_initials(self, initials: str):
        self._initials = (initials or "—").upper()[:2]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Outer ambient gold halo (juda nozik)
        cx, cy = w / 2, h / 2
        halo = QRadialGradient(cx, cy, w * 0.6)
        halo.setColorAt(0.45, QColor(200, 153, 104, 26))
        halo.setColorAt(1.0, QColor(200, 153, 104, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(0, 0, w, h)

        # Asosiy oltin gradient disc
        margin = max(2, int(w * 0.08))
        disc_size = w - 2 * margin
        grad = QLinearGradient(0, margin, 0, h - margin)
        grad.setColorAt(0.0, QColor(_GOLD_LIGHT))
        grad.setColorAt(1.0, QColor(_GOLD_DEEP))
        p.setBrush(QBrush(grad))
        # Outer subtle ring — slate-200 tonida
        p.setPen(QPen(QColor(_GOLD_DEEP), 1))
        p.drawEllipse(margin, margin, disc_size, disc_size)

        # Initiallar — oq, weight Black
        f = QFont()
        f.setPixelSize(int(w * 0.38))
        f.setWeight(QFont.Weight.Black)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._initials)


class BrandBlock(QWidget):
    """Top-bar brand: oltin disc + dinamik brand nomi + POINT OF SALE sub.

    Brand nomi POS Profile.custom_company_brand_name dan keladi (yo'q bo'lsa
    Company nomi, oxirgi chora — "JAZIRA POS").
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(6), 0, s(8), 0)
        layout.setSpacing(s(12))
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(BrandMark(s(36)))

        text = QVBoxLayout()
        text.setSpacing(s(1))
        text.setContentsMargins(0, 0, 0, 0)
        text.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._name = QLabel(self._resolve_brand())
        self._name.setFrameShape(QFrame.Shape.NoFrame)
        self._name.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nf = QFont()
        nf.setPixelSize(font(15))
        nf.setWeight(QFont.Weight.Black)
        nf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self._name.setFont(nf)
        self._name.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        text.addWidget(self._name)

        sub = QLabel("POINT  OF  SALE")
        sub.setFrameShape(QFrame.Shape.NoFrame)
        sub.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sf = QFont()
        sf.setPixelSize(font(8))
        sf.setWeight(QFont.Weight.Bold)
        sf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        sub.setFont(sf)
        sub.setStyleSheet(
            f"color: {_GOLD}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        text.addWidget(sub)

        layout.addLayout(text)

    @staticmethod
    def _resolve_brand() -> str:
        try:
            cfg = load_config()
        except Exception:
            return "POS"
        base = cfg.get("brand_name") or cfg.get("company") or ""
        base = str(base).strip().upper()
        if not base:
            return "POS"
        # POS suffix qo'shamiz, agar foydalanuvchi o'zi yozmagan bo'lsa
        if "POS" in base:
            return base
        return f"{base} POS"

    def refresh(self):
        """Config yangilangach brand'ni qayta-render."""
        if hasattr(self, "_name"):
            new = self._resolve_brand()
            if self._name.text() != new:
                self._name.setText(new)


class StatusIndicator(QWidget):
    """Status uchun elite painted indicator — dot emas, sof symbolic shape.

    Holatlar:
      online   — halqa ichida emerald check (✓), nafas oluvchi nozik glow
      offline  — halqa ichida red ×
      checking — 3 ta vertikal nuqta (loading)
    """

    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = "checking"
        self._color = QColor("#94a3b8")
        self._pulse = 0.0
        self._anim: QPropertyAnimation | None = None

    def set_state(self, state: str, hex_color: str):
        self._state = state
        self._color = QColor(hex_color)
        self.update()

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, v: float):
        self._pulse = float(v)
        self.update()

    pulse = pyqtProperty(float, _get_pulse, _set_pulse)

    def start_pulse(self):
        self.stop_pulse()
        self._anim = QPropertyAnimation(self, b"pulse", self)
        self._anim.setDuration(1800)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.start()

    def stop_pulse(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._pulse = 0.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - max(1, w * 0.06)

        # Nafas oluvchi nozik glow (faqat onlinde, pulse 0..1)
        if self._pulse > 0:
            glow_r = r * (1.0 + self._pulse * 0.7)
            glow = QRadialGradient(cx, cy, glow_r * 1.4)
            gc = QColor(self._color)
            gc.setAlphaF(0.28 * (1.0 - self._pulse))
            glow.setColorAt(0.30, gc)
            glow.setColorAt(1.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(int(cx - glow_r * 1.4), int(cy - glow_r * 1.4),
                          int(glow_r * 2.8), int(glow_r * 2.8))

        # Halqa (ring) — har 3 holat uchun ham asos
        ring_pen = QPen(self._color, max(1.0, w * 0.10))
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # Ichidagi symbolic shape
        stroke = QPen(self._color, max(1.4, w * 0.13))
        stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(stroke)
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self._state == "online":
            # Check ✓
            from PyQt6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(cx - r * 0.40, cy + r * 0.05)
            path.lineTo(cx - r * 0.05, cy + r * 0.35)
            path.lineTo(cx + r * 0.50, cy - r * 0.30)
            p.drawPath(path)
        elif self._state == "offline":
            # ✕
            off = r * 0.40
            p.drawLine(int(cx - off), int(cy - off), int(cx + off), int(cy + off))
            p.drawLine(int(cx + off), int(cy - off), int(cx - off), int(cy + off))
        else:
            # 3 ta nuqta — loading
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            dr = max(1.0, w * 0.07)
            for dx in (-r * 0.45, 0.0, r * 0.45):
                p.drawEllipse(int(cx + dx - dr), int(cy - dr), int(dr * 2), int(dr * 2))


class StatusPill(QFrame):
    """Server holati — pill + pulsing dot (online holatida nafas oladi)."""

    _CFG = {
        "online":   ("#f0fdf4", "#bbf7d0", "#047857", "#10b981", "Online"),
        "offline":  ("#fef2f2", "#fecaca", "#b91c1c", "#ef4444", "Offline"),
        "checking": ("#f8fafc", "#e2e8f0", "#475569", "#94a3b8", "Tekshirilmoqda"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(14), s(6), s(16), s(6))
        layout.setSpacing(s(10))

        self._indicator = StatusIndicator(s(16))
        layout.addWidget(self._indicator, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._text = QLabel("")
        self._text.setFrameShape(QFrame.Shape.NoFrame)
        self._text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tf = QFont()
        tf.setPixelSize(font(11))
        tf.setWeight(QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self._text.setFont(tf)
        layout.addWidget(self._text)

        self.set_state("checking")

    def set_state(self, state: str):
        bg, border, text_c, dot_c, label = self._CFG.get(
            state, self._CFG["checking"]
        )
        self.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {s(13)}px;
            }}
        """)
        self._indicator.set_state(state, dot_c)
        self._text.setStyleSheet(
            f"color: {text_c}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        self._text.setText(label.upper() if state == "online" else label)
        # Faqat online holatida nafas oladi
        if state == "online":
            self._indicator.start_pulse()
        else:
            self._indicator.stop_pulse()


class CompanyChip(QFrame):
    """Kompaniya pill — oltin chap aksent chiziq + UPPERCASE nom.

    Ikonka o'rniga chap chetida 3px oltin vertikal aksent — minimalist + brand.
    """

    def __init__(self, name: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        # Chap padding kichikroq — oltin aksent uchun joy
        layout.setContentsMargins(s(14), s(7), s(16), s(7))
        layout.setSpacing(0)

        self._text = QLabel("")
        self._text.setFrameShape(QFrame.Shape.NoFrame)
        self._text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tf = QFont()
        tf.setPixelSize(font(11))
        tf.setWeight(QFont.Weight.Black)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        self._text.setFont(tf)
        self._text.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        layout.addWidget(self._text)

        # Chap chetda oltin aksent chizig'i
        self.setStyleSheet(f"""
            QFrame {{
                background: white;
                border: 1px solid {_SLATE_200};
                border-left: 3px solid {_GOLD};
                border-top-left-radius: {s(6)}px;
                border-bottom-left-radius: {s(6)}px;
                border-top-right-radius: {s(13)}px;
                border-bottom-right-radius: {s(13)}px;
            }}
        """)
        self.set_company(name)

    def set_company(self, name: str):
        self._text.setText((name or "—").upper())


class CashierCard(QWidget):
    """Avatar disc + ism + rol caps (Kassir=gold, Ofitsant=binafsha).

    Elite ikki-qatorli ko'rinish:
      [AN]   Asadbek Nizomiddinov
             KASSIR  ·  Active     ← caps + letter-spacing + tint accent
    """

    _ROLE_CFG = {
        # (matn rangi, sub-aksent rangi)
        "Kassir":   ("#a07a44", _GOLD),
        "Ofitsant": ("#6d28d9", "#8b5cf6"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(2), 0, s(6), 0)
        layout.setSpacing(s(12))

        self._avatar = AvatarDisc(s(40))
        layout.addWidget(self._avatar, alignment=Qt.AlignmentFlag.AlignVCenter)

        right = QVBoxLayout()
        right.setSpacing(s(2))
        right.setContentsMargins(0, 0, 0, 0)
        right.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Ism — bold slate-900
        self._name = QLabel("—")
        self._name.setFrameShape(QFrame.Shape.NoFrame)
        self._name.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nf = QFont()
        nf.setPixelSize(font(13))
        nf.setWeight(QFont.Weight.Black)
        nf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
        self._name.setFont(nf)
        self._name.setStyleSheet(
            f"color: {_SLATE_900}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        right.addWidget(self._name)

        # Rol qator — bullet bilan
        role_row = QHBoxLayout()
        role_row.setContentsMargins(0, 0, 0, 0)
        role_row.setSpacing(s(6))

        # Bullet kichik aksent dot
        self._role_dot = QLabel("●")
        self._role_dot.setFrameShape(QFrame.Shape.NoFrame)
        bd = QFont()
        bd.setPixelSize(font(7))
        self._role_dot.setFont(bd)
        self._role_dot.setStyleSheet(
            f"color: {_GOLD}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        role_row.addWidget(self._role_dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Rol matni — caps, letter-spacing
        self._role_text = QLabel("")
        self._role_text.setFrameShape(QFrame.Shape.NoFrame)
        self._role_text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rf = QFont()
        rf.setPixelSize(font(9))
        rf.setWeight(QFont.Weight.Black)
        rf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        self._role_text.setFont(rf)
        self._role_text.setStyleSheet(
            f"color: {_GOLD}; background: transparent;"
            f" border: none; outline: none; padding: 0; margin: 0;"
        )
        role_row.addWidget(self._role_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        role_row.addStretch()

        right.addLayout(role_row)
        layout.addLayout(right)

    def set_cashier(self, name: str, role: str = ""):
        name = (name or "—").strip() or "—"
        self._name.setText(name)
        self._avatar.set_initials(self._initials(name))

        if role:
            text_c, dot_c = self._ROLE_CFG.get(role, self._ROLE_CFG["Kassir"])
            self._role_text.setText(role.upper())
            self._role_text.setStyleSheet(
                f"color: {text_c}; background: transparent;"
                f" border: none; outline: none; padding: 0; margin: 0;"
            )
            self._role_dot.setStyleSheet(
                f"color: {dot_c}; background: transparent;"
                f" border: none; outline: none; padding: 0; margin: 0;"
            )
            self._role_dot.setVisible(True)
            self._role_text.setVisible(True)
        else:
            self._role_dot.setVisible(False)
            self._role_text.setVisible(False)

    @staticmethod
    def _initials(name: str) -> str:
        parts = (name or "").strip().split()
        if not parts:
            return "—"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


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
def _btn_style(kind: str) -> str:
    """Top-bar tugma stillari — elite palette (slate + subtle red).

    kind:
      primary    — Slate-900 fill (Yangi sotuv) — asosiy harakat
      secondary  — White ghost with slate border (Tarix, Sinx, Kassa tarixi)
      danger     — Outlined red, hover-fill (Kassa yopish)
      neutral    — Backward-compat alias → secondary
      ghost      — Backward-compat alias → secondary
    """
    fs = font(13)
    r = s(10)
    px = s(18)

    if kind == "primary":
        return f"""
            QPushButton {{
                background: {_SLATE_900};
                color: white;
                font-weight: 700;
                font-size: {fs}px;
                border-radius: {r}px;
                border: 1px solid {_SLATE_900};
                padding: 0 {px}px;
            }}
            QPushButton:hover {{
                background: #1e293b;
                border-color: #1e293b;
            }}
            QPushButton:pressed {{ background: #0b1220; }}
            QPushButton:disabled {{
                background: {_SLATE_100};
                color: #94a3b8;
                border-color: {_SLATE_200};
            }}
        """
    if kind == "danger":
        return f"""
            QPushButton {{
                background: white;
                color: #b91c1c;
                font-weight: 700;
                font-size: {fs}px;
                border-radius: {r}px;
                border: 1px solid #fecaca;
                padding: 0 {s(16)}px;
            }}
            QPushButton:hover {{
                background: #fef2f2;
                color: #991b1b;
                border-color: #fca5a5;
            }}
            QPushButton:pressed {{ background: #fee2e2; }}
        """
    # secondary / neutral / ghost
    return f"""
        QPushButton {{
            background: white;
            color: {_SLATE_700};
            font-weight: 600;
            font-size: {fs}px;
            border-radius: {r}px;
            border: 1px solid {_SLATE_200};
            padding: 0 {s(16)}px;
        }}
        QPushButton:hover {{
            background: {_SLATE_50};
            border: 1px solid #cbd5e1;
            color: {_SLATE_900};
        }}
        QPushButton:pressed {{ background: #e2e8f0; }}
        QPushButton:disabled {{
            background: {_SLATE_50};
            color: #94a3b8;
        }}
    """


def _tb_btn(label: str, kind: str = "secondary") -> QPushButton:
    b = QPushButton(label)
    b.setFixedHeight(s(44))
    b.setIconSize(QSize(s(16), s(16)))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(_btn_style(kind))
    return b


class CounterChip(QFrame):
    """Top-bar counter — label + integrated badge.

    Holatlar:
      idle (count=0): muted slate badge
      active (count>0): orange tinted with bold count

    API:
      .set_count(n)
      .clicked signal
    """

    clicked = pyqtSignal()

    def __init__(self, label: str, icon=None, parent=None):
        super().__init__(parent)
        self._label_text = label
        self._count = 0
        self._build(icon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(s(44))
        self.set_count(0)

    def _build(self, icon):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(s(14), 0, s(10), 0)
        layout.setSpacing(s(10))

        if icon is not None:
            self._icon = QLabel()
            self._icon.setFixedSize(s(16), s(16))
            self._icon.setPixmap(icon.pixmap(s(15), s(15)))
            self._icon.setStyleSheet("background: transparent; border: none;")
            layout.addWidget(self._icon)
        else:
            self._icon = None

        self._label = QLabel(self._label_text)
        lf = QFont()
        lf.setPixelSize(font(13))
        lf.setWeight(QFont.Weight.DemiBold)
        self._label.setFont(lf)
        layout.addWidget(self._label)

        # Counter badge pill
        self._badge = QLabel("0")
        bf = QFont()
        bf.setPixelSize(font(11))
        bf.setWeight(QFont.Weight.Black)
        self._badge.setFont(bf)
        self._badge.setMinimumWidth(s(24))
        self._badge.setFixedHeight(s(22))
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._badge)

    def set_count(self, n: int):
        self._count = int(n)
        self._badge.setText(str(self._count))
        self._refresh_style()

    def _refresh_style(self):
        if self._count > 0:
            # Active — orange tint
            bg = "white"
            border = "#fdba74"
            hover_bg = "#fff7ed"
            label_color = "#c2410c"
            badge_bg = "#ea580c"
            badge_fg = "white"
        else:
            # Idle — muted slate
            bg = "white"
            border = _SLATE_200
            hover_bg = _SLATE_50
            label_color = _SLATE_700
            badge_bg = _SLATE_100
            badge_fg = _SLATE_500

        self.setStyleSheet(f"""
            CounterChip {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {s(10)}px;
            }}
            CounterChip:hover {{
                background: {hover_bg};
            }}
        """)
        self._label.setStyleSheet(
            f"color: {label_color}; background: transparent; border: none;"
        )
        self._badge.setStyleSheet(f"""
            color: {badge_fg};
            background: {badge_bg};
            border-radius: {s(11)}px;
            border: none;
            padding: 0 {s(8)}px;
        """)

    def setText(self, _text: str):
        """Backward-compat — eski 'Offline: 3' format chaqirilsa raqamni ajratish."""
        try:
            n = int(_text.split(":")[-1].strip())
            self.set_count(n)
        except (ValueError, AttributeError):
            pass

    def setIcon(self, _icon):
        """Backward-compat no-op — ikona constructor'da o'rnatiladi."""
        pass

    def setStyleSheet(self, sheet: str):
        super().setStyleSheet(sheet)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):

    def __init__(self, api: FrappeAPI, active_cashier: dict = None):
        super().__init__()
        self.api = api
        self.opening_entry = None
        self.active_cashier = active_cashier   # {"name": ..., "full_name": ..., "pin_hash": ...}
        # Brand window title — config dan dinamik
        try:
            _b = (load_config().get("brand_name")
                  or load_config().get("company") or "").strip()
            if not _b:
                self.setWindowTitle("POS")
            else:
                self.setWindowTitle(_b if "POS" in _b.upper() else f"{_b} POS")
        except Exception:
            self.setWindowTitle("POS")

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

        # ── Brand block ──────────────────────────────
        self._brand_block = BrandBlock()
        top_bar.addWidget(self._brand_block)

        # Vertikal hairline separator
        def _hairline():
            line = QFrame()
            line.setFixedSize(s(1), s(32))
            line.setStyleSheet(f"background: {_SLATE_200}; border: none;")
            return line

        top_bar.addSpacing(s(12))
        top_bar.addWidget(_hairline())
        top_bar.addSpacing(s(14))

        config = load_config()
        company_name = config.get("company", "")
        cashier = config.get("cashier", config.get("user", ""))

        # ── Status pill ──────────────────────────────
        self._status_pill = StatusPill()
        top_bar.addWidget(self._status_pill)

        top_bar.addSpacing(s(10))

        # ── Company chip ─────────────────────────────
        self._company_chip = CompanyChip(company_name)
        top_bar.addWidget(self._company_chip)

        top_bar.addSpacing(s(18))

        # ── Cashier card (avatar + ism + rol chip) ──
        self._cashier_card = CashierCard()
        self._update_cashier_badge(cashier)
        top_bar.addWidget(self._cashier_card)

        top_bar.addStretch()

        # Tashqi tugmalar
        # Counter chips (Offline + To'lov kutilmoqda)
        self.offline_btn = CounterChip("Offline", icon_signal(_SLATE_500))
        self.offline_btn.clicked.connect(self.show_offline_queue)
        top_bar.addWidget(self.offline_btn)

        # TZ 4.2 — To'lov kutilmoqda
        self.pending_btn = CounterChip("To'lov kutilmoqda", icon_clock())
        self.pending_btn.clicked.connect(self.show_pending_orders)
        top_bar.addWidget(self.pending_btn)

        top_bar.addSpacing(s(6))
        top_bar.addWidget(_hairline())
        top_bar.addSpacing(s(6))

        self.add_sale_btn = _tb_btn("Yangi sotuv", "primary")
        self.add_sale_btn.setIcon(icon_plus())
        self.add_sale_btn.clicked.connect(self.add_new_sale_tab)
        top_bar.addWidget(self.add_sale_btn)

        self.history_btn = _tb_btn("Tarix", "secondary")
        self.history_btn.clicked.connect(self.show_history)
        top_bar.addWidget(self.history_btn)

        self.sync_btn = _tb_btn("Sinxronlash", "secondary")
        self.sync_btn.clicked.connect(self.start_sync)
        top_bar.addWidget(self.sync_btn)

        self.shifts_btn = _tb_btn("Kassa tarixi", "secondary")
        self.shifts_btn.setIcon(icon_clock())
        self.shifts_btn.clicked.connect(self.show_shifts_history)
        top_bar.addWidget(self.shifts_btn)

        self.close_shift_btn = _tb_btn("Kassa yopish", "danger")
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

        # Sales tabs — elite minimalist
        self.sales_tabs = QTabWidget()
        self.sales_tabs.setTabsClosable(True)
        self.sales_tabs.setMovable(True)
        self.sales_tabs.setDocumentMode(True)
        self.sales_tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sales_tabs.tabCloseRequested.connect(self.close_sale_tab)
        # TabBar font — Bold caps + letter-spacing (elite)
        _tab_font = QFont()
        _tab_font.setPixelSize(font(11))
        _tab_font.setWeight(QFont.Weight.Black)
        _tab_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        self.sales_tabs.tabBar().setFont(_tab_font)
        self.sales_tabs.setStyleSheet(f"""
            QTabWidget {{
                background: white;
                border: none;
            }}
            QTabWidget::pane {{
                border: none;
                background: white;
                top: -1px;
            }}
            QTabBar {{
                background: white;
                border: none;
                qproperty-drawBase: 0;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {_SLATE_500};
                padding: {s(10)}px {s(20)}px;
                margin: 0 {s(2)}px;
                border: none;
                border-bottom: 2px solid transparent;
                min-width: {s(80)}px;
                outline: none;
            }}
            QTabBar::tab:hover:!selected {{
                color: {_SLATE_900};
                border-bottom: 2px solid {_SLATE_200};
            }}
            QTabBar::tab:selected {{
                color: {_SLATE_900};
                border-bottom: 2px solid {_GOLD};
                background: transparent;
            }}
            QTabBar::scroller {{ width: 0px; }}
        """)
        # Default tab close tugmasi ('×') o'rniga custom elite tugmaslarni
        # `addTab` da o'rnatamiz (setTabButton).

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

        # ─ Inline Pending Orders Panel ───────────
        self.pending_panel = PendingOrdersWindow(self.api, self)
        self.pending_panel.setVisible(False)
        self.pending_panel.setMinimumHeight(s(320))
        self.pending_panel.setMaximumHeight(s(460))
        self.pending_panel.setStyleSheet("background: white; border-top: 2px solid #e2e8f0;")
        self.pending_panel.pay_requested.connect(self._on_pending_pay_requested)
        self.pending_panel.count_changed.connect(self._on_pending_count_changed)
        main_layout.addWidget(self.pending_panel)

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
        if hasattr(self, "_company_chip"):
            self._company_chip.set_company(company or "—")

    def _update_cashier_badge(self, cashier: str = ""):
        # active_cashier mavjud bo'lsa — uning full_name + role ni ko'rsat
        role = ""
        if self.active_cashier:
            display = (
                self.active_cashier.get("full_name")
                or self.active_cashier.get("name", "")
            )
            role = self.active_cashier.get("role") or "Kassir"
        elif cashier:
            # Fallback: ERPNext foydalanuvchi nomi (kassirlar yo'q holatda)
            display = (
                cashier.split("@")[0]
                .replace(".", " ")
                .replace("_", " ")
                .title()
            )
            role = "Kassir"
        else:
            display = "—"

        if hasattr(self, "_cashier_card"):
            self._cashier_card.set_cashier(display, role)

    def get_active_cashier_name(self) -> str:
        """Checkout uchun faol kassir ismini qaytarish."""
        if self.active_cashier:
            return self.active_cashier.get("full_name") or self.active_cashier.get("name", "")
        return ""

    def get_active_cashier_role(self) -> str:
        """Faol kassirning roli (Kassir/Ofitsant). Default: Kassir."""
        if self.active_cashier:
            return self.active_cashier.get("role") or "Kassir"
        return "Kassir"

    def get_active_cashier_user(self) -> str:
        """Faol kassirning Frappe User email'i — KPI uchun cashier/waiter field'iga."""
        if self.active_cashier:
            return self.active_cashier.get("user", "") or ""
        return ""

    def is_waiter(self) -> bool:
        return self.get_active_cashier_role() == "Ofitsant"

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

        # ── Phase 2: Real-time + ConnectionMonitor (TZ 4.4, 4.7) ──
        self._start_realtime_and_monitor()

        self._check_pos_opening()

    # ── Realtime + connection monitor (Phase 2) ──────
    def _start_realtime_and_monitor(self):
        try:
            self.realtime = RealtimeClient(self.api, parent=self)
            self.connection_monitor = ConnectionMonitor(
                self.api, realtime=self.realtime, parent=self,
            )

            # Realtime eventlari → handlerlar
            self.realtime.pending_order_created.connect(self._on_realtime_pending_changed)
            self.realtime.pending_order_updated.connect(self._on_realtime_pending_changed)
            self.realtime.pending_order_cancelled.connect(self._on_realtime_pending_changed)
            self.realtime.pending_order_paid.connect(self._on_realtime_pending_changed)
            self.realtime.table_occupied.connect(self._on_realtime_table_changed)
            self.realtime.table_freed.connect(self._on_realtime_table_changed)

            # Holat o'zgarganda — UI va overlay
            self.connection_monitor.state_changed.connect(self._on_connection_state_changed)

            # Ofitsant uchun overlay (faqat ofitsant rolida ko'rinadi)
            self.offline_overlay = OfflineBlockOverlay(self)
            self.offline_overlay.set_debug_info_provider(self._debug_info)
            self.offline_overlay.retry_requested.connect(self._on_overlay_retry)
            self.offline_overlay.hide()

            self.realtime.start()
            self.connection_monitor.start()
        except Exception as e:
            logger.error("Realtime / ConnectionMonitor boshlash xatosi: %s", e)

    def _on_realtime_pending_changed(self, payload: dict):
        """Pending order eventlari — panel va countni yangilash."""
        try:
            if hasattr(self, "pending_panel"):
                # Faqat panel ochiq bo'lsa to'liq yuklash, yopiq bo'lsa faqat count
                if self.pending_panel.isVisible():
                    self.pending_panel.load_pending()
                else:
                    self.pending_panel.refresh_count()
        except Exception as e:
            logger.debug("pending realtime handler xatosi: %s", e)

    def _on_realtime_table_changed(self, payload: dict):
        """Stol band/bo'shadi — TablePicker ochiq bo'lsa refresh."""
        try:
            picker = getattr(self, "_active_table_picker", None)
            if picker is not None and picker.isVisible():
                picker.refresh_tables()
        except Exception as e:
            logger.debug("table realtime handler xatosi: %s", e)

    def _on_connection_state_changed(self, state: str):
        """checking / online / offline. Ofitsant rolida overlay show/hide."""
        # Offline → online o'tishida pending count'ni qayta yuklash (uzilishda
        # o'tkazib yuborilgan eventlar uchun safety net)
        prev_state = getattr(self, "_last_conn_state", None)
        if state == STATE_ONLINE and prev_state in (STATE_OFFLINE, "checking"):
            self._refresh_pending_count_silent()
        self._last_conn_state = state

        # Top-bar status pill (elite)
        if hasattr(self, "_status_pill"):
            if state == STATE_ONLINE:
                self._status_pill.set_state("online")
            elif state == STATE_OFFLINE:
                self._status_pill.set_state("offline")
            else:
                self._status_pill.set_state("checking")

        # Ofitsant rolida — offline bo'lsa block overlay (TZ 4.7.3)
        if self.is_waiter() and hasattr(self, "offline_overlay"):
            if state == STATE_OFFLINE:
                self.offline_overlay.show_overlay()
            else:
                self.offline_overlay.hide_overlay()

    def _on_overlay_retry(self):
        """Ofitsant 'Qayta urinish' bossadi — darhol ping va realtime reconnect."""
        try:
            if hasattr(self, "realtime") and not self.realtime.is_connected:
                self.realtime.start()
            if hasattr(self, "connection_monitor"):
                self.connection_monitor.force_check()
        except Exception as e:
            logger.debug("retry xatosi: %s", e)

    def _debug_info(self) -> str:
        """Yordam dialog uchun diagnostika ma'lumotlari."""
        rt_ok = getattr(self, "realtime", None) and self.realtime.is_connected
        state = getattr(self, "connection_monitor", None) and self.connection_monitor.state
        return (
            f"FRAPPE_URL: {self.api.url}\n"
            f"SocketIO ulangan: {rt_ok}\n"
            f"Tarmoq holati: {state}\n"
            f"Foydalanuvchi: {self.get_active_cashier_name()} ({self.get_active_cashier_role()})"
        )

    # ── System monitor ───────────────────────────────
    def monitor_system(self):
        # Phase 2 da connectivity check ConnectionMonitor tomonidan amalga oshiriladi.
        self._update_offline_queue_count()
        # Pending count fallback — SocketIO event'siz holatlar uchun (yoki dastur
        # ochilganda mavjud Draft'lar ko'rinishi uchun).
        self._refresh_pending_count_silent()

    def _refresh_pending_count_silent(self):
        """Top-bar pending countni jim yangilash (panel ochiq emas paytda)."""
        try:
            if not hasattr(self, "pending_panel"):
                return
            # Role/name oxirgi marta o'rnatilgani saqlanadi panelda
            self.pending_panel.set_role_and_name(
                self.get_active_cashier_role(),
                self.get_active_cashier_name(),
                self.get_active_cashier_user(),
            )
            self.pending_panel.refresh_count()
        except Exception as e:
            logger.debug("Pending count silent refresh xatosi: %s", e)

    def _update_offline_queue_count(self):
        try:
            count = PendingInvoice.select().where(PendingInvoice.status == "Pending").count()
            if hasattr(self, "offline_btn") and hasattr(self.offline_btn, "set_count"):
                self.offline_btn.set_count(count)
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
            if hasattr(self, "pending_panel"):
                self.pending_panel.setVisible(False)
            self.offline_panel.setVisible(True)
            self.offline_panel.load_pending()

    def add_new_sale_tab(self):
        tab_count = self.sales_tabs.count()
        new_cart = CartWidget()
        new_cart.checkout_requested.connect(self.on_checkout)
        new_cart.save_requested.connect(self.on_save_order)            # TZ 4.2
        new_cart.table_pick_requested.connect(lambda: self.open_table_picker(new_cart))
        new_cart.set_role(self.get_active_cashier_role())               # TZ 4.3
        new_cart.apply_settings()
        tab_index = self.sales_tabs.addTab(
            new_cart, f"SOTUV {tab_count + 1}"
        )
        # Elite custom close tugmasi — slate-400 'x', hover red tint
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(28), s(28))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_SLATE_400};
                font-size: {font(13)}px;
                font-weight: 700;
                border: 1px solid transparent;
                border-radius: {s(14)}px;
                outline: none;
                padding: 0;
            }}
            QPushButton:hover {{
                background: #fef2f2;
                color: #b91c1c;
                border: 1px solid #fecaca;
            }}
            QPushButton:pressed {{ background: #fee2e2; }}
        """)
        close_btn.clicked.connect(
            lambda _, w=new_cart: self.close_sale_tab(self.sales_tabs.indexOf(w))
        )
        from PyQt6.QtWidgets import QTabBar as _QTabBar
        self.sales_tabs.tabBar().setTabButton(
            tab_index, _QTabBar.ButtonPosition.RightSide, close_btn,
        )
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
        order_data["active_cashier_role"] = self.get_active_cashier_role()
        order_data["active_cashier_user"] = self.get_active_cashier_user()
        dialog = CheckoutWindow(self, order_data, self.api)
        dialog.checkout_completed.connect(self.on_checkout_completed)
        dialog.exec()

    def on_checkout_completed(self):
        active_cart = self.sales_tabs.currentWidget()
        if active_cart:
            active_cart.clear_cart()
        self._update_offline_queue_count()
        # Pending count yangilash
        if hasattr(self, "pending_panel"):
            self.pending_panel.load_pending()

    # ── TZ 4.2: To'lovsiz saqlash ─────────────────
    def on_save_order(self, order_data: dict):
        order_data["active_cashier"] = self.get_active_cashier_name()
        order_data["active_cashier_role"] = self.get_active_cashier_role()
        order_data["active_cashier_user"] = self.get_active_cashier_user()
        # Print payti uchun order_data ni saqlab qo'yamiz (worker async tugagach kerak)
        self._last_save_order_data = dict(order_data)
        self._save_worker = SaveOrderWorker(
            order_data, self.api, role=self.get_active_cashier_role()
        )
        self._save_worker.result_ready.connect(self._on_save_done)
        self._save_worker.start()
        # UI feedback
        self.status_label.setText("Buyurtma saqlanmoqda...")

    def _on_save_done(self, success: bool, message: str, invoice_name: str):
        self.status_label.setText(message)
        if success:
            # KOT (oshxona chek) chop etish — mijoz cheki YO'Q (hali to'lov bo'lmagan)
            self._print_kot_for_save(invoice_name)

            InfoDialog(self, "Saqlandi", message, kind="success").exec()
            active_cart = self.sales_tabs.currentWidget()
            if active_cart:
                active_cart.clear_cart()
            # Pending list yangilash
            if hasattr(self, "pending_panel"):
                self.pending_panel.load_pending()
        else:
            # Ofitsant rolida tarmoq xatosi bo'lsa Phase 2 da blok overlay chiqadi
            InfoDialog(self, "Xatolik", message, kind="error").exec()

    def _print_kot_for_save(self, invoice_name: str = ""):
        """Saqlash flowida faqat oshxona (production) cheklarini chop etish.

        Mijoz cheki to'lov paytida chiqadi (TZ 4.2 — KOT darhol, mijoz cheki keyin).
        Ofitsant rolida ham KOT darhol oshxonaga ketishi kerak.
        """
        order_data = getattr(self, "_last_save_order_data", None)
        if not order_data:
            return
        try:
            from core.printer import print_receipt
            results = print_receipt(
                self, order_data, [],
                include_customer=False,
                include_production=True,
            )
            failed = [k for k, v in results.items() if not v]
            if failed:
                logger.warning("KOT printerlar chop etilmadi: %s", ", ".join(failed))
                names = ", ".join(failed)
                InfoDialog(
                    self, "Oshxona printeri ulanmagan",
                    f"Buyurtma saqlandi ✓\n\n"
                    f"Lekin oshxona printeri ({names}) chop etmadi.\n"
                    f"Iltimos, buyurtmani oshxonaga og'zaki yetkazib bering "
                    f"yoki printerni tekshiring.",
                    kind="info",
                    icon="🖨️",
                ).exec()
        except Exception as e:
            logger.error("KOT chop etish xatosi (save): %s", e)
        finally:
            self._last_save_order_data = None

    # ── TZ 4.1: Stol picker ─────────────────────
    def open_table_picker(self, cart: CartWidget):
        cfg = load_config()
        current_tbl = (cart.selected_table or {}).get("name", "")
        dlg = TablePickerDialog(
            self, self.api,
            current_table=current_tbl,
            active_cashier=self.get_active_cashier_name(),
            active_cashier_role=self.get_active_cashier_role(),
        )
        # Realtime handler dialogga ulanishi uchun reference saqlash
        self._active_table_picker = dlg
        try:
            if dlg.exec():
                if dlg.selected_table:
                    cart.set_selected_table(dlg.selected_table)
        finally:
            self._active_table_picker = None

    # ── TZ 4.2: To'lov kutilmoqda panel ──────────
    def show_pending_orders(self):
        visible = self.pending_panel.isVisible()
        if visible:
            self.pending_panel.setVisible(False)
            return
        # Boshqa panellarni yopish
        self.history_panel.setVisible(False)
        self.shifts_panel.setVisible(False)
        self.offline_panel.setVisible(False)
        # Role + name + user set (KPI: kim cancel qildi, kim to'lov qildi)
        self.pending_panel.set_role_and_name(
            self.get_active_cashier_role(),
            self.get_active_cashier_name(),
            self.get_active_cashier_user(),
        )
        self.pending_panel.setVisible(True)
        self.pending_panel.load_pending()

    def _on_pending_pay_requested(self, detail: dict):
        """Pending listdan 💰 To'lov bossadi — CheckoutWindow ochiladi."""
        order_data = {
            "items": [
                {
                    "item_code": i.get("item_code", ""),
                    "name": i.get("item_name", ""),
                    "price": float(i.get("rate", 0)),
                    "qty": int(i.get("qty", 0)),
                    "currency": "UZS",
                }
                for i in detail.get("items", [])
            ],
            "total_amount": float(detail.get("grand_total") or detail.get("rounded_total") or 0),
            "order_type": detail.get("order_type", ""),
            "ticket_number": detail.get("custom_ticket_number", ""),
            "restaurant_table": detail.get("restaurant_table", ""),
            "customer": detail.get("customer", ""),
            "comment": detail.get("custom_comments", ""),
            "active_cashier": self.get_active_cashier_name(),
            "active_cashier_role": self.get_active_cashier_role(),
            "active_cashier_user": self.get_active_cashier_user(),
            "existing_invoice": detail.get("name", ""),     # CheckoutWorker buni inobatga oladi (Phase 3)
        }
        dialog = CheckoutWindow(self, order_data, self.api)
        dialog.checkout_completed.connect(self.on_checkout_completed)
        dialog.exec()

    def _on_pending_count_changed(self, count: int):
        """Top-bar tugmasini yangilash."""
        if hasattr(self, "pending_btn") and hasattr(self.pending_btn, "set_count"):
            self.pending_btn.set_count(int(count))

    # ── History / Shifts ─────────────────────────────
    def show_shifts_history(self):
        visible = self.shifts_panel.isVisible()
        if visible:
            self.shifts_panel.setVisible(False)
        else:
            self.history_panel.setVisible(False)
            self.offline_panel.setVisible(False)
            if hasattr(self, "pending_panel"):
                self.pending_panel.setVisible(False)
            self.shifts_panel.setVisible(True)
            self.shifts_panel.load_shifts()

    def show_history(self):
        self.shifts_panel.setVisible(False)
        self.offline_panel.setVisible(False)
        if hasattr(self, "pending_panel"):
            self.pending_panel.setVisible(False)
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
        self._sync_spinner.stop()
        cfg = load_config()
        self._update_company_badge(cfg.get("company", ""), cfg.get("pos_profile", ""))
        self._update_cashier_badge(cfg.get("cashier", cfg.get("user", "")))
        # POS Profile dan brand_name yangilangan bo'lishi mumkin — top bar
        # brand'ni qayta render qilamiz
        if hasattr(self, "_brand_block"):
            self._brand_block.refresh()
        # Window title ham brand'ga moslashtirish (foydalanuvchiga clarity)
        try:
            brand = (cfg.get("brand_name") or cfg.get("company") or "").strip()
            if not brand:
                self.setWindowTitle("POS")
            else:
                self.setWindowTitle(
                    brand if "POS" in brand.upper() else f"{brand} POS"
                )
        except Exception:
            pass
        self._apply_pos_settings(cfg)
        if success:
            # Sidebar kategoriyalarini va itemlarni yangilash
            self.item_browser.load_categories()
            self.item_browser.load_items()
            # Birinchi sync tugagach pending count yuklab top-bar tugmasini
            # to'g'ri ko'rsatamiz (avval 0 turardi, SocketIO event'lar yangi
            # zakazlar uchun keladi).
            self._refresh_pending_count_silent()
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

        # Phase 3 TZ #16: pending Draft tekshiruvi
        if not self._check_pending_before_closing():
            return

        dlg = ConfirmDialog(
            self, "Kassani yopish",
            "Kassani yopmoqchimisiz?\nBarcha to'lovlar hisoblanadi.",
            icon="🔒", yes_text="Ha, yopish", yes_color="#dc2626",
        )
        dlg.exec()
        if not dlg.result_accepted:
            return

        # Orphan stollarni tozalash (background, blocking emas)
        self._cleanup_orphan_tables_async()

        closing_dlg = PosClosingDialog(self, self.api, self.opening_entry)
        closing_dlg.closing_completed.connect(self._on_pos_closed)
        closing_dlg.exec()

    def _check_pending_before_closing(self) -> bool:
        """Pending Draft buyurtmalar bo'lsa — ogohlantirish dialog.

        Returns:
            True — davom etish, False — bekor qilish.
        """
        try:
            ok, counts = self.api.call_method(
                "ury.ury_pos.api.getPendingOrderCounts",
                {"only_mine": 0, "mine_cashier_name": ""},
            )
            total = int(counts.get("all", 0)) if (ok and isinstance(counts, dict)) else 0
        except Exception as e:
            logger.debug("Pending count tekshirish xatosi: %s", e)
            total = 0

        if total == 0:
            return True

        # Ogohlantirish
        dlg = ConfirmDialog(
            self, "To'lov kutilayotgan buyurtmalar",
            f"{total} ta to'lanmagan buyurtma bor.\n\n"
            f"Yopishdan oldin hammasini hal qiling yoki\n"
            f"majburiy yopish (force) variantini tanlang.",
            icon="⚠️",
            yes_text="Ko'rib chiqish",
            yes_color="#0ea5e9",
            no_text="Bekor",
        )
        dlg.exec()
        if dlg.result_accepted:
            # Pending panelni ochish
            self.show_pending_orders()
        return False

    def _cleanup_orphan_tables_async(self):
        """Background da orphan stollarni tozalash (TZ 4.6.3)."""
        class _Worker(QThread):
            done = pyqtSignal(int)

            def __init__(self, api):
                super().__init__()
                self.api = api

            def run(self):
                try:
                    ok, resp = self.api.call_method(
                        "ury.ury_pos.api.cleanupOrphanTables"
                    )
                    if ok and isinstance(resp, dict):
                        self.done.emit(int(resp.get("freed_count", 0)))
                    else:
                        self.done.emit(0)
                except Exception:
                    self.done.emit(0)

        self._orphan_worker = _Worker(self.api)
        self._orphan_worker.done.connect(self._on_orphan_cleanup_done)
        self._orphan_worker.start()

    def _on_orphan_cleanup_done(self, freed: int):
        if freed > 0:
            logger.info("Orphan stollar tozalandi: %d ta", freed)
            self.status_label.setText(f"Orphan stollar tozalandi: {freed} ta")

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
    def resizeEvent(self, event):
        # Phase 2: ofitsant block overlay butun oynani egallasin
        if hasattr(self, 'offline_overlay'):
            self.offline_overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    def closeEvent(self, event):
        # 1. Timerni to'xtatish — yangi worker yaratilmasin
        if hasattr(self, 'monitor_timer'):
            self.monitor_timer.stop()

        # 1b. ConnectionMonitor va SocketIO ni to'xtatish (Phase 2)
        if hasattr(self, 'connection_monitor'):
            try:
                self.connection_monitor.stop()
            except Exception:
                pass
        if hasattr(self, 'realtime'):
            try:
                self.realtime.stop()
            except Exception:
                pass

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
