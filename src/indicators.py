from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift(1)).abs()
    low_close = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["MA20"] = out["Close"].rolling(20).mean()
    out["MA60"] = out["Close"].rolling(60).mean()
    out["RSI14"] = calculate_rsi(out["Close"], 14)

    macd, signal, hist = calculate_macd(out["Close"])
    out["MACD"] = macd
    out["MACDSignal"] = signal
    out["MACDHist"] = hist

    out["ATR14"] = calculate_atr(out, 14)
    out["ATR14Pct"] = out["ATR14"] / out["Close"] * 100

    out["52WHigh"] = out["Close"].rolling(252, min_periods=20).max()
    out["52WLow"] = out["Close"].rolling(252, min_periods=20).min()
    range_52w = (out["52WHigh"] - out["52WLow"]).replace(0, np.nan)
    out["Position52W"] = (out["Close"] - out["52WLow"]) / range_52w * 100

    rolling_high = out["Close"].rolling(252, min_periods=20).max()
    out["DrawdownPct"] = (out["Close"] / rolling_high - 1) * 100

    out["MA20DiffPct"] = (out["Close"] / out["MA20"] - 1) * 100
    out["MA60DiffPct"] = (out["Close"] / out["MA60"] - 1) * 100

    volume_ma20 = out["Volume"].rolling(20).mean().replace(0, np.nan)
    out["VolumeRatio"] = out["Volume"] / volume_ma20

    return out
