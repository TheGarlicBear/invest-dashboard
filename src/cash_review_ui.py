
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.cash_review_store import CashReviewStore
from src.transactions_service import list_transactions


def render_cash_section(active_user: str):
    store = CashReviewStore()
    balances = store.get_cash_balances(active_user)

    st.markdown("### 예수금")
    c1, c2 = st.columns(2)
    c1.metric("KRW 예수금", f"₩{balances.get('KRW', 0):,.0f}")
    c2.metric("USD 예수금", f"${balances.get('USD', 0):,.2f}")

    with st.expander("예수금 수동 조정", expanded=False):
        e1, e2, e3 = st.columns(3)
        with e1:
            krw_balance = st.number_input("KRW 잔액", value=float(balances.get("KRW", 0.0)), step=10000.0)
        with e2:
            usd_balance = st.number_input("USD 잔액", value=float(balances.get("USD", 0.0)), step=100.0)
        with e3:
            st.write("")
            st.write("")
            if st.button("예수금 저장", key="save_cash_balance", width="stretch"):
                store.set_cash_balance(active_user, "KRW", krw_balance, memo="manual_set_krw")
                store.set_cash_balance(active_user, "USD", usd_balance, memo="manual_set_usd")
                st.success("예수금 저장 완료")
                st.rerun()

    with st.expander("예수금 변동 내역", expanded=False):
        ledger_df = store.load_cash_ledger(active_user, limit=100)
        if ledger_df.empty:
            st.info("예수금 변동 내역이 없습니다.")
        else:
            ledger_df = ledger_df.copy()
            def _fmt(row):
                cur = str(row.get("currency", ""))
                amt = float(row.get("amount", 0) or 0)
                return f"₩{amt:,.0f}" if cur == "KRW" else f"${amt:,.2f}"
            ledger_df["금액"] = ledger_df.apply(_fmt, axis=1)
            show_cols = [c for c in ["currency", "entry_type", "금액", "memo", "created_at"] if c in ledger_df.columns]
            st.dataframe(ledger_df[show_cols], width="stretch", hide_index=True)


def render_review_tab(active_user: str):
    st.subheader("매매복기")
    st.caption("20거래일 기준 지연 판정용 탭입니다. 현재는 거래기록 모음부터 시작합니다.")

    tx_rows = list_transactions(active_user, limit=500)
    df = pd.DataFrame(tx_rows)
    exclude_tags = ["테스트", "test", "초기세팅", "수동조정", "분할병합", "보유종목 기록", "보유 종목 기록"]

    if "memo" in df.columns:
        df = df[~df["memo"].astype(str).str.lower().str.contains("|".join(exclude_tags))]

    if df.empty:
        st.info("거래 기록이 없습니다.")
        return

    df = df.copy()
    if "executed_at" in df.columns:
        df["executed_at"] = pd.to_datetime(df["executed_at"], errors="coerce")

    if "realized_pnl" in df.columns:
        df["realized_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce").fillna(0)

    c1, c2, c3 = st.columns(3)
    c1.metric("전체 거래 수", len(df))
    c2.metric("매도 거래 수", int((df["tx_type"] == "SELL").sum()) if "tx_type" in df.columns else 0)
    c3.metric("실현손익 합계", f"{df['realized_pnl'].sum():,.0f}" if "realized_pnl" in df.columns else "0")

    st.dataframe(df, width="stretch", hide_index=True)
