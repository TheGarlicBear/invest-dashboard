from __future__ import annotations

from typing import Dict, Iterable, Tuple

import pandas as pd
import yfinance as yf

from src.krx_lookup import get_display_name_for_ticker


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("빈 데이터")

    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)

    out = out.rename_axis("Date").reset_index()
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in required if col not in out.columns]
    if missing:
        raise ValueError(f"필수 컬럼 없음: {missing}")

    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    return out


def get_display_name(ticker: str) -> str:
    return get_display_name_for_ticker(ticker)


def fetch_single(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    return _normalize_frame(df)


def fetch_multiple(
    tickers: Iterable[str], period: str, interval: str
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str], Dict[str, str]]:
    data_map: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, str] = {}
    display_names: Dict[str, str] = {}

    for ticker in tickers:
        try:
            data_map[ticker] = fetch_single(ticker=ticker, period=period, interval=interval)
            display_names[ticker] = get_display_name(ticker)
        except Exception as exc:  # noqa: BLE001
            errors[ticker] = str(exc)

    return data_map, errors, display_names
