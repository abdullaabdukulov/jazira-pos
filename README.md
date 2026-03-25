# URY Desktop POS

Frappe ERPNext (URY moduli) uchun oflayn rejimda ishlaydigan Desktop POS ilovasi.

## Xususiyatlar

- Sensorli ekranga moslashtirilgan to'liq POS interfeys
- Oflayn rejim — internet yo'qligida ham sotuv davom etadi
- QZ Tray orqali ESC/POS termal printerlarga chek chiqarish
- Kassa ochish/yopish (POS Opening/Closing)
- Buyurtma tarixi va bekor qilish
- Ko'p tabli sotuv (bir vaqtda bir nechta savat)
- Buyurtma turlari: Shu yerda, Saboy, Dastavka, Dastavka Saboy
- Stiker/ticket raqam tizimi
- Mijozlar ro'yxati (serverdan sinxronlash)
- Avtomatik responsiv dizayn (1366x768 dan 2560x1440 gacha)

## Texnologiyalar

| Komponent | Texnologiya |
|---|---|
| UI Framework | PyQt6 |
| Ma'lumotlar bazasi | SQLite (WAL mode) + Peewee ORM |
| Backend API | Frappe/ERPNext REST API (requests) |
| Printer | QZ Tray (WebSocket) + ESC/POS |
| Build | PyInstaller |

## Loyiha strukturasi

```
ury_desktop_pos/
├── main.py                     # Ilovaning kirish nuqtasi
├── config.json                 # Ish vaqtida sozlamalar (avtomatik yaratiladi)
├── config.example.json         # Sozlamalar namunasi
├── requirements.txt            # Python paketlari
├── pos_data.db                 # SQLite ma'lumotlar bazasi (avtomatik)
├── .env                        # Login ma'lumotlari (avtomatik)
│
├── core/                       # Asosiy modullar
│   ├── api.py                  # Frappe REST API klient (thread-safe)
│   ├── config.py               # Konfiguratsiya boshqaruvi
│   ├── constants.py            # Konstantalar (timeout, limitlar)
│   ├── exceptions.py           # Maxsus xatolar
│   ├── logger.py               # Rotating file logger
│   ├── receipt_builder.py      # ESC/POS chek formatlash
│   └── qz_printer.py           # QZ Tray WebSocket integratsiya
│
├── database/                   # Ma'lumotlar bazasi
│   ├── models.py               # Peewee ORM modellari
│   ├── migrations.py           # Sxema migratsiyalari
│   ├── sync.py                 # SyncWorker (server → lokal sinxronlash)
│   ├── offline_sync.py         # OfflineSyncWorker (lokal → server)
│   └── invoice_processor.py    # Oflayn chek qayta ishlash
│
├── ui/                         # Foydalanuvchi interfeysi
│   ├── main_window.py          # Asosiy oyna + worker boshqaruvi
│   ├── login_window.py         # Login oynasi (sensorli klaviatura)
│   ├── scale.py                # Responsiv masshtablash
│   ├── styles.py               # Global QSS stillar
│   └── components/             # UI komponentlari
│       ├── item_browser.py     # Tovar katalogi (kategoriya + grid)
│       ├── cart_widget.py      # Savat (buyurtma turlari, stiker, mijoz)
│       ├── checkout_window.py  # To'lov oynasi (naqd, Payme, Click...)
│       ├── history_window.py   # Buyurtma tarixi
│       ├── pos_opening.py      # Kassa ochish dialogi
│       ├── pos_closing.py      # Kassa yopish dialogi
│       ├── pos_shifts_window.py # Kassa tarixi
│       ├── offline_queue_window.py # Oflayn cheklar ro'yxati
│       ├── dialogs.py          # InfoDialog, ConfirmDialog
│       ├── keyboard.py         # Sensorli klaviatura
│       └── numpad.py           # Raqamli panel
│
└── logs/                       # Log fayllar
    └── pos.log                 # Ilova loglari (5MB, 3 backup)
```

## O'rnatish

### Talablar

- Python 3.10+
- Frappe server (URY moduli o'rnatilgan)
- QZ Tray (printer uchun, ixtiyoriy)

### Linux

```bash
# Virtual muhit yaratish
python3 -m venv venv
source venv/bin/activate

# Paketlar o'rnatish
pip install -r requirements.txt
```

### Windows

```bash
# Virtual muhit yaratish
python -m venv venv
venv\Scripts\activate

# Paketlar o'rnatish
pip install -r requirements.txt
```

## Ishga tushirish

```bash
# Linux
source venv/bin/activate
python main.py

# Windows
venv\Scripts\activate
python main.py
```

Birinchi marta ishga tushirilganda:

1. Login oynasi ochiladi — server URL, login va parolni kiriting
2. Login muvaffaqiyatli bo'lganda barcha ma'lumotlar sinxronizatsiya qilinadi:
   - POS profil sozlamalari
   - Tovarlar menusi
   - Mijozlar ro'yxati
   - To'lov usullari
   - Printer sozlamalari
   - Production unit konfiguratsiyasi
3. Kassa ochish dialogi ko'rsatiladi

## EXE ga build qilish (PyInstaller)

### Linux (AppImage/binary)

```bash
source venv/bin/activate
pip install pyinstaller

pyinstaller --noconfirm --onefile --windowed \
  --name "JaziraPOS" \
  --add-data "config.example.json:." \
  --hidden-import="PyQt6.QtCore" \
  --hidden-import="PyQt6.QtGui" \
  --hidden-import="PyQt6.QtWidgets" \
  --hidden-import="peewee" \
  --hidden-import="websocket" \
  main.py
```

Tayyor fayl: `dist/JaziraPOS`

```bash
# Ishga tushirish
chmod +x dist/JaziraPOS
./dist/JaziraPOS
```

### Windows EXE

```bat
venv\Scripts\activate
pip install pyinstaller

pyinstaller --noconfirm --onefile --windowed ^
  --name "JaziraPOS" ^
  --add-data "config.example.json;." ^
  --hidden-import="PyQt6.QtCore" ^
  --hidden-import="PyQt6.QtGui" ^
  --hidden-import="PyQt6.QtWidgets" ^
  --hidden-import="peewee" ^
  --hidden-import="websocket" ^
  --icon="NONE" ^
  main.py
```

Tayyor fayl: `dist\JaziraPOS.exe`

### Build eslatmalari

- `config.json`, `.env`, `pos_data.db` fayllar EXE ichiga kiritilmaydi — ular dastur ishga tushganda avtomatik yaratiladi
- Birinchi marta EXE ishga tushganda login oynasi ochiladi
- `config.example.json` faqat namuna sifatida kiritiladi
- Windows da ikonka qo'shish uchun `--icon="icon.ico"` parametrini o'zgartiring

### Spec fayl bilan build (murakkab holatlar uchun)

Agar `--onefile` rejimida muammo bo'lsa, avval spec fayl yarating:

```bash
pyinstaller --name "JaziraPOS" --windowed --onefile main.py
```

Bu `JaziraPOS.spec` faylini yaratadi. Keyin uni tahrirlang va qayta build qiling:

```bash
pyinstaller JaziraPOS.spec
```

## Printer sozlash (QZ Tray)

Ilova QZ Tray orqali ESC/POS printerlarga chek yuboradi.

### QZ Tray o'rnatish

1. [qz.io](https://qz.io/) saytidan QZ Tray ni yuklab o'rnating
2. QZ Tray ishga tushganiga ishonch hosil qiling (system tray da ikonka)
3. Standart port: `ws://localhost:8182`

### Printer sozlamalari

Printer sozlamalari **serverdan avtomatik sinxronizatsiya** qilinadi:

| Sozlama | Tavsif | Qayerdan |
|---|---|---|
| `qz_print` | QZ Tray yoqilgan/o'chirilgan (1/0) | Serverdan |
| `qz_host` | QZ Tray host (default: localhost) | Serverdan |
| `customer_qz_printer` | Mijoz cheki printeri nomi | Serverdan |
| `production_units[].qz_printer_name` | Production unit printer nomi | Serverdan |

Printer nomlari QZ Tray da ko'rinadigan nomlar bilan bir xil bo'lishi kerak.

### Chek chiqarish mantiqi

Buyurtma → **1 ta mijoz cheki** + **N ta production unit cheki**:

| Chek turi | Mazmuni | Printer |
|---|---|---|
| Mijoz cheki | Barcha tovarlar + narxlar + to'lov + qaytim + stiker | `customer_qz_printer` |
| Production unit cheki | Faqat shu unitga tegishli tovarlar (narxsiz) + stiker + buyurtma turi | `production_units[].qz_printer_name` |

Misol: 1 Latte + 1 Hotdog buyurtma qilindi (Stiker: 42):
- **Mijoz cheki** → Latte 25,000 + Hotdog 15,000 = 40,000 UZS
- **Barista cheki** → Latte x1, Stiker: 42
- **Oshxona cheki** → Hotdog x1, Stiker: 42

## Oflayn rejim

- Server bilan aloqa yo'q bo'lganda buyurtmalar lokal SQLite bazaga saqlanadi
- Cheklar darhol chop etiladi (lokal ma'lumotlar asosida)
- Status bar da **OFFLINE** ko'rsatiladi, offline cheklar soni tugmada ko'rinadi
- Internet tiklanishi bilan cheklar avtomatik serverga yuboriladi (har 30 sekundda tekshiriladi)
- Agar `sync_order` muvaffaqiyatli, lekin `make_invoice` xato bo'lsa — qayta urinishda faqat `make_invoice` chaqiriladi (duplikat buyurtma oldini olish)
- Doimiy xatolar (ValidationError, 403, 404) qayta urinilmaydi — "Failed" statusiga o'tkaziladi

## Buyurtma turlari

| Tur | Stiker talab | Tavsif |
|---|---|---|
| Shu yerda | Ha | Restoranda yeyish |
| Saboy | Ha | Olib ketish |
| Dastavka | Yo'q | Yetkazib berish |
| Dastavka Saboy | Yo'q | Yetkazib berish (saboy) |

## Konfiguratsiya fayllari

### `.env` — Login ma'lumotlari

Avtomatik yaratiladi. Qo'lda yaratish:

```env
FRAPPE_URL=http://your-server:8000
FRAPPE_USER=user@example.com
FRAPPE_PASSWORD=your-password
FRAPPE_SITE=your-site.localhost
```

`FRAPPE_SITE` — faqat multi-site bench uchun kerak.

### `config.json` — Ish vaqtida sozlamalar

Sinxronizatsiya vaqtida serverdan avtomatik to'ldiriladi. Qo'lda o'zgartirish shart emas.

## Xatoliklarni tuzatish

### Ilova ishga tushmayapti

```bash
# Loglarni tekshiring
cat logs/pos.log

# Verbose rejimda ishga tushiring
python main.py
```

### Printer ishlamayapti

1. QZ Tray ishga tushganligini tekshiring (system tray)
2. `config.json` da `qz_print: 1` ekanligini tekshiring
3. Printer nomi QZ Tray dagi nom bilan bir xilligini tekshiring
4. QZ Tray konsolida xatolarni tekshiring

### Server bilan aloqa yo'q

1. `.env` dagi `FRAPPE_URL` to'g'riligini tekshiring
2. Serverda URY moduli o'rnatilganligini tekshiring
3. Foydalanuvchi POS profiliga ruxsati borligini tekshiring

### Ma'lumotlar bazasini tozalash

```bash
# Barcha lokal ma'lumotlarni o'chirish
rm pos_data.db
# Ilovani qayta ishga tushiring — baza qaytadan yaratiladi
```
