from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base for models
Base = declarative_base()


def get_db():
    """Dependency for getting DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Enable JSON support in PostgreSQL
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Enable JSON support."""
    pass  # psycopg2 automatically supports JSON


def ensure_admin_role_column() -> None:
    """create_all never alters an existing table: add admin.role to databases
    created before roles existed (existing accounts stay full admins)."""
    from sqlalchemy import inspect, text

    if "role" in {c["name"] for c in inspect(engine).get_columns("admin")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE admin ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'ADMIN'"))
