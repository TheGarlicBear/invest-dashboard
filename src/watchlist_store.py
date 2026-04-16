
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from src.config import DEFAULT_TICKERS
from src.krx_lookup import DATA_DIR

WATCHLISTS_DIR = DATA_DIR / "watchlists"


def sanitize_user_id(user_id: str) -> str:
    raw = str(user_id or "").strip()
    if not raw:
        return "master"
    forbidden = '<>:"/\\|?*'
    sanitized = "".join("_" if ch in forbidden else ch for ch in raw)
    sanitized = sanitized.strip().strip(".")
    return sanitized or "master"


def normalize_tickers(tickers: Iterable[str] | str) -> list[str]:
    if isinstance(tickers, str):
        parts = [item.strip().upper() for item in tickers.split(",")]
    else:
        parts = [str(item).strip().upper() for item in tickers]
    out: list[str] = []
    seen: set[str] = set()
    for item in parts:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _watchlist_path(user_id: str) -> Path:
    return WATCHLISTS_DIR / f"{sanitize_user_id(user_id)}.json"


def list_watchlist_users(default_users: Iterable[str] | None = None) -> list[str]:
    WATCHLISTS_DIR.mkdir(parents=True, exist_ok=True)
    users = [path.stem for path in WATCHLISTS_DIR.glob("*.json")]
    if default_users:
        for user in default_users:
            if user not in users:
                users.append(user)
    return sorted(set(users), key=lambda x: x.lower())


def load_watchlist(user_id: str, fallback: Iterable[str] | None = None) -> list[dict]:
    WATCHLISTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _watchlist_path(user_id)
    default_tickers = normalize_tickers(list(DEFAULT_TICKERS if fallback is None else fallback))
    default_items = [{"ticker": t, "attractiveness_score": 3} for t in default_tickers]

    if not path.exists():
        return default_items

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))

        # 새 포맷 지원
        raw_items = payload.get("items")
        if isinstance(raw_items, list):
            clean_items = []
            seen = set()

            for item in raw_items:
                if not isinstance(item, dict):
                    continue

                ticker = str(item.get("ticker", "")).strip().upper()
                if not ticker or ticker in seen:
                    continue

                score = item.get("attractiveness_score", 3)
                try:
                    score = int(score)
                except Exception:
                    score = 3

                score = max(1, min(5, score))

                clean_items.append({
                    "ticker": ticker,
                    "attractiveness_score": score,
                })
                seen.add(ticker)

            if clean_items:
                return clean_items

        # 구 포맷(tickers 리스트) 호환
        raw_tickers = payload.get("tickers", default_tickers)
        tickers = normalize_tickers(raw_tickers)
        return [{"ticker": t, "attractiveness_score": 3} for t in tickers]

    except Exception:
        return default_items


def save_watchlist(user_id: str, items: Iterable[dict] | Iterable[str] | str) -> Path:
    WATCHLISTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _watchlist_path(user_id)

    clean_items = []
    seen = set()

    if isinstance(items, str):
        items = [items]

    for item in items:
        if isinstance(item, dict):
            ticker = str(item.get("ticker", "")).strip().upper()
            score = item.get("attractiveness_score", 3)
        else:
            ticker = str(item).strip().upper()
            score = 3

        if not ticker or ticker in seen:
            continue

        try:
            score = int(score)
        except Exception:
            score = 3

        score = max(1, min(5, score))

        clean_items.append({
            "ticker": ticker,
            "attractiveness_score": score,
        })
        seen.add(ticker)

    payload = {
        "user_id": sanitize_user_id(user_id),
        "items": clean_items,
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return path


def reset_watchlist(user_id: str, fallback: Iterable[str] | None = None) -> Path:
    default_items = normalize_tickers(list(DEFAULT_TICKERS if fallback is None else fallback))
    return save_watchlist(user_id=user_id, tickers=default_items)
