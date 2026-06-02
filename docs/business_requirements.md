# Business Requirements Document (BRD)
## Metals Trading Risk Dashboard — Phase 1

| Field | Detail |
|---|---|
| **Document ID** | BRD-MTD-2024-001 |
| **Version** | 1.2 |
| **Status** | Approved |
| **Author** | Business Analyst, Global Trading Solutions |
| **Reviewers** | Front Office, Market Risk, Global Middle Office, Back Office |
| **Date** | 2024-09-15 |
| **Application Deadline** | 2024-10-01 |

---

## 1. Executive Summary

Global Trading Solutions requires a consolidated **Metals Trading Risk Dashboard** to provide real-time visibility into trading positions, PnL, and market risk exposures across Precious and Base Metals desks. Currently, risk reporting is fragmented across manual Excel workbooks, resulting in delayed PnL reporting, inconsistent exposure calculations, and operational risk from human error.

This BRD defines the business requirements for Phase 1: a data pipeline, position management system, and interactive reporting layer covering Gold, Silver, Platinum, Palladium, Copper, Aluminium, Zinc, and Nickel.

---

## 2. Business Context

### 2.1 Problem Statement

The Metals trading desks operate across two business lines:

- **Precious Metals** — physical and derivative trading in XAU, XAG, XPT, XPD, priced against LBMA benchmarks
- **Base Metals** — LME-traded contracts in Copper, Aluminium, Zinc, Nickel; including inventory management and physical delivery

Current pain points identified during stakeholder interviews:

| # | Pain Point | Business Impact | Source |
|---|---|---|---|
| P1 | PnL reports produced manually in Excel, T+1 delivery | Risk decisions made on stale data | Front Office |
| P2 | No single source of truth for net positions | Duplicate or conflicting position reports | Middle Office |
| P3 | Counterparty exposure calculated differently by Credit and Trading | Credit limit breaches not caught intraday | Market Risk |
| P4 | Settlement ladder produced ad hoc; no automated cash flow projection | Operations team manually chases settlements | Back Office |
| P5 | No audit trail for price curve overrides | Audit and compliance concerns | Compliance |

### 2.2 Strategic Alignment

This initiative supports the firm's **Ambition 2030** goal of becoming a digital-first, AI-powered trading operation. Specifically:

- Automate repetitive risk reporting tasks (target: save 15+ analyst hours/week)
- Enable intraday risk decisions with live data feeds
- Build a scalable data foundation for future quant model integration

---

## 3. Stakeholders

| Stakeholder | Role | Interest / Concern |
|---|---|---|
| Precious Metals Desk Head | Sponsor | Daily PnL accuracy; desk-level P&L attribution |
| Base Metals Trader | End user | Real-time position view; fast blotter access |
| Market Risk Manager | Reviewer | Exposure limits; VaR inputs; volatility data |
| Global Middle Office Lead | Reviewer | Trade confirmation status; settlement accuracy |
| Back Office Operations | End user | Settlement ladder; cash flow projections |
| MFL Quants | Consumer | Clean price history for model calibration |
| Technology BA (author) | Author/Facilitator | Requirements accuracy; test management |
| Compliance | Reviewer | Audit trail; data retention |

---

## 4. Scope

### 4.1 In Scope — Phase 1

- **Data ingestion**: Load trade blotter, market prices, and reference data (metals master, books, counterparties)
- **Position management**: Net position calculation per book/metal as of any given date
- **PnL Explained**: Daily unrealised PnL with price effect and position effect decomposition
- **Risk reporting**: Gross/net exposure, counterparty exposure, long/short imbalance, settlement ladder
- **Dashboard**: Interactive Power BI report with drill-through by desk → book → metal
- **Automation**: Scheduled daily ETL pipeline (Python) replacing manual Excel refresh

### 4.2 Out of Scope — Phase 1

- Realised PnL (requires full trade lifecycle/settlement matching) — Phase 2
- FX-adjusted PnL for non-USD books — Phase 2
- VaR calculation — Phase 3
- Endur/ETRM direct system integration — Phase 3
- Options greeks and premium attribution — Phase 3

---

## 5. Functional Requirements

### 5.1 Data Pipeline (ETL)

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-01 | System shall ingest daily trade blotter CSV from middle office shared drive by 07:00 ET | Must Have | Middle Office |
| FR-02 | System shall ingest daily spot prices from LBMA/LME feeds (or file drop) by 06:30 ET | Must Have | Market Risk |
| FR-03 | System shall validate trade records against reference data (valid symbol, book, counterparty) and reject/flag invalid rows | Must Have | Back Office |
| FR-04 | System shall log all rejected records with reason code to an exceptions table | Must Have | Compliance |
| FR-05 | System shall support historical backfill for up to 24 months of trade history | Should Have | Quants |
| FR-06 | System shall support manual price override with mandatory comment field and user stamp | Should Have | Front Office |

### 5.2 Position Management

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-07 | System shall calculate net position (quantity and notional) per book per metal as of T and T-N | Must Have | Front Office |
| FR-08 | Position calculation shall exclude Cancelled trades and include Confirmed, Pending, and Settled | Must Have | Middle Office |
| FR-09 | System shall display long/short/flat status per position | Must Have | Traders |
| FR-10 | System shall support point-in-time position query (i.e. "what was my position on 2024-06-15?") | Should Have | Compliance |

### 5.3 PnL Reporting

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-11 | System shall calculate daily unrealised PnL = (spot price × net quantity) − cost basis | Must Have | Front Office |
| FR-12 | System shall produce PnL Explained output decomposing: Price Effect, Position Effect | Must Have | Market Risk |
| FR-13 | PnL shall roll up to book → desk → firm level | Must Have | Senior Management |
| FR-14 | System shall flag positions where unrealised PnL exceeds ±10% of cost basis | Should Have | Risk |

### 5.4 Risk & Exposure

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-15 | System shall calculate gross long, gross short, and net USD exposure per metal | Must Have | Market Risk |
| FR-16 | System shall flag any book with >40% concentration of total portfolio notional | Must Have | Risk |
| FR-17 | System shall produce a 13-week rolling settlement ladder showing net cash flows | Must Have | Back Office |
| FR-18 | System shall calculate counterparty gross and net exposure for credit monitoring | Must Have | Credit Risk |
| FR-19 | System shall calculate 30-day rolling annualised volatility per metal | Should Have | Quants |

### 5.5 Dashboard / Reporting

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-20 | Dashboard shall provide desk-level summary with drill-through to book and trade level | Must Have | All desks |
| FR-21 | Dashboard shall update automatically when the daily ETL completes | Must Have | Operations |
| FR-22 | Dashboard shall allow filtering by: date range, desk, book, metal, asset class, trade type | Must Have | Traders |
| FR-23 | Dashboard shall include a PnL trend chart (30-day rolling) per metal | Should Have | Front Office |
| FR-24 | Dashboard shall include a heatmap of concentration by book/metal | Nice to Have | Risk |

---

## 6. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | ETL pipeline must complete within 30 minutes of price file availability | <30 min |
| NFR-02 | Dashboard must load within 5 seconds for typical user query | <5 sec |
| NFR-03 | System must retain 24 months of trade and price history | 24 months |
| NFR-04 | All data access must be role-based (traders see own desk only; risk sees all) | RBAC |
| NFR-05 | All pipeline runs must be logged with row counts, errors, and run time | 100% |
| NFR-06 | System must be available during trading hours 06:00–22:00 ET | 99.5% uptime |

---

## 7. Business Rules

| ID | Rule | Detail |
|---|---|---|
| BR-01 | Spot = T+2 | Default settlement for spot trades is trade date + 2 business days |
| BR-02 | MTM currency | All MTM calculations in USD; FX conversion out of scope Phase 1 |
| BR-03 | Price source hierarchy | LBMA AM/PM fix for Precious; LME official close for Base |
| BR-04 | Net position sign | Long = positive quantity; Short = negative quantity |
| BR-05 | Cancelled trades | Excluded from all position and PnL calculations |
| BR-06 | Cost basis | Weighted average cost of all non-cancelled buys minus sells |

---

## 8. Assumptions & Dependencies

**Assumptions**
- Middle Office will provide a standardised trade blotter CSV schema (defined in Data Dictionary)
- Price vendor file format will not change without 10-day advance notice
- Power BI Pro licences are available for all dashboard users

**Dependencies**
- Middle Office: trade blotter file drop by 07:00 ET daily
- Market Risk: price file schema agreement by 2024-10-01
- IT Infrastructure: Python 3.11 environment and scheduled task runner available

**Risks**
- Price feed delays could cause ETL failures → Mitigation: retry logic + alerting in pipeline
- Schema changes in blotter file could break ingestion → Mitigation: schema validation at ingestion layer with rejection logging

---

## 9. Acceptance Criteria

| ID | Criterion | Verified By |
|---|---|---|
| AC-01 | ETL processes a 300-row trade file end-to-end with zero data loss | BA + Middle Office |
| AC-02 | Net positions for Gold and Copper match manually verified test cases (±$1 rounding tolerance) | BA + Front Office |
| AC-03 | PnL Explained output for a known trade set matches pre-calculated expected values | BA + Market Risk |
| AC-04 | Dashboard drill-through navigates from firm → desk → book → trade with correct filters | BA + IT |
| AC-05 | Counterparty exposure report flags test case exceeding notional threshold | BA + Credit Risk |
| AC-06 | ETL completes within 30-minute SLA on a 300-trade dataset | IT + Operations |

---

## 10. Change Log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2024-08-01 | BA | Initial draft |
| 1.1 | 2024-08-22 | BA | Added NFRs and counterparty exposure requirements after Market Risk review |
| 1.2 | 2024-09-15 | BA | Clarified scope exclusions; added Phase 2/3 items; approved by all stakeholders |
