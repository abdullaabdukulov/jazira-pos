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
    finally:
        if not db.is_closed():
            db.close()


def _table_is_empty() -> bool:
    try:
        return SchemaVersion.select().count() == 0
    except Exception:
        return True
