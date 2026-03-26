from __future__ import annotations
from typing import Dict, List, Tuple

from dotenv import load_dotenv
import os

load_dotenv()

APP_ENV = os.getenv("APP_ENV")
SECRET_KEY = os.getenv("SECRET_KEY")

import altair as alt
import pandas as pd
import streamlit as st

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
from src.holdings_store import load_holdings
from src.indicators import add_indicators
from src.krx_lookup import build_name_map, load_krx_tickers, search_krx_tickers, update_krx_tickers_from_pykrx
from src.watchlist_store import load_watchlist, reset_watchlist, save_watchlist

APP_VERSION = "v16-exit-and-ux"

st.set_page_config(page_title="개인 투자 판단 보조기", layout="wide")

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


@st.cache_data(ttl=60 * 30)
def load_market_data(tickers: Tuple[str, ...], period: str, interval: str) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str], Dict[str, str]]:
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


def append_ticker_from_search(ticker_to_add: str) -> None:
    current_text = st.session_state.get("ticker_text", "")
    current = [item.strip().upper() for item in current_text.split(",") if item.strip()]
    if ticker_to_add.upper() not in current:
        current.append(ticker_to_add.upper())
    st.session_state["ticker_text"] = ", ".join(current)


def persist_current_watchlist(user_id: str) -> None:
    current_text = st.session_state.get("ticker_text", "")
    save_watchlist(user_id=user_id, tickers=current_text)
    st.session_state["watchlist_notice"] = f"{user_id} 관심종목을 저장했습니다."


def reset_current_watchlist(user_id: str) -> None:
    reset_watchlist(user_id=user_id)
    default_items = load_watchlist(user_id=user_id)
    st.session_state["ticker_text"] = ", ".join(default_items)
    st.session_state["watchlist_notice"] = f"{user_id} 관심종목을 기본값으로 초기화했습니다."


def format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:.2f}%"


def market_summary_rows(data_map: Dict[str, pd.DataFrame], display_names: Dict[str, str], holdings_df: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    holding_map = holdings_df.set_index('ticker').to_dict('index') if not holdings_df.empty else {}
    for ticker, raw_df in data_map.items():
        enriched = add_indicators(raw_df)
        latest = enriched.iloc[-1]
        evaluation = evaluate_latest(latest.to_dict(), ticker)
        hold = holding_map.get(ticker, {})
        avg_price = pd.to_numeric(hold.get('avg_price'), errors='coerce') if hold else None
        qty = pd.to_numeric(hold.get('qty'), errors='coerce') if hold else None
        current_price = float(latest['Close'])
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
    return enriched[['Date','Close','MA20','MA60']].set_index('Date').dropna(how='all').round(2)


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


def holdings_view(holdings_df: pd.DataFrame, data_map: Dict[str, pd.DataFrame], display_names: Dict[str, str]) -> pd.DataFrame:
    if holdings_df.empty:
        return pd.DataFrame()
    rows=[]
    for _, row in holdings_df.iterrows():
        ticker=row['ticker']
        if ticker not in data_map:
            continue
        latest = add_indicators(data_map[ticker]).iloc[-1]
        current_price=float(latest['Close'])
        avg=float(row['avg_price'])
        qty=float(row['qty'])
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
            '종목': display_names.get(ticker, row['name'] or ticker),
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
    ordered = ['종목','Ticker','평균단가','현재가','수량','손익률(%)','평균단가 대비(%)','평가손익','시장점수','구조훼손점수','구조훼손판정','익절점수','익절판정','추매점수','추매판정','프로필']
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
        submitted = st.form_submit_button('로그인', use_container_width=True)

    if submitted:
        ok, user_info = verify_login(login_user.strip(), login_password)
        if ok:
            st.session_state['authenticated_user'] = login_user.strip()
            st.session_state['authenticated_role'] = user_info.get('role', 'user')
            st.success(f"{login_user.strip()} 로그인 성공")
            st.rerun()
        else:
            st.error('로그인 실패: 사용자 ID 또는 비밀번호를 확인하세요.')

    st.info('초기 계정은 README에 안내된 기본 계정을 사용한 뒤 users.json에서 변경하세요.')
    return None


def main() -> None:
    st.title('개인 투자 판단 보조기')
    st.caption('관심 종목과 보유 종목을 분리하고, 사용자별 관심 목록과 평균단가 기반 추매 판단을 함께 보는 대시보드')

    active_user = render_login_gate()
    if not active_user:
        return

    with st.sidebar:
        st.header('설정')
        if st.button('로그아웃', use_container_width=True):
            st.session_state.pop('authenticated_user', None)
            st.session_state.pop('authenticated_role', None)
            st.session_state.pop('ticker_text', None)
            st.rerun()

        if st.session_state.get('active_user') != active_user:
            st.session_state['active_user']=active_user
            st.session_state['ticker_text']=', '.join(load_watchlist(active_user))
        elif 'ticker_text' not in st.session_state:
            st.session_state['ticker_text']=', '.join(load_watchlist(active_user))

        st.caption(f'현재 사용자: {active_user}')
        role = st.session_state.get('authenticated_role', 'user')
        st.caption(f'권한: {role}')
        st.text_area('관심 종목 (쉼표로 구분)', key='ticker_text', help='미국: SOXL, QQQ / 한국: 종목명 검색으로 추가하거나 005930.KS 형식으로 직접 입력', height=120)
        c1,c2=st.columns(2)
        with c1:
            st.button('관심종목 저장', use_container_width=True, on_click=persist_current_watchlist, args=(active_user,))
        with c2:
            st.button('초기화', use_container_width=True, on_click=reset_current_watchlist, args=(active_user,))
        if st.session_state.get('watchlist_notice'):
            st.success(st.session_state['watchlist_notice'])
            del st.session_state['watchlist_notice']

        st.markdown('### 국장 종목 검색')
        krx_df=load_krx_lookup()
        search_name=st.text_input('종목명/코드 검색', placeholder='예: 삼성, 하이닉스, 005930')
        with st.expander('최신 KRX 목록 갱신(선택)', expanded=False):
            st.caption('기본값은 전체 KRX CSV입니다. 실패해도 기존 CSV를 계속 사용합니다.')
            if st.button('KRX 목록 업데이트', use_container_width=True):
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
            matched_df['표시'] = matched_df.apply(lambda row: f"{row['name']} | {row['ticker_yf']} | {row['market']}", axis=1)
            selected_option = st.selectbox('검색 결과', options=matched_df['표시'].tolist())
            selected_row = matched_df.loc[matched_df['표시'] == selected_option].iloc[0]
            st.caption(f"선택: {selected_row['name']} ({selected_row['ticker_yf']})")
            st.button('관심 종목에 추가', use_container_width=True, on_click=append_ticker_from_search, args=(selected_row['ticker_yf'],))

        period=st.selectbox('조회 기간', PERIOD_OPTIONS, index=PERIOD_OPTIONS.index(DEFAULT_PERIOD))
        interval=st.selectbox('간격', INTERVAL_OPTIONS, index=INTERVAL_OPTIONS.index(DEFAULT_INTERVAL))
        if st.button('새로고침', type='primary', use_container_width=True):
            load_market_data.clear()

    holdings_df = load_holdings(active_user)
    holdings_tickers = holdings_df['ticker'].tolist() if not holdings_df.empty else []
    watchlist = [ticker.strip().upper() for ticker in st.session_state['ticker_text'].split(',') if ticker.strip()]
    combined = []
    for t in watchlist + holdings_tickers:
        if t not in combined:
            combined.append(t)
    tickers = tuple(combined)
    if not tickers:
        st.warning('최소 1개 이상의 티커를 입력해야 합니다.')
        return

    with st.spinner('시장 데이터를 불러오는 중...'):
        data_map, errors, _ = load_market_data(tickers=tickers, period=period, interval=interval)

    if errors:
        with st.expander('불러오지 못한 종목', expanded=False):
            for ticker, error in errors.items():
                st.write(f'- {ticker}: {error}')
    if not data_map:
        st.error('불러온 데이터가 없습니다. 티커 형식을 다시 확인하세요.')
        return

    krx_df = load_krx_lookup()
    display_names = normalize_display_names(tuple(data_map.keys()), krx_df)
    summary_df = market_summary_rows(data_map, display_names, holdings_df)
    signal_df = build_signal_table(data_map, display_names)
    holdings_view_df = holdings_view(holdings_df, data_map, display_names)

    render_top_metrics(summary_df, len(data_map), len(holdings_df))

    tab1, tab2 = st.tabs(['관심 종목', '보유 종목'])
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
            chart_df = build_chart_frame(data_map[selected_ticker]).reset_index().melt('Date', var_name='구분', value_name='가격')
            chart = alt.Chart(chart_df).mark_line().encode(x='Date:T', y='가격:Q', color='구분:N', tooltip=['Date:T','구분:N', alt.Tooltip('가격:Q', format='.2f')]).properties(height=360)
            st.altair_chart(chart, use_container_width=True)
        with c2:
            score_df = build_score_table(data_map[selected_ticker], selected_ticker)
            st.markdown('#### 항목별 점수 기여도')
            st.altair_chart(build_contribution_chart(score_df), use_container_width=True)
        st.markdown('#### 정량 점수표')
        st.dataframe(score_df, width='stretch', hide_index=True)

    with tab2:
        st.subheader('보유 종목 현황')
        if holdings_df.empty:
            st.info('현재 사용자 보유 종목 파일이 없습니다.')
        else:
            st.caption('보유 종목은 data/holdings/<사용자>.csv 에서 로드된다. 평균단가 대비 괴리, 구조 훼손 경고, 익절 신호를 함께 본다.')
            st.dataframe(style_holdings(holdings_view_df), width='stretch', hide_index=True)
            st.caption('익절판정: 계속보유 / 과열 주의 / 분할익절 검토 / 일부축소 우선')
            if not holdings_view_df.empty:
                st.markdown('#### 추매 후보 보기')
                candidate_df = holdings_view_df[holdings_view_df['추매점수'] >= 2].copy()
                if candidate_df.empty:
                    st.info('현재 기준으로 1차 추매 후보 이상 종목이 없습니다.')
                else:
                    st.dataframe(candidate_df, width='stretch', hide_index=True)

if __name__ == '__main__':
    main()
