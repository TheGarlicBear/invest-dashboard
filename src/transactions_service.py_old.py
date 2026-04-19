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


def infer_currency_from_ticker(ticker: str) -> str:
    t = str(ticker or "").upper().strip()
    if t.endswith(".KS") or t.endswith(".KQ") or (t.isdigit() and len(t) == 6):
        return "KRW"
    return "USD"


def infer_tx_tag(tx_type: str, memo: str = "") -> str:
    m = str(memo or "").strip().lower()
    if "테스트" in m or "test" in m:
        return "테스트"
    if "초기" in m:
        return "초기세팅"
    if "수동" in m:
        return "수동조정"
    if tx_type.upper() == "BUY":
        if "추매" in m:
            return "추매"
        return "신규매수"
    if tx_type.upper() == "SELL":
        if "손절" in m:
            return "손절"
        if "전량" in m:
            return "전량매도"
        if "일부" in m or "분할" in m:
            return "부분익절"
        return "매도"
    return "기타"


def _ensure_cash_row(conn, user_id: int, currency: str):
    conn.execute(
        text("""
            INSERT INTO cash_balances (user_id, currency, balance, updated_at)
            VALUES (:uid, :currency, 0, now())
            ON CONFLICT (user_id, currency)
            DO NOTHING
        """),
        {"uid": user_id, "currency": currency},
    )


def _adjust_cash(conn, user_id: int, currency: str, delta: Decimal, entry_type: str, memo: str = "", ref_tx_id=None):
    _ensure_cash_row(conn, user_id, currency)
    conn.execute(
        text("""
            UPDATE cash_balances
            SET balance = balance + :delta, updated_at = now()
            WHERE user_id = :uid AND currency = :currency
        """),
        {"uid": user_id, "currency": currency, "delta": delta},
    )
    conn.execute(
        text("""
            INSERT INTO cash_ledger (user_id, currency, entry_type, amount, memo, ref_tx_id, created_at)
            VALUES (:uid, :currency, :entry_type, :amount, :memo, :ref_tx_id, now())
        """),
        {
            "uid": user_id,
            "currency": currency,
            "entry_type": entry_type,
            "amount": delta,
            "memo": memo,
            "ref_tx_id": ref_tx_id,
        },
    )


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
                    SELECT id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at,
                           COALESCE(currency, :currency) AS currency,
                           COALESCE(tx_tag, '') AS tx_tag
                    FROM holding_transactions
                    WHERE user_id = :uid AND ticker = :t
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "t": ticker, "lim": limit, "currency": infer_currency_from_ticker(ticker)}
            ).mappings().fetchall()
        else:
            rows = conn.execute(
                text("""
                    SELECT id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at,
                           currency, COALESCE(tx_tag, '') AS tx_tag
                    FROM holding_transactions
                    WHERE user_id = :uid
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "lim": limit}
            ).mappings().fetchall()

        return [dict(r) for r in rows]


def record_buy(username, ticker, quantity, price, fee=0, memo='', executed_at=None, profile_name=None):
    now = datetime.utcnow()

    ticker = str(ticker).upper().strip()
    quantity = Decimal(str(quantity))
    price = Decimal(str(price))
    fee = Decimal(str(fee))
    currency = infer_currency_from_ticker(ticker)
    tx_tag = infer_tx_tag("BUY", memo)

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

        tx_id = conn.execute(
            text("""
                INSERT INTO holding_transactions
                (user_id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at, currency, tx_tag)
                VALUES (:uid, :t, 'BUY', :q, :p, :f, :m, 0, :e, now(), :currency, :tx_tag)
                RETURNING id
            """),
            {
                "uid": user_id,
                "t": ticker,
                "q": quantity,
                "p": price,
                "f": fee,
                "m": memo,
                "e": executed_at or now,
                "currency": currency,
                "tx_tag": tx_tag,
            }
        ).scalar_one()

        _adjust_cash(
            conn,
            user_id=user_id,
            currency=currency,
            delta=-(quantity * price + fee),
            entry_type="trade_buy",
            memo=f"BUY:{ticker}",
            ref_tx_id=tx_id,
        )


def record_sell(username, ticker, quantity, price, fee=0, memo='', executed_at=None):
    now = datetime.utcnow()

    ticker = str(ticker).upper().strip()
    quantity = Decimal(str(quantity))
    price = Decimal(str(price))
    fee = Decimal(str(fee))
    currency = infer_currency_from_ticker(ticker)
    tx_tag = infer_tx_tag("SELL", memo)

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

        tx_id = conn.execute(
            text("""
                INSERT INTO holding_transactions
                (user_id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at, currency, tx_tag)
                VALUES (:uid, :t, 'SELL', :q, :p, :f, :m, :rp, :e, now(), :currency, :tx_tag)
                RETURNING id
            """),
            {
                "uid": user_id,
                "t": ticker,
                "q": quantity,
                "p": price,
                "f": fee,
                "m": memo,
                "rp": realized_pnl,
                "e": executed_at or now,
                "currency": currency,
                "tx_tag": tx_tag,
            }
        ).scalar_one()

        _adjust_cash(
            conn,
            user_id=user_id,
            currency=currency,
            delta=(quantity * price - fee),
            entry_type="trade_sell",
            memo=f"SELL:{ticker}",
            ref_tx_id=tx_id,
        )
