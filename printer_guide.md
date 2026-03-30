# Termal printer sozlash qo'llanmasi — USB to'g'ridan-to'g'ri chop etish

Bu qo'llanma Windows va Linux da USB termal printer orqali chek chop etishni sozlashni o'rgatadi.

> **QZ Tray kerak emas!** Ilova to'g'ridan-to'g'ri OS printer API orqali ishlaydi:
> - Windows: `win32print` (pywin32)
> - Linux: `lp` buyrug'i

---

## 1-qadam. USB printerni ulash va drayverni o'rnatish

### Windows

#### A. Ishlab chiqaruvchidan drayver o'rnatish (tavsiya)

| Printer | Drayver manbasi |
|---------|----------------|
| XP-365B, XP-80C | https://www.xprinter.net → Support → Downloads |
| Epson TM-T20/T82 | https://download.ebz.epson.net/dsc/search/01/search |
| Star TSP143 | https://www.starmicronics.com → Support |

Drayverni yuklab oling, o'rnating, printerni USB orqali ulang.

#### B. Generic / Text Only drayver (agar mahsus drayver topilmasa)

```cmd
:: Printers & Scanners oynasini ochish
rundll32 printui.dll,PrintUIEntry /il
```

1. "Add a local printer" tanlang
2. "Use an existing port" → USB001 (printer ulangan port)
3. Manufacturer: **Generic**, Printer: **Generic / Text Only**
4. Printer nomini bering: masalan `ThermalPOS`

### Linux

```bash
# CUPS o'rnatilganini tekshirish
sudo apt install cups

# Printer USB da ko'rinishini tekshirish
lsusb | grep -i printer

# CUPS web interfeys orqali printer qo'shish
# http://localhost:631 → Administration → Add Printer
```

---

## 2-qadam. Printer nomini aniqlash

Bu nom ERPNext da va config.json da yoziladigan nom.

### Windows

```cmd
wmic printer get name
```

Natija:
```
Name
Microsoft Print to PDF
XP-365B
```

### Linux

```bash
lpstat -p
```

Natija:
```
printer XP-365B is idle.
```

> **Muhim:** Printer nomi **100% to'g'ri** bo'lishi kerak. Hatto bitta probel farqi ham xatolikka olib keladi.

---

## 3-qadam. Printer ishlashini tekshirish

### Windows — Python orqali (tavsiya)

```cmd
cd C:\ury_desktop_pos
venv\Scripts\activate

python -c "
from core.printer import _send_raw
from core.receipt_builder import build_test_receipt

data = build_test_receipt('XP-365B')
result = _send_raw('XP-365B', data)
print('Natija:', 'Muvaffaqiyatli!' if result else 'Xatolik!')
"
```

### Linux — Python orqali

```bash
cd /opt/ury_desktop_pos
source venv/bin/activate

python3 -c "
from core.printer import _send_raw
from core.receipt_builder import build_test_receipt

data = build_test_receipt('XP-365B')
result = _send_raw('XP-365B', data)
print('Natija:', 'Muvaffaqiyatli!' if result else 'Xatolik!')
"
```

### Windows — CMD orqali oddiy test

```cmd
:: Test sahifa chop etish
echo Test page | lpr -S localhost -P "XP-365B"
```

### Linux — buyruq orqali

```bash
echo "Test page" | lp -d XP-365B -o raw
```

**Muvaffaqiyatli bo'lsa** — printerdan test cheki yoki matn chiqadi.

---

## 4-qadam. Frappe ERPNext da printer sozlash

### A. POS Profile — kassa printeri

1. **POS Profile** → o'z profilingizni oching
2. **Chop etishni yoqish** — belgilang (✓)
3. **Kassa printer nomi** — Windows/Linux dagi printer nomi (`XP-365B`)
4. Saqlang

### B. URY Production Unit — oshxona/bar printerlari

1. **URY Production Unit** ro'yxatiga o'ting
2. Har bir unit uchun (masalan: Oshpaz, Bar):
   - **Printer nomi** — shu unit uchun printer nomi (masalan: `Kitchen-Printer`)
   - **Item Groups** — shu printerga chiqadigan tovar guruhlarini tanlang
3. Saqlang

### C. Bitta printer bilan test (sinov uchun)

Agar bitta printeringiz bo'lsa — hamma joyga shu nom yozing:

| Sozlama | Qiymat |
|---------|--------|
| POS Profile → Kassa printer nomi | `XP-365B` |
| Oshpaz unit → Printer nomi | `XP-365B` |
| Bar unit → Printer nomi | `XP-365B` |

Natija: bitta printerdan ketma-ket 3 ta chek chiqadi (mijoz, oshxona, bar).

---

## 5-qadam. Sozlamalar POS ilovasiga sync bo'lishi

Ilovani qayta ishga tushiring. Login dan keyin sync avtomatik amalga oshadi.
`config.json` da quyidagi maydonlar paydo bo'ladi:

```json
{
  "qz_print": 1,
  "customer_qz_printer": "XP-365B",
  "production_units": [
    {
      "name": "Oshpaz",
      "qz_printer_name": "Kitchen-Printer",
      "item_groups": ["Oshpaz", "Taomlar"]
    },
    {
      "name": "Bar",
      "qz_printer_name": "Bar-Printer",
      "item_groups": ["Ichimliklar", "Cocktail"]
    }
  ]
}
```

---

## Chek chop etish jarayoni (arxitektura)

```
Kassir "TO'LOV" bosadi
        |
        v
  CheckoutWorker → Frappe API (sync_order → make_invoice)
        |
        v (muvaffaqiyatli)
  print_receipt() chaqiriladi
        |
        +---> build_customer_receipt() → ESC/POS bytes
        |         |
        |         v
        |     _send_raw("XP-365B", bytes)
        |         |
        |         v
        |     win32print API (Windows) yoki lp (Linux) → Printer
        |
        +---> Production unit lar uchun (har biri alohida):
              |
              +---> item_groups bo'yicha filtrlash
              +---> build_production_receipt() → ESC/POS bytes
              +---> _send_raw("Kitchen-Printer", bytes)
```

**Avvalgi usul (QZ Tray) bilan farqi:**

| | QZ Tray (eski) | To'g'ridan-to'g'ri USB (yangi) |
|---|---|---|
| Java | Kerak (JDK 11+) | **Kerak emas** |
| QZ Tray dasturi | Kerak (o'rnatish + litsenziya) | **Kerak emas** |
| WebSocket | ws://localhost:8182 | **Yo'q** |
| Sertifikat | QZ sertifikat kerak | **Kerak emas** |
| Tarmoq printer | Ha (boshqa kompyuterga) | Yo'q (faqat lokal USB) |
| Tezlik | ~200ms (WebSocket overhead) | **~50ms** (to'g'ridan-to'g'ri) |
| Ishonchlilk | QZ crash = chek chiqmaydi | **OS printer drayveriga bog'liq** |

---

## Muammolarni bartaraf etish (Troubleshooting)

### Printer topilmayapti

```cmd
:: Windows — printer nomini qaytadan tekshiring
wmic printer get name

:: Linux
lpstat -p

:: Python orqali mavjud printerlarni ko'rish
python -c "
import win32print
printers = [p[2] for p in win32print.EnumPrinters(
    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
)]
print('Mavjud printerlar:', printers)
"
```

> Printer nomi **harf-ma-harf** to'g'ri bo'lishi kerak!

### Chek chiqmayapti lekin xatolik yo'q

1. `config.json` ni tekshiring:
   - `qz_print` = **1** bo'lishi kerak (bu flag yoqadi)
   - `customer_qz_printer` = printer nomi bo'sh emasligini tekshiring

```cmd
:: Windows
type config.json

:: Linux
cat config.json
```

2. Production unit lar uchun — `item_groups` to'g'ri ekanligini tekshiring

### Kirill/O'zbek harflar noto'g'ri chiqyapti

Termal printer odatda **CP866** (Cyrillic DOS) kodlashni qo'llab-quvvatlaydi.
Agar harflar buzilsa:

1. Printer drayver sozlamalarida **Code Page 866** ni tanlang
2. Yoki printer utility dasturida character set ni o'zgartiring

### Cash drawer ochilmayapti

```cmd
python -c "
from core.printer import open_cash_drawer
result = open_cash_drawer()
print('Cash drawer:', 'Ochildi' if result else 'Xatolik')
"
```

Agar xatolik bo'lsa:
- Cash drawer printerga **RJ-11/RJ-12 kabel** bilan ulangan bo'lishi kerak
- Ba'zi printerlarda drawer port yo'q — tekshiring

### Linux da "permission denied" xatosi

```bash
# Foydalanuvchini lpadmin guruhiga qo'shish
sudo usermod -aG lpadmin $USER

# CUPS xizmatini qayta ishga tushirish
sudo systemctl restart cups
```

---

## Ma'lum bo'lgan cheklovlar va edge case lar

### 1. Printer kabeli uzilib qolsa

OS xatolik qaytaradi → `_send_raw()` `False` qaytaradi → kassirga ogohlantirish ko'rsatiladi.
Buyurtma saqlanadi, chekni keyinroq qayta chop etish mumkin.

### 2. Item kitchen printerga yo'naltirilmasa

Agar itemning guruhi hech bir production unitning `item_groups` ro'yxatida bo'lmasa:
- **Mijoz chekida** — item ko'rinadi (to'g'ri)
- **Kitchen chekda** — item **ko'rinmaydi** (xavfli!)

**Yechim:** Frappe da har bir item guruhi kamida bitta production unitga biriktirilganini tekshiring.

### 3. Offline rejimda chop etish

Agar internet yo'q bo'lsa:
- Buyurtma lokal SQLite ga saqlanadi
- Printer sozlamalari **oxirgi sync** dan olinadi
- Chek lokal printerga chop etiladi (printer ishlayotgan bo'lsa)

### 4. Juda uzun item nomlari

- Mijoz chekida: 48 belgidan uzun nomlar 2 qatorga bo'linadi
- Kitchen chekda: 24 belgidan uzun nomlar kesiladi

### 5. Maxsus belgilar (emoji, iyeroglif)

- CP866 da qo'llab-quvvatlanmaydigan belgilar `?` ga almashtiriladi
- O'zbek/rus harflar to'g'ri ishlaydi

### 6. Tarmoq printer (boshqa kompyuter)

Hozirgi versiya faqat **lokal USB printerlarni** qo'llab-quvvatlaydi.
Agar printer boshqa kompyuterda bo'lsa:
- Windows: printerning **shared** qilib, boshqa kompyuterda **network printer** sifatida qo'shish → u holda `wmic printer get name` da ko'rinadi
- Linux: CUPS da remote printer qo'shish → `lpstat -p` da ko'rinadi

---

## Tez tekshirish ro'yxati (Checklist)

```
[ ] Printer USB orqali ulangan
[ ] Printer drayveri o'rnatilgan        → wmic printer get name / lpstat -p
[ ] Printer nomi to'g'ri yozilgan       → ERPNext → POS Profile
[ ] Chop etish yoqilgan                 → POS Profile → "Chop etishni yoqish" ✓
[ ] Kassa printer nomi sozlangan        → POS Profile → "Kassa printer nomi"
[ ] Production unit printer sozlangan   → URY Production Unit → "Printer nomi"
[ ] Item groups to'g'ri biriktirilgan   → URY Production Unit → Item Groups
[ ] Test chek chiqdi                    → python test script (3-qadam)
[ ] POS ilova sync qilindi              → Login yoki "Sinxronlash" tugmasi
```
