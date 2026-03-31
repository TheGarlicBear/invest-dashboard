from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_TICKERS
from src.holdings_store import load_holdings as load_holdings_local
from src.watchlist_store import load_watchlist as load_watchlist_local
from src.db_store import load_holdings_from_db, load_watchlist_from_db


def get_watchlist_for_user(active_user: str) -> list[str]:
    if active_user == 'guest' or st.session_state.get('is_guest'):
        guest_text = st.session_state.get('guest_watchlist', ', '.join(DEFAULT_TICKERS))
        return [item.strip().upper() for item in guest_text.split(',') if item.strip()]

    try:
        watchlist_db = load_watchlist_from_db(active_user)
        if watchlist_db is not None:
            return watchlist_db
    except Exception:
        pass

    return load_watchlist_local(active_user)



def bootstrap_user_session(active_user: str) -> None:
    """로그인/Guest 사용자에 맞춰 세션 상태를 안전하게 초기화한다."""
    default_guest = ', '.join(DEFAULT_TICKERS)

    if st.session_state.get('active_user') != active_user:
        st.session_state['active_user'] = active_user
        if active_user == 'guest':
            st.session_state['guest_watchlist'] = st.session_state.get('guest_watchlist', default_guest)
            st.session_state['ticker_text'] = st.session_state['guest_watchlist']
        else:
            st.session_state['ticker_text'] = ', '.join(get_watchlist_for_user(active_user))
        return

    if 'ticker_text' not in st.session_state:
        if active_user == 'guest':
            st.session_state['guest_watchlist'] = st.session_state.get('guest_watchlist', default_guest)
            st.session_state['ticker_text'] = st.session_state['guest_watchlist']
        else:
            st.session_state['ticker_text'] = ', '.join(get_watchlist_for_user(active_user))



def get_holdings_for_user(active_user: str) -> pd.DataFrame:
    if active_user == 'guest' or st.session_state.get('is_guest'):
        return pd.DataFrame(columns=['ticker', 'name', 'avg_price', 'qty', 'profile_name', 'status'])

    try:
        holdings_db = load_holdings_from_db(active_user)
        if holdings_db is not None:
            return holdings_db
    except Exception:
        pass

    return load_holdings_local(active_user)
