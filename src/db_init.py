"""
Initialize PostgreSQL tables for invest-dashboard.

Usage:
    python3 src/db_init.py
"""

from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Text,
    text,
)
from sqlalchemy.exc import SQLAlchemyError


def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    return create_engine(db_url, future=True)


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(100), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(50), nullable=False, server_default=text("'user'")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

watchlists = Table(
    "watchlists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", String(50), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("user_id", "ticker", name="uq_watchlists_user_ticker"),
)

holdings = Table(
    "holdings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", String(50), nullable=False),
    Column("quantity", Numeric(18, 4), nullable=False, server_default=text("0")),
    Column("avg_price", Numeric(18, 4), nullable=False, server_default=text("0")),
    Column("profile_name", String(100), nullable=True),
    Column("status", String(30), nullable=False, server_default=text("'active'")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("user_id", "ticker", name="uq_holdings_user_ticker"),
)

holding_transactions = Table(
    "holding_transactions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", String(50), nullable=False),
    Column("tx_type", String(30), nullable=False),
    Column("quantity", Numeric(18, 4), nullable=False),
    Column("price", Numeric(18, 4), nullable=False),
    Column("amount", Numeric(18, 4), nullable=True),
    Column("fee", Numeric(18, 4), nullable=True, server_default=text("0")),
    Column("memo", Text, nullable=True),
    Column("executed_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)


def main():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            value = conn.execute(text("SELECT 1")).scalar()
            print(f"DB connection OK: {value}")

        metadata.create_all(engine)
        print("Tables created or already exist:")
        for table_name in metadata.tables:
            print(f" - {table_name}")

    except (ValueError, SQLAlchemyError) as e:
        print(f"DB init failed: {e}")
        raise


if __name__ == "__main__":
    main()
