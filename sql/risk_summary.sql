-- =============================================================================
-- risk_summary.sql
-- Metals Risk Dashboard — Market Risk & Exposure Queries
--
-- Covers: gross/net exposure, concentration risk, long/short imbalance,
--         settlement ladder, and counterparty exposure
-- =============================================================================


-- =============================================================================
-- 1. GROSS & NET EXPOSURE BY METAL
--    Key risk metric: how much USD notional is at risk per metal
-- =============================================================================
SELECT
    m.asset_class,
    m.metal_name,
    m.symbol,
    ROUND(SUM(CASE WHEN t.buy_sell = 'Buy'  THEN t.notional_usd ELSE 0 END), 2) AS gross_long_usd,
    ROUND(SUM(CASE WHEN t.buy_sell = 'Sell' THEN t.notional_usd ELSE 0 END), 2) AS gross_short_usd,
    ROUND(
        SUM(CASE WHEN t.buy_sell = 'Buy'  THEN  t.notional_usd ELSE 0 END) -
        SUM(CASE WHEN t.buy_sell = 'Sell' THEN  t.notional_usd ELSE 0 END)
    , 2)                                                        AS net_exposure_usd,
    COUNT(*)                                                    AS open_trade_count
FROM trades  t
JOIN metals  m ON t.symbol = m.symbol
WHERE t.status IN ('Confirmed', 'Pending')
GROUP BY m.asset_class, m.metal_name, m.symbol
ORDER BY ABS(net_exposure_usd) DESC;


-- =============================================================================
-- 2. BOOK-LEVEL RISK CONCENTRATION
--    Flags any book exceeding 40% of total portfolio notional
-- =============================================================================
WITH book_notional AS (
    SELECT
        book_id,
        ROUND(SUM(notional_usd), 2) AS book_notional
    FROM trades
    WHERE status IN ('Confirmed', 'Pending')
    GROUP BY book_id
),
total AS (
    SELECT SUM(book_notional) AS total_notional FROM book_notional
)
SELECT
    bn.book_id,
    b.desk,
    b.book_type,
    bn.book_notional,
    t.total_notional,
    ROUND(bn.book_notional / t.total_notional * 100, 2) AS concentration_pct,
    CASE
        WHEN bn.book_notional / t.total_notional > 0.40 THEN '⚠ HIGH'
        WHEN bn.book_notional / t.total_notional > 0.25 THEN '~ MEDIUM'
        ELSE '✓ NORMAL'
    END AS concentration_flag
FROM book_notional bn
CROSS JOIN total t
JOIN books b ON bn.book_id = b.book_id
ORDER BY concentration_pct DESC;


-- =============================================================================
-- 3. SETTLEMENT LADDER
--    How much notional settles each week? Liquidity/ops view
-- =============================================================================
SELECT
    STRFTIME('%Y-%W', settlement_date)  AS settlement_week,
    MIN(settlement_date)                AS week_start,
    MAX(settlement_date)                AS week_end,
    COUNT(*)                            AS trades_settling,
    COUNT(DISTINCT symbol)              AS metals,
    ROUND(SUM(CASE WHEN buy_sell = 'Buy'  THEN notional_usd ELSE 0 END), 2) AS cash_out_usd,
    ROUND(SUM(CASE WHEN buy_sell = 'Sell' THEN notional_usd ELSE 0 END), 2) AS cash_in_usd,
    ROUND(
        SUM(CASE WHEN buy_sell = 'Sell' THEN notional_usd ELSE 0 END) -
        SUM(CASE WHEN buy_sell = 'Buy'  THEN notional_usd ELSE 0 END)
    , 2)                                AS net_cash_flow_usd
FROM trades
WHERE status IN ('Confirmed', 'Pending')
  AND settlement_date >= DATE('now')
GROUP BY settlement_week
ORDER BY settlement_week;


-- =============================================================================
-- 4. COUNTERPARTY EXPOSURE
--    Credit risk: total open notional per counterparty
-- =============================================================================
SELECT
    counterparty,
    COUNT(*)                                                AS open_trades,
    COUNT(DISTINCT symbol)                                  AS metals,
    COUNT(DISTINCT book_id)                                 AS books,
    ROUND(SUM(notional_usd), 2)                             AS gross_exposure_usd,
    ROUND(
        SUM(CASE WHEN buy_sell = 'Buy'  THEN  notional_usd ELSE 0 END) -
        SUM(CASE WHEN buy_sell = 'Sell' THEN  notional_usd ELSE 0 END)
    , 2)                                                    AS net_exposure_usd,
    ROUND(AVG(notional_usd), 2)                             AS avg_trade_size,
    MAX(notional_usd)                                       AS largest_single_trade
FROM trades
WHERE status IN ('Confirmed', 'Pending')
GROUP BY counterparty
ORDER BY gross_exposure_usd DESC;


-- =============================================================================
-- 5. LONG/SHORT IMBALANCE MONITOR
--    Are we running dangerously one-sided on any metal?
-- =============================================================================
WITH ls AS (
    SELECT
        symbol,
        ROUND(SUM(CASE WHEN buy_sell = 'Buy'  THEN quantity ELSE 0 END), 4) AS total_long_qty,
        ROUND(SUM(CASE WHEN buy_sell = 'Sell' THEN quantity ELSE 0 END), 4) AS total_short_qty
    FROM trades
    WHERE status IN ('Confirmed','Pending','Settled')
    GROUP BY symbol
)
SELECT
    ls.symbol,
    m.metal_name,
    m.asset_class,
    m.unit,
    ls.total_long_qty,
    ls.total_short_qty,
    ROUND(ls.total_long_qty - ls.total_short_qty, 4) AS net_qty,
    CASE
        WHEN ls.total_long_qty = 0 AND ls.total_short_qty = 0 THEN NULL
        ELSE ROUND(
            ABS(ls.total_long_qty - ls.total_short_qty) /
            NULLIF((ls.total_long_qty + ls.total_short_qty), 0) * 100
        , 2)
    END AS imbalance_pct,
    CASE
        WHEN ABS(ls.total_long_qty - ls.total_short_qty) /
             NULLIF((ls.total_long_qty + ls.total_short_qty), 0) > 0.5
             THEN '⚠ IMBALANCED'
        ELSE '✓ BALANCED'
    END AS balance_flag
FROM ls
JOIN metals m ON ls.symbol = m.symbol
ORDER BY imbalance_pct DESC;


-- =============================================================================
-- 6. PRICE VOLATILITY — Rolling 30-day realised vol per metal
--    Used in risk reporting and curve building inputs
-- =============================================================================
WITH daily_returns AS (
    SELECT
        symbol,
        price_date,
        spot_price,
        LAG(spot_price) OVER (PARTITION BY symbol ORDER BY price_date) AS prev_price
    FROM price_history
),
log_returns AS (
    SELECT
        symbol,
        price_date,
        CASE WHEN prev_price > 0
             THEN LN(spot_price / prev_price)
             ELSE NULL
        END AS log_return
    FROM daily_returns
    WHERE prev_price IS NOT NULL
)
SELECT
    lr.symbol,
    m.metal_name,
    m.asset_class,
    lr.price_date,
    -- Annualised volatility proxy (stddev of last 30 days * sqrt(252))
    ROUND(
        SQRT(
            AVG(lr.log_return * lr.log_return) OVER w -
            AVG(lr.log_return) OVER w * AVG(lr.log_return) OVER w
        ) * SQRT(252) * 100
    , 4)                                    AS annualised_vol_pct
FROM log_returns lr
JOIN metals      m ON lr.symbol = m.symbol
WINDOW w AS (
    PARTITION BY lr.symbol
    ORDER BY lr.price_date
    ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
)
ORDER BY lr.symbol, lr.price_date DESC;
