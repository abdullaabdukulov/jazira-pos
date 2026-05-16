import datetime
import os
from peewee import (
    SqliteDatabase, Model, CharField, FloatField,
    BooleanField, DateTimeField, TextField, IntegerField,
)

db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pos_data.db")
db = SqliteDatabase(db_path, pragmas={"journal_mode": "wal", "foreign_keys": 1})


class BaseModel(Model):
    class Meta:
        database = db


class Item(BaseModel):
    item_code = CharField(unique=True, index=True)
    item_name = CharField()
    item_group = CharField(null=True)
    course = CharField(null=True)
    barcode = CharField(null=True, index=True)
    uom = CharField(null=True)
    image = CharField(null=True)
    has_batch_no = BooleanField(default=False)
    is_stock_item = BooleanField(default=True)
    # Top sotuv darajasi — server tomondan oxirgi 30 kun sotuv statistikasi
    # bo'yicha keladi. 0 = oddiy, 1=top, 2=top-2, 3=top-3 (eng zo'r).
    # UI da rim raqami (I, II, III) bilan badge ko'rsatiladi.
    sales_count = IntegerField(default=0, index=True)
    top_level = IntegerField(default=0)  # 0..3 (rim raqami uchun)
    # URY Menu Item.idx — admin ERPNext da drag-drop bilan o'zgartiriladi.
    # ItemBrowser orderlash uchun (TZ Phase 3).
    display_idx = IntegerField(default=0, index=True)
    last_sync = DateTimeField(default=datetime.datetime.now)


class Customer(BaseModel):
    name = CharField(unique=True, index=True)
    customer_name = CharField()
    customer_group = CharField(null=True)
    phone = CharField(null=True)
    last_sync = DateTimeField(default=datetime.datetime.now)


class ItemPrice(BaseModel):
    name = CharField(unique=True)
    item_code = CharField(index=True)
    price_list = CharField()
    price_list_rate = FloatField(default=0.0)
    currency = CharField(default="UZS")
    last_sync = DateTimeField(default=datetime.datetime.now)


class Room(BaseModel):
    """URY Room — filial ichidagi xona. Stol rejimida ishlatiladi."""
    name = CharField(unique=True, index=True)
    branch = CharField(null=True)
    room_type = CharField(null=True)  # AC / NON-AC
    last_sync = DateTimeField(default=datetime.datetime.now)


class RestaurantTable(BaseModel):
    """URY Table — restorandagi stol. Stol rejimida TablePicker ko'rsatadi.

    Model nomi `RestaurantTable` chunki `table` SQL reserved word va peewee
    `Table` klassi ham mavjud. SQLite tabel nomi: `restauranttable`.
    """
    name = CharField(unique=True, index=True)             # URY Table.name
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


class PendingInvoice(BaseModel):
    offline_id = CharField(null=True, index=True)
    invoice_data = TextField()
    status = CharField(default="Pending")
    error_message = TextField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)


class PosShift(BaseModel):
    opening_entry = CharField(null=True, index=True)
    pos_profile = CharField()
    company = CharField()
    user = CharField()
    opening_amounts = TextField(default="{}")
    status = CharField(default="Open")  # Open / Closed
    opened_at = DateTimeField(default=datetime.datetime.now)
    closed_at = DateTimeField(null=True)


class SchemaVersion(BaseModel):
    version = IntegerField(unique=True)
    applied_at = DateTimeField(default=datetime.datetime.now)
    description = CharField(default="")


ALL_MODELS = [Item, Customer, ItemPrice, Room, RestaurantTable, PendingInvoice, PosShift, SchemaVersion]
