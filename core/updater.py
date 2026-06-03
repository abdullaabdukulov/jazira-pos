"""Auto-update — GitHub Releases orqali ilovani yangilash (onefile build).

Build rejimi: --onefile → bitta JaziraPOS.exe (README'dagidek).
Release asset: JaziraPOS.exe.

Mantiq:
    1. UpdateCheckWorker GitHub API'dan eng so'nggi release'ni oladi
    2. Versiya joriydan kattaroq bo'lsa → update_available signali
    3. Foydalanuvchi tasdiqlasa → UpdateDownloadWorker yangi .exe ni yuklaydi
    4. Windows ishlab turgan .exe ni o'chira olmaydi, lekin nomini o'zgartira oladi:
         JaziraPOS.exe      → JaziraPOS.old.exe
         JaziraPOS.new.exe  → JaziraPOS.exe
       So'ng yangi .exe ishga tushiriladi, eskisi yopiladi.
    5. Keyingi ochilishda cleanup_old_exe() qoldiq .old.exe ni o'chiradi.

Faqat PyInstaller bilan "muzlatilgan" (frozen) .exe da ishlaydi. Manbadan
(python main.py) ishlaganda update o'tkazib yuboriladi.
"""
import os
import sys
import subprocess
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from core.logger import get_logger
from core.version import __version__, GITHUB_REPO, ASSET_NAME
from core.constants import API_TIMEOUT_DEFAULT

logger = get_logger(__name__)

DOWNLOAD_TIMEOUT = 120  # sekund — .exe katta bo'lishi mumkin


def is_frozen() -> bool:
    """PyInstaller .exe ichida ishlayaptimi?"""
    return getattr(sys, "frozen", False)


def _exe_path() -> Path:
    """Joriy ishlab turgan .exe yo'li."""
    return Path(sys.executable)


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


def cleanup_old_exe():
    """Oldingi yangilanishdan qolgan .old.exe ni o'chirish (startup'da)."""
    if not is_frozen():
        return
    try:
        exe = _exe_path()
        old = exe.with_name(exe.stem + ".old.exe")
        if old.exists():
            old.unlink()
            logger.info("Eski .exe tozalandi: %s", old.name)
    except Exception as e:
        # Hali bandligi mumkin — keyingi safar tozalanadi
        logger.debug("Eski .exe tozalanmadi: %s", e)


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

            # .exe asset'ni topish
            download_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name == ASSET_NAME or name.lower().endswith(".exe"):
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url:
                self.check_failed.emit(".exe asset topilmadi")
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
    """Yangi .exe ni yuklab, almashtirishga tayyorlaydi."""

    progress = pyqtSignal(int)        # 0..100
    finished_ok = pyqtSignal(str)     # yangi exe yo'li
    failed = pyqtSignal(str)

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url

    def run(self):
        try:
            exe = _exe_path()
            new_exe = exe.with_name(exe.stem + ".new.exe")

            with requests.get(self.download_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(new_exe, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(int(downloaded * 100 / total))

            logger.info("Yangi .exe yuklandi: %s", new_exe.name)
            self.finished_ok.emit(str(new_exe))
        except Exception as e:
            logger.error("Update yuklash xatosi: %s", e)
            self.failed.emit(str(e))


def apply_update_and_restart(new_exe_path: str):
    """Eski .exe ni .old ga ko'chirib, yangisini o'rniga qo'yib, restart qiladi.

    Bu funksiya ilova yopilishidan oldin chaqiriladi.
    """
    exe = _exe_path()
    new_exe = Path(new_exe_path)
    old_exe = exe.with_name(exe.stem + ".old.exe")

    # Qoldiq .old bo'lsa o'chiramiz
    if old_exe.exists():
        try:
            old_exe.unlink()
        except Exception:
            pass

    # Ishlab turgan .exe nomini o'zgartirish (Windows buni ruxsat beradi)
    os.rename(exe, old_exe)
    os.rename(new_exe, exe)

    # Yangi .exe ni ishga tushirish
    subprocess.Popen([str(exe)], close_fds=True)
    logger.info("Yangi versiya ishga tushirildi, eski jarayon yopilmoqda")
