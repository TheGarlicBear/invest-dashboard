import os
from pathlib import Path
from datetime import datetime
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(dotenv_path=Path(".env"))
engine = create_engine(os.getenv("DATABASE_URL"))


def get_user_id(conn, username):
    row = conn.execute(
        text("SELECT id FROM users WHERE username = :u"),
        {"u": username}
    ).fetchone()
    if not row:
        raise ValueError(f"user not found: {username}")
    return row[0]


def get_holding(username, ticker):
    with engine.begin() as conn:
        user_id = get_user_id(conn, username)
        row = conn.execute(
            text("""
                SELECT ticker, quantity, avg_price, status
                FROM holdings
                WHERE user_id = :uid AND ticker = :t
            """),
            {"uid": user_id, "t": ticker}
        ).mappings().fetchone()
        return dict(row) if row else None


def list_transactions(username, ticker=None, limit=50):
    with engine.begin() as conn:
        user_id = get_user_id(conn, username)

        if ticker:
            rows = conn.execute(
                text("""
                    SELECT ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at
                    FROM holding_transactions
                    WHERE user_id = :uid AND ticker = :t
                    ORDER BY executed_at DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "t": ticker, "lim": limit}
            ).mappings().fetchall()
        else:
            rows = conn.execute(
                text("""
                    SELECT ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at
                    FROM holding_transactions
                    WHERE user_id = :uid
                    ORDER BY executed_at DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "lim": limit}
            ).mappings().fetchall()

        return [dict(r) for r in rows]


def record_buy(username, ticker, quantity, price, fee=0, memo='', profile_name=None):
    now = datetime.utcnow()

    quantity = Decimal(str(quantity))
    price = Decimal(str(price))
    fee = Decimal(str(fee))

    with engine.begin() as conn:
        user_id = get_user_id(conn, username)

        row = conn.execute(
            text("""
                SELECT id, quantity, avg_price
                FROM holdings
                WHERE user_id = :uid AND ticker = :t
            """),
            {"uid": user_id, "t": ticker}
        ).fetchone()

        if row:
            hid, old_qty, old_avg = row
            old_qty = Decimal(str(old_qty))
            old_avg = Decimal(str(old_avg))
            new_qty = old_qty + quantity
            new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty

            conn.execute(
                text("""
                    UPDATE holdings
                    SET quantity = :q, avg_price = :avg, updated_at = now()
                    WHERE id = :id
                """),
                {"q": new_qty, "avg": new_avg, "id": hid}
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO holdings (user_id, ticker, quantity, avg_price, status, created_at, updated_at)
                    VALUES (:uid, :t, :q, :avg, 'active', now(), now())
                """),
                {"uid": user_id, "t": ticker, "q": quantity, "avg": price}
            )

        conn.execute(
            text("""
                INSERT INTO holding_transactions
                (user_id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at)
                VALUES (:uid, :t, 'BUY', :q, :p, :f, :m, 0, :e, now())
            """),
            {
                "uid": user_id,
                "t": ticker,
                "q": quantity,
                "p": price,
                "f": fee,
                "m": memo,
                "e": now
            }
        )


def record_sell(username, ticker, quantity, price, fee=0, memo=''):
    now = datetime.utcnow()

    quantity = Decimal(str(quantity))
    price = Decimal(str(price))
    fee = Decimal(str(fee))

    with engine.begin() as conn:
        user_id = get_user_id(conn, username)

        row = conn.execute(
            text("""
                SELECT id, quantity, avg_price
                FROM holdings
                WHERE user_id = :uid AND ticker = :t
            """),
            {"uid": user_id, "t": ticker}
        ).fetchone()

        if not row:
            raise ValueError("no holding to sell")

        hid, old_qty, old_avg = row
        old_qty = Decimal(str(old_qty))
        old_avg = Decimal(str(old_avg))

        if quantity > old_qty:
            raise ValueError("sell quantity exceeds holding")

        new_qty = old_qty - quantity
        realized_pnl = (price - old_avg) * quantity - fee

        if new_qty == 0:
            conn.execute(
                text("""
                    UPDATE holdings
                    SET quantity = 0, status = 'closed', updated_at = now()
                    WHERE id = :id
                """),
                {"id": hid}
            )
        else:
            conn.execute(
                text("""
                    UPDATE holdings
                    SET quantity = :q, updated_at = now()
                    WHERE id = :id
                """),
                {"q": new_qty, "id": hid}
            )

        conn.execute(
            text("""
                INSERT INTO holding_transactions
                (user_id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at)
                VALUES (:uid, :t, 'SELL', :q, :p, :f, :m, :rp, :e, now())
            """),
            {
                "uid": user_id,
                "t": ticker,
                "q": quantity,
                "p": price,
                "f": fee,
                "m": memo,
                "rp": realized_pnl,
                "e": now
            }
        )
