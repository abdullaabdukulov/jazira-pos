from core.logger import get_logger
from database.models import db, ALL_MODELS, SchemaVersion

logger = get_logger(__name__)

# Each migration is: (version, description, list_of_sql_statements)
MIGRATIONS = [
    (1, "Initial schema - create all tables", []),
    (2, "Add image column to item table", [
        "ALTER TABLE item ADD COLUMN image VARCHAR(255);",
    ]),
    (3, "Add offline_id column to pendinginvoice", [
        "ALTER TABLE pendinginvoice ADD COLUMN offline_id VARCHAR(255);",
    ]),
    (4, "Create posshift table for POS opening/closing", [
        """CREATE TABLE IF NOT EXISTS posshift (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opening_entry VARCHAR(255),
            pos_profile VARCHAR(255) NOT NULL,
            company VARCHAR(255) NOT NULL,
            user VARCHAR(255) NOT NULL,
            opening_amounts TEXT DEFAULT '{}',
            status VARCHAR(20) DEFAULT 'Open',
            opened_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            closed_at DATETIME
        );""",
        "CREATE INDEX IF NOT EXISTS idx_posshift_opening_entry ON posshift(opening_entry);",
        "CREATE INDEX IF NOT EXISTS idx_posshift_status ON posshift(status);",
    ]),
    (5, "Add sales_count and top_level columns to item (top sellers ranking)", [
        "ALTER TABLE item ADD COLUMN sales_count INTEGER DEFAULT 0;",
        "ALTER TABLE item ADD COLUMN top_level INTEGER DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_item_sales_count ON item(sales_count);",
    ]),
    (6, "Create room and restauranttable tables for Stol order_number_type mode", [
        """CREATE TABLE IF NOT EXISTS room (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) UNIQUE NOT NULL,
            branch VARCHAR(255),
            room_type VARCHAR(50),
            last_sync DATETIME DEFAULT CURRENT_TIMESTAMP
        );""",
        "CREATE INDEX IF NOT EXISTS idx_room_name ON room(name);",
        """CREATE TABLE IF NOT EXISTS restauranttable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) UNIQUE NOT NULL,
            restaurant_room VARCHAR(255),
            no_of_seats INTEGER DEFAULT 0,
            occupied INTEGER DEFAULT 0,
            is_take_away INTEGER DEFAULT 0,
            latest_invoice_time VARCHAR(50),
            layout_x REAL DEFAULT 0,
            layout_y REAL DEFAULT 0,
            layout_width REAL DEFAULT 0,
            layout_height REAL DEFAULT 0,
            table_shape VARCHAR(50),
            last_sync DATETIME DEFAULT CURRENT_TIMESTAMP
        );""",
        "CREATE INDEX IF NOT EXISTS idx_restauranttable_name ON restauranttable(name);",
        "CREATE INDEX IF NOT EXISTS idx_restauranttable_room ON restauranttable(restaurant_room);",
    ]),
]


def get_current_version() -> int:
    try:
        row = SchemaVersion.select().order_by(SchemaVersion.version.desc()).first()
        return row.version if row else 0
    except Exception:
        return 0


def initialize_db():
    db.connect(reuse_if_open=True)
    try:
        # Create all tables (safe=True skips existing)
        db.create_tables(ALL_MODELS, safe=True)

        current = get_current_version()
        if current == 0 and not _table_is_empty():
            # Existing DB without version tracking — mark all migrations as applied
            for version, desc, _ in MIGRATIONS:
                SchemaVersion.get_or_create(version=version, defaults={"description": desc})
            logger.info("Mavjud DB uchun migratsiya versiyalari qayd etildi (v%d)", MIGRATIONS[-1][0])
            return

        # Apply pending migrations
        for version, desc, statements in MIGRATIONS:
            if version <= current:
                continue
            try:
                with db.atomic():
                    for sql in statements:
                        try:
                            db.execute_sql(sql)
                        except Exception as e:
                            # Column may already exist (e.g., duplicate column error)
                            if "duplicate column" in str(e).lower():
                                logger.debug("Migratsiya v%d: ustun allaqachon mavjud, o'tkazib yuborildi", version)
                            else:
                                raise
                    SchemaVersion.create(version=version, description=desc)
                logger.info("Migratsiya v%d qo'llanildi: %s", version, desc)
            except Exception as e:
                logger.error("Migratsiya v%d xatosi: %s", version, e)
                raise
    except Exception:
        raise
    # DB ochiq qoladi — ilova hayoti davomida yopilmaydi


def _table_is_empty() -> bool:
    try:
        return SchemaVersion.select().count() == 0
    except Exception:
        return True
