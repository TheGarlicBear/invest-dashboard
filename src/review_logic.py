{\rtf1\ansi\ansicpg949\cocoartf2868
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 from dataclasses import dataclass\
from typing import Optional, Literal\
\
ReviewSide = Literal["BUY", "SELL"]\
\
@dataclass\
class TradeReviewInput:\
    side: ReviewSide\
    entry_price: float\
    price_d5: Optional[float] = None\
    price_d20: Optional[float] = None\
    price_d60: Optional[float] = None\
    max_price_d20: Optional[float] = None\
    min_price_d20: Optional[float] = None\
    realized_pnl: Optional[float] = None\
\
@dataclass\
class TradeReviewResult:\
    status: str\
    label: str\
    score: float\
    reason: str\
\
def _pct(base, value):\
    if not value or base == 0:\
        return None\
    return (value / base - 1) * 100\
\
def evaluate_trade_review(inp: TradeReviewInput) -> TradeReviewResult:\
    ret20 = _pct(inp.entry_price, inp.price_d20)\
\
    if inp.side == "BUY":\
        if ret20 is None:\
            return TradeReviewResult("pending", "\uc0\u54217 \u44032 \u45824 \u44592 ", 0, "\u45936 \u51060 \u53552  \u48512 \u51313 ")\
\
        if ret20 >= 5:\
            return TradeReviewResult("done", "\uc0\u51096 \u54620  \u47588 \u49688 ", 80, "\u49345 \u49849 ")\
        elif ret20 >= 2:\
            return TradeReviewResult("done", "\uc0\u44316 \u52270 \u51008  \u47588 \u49688 ", 65, "\u48372 \u53685 ")\
        elif ret20 <= -3:\
            return TradeReviewResult("done", "\uc0\u45208 \u49244  \u47588 \u49688 ", 30, "\u54616 \u46973 ")\
        else:\
            return TradeReviewResult("done", "\uc0\u50528 \u47588 \u54620  \u47588 \u49688 ", 50, "\u51473 \u47549 ")\
\
    if inp.side == "SELL":\
        if ret20 is None:\
            return TradeReviewResult("pending", "\uc0\u54217 \u44032 \u45824 \u44592 ", 0, "\u45936 \u51060 \u53552  \u48512 \u51313 ")\
\
        if ret20 <= -3:\
            return TradeReviewResult("done", "\uc0\u51096 \u54620  \u47588 \u46020 ", 80, "\u54616 \u46973  \u54924 \u54588 ")\
        elif ret20 >= 5:\
            return TradeReviewResult("done", "\uc0\u45320 \u47924  \u51060 \u47480  \u47588 \u46020 ", 30, "\u49345 \u49849  \u45459 \u52840 ")\
        else:\
            return TradeReviewResult("done", "\uc0\u50528 \u47588 \u54620  \u47588 \u46020 ", 50, "\u51473 \u47549 ")}