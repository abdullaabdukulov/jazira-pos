# URY Desktop POS

Frappe ERPNext uchun oflayn rejimda ishlaydigan Desktop POS ilovasi.

## Xususiyatlari
- Oflayn savdo qilish va chek chop etish.
- Internet kelganda ma'lumotlarni avtomatik serverga yuborish.
- ESC/POS termal printerlar bilan ishlash (XP-365B va boshqalar).
- Windows va Linux qo'llab-quvvatlanadi.

## O'rnatish (Ishlab chiquvchilar uchun)

1. Python 3.10 yoki undan yuqori versiyasini o'rnating.
2. Virtual muhit yarating:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux
   venv\Scripts\activate     # Windows
   ```
3. Kutubxonalarni o'rnating:
   ```bash
   pip install -r requirements.txt
   ```

## Windows uchun EXE fayl yaratish (Build)

Ilovani bitta `.exe` fayl holatiga keltirish uchun `PyInstaller` dan foydalanamiz:

1. Terminalni oching va virtual muhitni faollashtiring.
2. Quyidagi buyruqni bajaring:
   ```bash
   pyinstaller --noconfirm --onefile --windowed --name "JaziraPOS" --add-data "ui;ui" --add-data "core;core" --add-data "database;database" --hidden-import="PyQt6.QtCore" --hidden-import="PyQt6.QtGui" --hidden-import="PyQt6.QtWidgets" main.py
   ```

3. Tayyor fayl `dist/JaziraPOS.exe` papkasida paydo bo'ladi.

**Eslatma:** Windows'da printer nomi `config.json` faylida `"printer_name"` kaliti orqali berilishi mumkin (default: `XP-365B`).

## Printer Sozlamalari (Windows)

Windows tizimida printer drayverini o'rnating va uning nomini eslab qoling.
Agar printer nomi boshqacha bo'lsa (masalan, `POS-80`), `config.json` faylini yarating va quyidagicha yozing:

```json
{
    "printer_name": "POS-80"
}
```

## Texnologiyalar
- **Frontend:** PyQt6
- **Database:** SQLite (Peewee ORM)
- **API:** Frappe REST API
