"""Auto-update — GitHub Releases orqali ilovani yangilash (onedir build).

Build rejimi: --onedir → JaziraPOS papkasi ichida JaziraPOS.exe + _internal/.
Release asset: butun papka zip qilingan (JaziraPOS.zip).

Mantiq:
    1. UpdateCheckWorker GitHub API'dan eng so'nggi release'ni oladi
    2. Versiya joriydan kattaroq bo'lsa → update_available signali
    3. Foydalanuvchi tasdiqlasa → UpdateDownloadWorker zip'ni yuklab, temp'ga ochadi
    4. Windows ishlab turgan papkani almashtira olmaydi (exe va DLL'lar band).
       Shuning uchun kichik .bat skript yoziladi:
         - ilova yopilishini kutadi (2 sek)
         - robocopy bilan yangi fayllarni install papkasiga ko'chiradi
           (config.json/.env/pos_data.db/logs — TEGILMAYDI, /MIR ishlatilmaydi)
         - ilovani qayta ishga tushiradi
         - o'zini o'chiradi
    5. .bat ishga tushiriladi, ilova yopiladi.

Faqat PyInstaller bilan "muzlatilgan" .exe da ishlaydi. Manbadan
(python main.py) ishlaganda update o'tkazib yuboriladi.
"""
import os
import sys
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from core.logger import get_logger
from core.version import __version__, GITHUB_REPO, ASSET_NAME
from core.constants import API_TIMEOUT_DEFAULT

logger = get_logger(__name__)

DOWNLOAD_TIMEOUT = 180  # sekund — zip katta bo'lishi mumkin
_TEMP_PREFIX = "jazira_update_"


def is_frozen() -> bool:
    """PyInstaller .exe ichida ishlayaptimi?"""
    return getattr(sys, "frozen", False)


def _exe_path() -> Path:
    """Joriy ishlab turgan .exe yo'li."""
    return Path(sys.executable)


def _install_dir() -> Path:
    """Ilova o'rnatilgan papka (exe joylashgan papka)."""
    return _exe_path().parent


def _parse_version(v: str) -> tuple:
    """'v1.2.3' yoki '1.2.3' → (1, 2, 3). Noto'g'ri bo'lsa (0,)."""
    v = (v or "").strip().lstrip("vV")
    parts = []
    for chunk in v.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, local: str) -> bool:
    """remote > local bo'lsa True."""
    return _parse_version(remote) > _parse_version(local)


def cleanup_temp_updates():
    """Oldingi yangilanishdan qolgan temp papkalarni o'chirish (startup'da)."""
    try:
        tmp = Path(tempfile.gettempdir())
        for d in tmp.glob(_TEMP_PREFIX + "*"):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        logger.debug("Temp update tozalanmadi: %s", e)


class UpdateCheckWorker(QThread):
    """GitHub'dan eng so'nggi release'ni tekshiradi (fon thread)."""

    # (version, download_url, release_notes)
    update_available = pyqtSignal(str, str, str)
    no_update = pyqtSignal()
    check_failed = pyqtSignal(str)

    def run(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            resp = requests.get(
                url,
                headers={"Accept": "application/vnd.github+json"},
                timeout=API_TIMEOUT_DEFAULT,
            )
            if resp.status_code != 200:
                self.check_failed.emit(f"GitHub API {resp.status_code}")
                return

            data = resp.json()
            tag = data.get("tag_name", "")
            notes = data.get("body", "") or ""

            if not is_newer(tag, __version__):
                self.no_update.emit()
                return

            # zip asset'ni topish
            download_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name == ASSET_NAME or name.lower().endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url:
                self.check_failed.emit(".zip asset topilmadi")
                return

            logger.info("Yangi versiya mavjud: %s (joriy: %s)", tag, __version__)
            self.update_available.emit(tag, download_url, notes)

        except requests.exceptions.RequestException as e:
            logger.debug("Update tekshiruvi (tarmoq): %s", e)
            self.check_failed.emit("Tarmoq xatosi")
        except Exception as e:
            logger.error("Update tekshiruv xatosi: %s", e)
            self.check_failed.emit(str(e))


class UpdateDownloadWorker(QThread):
    """Yangi versiya zip'ini yuklab, temp papkaga ochadi."""

    progress = pyqtSignal(int)        # 0..100
    finished_ok = pyqtSignal(str)     # ochilgan manba papka (JaziraPOS.exe shu yerda)
    failed = pyqtSignal(str)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url

    def run(self):
        try:
            work_dir = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
            zip_path = work_dir / "update.zip"

            # 1. Yuklash
            with requests.get(self.download_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=128 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(int(downloaded * 100 / total))

            # 2. Ochish
            extract_dir = work_dir / "extracted"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # 3. JaziraPOS.exe joylashgan papkani topish (zip ichida ichma-ich bo'lishi mumkin)
            src_dir = self._find_exe_dir(extract_dir)
            if not src_dir:
                self.failed.emit("Yuklangan arxivda JaziraPOS.exe topilmadi")
                return

            logger.info("Yangi versiya ochildi: %s", src_dir)
            self.finished_ok.emit(str(src_dir))
        except Exception as e:
            logger.error("Update yuklash xatosi: %s", e)
            self.failed.emit(str(e))

    @staticmethod
    def _find_exe_dir(root: Path) -> Path | None:
        target = _exe_path().name  # JaziraPOS.exe
        for p in root.rglob(target):
            return p.parent
        return None


def apply_update_and_restart(src_dir: str):
    """install papkasini yangi fayllar bilan almashtirib, qayta ishga tushiradigan
    .bat yozadi va ishga tushiradi. Ilova shundan keyin yopilishi kerak.
    """
    src = Path(src_dir)
    dst = _install_dir()
    exe = _exe_path()

    bat_path = Path(tempfile.gettempdir()) / "jazira_apply_update.bat"

    # robocopy /E — fayllarni ko'chiradi/ustiga yozadi, lekin dst'dagi
    # qo'shimcha fayllarni (config.json, .env, pos_data.db, logs) O'CHIRMAYDI.
    bat = f"""@echo off
timeout /t 2 /nobreak >nul
robocopy "{src}" "{dst}" /E /R:10 /W:2 >nul
start "" "{exe}"
(goto) 2>nul & del "%~f0"
"""
    bat_path.write_text(bat, encoding="utf-8")

    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True,
    )
    logger.info("Yangilash skripti ishga tushdi, ilova yopilmoqda")
