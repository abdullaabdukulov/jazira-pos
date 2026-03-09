import json
import os
from dotenv import load_dotenv
from core.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

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
    config = load_config()
    sensitive_keys = {"api_key", "api_secret", "user", "password"}
    clean_data = {k: v for k, v in data.items() if k not in sensitive_keys}
    config.update(clean_data)

    for key in sensitive_keys:
        config.pop(key, None)

    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except PermissionError:
        logger.error("config.json yozishda ruxsat yo'q")


def save_credentials(url: str, user: str, password: str, site: str = ""):
    env_lines = [
        f"FRAPPE_URL={url}\n",
        f"FRAPPE_USER={user}\n",
        f"FRAPPE_PASSWORD={password}\n",
        f"FRAPPE_SITE={site}\n",
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
