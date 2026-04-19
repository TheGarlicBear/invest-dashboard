from __future__ import annotations

from typing import Dict, List, Tuple

import altair as alt
import pandas as pd
import streamlit as st

import os
import json
from datetime import datetime, date
import traceback
from sqlalchemy import create_engine, text



from src.config import (
    DEFAULT_INTERVAL,
    DEFAULT_PERIOD,
    DEFAULT_TICKERS,
    INTERVAL_OPTIONS,
    PERIOD_OPTIONS,
    SUMMARY_COLUMNS,
)
from src.auth_store import verify_login, seed_default_users
from src.data_loader import fetch_multiple
from src.evaluator import evaluate_latest, get_profile_for_ticker
from src.indicators import add_indicators
from src.krx_lookup import build_name_map, load_krx_tickers, search_krx_tickers, update_krx_tickers_from_pykrx
from src.holding_signal import decide_final_action
from src.transactions_service import record_buy, record_sell, list_transactions
from src.cash_review_ui import render_cash_section, render_review_tab
from src.store_layer import (
    load_watchlist,
    load_holdings,
    save_watchlist,
    save_holdings,
    bootstrap_user_session,
)

APP_VERSION = "v18-stability-and-trade-date"

st.set_page_config(page_title="개인 투자 판단 보조기", layout="wide")

if "session_created_at" not in st.session_state:
    st.session_state["session_created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

st.sidebar.caption(f"APP_VERSION: {APP_VERSION}")
st.sidebar.caption(f"Session started: {st.session_state['session_created_at']}")
st.sidebar.caption(f"PID: {os.getpid()}")

CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1520px;}
.metric-grid {display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 10px 0 22px 0;}
.metric-card {background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%); color: #ffffff; border-radius: 18px; padding: 18px 22px; border: 1px solid rgba(255,255,255,0.12); box-shadow: 0 12px 28px rgba(37, 99, 235, 0.18); min-height: 120px;}
.metric-title {font-size: 1rem; font-weight: 700; color: rgba(255,255,255,0.92); margin-bottom: 14px;}
.metric-value {font-size: 3rem; font-weight: 800; line-height: 1.05; color: #ffffff;}
.card {background: #0f172a; color: #f8fafc; border-radius: 18px; padding: 1rem 1.1rem; border: 1px solid rgba(148,163,184,0.18); box-shadow: 0 8px 24px rgba(15, 23, 42, 0.10);}
.section-title {font-size: 1.05rem; font-weight: 700; margin-bottom: 0.65rem;}
.badge {display:inline-block; padding:0.22rem 0.55rem; border-radius:999px; font-size:0.78rem; font-weight:600; background:#1d4ed8; color:white;}
.small-note {font-size: 0.82rem; color: #64748b;}
@media (max-width: 980px) {.metric-grid {grid-template-columns: 1fr 1fr;}}
@media (max-width: 640px) {.metric-grid {grid-template-columns: 1fr;}}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=60 * 5)
def load_market_data(
    tickers: Tuple[str, ...],
    period: str,
    interval: str
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str], Dict[str, str], Dict[str, float]]:
    return fetch_multiple(tickers=tickers, period=period, interval=interval)

@st.cache_data(ttl=60 * 60)
def load_krx_lookup() -> pd.DataFrame:
    return load_krx_tickers()


def _safe_round(value: object, digits: int = 2):
    if pd.isna(value):
        return None
    return round(float(value), digits)


def label_to_color(label: str) -> str:
    return {"1차 분할매수 후보": "#16a34a", "관심 구간": "#2563eb", "중립·관망": "#f59e0b", "리스크 주의": "#dc2626"}.get(label, "#64748b")


def state_badge(state: str) -> str:
    mapping = {"좋음": "🟢 좋음", "양호": "🔵 양호", "보통": "🟡 보통", "주의": "🟠 주의", "위험": "🔴 위험"}
    return mapping.get(state, state)


def score_to_signal(value: float) -> str:
    if value >= 2: return "좋음"
    if value >= 1: return "양호"
    if value >= 0: return "보통"
    if value >= -1: return "주의"
    return "위험"


def get_name_map(krx_df: pd.DataFrame) -> dict[str, str]:
    return build_name_map(krx_df)


def normalize_display_names(tickers: Tuple[str, ...], krx_df: pd.DataFrame) -> Dict[str, str]:
    name_map = get_name_map(krx_df)
    return {ticker: name_map.get(str(ticker).upper(), ticker) for ticker in tickers}

def _normalize_watchlist_items(raw_items, default_score: int = 3) -> list[dict]:
    clean_items = []
    seen = set()

    if raw_items is None:
        raw_items = []

    for item in raw_items:
        if isinstance(item, dict):
            ticker = _clean_ticker(item.get("ticker", ""))
            score = item.get("attractiveness_score", default_score)
        else:
            ticker = _clean_ticker(item)
            score = default_score

        if not ticker or ticker in seen:
            continue

        try:
            score = int(score)
        except Exception:
            score = default_score

        score = max(1, min(5, score))

        clean_items.append({
            "ticker": ticker,
            "attractiveness_score": score,
        })
        seen.add(ticker)

    return clean_items


def append_ticker_from_search(ticker_to_add: str) -> None:
    current_items = _normalize_watchlist_items(st.session_state.get("watchlist_items", []))
    current_tickers = [item["ticker"] for item in current_items]

    if ticker_to_add.upper() not in current_tickers:
        current_items.append({
            "ticker": ticker_to_add.upper(),
            "attractiveness_score": 3,
        })

    st.session_state["watchlist_items"] = current_items
    st.session_state["watchlist_editor_needs_sync"] = True

def _clean_ticker(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\xa0", "")
        .strip()
        .upper()
    )


def _parse_ticker_text(current_text: str | None) -> list[str]:
    current_text = current_text or ""
    clean = []
    for raw in current_text.split(","):
        t = _clean_ticker(raw)
        if t and t not in clean:
            clean.append(t)
    return clean


def persist_current_watchlist(user_id: str, current_text: str | None = None, default_score: int = 3) -> None:
    tickers = _parse_ticker_text(
        current_text if current_text is not None else st.session_state.get("ticker_text_input", "")
    )

    existing_items = _normalize_watchlist_items(st.session_state.get("watchlist_items", []))
    score_map = {item["ticker"]: item["attractiveness_score"] for item in existing_items}

    items = [
        {
            "ticker": t,
            "attractiveness_score": score_map.get(t, default_score),
        }
        for t in tickers
    ]

    if user_id == "guest" or st.session_state.get("is_guest"):
        st.session_state["guest_watchlist"] = tickers
        st.session_state["watchlist_items"] = items
        st.session_state["watchlist_notice"] = "Guest 모드에서는 저장되지 않습니다. 현재 세션에서만 유지됩니다."
        st.session_state["watchlist_editor_needs_sync"] = True
        return

    save_watchlist(user_id, items)
    st.session_state["watchlist_items"] = items
    st.session_state["watchlist_notice"] = f"{user_id} 관심종목을 저장했습니다."
    st.session_state["watchlist_editor_needs_sync"] = True


def reset_current_watchlist(user_id: str) -> None:
    default_items = [{"ticker": t, "attractiveness_score": 3} for t in list(DEFAULT_TICKERS)]

    if user_id == "guest" or st.session_state.get("is_guest"):
        st.session_state["guest_watchlist"] = [item["ticker"] for item in default_items]
        st.session_state["watchlist_items"] = default_items
        st.session_state["watchlist_notice"] = "Guest 관심종목을 기본값으로 초기화했습니다."
        st.session_state["watchlist_editor_needs_sync"] = True
        return

    save_watchlist(user_id, default_items)
    st.session_state["watchlist_items"] = default_items
    st.session_state["watchlist_notice"] = f"{user_id} 관심종목을 기본값으로 초기화했습니다."
    st.session_state["watchlist_editor_needs_sync"] = True

def format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:.2f}%"


def infer_currency_from_ticker(ticker: str) -> str:
    t = str(ticker).upper()
    if t.endswith('.KS') or t.endswith('.KQ') or (t.isdigit() and len(t) == 6):
        return 'KRW'
    return 'USD'


def format_money_by_currency(value: float | int | None, currency: str) -> str:
    if value is None or pd.isna(value):
        return '-'
    amount = float(value)
    if currency == 'KRW':
        return f"₩{amount:,.0f}"
    return f"${amount:,.2f}"


def is_test_trade_memo(memo: object) -> bool:
    if memo is None or pd.isna(memo):
        return False
    s = str(memo).strip().lower()
    return any(k in s for k in ['test', '테스트', '시험'])


@st.cache_resource
def get_db_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    return create_engine(db_url)


def get_user_id_db(username: str) -> int | None:
    with get_db_engine().begin() as conn:
        row = conn.execute(text("SELECT id FROM users WHERE username = :u"), {"u": username}).fetchone()
        return row[0] if row else None


def _pnl_adjustment_path(username: str) -> str:
    base_dir = os.path.join("data", "user_overrides")
    os.makedirs(base_dir, exist_ok=True)
    safe = str(username).strip().replace("/", "_")
    return os.path.join(base_dir, f"{safe}_pnl_adjustment.json")


def load_pnl_adjustments(username: str) -> dict:
    path = _pnl_adjustment_path(username)
    if not os.path.exists(path):
        return {"KRW": 0.0, "USD": 0.0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "KRW": float(data.get("KRW", 0.0) or 0.0),
            "USD": float(data.get("USD", 0.0) or 0.0),
        }
    except Exception:
        return {"KRW": 0.0, "USD": 0.0}


def save_pnl_adjustments(username: str, krw: float, usd: float) -> None:
    path = _pnl_adjustment_path(username)
    payload = {"KRW": float(krw or 0.0), "USD": float(usd or 0.0)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def fetch_transactions_admin(username: str, limit: int = 300) -> pd.DataFrame:
    user_id = get_user_id_db(username)
    if user_id is None:
        return pd.DataFrame()
    with get_db_engine().begin() as conn:
        rows = conn.execute(text("""
            SELECT id, ticker, tx_type, quantity, price, fee, memo, realized_pnl, executed_at, created_at
            FROM holding_transactions
            WHERE user_id = :uid
            ORDER BY COALESCE(executed_at, created_at) DESC, created_at DESC, id DESC
            LIMIT :lim
        """), {"uid": user_id, "lim": limit}).mappings().fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def rebuild_holdings_from_transactions(username: str) -> None:
    user_id = get_user_id_db(username)
    if user_id is None:
        return

    with get_db_engine().begin() as conn:
        rows = conn.execute(text("""
            SELECT ticker, tx_type, quantity, price, executed_at, created_at, id
            FROM holding_transactions
            WHERE user_id = :uid
            ORDER BY COALESCE(executed_at, created_at) ASC, created_at ASC, id ASC
        """), {"uid": user_id}).mappings().fetchall()

        positions: dict[str, dict[str, float]] = {}
        for row in rows:
            ticker = str(row["ticker"]).upper()
            tx_type = str(row["tx_type"]).upper()
            qty = float(row.get("quantity") or 0)
            price = float(row.get("price") or 0)

            if ticker not in positions:
                positions[ticker] = {"quantity": 0.0, "avg_price": 0.0}

            pos = positions[ticker]

            if tx_type == "BUY":
                new_qty = pos["quantity"] + qty
                if new_qty > 0:
                    pos["avg_price"] = ((pos["quantity"] * pos["avg_price"]) + (qty * price)) / new_qty
                    pos["quantity"] = new_qty
            elif tx_type == "SELL":
                pos["quantity"] = max(0.0, pos["quantity"] - qty)
                if pos["quantity"] == 0:
                    pos["avg_price"] = 0.0

        conn.execute(text("DELETE FROM holdings WHERE user_id = :uid"), {"uid": user_id})

        for ticker, pos in positions.items():
            if pos["quantity"] <= 0:
                continue
            conn.execute(text("""
                INSERT INTO holdings (user_id, ticker, quantity, avg_price, status, created_at, updated_at)
                VALUES (:uid, :ticker, :quantity, :avg_price, 'active', now(), now())
            """), {
                "uid": user_id,
                "ticker": ticker,
                "quantity": pos["quantity"],
                "avg_price": pos["avg_price"],
            })


def delete_transaction_by_id(username: str, transaction_id: int) -> None:
    user_id = get_user_id_db(username)
    if user_id is None:
        return
    with get_db_engine().begin() as conn:
        conn.execute(text("DELETE FROM holding_transactions WHERE user_id = :uid AND id = :txid"), {"uid": user_id, "txid": transaction_id})
    rebuild_holdings_from_transactions(username)


def delete_test_transactions_for_user(username: str) -> int:
    user_id = get_user_id_db(username)
    if user_id is None:
        return 0
    with get_db_engine().begin() as conn:
        result = conn.execute(text("""
            DELETE FROM holding_transactions
            WHERE user_id = :uid
              AND (LOWER(COALESCE(memo, '')) LIKE '%test%'
                   OR memo LIKE '%테스트%'
                   OR memo LIKE '%시험%')
        """), {"uid": user_id})
        deleted = result.rowcount or 0
    rebuild_holdings_from_transactions(username)
    return deleted


def clear_all_transactions_for_user(username: str) -> int:
    user_id = get_user_id_db(username)
    if user_id is None:
        return 0
    with get_db_engine().begin() as conn:
        result = conn.execute(text("DELETE FROM holding_transactions WHERE user_id = :uid"), {"uid": user_id})
        conn.execute(text("DELETE FROM holdings WHERE user_id = :uid"), {"uid": user_id})
        deleted = result.rowcount or 0
    return deleted


def apply_split_adjustment(username: str, ticker: str, ratio: float) -> bool:
    user_id = get_user_id_db(username)
    if user_id is None or ratio <= 0:
        return False
    with get_db_engine().begin() as conn:
        row = conn.execute(text("SELECT quantity, avg_price FROM holdings WHERE user_id = :uid AND ticker = :ticker"), {"uid": user_id, "ticker": ticker}).fetchone()
        if not row:
            return False
        quantity, avg_price = float(row[0]), float(row[1])
        conn.execute(text("""
            UPDATE holdings
            SET quantity = :q, avg_price = :a, updated_at = now()
            WHERE user_id = :uid AND ticker = :ticker
        """), {"q": quantity * ratio, "a": avg_price / ratio if ratio else avg_price, "uid": user_id, "ticker": ticker})
    return True


def upsert_holding_snapshot(username: str, ticker: str, quantity: float, avg_price: float) -> bool:
    user_id = get_user_id_db(username)
    if user_id is None:
        return False
    ticker = str(ticker).upper()
    with get_db_engine().begin() as conn:
        conn.execute(text("DELETE FROM holdings WHERE user_id = :uid AND ticker = :ticker"), {"uid": user_id, "ticker": ticker})
        if quantity > 0:
            conn.execute(text("""
                INSERT INTO holdings (user_id, ticker, quantity, avg_price, status, created_at, updated_at)
                VALUES (:uid, :ticker, :q, :a, 'active', now(), now())
            """), {"uid": user_id, "ticker": ticker, "q": quantity, "a": avg_price})
    return True

def market_summary_rows(
    data_map: Dict[str, pd.DataFrame],
    display_names: Dict[str, str],
    holdings_df: pd.DataFrame,
    price_map: Dict[str, float],
) -> pd.DataFrame:
    rows=[]
    holding_map = holdings_df.set_index('ticker').to_dict('index') if not holdings_df.empty else {}
    for ticker, raw_df in data_map.items():
        enriched = add_indicators(raw_df)
        latest = enriched.iloc[-1]
        evaluation = evaluate_latest(latest.to_dict(), ticker)
        hold = holding_map.get(ticker, {})
        avg_price = pd.to_numeric(hold.get('avg_price'), errors='coerce') if hold else None
        qty = pd.to_numeric(hold.get('qty', hold.get('quantity')), errors='coerce') if hold else None
        current_price = float(price_map.get(ticker, latest['Close']))
        avg_gap = ((current_price / avg_price) - 1) * 100 if avg_price and avg_price > 0 else None
        rows.append({
            '종목': display_names.get(ticker, ticker),
            'Ticker': ticker,
            '보유': '보유중' if hold else '미보유',
            '평균단가 대비(%)': _safe_round(avg_gap, 2),
            '프로필': evaluation.profile_label,
            '프로파일키': evaluation.profile_key,
            '프로파일유형': evaluation.profile_type,
            '현재가': _safe_round(current_price, 2),
            'RSI14': _safe_round(latest['RSI14'], 2),
            '20일선 대비(%)': _safe_round(latest['MA20DiffPct'], 2),
            '60일선 대비(%)': _safe_round(latest['MA60DiffPct'], 2),
            '고점 대비(%)': _safe_round(latest['DrawdownPct'], 2),
            '52주 위치(%)': _safe_round(latest['Position52W'], 2),
            'MACD 히스토그램': _safe_round(latest['MACDHist'], 2),
            'ATR14(%)': _safe_round(latest['ATR14Pct'], 2),
            '거래량 배수': _safe_round(latest['VolumeRatio'], 2),
            '판정': evaluation.label,
            '점수': _safe_round(evaluation.score, 2),
            '코멘트': evaluation.comment,
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    ordered = ['종목','Ticker','보유','평균단가 대비(%)','프로파일키','프로파일유형'] + SUMMARY_COLUMNS[2:]
    return result[ordered].sort_values(by=['보유','점수'], ascending=[False,False]).reset_index(drop=True)


def build_signal_table(data_map: Dict[str, pd.DataFrame], display_names: Dict[str, str]) -> pd.DataFrame:
    rows=[]
    for ticker, raw_df in data_map.items():
        latest = add_indicators(raw_df).iloc[-1]
        evaluation = evaluate_latest(latest.to_dict(), ticker)
        detail = {row['항목']: row['점수'] for row in evaluation.breakdown}
        trend_score = detail.get('20일선 대비',0) + detail.get('60일선 대비',0)
        rows.append({'종목': display_names.get(ticker, ticker), '총점': _safe_round(evaluation.score,2), 'RSI': state_badge(score_to_signal(detail.get('RSI14',0))), '낙폭': state_badge(score_to_signal(detail.get('고점 대비 낙폭',0))), '추세': state_badge(score_to_signal(trend_score)), 'MACD': state_badge(score_to_signal(detail.get('MACD 히스토그램',0))), '변동성': state_badge(score_to_signal(detail.get('ATR14 변동성',0))), '판정': evaluation.label, '핵심 코멘트': evaluation.comment})
    return pd.DataFrame(rows).sort_values(by='총점', ascending=False).reset_index(drop=True)

def build_chart_frame(df: pd.DataFrame) -> pd.DataFrame:
    enriched = add_indicators(df)
    return (
        enriched[["Date", "Close", "MA20", "MA60", "MA120", "MA200"]]
        .set_index("Date")
        .dropna(how="all")
        .round(2)
    )

def build_score_table(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    latest = add_indicators(df).iloc[-1]
    evaluation = evaluate_latest(latest.to_dict(), ticker)
    score_df = pd.DataFrame(evaluation.breakdown)
    for col in ['원점수','가중치','점수']:
        if col in score_df.columns:
            score_df[col] = pd.to_numeric(score_df[col], errors='coerce').round(2)
    return score_df


def build_contribution_chart(score_df: pd.DataFrame) -> alt.Chart:
    chart_df = score_df.copy()
    chart_df['색상'] = chart_df['점수'].apply(lambda x: '가점' if x > 0 else ('감점' if x < 0 else '중립'))
    return alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X('점수:Q', title='가중 반영 점수'), y=alt.Y('항목:N', sort='-x', title=None),
        color=alt.Color('색상:N', scale=alt.Scale(domain=['가점','중립','감점'], range=['#16a34a','#94a3b8','#dc2626']), legend=None),
        tooltip=['항목', alt.Tooltip('원점수:Q', format='.2f'), alt.Tooltip('가중치:Q', format='.2f'), alt.Tooltip('점수:Q', format='.2f'), '값', '설명']
    ).properties(height=320)


def style_summary(df: pd.DataFrame):
    def row_styles(row):
        styles = []
        for col in df.columns:
            style = ""
            if col == '보유':
                if str(row[col]) == '보유중':
                    style = 'background-color: #1d4ed8; color: white; font-weight: 700'
            elif col == '프로파일유형':
                label = str(row[col])
                if label == '개별':
                    style = 'background-color: #dbeafe; color: #1d4ed8; font-weight: 700'
                elif label == '세트':
                    style = 'background-color: #ede9fe; color: #6d28d9; font-weight: 700'
                elif label == '그룹':
                    style = 'background-color: #ecfccb; color: #3f6212; font-weight: 700'
                else:
                    style = 'background-color: #f1f5f9; color: #334155; font-weight: 700'
            elif col == '평균단가 대비(%)':
                val = row[col]
                if pd.notna(val):
                    if val >= 3:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
                    elif val > 0:
                        style = 'background-color: #fef2f2; color: #b91c1c; font-weight: 700'
                    elif val <= -5:
                        style = 'background-color: #dbeafe; color: #1d4ed8; font-weight: 700'
                    elif val < 0:
                        style = 'background-color: #eff6ff; color: #1d4ed8; font-weight: 700'
            elif col == '점수':
                val = row[col]
                if pd.notna(val):
                    if val >= 5:
                        style = 'background-color: #dcfce7; color: #166534; font-weight: 700'
                    elif val >= 3:
                        style = 'background-color: #ecfccb; color: #3f6212; font-weight: 700'
                    elif val < 1:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
            elif col == '판정':
                bg = label_to_color(row['판정'])
                style = f'background-color: {bg}; color: white; font-weight: 700'
            styles.append(style)
        return styles
    fmt = {col: '{:.2f}' for col in ['평균단가 대비(%)','현재가','RSI14','20일선 대비(%)','60일선 대비(%)','고점 대비(%)','52주 위치(%)','MACD 히스토그램','ATR14(%)','거래량 배수','점수'] if col in df.columns}
    return df.style.apply(row_styles, axis=1).format(fmt, na_rep='-')


def style_signal_table(df: pd.DataFrame):
    def color_label(row):
        bg = label_to_color(row['판정'])
        return [f'background-color: {bg}; color: white; font-weight: 700' if col == '판정' else (f"background-color: {'#16a34a' if str(row.get('구조훼손판정',''))=='유지' else '#f59e0b' if str(row.get('구조훼손판정',''))=='경고' else '#ea580c' if str(row.get('구조훼손판정',''))=='축소 후보' else '#b91c1c'}; color: white; font-weight: 700" if col == '구조훼손판정' else '') for col in df.columns]
    return df.style.apply(color_label, axis=1).format({'총점':'{:.2f}'}, na_rep='-')



def calc_structure_risk_score(row: pd.Series) -> tuple[float, str, str]:
    score = 0.0
    reasons = []

    gap = row.get("평균단가 대비(%)", None)
    ma20 = row.get("20일선 대비(%)", None)
    ma60 = row.get("60일선 대비(%)", None)
    macd_hist = row.get("MACD_hist", None)
    rsi = row.get("RSI14", None)
    profile_key = str(row.get("프로파일키", "DEFAULT"))

    if pd.notna(gap):
        if gap <= -15:
            score += 3.0
            reasons.append("평균단가 대비 손실 큼")
        elif gap <= -10:
            score += 2.0
            reasons.append("평균단가 대비 손실 확대")
        elif gap <= -5:
            score += 1.0
            reasons.append("평균단가 하회")

    if pd.notna(ma20) and ma20 < 0:
        score += 1.0
        reasons.append("20일선 하회")

    if pd.notna(ma60) and ma60 < 0:
        score += 2.0
        reasons.append("60일선 하회")

    if pd.notna(macd_hist) and macd_hist < 0:
        score += 1.0
        reasons.append("MACD 약세")

    if pd.notna(rsi) and rsi < 35:
        score += 0.5
        reasons.append("RSI 약세")

    # Profile adjustments
    if profile_key in {"SOXL", "TQQQ"}:
        # 레버리지는 단순 손실보다 추세 훼손이 중요
        score -= 0.5
        if pd.notna(ma60) and ma60 < -5:
            score += 1.0
            reasons.append("레버리지 추세 훼손")
    elif profile_key in {"KB_FINANCIAL", "SAMSUNG_FIRE_GROUP", "HYUNDAI_PREF_GROUP", "KT_DEFENSIVE", "HANA_FINANCIAL_GROUP"}:
        # 배당/방어주는 완전 손절보다 경고/축소 위주
        if pd.notna(gap) and gap <= -8:
            score += 0.5
        score -= 0.2
    elif profile_key in {"NAVER", "SAMSUNG_BIO_GROWTH", "SHIFTUP_GROWTH"}:
        # 성장주는 추세 훼손 시 더 민감
        if pd.notna(ma20) and ma20 < 0 and pd.notna(ma60) and ma60 < 0:
            score += 1.5
            reasons.append("성장주 추세 동시 훼손")

    score = max(0.0, round(score, 2))

    if score >= 6:
        label = "구조 훼손"
        summary = "비중 축소 또는 전략 재점검 우선"
    elif score >= 4:
        label = "축소 후보"
        summary = "추가매수 중단, 일부 축소 검토"
    elif score >= 2:
        label = "경고"
        summary = "추세 훼손 조짐, 보수적 대응"
    else:
        label = "유지"
        summary = "구조 훼손 신호 제한적"

    return score, label, summary



def calc_profit_signal_score(row: pd.Series) -> tuple[float, str, str]:
    score = 0.0
    reasons = []

    gap = row.get("평균단가 대비(%)", None)
    rsi = row.get("RSI14", None)
    pos52 = row.get("52주 위치(%)", None)
    ma20 = row.get("20일선 대비(%)", None)
    macd_hist = row.get("MACD_hist", None)
    profile_key = str(row.get("프로파일키", "DEFAULT"))

    if pd.notna(gap):
        if gap >= 25:
            score += 3.0
            reasons.append("평균단가 대비 수익 큼")
        elif gap >= 15:
            score += 2.0
            reasons.append("수익 구간 진입")
        elif gap >= 8:
            score += 1.0
            reasons.append("의미 있는 수익")

    if pd.notna(rsi):
        if rsi >= 72:
            score += 2.0
            reasons.append("RSI 과열")
        elif rsi >= 65:
            score += 1.0
            reasons.append("RSI 고점권")

    if pd.notna(pos52):
        if pos52 >= 85:
            score += 1.5
            reasons.append("52주 상단권")
        elif pos52 >= 75:
            score += 0.5
            reasons.append("52주 고점 근접")

    if pd.notna(ma20) and ma20 > 8:
        score += 1.0
        reasons.append("20일선 과열 이격")

    if pd.notna(macd_hist) and macd_hist < 0 and pd.notna(gap) and gap > 5:
        score += 1.0
        reasons.append("수익 상태에서 모멘텀 약화")

    # Profile adjustments
    if profile_key in {"SOXL", "TQQQ"}:
        if pd.notna(gap) and gap >= 18:
            score += 1.0
            reasons.append("레버리지 수익 보호 필요")
    elif profile_key in {"KB_FINANCIAL", "SAMSUNG_FIRE_GROUP", "HYUNDAI_PREF_GROUP", "KT_DEFENSIVE", "HANA_FINANCIAL_GROUP"}:
        score -= 0.5  # 방어/배당주는 익절 압박 완화
    elif profile_key in {"NAVER", "SAMSUNG_BIO_GROWTH", "SHIFTUP_GROWTH"}:
        if pd.notna(rsi) and rsi >= 68:
            score += 0.5

    score = max(0.0, round(score, 2))

    if score >= 5.5:
        label = "일부축소 우선"
        summary = "수익 보호 우선, 일부 비중 축소 검토"
    elif score >= 3.5:
        label = "분할익절 검토"
        summary = "과열/수익 구간, 분할익절 고려"
    elif score >= 2.0:
        label = "과열 주의"
        summary = "보유 유지 가능하나 신규추격 주의"
    else:
        label = "계속보유"
        summary = "익절 압력 제한적"

    return score, label, summary


def recommend_action_from_scores(row: pd.Series) -> tuple[str, str]:
    attractiveness = pd.to_numeric(row.get("절대매력"), errors="coerce")
    structure_label = str(row.get("구조훼손판정", ""))
    profit_label = str(row.get("익절판정", ""))
    add_label = str(row.get("추매판정", ""))
    final_label = str(row.get("최종판정", ""))

    if pd.isna(attractiveness):
        attractiveness = 3

    attractiveness = int(attractiveness)

    if attractiveness <= 2 and structure_label in {"구조 훼손", "축소 후보"}:
        return "손절 우선 검토", "절대매력 낮고 구조 훼손 신호가 강함"

    if attractiveness >= 4 and add_label in {"2차 추매 후보", "1차 추매 후보"} and structure_label in {"유지", "경고"}:
        return "추매 우선 검토", "절대매력 높고 눌림 구간"

    if attractiveness <= 2 and profit_label in {"일부축소 우선", "분할익절 검토"}:
        return "익절/축소 우선", "절대매력 낮아 수익 보호 우선"

    if attractiveness >= 4 and profit_label in {"일부축소 우선", "분할익절 검토"}:
        return "부분익절 후 보유", "좋은 종목이지만 과열 구간"

    if final_label in {"계속보유", "관망"}:
        return "보유/관망", "명확한 행동 신호 제한적"

    return "관찰 유지", "추가 신호 확인 필요"


def style_holdings(df: pd.DataFrame):
    def row_styles(row):
        styles = []
        for col in df.columns:
            style = ""
            if col == '보유':
                style = 'background-color: #1d4ed8; color: white; font-weight: 700'
            elif col in ['손익률(%)', '평균단가 대비(%)']:
                val = row[col]
                if pd.notna(val):
                    if val >= 3:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
                    elif val > 0:
                        style = 'background-color: #fef2f2; color: #b91c1c; font-weight: 700'
                    elif val <= -5:
                        style = 'background-color: #dbeafe; color: #1d4ed8; font-weight: 700'
                    elif val < 0:
                        style = 'background-color: #eff6ff; color: #1d4ed8; font-weight: 700'
                    else:
                        style = 'background-color: #f8fafc; color: #475569'
            elif col == '평가손익':
                val = row[col]
                if pd.notna(val):
                    if val > 0:
                        style = 'background-color: #fef2f2; color: #b91c1c; font-weight: 700'
                    elif val < 0:
                        style = 'background-color: #eff6ff; color: #1d4ed8; font-weight: 700'
            elif col == '익절판정':
                label = str(row[col])
                color_map = {
                    '일부축소 우선': '#b91c1c',
                    '분할익절 검토': '#9333ea',
                    '과열 주의': '#f59e0b',
                    '계속보유': '#0f766e',
                }
                bg = color_map.get(label, '#64748b')
                style = f'background-color: {bg}; color: white; font-weight: 700'
            elif col == '구조훼손판정':
                label = str(row[col])
                color_map = {
                    '구조 훼손': '#b91c1c',
                    '축소 후보': '#ea580c',
                    '경고': '#f59e0b',
                    '유지': '#16a34a',
                }
                bg = color_map.get(label, '#64748b')
                style = f'background-color: {bg}; color: white; font-weight: 700'
            elif col == '절대매력':
                val = row[col]
                if pd.notna(val):
                    if val >= 5:
                        style = 'background-color: #dcfce7; color: #166534; font-weight: 700'
                    elif val == 4:
                        style = 'background-color: #ecfccb; color: #3f6212; font-weight: 700'
                    elif val == 3:
                        style = 'background-color: #f8fafc; color: #475569; font-weight: 700'
                    elif val == 2:
                        style = 'background-color: #ffedd5; color: #9a3412; font-weight: 700'
                    else:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
            elif col == '행동추천':
                label = str(row[col])
                color_map = {
                    '추매 우선 검토': '#15803d',
                    '부분익절 후 보유': '#7c3aed',
                    '익절/축소 우선': '#ea580c',
                    '손절 우선 검토': '#b91c1c',
                    '보유/관망': '#475569',
                    '관찰 유지': '#64748b',
                }
                bg = color_map.get(label, '#64748b')
                style = f'background-color: {bg}; color: white; font-weight: 700'
            elif col == '추매판정':
                label = str(row[col])
                color_map = {
                    '2차 추매 후보': '#15803d',
                    '1차 추매 후보': '#16a34a',
                    '관망': '#64748b',
                    '추격 금지': '#dc2626',
                }
                bg = color_map.get(label, '#64748b')
                style = f'background-color: {bg}; color: white; font-weight: 700'
            elif col == '프로필':
                label = str(row[col])
                if '개별' in label:
                    style = 'background-color: #e0e7ff; color: #3730a3; font-weight: 700'
                elif '계열' in label:
                    style = 'background-color: #ede9fe; color: #6d28d9; font-weight: 700'
                else:
                    style = 'background-color: #f1f5f9; color: #334155; font-weight: 700'
            elif col == '익절점수':
                val = row[col]
                if pd.notna(val):
                    if val >= 5.5:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
                    elif val >= 3.5:
                        style = 'background-color: #f3e8ff; color: #7e22ce; font-weight: 700'
                    elif val >= 2:
                        style = 'background-color: #fef3c7; color: #92400e; font-weight: 700'
                    else:
                        style = 'background-color: #ccfbf1; color: #115e59; font-weight: 700'
            elif col == '구조훼손점수':
                val = row[col]
                if pd.notna(val):
                    if val >= 6:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
                    elif val >= 4:
                        style = 'background-color: #ffedd5; color: #9a3412; font-weight: 700'
                    elif val >= 2:
                        style = 'background-color: #fef3c7; color: #92400e; font-weight: 700'
                    else:
                        style = 'background-color: #dcfce7; color: #166534; font-weight: 700'
            elif col == '추매점수':
                val = row[col]
                if pd.notna(val):
                    if val >= 4:
                        style = 'background-color: #dcfce7; color: #166534; font-weight: 700'
                    elif val >= 2:
                        style = 'background-color: #ecfccb; color: #3f6212; font-weight: 700'
                    elif val < 0:
                        style = 'background-color: #fee2e2; color: #991b1b; font-weight: 700'
            styles.append(style)
        return styles

    fmt = {
        '평균단가': '{:.2f}',
        '현재가': '{:.2f}',
        '수량': '{:.0f}',
        '손익률(%)': '{:.2f}',
        '평균단가 대비(%)': '{:.2f}',
        '평가손익': '{:.2f}',
        '시장점수': '{:.2f}',
        '구조훼손점수': '{:.2f}',
        '익절점수': '{:.2f}',
        '추매점수': '{:.0f}',
        '절대매력': '{:.0f}',
    }
    return df.style.apply(row_styles, axis=1).format(fmt, na_rep='-')


def render_top_metrics(summary_df: pd.DataFrame, data_count: int, holdings_count: int) -> None:
    metric_items = [('조회 종목 수', data_count), ('보유 종목 수', holdings_count), ('관심 구간 이상', int((summary_df['점수'] >= 3).sum())), ('분할매수 후보', int((summary_df['판정'] == '1차 분할매수 후보').sum()))]
    cards = [f"<div class='metric-card'><div class='metric-title'>{title}</div><div class='metric-value'>{value}</div></div>" for title, value in metric_items]
    st.markdown(f"<div class='metric-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def render_profile_card(ticker: str, display_name: str) -> None:
    _, profile = get_profile_for_ticker(ticker)
    profile_type = profile.get('type', '기본')
    logic = profile.get('logic_summary', profile.get('description', ''))
    rules = profile.get('buy_add_rules', [])
    rules_html = ''.join([f"<li>{rule}</li>" for rule in rules[:4]])
    st.markdown(
        f"""
        <div class='card'>
            <div class='section-title'>{display_name} <span class='badge'>{profile['label']}</span></div>
            <div style='font-size:0.88rem;color:#93c5fd;margin-bottom:0.20rem'>프로파일 키: {get_profile_for_ticker(ticker)[0]}</div>
            <div style='font-size:0.88rem;color:#93c5fd;margin-bottom:0.55rem'>프로파일 유형: {profile_type}</div>
            <div style='font-size:0.95rem;color:#cbd5e1'>{logic}</div>
            <div style='font-size:0.9rem;color:#e2e8f0;margin-top:0.8rem'><strong>추매 기준 요약</strong><ul style='margin-top:0.35rem'>{rules_html}</ul></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def holdings_view(
    holdings_df: pd.DataFrame,
    data_map: Dict[str, pd.DataFrame],
    display_names: Dict[str, str],
    price_map: Dict[str, float],
) -> pd.DataFrame:
    if holdings_df.empty:
        return pd.DataFrame()
    rows=[]
    for _, row in holdings_df.iterrows():
        ticker=row['ticker']
        if ticker not in data_map:
            continue
        latest = add_indicators(data_map[ticker]).iloc[-1]
        current_price = float(price_map.get(ticker, latest['Close']))
        avg=float(row['avg_price'])
        qty=float(row.get('qty', row.get('quantity', 0)))
        pnl=(current_price-avg)*qty
        ret=((current_price/avg)-1)*100 if avg else None
        eval_result = evaluate_latest(latest.to_dict(), ticker)
        add_score=0
        if ret is not None:
            if ret <= -10: add_score += 3
            elif ret <= -5: add_score += 2
            elif ret <= 0: add_score += 1
            elif ret >= 20: add_score -= 2
            elif ret >= 10: add_score -= 1
        if pd.notna(latest['MA20DiffPct']) and latest['MA20DiffPct'] <= 0: add_score += 1
        if pd.notna(latest['MA60DiffPct']) and latest['MA60DiffPct'] < 0: add_score -= 1
        if add_score >= 4: add_label='2차 추매 후보'
        elif add_score >= 2: add_label='1차 추매 후보'
        elif add_score >= 0: add_label='관망'
        else: add_label='추격 금지'
        rows.append({
            '종목': display_names.get(ticker, row.get('name', ticker) or ticker),
            'Ticker': ticker,
            '평균단가': round(avg,2),
            '현재가': round(current_price,2),
            '수량': qty,
            '손익률(%)': round(ret,2) if ret is not None else None,
            '평균단가 대비(%)': round(ret,2) if ret is not None else None,
            '평가손익': round(pnl,2),
            '시장점수': round(eval_result.score,2),
            '추매점수': add_score,
            '추매판정': add_label,
            '프로필': eval_result.profile_label,
        })
    out = pd.DataFrame(rows)
    if out.empty: return out
    _risk_results = out.apply(lambda r: calc_structure_risk_score(r), axis=1, result_type='expand')
    _risk_results.columns = ['구조훼손점수', '구조훼손판정', '구조훼손요약']
    out = pd.concat([out, _risk_results], axis=1)
    _profit_results = out.apply(lambda r: calc_profit_signal_score(r), axis=1, result_type='expand')
    _profit_results.columns = ['익절점수', '익절판정', '익절요약']
    out = pd.concat([out, _profit_results], axis=1)
    _final_results = out.apply(
        lambda r: decide_final_action(r['구조훼손판정'], r['익절판정'], r['추매판정']),
        axis=1,
        result_type='expand'
    )
    _final_results.columns = ['최종판정', '판정요약']
    out = pd.concat([out, _final_results], axis=1)
    ordered = ['종목','Ticker','평균단가','현재가','수량','손익률(%)','평균단가 대비(%)','평가손익','시장점수','구조훼손점수','구조훼손판정','익절점수','익절판정','추매점수','추매판정','최종판정','판정요약','프로필']
    ordered = [c for c in ordered if c in out.columns]
    return out[ordered].sort_values(by=['구조훼손점수','추매점수','시장점수'], ascending=[False,False,False]).reset_index(drop=True)



def render_login_gate() -> str | None:
    seed_default_users()
    if st.session_state.get('authenticated_user'):
        return st.session_state['authenticated_user']

    st.markdown("""
    <div class="card" style="max-width:560px; margin:24px auto;">
      <div class="section-title">로그인</div>
      <div class="small-note">보유 종목, 평균단가, 관심종목은 로그인 후에만 표시됩니다.</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form('login_form', clear_on_submit=False):
        login_user = st.text_input('사용자 ID', placeholder='예: master')
        login_password = st.text_input('비밀번호', type='password')
        submitted = st.form_submit_button('로그인', width='stretch')

    if submitted:
        ok, user_info = verify_login(login_user.strip(), login_password)
        if ok:
            st.session_state['authenticated_user'] = login_user.strip()
            st.session_state['authenticated_role'] = user_info.get('role', 'user')
            st.session_state['is_guest'] = False
            st.success(f"{login_user.strip()} 로그인 성공")
            st.rerun()
        else:
            st.error('로그인 실패: 사용자 ID 또는 비밀번호를 확인하세요.')

    if st.button('Guest로 시작', width='stretch'):
        st.session_state['authenticated_user'] = 'guest'
        st.session_state['authenticated_role'] = 'guest'
        st.session_state['is_guest'] = True
        st.session_state['guest_watchlist'] = ', '.join(DEFAULT_TICKERS)
        st.session_state['ticker_text'] = st.session_state['guest_watchlist']
        st.rerun()

    st.info('초기 계정은 README에 안내된 기본 계정을 사용한 뒤 users.json에서 변경하세요.')
    return st.session_state.get('authenticated_user')


def render_trade_panel(active_user: str):
    st.markdown("---")
    st.subheader("거래 기록 입력")

    if st.session_state.get("is_guest"):
        st.info("Guest 모드에서는 거래 기록이 저장되지 않습니다.")
        return

    with st.form("trade_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            trade_ticker = st.text_input("종목 코드", placeholder="예: MSFT 또는 005930.KS").strip().upper()
        with c2:
            trade_qty = st.number_input("수량", min_value=1, step=1, value=1)
        with c3:
            trade_price = st.number_input("가격", min_value=0.0, step=0.01, value=0.0, format="%.4f")

        trade_memo = st.text_input("메모", placeholder="예: 1차 진입 / 분할매수 / 일부익절")
        trade_date = st.date_input("거래 날짜", value=date.today(), key="trade_date")

        b1, b2 = st.columns(2)
        with b1:
            buy_submitted = st.form_submit_button("매수 기록", width="stretch")
        with b2:
            sell_submitted = st.form_submit_button("매도 기록", width="stretch")

    if buy_submitted:
        trade_dt = datetime.combine(trade_date, datetime.min.time())
        if not trade_ticker:
            st.error("종목 코드를 입력하세요.")
            return
        if trade_price <= 0:
            st.error("가격은 0보다 커야 합니다.")
            return
        try:
            record_buy(username=active_user, ticker=trade_ticker, quantity=int(trade_qty), price=float(trade_price), memo=trade_memo,executed_at=trade_dt)
            st.success(f"{trade_ticker} 매수 기록이 저장되었습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"매수 기록 실패: {e}")

    if sell_submitted:
        trade_dt = datetime.combine(trade_date, datetime.min.time())
        if not trade_ticker:
            st.error("종목 코드를 입력하세요.")
            return
        if trade_price <= 0:
            st.error("가격은 0보다 커야 합니다.")
            return
        try:
            record_sell(username=active_user, ticker=trade_ticker, quantity=int(trade_qty), price=float(trade_price), memo=trade_memo,executed_at=trade_dt)
            st.success(f"{trade_ticker} 매도 기록이 저장되었습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"매도 기록 실패: {e}")

    st.markdown("---")
    st.subheader("최근 거래 기록")

    try:
        tx_rows = list_transactions(active_user, limit=200)
        if tx_rows:
            tx_df = pd.DataFrame(tx_rows)

            if "memo" in tx_df.columns:
                hide_test = st.checkbox("테스트 거래 숨기기", value=True, key="hide_test_trades")
                if hide_test:
                    tx_df = tx_df[~tx_df["memo"].apply(is_test_trade_memo)].copy()

            if tx_df.empty:
                st.caption("표시할 거래 기록이 없습니다.")
            else:
                if "tx_type" in tx_df.columns:
                    tx_df["tx_type"] = tx_df["tx_type"].replace({"BUY": "매수", "SELL": "매도"})

                tx_df["currency"] = tx_df["ticker"].apply(infer_currency_from_ticker)
                tx_df = tx_df.rename(columns={
                    "ticker": "종목코드",
                    "tx_type": "구분",
                    "quantity": "수량",
                    "price": "가격",
                    "fee": "수수료",
                    "memo": "메모",
                    "realized_pnl": "실현손익",
                    "executed_at": "거래시간",
                    "currency": "통화",
                })

                numeric_cols = ["수량", "가격", "수수료", "실현손익"]
                for col in numeric_cols:
                    if col in tx_df.columns:
                        tx_df[col] = pd.to_numeric(tx_df[col], errors="coerce").astype(float)

                if "거래시간" in tx_df.columns:
                    tx_df["거래시간"] = pd.to_datetime(tx_df["거래시간"]).dt.strftime("%Y-%m-%d %H:%M")

                krx_df = load_krx_lookup()
                name_map = build_name_map(krx_df)
                tx_df["종목명"] = tx_df["종목코드"].map(name_map).fillna("")
                tx_df["종목"] = tx_df.apply(
                    lambda r: f"{r['종목명']} ({r['종목코드']})" if str(r.get("종목명", "")).strip() else r["종목코드"],
                    axis=1,
                )

                tx_df["가격표시"] = tx_df.apply(lambda r: format_money_by_currency(r.get("가격"), r.get("통화", "USD")), axis=1)
                tx_df["수수료표시"] = tx_df.apply(lambda r: format_money_by_currency(r.get("수수료"), r.get("통화", "USD")), axis=1)
                tx_df["실현손익표시"] = tx_df.apply(lambda r: format_money_by_currency(r.get("실현손익"), r.get("통화", "USD")), axis=1)

                display_cols = ["종목", "구분", "통화", "수량", "가격표시", "수수료표시", "실현손익표시", "메모", "거래시간"]
                display_df = tx_df[[c for c in display_cols if c in tx_df.columns]].copy()
                display_df = display_df.rename(columns={"가격표시": "가격", "수수료표시": "수수료", "실현손익표시": "실현손익"})

                st.dataframe(
                    display_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "종목": st.column_config.TextColumn("종목"),
                        "구분": st.column_config.TextColumn("구분"),
                        "통화": st.column_config.TextColumn("통화"),
                        "수량": st.column_config.NumberColumn("수량", format="%,.2f"),
                        "가격": st.column_config.TextColumn("가격"),
                        "수수료": st.column_config.TextColumn("수수료"),
                        "실현손익": st.column_config.TextColumn("실현손익"),
                        "메모": st.column_config.TextColumn("메모"),
                        "거래시간": st.column_config.TextColumn("거래시간"),
                    },
                )

                st.markdown("### 거래기록 관리")
                admin_tx_df = fetch_transactions_admin(active_user, limit=300)
                if not admin_tx_df.empty:
                    if hide_test if "hide_test" in locals() else False:
                        admin_tx_df = admin_tx_df[~admin_tx_df["memo"].apply(is_test_trade_memo)].copy()
                    admin_tx_df["currency"] = admin_tx_df["ticker"].apply(infer_currency_from_ticker)
                    admin_tx_df["executed_display"] = pd.to_datetime(admin_tx_df["executed_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
                    admin_tx_df["name"] = admin_tx_df["ticker"].map(name_map).fillna("")
                    admin_tx_df["display"] = admin_tx_df.apply(
                        lambda r: f"#{int(r['id'])} | {(r['name'] + ' (' + r['ticker'] + ')') if str(r['name']).strip() else r['ticker']} | {r['tx_type']} | {float(r['quantity']):,.2f}주 | {format_money_by_currency(r['price'], r['currency'])} | {r['executed_display']}",
                        axis=1,
                    )
                    selected_tx_display = st.selectbox("삭제할 거래 선택", options=admin_tx_df["display"].tolist(), key="delete_tx_select")
                    selected_tx_id = int(admin_tx_df.loc[admin_tx_df["display"] == selected_tx_display, "id"].iloc[0])
                    if st.button("선택 거래 삭제", type="secondary"):
                        delete_transaction_by_id(active_user, selected_tx_id)
                        st.success("선택한 거래를 삭제했습니다.")
                        st.rerun()
                else:
                    st.caption("삭제할 거래가 없습니다.")
        else:
            st.caption("거래 기록이 없습니다.")
    except Exception as e:
        st.error(f"거래 기록 조회 실패: {e}")

def main() -> None:
    st.title('개인 투자 판단 보조기')
    st.caption('관심 종목과 보유 종목을 분리하고, 사용자별 관심 목록과 평균단가 기반 추매 판단을 함께 보는 대시보드')

    active_user = render_login_gate()
    if not active_user:
        return

    raw_items = load_watchlist(active_user)
    if not raw_items:
        raw_items = list(DEFAULT_TICKERS)

    items = _normalize_watchlist_items(raw_items)
    st.session_state["watchlist_items"] = items

    if st.session_state.get("watchlist_editor_needs_sync") or "ticker_text_input" not in st.session_state:
        st.session_state["ticker_text_input"] = ", ".join([item["ticker"] for item in items])
        st.session_state["watchlist_editor_needs_sync"] = False

    with st.sidebar:
        st.header('설정')
        if st.button('로그아웃', width='stretch'):
            for key in [
                'authenticated_user', 'authenticated_role', 'is_guest', 'guest_watchlist',
                'active_user', 'watchlist_items', 'ticker_text_input', 'watchlist_notice',
                'watchlist_editor_needs_sync'
            ]:
                st.session_state.pop(key, None)
            st.rerun()

        st.caption(f'현재 사용자: {active_user}')
        role = st.session_state.get('authenticated_role', 'user')
        st.caption(f'권한: {role}')
        if active_user == 'guest':
            st.warning('Guest 모드입니다. 저장은 현재 세션에서만 유지됩니다.')

        current_watchlist_text = st.text_area(
            '관심 종목 (쉼표로 구분)',
            key='ticker_text_input',
            help='미국: SOXL, QQQ / 한국: 종목명 검색으로 추가하거나 005930.KS 형식으로 직접 입력',
            height=120
        )

        attractiveness_score = st.selectbox(
            "절대 매력 점수(신규 기본값)",
            options=[1, 2, 3, 4, 5],
            index=2,
            help="새로 추가하는 관심종목의 기본 점수입니다."
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button('관심종목 저장', width='stretch'):
                persist_current_watchlist(active_user, current_watchlist_text, default_score=attractiveness_score)
                st.rerun()
        with c2:
            if st.button('초기화', width='stretch'):
                reset_current_watchlist(active_user)
                st.rerun()

        if st.session_state.get('watchlist_notice'):
            st.success(st.session_state['watchlist_notice'])
            del st.session_state['watchlist_notice']

        st.markdown('### 국장 종목 검색')
        krx_df = load_krx_lookup()
        search_name = st.text_input('종목명/코드 검색', placeholder='예: 삼성, 하이닉스, 005930')
        with st.expander('최신 KRX 목록 갱신(선택)', expanded=False):
            st.caption('기본값은 전체 KRX CSV입니다. 실패해도 기존 CSV를 계속 사용합니다.')
            if st.button('KRX 목록 업데이트', width='stretch'):
                ok, message, refreshed_df = update_krx_tickers_from_pykrx()
                if ok:
                    load_krx_lookup.clear()
                    krx_df = refreshed_df if refreshed_df is not None else load_krx_lookup()
                    st.success(message)
                else:
                    st.warning(message)

        matched_df = search_krx_tickers(search_name, krx_df, limit=30)
        if matched_df.empty:
            st.caption('검색 결과 없음')
        else:
            matched_df = matched_df.copy()
            matched_df['표시'] = matched_df.apply(
                lambda row: f"{row['name']} | {row['ticker_yf']} | {row['market']}",
                axis=1
            )
            selected_option = st.selectbox('검색 결과', options=matched_df['표시'].tolist())
            selected_row = matched_df.loc[matched_df['표시'] == selected_option].iloc[0]
            st.caption(f"선택: {selected_row['name']} ({selected_row['ticker_yf']})")
            st.button('관심 종목에 추가', width='stretch', on_click=append_ticker_from_search, args=(selected_row['ticker_yf'],))

        period = st.selectbox('조회 기간', PERIOD_OPTIONS, index=PERIOD_OPTIONS.index(DEFAULT_PERIOD))
        interval = st.selectbox('간격', INTERVAL_OPTIONS, index=INTERVAL_OPTIONS.index(DEFAULT_INTERVAL))
        if st.button('새로고침', type='primary', width='stretch'):
            load_market_data.clear()

    holdings_df = load_holdings(active_user)
    if not holdings_df.empty:
        if "quantity" in holdings_df.columns:
            holdings_df = holdings_df[holdings_df["quantity"] > 0].copy()
        elif "qty" in holdings_df.columns:
            holdings_df = holdings_df[holdings_df["qty"] > 0].copy()

    holdings_tickers = holdings_df['ticker'].tolist() if not holdings_df.empty else []

    items = _normalize_watchlist_items(st.session_state.get("watchlist_items", []))
    st.session_state["watchlist_items"] = items
    watchlist = [item["ticker"] for item in items]
    scores = {item["ticker"]: item["attractiveness_score"] for item in items}

    combined = []
    for t in watchlist + holdings_tickers:
        if t not in combined:
            combined.append(t)

    tickers = tuple(combined)
    if not tickers:
        st.warning('최소 1개 이상의 티커를 입력해야 합니다.')
        st.stop()

    with st.spinner('시장 데이터를 불러오는 중...'):
        data_map, errors, _, price_map = load_market_data(
            tickers=tickers,
            period=period,
            interval=interval
        )

    if errors:
        with st.expander('불러오지 못한 종목', expanded=False):
            for ticker, error in errors.items():
                st.write(f'- {ticker}: {error}')

    if not data_map:
        st.error('불러온 데이터가 없습니다. 티커 형식을 다시 확인하세요.')
        st.stop()

    krx_df = load_krx_lookup()
    display_names = normalize_display_names(tuple(data_map.keys()), krx_df)
    summary_df = market_summary_rows(data_map, display_names, holdings_df, price_map)
    if not summary_df.empty:
        summary_df["절대매력"] = summary_df["Ticker"].map(scores).fillna(3).astype(int)

    signal_df = build_signal_table(data_map, display_names)
    holdings_view_df = holdings_view(holdings_df, data_map, display_names, price_map)

    if not holdings_view_df.empty:
        holdings_view_df["절대매력"] = holdings_view_df["Ticker"].map(scores).fillna(3).astype(int)
        _action_df = holdings_view_df.apply(
            lambda row: recommend_action_from_scores(row),
            axis=1,
            result_type="expand"
        )
        _action_df.columns = ["행동추천", "행동요약"]
        holdings_view_df = pd.concat([holdings_view_df, _action_df], axis=1)

    render_top_metrics(summary_df, len(data_map), len(holdings_df))

    st.markdown("### 실현손익 요약")
    try:
        tx_rows = list_transactions(active_user, limit=1000)
        tx_df = pd.DataFrame(tx_rows)
        pnl_adj = load_pnl_adjustments(active_user)
        if not tx_df.empty:
            tx_df["realized_pnl"] = pd.to_numeric(tx_df["realized_pnl"], errors="coerce").fillna(0)
            tx_df["tx_type"] = tx_df["tx_type"].astype(str)
            tx_df["currency"] = tx_df["ticker"].apply(infer_currency_from_ticker)
            tx_df = tx_df[~tx_df["memo"].apply(is_test_trade_memo) if "memo" in tx_df.columns else [True] * len(tx_df)]
            sell_df = tx_df[tx_df["tx_type"] == "SELL"]

            krw_sell = sell_df[sell_df["currency"] == "KRW"]
            usd_sell = sell_df[sell_df["currency"] == "USD"]

            total_realized_krw = krw_sell["realized_pnl"].sum() + pnl_adj.get("KRW", 0.0)
            total_realized_usd = usd_sell["realized_pnl"].sum() + pnl_adj.get("USD", 0.0)
            trade_count = len(sell_df)
            win_count = len(sell_df[sell_df["realized_pnl"] > 0])
            win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("누적 실현손익(KRW)", format_money_by_currency(total_realized_krw, "KRW"))
            c2.metric("누적 실현손익(USD)", format_money_by_currency(total_realized_usd, "USD"))
            c3.metric("매도 횟수", trade_count)
            c4.metric("승률(%)", f"{win_rate:.1f}")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("누적 실현손익(KRW)", format_money_by_currency(pnl_adj.get("KRW", 0.0), "KRW"))
            c2.metric("누적 실현손익(USD)", format_money_by_currency(pnl_adj.get("USD", 0.0), "USD"))
            c3.metric("매도 횟수", 0)
            c4.metric("승률(%)", "0.0")

        with st.expander("누적 실현손익 보정", expanded=False):
            adj_c1, adj_c2 = st.columns(2)
            with adj_c1:
                pnl_adj_krw = st.number_input("KRW 보정값", value=float(pnl_adj.get("KRW", 0.0)), step=1000.0)
            with adj_c2:
                pnl_adj_usd = st.number_input("USD 보정값", value=float(pnl_adj.get("USD", 0.0)), step=1.0)
            if st.button("실현손익 보정 저장"):
                save_pnl_adjustments(active_user, pnl_adj_krw, pnl_adj_usd)
                st.success("실현손익 보정값을 저장했습니다.")
                st.rerun()
    except Exception as e:
        st.error(f"실현손익 계산 오류: {e}")

    tab1, tab2, tab3 = st.tabs(['관심 종목', '보유 종목', '매매복기'])

    with tab1:
        st.subheader('종합 상태판')
        st.caption('핵심 컬럼 중심으로 색을 강화해 빠르게 읽을 수 있게 조정했다.')
        st.dataframe(style_summary(summary_df), width='stretch', hide_index=True)

        st.subheader('신호등형 요약표')
        st.caption('보유 여부와 평균단가 대비 괴리를 함께 보도록 확장했다.')
        st.dataframe(style_signal_table(signal_df), width='stretch', hide_index=True)

        st.subheader('개별 종목 보기')
        select_options = {f"{display_names[t]} ({t})": t for t in data_map.keys()}
        selected_display = st.selectbox('차트 확인 종목', options=list(select_options.keys()))
        selected_ticker = select_options[selected_display]
        selected_name = display_names.get(selected_ticker, selected_ticker)
        render_profile_card(selected_ticker, selected_name)

        c1, c2 = st.columns([1.3, 1])
        with c1:
            chart_df = build_chart_frame(data_map[selected_ticker]).reset_index().melt(
                'Date',
                var_name='구분',
                value_name='가격'
            )
            chart_df["구분"] = pd.Categorical(
                chart_df["구분"],
                categories=["Close", "MA20", "MA60", "MA120", "MA200"],
                ordered=True
            )
            chart = alt.Chart(chart_df).mark_line().encode(
                x='Date:T',
                y='가격:Q',
                color=alt.Color('구분:N', sort=["Close", "MA20", "MA60", "MA120", "MA200"]),
                tooltip=['Date:T', '구분:N', alt.Tooltip('가격:Q', format=',.2f')]
            ).properties(height=360)
            st.altair_chart(chart, width='stretch')

        with c2:
            score_df = build_score_table(data_map[selected_ticker], selected_ticker)
            st.markdown('#### 항목별 점수 기여도')
            st.altair_chart(build_contribution_chart(score_df), width='stretch')

        st.markdown('#### 정량 점수표')
        st.dataframe(score_df, width='stretch', hide_index=True)

    with tab2:
        render_cash_section(active_user)
        st.subheader('보유 종목 현황')
        if holdings_df.empty:
            st.info('현재 사용자 보유 종목 파일이 없습니다.')
        else:
            st.caption('보유 종목은 data/holdings/<사용자>.csv 에서 로드된다. 평균단가 대비 괴리, 구조 훼손 경고, 익절 신호를 함께 본다.')
            st.dataframe(style_holdings(holdings_view_df), width='stretch', hide_index=True)
            st.caption('익절판정: 계속보유 / 과열 주의 / 분할익절 검토 / 일부축소 우선')

            st.markdown("### 보유종목 절대 매력 점수 수정")
            edited_scores = {}
            cols = st.columns(3)
            name_map = build_name_map(krx_df)

            editable_items = []
            seen = set()
            for item in items:
                ticker = item["ticker"]
                score = item["attractiveness_score"]
                editable_items.append({"ticker": ticker, "attractiveness_score": score})
                seen.add(ticker)

            for ticker in holdings_tickers:
                if ticker not in seen:
                    editable_items.append({"ticker": ticker, "attractiveness_score": scores.get(ticker, 3)})
                    seen.add(ticker)

            for i, item in enumerate(editable_items):
                ticker = item["ticker"]
                current_score = int(item.get("attractiveness_score", 3))
                display_name = name_map.get(ticker, "")
                display = f"{display_name} ({ticker})" if display_name else ticker
                with cols[i % 3]:
                    st.markdown(f"<div style='font-size:0.85rem; margin-bottom:4px'>{display}</div>", unsafe_allow_html=True)
                    edited_scores[ticker] = st.selectbox(
                        f"절대매력_{ticker}",
                        [1, 2, 3, 4, 5],
                        index=[1, 2, 3, 4, 5].index(current_score),
                        key=f"score_{ticker}",
                        label_visibility="collapsed"
                    )

            if st.button("보유종목 절대 매력 점수 저장"):
                existing_items = _normalize_watchlist_items(st.session_state.get("watchlist_items", []))
                existing_tickers = {item["ticker"] for item in existing_items}
                updated_items = []

                for item in existing_items:
                    ticker = item["ticker"]
                    updated_items.append({
                        "ticker": ticker,
                        "attractiveness_score": edited_scores.get(ticker, item.get("attractiveness_score", 3)),
                    })

                for ticker in edited_scores:
                    if ticker not in existing_tickers:
                        updated_items.append({
                            "ticker": ticker,
                            "attractiveness_score": edited_scores[ticker],
                        })

                save_watchlist(active_user, updated_items)
                st.session_state["watchlist_items"] = updated_items
                st.session_state["watchlist_editor_needs_sync"] = True
                st.success("절대 매력 점수 저장 완료")
                st.rerun()

            st.markdown("### 보유종목 조정 도구")
            tool_c1, tool_c2 = st.columns(2)

            with tool_c1:
                st.markdown("#### 수량/평단 수동 조정")
                if holdings_tickers:
                    selected_holding = st.selectbox("조정할 종목", options=holdings_tickers, key="manual_adjust_ticker")
                    selected_row = holdings_df[holdings_df["ticker"] == selected_holding].iloc[0]
                    qty_default = float(selected_row.get("quantity", selected_row.get("qty", 0)) or 0)
                    avg_default = float(selected_row.get("avg_price", 0) or 0)
                    manual_qty = st.number_input("수량", min_value=0.0, value=qty_default, step=1.0, key="manual_adjust_qty")
                    manual_avg = st.number_input("평균단가", min_value=0.0, value=avg_default, step=0.01, key="manual_adjust_avg")
                    if st.button("보유종목 값 저장"):
                        upsert_holding_snapshot(active_user, selected_holding, manual_qty, manual_avg)
                        st.success("보유종목 수량/평단 반영 완료")
                        st.rerun()
                else:
                    st.caption("보유종목이 없으면 조정할 수 없습니다.")

            with tool_c2:
                st.markdown("#### 액면분할/병합 반영")
                if holdings_tickers:
                    split_ticker = st.selectbox("분할 반영 종목", options=holdings_tickers, key="split_ticker")
                    split_ratio = st.number_input("분할 비율", min_value=0.01, value=1.0, step=0.01, help="예: 5대1 분할이면 5 입력", key="split_ratio")
                    if st.button("분할 비율 반영"):
                        ok = apply_split_adjustment(active_user, split_ticker, float(split_ratio))
                        if ok:
                            st.success("액면분할/병합 반영 완료")
                            st.rerun()
                        else:
                            st.error("반영 실패: 보유종목 또는 비율을 확인하세요.")
                else:
                    st.caption("보유종목이 없으면 조정할 수 없습니다.")
            if not holdings_view_df.empty:
                st.markdown('#### 추매 후보 보기')
                candidate_df = holdings_view_df[holdings_view_df['추매점수'] >= 2].copy()
                if candidate_df.empty:
                    st.info('현재 기준으로 1차 추매 후보 이상 종목이 없습니다.')
                else:
                    st.dataframe(candidate_df, width='stretch', hide_index=True)

        render_trade_panel(active_user)

    with tab3:
        render_review_tab(active_user)    

if __name__ == '__main__':
    main()
