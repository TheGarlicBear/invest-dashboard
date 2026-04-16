import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(dotenv_path=Path(".env"))


class DBStore:
    def __init__(self):
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL not set")
        self.engine = create_engine(db_url)

    def _get_user_id(self, username: str):
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
            if not row:
                return None
            return row[0]

    def load_watchlist(self, username: str):
        user_id = self._get_user_id(username)
        if user_id is None:
            return []

        with self.engine.begin() as conn:
            rows = conn.execute(
                text("""
                    SELECT ticker
                    FROM watchlists
                    WHERE user_id = :uid
                    ORDER BY id
                """),
                {"uid": user_id},
            ).fetchall()

        return [r[0] for r in rows]

    def load_holdings(self, username: str):
        user_id = self._get_user_id(username)
        if user_id is None:
            return pd.DataFrame(columns=["ticker", "quantity", "avg_price", "status"])

        with self.engine.begin() as conn:
            rows = conn.execute(
                text("""
                    SELECT ticker, quantity, avg_price, status
                    FROM holdings
                    WHERE user_id = :uid
                    ORDER BY id
                """),
                {"uid": user_id},
            ).mappings().all()

        return pd.DataFrame(rows)

def save_watchlist(self, username: str, items):
    user_id = self._get_user_id(username)
    if user_id is None:
        raise ValueError(f"user not found: {username}")

    clean_items = []
    seen = set()

    for item in items:
        if isinstance(item, dict):
            ticker = str(item.get("ticker", "")).strip().upper()
            score = item.get("attractiveness_score", 3)
        else:
            ticker = str(item).strip().upper()
            score = 3

        try:
            score = int(score)
        except Exception:
            score = 3

        score = max(1, min(5, score))

        if ticker and ticker not in seen:
            clean_items.append({
                "ticker": ticker,
                "attractiveness_score": score,
            })
            seen.add(ticker)

    with self.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM watchlists WHERE user_id = :uid"),
            {"uid": user_id},
        )

        for item in clean_items:
            conn.execute(
                text("""
                    INSERT INTO watchlists (user_id, ticker, attractiveness_score, created_at)
                    VALUES (:uid, :ticker, :score, now())
                """),
                {
                    "uid": user_id,
                    "ticker": item["ticker"],
                    "score": item["attractiveness_score"],
                },
            )

    return clean_items

    def save_holdings(self, username: str, df: pd.DataFrame):
        user_id = self._get_user_id(username)
        if user_id is None:
            raise ValueError(f"user not found: {username}")

        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM holdings WHERE user_id = :uid"),
                {"uid": user_id},
            )

            if df is None or df.empty:
                return

            for _, row in df.iterrows():
                ticker = str(row.get("ticker", "")).strip().upper()
                if not ticker:
                    continue

                quantity = float(row.get("quantity", 0) or 0)
                avg_price = float(row.get("avg_price", 0) or 0)
                status = str(row.get("status", "active") or "active")

                conn.execute(
                    text("""
                        INSERT INTO holdings
                        (user_id, ticker, quantity, avg_price, status, created_at, updated_at)
                        VALUES (:uid, :ticker, :quantity, :avg_price, :status, now(), now())
                    """),
                    {
                        "uid": user_id,
                        "ticker": ticker,
                        "quantity": quantity,
                        "avg_price": avg_price,
                        "status": status,
                    },
                )
