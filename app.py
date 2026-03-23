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
    PROFILE_RULES,
    SUMMARY_COLUMNS,
)
from src.data_loader import fetch_multiple
from src.evaluator import evaluate_latest, get_profile_for_ticker
from src.indicators import add_indicators
from src.krx_lookup import build_name_map, get_display_name_for_ticker, load_krx_tickers, search_krx_tickers, update_krx_tickers_from_pykrx
from src.watchlist_store import list_watchlist_users, load_watchlist, reset_watchlist, save_watchlist

st.set_page_config(page_title="개인 투자 판단 보조기", layout="wide")

CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1520px;}
.metric-grid {display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 10px 0 22px 0;}
.metric-card {
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
  color: #ffffff;
  border-radius: 18px;
  padding: 18px 22px;
  border: 1px solid rgba(255,255,255,0.12);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.18);
  min-height: 120px;
}
.metric-title {font-size: 1rem; font-weight: 700; color: rgba(255,255,255,0.92); margin-bottom: 14px;}
.metric-value {font-size: 3rem; font-weight: 800; line-height: 1.05; color: #ffffff;}
.metric-label {font-size: 0.82rem; color: #cbd5e1; margin-bottom: 0.2rem;}
.card {
  background: #0f172a;
  color: #f8fafc;
  border-radius: 18px;
  padding: 1rem 1.1rem;
  border: 1px solid rgba(148,163,184,0.18);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.10);
}
.section-title {font-size: 1.05rem; font-weight: 700; margin-bottom: 0.65rem;}
.badge {
  display:inline-block; padding:0.22rem 0.55rem; border-radius:999px;
  font-size:0.78rem; font-weight:600; background:#1d4ed8; color:white;
}
.small-note {font-size: 0.82rem; color: #64748b;}
@media (max-width: 980px) {
  .metric-grid {grid-template-columns: 1fr 1fr;}
}
@media (max-width: 640px) {
  .metric-grid {grid-template-columns: 1fr;}
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=60 * 30)
def load_market_data(
    tickers: Tuple[str, ...], period: str, interval: str
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str], Dict[str, str]]:
    return fetch_multiple(tickers=tickers, period=period, interval=interval)




@st.cache_data(ttl=60 * 60)
def load_krx_lookup() -> pd.DataFrame:
    return load_krx_tickers()


def _safe_round(value: object, digits: int = 2):
    if pd.isna(value):
        return None
    return round(float(value), digits)


def label_to_color(label: str) -> str:
    return {
        "1차 분할매수 후보": "#16a34a",
        "관심 구간": "#2563eb",
        "중립·관망": "#f59e0b",
        "리스크 주의": "#dc2626",
    }.get(label, "#64748b")


def state_badge(state: str) -> str:
    mapping = {
        "좋음": "🟢 좋음",
        "양호": "🔵 양호",
        "보통": "🟡 보통",
        "주의": "🟠 주의",
        "위험": "🔴 위험",
    }
    return mapping.get(state, state)


def score_to_signal(value: float) -> str:
    if value >= 2:
        return "좋음"
    if value >= 1:
        return "양호"
    if value >= 0:
        return "보통"
    if value >= -1:
        return "주의"
    return "위험"


def format_value(value: object, digits: int = 2) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def build_summary_table(data_map: Dict[str, pd.DataFrame], display_names: Dict[str, str]) -> pd.DataFrame:
    rows: List[dict] = []

    for ticker, raw_df in data_map.items():
        enriched = add_indicators(raw_df)
        latest = enriched.iloc[-1]
        evaluation = evaluate_latest(latest.to_dict(), ticker)

        rows.append(
            {
                "종목": display_names.get(ticker, ticker),
                "Ticker": ticker,
                "프로필": evaluation.profile_label,
                "현재가": _safe_round(latest["Close"], 2),
                "RSI14": _safe_round(latest["RSI14"], 2),
                "20일선 대비(%)": _safe_round(latest["MA20DiffPct"], 2),
                "60일선 대비(%)": _safe_round(latest["MA60DiffPct"], 2),
                "고점 대비(%)": _safe_round(latest["DrawdownPct"], 2),
                "52주 위치(%)": _safe_round(latest["Position52W"], 2),
                "MACD 히스토그램": _safe_round(latest["MACDHist"], 2),
                "ATR14(%)": _safe_round(latest["ATR14Pct"], 2),
                "거래량 배수": _safe_round(latest["VolumeRatio"], 2),
                "판정": evaluation.label,
                "점수": _safe_round(evaluation.score, 2),
                "코멘트": evaluation.comment,
                "판정색": label_to_color(evaluation.label),
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result[SUMMARY_COLUMNS + ["판정색"]]
    return result.sort_values(by=["점수", "RSI14"], ascending=[False, True]).reset_index(drop=True)


def build_signal_table(data_map: Dict[str, pd.DataFrame], display_names: Dict[str, str]) -> pd.DataFrame:
    rows: List[dict] = []
    for ticker, raw_df in data_map.items():
        latest = add_indicators(raw_df).iloc[-1]
        evaluation = evaluate_latest(latest.to_dict(), ticker)
        detail = {row["항목"]: row["점수"] for row in evaluation.breakdown}
        trend_score = detail.get("20일선 대비", 0) + detail.get("60일선 대비", 0)
        rows.append(
            {
                "종목": display_names.get(ticker, ticker),
                "총점": _safe_round(evaluation.score, 2),
                "RSI": state_badge(score_to_signal(detail.get("RSI14", 0))),
                "낙폭": state_badge(score_to_signal(detail.get("고점 대비 낙폭", 0))),
                "추세": state_badge(score_to_signal(trend_score)),
                "MACD": state_badge(score_to_signal(detail.get("MACD 히스토그램", 0))),
                "변동성": state_badge(score_to_signal(detail.get("ATR14 변동성", 0))),
                "판정": evaluation.label,
                "판정색": label_to_color(evaluation.label),
                "핵심 코멘트": evaluation.comment,
            }
        )
    signal_df = pd.DataFrame(rows)
    return signal_df.sort_values(by="총점", ascending=False).reset_index(drop=True)


def build_chart_frame(df: pd.DataFrame) -> pd.DataFrame:
    enriched = add_indicators(df)
    chart_df = enriched[["Date", "Close", "MA20", "MA60"]].set_index("Date").dropna(how="all")
    return chart_df.round(2)


def build_score_table(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    latest = add_indicators(df).iloc[-1]
    evaluation = evaluate_latest(latest.to_dict(), ticker)
    score_df = pd.DataFrame(evaluation.breakdown)
    numeric_cols = ["원점수", "가중치", "점수"]
    for col in numeric_cols:
        if col in score_df.columns:
            score_df[col] = pd.to_numeric(score_df[col], errors="coerce").round(2)
    return score_df


def build_contribution_chart(score_df: pd.DataFrame) -> alt.Chart:
    chart_df = score_df.copy()
    chart_df["색상"] = chart_df["점수"].apply(lambda x: "가점" if x > 0 else ("감점" if x < 0 else "중립"))
    color_scale = alt.Scale(domain=["가점", "중립", "감점"], range=["#16a34a", "#94a3b8", "#dc2626"])

    return (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("점수:Q", title="가중 반영 점수"),
            y=alt.Y("항목:N", sort="-x", title=None),
            color=alt.Color("색상:N", scale=color_scale, legend=None),
            tooltip=[
                "항목",
                alt.Tooltip("원점수:Q", format=".2f"),
                alt.Tooltip("가중치:Q", format=".2f"),
                alt.Tooltip("점수:Q", format=".2f"),
                "값",
                "설명",
            ],
        )
        .properties(height=320)
    )


def build_weight_chart(ticker: str) -> alt.Chart:
    _, profile = get_profile_for_ticker(ticker)
    weight_df = pd.DataFrame(
        {"항목": list(profile["weights"].keys()), "가중치": list(profile["weights"].values())}
    )
    weight_df["가중치"] = weight_df["가중치"].round(2)
    return (
        alt.Chart(weight_df)
        .mark_bar(color="#2563eb", cornerRadiusEnd=4)
        .encode(
            x=alt.X("가중치:Q", title="가중치"),
            y=alt.Y("항목:N", sort="-x", title=None),
            tooltip=["항목", alt.Tooltip("가중치:Q", format=".2f")],
        )
        .properties(height=320)
    )


def style_summary(df: pd.DataFrame):
    display_df = df.drop(columns=["판정색"], errors="ignore").copy()

    def color_label(row):
        bg = label_to_color(row["판정"])
        return [
            f"background-color: {bg}; color: white; font-weight: 700" if col == "판정" else ""
            for col in display_df.columns
        ]

    return display_df.style.apply(color_label, axis=1).format(
        {
            "현재가": "{:.2f}",
            "RSI14": "{:.2f}",
            "20일선 대비(%)": "{:.2f}",
            "60일선 대비(%)": "{:.2f}",
            "고점 대비(%)": "{:.2f}",
            "52주 위치(%)": "{:.2f}",
            "MACD 히스토그램": "{:.2f}",
            "ATR14(%)": "{:.2f}",
            "거래량 배수": "{:.2f}",
            "점수": "{:.2f}",
        },
        na_rep="-",
    )


def style_signal_table(df: pd.DataFrame):
    display_df = df.drop(columns=["판정색"], errors="ignore").copy()

    def color_label(row):
        bg = label_to_color(row["판정"])
        return [
            f"background-color: {bg}; color: white; font-weight: 700" if col == "판정" else ""
            for col in display_df.columns
        ]

    return display_df.style.apply(color_label, axis=1).format({"총점": "{:.2f}"}, na_rep="-")


def render_top_metrics(summary_df: pd.DataFrame, data_count: int) -> None:
    metric_items = [
        ("조회 종목 수", data_count),
        ("관심 구간 이상", int((summary_df["점수"] >= 3).sum())),
        ("분할매수 후보", int((summary_df["판정"] == "1차 분할매수 후보").sum())),
        ("리스크 주의", int((summary_df["판정"] == "리스크 주의").sum())),
    ]
    cards = []
    for title, value in metric_items:
        cards.append(f"<div class='metric-card'><div class='metric-title'>{title}</div><div class='metric-value'>{value}</div></div>")
    st.markdown(f"<div class='metric-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def render_profile_card(ticker: str, display_name: str) -> None:
    _, profile = get_profile_for_ticker(ticker)
    st.markdown(
        f"""
        <div class='card'>
          <div class='section-title'>{display_name} <span class='badge'>{profile['label']}</span></div>
          <div style='font-size:0.95rem;color:#cbd5e1'>{profile['description']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def add_ticker_to_input(ticker_text: str, ticker_to_add: str) -> str:
    current = [item.strip().upper() for item in ticker_text.split(",") if item.strip()]
    if ticker_to_add.upper() not in current:
        current.append(ticker_to_add.upper())
    return ", ".join(current)


def append_ticker_from_search(ticker_to_add: str) -> None:
    current_text = st.session_state.get("ticker_text", "")
    st.session_state["ticker_text"] = add_ticker_to_input(current_text, ticker_to_add)



def normalize_display_names(display_names: Dict[str, str], tickers: Tuple[str, ...], krx_df: pd.DataFrame) -> Dict[str, str]:
    name_map = build_name_map(krx_df)
    normalized = {}
    for ticker in tickers:
        current = display_names.get(ticker, ticker)
        normalized[ticker] = name_map.get(str(ticker).upper(), current)
    return normalized


def persist_current_watchlist(user_id: str) -> None:
    current_text = st.session_state.get("ticker_text", "")
    save_watchlist(user_id=user_id, tickers=current_text)
    st.session_state["watchlist_notice"] = f"{user_id} 관심종목을 저장했습니다."


def reset_current_watchlist(user_id: str) -> None:
    reset_watchlist(user_id=user_id)
    default_items = load_watchlist(user_id=user_id)
    st.session_state["ticker_text"] = ", ".join(default_items)
    st.session_state["watchlist_notice"] = f"{user_id} 관심종목을 기본값으로 초기화했습니다."


def main() -> None:
    st.title("개인 투자 판단 보조기")
    st.caption("종목별 프로필을 반영해 점수를 계산하고, 전체 KRX CSV 검색과 사용자별 관심종목 저장 기능을 포함한 개인용 대시보드")

    with st.sidebar:
        st.header("설정")
        default_users = ["master", "wife"]
        available_users = list_watchlist_users(default_users=default_users)
        default_option = st.session_state.get("selected_user_option", available_users[0])
        user_options = available_users + ["새 사용자 추가"]
        selected_user_option = st.selectbox(
            "사용자 선택",
            options=user_options,
            index=user_options.index(default_option) if default_option in user_options else 0,
            key="selected_user_option",
        )
        custom_user = ""
        if selected_user_option == "새 사용자 추가":
            custom_user = st.text_input("새 사용자 이름", placeholder="예: wife, master2")
        active_user = custom_user.strip() if selected_user_option == "새 사용자 추가" else selected_user_option
        active_user = active_user or available_users[0]

        if st.session_state.get("active_user") != active_user:
            st.session_state["active_user"] = active_user
            st.session_state["ticker_text"] = ", ".join(load_watchlist(active_user))
        elif "ticker_text" not in st.session_state:
            st.session_state["ticker_text"] = ", ".join(load_watchlist(active_user))

        st.caption(f"현재 사용자: {active_user}")
        st.text_area(
            "관심 종목 (쉼표로 구분)",
            key="ticker_text",
            help="미국: SOXL, QQQ / 한국: 종목명 검색으로 추가하거나 005930.KS 형식으로 직접 입력",
            height=120,
        )

        button_col1, button_col2 = st.columns(2)
        with button_col1:
            st.button(
                "관심종목 저장",
                use_container_width=True,
                on_click=persist_current_watchlist,
                args=(active_user,),
            )
        with button_col2:
            st.button(
                "초기화",
                use_container_width=True,
                on_click=reset_current_watchlist,
                args=(active_user,),
            )
        if st.session_state.get("watchlist_notice"):
            st.success(st.session_state["watchlist_notice"])
            del st.session_state["watchlist_notice"]

        st.markdown("### 국장 종목 검색")
        krx_df = load_krx_lookup()
        search_name = st.text_input("종목명/코드 검색", placeholder="예: 삼성, 하이닉스, 005930")
        with st.expander("최신 KRX 목록 갱신(선택)", expanded=False):
            st.caption("기본값은 전체 KRX CSV입니다. 이 버튼은 선택 기능이며, 실패해도 기존 CSV를 계속 사용합니다.")
            if st.button("KRX 목록 업데이트", use_container_width=True):
                ok, message, refreshed_df = update_krx_tickers_from_pykrx()
                if ok:
                    load_krx_lookup.clear()
                    krx_df = refreshed_df if refreshed_df is not None else load_krx_lookup()
                    st.success(message)
                else:
                    st.warning(message)

        matched_df = search_krx_tickers(search_name, krx_df, limit=30)
        if matched_df.empty:
            st.caption("검색 결과 없음")
        else:
            matched_df = matched_df.copy()
            matched_df["표시"] = matched_df.apply(
                lambda row: f"{row['name']} | {row['ticker_yf']} | {row['market']}", axis=1
            )
            selected_option = st.selectbox("검색 결과", options=matched_df["표시"].tolist())
            selected_row = matched_df.loc[matched_df["표시"] == selected_option].iloc[0]
            st.caption(f"선택: {selected_row['name']} ({selected_row['ticker_yf']})")
            st.button(
                "관심 종목에 추가",
                use_container_width=True,
                on_click=append_ticker_from_search,
                args=(selected_row["ticker_yf"],),
            )

        with st.expander("검색 결과 미리보기", expanded=False):
            preview_cols = ["name", "ticker_yf", "market"]
            st.dataframe(matched_df[preview_cols] if not matched_df.empty else matched_df, hide_index=True, width="stretch")

        period = st.selectbox("조회 기간", PERIOD_OPTIONS, index=PERIOD_OPTIONS.index(DEFAULT_PERIOD))
        interval = st.selectbox("간격", INTERVAL_OPTIONS, index=INTERVAL_OPTIONS.index(DEFAULT_INTERVAL))
        st.caption("프로필 기준: 레버리지 / 성장주 / 배당형 / 국내 반도체 / 기본형")
        run_button = st.button("새로고침", type="primary", use_container_width=True)

    tickers = tuple([ticker.strip().upper() for ticker in st.session_state["ticker_text"].split(",") if ticker.strip()])
    if not tickers:
        st.warning("최소 1개 이상의 티커를 입력해야 합니다.")
        return

    if run_button:
        load_market_data.clear()

    with st.spinner("시장 데이터를 불러오는 중..."):
        data_map, errors, display_names = load_market_data(tickers=tickers, period=period, interval=interval)

    krx_df = load_krx_lookup()
    display_names = normalize_display_names(display_names, tickers, krx_df)

    if errors:
        with st.expander("불러오지 못한 종목", expanded=False):
            for ticker, error in errors.items():
                st.write(f"- {ticker}: {error}")

    if not data_map:
        st.error("불러온 데이터가 없습니다. 티커 형식을 다시 확인하세요.")
        return

    summary_df = build_summary_table(data_map, display_names)
    signal_df = build_signal_table(data_map, display_names)

    render_top_metrics(summary_df, len(data_map))

    st.subheader("종합 상태판")
    st.dataframe(style_summary(summary_df), width="stretch", hide_index=True)

    st.subheader("신호등형 요약표")
    st.caption("히트맵 대신 주요 항목을 상태 배지로 보여주도록 바꿨다.")
    st.dataframe(style_signal_table(signal_df), width="stretch", hide_index=True)

    st.subheader("개별 종목 보기")
    select_options = {f"{display_names[ticker]} ({ticker})": ticker for ticker in data_map.keys()}
    selected_display = st.selectbox(
        "차트 확인 종목",
        options=list(select_options.keys()),
    )
    selected_ticker = select_options[selected_display]
    selected_raw = data_map[selected_ticker]
    selected_enriched = add_indicators(selected_raw)
    selected_latest = selected_enriched.iloc[-1]
    selected_eval = evaluate_latest(selected_latest.to_dict(), selected_ticker)

    selected_name = display_names.get(selected_ticker, selected_ticker)
    render_profile_card(selected_ticker, selected_name)

    info_left, info_mid, info_right = st.columns([1.3, 1, 1])
    with info_left:
        chart_df = build_chart_frame(selected_raw)
        st.line_chart(chart_df, height=340)
    with info_mid:
        st.markdown(
            f"""
            <div class='card'>
              <div class='section-title'>현재 판정</div>
              <div style='font-size:1.5rem;font-weight:800;color:{label_to_color(selected_eval.label)}'>{selected_eval.label}</div>
              <div style='margin-top:0.5rem;font-size:1.0rem'>총점 <b>{selected_eval.score:.2f}</b> / 원점수 <b>{selected_eval.total_raw_score:.2f}</b></div>
              <div style='margin-top:0.7rem;color:#cbd5e1'>{selected_eval.comment}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with info_right:
        metric_fields = [
            ("현재가", selected_latest.get("Close"), ".2f", ""),
            ("RSI14", selected_latest.get("RSI14"), ".2f", ""),
            ("고점 대비", selected_latest.get("DrawdownPct"), ".2f", "%"),
            ("52주 위치", selected_latest.get("Position52W"), ".2f", "%"),
            ("ATR14", selected_latest.get("ATR14Pct"), ".2f", "%"),
            ("거래량 배수", selected_latest.get("VolumeRatio"), ".2f", "x"),
        ]
        st.markdown("<div class='card'><div class='section-title'>핵심 수치</div>", unsafe_allow_html=True)
        for label, value, fmt, suffix in metric_fields:
            if pd.notna(value):
                st.markdown(
                    f"<div class='metric-label'>{label}</div><div style='font-size:1.15rem;font-weight:700;margin-bottom:0.55rem'>{value:{fmt}}{suffix}</div>",
                    unsafe_allow_html=True,
                )
        st.markdown("</div>", unsafe_allow_html=True)

    left, right = st.columns(2)
    score_df = build_score_table(selected_raw, selected_ticker)
    with left:
        st.markdown("#### 항목별 점수 기여도")
        st.altair_chart(build_contribution_chart(score_df), width="stretch")
    with right:
        st.markdown("#### 종목 프로필 가중치")
        st.altair_chart(build_weight_chart(selected_ticker), width="stretch")

    st.subheader("정량 점수표")
    ordered_columns = ["항목", "원점수", "가중치", "점수", "값", "설명"]
    score_display_df = score_df[ordered_columns].copy()
    for col in ["원점수", "가중치", "점수"]:
        if col in score_display_df.columns:
            score_display_df[col] = pd.to_numeric(score_display_df[col], errors="coerce").round(2)
    st.dataframe(score_display_df, width="stretch", hide_index=True)

    with st.expander("지원 중인 프로필 규칙 보기"):
        profile_rows = []
        for rule in PROFILE_RULES.values():
            profile_rows.append(
                {
                    "프로필": rule["label"],
                    "설명": rule["description"],
                    "예시 티커": ", ".join(rule["keywords"]) if rule["keywords"] else "기타 전체",
                }
            )
        st.dataframe(pd.DataFrame(profile_rows), width="stretch", hide_index=True)

    with st.expander("최근 15개 행 데이터 보기"):
        preview_columns = [
            "Date",
            "Close",
            "Volume",
            "MA20",
            "MA60",
            "RSI14",
            "MACD",
            "MACDSignal",
            "MACDHist",
            "ATR14Pct",
            "Position52W",
            "VolumeRatio",
            "DrawdownPct",
            "MA20DiffPct",
            "MA60DiffPct",
        ]
        preview_df = selected_enriched[preview_columns].tail(15).copy()
        numeric_cols = preview_df.select_dtypes(include="number").columns
        preview_df[numeric_cols] = preview_df[numeric_cols].round(2)
        st.dataframe(preview_df, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
