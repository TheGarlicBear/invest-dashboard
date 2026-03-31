
"""
Seed one user's existing local data into PostgreSQL.

Default target user: master

What this script does:
1) Reads DATABASE_URL from .env / environment
2) Ensures the target user exists in users table
3) Loads local watchlist from data/watchlists/<username>.json
4) Loads local holdings from data/holdings/<username>.csv
5) Upserts them into watchlists / holdings tables

Usage:
    python3 src/seed_user_to_db.py
    python3 src/seed_user_to_db.py master
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
AUTH_FILE = DATA_DIR / "auth" / "users.json"
WATCHLIST_DIR = DATA_DIR / "watchlists"
HOLDINGS_DIR = DATA_DIR / "holdings"


def get_engine() -> Engine:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    return create_engine(db_url, future=True)


def load_users_json() -> Dict[str, Any]:
    if not AUTH_FILE.exists():
        return {}
    with AUTH_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def extract_user_record(users_data: Dict[str, Any], username: str) -> Dict[str, Any]:
    """
    Accept several possible users.json shapes:
    - {"master": {"password_hash": "...", "role": "user"}}
    - {"master": {"password": "..."}}
    - {"users": {"master": {...}}}
    """
    if username in users_data and isinstance(users_data[username], dict):
        return users_data[username]

    nested = users_data.get("users")
    if isinstance(nested, dict) and isinstance(nested.get(username), dict):
        return nested[username]

    return {}


def resolve_password_hash(user_record: Dict[str, Any], username: str) -> str:
    # Prefer an existing hash-like field if present.
    for key in ("password_hash", "hash", "pw_hash", "passwd_hash"):
        value = user_record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Fall back to raw password if that is what the current app stores.
    for key in ("password", "passwd", "pw"):
        value = user_record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Last resort placeholder so row can exist for foreign keys / later migration.
    return f"seeded-no-password::{username}"


def resolve_role(user_record: Dict[str, Any]) -> str:
    role = user_record.get("role", "user")
    if not isinstance(role, str) or not role.strip():
        return "user"
    return role.strip()


def ensure_user(engine: Engine, username: str) -> int:
    users_data = load_users_json()
    user_record = extract_user_record(users_data, username)
    password_hash = resolve_password_hash(user_record, username)
    role = resolve_role(user_record)

    upsert_sql = text(
        """
        INSERT INTO users (username, password_hash, role)
        VALUES (:username, :password_hash, :role)
        ON CONFLICT (username)
        DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            role = EXCLUDED.role
        RETURNING id
        """
    )

    with engine.begin() as conn:
        user_id = conn.execute(
            upsert_sql,
            {
                "username": username,
                "password_hash": password_hash,
                "role": role,
            },
        ).scalar_one()
    return int(user_id)


def load_local_watchlist(username: str) -> List[str]:
    path = WATCHLIST_DIR / f"{username}.json"
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items: List[str] = []
    if isinstance(data, list):
        items = [str(x).strip().upper() for x in data if str(x).strip()]
    elif isinstance(data, dict):
        # Defensive: allow {"tickers": [...]}
        tickers = data.get("tickers", [])
        if isinstance(tickers, list):
            items = [str(x).strip().upper() for x in tickers if str(x).strip()]

    # de-dup while preserving order
    return list(dict.fromkeys(items))


def load_local_holdings(username: str) -> pd.DataFrame:
    path = HOLDINGS_DIR / f"{username}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["ticker", "avg_price", "qty", "profile_name"])

    df = pd.read_csv(path)

    # Normalize likely column names from the existing app.
    rename_map = {}
    for col in df.columns:
        c = str(col).strip().lower()
        if c in ("ticker", "code", "symbol"):
            rename_map[col] = "ticker"
        elif c in ("avg_price", "average_price", "buy_price", "avg"):
            rename_map[col] = "avg_price"
        elif c in ("qty", "quantity", "count", "shares"):
            rename_map[col] = "qty"
        elif c in ("profile_name", "profile", "profile_label"):
            rename_map[col] = "profile_name"
        elif c in ("status",):
            rename_map[col] = "status"
        elif c in ("name", "stock_name"):
            rename_map[col] = "name"

    df = df.rename(columns=rename_map)

    # Create missing columns if needed
    for col, default in (
        ("ticker", ""),
        ("avg_price", 0.0),
        ("qty", 0.0),
        ("profile_name", ""),
        ("status", "active"),
    ):
        if col not in df.columns:
            df[col] = default

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["ticker"] != ""].copy()

    df["avg_price"] = pd.to_numeric(df["avg_price"], errors="coerce").fillna(0.0)
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)
    df["profile_name"] = df["profile_name"].fillna("").astype(str)
    df["status"] = df["status"].fillna("active").astype(str)

    return df[["ticker", "avg_price", "qty", "profile_name", "status"]]


def seed_watchlist(engine: Engine, user_id: int, tickers: List[str]) -> int:
    # Make DB the source of truth for this user.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlists WHERE user_id = :user_id"), {"user_id": user_id})
        for ticker in tickers:
            conn.execute(
                text(
                    """
                    INSERT INTO watchlists (user_id, ticker)
                    VALUES (:user_id, :ticker)
                    ON CONFLICT (user_id, ticker) DO NOTHING
                    """
                ),
                {"user_id": user_id, "ticker": ticker},
            )
    return len(tickers)


def seed_holdings(engine: Engine, user_id: int, df: pd.DataFrame) -> int:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM holdings WHERE user_id = :user_id"), {"user_id": user_id})
        for _, row in df.iterrows():
            conn.execute(
                text(
                    """
                    INSERT INTO holdings (user_id, ticker, quantity, avg_price, profile_name, status)
                    VALUES (:user_id, :ticker, :quantity, :avg_price, :profile_name, :status)
                    ON CONFLICT (user_id, ticker)
                    DO UPDATE SET
                        quantity = EXCLUDED.quantity,
                        avg_price = EXCLUDED.avg_price,
                        profile_name = EXCLUDED.profile_name,
                        status = EXCLUDED.status,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "user_id": user_id,
                    "ticker": str(row["ticker"]),
                    "quantity": float(row["qty"]),
                    "avg_price": float(row["avg_price"]),
                    "profile_name": str(row["profile_name"]) if pd.notna(row["profile_name"]) else "",
                    "status": str(row["status"]) if pd.notna(row["status"]) else "active",
                },
            )
    return int(len(df))


def main() -> None:
    username = sys.argv[1].strip() if len(sys.argv) > 1 else "master"
    engine = get_engine()

    with engine.connect() as conn:
        ok = conn.execute(text("SELECT 1")).scalar()
        print(f"DB connection OK: {ok}")

    user_id = ensure_user(engine, username)
    print(f"user upserted: username={username}, id={user_id}")

    watchlist = load_local_watchlist(username)
    watch_count = seed_watchlist(engine, user_id, watchlist)
    print(f"watchlists seeded: {watch_count}")

    holdings_df = load_local_holdings(username)
    holdings_count = seed_holdings(engine, user_id, holdings_df)
    print(f"holdings seeded: {holdings_count}")

    print("Seed complete.")


if __name__ == "__main__":
    main()
