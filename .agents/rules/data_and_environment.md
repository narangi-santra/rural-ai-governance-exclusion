# Data Collection & Environment Guidelines

## 1. Government API Querying & Resilience
- **Mandatory Partition Indexing**: When querying `data.gov.in` (OGD Platform India) or other large government endpoints (multi-million record catalogs like Aadhaar monthly enrolment), never execute unindexed full-table queries. Always pass exposed partition filters (e.g. `filters[state]=...`) to prevent `502 Bad Gateway` and reverse-proxy memory exhaustion.
- **Client Resilience Standards**: All data ingestion scripts interfacing with government portals must implement:
  - Configurable `--timeout` (default ≥ 60s).
  - Manageable `--batch-size` (default 50–100 per request).
  - Automatic exponential retry backoff on `requests.Timeout` and `requests.ConnectionError`.
  - Built-in `--mock` data generator for reliable offline development, testing, and continuous integration.

## 2. macOS Environment & Library Compatibility
- **LibreSSL vs urllib3 v2**: If scripts might be run using macOS system Python (`/usr/bin/python3`), filter `NotOpenSSLWarning` prior to importing `requests` or `urllib3`:
  ```python
  import warnings
  warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")
  ```
- **Virtual Environment**: Prefer executing scripts inside the repository's dedicated virtual environment (`venv/bin/python`) which uses modern OpenSSL 3.x.

## 3. Unit of Analysis & Ethical Framing
- **District-Month Granularity**: In welfare authentication and exclusion modeling, maintain the **district-month** unit of analysis (~700 districts × available months).
- **Administrative Diagnostic Framing**: Position models strictly as administrative diagnostic and governance audit tools for policy feedback, not as individual-level scoring mechanisms.
