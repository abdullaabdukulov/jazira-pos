# URY Desktop POS

Frappe ERPNext uchun oflayn rejimda ishlaydigan Desktop POS ilovasi.

## O'rnatish

### Talablar
- Python 3.10+
- Frappe server (URY moduli bilan)
- ESC/POS termal printer (XP-365B, Epson TM va boshqalar)

### Linux

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Printer uchun ruxsat
sudo usermod -aG lp $USER
# Qayta login qiling
```

### Windows

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install pywin32
```

### Windows EXE (Build)

```bash
pyinstaller --noconfirm --onefile --windowed --name "JaziraPOS" \
  --add-data "ui;ui" --add-data "core;core" --add-data "database;database" \
  --hidden-import="PyQt6.QtCore" --hidden-import="PyQt6.QtGui" \
  --hidden-import="PyQt6.QtWidgets" main.py
```

Tayyor fayl: `dist/JaziraPOS.exe`

## Ishga tushirish

```bash
python main.py
```

Birinchi marta login qilganingizda barcha ma'lumotlar serverdan sinxronizatsiya qilinadi:
tovarlar, mijozlar, to'lov usullari va **production unitlar**.

## Printer sozlash

`config.example.json` dan nusxa oling:

```bash
cp config.example.json config.json
```

### Mijoz printeri

`config.json` dagi `printers` bo'limi:

```json
{
    "printers": [
        {
            "name": "Mijoz",
            "type": "customer",
            "device": "/dev/usb/lp0",
            "win_name": "XP-365B"
        }
    ]
}
```

| Maydon | Platforma | Tavsif |
|---|---|---|
| `device` | Linux | USB printer yo'li: `/dev/usb/lp0`, `/dev/usb/lp1` |
| `win_name` | Windows | Printer nomi (Settings → Printers da ko'ringandek) |

Windows da printer nomini tekshirish:

```bash
python -c "import win32print; [print(p[2]) for p in win32print.EnumPrinters(2)]"
```

### Production unit printerlar (oshxona, barista)

Production unitlar **serverdan avtomatik** sinxronizatsiya qilinadi (URY Production Unit doctype asosida). Faqat **printer sozlamasini** qo'lda yozish kerak:

```json
{
    "production_units": [
        {
            "name": "Oshxona",
            "item_groups": ["Oshpaz mahsulotlari"],
            "printer_device": "/dev/usb/lp1",
            "printer_win_name": "Kitchen Printer"
        },
        {
            "name": "Koffe",
            "item_groups": ["Koffe"],
            "printer_device": "/dev/usb/lp2",
            "printer_win_name": "Bar Printer"
        }
    ]
}
```

| Maydon | Qo'lda | Tavsif |
|---|---|---|
| `name` | Yo'q | Serverdan keladi |
| `item_groups` | Yo'q | Serverdan keladi |
| `printer_device` | Ha | Linux USB yo'li |
| `printer_win_name` | Ha | Windows printer nomi |

> Sinxronizatsiya qo'lda yozilgan `printer_device` va `printer_win_name` ni **yo'qotmaydi**.

## Chek chiqarish mantiqiy

Buyurtma → **1 ta mijoz cheki** + **N ta production unit cheki**:

| Chek | Mazmuni | Printer |
|---|---|---|
| Mijoz cheki | Barcha tovarlar + narxlar + to'lov + qaytim | `printers[type=customer]` |
| Production unit cheki | Faqat shu unitga tegishli tovarlar (narxsiz) + stiker | `production_units[].printer_device` |

Misol: 1 Latte + 1 Hotdog buyurtma qilindi:
- **Mijoz cheki** → Latte 25,000 + Hotdog 15,000 = 40,000 UZS
- **Barista cheki** → Latte x1, Stiker: 42
- **Oshxona cheki** → Hotdog x1, Stiker: 42

Filialda production unit yo'q bo'lsa — faqat mijoz cheki chop etiladi.

## Oflayn rejim

- Internet yo'q bo'lsa buyurtma lokal bazaga saqlanadi
- Cheklar darhol chop etiladi (lokal ma'lumotlar asosida)
- Internet kelganda avtomatik serverga yuboriladi
- Qayta chop etilmaydi
