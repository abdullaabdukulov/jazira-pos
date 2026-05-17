"""Frappe SocketIO klienti — Desktop POS Phase 2.

Server tomonda `frappe.publish_realtime(event, data)` chaqirilganda, ushbu
modul orqali POS GUI thread'iga Qt signali sifatida yetkaziladi.

Channels (TZ 4.4):
    pending_order_created    — yangi Draft POS Invoice yaratildi
    pending_order_updated    — Draft invoice o'zgardi
    pending_order_cancelled  — Draft cancel/delete qilindi
    pending_order_paid       — Draft → Paid (submit)
    table_occupied           — URY Table band bo'ldi
    table_freed              — URY Table bo'shadi

Qo'llanilishi:
    rt = RealtimeClient(api)
    rt.pending_order_created.connect(handler_fn)
    rt.start()
    ...
    rt.stop()
"""
from urllib.parse import urlparse, urlunparse

import socketio
from PyQt6.QtCore import QObject, pyqtSignal

from core.api import FrappeAPI
from core.logger import get_logger

logger = get_logger(__name__)


REALTIME_EVENTS = (
    "pending_order_created",
    "pending_order_updated",
    "pending_order_cancelled",
    "pending_order_paid",
    "table_occupied",
    "table_freed",
)


def derive_socketio_url(frappe_url: str, port: int = 9000) -> str:
    """Frappe URLdan SocketIO URLini hisoblash.

    Variants:
    - Lokal dev: `http://host:8000` → `http://host:9000`
    - Cloud HTTPS: `https://example.com` → `https://example.com` (nginx proxylaydi)
    - Cloud HTTP standard port: `http://example.com` → `http://example.com`

    Frappe production deploymentlari (nginx reverse proxy) `/socket.io/` ni
    asosiy HTTPS port (443) orqali yo'naltiradi. Faqat lokal dev da
    alohida 9000 portga ulanish kerak.
    """
    if not frappe_url:
        return ""
    p = urlparse(frappe_url)
    host = p.hostname or "127.0.0.1"
    scheme = p.scheme or "http"
    explicit_port = p.port

    # Standard web ports (cloud / production) — alohida port qo'shilmaydi
    if explicit_port is None:
        # https://example.com yoki http://example.com — same origin
        return urlunparse((scheme, host, "", "", "", ""))

    if explicit_port in (80, 443):
        # http://example.com:80 yoki https://example.com:443 — same origin
        return urlunparse((scheme, host, "", "", "", ""))

    # Lokal dev — 8000 yoki boshqa explicit port → 9000 ga o'tish
    return urlunparse((scheme, f"{host}:{port}", "", "", "", ""))


class RealtimeClient(QObject):
    """Frappe SocketIO bog'lanishi — Qt signallari orqali eventlarni
    GUI thread'ga yetkazadi.

    Avto-reconnect ishlaydi: socketio.Client(reconnection=True, ...).
    """

    pending_order_created = pyqtSignal(dict)
    pending_order_updated = pyqtSignal(dict)
    pending_order_cancelled = pyqtSignal(dict)
    pending_order_paid = pyqtSignal(dict)
    table_occupied = pyqtSignal(dict)
    table_freed = pyqtSignal(dict)

    connected_changed = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, api: FrappeAPI, url: str = "", parent=None):
        super().__init__(parent)
        self.api = api
        self.url = url or derive_socketio_url(api.url)
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=3,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False,
        )
        self._is_connected = False
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.event
        def connect():
            self._is_connected = True
            logger.info("SocketIO ulandi: %s", self.url)
            self.connected_changed.emit(True)

        @self.sio.event
        def disconnect():
            self._is_connected = False
            logger.warning("SocketIO uzildi")
            self.connected_changed.emit(False)

        @self.sio.event
        def connect_error(data):
            msg = f"SocketIO connect_error: {data}"
            logger.error(msg)
            self.error.emit(str(data))

        # Server tomon publish_realtime(event, data) → mana shu handler.
        # Frappe SocketIO standard payload: {"event": ..., "message": ...}
        @self.sio.on("*")
        def catch_all(event, data):
            if event in REALTIME_EVENTS:
                payload = self._extract_payload(data)
                self._dispatch(event, payload)

        for evt in REALTIME_EVENTS:
            # Eski Frappe versiyalari to'g'ridan-to'g'ri event nomi bilan
            # emit qilishi mumkin (catch_all qoplaydi), lekin eksplicit ham qo'shamiz
            self.sio.on(evt, lambda data, _evt=evt: self._dispatch(
                _evt, self._extract_payload(data)
            ))

    @staticmethod
    def _extract_payload(data):
        if isinstance(data, dict) and "message" in data:
            return data["message"] if isinstance(data["message"], dict) else {"data": data["message"]}
        if isinstance(data, dict):
            return data
        return {"data": data}

    def _dispatch(self, event: str, payload: dict):
        sig = getattr(self, event, None)
        if sig is not None:
            try:
                sig.emit(payload)
            except Exception as e:
                logger.error("Signal emit xatosi (%s): %s", event, e)

    def _build_auth(self):
        """Frappe sid cookie'sini olib auth header tayyorlash."""
        cookies = getattr(self.api, "_shared_cookies", {}) or {}
        sid = cookies.get("sid", "")
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return sid, cookie_str

    def start(self):
        """Ulanish — alohida thread'da ishlaydi (socketio.Client o'zi
        background thread yaratadi)."""
        if not self.url:
            logger.warning("SocketIO URL bo'sh — ulanilmadi")
            return
        if self.sio.connected:
            return

        sid, cookie_str = self._build_auth()
        if not sid:
            logger.warning("sid cookie topilmadi — SocketIO bog'lanmaydi")
            return

        logger.info("SocketIO connect → %s (path=/socket.io/, sid=%s...)",
                    self.url, sid[:8] if sid else "")

        try:
            # Frappe Realtime: namespace ni explicit '/' beramiz.
            # socketio_path Frappe nginx config'iga mos keladi.
            self.sio.connect(
                self.url,
                headers={"Cookie": cookie_str} if cookie_str else {},
                auth={"sid": sid},
                transports=["websocket", "polling"],
                socketio_path="/socket.io/",
                wait=False,
            )
        except Exception as e:
            logger.error("SocketIO start xatosi: %s (URL=%s)", e, self.url)
            self.error.emit(str(e))

    def stop(self):
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception as e:
            logger.debug("SocketIO stop xatosi: %s", e)

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self.sio.connected
