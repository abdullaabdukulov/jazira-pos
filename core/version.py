"""Ilova versiyasi va auto-update sozlamalari.

`__version__` build paytida GitHub Actions tomonidan tag'dan avtomatik
yoziladi (workflow `build.yml` ga qarang). Lokal ishlaganda "0.0.0" qoladi —
bu holatda auto-update tekshiruvi o'tkazilmaydi (har doim "yangi" deb hisoblanmasligi uchun).
"""

__version__ = "0.0.0"

# GitHub repo (owner/repo) — release'lar shu yerdan olinadi
GITHUB_REPO = "sar552/jazira-pos"

# Release asset nomi (workflow shu nom bilan zip yuklaydi — onedir build)
ASSET_NAME = "JaziraPOS.zip"
