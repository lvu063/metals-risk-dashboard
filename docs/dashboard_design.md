# Power BI Dashboard Design — Metals Risk Terminal

## Overview

This document describes the layout, visuals, DAX measures, and configuration of the **Metals Risk Dashboard** Power BI report (`metals_dashboard.pbix`).

The report has four pages, mirroring how a real trading desk would consume risk data — from the executive summary down to the individual trade level.

---

## Data Model

### Tables and Relationships

```
metals (1) ──────── (M) trades
metals (1) ──────── (M) price_history
metals (1) ──────── (M) positions
metals (1) ──────── (M) pnl_daily
books  (1) ──────── (M) trades
books  (1) ──────── (M) positions
books  (1) ──────── (M) pnl_daily
```

**Relationship types:** All single-direction, active. No bidirectional filters (avoids ambiguity in a financial model).

### Date Table (calculated)

```dax
DateTable =
ADDCOLUMNS(
    CALENDAR(DATE(2024,1,1), DATE(2024,12,31)),
    "Year",         YEAR([Date]),
    "Month",        FORMAT([Date], "MMM YYYY"),
    "MonthNum",     MONTH([Date]),
    "Quarter",      "Q" & FORMAT(QUARTER([Date]),"0"),
    "WeekDay",      FORMAT([Date], "ddd"),
    "IsWeekend",    WEEKDAY([Date],2) >= 6
)
```

Mark as **Date Table** on the `Date` column. Connect to `trades[trade_date]`, `pnl_daily[pnl_date]`, and `price_history[price_date]` with inactive relationships activated via `USERELATIONSHIP()` in measures where needed.

---

## Page 1 — Executive Summary

**Purpose:** One-screen view for senior management. All key numbers visible without scrolling.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  METALS RISK TERMINAL            [Date slicer] [Desk slicer]│
├──────────┬──────────┬──────────┬──────────┬────────────────-┤
│ Total PnL│ MTM Val  │Open Pos. │Win Rate% │ Daily Δ PnL     │
│  KPI card│  KPI card│ KPI card │ KPI card │  KPI card       │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                                                             │
│   PnL by Metal (bar chart, sorted desc by ABS value)        │
│                                                             │
├────────────────────────────────┬────────────────────────────┤
│ Desk split donut chart         │ 30D PnL trend line chart   │
│ (Precious vs Base MTM value)   │ (daily unrealised PnL)     │
└────────────────────────────────┴────────────────────────────┘
```

### Visuals Configuration

**KPI Cards (top row)**

| Card | Measure | Trend | Format |
|---|---|---|---|
| Total Unrealised PnL | `[Total Unrealised PnL]` | vs yesterday | `[PnL Display]` |
| Total MTM Value | `[Total MTM Value]` | — | $#,##0.00 |
| Open Positions | `[Open Positions]` | — | whole number |
| Win Rate | `[Win Rate %]` | — | 0.0% |
| Daily PnL Change | `[Daily PnL Change]` | up/down icon | `[PnL Change Label]` |

**Conditional formatting on KPI cards:**
- Font colour rule: `[PnL Colour Value]` → Green (#00C851) if = 1, Red (#FF4444) if = -1

**PnL by Metal (clustered bar chart)**
- Axis: `metals[metal_name]`
- Values: `[Total Unrealised PnL]`
- Sort: Descending by absolute value
- Data colours: Conditional — positive = green, negative = red
- Data labels: ON, formatted as `[PnL Display]`

**Desk Split (donut chart)**
- Legend: `books[desk]`
- Values: `[Total MTM Value]`
- Colours: Precious = #c9a84c (gold), Base = #4a9eff (steel blue)

**30D PnL Trend (line chart)**
- X axis: `DateTable[Date]` (last 30 days via slicer default)
- Y axis: `[Total Unrealised PnL]`
- Line colour: #c9a84c
- Enable markers: OFF (cleaner)
- Reference line: constant at 0 (dotted, red)

---

## Page 2 — Position Monitor

**Purpose:** Trader-facing. What do we own? Where are we long/short?

### Visuals

**Position heatmap (matrix)**
- Rows: `books[book_id]`
- Columns: `metals[metal_name]`
- Values: `[Net Exposure USD]`
- Conditional format: diverging colour scale (red → white → green, centred at 0)

**Long/Short bar (100% stacked bar)**
- Axis: `metals[metal_name]`
- Series: `[Gross Long USD]` and `[Gross Short USD]`
- Colours: Long = #00C851, Short = #FF4444
- Shows directional imbalance at a glance

**Top 5 open positions (table)**

| Column | Source |
|---|---|
| Metal | `metals[metal_name]` |
| Book | `positions[book_id]` |
| Net Qty | `positions[net_quantity]` |
| Unit | `metals[unit]` |
| Avg Cost | `positions[avg_cost_usd]` |
| Spot | `[Latest Spot Price]` |
| MTM Value | `[Total MTM Value]` |
| Unrealised PnL | `[Total Unrealised PnL]` |
| L/S | `positions[long_short]` |

Enable drill-through from this table to **Page 4 (Trade Blotter)** filtered by book + metal.

**Concentration gauge (card + bar)**
- `[Book Concentration %]` per book
- Conditional background: >40% = red background on row

---

## Page 3 — Risk & Exposure

**Purpose:** Risk manager view. Limits, counterparty, settlement.

### Visuals

**Gross/Net Exposure by Metal (waterfall chart)**
- Waterfall: Gross Long → Gross Short → Net
- Measure: `[Gross Long USD]`, `[Gross Short USD]`, `[Net Exposure USD]`

**Counterparty Exposure (horizontal bar)**
- Axis: `trades[counterparty]`
- Values: `[Counterparty Gross Exposure]`
- Sort descending
- Reference line: credit limit threshold (hardcoded or parameter)

**Settlement Ladder (clustered column)**
- X axis: settlement week (calculated column: `FORMAT([settlement_date],"YYYY-WW")`)
- Y axis: net cash flow per week
- Colours: positive flow = green, negative = red

**Volatility sparklines (small multiples)**
- One line per metal showing 30-day rolling vol
- Uses `price_history` table with vol measure via DAX window function approximation

---

## Page 4 — Trade Blotter

**Purpose:** Ops/middle office. Full trade-level detail with filters.

### Visuals

**Slicer panel (left column)**
- Date range slicer → `trades[trade_date]`
- Metal multi-select → `metals[metal_name]`
- Desk dropdown → `books[desk]`
- Status dropdown → `trades[status]`
- Buy/Sell toggle → `trades[buy_sell]`

**Trade table (main body)**

Columns: `trade_id`, `trade_date`, `settlement_date`, `metal_name`, `desk`, `book_id`, `trader`, `counterparty`, `buy_sell`, `trade_type`, `quantity`, `unit`, `trade_price`, `notional_usd`, `status`

Row-level conditional formatting:
- Cancelled rows → grey italic
- Pending rows → amber background
- Notional > $5M → bold

**Summary bar (below table)**
- `[Active Trade Count]` · `[Total Notional USD]` · `[Avg Trade Size USD]` · `[Largest Trade USD]`

---

## Slicers (Global — applied to all pages via sync)

| Slicer | Field | Type |
|---|---|---|
| As-of Date | `DateTable[Date]` | Date range |
| Desk | `books[desk]` | Dropdown |
| Asset Class | `metals[asset_class]` | Tile |
| Metal | `metals[metal_name]` | Multi-select list |
| Book | `books[book_id]` | Dropdown |

Enable **Sync Slicers** across all pages (View → Sync Slicers).

---

## Report Theme (JSON snippet)

Save as `metals_theme.json` and import via View → Themes → Browse:

```json
{
  "name": "Metals Risk Terminal",
  "dataColors": ["#c9a84c","#4a9eff","#00C851","#FF4444","#7b68ee","#ff9f40"],
  "background": "#0a1628",
  "foreground": "#e8e8e8",
  "tableAccent": "#c9a84c",
  "visualStyles": {
    "*": {
      "*": {
        "background": [{"color": "#0d1f3c"}],
        "fontColor": [{"color": "#e8e8e8"}],
        "gridlineColor": [{"color": "#1e3a5f"}]
      }
    }
  }
}
```

---

## Publishing & Refresh

1. Publish to **Power BI Service** (workspace: `Metals Risk Dashboard`)
2. Configure **scheduled refresh**: daily at 07:30 ET (after ETL completes)
3. Set up **data gateway** if running against local SQLite → migrate to Azure SQL or PostgreSQL for cloud refresh
4. Share dashboard with stakeholders via workspace access, not individual share links
5. Create a **Power BI App** to bundle all four pages into a single distributed view

---

## Row-Level Security (RLS)

```dax
-- Role: "Desk_PreciousMetals"
-- Filter on books table:
[desk] = "Precious Metals"

-- Role: "Desk_BaseMetals"
[desk] = "Base Metals"

-- Role: "Risk_AllDesks"
-- No filter — sees everything
```

Assign via Power BI Service → Security tab on the dataset.
