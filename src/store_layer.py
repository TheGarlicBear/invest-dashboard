import pandas as pd
from src.db_store import DBStore


def get_store(username):
    # Guest면 session store 쓰도록 나중에 확장 가능
    return DBStore()


# ====== Wrapper functions ======

def load_watchlist(username):
    store = get_store(username)
    return store.load_watchlist(username)


def load_holdings(username):
    store = get_store(username)
    return store.load_holdings(username)


def save_watchlist(username, items):
    store = get_store(username)
    return store.save_watchlist(username, items)


def save_holdings(username, df):
    store = get_store(username)
    return store.save_holdings(username, df)

def bootstrap_user_session(username):
    return None
