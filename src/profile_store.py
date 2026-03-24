from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROFILE_DIR = Path("data/profiles")
ASSIGN_PATH = PROFILE_DIR / "profile_assignments.json"
RULE_PATH = PROFILE_DIR / "profile_rules.json"

DEFAULT_PROFILE = {
    "label": "기본형",
    "type": "기본",
    "logic_summary": "별도 정의가 없는 종목에 쓰는 기본 프로파일.",
    "weights": {
        "RSI14": 1.0,
        "고점 대비 낙폭": 1.0,
        "20일선 대비": 1.0,
        "60일선 대비": 1.0,
        "MACD 히스토그램": 1.0,
        "52주 위치": 1.0,
        "ATR14 변동성": 1.0,
        "거래량 배수": 1.0,
    },
    "buy_add_rules": ["고점 추격보다 눌림 선호"],
}

_METRIC_KEY_MAP = {
    "drawdown": "고점 대비 낙폭",
    "rsi": "RSI14",
    "ma20": "20일선 대비",
    "ma60": "60일선 대비",
    "macd": "MACD 히스토그램",
    "volume": "거래량 배수",
    "atr": "ATR14 변동성",
    "position_gap": "평균단가 대비 괴리",
}

def _normalize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    rule = dict(rule)
    weights = {}
    raw_weights = rule.get("weights", {}) or {}
    for key, value in raw_weights.items():
        metric_key = _METRIC_KEY_MAP.get(key, key)
        try:
            weights[metric_key] = float(value)
        except Exception:
            continue
    normalized = {
        "label": rule.get("label", DEFAULT_PROFILE["label"]),
        "type": rule.get("type", DEFAULT_PROFILE["type"]),
        "logic_summary": rule.get("logic_summary", DEFAULT_PROFILE["logic_summary"]),
        "weights": {**DEFAULT_PROFILE["weights"], **weights},
        "buy_add_rules": list(rule.get("buy_add_rules", DEFAULT_PROFILE["buy_add_rules"])),
    }
    return normalized

@lru_cache(maxsize=1)
def load_profile_assignments() -> dict[str, str]:
    if not ASSIGN_PATH.exists():
        return {}
    with ASSIGN_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(k).upper(): str(v) for k, v in data.items()}

@lru_cache(maxsize=1)
def load_profile_rules() -> dict[str, dict[str, Any]]:
    if not RULE_PATH.exists():
        return {"DEFAULT": DEFAULT_PROFILE}
    with RULE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    out = {"DEFAULT": DEFAULT_PROFILE}
    for key, rule in data.items():
        out[str(key).upper()] = _normalize_rule(rule)
    return out

def get_profile_for_ticker_from_files(ticker: str) -> tuple[str, dict[str, Any]]:
    ticker_upper = str(ticker).upper().strip()
    assignments = load_profile_assignments()
    rules = load_profile_rules()
    profile_key = assignments.get(ticker_upper, "DEFAULT")
    profile = rules.get(profile_key.upper(), rules["DEFAULT"])
    return profile_key.upper(), profile

def clear_profile_caches() -> None:
    load_profile_assignments.cache_clear()
    load_profile_rules.cache_clear()