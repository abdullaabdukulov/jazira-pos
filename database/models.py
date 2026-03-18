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
    barcode = CharField(null=True, index=True)
    uom = CharField(null=True)
    image = CharField(null=True)
    has_batch_no = BooleanField(default=False)
    is_stock_item = BooleanField(default=True)
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


ALL_MODELS = [Item, Customer, ItemPrice, PendingInvoice, PosShift, SchemaVersion]
