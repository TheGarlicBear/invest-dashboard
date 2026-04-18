-- trading_review_schema_v1.sql
CREATE TABLE IF NOT EXISTS cash_balances (
    user_id INTEGER NOT NULL,
    currency VARCHAR(8) NOT NULL,
    balance NUMERIC(20,4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, currency)
);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    currency VARCHAR(8) NOT NULL,
    entry_type VARCHAR(32) NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    memo TEXT,
    ref_tx_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_review_snapshots (
    id BIGSERIAL PRIMARY KEY,
    tx_id BIGINT NOT NULL,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    tx_type VARCHAR(8) NOT NULL,
    tx_tag VARCHAR(32),
    currency VARCHAR(8),
    review_excluded BOOLEAN NOT NULL DEFAULT FALSE,
    profile_key VARCHAR(64),
    attractiveness_score INTEGER,
    market_score NUMERIC(10,2),
    add_score NUMERIC(10,2),
    structure_score NUMERIC(10,2),
    profit_score NUMERIC(10,2),
    structure_label VARCHAR(32),
    profit_label VARCHAR(32),
    action_label VARCHAR(32),
    rsi14 NUMERIC(10,4),
    ma20_diff_pct NUMERIC(10,4),
    ma60_diff_pct NUMERIC(10,4),
    ma120_diff_pct NUMERIC(10,4),
    ma200_diff_pct NUMERIC(10,4),
    drawdown_pct NUMERIC(10,4),
    position52w NUMERIC(10,4),
    volume_ratio NUMERIC(10,4),
    entry_price NUMERIC(20,4) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    realized_pnl NUMERIC(20,4),
    review_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    review_label VARCHAR(32),
    review_score NUMERIC(10,2),
    review_reason TEXT,
    price_d5 NUMERIC(20,4),
    price_d20 NUMERIC(20,4),
    price_d60 NUMERIC(20,4),
    max_price_d20 NUMERIC(20,4),
    min_price_d20 NUMERIC(20,4),
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS position_review_campaigns (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    campaign_key VARCHAR(128) NOT NULL,
    started_at TIMESTAMP,
    closed_at TIMESTAMP,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    currency VARCHAR(8),
    entry_count INTEGER NOT NULL DEFAULT 0,
    exit_count INTEGER NOT NULL DEFAULT 0,
    avg_entry_price NUMERIC(20,4),
    avg_exit_price NUMERIC(20,4),
    final_realized_pnl NUMERIC(20,4),
    review_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    review_label VARCHAR(32),
    review_score NUMERIC(10,2),
    review_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE(user_id, campaign_key)
);

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS tx_tag VARCHAR(32);

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8);

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS review_excluded BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS campaign_key VARCHAR(128);
