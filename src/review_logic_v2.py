
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

ReviewSide = Literal["BUY", "SELL"]


@dataclass
class TradeReviewInput:
    side: ReviewSide
    entry_price: float
    price_d5: Optional[float] = None
    price_d20: Optional[float] = None
    price_d60: Optional[float] = None
    max_price_d20: Optional[float] = None
    min_price_d20: Optional[float] = None
    realized_pnl: Optional[float] = None


@dataclass
class TradeReviewResult:
    status: str
    label: str
    score: float
    reason: str
    ret_d5: Optional[float]
    ret_d20: Optional[float]
    ret_d60: Optional[float]
    mfe_d20: Optional[float]
    mae_d20: Optional[float]


def _pct(base: float, value: Optional[float]) -> Optional[float]:
    if value is None or base in (None, 0):
        return None
    return (float(value) / float(base) - 1.0) * 100.0


def evaluate_trade_review(inp: TradeReviewInput) -> TradeReviewResult:
    ret_d5 = _pct(inp.entry_price, inp.price_d5)
    ret_d20 = _pct(inp.entry_price, inp.price_d20)
    ret_d60 = _pct(inp.entry_price, inp.price_d60)
    mfe_d20 = _pct(inp.entry_price, inp.max_price_d20)
    mae_d20 = _pct(inp.entry_price, inp.min_price_d20)

    if inp.side == "BUY":
        if ret_d20 is None:
            return TradeReviewResult("pending", "평가대기", 0.0, "20거래일 데이터 부족", ret_d5, ret_d20, ret_d60, mfe_d20, mae_d20)

        score = 50.0
        reason = []

        if ret_d20 >= 5:
            score += 25
            reason.append("20일 성과 양호")
        elif ret_d20 >= 2:
            score += 10
            reason.append("20일 성과 무난")
        elif ret_d20 <= -3:
            score -= 25
            reason.append("20일 성과 부진")

        if mae_d20 is not None:
            if mae_d20 > -3:
                score += 15
                reason.append("진입 후 낙폭 안정")
            elif mae_d20 <= -7:
                score -= 15
                reason.append("진입 후 낙폭 과도")

        if mfe_d20 is not None and mfe_d20 >= 6:
            score += 10
            reason.append("상승 탄력 확인")

        label = "잘한 매수" if score >= 80 else "괜찮은 매수" if score >= 60 else "애매한 매수" if score >= 40 else "나쁜 매수"
        return TradeReviewResult("done", label, round(score, 1), ", ".join(reason) if reason else "기준 충족 없음", ret_d5, ret_d20, ret_d60, mfe_d20, mae_d20)

    if inp.price_d20 is None and inp.max_price_d20 is None and inp.min_price_d20 is None:
        return TradeReviewResult("pending", "평가대기", 0.0, "매도 후 비교 데이터 부족", ret_d5, ret_d20, ret_d60, mfe_d20, mae_d20)

    score = 50.0
    reason = []

    if ret_d20 is not None:
        if ret_d20 <= -3:
            score += 25
            reason.append("매도 후 하락")
        elif ret_d20 >= 5:
            score -= 20
            reason.append("매도 후 재상승")

    if mfe_d20 is not None and mfe_d20 >= 7:
        score -= 20
        reason.append("너무 이른 매도 가능성")

    if mae_d20 is not None and mae_d20 <= -5:
        score += 15
        reason.append("매도 후 낙폭 커서 방어 성공")

    label = "잘한 매도" if score >= 75 else "너무 이른 매도" if score <= 35 else ("늦은 손절" if (inp.realized_pnl or 0) < 0 and score < 50 else "애매한 매도")
    return TradeReviewResult("done", label, round(score, 1), ", ".join(reason) if reason else "기준 충족 없음", ret_d5, ret_d20, ret_d60, mfe_d20, mae_d20)
