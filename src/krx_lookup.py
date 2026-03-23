from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
KRX_CSV_PATH = DATA_DIR / "krx_tickers.csv"

REQUIRED_COLUMNS = ["name", "code", "ticker_yf", "market"]


def _ensure_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    missing = [col for col in REQUIRED_COLUMNS if col not in out.columns]
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")
    out["name"] = out["name"].astype(str).str.strip()
    out["code"] = out["code"].astype(str).str.strip().str.zfill(6)
    out["ticker_yf"] = out["ticker_yf"].astype(str).str.strip().str.upper()
    out["market"] = out["market"].astype(str).str.strip().str.upper()
    out = out.drop_duplicates(subset=["ticker_yf"], keep="first")
    out = out.sort_values(["market", "name"]).reset_index(drop=True)
    return out


def load_krx_tickers() -> pd.DataFrame:
    if not KRX_CSV_PATH.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    df = pd.read_csv(KRX_CSV_PATH, dtype=str, encoding='utf-8-sig')
    return _ensure_dataframe(df)


def save_krx_tickers(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = _ensure_dataframe(df)
    clean.to_csv(KRX_CSV_PATH, index=False, encoding='utf-8-sig')


def build_name_map(df: pd.DataFrame | None = None) -> dict[str, str]:
    source = load_krx_tickers() if df is None else _ensure_dataframe(df)
    return dict(zip(source["ticker_yf"], source["name"]))


def search_krx_tickers(query: str, df: pd.DataFrame | None = None, limit: int = 30) -> pd.DataFrame:
    source = load_krx_tickers() if df is None else _ensure_dataframe(df)
    if source.empty:
        return source
    query = (query or "").strip().lower()
    if not query:
        return source.head(limit).reset_index(drop=True)
    mask = (
        source["name"].str.lower().str.contains(query, na=False)
        | source["code"].str.lower().str.contains(query, na=False)
        | source["ticker_yf"].str.lower().str.contains(query, na=False)
    )
    return source.loc[mask].head(limit).reset_index(drop=True)


def get_display_name_for_ticker(ticker: str, df: pd.DataFrame | None = None) -> str:
    ticker_upper = str(ticker).upper()
    name_map = build_name_map(df)
    return name_map.get(ticker_upper, ticker_upper)


def update_krx_tickers_from_pykrx() -> tuple[bool, str, pd.DataFrame | None]:
    try:
        from pykrx import stock
    except Exception:
        return False, "pykrx가 설치되어 있지 않습니다. requirements 설치 후 다시 시도하세요.", None

    all_rows: list[dict[str, str]] = []
    markets = [("KOSPI", ".KS"), ("KOSDAQ", ".KQ"), ("KONEX", ".KQ")]
    try:
        for market, suffix in markets:
            tickers = stock.get_market_ticker_list(market=market)
            for code in tickers:
                try:
                    name = stock.get_market_ticker_name(code)
                except Exception:
                    continue
                if not name:
                    continue
                all_rows.append(
                    {
                        "name": str(name).strip(),
                        "code": str(code).zfill(6),
                        "ticker_yf": f"{str(code).zfill(6)}{suffix}",
                        "market": market,
                    }
                )
        if not all_rows:
            return False, "pykrx 연결은 되었지만 종목 목록을 가져오지 못했습니다.", None
        out = pd.DataFrame(all_rows)
        out = _ensure_dataframe(out)
        # KRX raw에서 KONEX를 yfinance .KQ로 두되 시장은 KONEX 유지
        save_krx_tickers(out)
        return True, f"KRX 종목 목록 {len(out):,}개를 갱신했습니다.", out
    except Exception as exc:
        return False, f"KRX 목록 갱신 실패: {exc}", None
