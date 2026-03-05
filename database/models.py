from peewee import SqliteDatabase, Model, CharField, FloatField, BooleanField, DateTimeField, TextField
import datetime
import os

# Create DB file in the project folder
db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pos_data.db')
db = SqliteDatabase(db_path)

class BaseModel(Model):
    class Meta:
        database = db

class Item(BaseModel):
    item_code = CharField(unique=True, index=True)
    item_name = CharField()
    item_group = CharField(null=True)
    barcode = CharField(null=True, index=True)
    uom = CharField(null=True)
    image = CharField(null=True) # To store the image URL/path
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
    name = CharField(unique=True) # Usually Item Price ID
    item_code = CharField(index=True)
    price_list = CharField()
    price_list_rate = FloatField(default=0.0)
    currency = CharField(default="UZS")
    last_sync = DateTimeField(default=datetime.datetime.now)

class PendingInvoice(BaseModel):
    invoice_data = TextField() # JSON stringified data
    status = CharField(default="Pending") # Pending, Synced, Failed
    error_message = TextField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)

def initialize_db():
    db.connect(reuse_if_open=True)
    db.create_tables([Item, Customer, ItemPrice, PendingInvoice], safe=True)
    
    # Migration: Check if 'image' column exists in 'item' table
    columns = [c.name for c in db.get_columns('item')]
    if 'image' not in columns:
        try:
            db.execute_sql('ALTER TABLE item ADD COLUMN image VARCHAR(255);')
            print("Migration: Added 'image' column to 'item' table.")
        except Exception as e:
            print(f"Migration error: {e}")
            
    db.close()
