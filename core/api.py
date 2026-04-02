import json
import threading
import requests
from core.config import load_config
from core.logger import get_logger
from core.constants import API_TIMEOUT_SHORT, API_TIMEOUT_DEFAULT

logger = get_logger(__name__)


class FrappeAPI:
    def __init__(self):
        self._sessions_lock = threading.Lock()
        self._sessions: dict = {}          # thread_id → requests.Session
        self._shared_cookies = {}
        self._login_lock = threading.Lock()
        self._aborting = False
        self.reload_config()

    def _get_session(self) -> requests.Session:
        """Har bir thread uchun alohida requests.Session qaytaradi.
        Shared cookie'larni yangi session'ga ko'chiradi."""
        if self._aborting:
            raise requests.exceptions.ConnectionError("API yopilmoqda")
        tid = threading.get_ident()
        with self._sessions_lock:
            if tid not in self._sessions:
                session = requests.Session()
                session.headers.update({"Expect": ""})
                if self._shared_cookies:
                    session.cookies.update(self._shared_cookies)
                self._sessions[tid] = session
            return self._sessions[tid]

    def reload_config(self):
        """Config ni qayta yuklash va barcha sessionlarni tozalash (FAQAT logout uchun)."""
        config = load_config()
        self.url = config.get("url", "").rstrip("/")
        self.site = config.get("site", "")
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        self._shared_cookies = {}
        self._aborting = False
        with self._sessions_lock:
            for s in self._sessions.values():
                try:
                    s.close()
                except Exception:
                    pass
            self._sessions.clear()

    def reload_settings(self):
        """Config ni qayta o'qish — session va cookie'larni SAQLAB qoladi.
        Login dan keyin chaqirish uchun (sync, pos_profile yangilanishi)."""
        config = load_config()
        self.url = config.get("url", "").rstrip("/")
        self.site = config.get("site", "")
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        # _shared_cookies va _sessions o'ZGARTIRILMAYDI

    def abort_all(self):
        """Barcha aktiv HTTP ulanishlarni to'xtatish (app yopilganda).

        Barcha thread'lardagi bloklangan session.get/post ni darhol
        ConnectionError bilan yakunlaydi — thread'lar except blokida
        ushlab, o'z-o'zidan chiqib ketadi.
        """
        self._aborting = True
        with self._sessions_lock:
            for session in self._sessions.values():
                try:
                    session.close()
                except Exception:
                    pass
            self._sessions.clear()

    def get_headers(self, is_json=True) -> dict:
        headers = {
            "Accept": "application/json",
            "Expect": "",
        }

        # Multi-site bench uchun sayt nomini header'da yuboramiz
        if self.site:
            headers["X-Frappe-Site-Name"] = self.site

        if self.api_key and self.api_secret:
            headers["Authorization"] = f"token {self.api_key}:{self.api_secret}"

        if is_json:
            headers["Content-Type"] = "application/json"
        return headers

    def is_configured(self) -> bool:
        return bool(self.url and ((self.api_key and self.api_secret) or (self.user and self.password)))

    def login(self, url: str, usr: str, pwd: str, site: str = "") -> tuple[bool, str]:
        """Username va Password orqali login qilish."""
        login_url = f"{url.rstrip('/')}/api/method/login"
        payload = {
            "usr": usr,
            "pwd": pwd
        }
        headers = {"Accept": "application/json", "Expect": ""}
        if site:
            headers["X-Frappe-Site-Name"] = site

        session = self._get_session()
        try:
            response = session.post(login_url, data=payload, headers=headers, timeout=API_TIMEOUT_DEFAULT)
            if response.status_code == 200 or (
                response.status_code != 200
                and response.json().get("message") == "Logged In"
            ):
                logger.info("Login muvaffaqiyatli: %s (User: %s)", url, usr)
                self.url = url.rstrip("/")
                self.user = usr
                self.password = pwd
                self.site = site
                # Cookie'larni oddiy dict sifatida saqlash (thread-safe)
                self._shared_cookies = {c.name: c.value for c in session.cookies}
                return True, "Success"
            else:
                logger.warning("Login xatosi: %d - %s", response.status_code, response.text[:200])
                return False, "Login yoki parol noto'g'ri"
        except (json.JSONDecodeError, ValueError):
            # JSON parse xatosi — lekin status 200 bo'lishi mumkin
            if response.status_code == 200:
                self.url = url.rstrip("/")
                self.user = usr
                self.password = pwd
                self.site = site
                self._shared_cookies = {c.name: c.value for c in session.cookies}
                return True, "Success"
            return False, "Login yoki parol noto'g'ri"
        except requests.exceptions.RequestException as e:
            logger.error("Login ulanish xatosi: %s", e)
            return False, "Server bilan aloqa o'rnatib bo'lmadi"

    def _auto_relogin(self) -> bool:
        """Thread-safe avtomatik qayta login.
        Faqat bitta thread login qiladi, qolganlar cookie oladi."""
        with self._login_lock:
            # Boshqa thread allaqachon login qilgan bo'lishi mumkin — cookie'ni tekshir
            cookies = self._shared_cookies
            if cookies:
                session = self._get_session()
                session.cookies.update(cookies)
                return True
            # Hali hech kim login qilmagan — biz qilamiz
            if self.user and self.password:
                success, _ = self.login(self.url, self.user, self.password, self.site)
                return success
            return False

    def ping(self, url: str, api_key: str, api_secret: str) -> tuple[bool, str]:
        test_url = f"{url.rstrip('/')}/api/method/frappe.auth.get_logged_user"
        headers = {
            "Authorization": f"token {api_key}:{api_secret}",
            "Accept": "application/json",
        }
        if self.site:
            headers["X-Frappe-Site-Name"] = self.site

        try:
            response = requests.get(test_url, headers=headers, timeout=API_TIMEOUT_DEFAULT)
            if response.status_code == 200:
                return True, "Success"
            else:
                return False, f"Error: {response.status_code}"
        except Exception as e:
            logger.error("Ping xatosi: %s", e)
            return False, str(e)

    def fetch_data(self, doctype: str, fields: str = '["*"]', filters=None, limit: int = 0):
        if not self.is_configured():
            return None

        endpoint = f"{self.url}/api/resource/{doctype}"
        params = {"fields": fields, "limit_page_length": limit}

        if filters:
            if isinstance(filters, dict):
                filter_list = [[doctype, k, "=", v] for k, v in filters.items()]
                params["filters"] = json.dumps(filter_list)
            elif isinstance(filters, str):
                params["filters"] = filters

        session = self._get_session()
        try:
            response = session.get(
                endpoint,
                headers=self.get_headers(is_json=False),
                params=params,
                timeout=API_TIMEOUT_SHORT,
            )

            if response.status_code == 403 and self._auto_relogin():
                session = self._get_session()
                response = session.get(
                    endpoint,
                    headers=self.get_headers(is_json=False),
                    params=params,
                    timeout=API_TIMEOUT_SHORT,
                )

            if response.status_code == 200:
                return response.json().get("data", [])
            return None
        except Exception as e:
            logger.error("fetch_data %s xatosi: %s", doctype, e)
            return None

    def call_method(self, method: str, data=None) -> tuple[bool, object]:
        if not self.is_configured():
            return False, "API sozlanmagan"

        endpoint = f"{self.url}/api/method/{method}"
        session = self._get_session()
        try:
            headers = self.get_headers(is_json=True)

            if data is not None:
                response = session.post(endpoint, headers=headers, json=data, timeout=API_TIMEOUT_DEFAULT)
            else:
                response = session.get(endpoint, headers=headers, timeout=API_TIMEOUT_DEFAULT)

            if response.status_code == 403 and self._auto_relogin():
                session = self._get_session()
                headers = self.get_headers(is_json=True)
                if data is not None:
                    response = session.post(endpoint, headers=headers, json=data, timeout=API_TIMEOUT_DEFAULT)
                else:
                    response = session.get(endpoint, headers=headers, timeout=API_TIMEOUT_DEFAULT)

            if response.status_code == 200:
                return True, response.json().get("message", response.json())
            else:
                logger.error("call_method %s — HTTP %d: %s", method, response.status_code, response.text[:500])
                return False, f"Server xatosi ({response.status_code})"
        except Exception as e:
            logger.error("call_method %s xatosi: %s", method, e)
            return False, str(e)
