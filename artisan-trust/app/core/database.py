from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """
    Applies the Plumbline schema with engine-level self-referential integrity.
    Rejects any insertion whose parent_hash is not already an immutable current_hash.
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS merkle_ledger (
        id SERIAL PRIMARY KEY,
        parent_hash TEXT REFERENCES merkle_ledger(current_hash),
        transaction_payload JSONB NOT NULL,
        timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        current_hash TEXT UNIQUE NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_merkle_parent_hash ON merkle_ledger(parent_hash);
    CREATE INDEX IF NOT EXISTS idx_merkle_current_hash ON merkle_ledger(current_hash);
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
