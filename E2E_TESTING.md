# E2E Test ssenariylari — URY Desktop POS

**Versiya:** Phase 1 + 2 + 3 (TZ v2)
**Sana:** 2026-05-17
**Maqsad:** Real device va real serverda funksional tekshirish.

---

## Tayyorgarlik

### Server tomon (jazira.local)

```bash
cd ~/frappe-projects/bench_v15
bench --site jazira.local migrate     # Custom fieldlar va doctype yangilanishi
bench --site jazira.local clear-cache
bench restart                          # gunicorn + socketio
```

### Sozlash (ERPNext)

1. **URY POS Cashier** ro'yxati:
   - Kamida 1 ta **Kassir** rolida (PIN bilan)
   - Kamida 1 ta **Ofitsant** rolida (PIN bilan)
2. **POS Profile**:
   - `Buyurtma raqami turi`: testdan kelib chiqib `Stiker` yoki `Stol` ga sozlash
   - `Multiple Cashier` — ixtiyoriy
3. **URY Table**:
   - Kamida 5 ta stol kiritilgan (layout_x/y bilan yoki bo'lmasa fallback grid)
   - Stollar `URY Room` ga biriktirilgan
4. **URY Menu Item**:
   - Eng kamida 10 ta item, `idx` bilan tartiblash mumkin (drag-drop)

### Client tomon

```bash
cd ~/frappe-projects/bench_v15/ury_desktop_pos
source venv/bin/activate
pip install -r requirements.txt        # python-socketio[client] uchun
python main.py
```

Birinchi sinx → POS Profile, kassirlar, stollar va items yuklanadi.

---

## Test ssenariylari

### 7.1 — Stiker rejimi, Kassir flow

**POS Profile:** `Buyurtma raqami turi = Stiker`

1. Kassir PIN bilan kirsa, top-bar da `👤 Aziz · Kassir` (ko'k badge) ko'rinadi
2. Itemlardan 3 tasini cartga qo'shadi
3. "STIKER" inputiga `42` kiritadi
4. `💾 Saqlash` bossadi → toast: "Buyurtma saqlandi"
5. Cart bo'shaydi, KOT oshxonaga chiqadi
6. Top-bar: `To'lov kutilmoqda: 1` rangli paydo bo'ladi
7. Top-bar `To'lov kutilmoqda` ni bossadi → panel ochiladi, zakaz ko'rinadi
8. `💰 To'lov` bossadi → CheckoutWindow ochiladi
9. Naqd `50000` kiritadi → submit → "To'lov muvaffaqiyatli"
10. Pending listdan zakaz yo'qoladi, History da paydo bo'ladi

**Kutilgan:** ✅ KOT oshxonaga, mijoz cheki "Stiker №42" bilan, history da Paid status.

---

### 7.2 — Stol rejimi, Kassir flow

**POS Profile:** `Buyurtma raqami turi = Stol`

1. Kassir kiradi, sync qiladi
2. Cart da `Shu yerda` tanlanganda **STIKER input yo'q**, `STOL` tugma ko'rinadi
3. `STOL` tugmasini bossadi → TablePicker ochiladi
4. Layout x/y bo'yicha stollar absolute pozitsiyada chiqadi (yoki grid fallback)
5. Stol 5 ga bossadi (bo'sh, yashil rang)
6. Cartda `Stol 5` ko'rsatiladi
7. Item qo'shadi, `💾 Saqlash` bossadi
8. Server: `URY Table.occupied = 1` (boshqa POSlarda real-time qizil)
9. To'lov → `URY Table.occupied = 0` (boshqalarda yashil)

**Kutilgan:** ✅ Chekda `Stol: Zal 1 / 5`, KOT da xuddi shunday.

---

### 7.3 — Saboy + Stol rejimi (raqamsiz)

**POS Profile:** `Buyurtma raqami turi = Stol`

1. Cart da `Saboy` tanlanadi → na stiker, na stol tugma ko'rinmaydi
2. Item qo'shib `💾 Saqlash` bossadi → muvaffaqiyatli
3. KOT da "SABOY" yozuvi (raqamsiz)
4. Chekda "Stol: ..." yo'q, "Stiker №..." ham yo'q

**Kutilgan:** ✅ Faqat order_type "Saboy" KOT da chiqadi.

---

### 7.4 — Ofitsant → Kassir flow (real-time SocketIO)

**Talab:** 2 ta qurilma (yoki 2 ta POS instance bir kompyuterda)

1. **POS A**: Ofitsant (Bekzod) PIN bilan kirsa, top-bar `👤 Bekzod · Ofitsant` (binafsha badge)
2. **POS B**: Kassir (Aziz) PIN bilan kirsa, `👤 Aziz · Kassir` (ko'k badge)
3. **POS A**: Ofitsant cartda **`💰 To'lov` tugmasi YO'Q** — faqat `💾 Saqlash`
4. **POS A**: Stol 3 ga 2 ta item qo'shib `💾 Saqlash` bossadi
5. **POS B**: 1-2 sek ichida `To'lov kutilmoqda` count `0 → 1` ga ko'tariladi (SocketIO)
6. **POS B**: Kassir panelni ochsa, Bekzod yaratgan zakaz `Ofitsant: Bekzod` bilan ko'rinadi
7. **POS B**: Kassir `💰 To'lov` bossadi → CheckoutWindow → submit
8. **POS A**: Pending listdan zakaz yo'qoladi (real-time)
9. **POS A**: Stol 3 yashil rangga qaytadi

**Kutilgan:** ✅ Latency < 2 sek, ikkala POS da bir xil holat.

---

### 7.5 — Ofitsant faqat o'zinikini ko'radi

**Talab:** 2 ofitsant + 1 kassir

1. Ofitsant1 (Bekzod) 2 ta zakaz qiladi
2. Ofitsant2 (Karim) 3 ta zakaz qiladi
3. **Bekzod POSida** pending list → faqat 2 ta (Karim'ning ko'rinmaydi)
4. **Karim POSida** pending list → faqat 3 ta
5. **Kassir POSida** → 5 ta hammasi ko'rinadi
6. Ofitsantning panelda `💰 To'lov` va `✕ Bekor` tugmalari **YO'Q** (read-only)

**Kutilgan:** ✅ `only_mine=1` filter ofitsantda, kassir hammasini ko'radi.

---

### 7.6 — Stol race condition

**Talab:** 2 kassir

1. **Kassir A**: TablePicker ochib Stol 5 ni bo'shligini ko'radi
2. **Kassir B**: Tezroq Stol 5 ga item qo'shib `💾 Saqlash` bossadi
3. **Kassir A**: 1 sek ichida Stol 5 qizil bo'ladi (SocketIO realtime)
4. **Kassir A**: Agar Stol 5 ga ursa → server `table_busy` qaytaradi
5. Foydalanuvchi: "Server rad etdi: Stol T-005 boshqa POS da band (zakaz: INV-...)"

**Kutilgan:** ✅ Real-time picker, server-side race-check.

---

### 7.7 — Qo'lda stol bo'shatish

1. Stol 7 band (latest zakaz qoldi, lekin to'lov qabul qilinmagan)
2. Kassir TablePicker da Stol 7 ni bossadi (qizil)
3. `🔓 Bo'shatish` tugmasi chiqadi
4. Sabab dialog: "Mijoz keta qoldi, to'lamadi" → tasdiqlash
5. Server: `freeTable` API → `URY Table.occupied = 0`, Comment audit log
6. Realtime `table_freed` event → barcha POSlarda Stol 7 yashil

**Kutilgan:** ✅ Audit log Comment'da, real-time UI yangilanish.

---

### 7.8 — POS Closing va Draft buyurtmalar

1. 3 ta to'lanmagan Draft mavjud
2. Kassir `🔒 Kassa yopish` bossadi
3. Warning dialog: "3 ta to'lanmagan buyurtma bor"
4. `Ko'rib chiqish` → pending panel ochiladi
5. Hammasini to'lab tugatish yoki cancel qilish
6. Qaytib `Kassa yopish` → endi tekshiruv o'tib, normal flow

**Kutilgan:** ✅ Kassir ehtibor qaratadi.

---

### 7.9 — Orphan stol cleanup

**Tayyorgarlik:** DB da Stol 8 `occupied=1` lekin active Draft yo'q (manual `frappe.db.set_value`)

1. Kassir `🔒 Kassa yopish` bossadi (Draft yo'q bo'lsa)
2. Tasdiqlangach background da `cleanupOrphanTables` chaqiriladi
3. Stol 8 avto bo'shaydi → status bar: "Orphan stollar tozalandi: 1 ta"

**Kutilgan:** ✅ Logs/UI da habar.

---

### 7.10 — Tarmoq uzilishi: OFITSANT (blok ekran)

1. Ofitsant POS ishlayotgan paytda WiFi/Ethernet uziladi
2. **3-5 sek grace period** ichida hech narsa o'zgarmaydi (qisqa uzilish himoyasi)
3. 5 sek o'tgach: to'liq ekran **blok overlay** chiqadi
   - 📡 ❌ Tarmoq bilan aloqa yo'q
   - "Iltimos, mijozni kassaga yuboring"
   - `⟳ Qayta urinish` + `📞 Yordam` tugmalari
   - "Tekshirilmoqda... N sek o'tdi"
4. ESC, Alt+Tab ishlamaydi
5. Cart ostida saqlanadi (yo'qolmaydi)
6. WiFi qaytarilgach 1-3 sek ichida overlay **avto yashirinadi**
7. Cart joyida turibdi, davom ettirish mumkin

**Kutilgan:** ✅ Ofitsant zakaz urolmaydi offline da.

---

### 7.11 — Tarmoq uzilishi: KASSIR (offline ishlash)

1. Kassir POS ishlayotgan paytda WiFi uziladi
2. **Blok overlay yo'q** — kassir normal ishlayveradi
3. Top-bar wifi 🔴 Offline rangga o'tadi
4. `💰 To'lov` qiladi → tarmoq xatosi → `PendingInvoice` lokalga
5. Status bar: `🟠 Offline — 1 ta yuborilmagan`
6. KOT USB printerga chiqadi (lokal)
7. WiFi qaytarilgach `OfflineSyncWorker` avto retry → server qabul qiladi
8. SocketIO orqali boshqa POSlarga ko'rinadi

**Kutilgan:** ✅ Hech qaysi zakaz yo'qolmaydi.

---

### 7.12 — Qisqa tarmoq uzilishi (grace period)

1. Ofitsant POSi ishlayotganda WiFi 2 sek ga uziladi (router restart)
2. **3 sek grace period** ichida bekor qilinadi
3. Blok overlay **chiqmaydi**, foydalanuvchi farqlamaydi

**Kutilgan:** ✅ Soxta offline detection bo'lmaydi.

---

### 7.13 — Menu item drag-drop reorder

1. ERPNext da URY Menu ochiladi (Burger 5-pozitsiyada turibdi)
2. Admin Burger ni 1-pozitsiyaga drag-drop qiladi → `idx=1`
3. Save bosadi
4. POS da `Sinxronlash` bossadi
5. ItemBrowser da Burger eng birinchi ko'rinadi

**Kutilgan:** ✅ Admin `idx` orqali tartibni boshqaradi.

---

### 7.14 — Pending order cancel + Cancel KOT

1. Kassir yoki ofitsant zakaz qiladi (`💾 Saqlash`)
2. Pending listdan zakazga bossadi
3. `✕ Bekor` tugmasi (kassir uchun)
4. Sabab dialog: "Mijoz fikrini o'zgartirdi"
5. Server: POS Invoice cancel + Cancel KOT chiqadi (oshxonaga)
6. Stol bo'shaydi (stol rejimida)
7. Realtime `pending_order_cancelled` → boshqa POSlarda yo'qoladi

**Kutilgan:** ✅ Cancel KOT printerda, audit log saqlanadi.

---

### 7.15 — SocketIO disconnect, polling fallback (kassir)

1. Kassir online, SocketIO ulangan
2. Server SocketIO process restart (gunicorn ham emas)
3. **Blok yo'q** (kassir rolida)
4. ConnectionMonitor: SocketIO disconnect → grace → HTTP ping fallback (10 sek)
5. HTTP API hali ishlaydi → state ONLINE bo'lib qoladi
6. Server SocketIO qaytsa auto-reconnect → realtime tiklanadi

**Kutilgan:** ✅ Kassir to'xtamaydi.

---

## Smoke test checklist (qisqa ro'yxat)

- [ ] Server `bench migrate` muvaffaqiyatli, custom fieldlar va doctype yangilanishlar qabul qilindi
- [ ] Client login (PIN orqali) — Kassir va Ofitsant rollarida ishlaydi
- [ ] POS Profile sinx natijasi: `order_number_type` config.json ga tushdi
- [ ] Item sync da `display_idx` qaytarilyapti va lokal saqlanyapti
- [ ] TablePicker layout to'g'ri (yoki grid fallback)
- [ ] `💾 Saqlash` ishlaydi (Draft yaratiladi, KOT chiqadi)
- [ ] `💰 To'lov` kassir uchun pending listda ishlaydi (existing invoice davom)
- [ ] SocketIO `pending_order_created` 2 ta POS o'rtasida ishlaydi
- [ ] SocketIO `table_occupied / table_freed` real-time
- [ ] Ofitsant offline → blok overlay 5 sek dan keyin
- [ ] Tarmoq qaytsa overlay avto yashirinadi
- [ ] POS Closing oldida pending tekshiruvi
- [ ] Chekda `Stol: Zal 1 / 5` yoki `Stiker №42` va `Ofitsant: ...`

---

## Diagnostika

**Tarmoq holatini tekshirish (overlay'dagi Yordam tugma):**
```
FRAPPE_URL: http://jazira.local:8000
SocketIO ulangan: True/False
Tarmoq holati: online/offline/checking
Foydalanuvchi: Aziz Karimov (Kassir)
```

**Log:**
- Client: `ury_desktop_pos/logs/pos.log`
- Server: `~/frappe-projects/bench_v15/logs/web.error.log`

**SocketIO event'larni qo'lda yuborish (server console):**
```python
import frappe
frappe.publish_realtime("pending_order_created", {
    "invoice": "POS-TEST-001",
    "branch": "Saripul",
    "order_type": "Dine In",
}, after_commit=True)
```
