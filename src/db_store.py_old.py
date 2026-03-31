from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    return create_engine(db_url, future=True)


@lru_cache(maxsize=128)
def get_user_id(username: str) -> Optional[int]:
    engine = get_engine()
    query = text("SELECT id FROM users WHERE username = :username LIMIT 1")
    with engine.connect() as conn:
        row = conn.execute(query, {"username": username}).mappings().first()
        return int(row["id"]) if row else None


def load_watchlist_from_db(username: str) -> Optional[List[str]]:
    """
    Returns:
        - None: user does not exist in DB yet (caller may fallback to local file)
        - [] or list[str]: user exists, DB is source of truth
    """
    user_id = get_user_id(username)
    if user_id is None:
        return None

    engine = get_engine()
    query = text(
        """
        SELECT ticker
        FROM watchlists
        WHERE user_id = :user_id
        ORDER BY ticker ASC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"user_id": user_id}).mappings().all()
        return [str(row["ticker"]).upper() for row in rows]



def load_holdings_from_db(username: str) -> Optional[pd.DataFrame]:
    """
    Returns:
        - None: user does not exist in DB yet (caller may fallback to local file)
        - DataFrame: DB result is source of truth
    """
    user_id = get_user_id(username)
    if user_id is None:
        return None

    engine = get_engine()
    query = text(
        """
        SELECT
            ticker,
            COALESCE(ticker, '') AS name,
            COALESCE(avg_price, 0) AS avg_price,
            COALESCE(quantity, 0) AS qty,
            COALESCE(profile_name, '') AS profile_name,
            COALESCE(status, 'active') AS status
        FROM holdings
        WHERE user_id = :user_id
        ORDER BY ticker ASC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"user_id": user_id}).mappings().all()

    if not rows:
        return pd.DataFrame(columns=["ticker", "name", "avg_price", "qty", "profile_name", "status"])

    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["name"] = df["name"].replace("", pd.NA).fillna(df["ticker"])
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors="coerce").fillna(0.0)
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)
    return df



def test_db_read(username: str = "master") -> str:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        user_id = get_user_id(username)
        if user_id is None:
            return f"DB 연결 성공 / users 테이블에 '{username}' 없음"
        return f"DB 연결 성공 / user_id={user_id}"
    except (ValueError, SQLAlchemyError) as exc:
        return f"DB 연결 실패: {exc}"
