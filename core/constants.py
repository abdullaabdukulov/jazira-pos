# API timeouts (seconds)
API_TIMEOUT_SHORT = 5
API_TIMEOUT_DEFAULT = 10
API_TIMEOUT_LONG = 15
IMAGE_TIMEOUT = 2

# Database
ITEM_LOAD_LIMIT = 100
CUSTOMER_SYNC_LIMIT = 1000
HISTORY_FETCH_LIMIT = 50

# Offline sync interval (seconds)
OFFLINE_SYNC_INTERVAL = 30

# Monitor interval (milliseconds)
MONITOR_INTERVAL_MS = 10000

# Default values
DEFAULT_CURRENCY = "UZS"
DEFAULT_CUSTOMER = ""
DEFAULT_UOM = "Dona"
DEFAULT_PRICE_LIST = "Standard"

# Stiker rejimida ushbu order_type'lar uchun stiker raqami talab qilinadi
TICKET_ORDER_TYPES = ["Shu yerda", "Saboy"]

# Stol rejimida faqat ushbu order_type stol talab qiladi (TZ 4.1.1)
# Saboy stolsiz — KOT da "Saboy" yozuvi
TABLE_ORDER_TYPES = ["Shu yerda"]

# All order types
ORDER_TYPES = ["Shu yerda", "Saboy", "Dastavka", "Dastavka Saboy"]

# UI order type → Frappe server order type mapping
ORDER_TYPE_MAP = {
    "Shu yerda": "Dine In",
    "Saboy": "Take Away",
    "Dastavka": "Delivery",
    "Dastavka Saboy": "Delivery",
}

# Order number type values (POS Profile custom_order_number_type)
ORDER_NUMBER_TYPE_STICKER = "Stiker"
ORDER_NUMBER_TYPE_TABLE = "Stol"
