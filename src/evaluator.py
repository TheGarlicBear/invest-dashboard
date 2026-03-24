from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.profile_store import get_profile_for_ticker_from_files


@dataclass
class EvaluationResult:
    label: str
    score: float
    comment: str
    breakdown: list[dict[str, Any]]
    profile_key: str
    profile_label: str
    profile_description: str
    total_raw_score: int
    buy_add_rules: list[str]
    profile_type: str


def _add_detail(
    breakdown: list[dict[str, Any]],
    metric: str,
    raw_score: int,
    weight: float,
    value: str,
    note: str,
) -> float:
    weighted_score = round(float(raw_score) * float(weight), 2)
    breakdown.append(
        {
            "항목": metric,
            "원점수": raw_score,
            "가중치": round(float(weight), 2),
            "점수": weighted_score,
            "값": value,
            "설명": note,
        }
    )
    return weighted_score


def get_profile_for_ticker(ticker: str) -> tuple[str, dict[str, Any]]:
    return get_profile_for_ticker_from_files(ticker)


def evaluate_latest(latest: dict[str, Any], ticker: str) -> EvaluationResult:
    score = 0.0
    total_raw_score = 0
    breakdown: list[dict[str, Any]] = []

    profile_key, profile = get_profile_for_ticker(ticker)
    weights = profile["weights"]

    rsi = latest.get("RSI14")
    if pd.notna(rsi):
        raw = 0
        note = "중립"
        if rsi <= 30:
            raw = 3
            note = "강한 과매도 구간"
        elif rsi <= 35:
            raw = 2
            note = "과매도 근접"
        elif rsi <= 45:
            raw = 1
            note = "중립 이하"
        elif rsi >= 70:
            raw = -2
            note = "과열 구간"
        total_raw_score += raw
        score += _add_detail(breakdown, "RSI14", raw, weights["RSI14"], f"{rsi:.1f}", note)

    drawdown = latest.get("DrawdownPct")
    if pd.notna(drawdown):
        raw = 0
        note = "중간 구간"
        if drawdown <= -15:
            raw = 3
            note = "낙폭이 큰 구간"
        elif drawdown <= -10:
            raw = 2
            note = "의미 있는 조정"
        elif drawdown <= -5:
            raw = 1
            note = "약한 조정"
        elif drawdown >= -1:
            raw = -1
            note = "고점 부근"
        total_raw_score += raw
        score += _add_detail(breakdown, "고점 대비 낙폭", raw, weights["고점 대비 낙폭"], f"{drawdown:.2f}%", note)

    ma20 = latest.get("MA20DiffPct")
    if pd.notna(ma20):
        raw = 0
        note = "중립"
        if ma20 <= -3:
            raw = 2
            note = "단기 이격 과도"
        elif ma20 <= 0:
            raw = 1
            note = "20일선 아래"
        elif ma20 >= 5:
            raw = -1
            note = "단기 과열 가능"
        total_raw_score += raw
        score += _add_detail(breakdown, "20일선 대비", raw, weights["20일선 대비"], f"{ma20:.2f}%", note)

    ma60 = latest.get("MA60DiffPct")
    if pd.notna(ma60):
        raw = 1 if ma60 >= 0 else -1
        note = "중기 추세 유지" if ma60 >= 0 else "중기 추세 약화"
        total_raw_score += raw
        score += _add_detail(breakdown, "60일선 대비", raw, weights["60일선 대비"], f"{ma60:.2f}%", note)

    macd_hist = latest.get("MACDHist")
    if pd.notna(macd_hist):
        raw = 1 if macd_hist > 0 else -1
        note = "상승 모멘텀 우위" if macd_hist > 0 else "하락 모멘텀 우위"
        total_raw_score += raw
        score += _add_detail(breakdown, "MACD 히스토그램", raw, weights["MACD 히스토그램"], f"{macd_hist:.4f}", note)

    pos_52w = latest.get("Position52W")
    if pd.notna(pos_52w):
        raw = 0
        note = "중간 구간"
        if pos_52w <= 20:
            raw = 2
            note = "연중 하단 구간"
        elif pos_52w <= 40:
            raw = 1
            note = "하단권"
        elif pos_52w >= 85:
            raw = -2
            note = "연중 상단 구간"
        elif pos_52w >= 70:
            raw = -1
            note = "상단권"
        total_raw_score += raw
        score += _add_detail(breakdown, "52주 위치", raw, weights["52주 위치"], f"{pos_52w:.1f}%", note)

    atr_pct = latest.get("ATR14Pct")
    if pd.notna(atr_pct):
        raw = 0
        note = "변동성 보통"
        if atr_pct >= 6:
            raw = -2
            note = "변동성 높음"
        elif atr_pct >= 4:
            raw = -1
            note = "변동성 다소 높음"
        total_raw_score += raw
        score += _add_detail(breakdown, "ATR14 변동성", raw, weights["ATR14 변동성"], f"{atr_pct:.2f}%", note)

    vol_ratio = latest.get("VolumeRatio")
    if pd.notna(vol_ratio):
        trend_ok = pd.notna(ma20) and pd.notna(ma60) and ma20 > 0 and ma60 > 0
        raw = 0
        note = "평균 수준"
        if vol_ratio >= 1.5 and trend_ok:
            raw = 1
            note = "상승 추세 속 거래량 보강"
        elif vol_ratio >= 1.5 and not trend_ok:
            note = "거래량은 증가했으나 추세 미확인"
        total_raw_score += raw
        score += _add_detail(breakdown, "거래량 배수", raw, weights["거래량 배수"], f"{vol_ratio:.2f}x", note)

    if score >= 6:
        label = "1차 분할매수 후보"
    elif score >= 3:
        label = "관심 구간"
    elif score >= 0:
        label = "중립·관망"
    else:
        label = "리스크 주의"

    positives = [row["설명"] for row in breakdown if row["점수"] > 0][:2]
    negatives = [row["설명"] for row in breakdown if row["점수"] < 0][:2]
    positive_text = ", ".join(positives) if positives else "뚜렷한 강점은 제한적"
    negative_text = ", ".join(negatives) if negatives else "큰 경고 신호는 제한적"
    comment = f"강점: {positive_text} / 주의: {negative_text}"

    return EvaluationResult(
        label=label,
        score=round(score, 2),
        comment=comment,
        breakdown=breakdown,
        profile_key=profile_key,
        profile_label=profile["label"],
        profile_description=profile["logic_summary"],
        total_raw_score=total_raw_score,
        buy_add_rules=profile.get("buy_add_rules", []),
        profile_type=profile.get("type", "기본"),
    )