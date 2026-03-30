# URY Desktop POS

Frappe ERPNext (URY moduli) uchun oflayn rejimda ishlaydigan Desktop POS ilovasi.

## Xususiyatlar

- Sensorli ekranga moslashtirilgan to'liq POS interfeys
- Oflayn rejim — internet yo'qligida ham sotuv davom etadi
- USB termal printerlarga to'g'ridan-to'g'ri ESC/POS chek chiqarish
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
| Printer | win32print (Windows) / lp (Linux) + ESC/POS |
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
│   └── printer.py              # USB printer orqali chop etish
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
- USB termal printer (XPrinter, Epson, Star va boshqalar)

### Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Windows

```bat
python -m venv venv
venv\Scripts\activate
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
2. Login muvaffaqiyatli bo'lganda barcha ma'lumotlar sinxronizatsiya qilinadi
3. Kassa ochish dialogi ko'rsatiladi

## EXE ga build qilish (PyInstaller)

### Linux

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
  main.py
```

### Windows

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
  --hidden-import="win32print" ^
  main.py
```

Tayyor fayl: `dist\JaziraPOS.exe`

## Printer sozlash

Ilova USB printerga to'g'ridan-to'g'ri ESC/POS baytlar yuboradi. QZ Tray yoki boshqa vositachi dastur kerak emas.

### 1. Printerni ulash va drayver o'rnatish

1. Termal printerni USB orqali kompyuterga ulang
2. Printer drayverini o'rnating (ishlab chiqaruvchidan yoki Generic / Text Only)
3. Printer nomini oling:

```bat
:: Windows
wmic printer get name
```

```bash
# Linux
lpstat -p
```

### 2. Frappe ERPda sozlash

**POS Profile:**

| Maydon | Qiymat | Izoh |
|---|---|---|
| Chop etishni yoqish | ✓ | Printerni yoqish |
| Kassa printer nomi | `XP-365B` | wmic/lpstat dan olingan nom |

**URY Production Unit (har bir unit uchun):**

| Maydon | Qiymat | Izoh |
|---|---|---|
| Printer nomi | `XP-365B` | Shu unitga tegishli printer |
| Item Groups | Oshpaz, Koffe va h.k. | Qaysi tovarlar shu printerga borishi |

### 3. Bitta printer bilan test

Agar bitta printeringiz bo'lsa — hamma joyga shu printer nomini yozing:
- POS Profile → Kassa printer nomi: `XP-365B`
- Oshpaz unit → Printer nomi: `XP-365B`
- Bar unit → Printer nomi: `XP-365B`

Natija: bitta printerdan ketma-ket 3 ta chek chiqadi (mijoz, oshxona, bar).

### Chek chiqarish mantiqi

Buyurtma → **1 ta mijoz cheki** + **N ta production unit cheki**:

| Chek turi | Mazmuni | Printer |
|---|---|---|
| Mijoz cheki | Barcha tovarlar + narxlar + to'lov + qaytim + stiker | Kassa printer |
| Production unit cheki | Faqat shu unitga tegishli tovarlar (narxsiz, katta shrift) + stiker + buyurtma turi | Unit printer |

Misol: 1 Latte + 1 Hotdog buyurtma (Stiker: 42):
- **Mijoz cheki** → Latte 25,000 + Hotdog 15,000 = 40,000 UZS
- **Barista cheki** → Latte x1, Stiker: 42
- **Oshxona cheki** → Hotdog x1, Stiker: 42

## Oflayn rejim

- Server bilan aloqa yo'q bo'lganda buyurtmalar lokal SQLite bazaga saqlanadi
- Status bar da **OFFLINE** ko'rsatiladi, offline cheklar soni tugmada ko'rinadi
- Internet tiklanishi bilan cheklar avtomatik serverga yuboriladi (har 30 sekundda)
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

1. `config.json` da `qz_print: 1` ekanligini tekshiring
2. Printer nomi OS dagi nom bilan bir xilligini tekshiring
3. Windows: `wmic printer get name` — printer ro'yxatda bormi?
4. Linux: `lpstat -p` — printer ro'yxatda bormi?
5. Printer yoqilganligini va USB ulangan bo'lishini tekshiring

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
