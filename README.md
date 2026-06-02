# 🏦 Metals Trading Risk Dashboard

> An end-to-end data pipeline and reporting system simulating a precious & base metals trading desk at a major financial institution. Built to demonstrate production-level skills in data engineering, Python OOP, SQL analytics, web development, and financial domain knowledge.

---

## 📌 Project Overview

Trading desks generate enormous volumes of data — trade blotters, market prices, positions, and PnL — often managed in fragmented Excel files. This project builds a **production-style data pipeline and reporting layer** that replaces that manual workflow with:

- A **Python ETL pipeline** that ingests, validates, and loads trade data into a structured SQLite database
- A **Python OOP analysis module** using pandas and numpy for PnL attribution, volatility, correlation, and exposure analytics
- **SQL analytics** covering PnL Explained, risk exposure, counterparty limits, and the settlement ladder
- A **Power BI dashboard** with 35 DAX measures, drill-through navigation, and row-level security
- A **vanilla JS internal web portal** for browsing PnL data with live filtering, sorting, and CSV export
- **Power Automate flows** orchestrating the full daily pipeline — file ingestion, ETL trigger, PBI refresh, and breach alerts
- A full **Business Requirements Document** and test strategy — 55 test cases across 6 test groups

**Asset classes covered:** Gold · Silver · Platinum · Palladium · Copper · Aluminium · Zinc · Nickel

---

## Live Dashboard

**[View interactive dashboard →](https://metals-risk-angie.lovable.app/)**

---

## 🗂️ Repository Structure

```
metals-risk-dashboard/
│
├── python/
│   ├── generate_mock_data.py    # Synthetic data generator — GBM price paths, 8 metals
│   ├── etl_pipeline.py          # Extract → Validate → Transform → Load → Verify
│   └── analysis.py              # OOP analysis module — pandas/numpy, 4-class design
│
├── sql/
│   ├── schema.sql               # Full DB schema (SQLite / PostgreSQL compatible)
│   ├── pnl_explained.sql        # PnL decomposition: price effect vs position effect
│   └── risk_summary.sql         # Exposure, concentration, settlement ladder, vol
│
├── web/
│   └── index.html               # Internal risk portal — HTML/CSS/JS, no frameworks
│
├── powerbi/
│   ├── dax_measures.dax         # 35 DAX measures across 8 categories
│   └── dashboard_design.md      # Full 4-page report spec with layout and RLS config
│
├── excel/
│   ├── MetalsRiskDashboard.xlsx # Formatted workbook: blotter, PnL, risk, VBA macros
│   └── build_excel_workbook.py  # Script that generates the workbook via openpyxl
│
├── docs/
│   ├── business_requirements.md # BRD: FR-01–FR-24, NFRs, acceptance criteria
│   ├── test_strategy.md         # 55 test cases, defect triage, UAT sign-off matrix
│   ├── power_automate_flows.md  # 4 documented flows: ingestion, ETL, reporting, override
│   └── endur_integration_notes.md # Endur ETRM domain knowledge and integration plan
│
└── data/                        # Generated CSVs (run generate_mock_data.py first)
    ├── trades.csv
    ├── price_history.csv
    ├── positions.csv
    └── pnl_summary.csv
```

---

## ⚙️ Quick Start

### 1. Install dependencies

```bash
pip install pandas numpy openpyxl
```

### 2. Generate mock data

```bash
# Default: 300 trades, 2024 calendar year
python python/generate_mock_data.py

# Custom options
python python/generate_mock_data.py --rows 1000 --seed 7 --start 2023-01-01 --end 2023-12-31
```

### 3. Run the ETL pipeline

```bash
# Full pipeline with post-load verification (9 checks)
python python/etl_pipeline.py --verify

# Dry run — validate only, no DB writes
python python/etl_pipeline.py --dry-run
```

### 4. Run the analysis module

```bash
# All reports: PnL, risk exposure, volatility, correlation
python python/analysis.py

# Individual reports
python python/analysis.py --report pnl
python python/analysis.py --report risk
python python/analysis.py --report vol

# Export results to CSV
python python/analysis.py --export
```

### 5. Open the web portal

```bash
# No server needed — open directly in any browser
open web/index.html
```

Click **Load Demo Data** to see the dashboard immediately, or drop your own `pnl_summary.csv` onto the upload zone.

### 6. Run SQL analytics

```bash
sqlite3 -header -column metals.db < sql/pnl_explained.sql
sqlite3 -header -column metals.db < sql/risk_summary.sql
```

---

## 🐍 Python OOP Design (`analysis.py`)

The analysis module uses a four-class architecture demonstrating OOP principles:

```
MetalsDashboard          ← Facade: single entry point, composes the three below
    │
    ├── DataLoader        ← Extraction: loads/validates/caches CSVs as typed DataFrames
    ├── MetalsAnalyser    ← Logic: PnL, exposure, volatility, correlation (pandas/numpy)
    └── RiskReporter      ← Presentation: formatted console output and CSV export
```

Three typed dataclasses (`PnLSummary`, `VolatilityResult`, `ExposureSnapshot`) carry results between layers with `__repr__` methods for clean debugging.

**pandas/numpy used for:**
- Log return calculation: `np.log(prices / prices.shift(1))`
- Rolling annualised volatility: `rolling().std() * np.sqrt(252)`
- Pearson correlation matrix: `pivot.corr(method="pearson")`
- Multi-key aggregation: `groupby().agg()`
- Conditional column creation: `np.where()`
- Period conversion: `dt.to_period("M")`

---

## 🌐 Web Portal (`web/index.html`)

A self-contained internal portal — **zero frameworks, zero dependencies**. Pure HTML, CSS, and vanilla JavaScript.

**CSS features:** CSS custom properties (variables), CSS Grid, Flexbox, sticky navigation, keyframe animations, responsive breakpoints, transition effects, conditional classes for PnL colouring.

**JavaScript features:**

| Feature | Implementation |
|---|---|
| CSV parser | Manual parser handling quoted fields with commas |
| Multi-column sort | Direction toggle, numeric vs string detection |
| Live search | Filters across metal, book, desk, symbol simultaneously |
| Multi-filter | Desk · Direction (Long/Short) · PnL (Gain/Loss) — all combinable |
| KPI cards | Recompute dynamically on every filter change |
| Drag-and-drop upload | `dragover` / `drop` events with file reader |
| CSV export | Serialises current filtered view to downloadable file |
| Live UTC clock | `setInterval` updating every second |

---

## 📊 SQL Analytics

### PnL Explained (`pnl_explained.sql`)

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

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Data generation | Python · `random` · `math` (GBM simulation) |
| Data analysis | Python OOP · `pandas` · `numpy` |
| ETL pipeline | Python · CSV validation · SQLite · structured logging |
| Data storage | SQLite (local) · PostgreSQL-compatible schema |
| SQL analytics | Window functions · CTEs · aggregations · log return vol |
| Web portal | HTML5 · CSS3 · Vanilla JavaScript (no frameworks) |
| BI dashboards | Power BI · DAX (35 measures) · RLS · scheduled refresh |
| Automation | Power Automate (4 flows) · SharePoint · Teams · Outlook |
| Excel | openpyxl · conditional formatting · VBA macros |
| Documentation | BRD · Test strategy · Endur integration notes |

---

## 🏷️ Skills Demonstrated

| Skill (from JD) | Where to find it |
|---|---|
| Python OOP | `python/analysis.py` — 4-class design, dataclasses, Facade pattern |
| Data handling libraries (pandas/numpy) | `python/analysis.py` — rolling vol, correlation, groupby, np.where |
| SQL programming | `sql/pnl_explained.sql`, `sql/risk_summary.sql` |
| HTML / CSS / JavaScript | `web/index.html` — self-contained, no frameworks |
| Power BI / DAX | `powerbi/dax_measures.dax`, `powerbi/dashboard_design.md` |
| Power Automate | `docs/power_automate_flows.md` — 4 flows documented end-to-end |
| M365 integration | Power Automate flows: SharePoint, Teams, Outlook |
| Excel / macros | `excel/MetalsRiskDashboard.xlsx`, VBA in `build_excel_workbook.py` |
| Endur / ETRM knowledge | `docs/endur_integration_notes.md` |
| Business requirements | `docs/business_requirements.md` — FR-01–FR-24 |
| Test strategy & UAT | `docs/test_strategy.md` — 55 test cases, sign-off matrix |
| ETL pipeline design | `python/etl_pipeline.py` — validate, transform, load, verify |
| Data modelling | `sql/schema.sql` |
| Commodities domain | All files — desk structure, PnL Explained, settlement, curves |

---

## 📈 Sample Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  METALS RISK DASHBOARD — Analysis Report   2024-12-31
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DESK                  MTM VALUE        UNREALISED PnL      PnL%
────────────────────────────────────────────────────────────────────
Base Metals      $1,023,895,336   ▲ +$432,281,941      +73.07%
Precious Metals  $ -143,968,460   ▼  $-80,405,165       -7.56%

VOLATILITY SUMMARY
Metal       Symbol   Ann Vol%    52W High      52W Low   Range%
────────────────────────────────────────────────────────────────────
Nickel      NI        40.76%    $30,928.09   $15,066.50  105.3%
Copper      HG        35.87%    $     6.91   $     3.64   89.5%
Gold        XAU       17.24%    $ 2,626.18   $ 1,971.71   33.2%
```

---

## 🔭 Roadmap

- [ ] **Sustainability pivot** — reframe asset classes around carbon markets (EUA, CCA), critical minerals for EVs, and renewable energy certificates
- [ ] **Phase 2** — Realised PnL, FX-adjusted exposure, multi-currency books
- [ ] **Phase 3** — Endur/ETRM direct Oracle DB integration, VaR calculation
- [ ] **ML** — Price anomaly detection using isolation forest

---

## 📄 License

MIT — free to use, adapt, and reference for portfolio purposes.

---

*Built as a portfolio project targeting data engineering roles in financial services. Background in international economics and development — strong on financial domain knowledge, building technical depth.*
