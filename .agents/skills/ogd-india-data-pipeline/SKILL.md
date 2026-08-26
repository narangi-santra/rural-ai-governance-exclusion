---
name: ogd-india-data-pipeline
description: >-
  Runbook and procedures for querying, filtering, and aggregating datasets from India's
  Open Government Data portal (data.gov.in / api.data.gov.in) and handling large-scale
  state-partitioned government data feeds.
---

# OGD India Data Ingestion & Processing

## Key Query Patterns

1. **Always Check Exposed/Mandatory Fields**:
   - Inspect resource metadata JSON (`field_exposed`) before issuing bulk queries.
   - If `state` or another field has `"mandatory": true`, include `filters[state]=<StateName>` in queries to avoid `502 Bad Gateway` and database crashes on the government portal.

2. **Pagination & Query Parameters**:
   - `api-key`: User OGD API key (read from `DATA_GOV_IN_API_KEY` environment variable).
   - `format`: `json`
   - `offset`: Record index offset.
   - `limit`: Number of records (use 50–100 per request to avoid gateway timeouts).
   - `filters[state]`: Target state name (e.g. `Jharkhand`, `Bihar`, `Uttar Pradesh`).

3. **Handling Server Latencies & Downtime**:
   - Set request timeout to 60–120 seconds.
   - Implement exponential retry backoff (e.g., 2s, 4s, 8s) on timeout.
   - Provide an offline `--mock` fallback for testing without external network dependencies.
   - If REST API fails repeatedly due to server load, download the static CSV export directly from the data.gov.in dataset page.

4. **District-Month Aggregation**:
   - When ingesting PIN-code or transaction level feeds, aggregate numeric metrics (e.g., `age_0_5`, `age_5_17`, `age_18_greater`) grouped by `(state, district, date)`:
     ```python
     district_df = (
         raw_df.groupby(["state", "district", "date"])[["age_0_5", "age_5_17", "age_18_greater"]]
         .sum()
         .reset_index()
     )
     ```
