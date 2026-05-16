"""Tarmoq holatini real-time kuzatish — Desktop POS Phase 2 (TZ 4.7).

State machine:
    ONLINE    — server bilan aloqa bor (SocketIO ulangan yoki HTTP ping OK)
    OFFLINE   — aloqa yo'q (3 sek grace period o'tdi)
    CHECKING  — birinchi tekshiruv jarayonida

Algoritm:
    1. SocketIO `connect` event → ONLINE (darhol)
    2. SocketIO `disconnect` → 3 sek grace timer ishga tushadi
    3. Grace ichida `connect` bo'lsa — bekor qilinadi, ONLINE saqlanadi
    4. Grace o'tsa va hali OFFLINE — state OFFLINE ga o'tadi
    5. Har 10 sek HTTP ping (fallback) — SocketIO yo'q bo'lsa ham ishlaydi
"""
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.api import FrappeAPI
from core.logger import get_logger
from core.realtime import RealtimeClient

logger = get_logger(__name__)


STATE_CHECKING = "checking"
STATE_ONLINE = "online"
STATE_OFFLINE = "offline"

GRACE_PERIOD_MS = 3000      # SocketIO disconnect dan keyin necha ms kutish
PING_INTERVAL_MS = 10000    # HTTP ping har 10 sek


class _PingWorker(QThread):
    """Light HTTP ping — `frappe.auth.get_logged_user` chaqirib tekshiradi."""

    result_ready = pyqtSignal(bool)

    def __init__(self, api: FrappeAPI):
        super().__init__()
        self.api = api

    def run(self):
        try:
            ok, _ = self.api.call_method("frappe.auth.get_logged_user")
            self.result_ready.emit(bool(ok))
        except Exception:
            self.result_ready.emit(False)


class ConnectionMonitor(QObject):
    """Tarmoq holatini kuzatuvchi.

    Signals:
        state_changed(str): 'online' / 'offline' / 'checking'
    """

    state_changed = pyqtSignal(str)

    def __init__(self, api: FrappeAPI, realtime: RealtimeClient = None, parent=None):
        super().__init__(parent)
        self.api = api
        self.realtime = realtime
        self._state = STATE_CHECKING

        # Grace timer — disconnect dan keyin OFFLINE deb e'lon qilishdan oldin kutish
        self._grace_timer = QTimer(self)
        self._grace_timer.setSingleShot(True)
        self._grace_timer.setInterval(GRACE_PERIOD_MS)
        self._grace_timer.timeout.connect(self._on_grace_expired)

        # HTTP ping fallback (SocketIO bo'lmasa ham aloqa borligini bilish)
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._start_ping)
        self._ping_worker = None

        if realtime is not None:
            realtime.connected_changed.connect(self._on_realtime_connected_changed)

    # ── Public ─────────────────────────────────────────
    @property
    def state(self) -> str:
        return self._state

    @property
    def is_online(self) -> bool:
        return self._state == STATE_ONLINE

    def start(self):
        """Monitoringni boshlash."""
        self._set_state(STATE_CHECKING)
        self._ping_timer.start()
        self._start_ping()  # darhol bitta ping

    def stop(self):
        self._ping_timer.stop()
        self._grace_timer.stop()
        if self._ping_worker and self._ping_worker.isRunning():
            self._ping_worker.quit()
            self._ping_worker.wait(1000)

    def force_check(self):
        """Foydalanuvchi "Qayta urinish" tugmasi bossadi — darhol ping."""
        self._grace_timer.stop()
        self._start_ping()

    # ── Realtime callbacks ─────────────────────────────
    def _on_realtime_connected_changed(self, is_connected: bool):
        if is_connected:
            self._grace_timer.stop()
            self._set_state(STATE_ONLINE)
        else:
            # Darhol OFFLINE deb e'lon qilmaymiz — grace period
            if self._state == STATE_ONLINE:
                self._grace_timer.start()

    def _on_grace_expired(self):
        """Grace period o'tdi. Hali ulanish yo'q — HTTP ping bilan tekshiramiz."""
        if self.realtime and self.realtime.is_connected:
            self._set_state(STATE_ONLINE)
            return
        self._start_ping()

    # ── HTTP ping ──────────────────────────────────────
    def _start_ping(self):
        if self._ping_worker and self._ping_worker.isRunning():
            return
        self._ping_worker = _PingWorker(self.api)
        self._ping_worker.result_ready.connect(self._on_ping_result)
        self._ping_worker.start()

    def _on_ping_result(self, ok: bool):
        if ok:
            self._set_state(STATE_ONLINE)
        else:
            # SocketIO ham ulanmagan bo'lsa — to'liq OFFLINE
            if not (self.realtime and self.realtime.is_connected):
                self._set_state(STATE_OFFLINE)

    # ── State ──────────────────────────────────────────
    def _set_state(self, new_state: str):
        if new_state == self._state:
            return
        self._state = new_state
        logger.info("Tarmoq holati: %s", new_state)
        self.state_changed.emit(new_state)
