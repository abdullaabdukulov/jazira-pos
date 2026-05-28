# Texnik Topshiriq (TZ) — URY Desktop POS yangilanishi

**Sana:** 2026-05-16
**Loyiha:** URY Desktop POS (PyQt6 client) + Frappe URY moduli (jazira.local)
**Mas'ul:** Abdulla
**Status:** Tasdiqlash kutilmoqda — v2 (URY Table integration + real-time + edge cases)

---

## 1. Maqsad

Mavjud URY Desktop POS tizimiga quyidagi funksiyalarni qo'shish:

1. **Order number type** — POS Profile da `Stiker` (free-text) yoki `Stol` (mavjud `URY Table` doctype dan tanlash)
2. **To'lovsiz buyurtma** — savatdan to'lov qilmasdan buyurtmani saqlash; "To'lov kutilmoqda" panel + order_type filter chiplari
3. **Kassir/Ofitsant rollari** — POS dan ham kassir, ham ofitsant; ofitsant faqat to'lovsiz buyurtma yaratadi va o'zinikini ko'radi (read-only)
4. **Devicelararo real-time sinxronlash** — ofitsant urgan zakaz kassirda darhol paydo bo'ladi (Frappe SocketIO)
5. **Menu item tartibini boshqarish** — URY Menu Item `idx` orqali admin ERPNext da drag-drop qiladi
6. **Ofitsant online-only** — ofitsant offline rejimda zakaz urolmaydi: ekran blok bo'lib "Tarmoq yo'q — kassadan zakaz bering" xabari chiqadi

---

## 2. Hozirgi tizim qisqacha tahlili

| Komponent | Holat |
|---|---|
| **POS Profile** | `custom_order_type_dine_in/take_away/delivery/delivery_saboy` checkboxlar, `custom_show_*`, `custom_company_logo`, `custom_receipt_footer`, `custom_enable_multiple_cashier` |
| **POS Invoice** | `custom_ticket_number` (Int), `custom_active_cashier` (Data), `custom_client_ref`, **`restaurant_table` (Link → URY Table)** |
| **URY Table** | `restaurant_room`, `branch`, `no_of_seats`, `is_take_away`, `occupied`, `latest_invoice_time`, `layout_x/y/width/height`, `table_shape` |
| **URY Room** | `branch`, `room_type` (AC/NON-AC). **Branch → Room → Table** ierarxiyasi |
| **Multiple Rooms** | POS Opening Entry child table — bir kassir bir nechta xonaga kirishi mumkin |
| **`sync_order` (ury_order.py:328)** | `invoice.invoice_printed == 0 and table` bo'lsa, `URY Table.occupied=1` va `latest_invoice_time` o'rnatiladi |
| **URY Menu Item** | `item`, `item_name`, `rate`, `course`, `disabled`, `special_dish`. Frappe child table → avtomatik `idx` field mavjud, lekin hozir foydalanilmagan |
| **Menu getRestaurantMenu** | Hozir `order_by="item_name asc"` (alphabetic) |
| **Order types (client)** | `Shu yerda`, `Saboy` (stiker talab), `Dastavka`, `Dastavka Saboy` — `core/constants.py:25-28` |
| **Checkout** | Bitta yo'l: `TO'LOV QILISH` → `sync_order` + `make_invoice` (`checkout_window.py:466-529`) |
| **PendingInvoice** | Lokal SQLite — **faqat tarmoq xatosi** uchun |
| **URY POS Cashier** | `user`, `full_name`, `pin`, `active` — **rol yo'q** |
| **Frappe Realtime** | Server tomon `frappe.publish_realtime` allaqachon ishlatiladi (reload_ro, KOT, print channels). Desktop POS hozircha SocketIO ga ulanmaydi |

**🟡 Diqqat:** Hozirgi Desktop POS da `restaurant_table` to'ldirilmaydi. Yangi TZ da Stol rejimida `URY Table.name` haqiqiy qiymat bilan to'ldiriladi → `occupied=1` mantiqi avto yoqiladi.

---

## 3. Qabul qilingan qarorlar

| Savol | Javob |
|---|---|
| Stol rejimida raqam qaysi turlarga? | `Shu yerda` faqat. **Saboy stol talab qilmaydi** (KOT da "Saboy" yozuvi) |
| Stiker rejimida qaysi turlarga? | Hozirgidek: `Shu yerda` + `Saboy` (free-text raqam) |
| Stol bo'shatish | (1) To'lov/Bekor avto + (2) TablePicker da `🔓 Bo'shatish` tugma + (3) POS Closing da orphan tekshiruvi |
| Ofitsant pending listni? | Faqat o'zinikini, **read-only** (qo'shimcha tahrir yo'q) |
| To'lovsiz buyurtmada KOT? | Ha, darhol oshxonaga |
| Rol qayerda? | `URY POS Cashier.role` (Select: Kassir/Ofitsant) |
| Devicelararo real-time? | **Frappe SocketIO + python-socketio** client |
| Menu item order? | **URY Menu Item `idx`** (Frappe child table standard, admin drag-drop) |
| Ofitsant offline rejimida? | **BLOK** — to'liq ekran ustida "Tarmoq yo'q — kassadan zakaz bering" xabari. Ofitsant offline da zakaz urolmaydi |
| Kassir offline rejimida? | Hozirgidek ishlayveradi (PendingInvoice → server tiklanganda retry). Realtime ishlamaydi |
| KOT printer | Aralash: kassirda USB bill, oshxonada LAN KOT printer |
| Frappe joylashuv | Bulutda (internet kerak) |

---

## 4. Funksional talablar

### 4.1 — POS Profile: Order Number Type (Stiker / Stol)

#### 4.1.1 Saboy + Stol rejimi qoidasi

| order_number_type | Shu yerda | Saboy | Dastavka | Dastavka Saboy |
|---|---|---|---|---|
| **Stiker** | Stiker (free-text) | Stiker (free-text) | — | — |
| **Stol** | **Stol pickerdan** | — (raqamsiz) | — | — |

**Saboy + Stol** holatida: Cart da na stiker, na stol input ko'rinmaydi. Faqat KOT/chekda "Saboy" yozuvi chiqadi. Ofitsant/kassir mijozga og'zaki "X daqiqadan keyin tayyor" deydi.

#### 4.1.2 Server tomon — POS Profile field

`apps/ury/ury/fixtures/custom_field.json`:

```json
{
  "doctype": "Custom Field", "dt": "POS Profile",
  "fieldname": "custom_order_number_type",
  "fieldtype": "Select",
  "options": "Stiker\nStol",
  "default": "Stiker",
  "label": "Buyurtma raqami turi",
  "description": "Stiker = mijozga beriladigan raqam (free-text). Stol = URY Table dan tanlanadi, occupied avto belgilanadi. Stol rejimida faqat Shu yerda buyurtmasiga stol talab qilinadi.",
  "insert_after": "custom_order_type_delivery_saboy",
  "name": "POS Profile-custom_order_number_type",
  "allow_on_submit": 1
}
```

`ury_pos/api.py:getPosProfile()` qaytarish:
```python
"order_number_type": pos_profiles.custom_order_number_type or "Stiker",
```

#### 4.1.3 Server — Stol/Xona API

```python
@frappe.whitelist()
def getTables(branch=None, room=None):
    """Filial (yoki xona) bo'yicha stollar — barchasi (band va bo'sh)."""
    if not branch:
        branch = getBranch()
    filters = {"branch": branch}
    if room:
        filters["restaurant_room"] = room
    return frappe.get_all(
        "URY Table",
        filters=filters,
        fields=["name", "restaurant_room", "no_of_seats", "occupied",
                "latest_invoice_time", "is_take_away",
                "layout_x", "layout_y", "layout_width", "layout_height",
                "table_shape"],
        order_by="restaurant_room asc, name asc",
        limit_page_length=500,
    )


@frappe.whitelist()
def getRoomsForBranch(branch=None):
    """POS Opening Entry'ga biriktirilgan xonalar (Multiple Rooms),
    yoki yo'q bo'lsa barcha filial xonalari."""
    # 1) Joriy opening entrydan Multiple Rooms olish
    # 2) Bo'sh bo'lsa filial bo'yicha barchasi
    ...


@frappe.whitelist()
def freeTable(table, reason):
    """Stolni qo'lda bo'shatish (admin/kassir uchun).

    Effects:
    - URY Table.occupied = 0
    - latest_invoice_time = None
    - URY Activity Log ga yozuv (kim, qachon, sabab)
    """
    if not frappe.has_permission("URY Table", "write"):
        frappe.throw("Sizda stol bo'shatish huquqi yo'q")
    frappe.db.set_value("URY Table", table, {
        "occupied": 0, "latest_invoice_time": None
    })
    frappe.get_doc({
        "doctype": "URY Activity Log",  # yoki existing log mexanizmi
        "action": "Table Freed",
        "ref_doctype": "URY Table",
        "ref_name": table,
        "user": frappe.session.user,
        "reason": reason,
    }).insert(ignore_permissions=True)
    frappe.publish_realtime("table_freed", {"table": table})
    return {"status": "ok"}
```

#### 4.1.4 Server — POS Invoice submit/cancel da stol bo'shatish

`apps/ury/ury/ury/hooks/ury_pos_invoice.py` (mavjud hook fayli) ga qo'shish:

```python
def on_submit(doc, method):
    """To'lov qabul qilingach — stol bo'shaydi."""
    if doc.restaurant_table:
        frappe.db.set_value("URY Table", doc.restaurant_table, {
            "occupied": 0, "latest_invoice_time": None
        })
        frappe.publish_realtime("table_freed", {"table": doc.restaurant_table})


def on_cancel(doc, method):
    """Bekor qilingach — stol bo'shaydi va Cancel KOT chiqadi."""
    if doc.restaurant_table:
        frappe.db.set_value("URY Table", doc.restaurant_table, {
            "occupied": 0, "latest_invoice_time": None
        })
        frappe.publish_realtime("table_freed", {"table": doc.restaurant_table})
    # cancel_kot allaqachon mavjud (ury_order.py:712)
```

Hooks ro'yxatga olish — `hooks.py` da:
```python
doc_events = {
    "POS Invoice": {
        "on_submit": "ury.ury.hooks.ury_pos_invoice.on_submit",
        "on_cancel": "ury.ury.hooks.ury_pos_invoice.on_cancel",
    }
}
```

#### 4.1.5 Client — Lokal modellar

`database/models.py` ga qo'shish:
```python
class Room(BaseModel):
    name = CharField(unique=True, index=True)
    branch = CharField(null=True)
    room_type = CharField(null=True)
    last_sync = DateTimeField(default=datetime.datetime.now)

class Table(BaseModel):
    name = CharField(unique=True, index=True)
    restaurant_room = CharField(null=True, index=True)
    no_of_seats = IntegerField(default=0)
    occupied = BooleanField(default=False)
    is_take_away = BooleanField(default=False)
    latest_invoice_time = CharField(null=True)
    layout_x = FloatField(default=0)
    layout_y = FloatField(default=0)
    layout_width = FloatField(default=0)
    layout_height = FloatField(default=0)
    table_shape = CharField(null=True)
    last_sync = DateTimeField(default=datetime.datetime.now)
```

`database/migrations.py` da schema versiya bump.

`database/sync.py` ga `_sync_tables_and_rooms()` (faqat `order_number_type=Stol` bo'lsa).

#### 4.1.6 Client — TablePickerDialog

**Yangi fayl:** `ui/components/table_picker.py`

UI:
```
┌─────────────────────────────────────────────────┐
│  Stol tanlang                          [✕]      │
├─────────────────────────────────────────────────┤
│  [Zal 1] [Zal 2] [Terassa]              ← tabs  │
├─────────────────────────────────────────────────┤
│   ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐                     │
│   │ 1│ │ 2│ │ 3│ │ 4│ │ 5│ ← layout_x/y dan   │
│   └──┘ └──┘ └──┘ └──┘ └──┘                     │
│        ┌────────┐                               │
│        │  6 ●   │ ← qizil (band)               │
│        │  band  │                               │
│        └────────┘   [🔓 Bo'shatish] (band ustida)│
└─────────────────────────────────────────────────┘
```

- **Layout** — `URY Table.layout_x/y` dan absolute positioning
- **Layout 0 bo'lsa** — fallback grid (5 ustun)
- **Band stol bossa** — `🔓 Bo'shatish` tugma chiqadi (reason bilan dialog)
- **SocketIO event** — `table_freed`, `table_occupied` event larida real-time refresh
- **Pickerda real-time** — bir kassir picker ochib turganda boshqa kassir stolga ursa → o'sha lahzada qizil bo'ladi

#### 4.1.7 Client — Cart widget

**Stiker rejimi** — hozirgidek (free-text).

**Stol rejimi:**

| order_type | Stol tugmasi | Stiker input |
|---|---|---|
| Shu yerda | ✅ ko'rinadi (talab) | yashirin |
| Saboy | yashirin | yashirin (raqamsiz) |
| Dastavka, D. Saboy | yashirin | yashirin |

```python
def apply_settings(self, ...):
    cfg = load_config()
    order_number_type = cfg.get("order_number_type", "Stiker")
    needs_table = (order_number_type == "Stol"
                   and self.current_order_type == "Shu yerda")
    needs_sticker = (order_number_type == "Stiker"
                     and self.current_order_type in TICKET_ORDER_TYPES)

    self.table_button_container.setVisible(needs_table)
    self.ticket_input_container.setVisible(needs_sticker)
```

Tanlangan stol Cart da chiroyli ko'rsatiladi: `Zal 1 / 5 (4o'rin)`.

#### 4.1.8 Receipt va KOT

`core/receipt_builder.py`:
- Stiker: `STIKER: #42`
- Stol: `STOL: Zal 1 / 5 (4o'rin)`
- Saboy + Stol: `🛍 SABOY`

#### 4.1.9 Qabul mezonlari

- ✅ POS Profile sozlangach POS sinxronlangach Cart UI mos
- ✅ TablePicker URY Table layout asosida to'g'ri ko'rsatadi
- ✅ Band stollar real-time qizil ko'rinadi
- ✅ Tanlangan stol POS Invoice ga `restaurant_table` sifatida saqlanadi
- ✅ To'lov/Bekor — stol avto bo'shaydi (`on_submit`/`on_cancel` hooks)
- ✅ Qo'lda bo'shatish — reason bilan, log saqlanadi
- ✅ Saboy + Stol rejimida na stol, na stiker talab qilinmaydi
- ✅ Backward compat — eski profiles `Stiker` (default)

---

### 4.2 — To'lovsiz buyurtma + "To'lov kutilmoqda" ro'yxati

#### 4.2.1 Client — savatga "Saqlash" tugmasi

```
[💾 SAQLASH]            [💰 TO'LOV QILISH]
```

- **Ofitsant rolida** — `TO'LOV QILISH` yashirin
- `save_requested` yangi signal

#### 4.2.2 SaveOrderWorker

`ury.ury.doctype.ury_order.ury_order.sync_order` chaqiradi, `make_invoice` chaqirilmaydi. Draft POS Invoice qoladi. KOT avto chiqadi.

Tarmoq xatosi → `PendingInvoice` (lokal) ga tushadi.

#### 4.2.3 PendingOrdersWindow

**Yangi fayl:** `ui/components/pending_orders_window.py`

```
┌─────────────────────────────────────────────────────────────┐
│  To'lov kutilmoqda                       [⟳] [✕]            │
├─────────────────────────────────────────────────────────────┤
│  [Hammasi 12] [Shu yerda 5] [Saboy 4] [Dastavka 2] [D.S. 1]│
├─────────────────────────────────────────────────────────────┤
│  Vaqt│#N/Stol  │Tur     │Mijoz   │Ofitsant │Summa │Amallar│
│ 14:23│Zal 1/T5 │Shuyerda│Walk-in │Aziz K.  │45,000│[💰][✕]│
│ 14:18│#41      │Saboy   │Walk-in │Bekzod   │30,000│[💰][✕]│
└─────────────────────────────────────────────────────────────┘
```

- `#N/Stol` — order_number_type ga qarab
- Amallar **faqat kassir** uchun ko'rinadi

#### 4.2.4 Server API

```python
@frappe.whitelist()
def getPendingOrders(order_type=None, only_mine=0, mine_cashier_name=None,
                    limit=50, limit_start=0):
    """Draft + invoice_printed=0 invoicelar. SQL: WHERE branch=? AND status='Draft'
    AND docstatus=0 AND invoice_printed=0 [AND order_type=?] [AND custom_active_cashier=?]"""
    ...

@frappe.whitelist()
def getPendingOrderCounts(only_mine=0, mine_cashier_name=None):
    """Filter chiplari uchun: {"Dine In": 5, "Take Away": 4, ...}"""
    ...

@frappe.whitelist()
def cancel_pending_order(invoice, reason):
    """Bekor qilish + Cancel KOT + Stol bo'shatish (on_cancel hook avto)."""
    doc = frappe.get_doc("POS Invoice", invoice)
    if doc.docstatus != 0:
        frappe.throw("Faqat Draft buyurtmalarni bekor qilish mumkin")
    doc.custom_cancel_reason = reason
    doc.cancel()  # on_cancel hook → stol bo'shaydi + cancel_kot
    frappe.publish_realtime("pending_order_cancelled", {"invoice": invoice})
    return {"status": "ok"}
```

#### 4.2.5 Davom etish flow (Kassir)

"💰 To'lov" bossadi:
1. `getPosInvoiceItems(invoice)` chaqiriladi — itemlarni oladi
2. `CheckoutWindow` ochiladi `existing_invoice` parametri bilan
3. Worker `make_invoice(invoice=existing_invoice)` chaqiradi — `sync_order` qayta chaqirilmaydi (mavjud Draft saqlanadi)
4. Submit bo'lgach `on_submit` hook → stol bo'shaydi
5. SocketIO event → boshqa POSlarda pending listdan yo'qoladi

#### 4.2.6 Top-bar tugma

```python
self.pending_btn = _tb_btn("To'lov kutilmoqda: 0", "ghost")
```

Count 0 dan katta bo'lsa rangli. SocketIO event yoki polling (har 10 sek).

#### 4.2.7 Qabul mezonlari

- ✅ Saqlash → server Draft + KOT + (Stol rejimida) `occupied=1`
- ✅ Pending listda ko'rinadi (kassirda real-time)
- ✅ Filter chiplari to'g'ri ishlaydi
- ✅ To'lov → submit → invoice yo'qoladi, stol bo'shaydi
- ✅ Bekor → invoice cancel, Cancel KOT, stol bo'shaydi
- ✅ Ofitsant pending listni read-only ko'radi (faqat o'zinikini)
- ✅ Tarmoq yo'q → PendingInvoice lokalga, tiklangach yuboriladi

---

### 4.3 — Kassir/Ofitsant rollari

#### 4.3.1 Server — URY POS Cashier role

`apps/ury/ury/ury/doctype/ury_pos_cashier/ury_pos_cashier.json`:
```json
{
  "fieldname": "role",
  "fieldtype": "Select",
  "label": "Rol",
  "options": "Kassir\nOfitsant",
  "default": "Kassir",
  "reqd": 1,
  "in_list_view": 1
}
```

`get_pos_cashiers()` qaytarishga `role` qo'shiladi.

#### 4.3.2 Server — POS Invoice ga role

```json
{
  "doctype": "Custom Field", "dt": "POS Invoice",
  "fieldname": "custom_active_cashier_role",
  "fieldtype": "Data",
  "read_only": 1,
  "insert_after": "custom_active_cashier"
}
```

`sync_order` ga `active_cashier_role` parametri.

#### 4.3.3 Client — UI

- Top-bar rol badge (Kassir=ko'k, Ofitsant=binafsha)
- Cart `set_role()` metodi → ofitsant uchun checkout_btn yashirin
- PendingOrdersWindow `only_mine=1` ofitsantda

#### 4.3.4 Chek shabloni

```
Ofitsant: Aziz Karimov
Stol: Zal 1 / 5
```

---

### 4.4 — Real-time sinxronlash (Frappe SocketIO)

#### 4.4.1 Texnologiya

- **Backend:** `frappe.publish_realtime(channel, data)` — allaqachon ishlatiladi
- **Client:** `python-socketio[client]` paketi (requirements.txt ga qo'shish)
- **URL:** Frappe SocketIO endpoint — `<FRAPPE_URL>:9000` (default) yoki bench `socketio_port`

#### 4.4.2 Yangi modul — `core/realtime.py`

```python
import socketio
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from core.logger import get_logger

logger = get_logger(__name__)


class RealtimeClient(QObject):
    """Frappe SocketIO orqali serverdan eventlar olish.

    Channels:
        pending_order_created    — yangi Draft POS Invoice yaratildi
        pending_order_updated    — Draft invoice o'zgardi
        pending_order_cancelled  — Draft cancel qilindi
        pending_order_paid       — Draft → Paid
        table_occupied           — URY Table band bo'ldi
        table_freed              — URY Table bo'shadi
        kot_created              — Yangi KOT chiqdi (optional)
    """
    pending_order_created   = pyqtSignal(dict)
    pending_order_updated   = pyqtSignal(dict)
    pending_order_cancelled = pyqtSignal(dict)
    pending_order_paid      = pyqtSignal(dict)
    table_occupied          = pyqtSignal(dict)
    table_freed             = pyqtSignal(dict)
    connected               = pyqtSignal(bool)

    def __init__(self, url, sid_cookie):
        super().__init__()
        self.url = url
        self.sid_cookie = sid_cookie
        self.sio = socketio.Client(reconnection=True,
                                   reconnection_attempts=0,  # cheksiz
                                   reconnection_delay=3,
                                   reconnection_delay_max=30)
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.event
        def connect():
            logger.info("SocketIO connected")
            self.connected.emit(True)

        @self.sio.event
        def disconnect():
            logger.warning("SocketIO disconnected")
            self.connected.emit(False)

        @self.sio.on("pending_order_created")
        def on_created(data): self.pending_order_created.emit(data)

        @self.sio.on("table_occupied")
        def on_tocc(data): self.table_occupied.emit(data)

        @self.sio.on("table_freed")
        def on_tfree(data): self.table_freed.emit(data)
        # ...

    def start(self):
        try:
            self.sio.connect(self.url,
                           headers={"Cookie": f"sid={self.sid_cookie}"},
                           transports=["websocket"])
        except Exception as e:
            logger.error("SocketIO connect xatosi: %s", e)

    def stop(self):
        if self.sio.connected:
            self.sio.disconnect()
```

#### 4.4.3 Server — yangi publish_realtime chaqirishlar

`apps/ury/ury/ury/hooks/ury_pos_invoice.py`:

```python
def after_insert(doc, method):
    if doc.docstatus == 0 and doc.status == "Draft":
        frappe.publish_realtime("pending_order_created", {
            "invoice": doc.name,
            "branch": doc.branch,
            "order_type": doc.order_type,
            "custom_active_cashier": doc.custom_active_cashier,
            "grand_total": float(doc.grand_total or 0),
        }, after_commit=True)

def on_update(doc, method):
    if doc.docstatus == 0 and doc.status == "Draft":
        frappe.publish_realtime("pending_order_updated", {...}, after_commit=True)

def on_submit(doc, method):
    if doc.restaurant_table:
        frappe.db.set_value("URY Table", doc.restaurant_table,
                          {"occupied": 0, "latest_invoice_time": None})
        frappe.publish_realtime("table_freed", {"table": doc.restaurant_table},
                              after_commit=True)
    frappe.publish_realtime("pending_order_paid", {"invoice": doc.name},
                          after_commit=True)
```

#### 4.4.4 Client — integratsiya

`ui/main_window.py`:

```python
def _start_realtime(self):
    cfg = load_config()
    sio_url = cfg.get("realtime_url") or self._derive_sio_url()
    self.realtime = RealtimeClient(sio_url, self.api.sid)
    self.realtime.pending_order_created.connect(self._on_realtime_pending_created)
    self.realtime.pending_order_paid.connect(self._on_realtime_pending_paid)
    self.realtime.table_occupied.connect(self._on_realtime_table_changed)
    self.realtime.table_freed.connect(self._on_realtime_table_changed)
    self.realtime.connected.connect(self._on_realtime_status)
    self.realtime.start()
```

Handler-lar:
- Pending list ochiq bo'lsa, darhol qayta yuklash
- Top-bar counter yangilanadi
- TablePicker ochiq bo'lsa, stol holatlari real-time refresh

#### 4.4.5 Connection lost holati

- 3 sekund kechikish bilan auto-reconnect (cheksiz)
- Disconnected paytida fallback polling 10 sek
- Top-bar da kichik indikator: 🟢 Realtime / 🟡 Polling (orange) / 🔴 Offline

#### 4.4.6 Qabul mezonlari

- ✅ Ofitsant urgani 1-2 soniyada kassirda paydo bo'ladi
- ✅ Stol holati barcha POSlarda real-time
- ✅ Disconnect bo'lsa avtomatik qayta ulanadi
- ✅ Connection lost paytda fallback polling

---

### 4.5 — Menu item tartibini boshqarish

#### 4.5.1 Server tomon

URY Menu Item — Frappe child table → avtomatik `idx` field bor.

`apps/ury/ury/ury_pos/api.py:getRestaurantMenu` ni o'zgartirish:

```python
items_data = frappe.db.get_all(
    "URY Menu Item",
    filters={"parent": menu, "disabled": 0},
    fields=["item", "item_name", "rate", "special_dish", "disabled", "course", "idx"],
    order_by="idx asc, item_name asc"  # ← idx birinchi
)
```

Admin ERPNext da URY Menu doctype ichida menu itemlarini drag-drop qilib tartibni o'zgartiradi → keyingi sinxronlashda POS da yangi tartib chiqadi.

#### 4.5.2 Client tomon

`database/models.py:Item` ga `display_idx` field:
```python
display_idx = IntegerField(default=0, index=True)
```

`database/sync.py:_sync_items` — `idx` ni `display_idx` ga saqlash.

`ui/components/item_browser.py` — `Item.select().order_by(Item.display_idx, Item.item_name)`.

#### 4.5.3 Qabul mezonlari

- ✅ ERPNext da URY Menu da drag-drop ishlaydi (standard Frappe)
- ✅ POS sinxronlangach yangi tartib qo'llanadi
- ✅ Eski sinxronlanmagan POSlarda alphabetic fallback (default 0)

---

### 4.7 — Ofitsant Online-Only rejimi (offline blok)

#### 4.7.1 Maqsad

Ofitsant **majburiy onlayn** ishlaydi. Internet uzilsa, ofitsant POSi to'liq blok bo'ladi — zakaz urolmaydi, mavjud cart yopilmaydi (saqlanadi), ekranda **to'liq ekran modal** ko'rsatiladi.

**Sabab:** Ofitsant offline rejimida zakaz saqlasa, kassir buni ko'rmaydi va to'lov olishi mumkin emas. Bu **business risk** (mijoz ketib qoladi yoki kassir qog'ozdan qo'lda kiritishi kerak). Soddaroq qoida: ofitsant online → KOT → kassirga ko'rinadi → to'lov. Offline → to'xtatish.

#### 4.7.2 Connection detection

Yangi modul: `core/connection_monitor.py`

```python
class ConnectionMonitor(QObject):
    """Real-time tarmoq holatini kuzatadi.

    State: ONLINE | OFFLINE
    - SocketIO bog'lanish + 5 sek lik ping (light API call)
    - Disconnect bo'lganda 3 sek grace period (qisqa uzilishlar uchun)
    """
    state_changed = pyqtSignal(str)  # "online" | "offline" | "checking"

    def __init__(self, api, realtime):
        self.api = api
        self.realtime = realtime
        self.current_state = "checking"
        self._grace_timer = QTimer(singleShot=True)
        self._grace_timer.timeout.connect(self._declare_offline)
        # SocketIO disconnect → start grace
        # HTTP ping har 10 sek (fallback)
```

**Algoritm:**
1. SocketIO `connected` event → state=ONLINE
2. SocketIO `disconnect` → **3 sek timer** boshlanadi
3. 3 sek ichida `connect` bo'lsa — bekor qilinadi (qisqa uzilish)
4. 3 sek o'tsa va hali `disconnect` bo'lsa — state=OFFLINE
5. HTTP ping fallback har 10 sek (SocketIO bo'lmasa)

#### 4.7.3 Ofitsant ekran blok UI

`ui/components/offline_block_overlay.py` (YANGI)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│                                                         │
│             📡  ❌                                      │
│                                                         │
│       Tarmoq bilan aloqa yo'q                          │
│                                                         │
│       Iltimos, mijozni kassaga yuboring.               │
│       Kassir to'g'ridan-to'g'ri zakazni qabul qiladi.  │
│                                                         │
│       Tarmoq tiklangach avto ochiladi.                 │
│                                                         │
│       [⟳ Qayta urinish]    [📞 Yordam (admin)]          │
│                                                         │
│       Tekshirilmoqda... 12 sek o'tdi                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- **Modal overlay** — semi-transparent qora ust qatlam (95% qoplama)
- Ostida hozirgi cart **saqlanib qoladi** (tarmoq tiklansa darhol davom etish)
- ESC bilan yopilmaydi, fokus chiqib ketmaydi
- "Qayta urinish" — darhol ping yuboradi
- "Yordam (admin)" — debug ma'lumotlar (FRAPPE_URL, last ping vaqti, IP) ko'rsatadi
- Tarmoq tiklangach **avto yashirinadi** (state=ONLINE)

#### 4.7.4 Zakaz urilayotgan paytda tarmoq uzilishi

**Stsenariy:** Ofitsant "Saqlash" bossadi, request yuborilayotganda tarmoq uziladi.

**Yechim:**
- `SaveOrderWorker` xato qaytaradi (timeout yoki connection error)
- Cart **bo'shamaydi** (data saqlanadi)
- Toast: "Tarmoq uzildi. Cart saqlanib qoldi. Tarmoq tiklangach qaytadan urining."
- Keyin overlay chiqadi (ConnectionMonitor offline ni aniqlagach)
- Tarmoq tiklangach overlay yo'qoladi, foydalanuvchi yana "Saqlash" tugmasini bosishi kerak

**Diqqat:** Ofitsant da **`PendingInvoice` (lokal queue) ishlatilmaydi**. Faqat kassir uchun.

#### 4.7.5 Kassir offline rejimida

Kassir uchun **hozirgi xulq saqlanadi**:
- Offline da zakaz va to'lov mumkin
- `PendingInvoice` lokal SQLite ga tushadi
- Tarmoq tiklangach `OfflineSyncWorker` server ga yuboradi
- KOT printer USB orqali ishlayveradi
- SocketIO yo'q paytda pending list **ko'rinmaydi** (server da Draft invoicelar haqida bilmaydi)
- Status bar: 🟠 **Offline — N ta yuborilmagan**

#### 4.7.6 Connection states matrix

| State | Ofitsant POS | Kassir POS | Indicator |
|---|---|---|---|
| Online + Realtime | Ishlaydi normal | Ishlaydi normal, realtime updates | 🟢 |
| Online + Polling (SocketIO down) | Ishlaydi, pending list 10 sek polling | Ishlaydi, pending list 10 sek polling | 🟡 |
| Offline | **BLOK ekran** | Lokal saqlash, pending list ko'rinmaydi | 🔴 |

#### 4.7.7 Qabul mezonlari

- ✅ Ofitsant rolida tarmoq uzilsa, 3-5 sek ichida blok overlay chiqadi
- ✅ Blok overlay yopilmaydi (ESC, alt-tab ishlamaydi)
- ✅ Tarmoq tiklangach avto yashirinadi
- ✅ Cart data yo'qolmaydi (saqlanadi ostidagi state da)
- ✅ Kassir uchun blok yo'q (hozirgi xulq saqlanadi)
- ✅ Qisqa uzilishlar (5 sek dan kam) overlay ko'rsatmaydi (grace period)

---

### 4.6 — Edge cases va xatolik holatlari

#### 4.6.1 POS Closing va Draft invoices

**Muammo:** Kassa yopayotganda Draft (to'lanmagan) buyurtmalar mavjud.

**Yechim:**
- POS Closing dialogi oldida tekshirish: `getPendingOrders(branch=...)` count > 0 bo'lsa:
  - **Warning** dialog: "To'lov kutilayotgan N ta buyurtma bor. Yopishdan oldin hammasini hal qiling."
  - Variantlar: [Pending listni ochish] [Force yopish — admin PIN]
  - Force yopish bo'lsa, hamma Draft invoicelar avto cancel (audit log saqlanadi)

#### 4.6.2 Bir vaqtda bir stolga ikkita POS

**Muammo:** Kassir A va Kassir B bir vaqtda Stol 5 ga buyurtma uradi.

**Yechim — server tomon `sync_order`:**
```python
# Yangi invoice yaratilayotgan bo'lsa va stol band bo'lsa
if not invoice.name and table:
    table_doc = frappe.get_doc("URY Table", table)
    if table_doc.occupied:
        # Boshqa active Draft invoice bormi?
        other = frappe.db.exists("POS Invoice", {
            "restaurant_table": table,
            "docstatus": 0, "status": "Draft", "invoice_printed": 0
        })
        if other:
            return {"status": "Failure",
                   "message": f"Stol {table} boshqa POS da band ({other})"}
```

**Client tomon:** `TablePickerDialog` real-time refresh, picker ochiq paytda boshqa kassir ursa — qizil bo'ladi va tanlash imkoni yo'qoladi.

#### 4.6.3 Orphaned occupied stollar

**Muammo:** Server crash yoki cancel qilinmagan Draft tufayli stol band qolib ketdi.

**Yechim — POS Closing paytida:**
```python
@frappe.whitelist()
def cleanup_orphan_tables(branch):
    """Occupied=1 lekin active Draft yo'q stollarni bo'shatish."""
    tables = frappe.get_all("URY Table",
                           filters={"branch": branch, "occupied": 1},
                           pluck="name")
    freed = []
    for t in tables:
        has_active = frappe.db.exists("POS Invoice", {
            "restaurant_table": t,
            "docstatus": 0, "status": "Draft", "invoice_printed": 0
        })
        if not has_active:
            frappe.db.set_value("URY Table", t,
                               {"occupied": 0, "latest_invoice_time": None})
            freed.append(t)
    return {"freed_count": len(freed), "tables": freed}
```

POS Closing dialogida "Orphan stollar tozalandi: N ta" xabari.

#### 4.6.4 Tarmoq xatosi paytida zakaz urish

**Ofitsant rolida (online-only):**
- Tarmoq uzilsa **blok overlay** chiqadi (4.7 ga qarang)
- Zakaz urilmaydi, `PendingInvoice` ishlatilmaydi
- Cart saqlanib qoladi, tarmoq tiklangach davom etish mumkin

**Kassir rolida (offline ham ishlaydi):**
- `CheckoutWorker` xato → `PendingInvoice` (lokal) ga
- Status bar: "🟠 Offline — N ta yuborilmagan"
- Tarmoq tiklangach `OfflineSyncWorker` (mavjud) yuboradi
- KOT printer USB orqali to'g'ridan-to'g'ri ishlaydi
- **Stol band qilish:** Offline da `URY Table.occupied=1` server da bo'lmaydi. Lokal "rejimda band" bayroq qo'yiladi (faqat shu POS da). Tarmoq tiklangach real `occupied=1` (boshqa POSlar ko'radi)

#### 4.6.5 Ofitsant Draft invoice ga qaytib qaramoqchi (read-only)

**Qaror:** Ofitsant pending listdan buyurtmasini ochib ko'ra oladi (item ro'yxati, summa), lekin tahrirlay olmaydi. Yangi item qo'shish kerak bo'lsa — alohida zakaz (yangi POS Invoice). Bu mantiq toza ajratish uchun.

#### 4.6.6 KOT differential

**Muammo:** Save → KOT chiqdi (3 item). Bir necha daqiqadan keyin mijoz "yana 1 ta qo'sh" desa, qanday qilamiz?

**Hozirgi versiyada — qaror:** Faqat **kassir** qo'shimcha buyurtma urishi mumkin (yangi zakaz, alohida POS Invoice, alohida KOT). Mavjud Draft tahrirlanmaydi.

**Kelajakda (out of scope):** "Item qo'shish" tugmasi pending listda, faqat kassir uchun. `sync_order` `past_item` mantiqi (`ury_order.py:263-271`) farqi bo'yicha yangi KOT chiqaradi.

#### 4.6.7 Bekor qilingan Draft — Cancel KOT

**Mantiq:** `on_cancel` hook → mavjud `cancel_kot` (ury_order.py:712) chaqiriladi → oshxonaga "bekor qilindi" cheki avto chiqadi.

#### 4.6.8 POS Profile dan order_number_type o'zgartirilsa (yarim yo'lda)

**Stsenariy:** Profil `Stiker` edi, faol 5 ta Draft invoice bor (custom_ticket_number bilan). Admin profilini `Stol` ga o'zgartirdi.

**Yechim:**
- Mavjud Draft invoicelar `custom_ticket_number` bilan saqlanadi
- Pending listda ko'rsatish: ikkala fieldni ham tekshirish, qaysi biri to'lgan bo'lsa o'sha ko'rsatiladi
- Yangi invoicelar yangi rejimda yaratiladi

#### 4.6.9 Stol picker ochilganda lokal DB bo'sh

**Stsenariy:** Sinxronlash hali qilinmagan, Stol picker ochilsa.

**Yechim:**
- "Stollar yuklanmagan. Sinxronlashni boshlash?" dialogi
- Foydalanuvchi bossa — sinxronlash boshlanadi va picker yopiladi

#### 4.6.10 Layout x/y bo'lmagan stollar

**Yechim:** Fallback **grid layout** — 5 ustun, har stol qutisi `100×80px`. Stol nomi va `no_of_seats` ko'rsatiladi.

#### 4.6.11 Multiple Cashier rejimi

**Stsenariy:** POS Profile da `custom_enable_multiple_cashier=1`. POS Opening da bir nechta kassir.

**Pending list filtering:**
- Kassir: filial bo'yicha hamma (faqat `only_mine=0` bilan)
- Ofitsant: faqat o'zinikini

#### 4.6.12 SocketIO ulanmagan paytda

**Yechim:**
- Top-bar indicator: 🟡 polling rejimi
- Fallback polling 10 sek davom etadi
- Connect bo'lganda darhol bir martalik full refresh

#### 4.6.13 Sticker rejimi va stol bo'shatish

**Eslatma:** Stiker rejimida `URY Table` umuman teglanmaydi. `restaurant_table` bo'sh qoladi. Stikerni "bo'shatish" tushunchasi yo'q — har yangi buyurtma yangi stiker raqami oladi. Stikerlar fizik (qog'oz) bo'lib, kassirda alohida boshqariladi.

---

## 5. O'zgartiriladigan fayllar ro'yxati

### Server (`apps/ury`)

| Fayl | O'zgarish |
|---|---|
| `ury/fixtures/custom_field.json` | `POS Profile-custom_order_number_type`, `POS Invoice-custom_active_cashier_role` |
| `ury/ury/doctype/ury_pos_cashier/ury_pos_cashier.json` | `role` field |
| `ury/ury_pos/api.py` | `getPosProfile`+order_number_type, `get_pos_cashiers`+role, **yangi:** `getTables`, `getRoomsForBranch`, `freeTable`, `getPendingOrders`, `getPendingOrderCounts`, `cancel_pending_order`, `cleanup_orphan_tables`. `getRestaurantMenu` ga `idx asc` |
| `ury/ury/doctype/ury_order/ury_order.py` | `sync_order` ga `active_cashier_role` parametri, stol race-check |
| `ury/ury/hooks/ury_pos_invoice.py` | `on_submit` va `on_cancel` ga stol bo'shatish + realtime publish; `after_insert` va `on_update` realtime publish |
| `ury/hooks.py` | doc_events ro'yxatga olish |

### Client (`ury_desktop_pos`)

| Fayl | O'zgarish |
|---|---|
| `requirements.txt` | `python-socketio[client]` qo'shish |
| `core/constants.py` | `ORDER_NUMBER_LABELS`, channel nomlari |
| `core/config.py` | Yangi default keylar |
| `core/realtime.py` | **YANGI** — Frappe SocketIO klient |
| `core/connection_monitor.py` | **YANGI** — Tarmoq holatini real-time kuzatish (SocketIO + HTTP ping + grace period) |
| `ui/components/offline_block_overlay.py` | **YANGI** — Ofitsant offline blok ekrani (modal overlay) |
| `database/models.py` | **Yangi:** `Room`, `Table`. Item ga `display_idx` |
| `database/migrations.py` | Schema versiya bump |
| `database/sync.py` | `_sync_pos_profile` (yangi maydonlar); `_sync_tables_and_rooms`; `_sync_items` (idx) |
| `ui/components/cart_widget.py` | Stol/Stiker dinamik UI, "Saqlash" tugma, role visibility |
| `ui/components/table_picker.py` | **YANGI** — layout asosida picker + 🔓 Bo'shatish |
| `ui/components/checkout_window.py` | `restaurant_table` payloadga; existing Draft davom etish |
| `ui/components/pending_orders_window.py` | **YANGI** — filter chiplari, SocketIO listener |
| `ui/components/pos_closing.py` | Draft tekshiruvi + orphan cleanup |
| `ui/components/item_browser.py` | `display_idx` bo'yicha order |
| `ui/main_window.py` | Top-bar "To'lov kutilmoqda" + 🟢/🟡 realtime indicator, rol badge, role-aware |
| `ui/login_window.py` | Role avto orqali (active_cashier ichida) |
| `core/receipt_builder.py` | Stol/Stiker, ofitsant ismi |

---

## 6. Bosqichlar va vaqt

| # | Bosqich | Server | Client | Test |
|---|---|---|---|---|
| 1 | Custom fieldlar + doctype yangilanishlari | 2 | — | 1 |
| 2 | URY POS Cashier role + get_pos_cashiers | 1 | 1 | 1 |
| 3 | getPosProfile + order_number_type sync | 1 | 1 | 1 |
| 4 | getRestaurantMenu idx asc + client display_idx | 1 | 1 | 1 |
| 5 | URY Table sync (getTables, getRoomsForBranch) + lokal modellar | 2 | 3 | 2 |
| 6 | TablePickerDialog (layout + qo'lda bo'shatish) | 1 | 6 | 2 |
| 7 | Cart widget: Stol/Stiker/Saboy dinamik UI | — | 3 | 2 |
| 8 | sync_order race-check + on_submit/on_cancel hooks | 2 | — | 2 |
| 9 | SaveOrderWorker + "Saqlash" tugma | 1 | 3 | 2 |
| 10 | getPendingOrders + counts + cancel API | 3 | — | 1 |
| 11 | PendingOrdersWindow + filter chiplari | — | 5 | 3 |
| 12 | Checkout: existing Draft invoice davom | 1 | 2 | 2 |
| 13 | **Frappe SocketIO client (core/realtime.py)** | 2 | 5 | 3 |
| 14 | **ConnectionMonitor + OfflineBlockOverlay (ofitsant uchun)** | — | 3 | 2 |
| 15 | Real-time integratsiya (main_window, table_picker, pending_orders) | — | 3 | 3 |
| 16 | POS Closing: Draft tekshiruvi + orphan cleanup | 1 | 2 | 2 |
| 17 | Role-aware UI (cashier vs waiter) yakunlash | — | 2 | 2 |
| 18 | Chek shabloni va KOT | — | 1 | 1 |
| 19 | E2E test ssenariylari | — | — | 4 |

**Jami:** ~18 server soat + ~41 client soat + ~37 test soat = **~96 soat (~12-13 ish kun)**

> Eski v1 bahodan: +13 soat URY Table; +13 soat SocketIO + edge cases; +6 soat menu order; +5 soat offline blok.

---

## 7. Test ssenariylari

### 7.1 Stiker rejimi — Kassir
1. Kassir PIN → "Aziz · Kassir"
2. Savatga item, stiker #42, "Saqlash" → pending paydo, KOT oshxonaga
3. "💰 To'lov" → submit → pending dan yo'qoladi, history da

### 7.2 Stol rejimi — Kassir
1. POS Profile `Stol`, sync
2. Cart da "STOL" tugma → picker → Zal 1 / Stol 5 (band emas)
3. "Saqlash" → server Draft, `restaurant_table=T-005`, `occupied=1`
4. Boshqa POS da real-time qizil
5. To'lov → submit → stol bo'shadi → boshqa POSlarda yashil

### 7.3 Saboy + Stol rejimi
1. POS Profile `Stol`
2. Cart da `Saboy` tanlanadi → na stiker, na stol tugma ko'rinmaydi
3. "Saqlash" → KOT da "SABOY" yozuvi
4. Mijoz keladi → kassir to'lov qiladi

### 7.4 Ofitsant — kassir ko'p kassir flow
1. Ofitsant (Bekzod) tabletda PIN
2. Stol 3 ga 2 ta item, "💾 Saqlash"
3. Kassir (Aziz) o'z POS da 1-2 soniyada pending listda yangi zakaz ko'radi (SocketIO)
4. Aziz "💰 To'lov" → CheckoutWindow → submit
5. Bekzodning POSida pending dan yo'qoladi (real-time)

### 7.5 Bir vaqtda bir stol race
1. Kassir A va B bir vaqtda Stol 5 ga ursa
2. Birinchi bo'lib sync_order ga yetib kelgan g'olib, ikkinchi xato oladi
3. Ikkinchi POS da TablePicker da Stol 5 qizil ko'rinadi

### 7.6 Qo'lda stol bo'shatish
1. Kassir TablePicker da band Stol 5 ga bosadi
2. "🔓 Bo'shatish" tugma chiqadi → sabab dialog
3. Sabab: "Mijoz keta qoldi, to'lamadi"
4. `freeTable` API → log saqlanadi → real-time barcha POSlarda yashil

### 7.7 POS Closing va Draft
1. 3 ta to'lanmagan Draft bor
2. "Kassani yopish" bossadi → warning dialog
3. "Pending listni ochish" yoki "Force yopish (admin PIN)"
4. Force yopilganda — barcha Draft auto cancel, stollar bo'shaydi

### 7.8 Tarmoq uzilishi — Ofitsant (BLOK)
1. Ofitsant zakaz urayotgan paytda WiFi uziladi
2. 3-5 sek grace period o'tadi
3. To'liq ekran **blok overlay** chiqadi: "📡 Tarmoq yo'q — kassadan zakaz bering"
4. Cart yo'qolmaydi (ostida saqlanadi)
5. ESC, alt-tab ishlamaydi
6. Mijoz kassirga ketadi → kassir cart-ga item kiritib to'lov qabul qiladi
7. WiFi tiklangach overlay avto yo'qoladi
8. Ofitsant cartni davom ettirishi yoki tozalashi mumkin

### 7.9 Tarmoq uzilishi — Kassir (PendingInvoice)
1. Kassir zakaz urayotgan paytda WiFi uziladi
2. **Blok yo'q** — kassir ishlayveradi
3. "Saqlash"/"To'lov" → `PendingInvoice` (lokal)
4. KOT USB printer orqali oshxonaga chiqadi
5. Status bar: 🟠 Offline — 1 ta yuborilmagan
6. WiFi tiklangach `OfflineSyncWorker` server ga yuboradi
7. Server qabul qilgach → SocketIO event → boshqa POSlarga ko'rinadi

### 7.10 SocketIO disconnect (kassir)
1. Kassir online, lekin SocketIO uziladi (server restart)
2. HTTP API hali ishlaydi → kassir bloklanmaydi
3. Top-bar 🟡 sariq → polling fallback (10 sek)
4. Server qaytsa avto reconnect → 🟢 yashil

### 7.11 Qisqa uzilish (5 sek dan kam)
1. WiFi 2 sek ga uziladi va tiklanadi (router restart)
2. **Grace period** ichida (3 sek) overlay chiqmaydi
3. Foydalanuvchi farqlamasdan davom etadi

### 7.12 Menu item reorder
1. ERPNext da URY Menu doctype ochiladi
2. "Burger" ni yuqoriga drag-drop
3. URY Menu Item rows da `idx=1` Burger ga
4. POS sinxronlash → ItemBrowser da Burger eng birinchi

### 7.13 Orphan stol (POS Closing)
1. Server crash bo'lgan → Stol 7 `occupied=1`, lekin Draft yo'q
2. POS Closing → cleanup_orphan_tables → Stol 7 avto bo'shadi
3. Yopish dialogida xabar: "1 ta orphan stol tozalandi"

---

## 8. Risklar

| Risk | Yumshatish |
|---|---|
| `PendingInvoice` (offline) va Pending Orders (server Draft) chalkashishi | UI nomlari: `Offline navbat` vs `To'lov kutilmoqda` |
| `sync_order` payments=[] bilan `invoice_created=1` muammosi | Test: `make_invoice` mavjud Draft uchun ham ishlaydimi tekshiriladi |
| `custom_active_cashier` (full_name) vs `frappe.session.user` (email) | Client `mine_cashier_name=full_name` explicit yuboradi |
| Backward compat (eski POS Invoice) | Default `Kassir`, default `Stiker` |
| KOT ikki marta | `past_item` diff (`ury_order.py:263`) — yangi item bo'lmasa KOT yo'q |
| Stol race (ikki POS bir vaqtda) | Server-side check + realtime UI |
| Orphan occupied | POS Closing cleanup |
| SocketIO connection drop | Reconnect + polling fallback (kassir uchun); blok overlay (ofitsant uchun) |
| Tarmoq xatosi paytda saqlash | Ofitsant: blok ekran, cart saqlanadi. Kassir: `PendingInvoice` mavjud retry mexanizmi |
| Soxta offline detection (qisqa uzilish) | 3 sek grace period — qisqa uzilishlar overlay ko'rsatmaydi |
| Tarmoq qaytsa, ofitsant cartni esladimi? | Cart memory'da saqlanadi (sessiya tugamasa). Cart clear button mavjud |
| Layout 0 stollar | Fallback grid |
| python-socketio paket pyinstaller bilan | Test build qilinadi; agar muammo bo'lsa `--hidden-import` flaglar qo'shiladi |

---

## 9. Backward compatibility

- Mavjud POS Invoice lar (rol, order_number_type, restaurant_table=null) buzilmaydi
- Eski cashier — default `Kassir`
- Eski profile — default `Stiker` (hozirgi xulq saqlanadi)
- URY Menu Item idx default 0 → alphabetic fallback
- Eski clientlar SocketIO ulanmasa polling fallback ishlaydi
- Sinxronlash birinchi marta yangi config'ni yuklab oladi

---

## 10. Yo'l xaritasi (priority)

**Phase 1 (MVP — 7 ish kun):** 1, 2, 3, 5, 6, 7, 9, 10, 11, 17 — Core funksiya, SocketIOsiz
**Phase 2 (Real-time + Offline Block — 3 ish kun):** 13, 14, 15 — SocketIO + ConnectionMonitor + OfflineBlockOverlay + integratsiya
**Phase 3 (Polish — 3 ish kun):** 4, 8, 12, 16, 18, 19 — Edge cases + POS Closing + chek + tests

---

**Tasdiqlash:** _______________________   Sana: _______________________
