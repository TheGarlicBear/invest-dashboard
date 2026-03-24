from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from src.krx_lookup import DATA_DIR
from src.watchlist_store import sanitize_user_id

HOLDINGS_DIR = DATA_DIR / "holdings"
REQUIRED_COLUMNS = ["ticker", "name", "avg_price", "qty", "currency", "market", "memo"]


def _path(user_id: str) -> Path:
    return HOLDINGS_DIR / f"{sanitize_user_id(user_id)}.csv"


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_df()
    out = df.copy()
    for col in REQUIRED_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out = out[REQUIRED_COLUMNS]
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    out["name"] = out["name"].astype(str).str.strip()
    out["avg_price"] = pd.to_numeric(out["avg_price"], errors="coerce")
    out["qty"] = pd.to_numeric(out["qty"], errors="coerce")
    out["currency"] = out["currency"].astype(str).str.strip().replace({"": "KRW"})
    out["market"] = out["market"].astype(str).str.strip()
    out["memo"] = out["memo"].astype(str).replace({"nan": ""})
    out = out.dropna(subset=["ticker", "avg_price", "qty"])
    out = out[out["ticker"] != ""]
    out = out.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)
    return out


def load_holdings(user_id: str) -> pd.DataFrame:
    HOLDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(user_id)
    if not path.exists():
        return _empty_df()
    try:
        return _normalize(pd.read_csv(path, dtype=str, encoding="utf-8-sig"))
    except Exception:
        return _empty_df()


def save_holdings(user_id: str, df: pd.DataFrame) -> Path:
    HOLDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(user_id)
    clean = _normalize(df)
    clean.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def reset_holdings(user_id: str) -> Path:
    HOLDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(user_id)
    clean = _empty_df()
    clean.to_csv(path, index=False, encoding="utf-8-sig")
    return path
