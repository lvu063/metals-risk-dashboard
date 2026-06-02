# Power Automate — Flow Documentation
## Metals Risk Dashboard: Daily Pipeline Orchestration

| Field | Detail |
|---|---|
| **Flow Name** | MTD_DailyRiskPipeline_Prod |
| **Environment** | Production |
| **Owner** | Risk Technology Team |
| **Trigger type** | Scheduled (Recurrence) |
| **Run schedule** | Mon–Fri, 06:30 ET |
| **Last modified** | 2024-10-01 |
| **Status** | Active |

---

## Overview

This document describes three Power Automate flows that orchestrate the end-to-end daily metals risk pipeline. Together they replace 14 hours/week of manual analyst work: downloading price files, refreshing Excel blotters, running SQL updates, and distributing reports.

```
06:30 ET                07:00 ET              07:30 ET             08:00 ET
   │                       │                      │                    │
   ▼                       ▼                      ▼                    ▼
[Flow 1]              [Flow 2]              [Flow 3]              Trading
Price File       ETL Trigger &         Report Distribution      Desk Open
Ingestion        Validation            & Alerts
```

---

## Flow 1 — Price File Ingestion

**Purpose:** Monitor SharePoint for incoming price files from LBMA/LME vendor, validate format, move to processing folder.

### Trigger
- **Type:** Automated — SharePoint file created
- **Site:** `https://bmofg.sharepoint.com/sites/GlobalTradingSolutions`
- **Library:** `RiskData/PriceFeeds/Incoming`
- **File filter:** `*.csv`

### Steps

```
1. TRIGGER: When a file is created in SharePoint folder
   └── Folder: /RiskData/PriceFeeds/Incoming

2. ACTION: Get file content
   └── File: triggerOutputs()?['body/Id']

3. ACTION: Get file metadata
   └── Capture: file name, size, created time

4. CONDITION: Is file name valid?
   └── Expression: startsWith(triggerOutputs()?['body/Name'], 'LBMA_')
                   OR startsWith(triggerOutputs()?['body/Name'], 'LME_')
   ├── YES → Step 5
   └── NO  → Step 8 (Error branch)

5. ACTION: Parse CSV (using "Parse JSON" on CSV content)
   └── Validate columns: price_date, symbol, spot_price, currency, source

6. CONDITION: Row count > 0 AND required columns present?
   ├── YES → Step 7
   └── NO  → Step 8 (Error branch)

7. ACTION: Move file to /RiskData/PriceFeeds/Validated
   └── Also: Create item in SharePoint list "PipelineLog"
             Fields: run_date, file_name, row_count, status="Validated"

8. (Error) ACTION: Move file to /RiskData/PriceFeeds/Rejected
   └── ACTION: Send email via Outlook
               To: risk-tech@bmo.com
               Subject: ⚠ Price file rejected — [filename]
               Body: File failed validation. Check /Rejected folder.
   └── ACTION: Post to Teams channel "Risk Tech Alerts"
               Message: "@Risk Tech — price file [name] failed validation at [time]"
```

### Outputs
- Validated files in `/Validated` folder
- Log entry in `PipelineLog` SharePoint list
- Rejection email + Teams alert on failure

---

## Flow 2 — ETL Trigger and Validation

**Purpose:** After price file lands in Validated folder, trigger Python ETL, monitor completion, and validate output row counts.

### Trigger
- **Type:** Automated — SharePoint item created
- **List:** `PipelineLog` (status = "Validated")

### Steps

```
1. TRIGGER: When item created in PipelineLog with status = "Validated"

2. ACTION: HTTP POST to Azure Function (ETL trigger endpoint)
   └── Method: POST
       URL: https://mrd-functions.azurewebsites.net/api/RunETL
       Headers: { "x-functions-key": "[stored in Key Vault]" }
       Body: {
         "price_file": "@{triggerBody()?['file_name']}",
         "run_date":   "@{utcNow('yyyy-MM-dd')}",
         "env":        "production"
       }

3. ACTION: Delay — wait 20 minutes
   └── (ETL runtime SLA is <30 minutes per NFR-01)

4. ACTION: HTTP GET — check ETL status
   └── URL: https://mrd-functions.azurewebsites.net/api/ETLStatus
       Query: run_date=@{utcNow('yyyy-MM-dd')}

5. CONDITION: ETL status = "COMPLETE"?
   ├── YES → Step 6
   └── NO  → Step 9 (Retry/Escalate branch)

6. ACTION: HTTP GET — fetch row count validation
   └── Returns: { trades_loaded, positions_calculated, pnl_records }

7. CONDITION: Row counts within expected range?
   └── Expression: int(body('Get_Counts')?['trades_loaded']) > 0
                   AND int(body('Get_Counts')?['pnl_records']) > 0
   ├── YES → Step 8
   └── NO  → Step 9

8. ACTION: Update SharePoint list item
   └── PipelineLog: status = "ETL_COMPLETE", row_counts = [json]
   └── ACTION: Trigger Flow 3 (Report Distribution)
       via HTTP POST to Flow 3 webhook URL

9. (Retry) CONDITION: Retry attempt < 2?
   ├── YES → Delay 10 min → go back to Step 4
   └── NO  → Escalate:
             Send Outlook email to risk-tech@bmo.com + manager
             Post to Teams: "🔴 ETL FAILED after 2 retries — [date]"
             Update PipelineLog: status = "FAILED"
```

### Error Handling Summary

| Failure point | Retry | Escalation |
|---|---|---|
| Price file invalid | None (immediate) | Email + Teams |
| ETL timeout (>30 min) | 2× retry, 10 min apart | Email + Teams + manager CC |
| Row count zero | 1× retry | Email + Teams |
| Azure Function unreachable | 3× retry, 2 min apart | IT ops page |

---

## Flow 3 — Report Distribution and Alerts

**Purpose:** After ETL completes successfully, refresh Power BI dataset, distribute daily summary email, and fire breach alerts.

### Trigger
- **Type:** Instant — HTTP request (called by Flow 2 Step 8)
- **Schema:** `{ "run_date": "string", "pnl_total": "number", "breach_flags": "array" }`

### Steps

```
1. TRIGGER: HTTP request from Flow 2

2. ACTION: Refresh Power BI Dataset
   └── Workspace: Metals Risk Dashboard
       Dataset: MetalsRiskDataset
       Wait for completion: YES

3. ACTION: Get PnL summary from SharePoint list
   └── List: DailyPnLSummary
       Filter: run_date = @{triggerBody()?['run_date']}

4. ACTION: Compose daily summary HTML email body
   └── Dynamic content from Step 3:
       - Total Unrealised PnL
       - Precious Metals PnL
       - Base Metals PnL
       - Open positions count
       - Largest single-day move (metal name + %)

5. ACTION: Send email via Outlook
   └── To: dl-metals-risk@bmo.com
       Subject: 📊 Metals Risk Summary — @{triggerBody()?['run_date']}
       Body: [HTML from Step 4]
       Attachment: link to Power BI report

6. CONDITION: Any breach flags in input?
   └── Expression: length(triggerBody()?['breach_flags']) > 0
   ├── NO  → Step 9 (Log success)
   └── YES → Step 7

7. APPLY TO EACH breach in breach_flags array:
   └── ACTION: Post adaptive card to Teams channel "Risk Alerts"
       Card fields:
         Title:   "⚠ Risk Limit Breach Detected"
         Book:    item()?['book_id']
         Metal:   item()?['metal']
         Type:    item()?['breach_type']   -- e.g. "Concentration >40%"
         Value:   item()?['value']
         Limit:   item()?['limit']
       Buttons: [View in Dashboard] [Acknowledge]

8. ACTION: Create SharePoint list item in "BreachLog"
   └── Fields: breach_date, book_id, metal, breach_type, value, limit, status="Open"

9. ACTION: Update PipelineLog
   └── status = "COMPLETE", end_time = utcNow()
   └── Post to Teams "Risk Tech Ops": "✅ Pipeline complete — [date] [row counts]"
```

---

## Flow 4 — Manual Override Approval (Supporting Flow)

**Purpose:** When a trader requests a manual price override (FR-06 in BRD), route through approval before applying.

### Trigger
- **Type:** Instant — Power Apps button (from `MetalsOverrideTool` app)
- **Inputs:** `metal`, `original_price`, `override_price`, `reason`, `requested_by`

### Steps

```
1. TRIGGER: PowerApps calls flow with override request

2. ACTION: Start and wait for approval
   └── Approval type: First to respond
       Assigned to: risk-manager@bmo.com
       Title: "Price Override Request — [metal] — [date]"
       Details: "Trader: [requested_by]
                 Metal: [metal]
                 Original: [original_price]
                 Override: [override_price]
                 Reason: [reason]"
       Timeout: 2 hours

3. CONDITION: Outcome = "Approve"?
   ├── YES → Step 4
   └── NO  → Notify requester: "Override rejected by risk manager"
              Update override log: status = "Rejected"

4. ACTION: HTTP POST to ETL API — apply override
   └── Body: { metal, override_price, approved_by, reason, timestamp }

5. ACTION: Append to SharePoint list "PriceOverrideAuditLog"
   └── Fields: request_date, metal, original, override, reason,
               requested_by, approved_by, approval_time
               (Satisfies Compliance requirement — audit trail)

6. ACTION: Notify requester via email
   └── "Your override for [metal] has been approved and applied."

7. ACTION: Post to Teams "Risk Tech Ops"
   └── "📝 Price override applied: [metal] [original] → [override] | Approved by [name]"
```

---

## SharePoint Lists Used

| List name | Purpose | Key fields |
|---|---|---|
| `PipelineLog` | Daily run audit trail | run_date, status, file_name, row_counts |
| `DailyPnLSummary` | Aggregated PnL for email | run_date, pnl fields per desk/metal |
| `BreachLog` | Open risk breaches | breach_date, book, metal, type, status |
| `PriceOverrideAuditLog` | Compliance trail for overrides | all override fields + approver |

---

## Teams Channels Used

| Channel | Purpose |
|---|---|
| `Risk Tech Alerts` | Automated breach notifications (adaptive cards) |
| `Risk Tech Ops` | Pipeline status updates (success/failure) |
| `Metals Desk — Daily` | Trader-facing summary (daily PnL email mirror) |

---

## Environment Variables (stored in Power Platform)

| Variable | Value source | Used in |
|---|---|---|
| `ETL_Function_URL` | Azure Key Vault | Flow 2 |
| `ETL_Function_Key` | Azure Key Vault | Flow 2 |
| `PBI_Workspace_ID` | Power BI Service | Flow 3 |
| `PBI_Dataset_ID` | Power BI Service | Flow 3 |
| `SharePoint_Site_URL` | Static config | All flows |

Never hardcode keys in flow steps — always reference environment variables or Key Vault connections.
