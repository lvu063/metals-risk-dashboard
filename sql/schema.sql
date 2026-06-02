-- =============================================================================
-- schema.sql
-- Metals Risk Dashboard — Database Schema
-- Compatible with: PostgreSQL 14+ / SQLite 3.35+
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Reference: Metal master data
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metals (
    symbol          VARCHAR(6)   PRIMARY KEY,
    metal_name      VARCHAR(50)  NOT NULL,
    asset_class     VARCHAR(20)  NOT NULL CHECK (asset_class IN ('Precious', 'Base')),
    unit            VARCHAR(20)  NOT NULL,          -- e.g. 'troy oz', 'MT', 'lbs'
    price_source    VARCHAR(20),                    -- LBMA, LME, CME, etc.
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO metals VALUES ('XAU','Gold',     'Precious','troy oz','LBMA', CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('XAG','Silver',   'Precious','troy oz','LBMA', CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('XPT','Platinum', 'Precious','troy oz','LBMA', CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('XPD','Palladium','Precious','troy oz','LBMA', CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('HG', 'Copper',   'Base',    'lbs',    'LME',  CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('AL', 'Aluminium','Base',    'MT',     'LME',  CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('ZN', 'Zinc',     'Base',    'MT',     'LME',  CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metals VALUES ('NI', 'Nickel',   'Base',    'MT',     'LME',  CURRENT_TIMESTAMP);


-- -----------------------------------------------------------------------------
-- Reference: Trading desks and books
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS books (
    book_id         VARCHAR(20)  PRIMARY KEY,
    desk            VARCHAR(50)  NOT NULL,
    book_type       VARCHAR(20)  CHECK (book_type IN ('Prop','Hedge','Client')),
    trader_lead     VARCHAR(100)
);

INSERT OR IGNORE INTO books VALUES ('PM-PROP-01',  'Precious Metals', 'Prop',   NULL);
INSERT OR IGNORE INTO books VALUES ('PM-HEDGE-01', 'Precious Metals', 'Hedge',  NULL);
INSERT OR IGNORE INTO books VALUES ('PM-CLIENT-01','Precious Metals', 'Client', NULL);
INSERT OR IGNORE INTO books VALUES ('BM-PROP-01',  'Base Metals',     'Prop',   NULL);
INSERT OR IGNORE INTO books VALUES ('BM-HEDGE-01', 'Base Metals',     'Hedge',  NULL);
INSERT OR IGNORE INTO books VALUES ('BM-CLIENT-01','Base Metals',     'Client', NULL);


-- -----------------------------------------------------------------------------
-- Daily market prices (spot)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_history (
    price_id        INTEGER      PRIMARY KEY AUTOINCREMENT,
    price_date      DATE         NOT NULL,
    symbol          VARCHAR(6)   NOT NULL REFERENCES metals(symbol),
    spot_price      NUMERIC(18,6) NOT NULL,
    currency        CHAR(3)      NOT NULL DEFAULT 'USD',
    source          VARCHAR(20),
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (price_date, symbol, currency)
);

CREATE INDEX IF NOT EXISTS idx_price_date_symbol ON price_history (price_date, symbol);


-- -----------------------------------------------------------------------------
-- Trade blotter
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    trade_id        VARCHAR(20)  PRIMARY KEY,
    trade_date      DATE         NOT NULL,
    settlement_date DATE         NOT NULL,
    symbol          VARCHAR(6)   NOT NULL REFERENCES metals(symbol),
    book_id         VARCHAR(20)  NOT NULL REFERENCES books(book_id),
    trader          VARCHAR(100),
    counterparty    VARCHAR(100),
    buy_sell        CHAR(4)      NOT NULL CHECK (buy_sell IN ('Buy','Sell')),
    trade_type      VARCHAR(20)  CHECK (trade_type IN ('Spot','Forward','Option','Swap')),
    quantity        NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    trade_price     NUMERIC(18,6) NOT NULL,
    spot_at_trade   NUMERIC(18,6),
    currency        CHAR(3)      NOT NULL DEFAULT 'USD',
    notional_usd    NUMERIC(18,2),
    status          VARCHAR(20)  DEFAULT 'Confirmed'
                    CHECK (status IN ('Confirmed','Pending','Settled','Cancelled')),
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_date   ON trades (trade_date);
CREATE INDEX IF NOT EXISTS idx_trades_book   ON trades (book_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);


-- -----------------------------------------------------------------------------
-- Net positions (snapshot per book/metal/as-of date)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    position_id     INTEGER      PRIMARY KEY AUTOINCREMENT,
    as_of_date      DATE         NOT NULL,
    book_id         VARCHAR(20)  NOT NULL REFERENCES books(book_id),
    symbol          VARCHAR(6)   NOT NULL REFERENCES metals(symbol),
    net_quantity    NUMERIC(18,4) NOT NULL,
    avg_cost_usd    NUMERIC(18,6),
    total_cost_usd  NUMERIC(18,2),
    long_short      VARCHAR(5)   CHECK (long_short IN ('Long','Short','Flat')),
    UNIQUE (as_of_date, book_id, symbol)
);


-- -----------------------------------------------------------------------------
-- Daily PnL
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pnl_daily (
    pnl_id          INTEGER      PRIMARY KEY AUTOINCREMENT,
    pnl_date        DATE         NOT NULL,
    book_id         VARCHAR(20)  NOT NULL REFERENCES books(book_id),
    symbol          VARCHAR(6)   NOT NULL REFERENCES metals(symbol),
    net_quantity    NUMERIC(18,4),
    spot_price_usd  NUMERIC(18,6),
    mtm_value_usd   NUMERIC(18,2),
    cost_basis_usd  NUMERIC(18,2),
    unrealised_pnl  NUMERIC(18,2),
    pnl_pct         NUMERIC(10,4),
    long_short      VARCHAR(5),
    UNIQUE (pnl_date, book_id, symbol)
);
