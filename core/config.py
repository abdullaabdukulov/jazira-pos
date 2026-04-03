import json
import os
import sys
import threading
from dotenv import load_dotenv
from core.logger import get_logger

logger = get_logger(__name__)

# PyInstaller frozen rejimda exe papkasini ishlatish
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")


_config_lock = threading.Lock()

load_dotenv(ENV_FILE)


def load_config() -> dict:
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
        except (json.JSONDecodeError, PermissionError) as e:
            logger.error("config.json o'qishda xatolik: %s", e)

    # Defaults and Env overrides
    config["url"] = os.getenv("FRAPPE_URL", config.get("url", "https://jazira.erpcontrol.uz/")).rstrip("/")
    config["site"] = os.getenv("FRAPPE_SITE", config.get("site", ""))
    config["api_key"] = os.getenv("FRAPPE_API_KEY", config.get("api_key", ""))
    config["api_secret"] = os.getenv("FRAPPE_API_SECRET", config.get("api_secret", ""))
    config["user"] = os.getenv("FRAPPE_USER", config.get("user", ""))
    config["password"] = os.getenv("FRAPPE_PASSWORD", config.get("password", ""))

    return config


def save_config(data: dict):
    with _config_lock:
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, PermissionError):
                pass

        # config.json ga yozilmasligi kerak bo'lgan kalitlar
        # url, site, user, password, api_key, api_secret → .env da saqlanadi
        excluded_keys = {"url", "site", "user", "password", "api_key", "api_secret"}
        clean_data = {k: v for k, v in data.items() if k not in excluded_keys}
        config.update(clean_data)

        # Eski qoldiqlarni tozalash
        for key in excluded_keys:
            config.pop(key, None)

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except PermissionError:
            logger.error("config.json yozishda ruxsat yo'q")



def save_credentials(url: str, user: str, password: str, site: str = "",
                     api_key: str = "", api_secret: str = ""):
    env_lines = [
        f"FRAPPE_URL={url}\n",
        f"FRAPPE_USER={user}\n",
        f"FRAPPE_PASSWORD={password}\n",
        f"FRAPPE_SITE={site}\n",
        f"FRAPPE_API_KEY={api_key}\n",
        f"FRAPPE_API_SECRET={api_secret}\n",
    ]
    try:
        with open(ENV_FILE, "w") as f:
            f.writelines(env_lines)
        load_dotenv(ENV_FILE, override=True)
        logger.info("Credentials .env fayliga saqlandi")
    except PermissionError:
        logger.error(".env fayliga yozishda ruxsat yo'q")


def clear_credentials():
    if os.path.exists(ENV_FILE):
        try:
            os.remove(ENV_FILE)
            logger.info(".env fayli o'chirildi (logout)")
        except Exception as e:
            logger.error(".env faylini o'chirishda xatolik: %s", e)

    os.environ.pop("FRAPPE_URL", None)
    os.environ.pop("FRAPPE_USER", None)
    os.environ.pop("FRAPPE_PASSWORD", None)
    os.environ.pop("FRAPPE_SITE", None)
    os.environ.pop("FRAPPE_API_KEY", None)
    os.environ.pop("FRAPPE_API_SECRET", None)


# ── PIN autentifikatsiya ──────────────────────────────
import hashlib


def _pin_hash(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def save_pin(pin: str):
    save_config({"pin_hash": _pin_hash(pin)})


def verify_pin(pin: str) -> bool:
    stored = load_config().get("pin_hash", "")
    return bool(stored) and _pin_hash(pin) == stored


def has_pin() -> bool:
    return bool(load_config().get("pin_hash"))


def has_saved_credentials() -> bool:
    cfg = load_config()
    return bool(cfg.get("user")) and bool(cfg.get("password")) and bool(cfg.get("url"))


# ── Ko'p kassir boshqaruvi ────────────────────────────

def get_cashiers() -> list:
    return load_config().get("cashiers", [])


def save_cashier(name: str, pin: str):
    """Kassirni qo'shish yoki PIN ni yangilash."""
    cashiers = [c for c in get_cashiers() if c.get("name", "").lower() != name.lower()]
    cashiers.append({"name": name, "pin_hash": _pin_hash(pin)})
    save_config({"cashiers": cashiers})


def delete_cashier(name: str):
    cashiers = [c for c in get_cashiers() if c.get("name", "").lower() != name.lower()]
    save_config({"cashiers": cashiers})


def verify_cashier_pin(name: str, pin: str) -> bool:
    for c in get_cashiers():
        if c.get("name", "").lower() == name.lower():
            return _pin_hash(pin) == c.get("pin_hash", "")
    return False
