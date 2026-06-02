# 🏦 Metals Trading Risk Dashboard

> An end-to-end data pipeline and reporting system simulating a precious & base metals trading desk at a major financial institution. Built to demonstrate skills in data engineering, SQL analytics, business analysis, and financial domain knowledge.

---

## 📌 Project Overview

Trading desks generate enormous volumes of data — trade blotters, market prices, positions, and PnL — often managed in fragmented Excel files. This project builds a **production-style data pipeline and reporting layer** that replaces that manual workflow with:

- A **Python ETL pipeline** that generates synthetic trade data and loads it into a structured database
- **SQL analytics** covering PnL Explained, risk exposure, counterparty limits, and the settlement ladder
- A **Power BI dashboard** providing desk-level, book-level, and metal-level drill-through
- A full **Business Requirements Document (BRD)** and test strategy — as would be produced in a real BA engagement

**Asset classes covered:** Gold · Silver · Platinum · Palladium · Copper · Aluminium · Zinc · Nickel

---

## 🗂️ Repository Structure

```
metals-risk-dashboard/
│
├── python/
│   ├── generate_mock_data.py    # Synthetic trade/price data generator (GBM price paths)
│   └── etl_pipeline.py          # Extract → Validate → Transform → Load pipeline
│
├── sql/
│   ├── schema.sql               # Full database schema (SQLite / PostgreSQL)
│   ├── pnl_explained.sql        # PnL decomposition: price effect vs position effect
│   └── risk_summary.sql         # Exposure, concentration, settlement ladder, vol
│
├── data/                        # Generated CSV outputs (gitignored in production)
│   ├── trades.csv
│   ├── price_history.csv
│   ├── positions.csv
│   └── pnl_summary.csv
│
├── powerbi/
│   └── metals_dashboard.pbix    # Power BI report file
│
└── docs/
    ├── business_requirements.md # Full BRD with stakeholder requirements
    ├── test_strategy.md          # UAT plan, test cases, and acceptance criteria
    └── data_dictionary.md        # Field-level definitions for all tables
```

---

## ⚙️ Quick Start

### 1. Generate mock data

```bash
# Default: 300 trades, 2024 calendar year
python python/generate_mock_data.py

# Custom options
python python/generate_mock_data.py --rows 1000 --seed 7 --start 2023-01-01 --end 2023-12-31
```

This produces four CSV files in `/data`:

| File | Description | Rows (default) |
|---|---|---|
| `trades.csv` | Trade blotter with 18 fields per trade | 300 |
| `price_history.csv` | Daily spot prices for 8 metals (GBM simulation) | ~2,088 |
| `positions.csv` | Net position per book/metal as of end date | ~24 |
| `pnl_summary.csv` | Unrealised PnL per position | ~24 |

### 2. Load into SQLite and run queries

```bash
# Create the database schema
sqlite3 metals.db < sql/schema.sql

# Import CSVs
sqlite3 metals.db << 'EOF'
.mode csv
.import data/trades.csv trades
.import data/price_history.csv price_history
.import data/positions.csv positions
.import data/pnl_summary.csv pnl_daily
EOF

# Run analytics
sqlite3 -header -column metals.db < sql/pnl_explained.sql
sqlite3 -header -column metals.db < sql/risk_summary.sql
```

---

## 📊 SQL Analytics

### PnL Explained (`pnl_explained.sql`)

Six analytical queries covering:

| Query | What it answers |
|---|---|
| **Daily PnL by book/metal** | Unrealised gain/loss per position with direction flag |
| **PnL Explained (day-over-day)** | Breaks PnL change into price effect and position effect |
| **Desk rollup** | Senior management view: total MTM, PnL, win/loss ratio per desk |
| **Metal contribution** | Which metals are driving portfolio gains or losses? |
| **Trade activity** | Monthly volume, trade count, and average size by metal and direction |
| **Trader scorecard** | Volume and trade status breakdown per trader |

### Risk Summary (`risk_summary.sql`)

| Query | What it answers |
|---|---|
| **Gross/net exposure** | Long and short notional per metal; net directional risk |
| **Book concentration** | Flags any book >40% of total portfolio notional |
| **Settlement ladder** | 13-week cash flow projection by week |
| **Counterparty exposure** | Gross and net credit exposure per counterparty |
| **Long/short imbalance** | Detects one-sided books with imbalance flag |
| **30-day realised vol** | Rolling annualised volatility per metal using log returns |

---

## 📐 Data Model

```
metals ──────────────────────────────────────┐
  │ symbol (PK)                              │
  │ metal_name, asset_class, unit, source    │
  └──────────┬──────────────────────────────┘
             │
books        │         price_history
  │ book_id  │           │ price_date
  │ desk     │           │ symbol → metals
  │ book_type│           │ spot_price, currency
  └────┬─────┘           │
       │                 │
       ▼                 ▼
    trades ──────────────────────
      │ trade_id (PK)
      │ trade_date, settlement_date
      │ symbol → metals
      │ book_id → books
      │ quantity, trade_price, notional_usd
      │ buy_sell, trade_type, status
       │
       ▼
    positions ──── pnl_daily
      (net qty       (MTM, cost basis,
       per book)      unrealised PnL)
```

---

## 📋 Business Analysis Artefacts

### Business Requirements Document
`docs/business_requirements.md` — A full BRD covering:
- Problem statement with stakeholder pain points
- In-scope / out-of-scope for Phase 1
- Functional requirements (FR-01 through FR-24) with priority and source
- Non-functional requirements (SLAs, RBAC, uptime)
- Business rules (settlement conventions, MTM currency, cost basis method)
- Acceptance criteria for UAT sign-off

### Test Strategy
`docs/test_strategy.md` — Covers:
- Test scope and approach (unit, integration, UAT)
- Test cases mapped to acceptance criteria
- Defect triage and escalation process

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Data generation | Python 3.11 · NumPy / random / math |
| Data storage | SQLite (local) · PostgreSQL-compatible schema |
| Analytics | SQL (window functions, CTEs, aggregations) |
| Visualisation | Power BI (DAX measures, drill-through, slicers) |
| Automation | Python ETL · CSV validation · exception logging |
| Documentation | Markdown · structured BRD format |

---

## 🏷️ Skills Demonstrated

This project is designed to map directly to roles in **financial data engineering** and **commodities business analysis**:

| Skill Area | Where to Find It |
|---|---|
| SQL analytics (window functions, CTEs) | `sql/pnl_explained.sql`, `sql/risk_summary.sql` |
| Python data pipeline & automation | `python/generate_mock_data.py`, `python/etl_pipeline.py` |
| Financial domain: PnL Explained | `sql/pnl_explained.sql` Query 2 |
| Financial domain: Inventory / position mgmt | `sql/risk_summary.sql` Queries 1, 5 |
| Financial domain: Risk reporting | `sql/risk_summary.sql` Queries 2–4 |
| Business requirements documentation | `docs/business_requirements.md` |
| Test strategy & UAT planning | `docs/test_strategy.md` |
| Data modelling | `sql/schema.sql` |
| Power BI dashboard design | `powerbi/metals_dashboard.pbix` |

---

## 📈 Sample Output

```
Metal-level PnL Contribution (as of 2024-12-31)
------------------------------------------------
asset_class  metal_name  net_qty    spot_usd   total_pnl    pnl_pct
Precious     Gold         10,000    2,003.26   -12,748,857  -38.9%
Precious     Silver       31,000       24.32     -174,339   -18.8%
Base         Copper    1,125,000        3.91   +2,156,230   +12.4%
Base         Nickel       50,000   16,450.00   +3,892,100    +8.1%
```

---

## 🔭 Roadmap

- [ ] **Phase 2** — Realised PnL, FX-adjusted exposure, multi-currency books
- [ ] **Phase 3** — Endur/ETRM mock integration, VaR calculation, Greeks for options
- [ ] **Automation** — Power Automate workflow for daily report distribution
- [ ] **ML** — Price anomaly detection using isolation forest

---

## 📄 License

MIT — free to use, adapt, and reference for portfolio purposes.

---

*Built as a portfolio project targeting roles in financial data engineering and commodities business analysis.*
