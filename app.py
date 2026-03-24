from __future__ import annotations

from typing import Dict, List, Tuple

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
from src.data_loader import fetch_multiple
from src.evaluator import evaluate_latest, get_profile_for_ticker
from src.holdings_store import load_holdings
from src.indicators import add_indicators
from src.krx_lookup import build_name_map, load_krx_tickers, search_krx_tickers, update_krx_tickers_from_pykrx
from src.watchlist_store import list_watchlist_users, load_watchlist, reset_watchlist, save_watchlist

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
    ordered = ['종목','Ticker','보유','평균단가 대비(%)'] + SUMMARY_COLUMNS[2:]
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
    def color_label(row):
        bg = label_to_color(row['판정'])
        return [f'background-color: {bg}; color: white; font-weight: 700' if col == '판정' else '' for col in df.columns]
    fmt = {col: '{:.2f}' for col in ['평균단가 대비(%)','현재가','RSI14','20일선 대비(%)','60일선 대비(%)','고점 대비(%)','52주 위치(%)','MACD 히스토그램','ATR14(%)','거래량 배수','점수'] if col in df.columns}
    return df.style.apply(color_label, axis=1).format(fmt, na_rep='-')


def style_signal_table(df: pd.DataFrame):
    def color_label(row):
        bg = label_to_color(row['판정'])
        return [f'background-color: {bg}; color: white; font-weight: 700' if col == '판정' else '' for col in df.columns]
    return df.style.apply(color_label, axis=1).format({'총점':'{:.2f}'}, na_rep='-')


def render_top_metrics(summary_df: pd.DataFrame, data_count: int, holdings_count: int) -> None:
    metric_items = [('조회 종목 수', data_count), ('보유 종목 수', holdings_count), ('관심 구간 이상', int((summary_df['점수'] >= 3).sum())), ('분할매수 후보', int((summary_df['판정'] == '1차 분할매수 후보').sum()))]
    cards = [f"<div class='metric-card'><div class='metric-title'>{title}</div><div class='metric-value'>{value}</div></div>" for title, value in metric_items]
    st.markdown(f"<div class='metric-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def render_profile_card(ticker: str, display_name: str) -> None:
    _, profile = get_profile_for_ticker(ticker)
    st.markdown(f"<div class='card'><div class='section-title'>{display_name} <span class='badge'>{profile['label']}</span></div><div style='font-size:0.95rem;color:#cbd5e1'>{profile['description']}</div></div>", unsafe_allow_html=True)


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
    return out.sort_values(by=['추매점수','시장점수'], ascending=[False,False]).reset_index(drop=True)


def main() -> None:
    st.title('개인 투자 판단 보조기')
    st.caption('관심 종목과 보유 종목을 분리하고, 사용자별 관심 목록과 평균단가 기반 추매 판단을 함께 보는 대시보드')

    with st.sidebar:
        st.header('설정')
        default_users=['master','wife']
        available_users=list_watchlist_users(default_users=default_users)
        default_option=st.session_state.get('selected_user_option', available_users[0])
        user_options=available_users + ['새 사용자 추가']
        selected_user_option=st.selectbox('사용자 선택', options=user_options, index=user_options.index(default_option) if default_option in user_options else 0, key='selected_user_option')
        custom_user=''
        if selected_user_option == '새 사용자 추가':
            custom_user=st.text_input('새 사용자 이름', placeholder='예: wife, master2')
        active_user=custom_user.strip() if selected_user_option == '새 사용자 추가' else selected_user_option
        active_user=active_user or available_users[0]

        if st.session_state.get('active_user') != active_user:
            st.session_state['active_user']=active_user
            st.session_state['ticker_text']=', '.join(load_watchlist(active_user))
        elif 'ticker_text' not in st.session_state:
            st.session_state['ticker_text']=', '.join(load_watchlist(active_user))

        st.caption(f'현재 사용자: {active_user}')
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
            st.caption('보유 종목은 data/holdings/<사용자>.csv 에서 로드된다. 평균단가 대비 괴리와 추매점수를 함께 본다.')
            st.dataframe(holdings_view_df.style.format({'평균단가':'{:.2f}','현재가':'{:.2f}','수량':'{:.0f}','손익률(%)':'{:.2f}','평균단가 대비(%)':'{:.2f}','평가손익':'{:.2f}','시장점수':'{:.2f}','추매점수':'{:.0f}'}, na_rep='-'), width='stretch', hide_index=True)
            if not holdings_view_df.empty:
                st.markdown('#### 추매 후보 보기')
                candidate_df = holdings_view_df[holdings_view_df['추매점수'] >= 2].copy()
                if candidate_df.empty:
                    st.info('현재 기준으로 1차 추매 후보 이상 종목이 없습니다.')
                else:
                    st.dataframe(candidate_df, width='stretch', hide_index=True)

if __name__ == '__main__':
    main()
