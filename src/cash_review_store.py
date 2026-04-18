
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(dotenv_path=Path(".env"))


class CashReviewStore:
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
            return row[0] if row else None

    def get_cash_balances(self, username: str) -> dict:
        user_id = self._get_user_id(username)
        if user_id is None:
            return {"KRW": 0.0, "USD": 0.0}

        with self.engine.begin() as conn:
            rows = conn.execute(
                text("""
                    SELECT currency, balance
                    FROM cash_balances
                    WHERE user_id = :uid
                """),
                {"uid": user_id},
            ).mappings().all()

        balances = {"KRW": 0.0, "USD": 0.0}
        for row in rows:
            balances[str(row["currency"]).upper()] = float(row["balance"] or 0)
        return balances

    def set_cash_balance(self, username: str, currency: str, balance: float, memo: str = "manual_adjust"):
        user_id = self._get_user_id(username)
        if user_id is None:
            raise ValueError(f"user not found: {username}")

        currency = str(currency).upper().strip()
        balance = float(balance or 0)

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO cash_balances (user_id, currency, balance, updated_at)
                    VALUES (:uid, :currency, :balance, now())
                    ON CONFLICT (user_id, currency)
                    DO UPDATE SET balance = EXCLUDED.balance, updated_at = now()
                """),
                {"uid": user_id, "currency": currency, "balance": balance},
            )
            conn.execute(
                text("""
                    INSERT INTO cash_ledger (user_id, currency, entry_type, amount, memo, created_at)
                    VALUES (:uid, :currency, 'manual_adjust', :amount, :memo, now())
                """),
                {"uid": user_id, "currency": currency, "amount": balance, "memo": memo},
            )

    def adjust_cash(self, username: str, currency: str, delta: float, memo: str, ref_tx_id=None):
        user_id = self._get_user_id(username)
        if user_id is None:
            raise ValueError(f"user not found: {username}")

        currency = str(currency).upper().strip()
        delta = float(delta or 0)

        with self.engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT balance
                    FROM cash_balances
                    WHERE user_id = :uid AND currency = :currency
                """),
                {"uid": user_id, "currency": currency},
            ).fetchone()

            current = float(row[0] or 0) if row else 0.0
            new_balance = current + delta

            conn.execute(
                text("""
                    INSERT INTO cash_balances (user_id, currency, balance, updated_at)
                    VALUES (:uid, :currency, :balance, now())
                    ON CONFLICT (user_id, currency)
                    DO UPDATE SET balance = EXCLUDED.balance, updated_at = now()
                """),
                {"uid": user_id, "currency": currency, "balance": new_balance},
            )

            conn.execute(
                text("""
                    INSERT INTO cash_ledger (user_id, currency, entry_type, amount, memo, ref_tx_id, created_at)
                    VALUES (:uid, :currency, 'trade_adjust', :amount, :memo, :ref_tx_id, now())
                """),
                {
                    "uid": user_id,
                    "currency": currency,
                    "amount": delta,
                    "memo": memo,
                    "ref_tx_id": ref_tx_id,
                },
            )

        return new_balance

    def load_cash_ledger(self, username: str, limit: int = 50) -> pd.DataFrame:
        user_id = self._get_user_id(username)
        if user_id is None:
            return pd.DataFrame(columns=["currency", "entry_type", "amount", "memo", "created_at"])

        with self.engine.begin() as conn:
            rows = conn.execute(
                text("""
                    SELECT currency, entry_type, amount, memo, ref_tx_id, created_at
                    FROM cash_ledger
                    WHERE user_id = :uid
                    ORDER BY id DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "lim": limit},
            ).mappings().all()

        return pd.DataFrame(rows)
