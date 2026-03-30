# QZ Tray — Windows uchun to'liq o'rnatish va sozlash qo'llanmasi

Bu qo'llanma Windows kompyuterda QZ Tray orqali termal printerga chek chop etishni CMD buyruqlari orqali to'liq sozlashni o'rgatadi.

---

## 1-qadam. Java o'rnatish (talab)

QZ Tray ishlashi uchun Java 11+ kerak.

```cmd
:: Java borligini tekshirish
java -version
```

Agar `java` topilmasa — https://adoptium.net dan **Temurin JDK 17 LTS** ni yuklab oling.

Yuklab olgandan keyin:

```cmd
:: O'rnatishni tekshirish
java -version

:: Natija shunga o'xshash bo'lishi kerak:
:: openjdk version "17.0.x" ...
```

> Agar `java` hali tanilmasa, CMD ni yopib qaytadan oching yoki quyidagi yo'lni qo'shing:
> ```cmd
> setx PATH "%PATH%;C:\Program Files\Eclipse Adoptium\jdk-17.0.x-hotspot\bin"
> ```

---

## 2-qadam. QZ Tray o'rnatish

1. https://qz.io/download saytiga kiring
2. **Windows (.exe)** ni yuklab oling
3. O'rnating — standart sozlamalar bilan:

```cmd
:: Yuklab olish (agar curl mavjud bo'lsa)
curl -L -o qz-tray-2.2.4.exe https://github.com/qzind/tray/releases/download/v2.2.4/qz-tray-2.2.4.exe

:: O'rnatish (GUI installer ochiladi)
qz-tray-2.2.4.exe
```

O'rnatgandan keyin QZ Tray tray icon sifatida ishlaydi (pastki o'ng burchakda).

---

## 3-qadam. QZ Tray ishlayotganini tekshirish

```cmd
:: WebSocket portini tekshirish (8182 = QZ Tray)
netstat -an | findstr 8182

:: Natija: TCP 0.0.0.0:8182 ... LISTENING — QZ Tray ishlayapti
:: Bo'sh natija — QZ Tray ishlamayapti
```

Agar ishlamasa:

```cmd
:: QZ Tray ni qo'lda ishga tushirish
"C:\Program Files\QZ Tray\qz-tray.exe"

:: Yoki Windows xizmati sifatida tekshirish
sc query "QZ Tray"
```

---

## 4-qadam. Windows printerlarni tekshirish

QZ Tray Windows'da o'rnatilgan printerlarni aniqlaydi. Printer o'rnatilganini tekshiring:

```cmd
:: Barcha o'rnatilgan printerlarni ko'rish
wmic printer get name,portname,drivername

:: Yoki PowerShell orqali
powershell "Get-Printer | Format-Table Name, PortName, DriverName"
```

**Natijada siz printer nomini ko'rasiz**, masalan:

```
Name                    PortName       DriverName
XP-365B                 USB001         POS Printer Driver
Xprinter XP-80C         USB002         Generic / Text Only
```

> **Muhim:** `Name` ustunidagi nom — QZ Tray ga beriladigan printer nomi.
> Masalan: `XP-365B`, `Xprinter XP-80C`

---

## 5-qadam. USB printer drayverini o'rnatish

Ko'p termal printerlar drayversiz ishlamaydi.

### A. Printer ishlab chiqaruvchidan drayver o'rnatish

| Printer | Drayver manbasi |
|---------|----------------|
| XP-365B, XP-80C | https://www.xprinter.net → Support → Downloads |
| Epson TM-T20/T82 | https://download.ebz.epson.net/dsc/search/01/search |
| Star TSP143 | https://www.starmicronics.com → Support |

### B. Generic / Text Only drayver (universal)

Agar mahsus drayver topilmasa:

```cmd
:: Printers & Scanners ni ochish
rundll32 printui.dll,PrintUIEntry /il
```

1. "Add a local printer" tanlang
2. "Use an existing port" → USB001 (printer ulangan port)
3. Manufacturer: **Generic**, Printer: **Generic / Text Only**
4. Printer nomini bering: masalan `ThermalPOS`

---

## 6-qadam. Printer ishlashini CMD dan tekshirish

```cmd
:: "XP-365B" o'rniga o'z printer nomingizni yozing
echo Test print | lpr -S localhost -P "XP-365B"
```

Yoki to'g'ridan to'g'ri:

```cmd
:: Notepad orqali test sahifa
notepad /p test.txt

:: Yoki PowerShell orqali
powershell "Get-Printer -Name 'XP-365B' | Out-Printer"
```

---

## 7-qadam. QZ Tray xavfsizlik sertifikati

QZ Tray ishonchli manba ekanligini tasdiqlash uchun sertifikat kerak.
Sinov uchun QZ Tray demo sertifikatidan foydalanish mumkin:

```cmd
:: QZ Tray sozlamalarini ochish (tray icon ustiga o'ng tugma → Advanced → Site Manager)
:: Yoki brauzerda:
start http://localhost:8182
```

**Muhim:** Production uchun QZ Tray litsenziya (https://qz.io/pricing) sotib olish tavsiya etiladi.

Demo rejimda QZ Tray har safar "Allow" dialogni ko'rsatadi.
Buni o'chirish uchun QZ Tray properties faylida:

```cmd
:: QZ Tray properties faylini ochish
notepad "C:\Program Files\QZ Tray\qz-tray.properties"
```

Quyidagini qo'shing (faqat test/development uchun):

```properties
security.data.enabled=false
security.file.enabled=false
```

QZ Tray ni qayta ishga tushiring:

```cmd
:: QZ Tray ni to'xtatish
taskkill /f /im qz-tray.exe

:: Qayta ishga tushirish
"C:\Program Files\QZ Tray\qz-tray.exe"
```

---

## 8-qadam. QZ Tray WebSocket ulanishini tekshirish

Python orqali tekshirish (URY POS venv dan):

```cmd
cd C:\ury_desktop_pos
venv\Scripts\activate

python -c "import websocket; ws = websocket.create_connection('ws://localhost:8182', timeout=5); print('QZ Tray ulanish muvaffaqiyatli!'); ws.close()"
```

**Natija:**
- `QZ Tray ulanish muvaffaqiyatli!` — hammasi ishlayapti
- `ConnectionRefusedError` — QZ Tray ishlamayapti (3-qadamga qayting)
- `ModuleNotFoundError: websocket` — `pip install websocket-client` qiling

---

## 9-qadam. Frappe backend sozlamalari

QZ Tray sozlamalari Frappe **POS Profile** da saqlanadi.

### A. POS Profile da QZ sozlamalarini yoqish

Frappe UI dan:
1. **POS Profile** → o'z profilingizni oching
2. `qz_print` maydonni **1** qiling (yoqish)
3. `qz_host` ga **localhost** yozing (yoki tarmoqdagi kompyuter IP si)
4. `customer_qz_printer_name` ga mijoz cheki printerining nomini yozing (masalan: `XP-365B`)
5. Saqlang

### B. Production Unit printerlarini sozlash

Frappe UI dan:
1. **URY Production Unit** ro'yxatiga o'ting
2. Har bir unit uchun (masalan: Oshpaz, Bar):
   - `qz_printer_name` — shu unit uchun kitchen printer nomi (masalan: `Kitchen-Printer-1`)
   - **URY Production Item Groups** — shu unitga tegishli item guruhlarni tanlang
3. Saqlang

### C. Sozlamalar URY POS Desktop ga sync bo'lishi

Ilovani qayta ishga tushiring — login dan keyin sync avtomatik amalga oshadi.
`config.json` da quyidagi maydonlar paydo bo'ladi:

```json
{
  "qz_print": 1,
  "qz_host": "localhost",
  "customer_qz_printer": "XP-365B",
  "production_units": [
    {
      "name": "Oshpaz",
      "qz_printer_name": "Kitchen-Printer-1",
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

## 10-qadam. To'liq test — chek chop etish

```cmd
cd C:\ury_desktop_pos
venv\Scripts\activate

python -c "
from core.qz_printer import _send_to_qz
from core.receipt_builder import build_test_receipt

data = build_test_receipt('XP-365B')
result = _send_to_qz('XP-365B', data, 'localhost')
print('Natija:', 'Muvaffaqiyatli!' if result else 'Xatolik!')
"
```

**Muvaffaqiyatli bo'lsa** — printerdan test cheki chiqadi.

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
        |     _send_to_qz("XP-365B", bytes, "localhost")
        |         |
        |         v
        |     WebSocket ws://localhost:8182 → QZ Tray → Printer
        |
        +---> Production unit lar uchun (har biri alohida):
              |
              +---> item_groups bo'yicha filtrlash
              +---> build_production_receipt() → ESC/POS bytes
              +---> _send_to_qz("Kitchen-Printer-1", bytes, "localhost")
```

---

## Tarmoqdagi boshqa kompyuterdan chop etish

Agar QZ Tray bitta kompyuterda, POS dasturi boshqa kompyuterda bo'lsa:

```
POS kompyuter (192.168.1.10) ---WebSocket---> QZ Tray kompyuter (192.168.1.20:8182)
```

1. QZ Tray kompyuterda Windows Firewall dan **8182** portni oching:

```cmd
:: Administrator CMD da:
netsh advfirewall firewall add rule name="QZ Tray" dir=in action=allow protocol=TCP localport=8182
```

2. QZ Tray properties faylida masofaviy ulanishlarga ruxsat:

```cmd
notepad "C:\Program Files\QZ Tray\qz-tray.properties"
```

Qo'shing:

```properties
websocket.origin=*
```

3. Frappe POS Profile da `qz_host` ni **192.168.1.20** ga o'zgartiring

---

## Muammolarni bartaraf etish (Troubleshooting)

### QZ Tray ishlamayapti

```cmd
:: Tekshiring
netstat -an | findstr 8182

:: Qayta ishga tushirish
taskkill /f /im qz-tray.exe
timeout /t 2
"C:\Program Files\QZ Tray\qz-tray.exe"
```

### Printer topilmayapti

```cmd
:: Printer nomini qaytadan tekshiring — nomi to'liq mos kelishi SHART
wmic printer get name

:: QZ Tray loglarni tekshiring
type "C:\Users\%USERNAME%\.qz\logs\debug.log"
```

> **Muhim:** QZ Tray ga beriladigan printer nomi Windows da ko'rinadigan nom bilan **100% bir xil** bo'lishi kerak. Hatto bir probel farqi ham xatolikka olib keladi.

### WebSocket ulanish xatosi

```cmd
:: Port band bo'lmaganini tekshirish
netstat -ano | findstr 8182

:: Agar boshqa dastur 8182 portni band qilgan bo'lsa
:: PID ni toping va to'xtating:
taskkill /f /pid <PID_RAQAMI>
```

### Chek chiqmayapti lekin xatolik yo'q

1. `config.json` ni tekshiring — `qz_print` **1** bo'lishi kerak
2. `customer_qz_printer` bo'sh emasligini tekshiring
3. Production unit lar uchun — `item_groups` to'g'ri ekanligini tekshiring

```cmd
:: config.json ni ko'rish
type config.json
```

### Kirill/O'zbek harflar noto'g'ri chiqyapti

Termal printer odatda **CP866** (Cyrillic DOS) kodlashni qo'llab-quvvatlaydi.
Agar harflar buzilsa:

1. Printer drayver sozlamalarida **Code Page 866** ni tanlang
2. Yoki printer utility dasturida character set ni o'zgartiring

### Cash drawer ochilmayapti

```cmd
python -c "
from core.qz_printer import open_cash_drawer
result = open_cash_drawer()
print('Cash drawer:', 'Ochildi' if result else 'Xatolik')
"
```

Agar xatolik bo'lsa:
- Cash drawer printer ga **RJ-11/RJ-12 kabel** bilan ulangan bo'lishi kerak
- Ba'zi printerlarda drawer port yo'q — tekshiring

---

## Ma'lum bo'lgan cheklovlar va edge case lar

### 1. QZ Tray to'satdan to'xtasa

Buyurtma **yo'qolmaydi** — Frappe serverga allaqachon saqlangan. Faqat chek chiqmaydi.
Kassirga ogohlantirish dialog oynasi ko'rsatiladi.

### 2. Printer kabel uzilib qolsa

QZ Tray xatolik qaytaradi → `print_receipt()` `False` qaytaradi → kassirga ogohlantirish ko'rsatiladi.
Buyurtma saqlanadi, chekni keyinroq qayta chop etish mumkin.

### 3. Item kitchen printerga yo'naltirilmasa

Agar itemning `item_group` si hech bir production unitning `item_groups` ro'yxatida bo'lmasa:
- **Mijoz chekida** — item ko'rinadi (to'g'ri)
- **Kitchen chekda** — item **ko'rinmaydi** (xavfli!)
- Oshxona bu itemni tayyorlamaslik xavfi bor

**Yechim:** Frappe da har bir itemning `item_group` si kamida bitta production unitga biriktirilganini tekshiring.

### 4. Offline rejimda chop etish

Agar internet yo'q bo'lsa:
- Buyurtma lokal SQLite ga saqlanadi
- Printer sozlamalari **oxirgi sync** dan olinadi
- Agar sync dan keyin server dagi printer nomi o'zgargan bo'lsa — chek **eski** printerga ketadi

### 5. Juda uzun item nomlari

- Mijoz chekida: 48 belgidan uzun nomlar 2 qatorga bo'linadi
- Kitchen chekda: 24 belgidan uzun nomlar kesiladi
- Ma'lumot yo'qolmaydi, faqat ko'rinishi o'zgaradi

### 6. Maxsus belgilar (emoji, iyeroglif)

- CP866 da qo'llab-quvvatlanmaydigan belgilar `?` ga almashtiriladi
- O'zbek/rus harflar to'g'ri ishlaydi
- Emoji va noyob Unicode belgilar chekda `?` bo'lib chiqadi

### 7. Bir vaqtda bir nechta buyurtma chop etilsa

Har bir chop etish alohida WebSocket ulanish ochadi va yopadi.
QZ Tray bir vaqtda bir nechta so'rovni qabul qiladi — muammo yo'q.

### 8. WebSocket timeout (7 sekund)

Agar QZ Tray 7 sekundda javob bermasa:
- Chop etish bekor qilinadi
- Log ga yoziladi
- Buyurtma saqlanadi
- Kassirga ogohlantirish ko'rsatiladi

---

## QZ Tray ni Windows bilan avtomatik ishga tushirish

```cmd
:: Startup papkasiga shortcut qo'shish
copy "C:\Program Files\QZ Tray\qz-tray.exe" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\"

:: Yoki registry orqali
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "QZ Tray" /t REG_SZ /d "\"C:\Program Files\QZ Tray\qz-tray.exe\"" /f
```

Tekshirish:

```cmd
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "QZ Tray"
```

---

## Tez tekshirish ro'yxati (Checklist)

```
[ ] Java 11+ o'rnatilgan              → java -version
[ ] QZ Tray o'rnatilgan               → netstat -an | findstr 8182
[ ] Printer drayveri o'rnatilgan       → wmic printer get name
[ ] Printer nomi to'g'ri yozilgan     → config.json → customer_qz_printer
[ ] qz_print = 1                      → config.json
[ ] qz_host = "localhost"             → config.json
[ ] websocket-client o'rnatilgan      → pip list | findstr websocket
[ ] Production unit lar sozlangan     → config.json → production_units
[ ] Item groups to'g'ri biriktirilgan → Frappe → URY Production Unit
[ ] Test chek chiqdi                  → python test script yuqorida
[ ] QZ Tray autostart sozlangan       → registry yoki startup papka
```
