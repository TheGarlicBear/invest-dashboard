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


def fetch_current_price(ticker: str, fallback_df: pd.DataFrame | None = None) -> float:
    tk = yf.Ticker(ticker)

    # 1순위: fast_info
    try:
        fi = tk.fast_info
        if fi:
            for key in ["lastPrice", "regularMarketPrice", "currentPrice"]:
                val = fi.get(key)
                if val is not None and pd.notna(val):
                    return float(val)
    except Exception:
        pass

    # 2순위: 최근 일봉 마지막 종가
    try:
        hist = tk.history(period="5d", interval="1d", auto_adjust=False)
        if hist is not None and not hist.empty:
            hist = hist.dropna(subset=["Close"])
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
    except Exception:
        pass

    # 3순위: 이미 받아둔 df 마지막 Close
    if fallback_df is not None and not fallback_df.empty:
        return float(fallback_df["Close"].iloc[-1])

    raise ValueError(f"현재가 조회 실패: {ticker}")


def fetch_multiple(
    tickers: Iterable[str], period: str, interval: str
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str], Dict[str, str], Dict[str, float]]:
    data_map: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, str] = {}
    display_names: Dict[str, str] = {}
    price_map: Dict[str, float] = {}

    for ticker in tickers:
        try:
            df = fetch_single(ticker=ticker, period=period, interval=interval)
            data_map[ticker] = df
            display_names[ticker] = get_display_name(ticker)

            try:
                price_map[ticker] = fetch_current_price(ticker, fallback_df=df)
            except Exception:
                price_map[ticker] = float(df["Close"].iloc[-1])

        except Exception as exc:
            errors[ticker] = str(exc)

    return data_map, errors, display_names, price_map
