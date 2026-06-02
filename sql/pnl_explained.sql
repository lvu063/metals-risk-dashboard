-- =============================================================================
-- pnl_explained.sql
-- Metals Risk Dashboard — PnL Explained Queries
--
-- "PnL Explained" breaks down daily profit/loss into its components:
--   Price Effect   — change in spot price (delta PnL)
--   Position Effect — change in net position size (new trades)
--   FX Effect      — currency moves (placeholder; all USD here)
--
-- Run against SQLite after loading CSVs via etl_pipeline.py
-- =============================================================================


-- =============================================================================
-- 1. DAILY PNL BY BOOK AND METAL
--    Simple unrealised PnL for each book/metal as of the latest date
-- =============================================================================
SELECT
    p.pnl_date,
    b.desk,
    p.book_id,
    m.metal_name,
    m.asset_class,
    p.net_quantity,
    m.unit,
    p.spot_price_usd,
    p.cost_basis_usd,
    p.mtm_value_usd,
    p.unrealised_pnl,
    p.pnl_pct,
    p.long_short,
    CASE
        WHEN p.unrealised_pnl > 0 THEN 'Gain'
        WHEN p.unrealised_pnl < 0 THEN 'Loss'
        ELSE 'Flat'
    END AS pnl_direction
FROM pnl_daily p
JOIN books  b ON p.book_id = b.book_id
JOIN metals m ON p.symbol  = m.symbol
WHERE p.pnl_date = (SELECT MAX(pnl_date) FROM pnl_daily)
ORDER BY ABS(p.unrealised_pnl) DESC;


-- =============================================================================
-- 2. PNL EXPLAINED — PRICE EFFECT vs POSITION EFFECT (day-over-day)
--    Compares today vs yesterday to isolate what drove the move
-- =============================================================================
WITH today AS (
    SELECT *
    FROM pnl_daily
    WHERE pnl_date = (SELECT MAX(pnl_date) FROM pnl_daily)
),
yesterday AS (
    SELECT *
    FROM pnl_daily
    WHERE pnl_date = (
        SELECT MAX(pnl_date) FROM pnl_daily
        WHERE pnl_date < (SELECT MAX(pnl_date) FROM pnl_daily)
    )
)
SELECT
    t.book_id,
    t.symbol,
    t.pnl_date                                              AS today_date,
    y.pnl_date                                              AS prev_date,

    -- Price effect: same position, new price
    ROUND((t.spot_price_usd - y.spot_price_usd)
          * y.net_quantity, 2)                              AS price_effect_usd,

    -- Position effect: new quantity at today's price
    ROUND((t.net_quantity - y.net_quantity)
          * t.spot_price_usd, 2)                           AS position_effect_usd,

    -- Total day PnL
    ROUND(t.unrealised_pnl - y.unrealised_pnl, 2)          AS total_day_pnl,

    t.spot_price_usd                                        AS spot_today,
    y.spot_price_usd                                        AS spot_prev,
    ROUND((t.spot_price_usd / y.spot_price_usd - 1) * 100, 4) AS spot_move_pct

FROM today t
JOIN yesterday y
  ON t.book_id = y.book_id
 AND t.symbol  = y.symbol
ORDER BY ABS(t.unrealised_pnl - y.unrealised_pnl) DESC;


-- =============================================================================
-- 3. DESK-LEVEL PNL ROLLUP
--    Senior management view: total PnL by desk
-- =============================================================================
SELECT
    b.desk,
    COUNT(DISTINCT p.book_id)               AS books_count,
    COUNT(DISTINCT p.symbol)                AS metals_traded,
    ROUND(SUM(p.mtm_value_usd), 2)          AS total_mtm_usd,
    ROUND(SUM(p.cost_basis_usd), 2)         AS total_cost_usd,
    ROUND(SUM(p.unrealised_pnl), 2)         AS total_unrealised_pnl,
    ROUND(
        SUM(p.unrealised_pnl) /
        NULLIF(ABS(SUM(p.cost_basis_usd)), 0) * 100
    , 4)                                    AS pnl_pct_overall,
    SUM(CASE WHEN p.unrealised_pnl > 0 THEN 1 ELSE 0 END) AS winning_positions,
    SUM(CASE WHEN p.unrealised_pnl < 0 THEN 1 ELSE 0 END) AS losing_positions
FROM pnl_daily  p
JOIN books      b ON p.book_id = b.book_id
WHERE p.pnl_date = (SELECT MAX(pnl_date) FROM pnl_daily)
GROUP BY b.desk
ORDER BY total_unrealised_pnl DESC;


-- =============================================================================
-- 4. METAL-LEVEL PNL CONTRIBUTION
--    Which metals are driving gains/losses across all books?
-- =============================================================================
SELECT
    m.asset_class,
    m.metal_name,
    p.symbol,
    ROUND(SUM(p.net_quantity), 2)           AS total_net_qty,
    m.unit,
    ROUND(AVG(p.spot_price_usd), 4)         AS avg_spot_usd,
    ROUND(SUM(p.mtm_value_usd), 2)          AS total_mtm_usd,
    ROUND(SUM(p.unrealised_pnl), 2)         AS total_pnl,
    ROUND(
        SUM(p.unrealised_pnl) /
        NULLIF(ABS(SUM(p.cost_basis_usd)), 0) * 100
    , 4)                                    AS pnl_pct,
    SUM(CASE WHEN p.long_short = 'Long'  THEN 1 ELSE 0 END) AS long_books,
    SUM(CASE WHEN p.long_short = 'Short' THEN 1 ELSE 0 END) AS short_books
FROM pnl_daily  p
JOIN metals     m ON p.symbol = m.symbol
WHERE p.pnl_date = (SELECT MAX(pnl_date) FROM pnl_daily)
GROUP BY m.asset_class, m.metal_name, p.symbol
ORDER BY ABS(total_pnl) DESC;


-- =============================================================================
-- 5. TRADE ACTIVITY SUMMARY — Blotter analytics
--    Volume, count, and avg size per metal per month
-- =============================================================================
SELECT
    STRFTIME('%Y-%m', t.trade_date)         AS trade_month,
    m.asset_class,
    m.metal_name,
    t.buy_sell,
    t.trade_type,
    COUNT(*)                                AS trade_count,
    ROUND(SUM(t.quantity), 2)               AS total_qty,
    ROUND(AVG(t.quantity), 2)               AS avg_qty,
    ROUND(SUM(t.notional_usd), 2)           AS total_notional_usd,
    ROUND(AVG(t.notional_usd), 2)           AS avg_notional_usd
FROM trades  t
JOIN metals  m ON t.symbol = m.symbol
WHERE t.status != 'Cancelled'
GROUP BY trade_month, m.asset_class, m.metal_name, t.buy_sell, t.trade_type
ORDER BY trade_month DESC, total_notional_usd DESC;


-- =============================================================================
-- 6. TRADER PERFORMANCE SCORECARD
--    PnL attributed to trader via their book (approximation)
-- =============================================================================
SELECT
    t.trader,
    t.book_id,
    COUNT(DISTINCT t.symbol)                AS metals_traded,
    COUNT(*)                                AS trade_count,
    ROUND(SUM(t.notional_usd), 2)           AS total_volume_usd,
    ROUND(AVG(t.notional_usd), 2)           AS avg_trade_size,
    SUM(CASE WHEN t.status = 'Confirmed' THEN 1 ELSE 0 END) AS confirmed,
    SUM(CASE WHEN t.status = 'Settled'   THEN 1 ELSE 0 END) AS settled,
    SUM(CASE WHEN t.status = 'Pending'   THEN 1 ELSE 0 END) AS pending,
    SUM(CASE WHEN t.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled
FROM trades t
GROUP BY t.trader, t.book_id
ORDER BY total_volume_usd DESC;
