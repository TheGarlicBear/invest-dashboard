
CREATE TABLE IF NOT EXISTS cash_balances (
    user_id INTEGER NOT NULL,
    currency VARCHAR(8) NOT NULL,
    balance NUMERIC(20, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, currency)
);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    currency VARCHAR(8) NOT NULL,
    entry_type VARCHAR(32) NOT NULL,
    amount NUMERIC(20, 4) NOT NULL,
    memo TEXT,
    ref_tx_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS tx_tag VARCHAR(32);

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8);

ALTER TABLE holding_transactions
    ADD COLUMN IF NOT EXISTS review_excluded BOOLEAN NOT NULL DEFAULT FALSE;
