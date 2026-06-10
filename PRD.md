# Product Requirement Document (PRD)
# Product Name: Omnichannel Foodservice Analytics Engine (OFAE)
### Strategic Framework: Otter (Hubster) Ecosystem Extension for Independent Restaurants

---

## 1. Project Overview & Business Value

### 1.1 Business Problem Statement
Independent, local restaurant brands operating in omnichannel environments face heavy financial erosion. While operations tools like Otter (Hubster) or Deliverect successfully consolidate multi-marketplace order tablets (UberEats, DoorDash, Rappi) into the kitchen POS, their built-in analytics are strictly operational. They show what was sold, but they are completely blind to structural business financials. 

Independent restaurant administrators suffer from two massive financial blind spots:
* **Recipe Cost Blindness (COGS):** Operational middleware tools have no context regarding ingredient costs, packaging expenses, or localized utility overhead. Operators cannot determine their true net profit margins per dish after factoring in steep marketplace commission structures (15% to 30%).
* **Bank Settlement Reconciliation Gaps:** Marketplace providers frequently miscalculate payouts, issue unverified customer refunds, or delay deposits. Busy independent owners lack the analytical infrastructure to cross-audit actual bank deposits against middleware order logs, leaving thousands of dollars in unclaimed platform discrepancies.

### 1.2 Target Data Product (The Commercial SaaS Offering)
OFAE is a specialized financial intelligence platform functioning as a zero-friction extension to a restaurant’s existing Otter setup. It consists of:
1. **An Automated Multi-Tenant S3 Data Lakehouse:** An open-source, decoupled storage footprint that ingests unified data structures directly from the public Otter API.
2. **A Cost-of-Goods-Sold (COGS) Ledger Subsystem:** A lightweight administrative interface allowing merchants to map base recipe and operational expenses to their menu items.
3. **A Serverless Financial Dashboard:** A Streamlit portal providing clean net margin insights, menu engineering alerts, and automated payout reconciliation tracking.

### 1.3 Success Metrics & Commercial KPIs
* **Zero-Friction Onboarding UX:** New users complete platform registration and data synchronization within 60 seconds by providing their Otter API authorization token via a secure OAuth workflow. No marketplace support tickets or developer portal requests are required.
* **Data Freshness SLA:** Complete financial and operational administrative tracking metrics must be successfully processed, audited, and fully visible in the UI by 06:00 AM local restaurant time daily.
* **Platform Gross Margin:** Compute architectures must scale down automatically during idle user patterns to keep operational overhead capped at a target baseline of $5.00 to $15.00 USD per month per low-volume tenant cluster.

---

## 2. Ingestion, Storage, & Security Architecture

### 2.1 Ingestion Strategy (Unified API Daily Batch Polling)
* **Frequency:** Automated cron execution once daily at 02:00 AM local restaurant time to capture the complete preceding operational date ($T-1$).
* **Mechanism:** A centralized Python pipeline extracting standardized merchant data from Otter's public endpoints (`/v1/orders`, `/v1/reports`).
* **Resiliency Controls:**
    * **Time-Windowed Restraints:** Request parameters must strictly bound extractions to `start_date = yesterday_00:00:00` and `end_date = yesterday_23:59:59` relative to store time zones to eliminate duplicate delta data loads.
    * **Rate-Limit Interception:** Network clients must catch HTTP 429 Too Many Requests codes and implement an exponential backoff routine with a maximum of 3 retries before logging execution faults.
    * **Historical Backfill Automation:** Upon successful registration, a one-time routine triggers with a flag (`is_backfill = True`) to sequentially pull the preceding 30 days of order history from Otter to populate dashboards instantly.

### 2.2 Landing Zone & Storage Architecture (AWS S3 Bronze)
Extracted data structures are committed directly to an Amazon S3 layer operating as the **Bronze (Raw) Layer**.
* **Bucket Layout Standard:** `ofae-data-lakehouse-bronze-[environment]`
* **Partition Separation (Multi-Tenant Fencing):** Strict Hive-style directory segregation to guarantee multi-tenant data boundary isolation:
  `s3://ofae-data-lakehouse-bronze-prod/otter/merchant_id=[id]/year=[YYYY]/month=[MM]/day=[DD]/`
* **Format:** Unmodified, raw JSON strings straight from the native Otter API responses to support future model re-playability.

### 2.3 Token Security & Management Specification
* **Credential Subsystem:** Active client environment keys and integration payloads are housed in a relational PostgreSQL configuration container (`merchant_credentials`).
* **Encryption Standards:** Application-layer envelope encryption must be enforced using AES-256-GCM via the Python `cryptography` library. Decryption steps consult an AWS KMS Customer Managed Key (CMK) to safeguard variables at rest while keeping infrastructure overhead at a flat $1.00 USD/month.
* **OAuth Token Refresh Loop Automation:** Prior to firing daily extraction routines, the pipeline evaluates access token timestamps. If the active token falls within a 10-minute expiry window, it executes a renewal call (`grant_type=refresh_token`), securely writes back the updated authorization string to PostgreSQL, and resumes data collection.

---

## 3. Transformation & Storage Tiering (Silver & Gold Layers)

### 3.1 Processing Engine Architecture
* **Framework:** Open-source `dbt-core` managing set-based transformations utilizing a portable, local file-driven adapter (`dbt-duckdb`) executed inside a serverless container environment.
* **Tenant Metadata Bridging:** In addition to Otter data, the transformation layer reads a tenant-managed PostgreSQL table (`merchant_cogs`) containing custom recipe cost parameters entered via the Streamlit frontend UI.

```text
+------------------------------------+
|  S3 Bronze Bucket (Raw Otter JSON) |
+------------------------------------+
                  |
                  v [dbt-duckdb Parsing]
+------------------------------------+      +-----------------------------------------+
| S3 Silver Bucket (Cleaned Parquet) | ---> | PostgreSQL merchant_cogs (Recipe Costs) |
+------------------------------------+      +-----------------------------------------+
                  |                                              |
                  +-----------------------+----------------------+
                                          |
                                          v [dbt Star-Schema Compilation]
                     +---------------------------------------+
                     |   S3 Gold Bucket (Analytical Marts)   |
                     +---------------------------------------+
```

### 3.2 Medallion Tiering Conventions
Silver Layer (Conformed & Flattened)
* Storage Path: s3://ofae-data-lakehouse-silver-prod/

* Format: Columnar Apache Parquet files containing Snappy compression.

* Transformation Logic: Parses nested Otter JSON blobs into uniform tabular fields, standardizing currency keys, and masking personal identifiable information (PII) like end-customer names or delivery phone numbers via salted SHA-256 hashing.

Gold Layer (Business & Analytical Data Marts)
* Storage Path: s3://ofae-data-lakehouse-gold-prod/

* Format: Apache Parquet.

* Structural Design: Star Schema multi-tenant layout mapping clean analytical tables:

    * fact_financial_sales: Combines Otter transaction line items with merchant_cogs data matrices to map gross_order_value, estimated_marketplace_commission, calculated_recipe_cogs, and true net_payout_margin calculations.

    * dim_menu_catalog: Canonical reference vectors mapping user-defined base food costs to menu naming metrics.

## 4. Serving Data & Application Layer (Streamlit)
### 4.1 UI Deployment Specification
* Framework: Open-source Python streamlit web application framework.

* Hosting Subsystem: Fully containerized, serverless instance deployment via AWS App Runner linked directly to version control production branches. This bypasses traditional Linux OS patching, Nginx reverse-proxies, and SSL renewal tracking overhead.

* Cost Mitigation Execution: CPU allocations scale to zero automatically during idle operational windows, maintaining low running costs while preserving quick container warm-up behavior when administrators load the dashboard.

* Data Isolation Protocol: User identities map directly to session states (st.session_state.merchant_id). All backend data routing calls reading Parquet objects from S3 Gold structures enforce this constraint to maintain bulletproof multi-tenant separation:
s3://ofae-data-lakehouse-gold-prod/fact_financial_sales/merchant_id={st.session_state.merchant_id}/

## 5. Observability & Self-Service Error Logging
### 5.1 Self-Service Pipeline Status Framework
Fault tracking and authorization validation histories are saved directly to a relational metadata table (pipeline_execution_logs) and exposed transparently within the Streamlit UI to empower users to troubleshoot external platform problems independently.

### 5.2 User-Facing Error Management Layout
When exceptions intercept background extraction loops, the system catches the fault and maps visibility profiles across three clear tiers:

* Tier 1: User Actionable (Authentication Expirations): Triggers on HTTP 401/403 responses. Streamlit renders a warning banner: "Action Required: Your connection to Hubster/Otter has expired. Please refresh your integration token within the Settings tab to resume daily data auditing."

* Tier 2: Aggregator Latency (Third-Party Downtime): Triggers on HTTP 502/503 responses. UI displays a neutral message: "Notice: Otter networks are currently experiencing brief syncing updates. Your financial data will automatically reconcile as third-party platform connection status stabilizes."

* Tier 3: Internal System Errors: Triggers on core infrastructure code breaks or S3 storage blocks. These logs are hidden from the user interface and routed directly to internal engineering alert loops.

### 5.3 Data Quality Trust Gates
dbt test assertions must evaluate production assets prior to materialization:

* Null Constraints: Primary revenue variables (gross_order_value, net_payout_margin) cannot contain null states. Detections default to 0.00 while flagging an administrative anomaly row.

* Entity Uniqueness: Enforces composite primary constraint verification tracking order_id + source_marketplace to completely eliminate double-counting vectors.

## 6. Core Analytics & Dashboard Specification (Streamlit UI)
### 6.1 Interactive Recipe Cost & COGS Configuration Matrix
* Functional Component: A specialized data editor view within Streamlit allowing restaurant owners to review their live menu items fetched via the Otter API and input/edit raw ingredient and packaging base costs.

* Persistence Logic: Inputs save directly to the relational merchant_cogs table, triggering an incremental dbt model run to instantly recalculate historical and current profit margins.

### 6.2 Executive Financial KPI Summary Blocks
* True Net Profit Margin Card: Displays actualized cash collections from the bank minus raw food costs and marketplace fees.

* Blended Commission Impact: Total Marketplace Commissions / Total Gross Sales Volume expressed as a unified percentage.

* Discovered Settlement Variances: Highlights discrepancies where marketplace payouts fall short of actual sales tallies, providing a direct target for financial reclamation.

### 6.3 Core Analytical Charts
Chart 1: True Omnichannel Profit Leakage Tracker
* Visual Type: Grouped Horizontal Bar Layout.

* Metrics: Y-Axis maps ordering distribution streams (UberEats vs. Rappi vs. DoorDash via Otter); X-Axis measures financial totals.

* Data Series: Gross Consumer Cost vs. Actual Marketplace Payout vs. True Net Profit (After COGS).

* Value Metric: Visually exposes which ordering channels consume excessive margin via commission fees and operational deductions.
 ```
Plaintext
                  [ Gross Sales ] 🟩🟩🟩🟩🟩🟩🟩🟩 $10,000
UberEats --------| [ Net Payout  ] 🟪🟪🟪🟪🟪 $6,500
                  [ True Profit ] 🟦🟦🟦 $3,000  <-- (After subtracting $3,500 COGS)

```
Chart 2: Menu Engineering Matrix (The Strategic Pricing Map)
* Visual Type: Sorted Horizontal Bar Chart split across a target profit margin baseline indicator.

* Metrics: Y-Axis contains discrete menu listings; X-Axis shows Net Profit per item.

* Value Metric: Isolates popular items whose profit margins are crushed by marketplace commissions. Tells the independent restaurant owner exactly which item prices they must adjust upward on delivery apps to remain viable.

Chart 3: Payout Reconciliation Audit Log
Visual Type: Tabular Exception Matrix accompanied by a status flag column.

* Metrics: Groups order sequences by settlement date, identifying marketplace discrepancies where the actualized payment does not align with the original order value.

* Value Metric: Provides independent operators with a clear audit list they can send directly to marketplace provider support channels to claim missing revenue.

### 6.4 Onboarding & Configuration UI Portal
* One-Click Authorization Wizard: A step-by-step connection manager featuring an input field to accept the merchant's Otter environment tokens.

* Connection Micro-Indicators: Visual status indicators next to platform profiles (e.g., green for Active Integration Mode, red for Action Required).

* Template Support Dispatcher: A fallback mechanism providing ready-to-send support text markdown for users whose middleware packages require out-of-band ecosystem permissions.

## 7. Integration & Local Testing Strategy
Because access to live multi-tenant production tokens is constrained during development, the data pipeline engine must implement a decoupled mock layer for continuous testing.

### 7.1 Local Network Layer Mocking
The python testing framework must leverage requests-mock or responses to intercept network operations targeting the Otter endpoint structure (api.tryotter.com/v1/*).

* Fixture Generation: True schema examples of Otter API outputs for /orders and /reports must be maintained locally as static JSON files within a /tests/fixtures/ project path.

* Assertion Targets: Test cases must assert that parsing mechanisms successfully unpack deep nested array components into target flat rows without truncating variations.

### 7.2 Resilience & State Loop Simulation
Testing suites must intentionally trigger external API edge behaviors to evaluate pipeline durability under structural friction:

* Token Refresh Invalidation: Force the mock target to serve an HTTP 401 response code. Assert that the core loop intercepts the trace, reads the relational PostgreSQL refresh key, issues an update call to the authentication endpoint, re-saves keys to storage, and accurately fulfills the primary ingestion block.

* Backoff Throttling: Program mock routines to fire HTTP 429 status values accompanied by custom reset time windows. The ingestion runner must prove execution of accurate exponential pauses instead of hard-failing system routines.