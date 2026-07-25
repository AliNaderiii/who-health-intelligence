# WHO Global Health Intelligence Platform

**Public Health Data Engineering, Epidemiological Analytics, and Interactive Business Intelligence**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Streamlit Cloud](https://img.shields.io/badge/deploy-Streamlit%20Cloud-red.svg)](https://streamlit.io/cloud)

> **Scope statement:** This repository is a **public health data engineering and analytics platform** for WHO Global Health Observatory (GHO) indicators. It is **not a validated AI prediction system**, forecasting product, clinical decision-support tool, or medical diagnostic system. It provides descriptive analytics, data quality monitoring, and interactive business intelligence.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Data Source](#data-source)
- [Official Indicator Definitions](#official-indicator-definitions)
- [LIVE Mode](#live-mode)
- [DEMO Mode](#demo-mode)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Local Execution](#local-execution)
- [Pipeline Execution](#pipeline-execution)
- [Dashboard Execution](#dashboard-execution)
- [Refresh Behavior](#refresh-behavior)
- [Database Schema](#database-schema)
- [Data Quality Report](#data-quality-report)
- [Deployment to Streamlit Community Cloud](#deployment-to-streamlit-community-cloud)
- [Data Freshness Behavior](#data-freshness-behavior)
- [Limitations](#limitations)
- [Responsible Use Disclaimer](#responsible-use-disclaimer)
- [Testing Instructions](#testing-instructions)
- [License](#license)

---

## Project Overview

The **WHO Global Health Intelligence Platform** is an open-source production deployment that retrieves **real data** from the WHO Global Health Observatory (GHO) OData API, validates, transforms, stores in SQLite with idempotent semantics, generates comprehensive data quality reports, and visualizes via Streamlit.

**Key production guarantees:**
- Default deployment mode is **LIVE** (`WHO_DATA_MODE=live`), never silently uses synthetic data
- **DEMO mode** requires explicit `WHO_DATA_MODE=demo`, UI shows banner `DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS`
- If LIVE API fails and no cached real snapshot exists: dashboard stops gracefully, shows clear error, failed API status, how to fix, no synthetic data displayed
- If cached real snapshot exists when LIVE fails: may be used as **STALE REAL DATA** fallback, clearly labeled with original extraction timestamp and failure reason
- Never mixes synthetic with live data
- Every real extraction generates `reports/data_quality_report.json` and stores report in DB table `data_quality_results`
- Status panel shows data mode, API status, last extraction, source, records, countries, year range, quality status with colors: Green live healthy, Amber stale cached, Red failed

---

## Architecture

```
WHO GHO OData API (https://ghoapi.azureedge.net/api/)
        │
        ▼
API Client (requests.Session, retry, exponential backoff, timeout, pagination, validation)
        │ logs every attempt, status, records, duration, latency
        ▼
ETL Transform (schema validation, type coercion, geography enrichment via pycountry/ISO)
        │
        ▼
SQLite (health_indicators + etl_metadata + indicator_definitions + source_info + data_quality_results)
        │ idempotent, unique constraints, transactions, atomic writes
        ▼
Dashboard Services (filtering, KPIs, analytical views, data mode status)
        │
        ▼
Streamlit Dashboard (choropleth, ranking, trend, comparison, country profile, distribution, association, explorer, CSV download)
        │
        ▼
Data Quality Reports (reports/data_quality_report.json + DB)
```

### Separation of concerns
- `src/who_health_intelligence/api/client.py` — production WHO GHO API client
- `src/who_health_intelligence/etl/` — transform, metadata, loader, quality, pipeline
- `src/who_health_intelligence/dashboard/services.py` — all data logic, testable without Streamlit
- `src/who_health_intelligence/dashboard/app.py` — UI orchestration only
- `src/who_health_intelligence/utils/config.py` — centralized config, env vars, official indicator definitions
- `src/who_health_intelligence/utils/data_mode.py` — LIVE/DEMO/STALE handling

---

## Data Source

| Source | Description | Endpoint | Documentation |
|---|---|---|---|
| WHO Global Health Observatory (GHO) OData API | WHO-published global health indicator data, 2000+ indicators, 194 member states | `https://ghoapi.azureedge.net/api/` (configurable via `WHO_API_BASE_URL`) | https://www.who.int/data/gho/info/gho-odata-api |

- **Current endpoint validated:** `https://ghoapi.azureedge.net/api/` — verified as documented in WHO official docs and as of April 2026 community guides still actively used. Base URL is configurable via `WHO_API_BASE_URL` for forward compatibility with upcoming World Health Data Hub OData API announced for end 2025.
- WHO data may be revised over time. Results depend on extraction date, selected indicators, API availability.
- No authentication required for public GHO data.

---

## Official Indicator Definitions

Validated against WHO Data Hub official metadata.

### LIFE_EXPECTANCY — `WHOSIS_000001`

- **Short:** Life expectancy at birth (years)
- **Official definition:** The average number of years that a newborn could expect to live, if he or she were to pass through life exposed to the sex- and age-specific death rates prevailing at the time of his or her birth, for a specific year, in a given country, territory, or geographic area.
- **Unit:** years
- **Source URL:** https://data.who.int/indicators/i/A21CFC2/90E2E48
- **WHO OData URL:** https://ghoapi.azureedge.net/api/WHOSIS_000001

### NCD_MORTALITY — `NCDMORT3070` (SDG 3.4.1)

- **Short:** Probability of premature death from major non-communicable diseases
- **Accurate wording (per spec, not only cardiovascular):** Probability of premature death from major non-communicable diseases — percentage of 30-year-old people who would die before their 70th birthday from any of cardiovascular disease, cancer, diabetes, or chronic respiratory disease, assuming current mortality rates and no other causes of death.
- **Official definition:** The percentage of 30-year-old people who would die before their 70th birthday from any of cardiovascular disease, cancer, diabetes, or chronic respiratory disease, assuming that they would experience current mortality rates at every age and they would not die from any other cause of death (e.g., injuries or HIV/AIDS).
- **Unit:** %
- **Source URL:** https://data.who.int/indicators/i/C540135/1F96863
- **WHO OData URL:** https://ghoapi.azureedge.net/api/NCDMORT3070

### UHC_COVERAGE — `UHC_INDEX_REPORTED` (SDG 3.8.1)

- **Short:** Universal Health Coverage service coverage index
- **Official definition:** The coverage of essential health services (defined as the average coverage of essential services based on tracer interventions that include reproductive, maternal, newborn and child health, infectious diseases, non-communicable diseases and service capacity and access, among the general and the most disadvantaged population). The indicator is an index reported on a unitless scale of 0 to 100, which is computed as the geometric mean of 14 tracer indicators of health service coverage.
- **Unit:** index (0-100)
- **Source URL:** https://data.who.int/indicators/i/3805B1E/9A706FD
- **WHO OData URL:** https://ghoapi.azureedge.net/api/UHC_INDEX_REPORTED

Indicator metadata stored in DB table `indicator_definitions` containing: indicator name, code, official definition, unit, WHO source URL, extraction timestamp, pipeline version.

If indicator code invalid/unavailable: marked as failed, continue with other valid indicators, show failure clearly in dashboard, not silently removed.

---

## LIVE Mode

**Default deployment mode.**

```bash
WHO_DATA_MODE=live python who_etl_pipeline.py
WHO_DATA_MODE=live python main.py etl
WHO_DATA_MODE=live streamlit run src/who_health_intelligence/dashboard/app.py
```

- Retrieves real WHO GHO data via production API client
- Validates API base URL (`https://ghoapi.azureedge.net/api/`)
- Validates each indicator endpoint
- Uses `requests.Session`, configurable timeout, retry logic, exponential backoff
- Handles HTTP 4xx/5xx, connection errors, malformed JSON, missing response keys (`value`)
- Supports pagination (`$skip/$top` and `@odata.nextLink`)
- Logs every extraction attempt, response status, number records retrieved, extraction duration, API latency
- Avoids excessive API calls (rate limiting, configurable TTL)

**Failure handling:**
- If LIVE fails and no previously cached real snapshot exists: stop dashboard gracefully, show clear error message, failed API status, explain how to fix, do **not** display synthetic data
- If previously fetched real snapshot exists: may be used as stale fallback, clearly labeled **STALE REAL DATA**, show original extraction timestamp and API failure reason
- Never mixes synthetic with live

**Environment variables:**

```bash
WHO_DATA_MODE=live
WHO_API_BASE_URL=https://ghoapi.azureedge.net/api/
WHO_API_TIMEOUT=30
WHO_API_MAX_RETRIES=3
WHO_REFRESH_TTL=3600
WHO_DB_PATH=data/who_health_data.db
```

See `.env.example` and `src/config.py`.

---

## DEMO Mode

**For local development and testing only. Must be explicitly enabled.**

```bash
WHO_DATA_MODE=demo python scripts/bootstrap_data.py
WHO_DATA_MODE=demo python main.py etl --demo
WHO_DATA_MODE=demo streamlit run src/who_health_intelligence/dashboard/app.py
```

- Generates synthetic bootstrap data matching WHO statistical profiles
- UI visibly shows: **DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS** with warning colors
- Requires explicit `WHO_DATA_MODE=demo` env var — if not set, script exits with error (never silent)
- Never allows demo to be mistaken for live production data
- Never mixed with live data

**Synthetic data disclaimer:** Development/demo data, not official WHO observations, for testing offline environments.

---

## Installation

```bash
git clone https://github.com/AliNaderiii/who-health-intelligence.git
cd who-health-intelligence
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies include `pycountry` for reliable ISO 3166 country metadata (not only Plotly Gapminder).

---

## Environment Variables

| Variable | Purpose | Default | Required |
|---|---|---|---|
| `WHO_DATA_MODE` | Data mode: `live` (default) or `demo` (explicit) | `live` | No, but demo must be explicit |
| `WHO_API_BASE_URL` | WHO GHO API base URL | `https://ghoapi.azureedge.net/api/` | No |
| `WHO_API_TIMEOUT` | Request timeout seconds | `30` | No |
| `WHO_API_MAX_RETRIES` | Max retry attempts | `3` | No |
| `WHO_REFRESH_TTL` | Streamlit cache TTL seconds | `3600` | No |
| `WHO_DB_PATH` | SQLite database path | `data/who_health_data.db` | No |
| `WHO_DATA_DIR` | Base data directory | `data/` | No |
| `LOG_LEVEL` | Logging level | `INFO` | No |

Legacy aliases still supported: `WHO_REQUEST_TIMEOUT`, `WHO_RETRY_COUNT`.

No secrets required for public WHO GHO API.

Example `.env.example` provided.

---

## Local Execution

```bash
# Set PYTHONPATH
export PYTHONPATH=src:.

# LIVE mode ETL (real WHO data)
WHO_DATA_MODE=live python main.py etl
# or
WHO_DATA_MODE=live python who_etl_pipeline.py

# Validate API endpoints
python main.py validate-api

# Show database info and schema validation
python main.py info
# or
python main.py info --db data/who_health_data.db

# DEMO mode (explicit)
WHO_DATA_MODE=demo python scripts/bootstrap_data.py
WHO_DATA_MODE=demo python main.py etl --demo

# Generate notebook
python main.py notebook
# or
python scripts/generate_notebook.py
```

---

## Pipeline Execution

### Package CLI

```bash
WHO_DATA_MODE=live python main.py etl
WHO_DATA_MODE=live python main.py etl --indicators LIFE_EXPECTANCY NCD_MORTALITY UHC_COVERAGE
WHO_DATA_MODE=live python main.py etl --quality-report data/quality_report.md
```

### Standalone ETL CLI

```bash
WHO_DATA_MODE=live python who_etl_pipeline.py
WHO_DATA_MODE=live python who_etl_pipeline.py --indicator NCD_MORTALITY UHC_COVERAGE
WHO_DATA_MODE=live python who_etl_pipeline.py --db-path data/who_health_data.db --quality-report data/quality_report.md
WHO_DATA_MODE=demo python who_etl_pipeline.py --demo  # synthetic demo
```

Exit codes: 0 success, 1 general failure, 2 no data extracted, 3 validation failure.

Pipeline features idempotency: repeated execution does not create duplicate records (unique constraints + upsert logic + transactions + atomic writes via safe temp DB replacement where appropriate).

---

## Dashboard Execution

```bash
# CLI launcher (LIVE default)
WHO_DATA_MODE=live python main.py dashboard
WHO_DATA_MODE=live python main.py dashboard --port 8501

# Direct Streamlit
WHO_DATA_MODE=live streamlit run src/who_health_intelligence/dashboard/app.py

# DEMO mode
WHO_DATA_MODE=demo streamlit run src/who_health_intelligence/dashboard/app.py
```

### Dashboard Features

Top visible status panel (required):
- Data mode: LIVE / DEMO / STALE REAL DATA with colors: Green live healthy, Amber stale cached, Red failed/unavailable
- API status: Online / Failed / Partial
- Last successful extraction time
- Data source
- Number records, countries, year range, data-quality status

Additional:
- Refresh Data button: triggers real API refresh, shows progress, reports success/failure, displays extraction timestamp, clears Streamlit caches, never creates duplicate records
- Streamlit caching with configurable TTL via `WHO_REFRESH_TTL`
- Global choropleth map (unweighted regional averages noted)
- Country ranking
- Time-series trends (unweighted country-level average)
- Indicator comparison
- Country profile
- Distribution analysis
- Association/correlation analysis labeled as **Descriptive association, not causal inference** with non-causal warning, sample size, method, missing handling, selected year/indicator
- Data explorer + CSV download
- Uses **Automated Analytical Summary** and **Data-Driven Observation** wording, not AI Insight (only use AI term if real validated ML model exists)
- Clearly distinguishes unweighted average across reporting countries vs population-weighted average only if population data available; shows unweighted country-level average when population not available
- Shows mapping coverage: total countries, mapped, unmapped, mapping coverage percentage

---

## Refresh Behavior

- Refresh button triggers real WHO API extraction via `WHOETLPipeline`
- Shows progress spinner, reports API success/failure, displays extraction timestamp
- Clears Streamlit cache (`st.cache_data.clear()`) and reruns
- Never creates duplicate records due to idempotent loader (delete-then-insert per indicator with transaction)
- In LIVE mode, if refresh fails and no cached snapshot, dashboard shows error and stops gracefully, no synthetic displayed
- If cached real snapshot exists, refresh failure uses **STALE REAL DATA** fallback with timestamp and failure reason

TTL: `WHO_REFRESH_TTL` default 3600 seconds controls Streamlit cache TTL to avoid fetching entire API for every widget interaction.

---

## Database Schema

Explicit schema with at least `health_indicators` containing per spec: country_code, country_name, continent, year, gender, indicator, value, unit, source, extracted_at, pipeline_version. Also legacy CamelCase columns for backward compatibility.

### `health_indicators`

```
id INTEGER PRIMARY KEY AUTOINCREMENT
country_code TEXT NOT NULL (ISO Alpha-3, via pycountry or internal WHO mapping)
country_name TEXT
continent TEXT
year INTEGER NOT NULL
gender TEXT NOT NULL (Both sexes/Male/Female)
indicator TEXT NOT NULL (e.g., LIFE_EXPECTANCY)
indicator_code TEXT NOT NULL (e.g., WHOSIS_000001)
value REAL NOT NULL
unit TEXT (years, %, index 0-100, etc.)
source TEXT (WHO GHO OData API + URL)
extracted_at TIMESTAMP (UTC)
pipeline_version TEXT
-- Legacy columns for dashboard compatibility:
CountryCode, Country, Year, Gender, Indicator, IndicatorCode, IndicatorDescription, Value, Continent, SourceTimestamp
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
UNIQUE(country_code, year, gender, indicator, indicator_code)
Indexes on indicator, country, year, continent, composite
```

### `etl_metadata`

```
id, run_timestamp, indicator, indicator_code, records_extracted, records_loaded, records_replaced, status, duration_seconds, pipeline_version, source_url, notes
```

### `indicator_definitions`

```
indicator_name PRIMARY KEY, indicator_code UNIQUE, description, official_definition, short_definition, unit, source_url, who_odata_url, category, extraction_timestamp, pipeline_version
```

Fields per spec: Indicator name, code, official definition, unit, WHO source URL, extraction timestamp, pipeline version.

### `source_info`

```
id, extraction_timestamp, source_name, source_url, pipeline_version, total_records_extracted, total_records_loaded, indicators_extracted, status, notes
```

### `data_quality_results`

```
id, extraction_timestamp, data_mode, api_status, indicator_status (JSON), raw_records, processed_records, countries, years, year_range (JSON), missing_values, invalid_numeric, duplicate_rows, duplicate_key_groups, unmapped_countries (JSON), out_of_range_values, indicator_coverage (JSON), api_latency_seconds, total_duration_seconds, overall_score, report_json (JSON), created_at
```

Pipeline idempotency via unique constraints, upsert logic, transactions, atomic writes, safe temporary database replacement (`loader.atomic_replace_database()`).

Do not commit synthetic data as if official WHO data.

---

## Data Quality Report

Every real extraction generates comprehensive report.

**Report includes:**
- Extraction timestamp in UTC
- API response status
- Indicator status (per indicator success/failed, record counts, latency)
- Number raw records, processed records, countries, years, year range
- Missing values, invalid numeric values, duplicate rows, duplicate key groups, unmapped countries, out-of-range values, indicator coverage, API latency, total extraction duration
- Additional: overall score, verification status, mapping coverage, quality issues

**Saved as:**
- `reports/data_quality_report.json` (required path, per spec)
- Also stored in DB table `data_quality_results` latest
- Export via `loader.export_quality_report_json()`
- Markdown report optionally via `python main.py quality`

**Thresholds:**
- Overall score >=80 and no critical issues => verified
- Score <50 or critical issues => warnings
- Score <30 => fail (pipeline exit code 3)
- Missing values >5% threshold triggers warning

Do not label data as verified unless quality checks passed.

Example JSON structure:

```json
{
  "extraction_timestamp_utc": "2026-05-13T12:34:56Z",
  "data_mode": "live",
  "api_status": "Online",
  "indicator_status": {
    "LIFE_EXPECTANCY": {"status": "success", "record_count": 5000},
    "NCD_MORTALITY": {"status": "success", "record_count": 4000}
  },
  "raw_records": 9000,
  "processed_records": 8500,
  "countries": 194,
  "years": 24,
  "year_range": [2000, 2023],
  "missing_values": 0,
  "invalid_numeric": 0,
  "duplicate_rows": 0,
  "duplicate_key_groups": 0,
  "unmapped_countries": {"count": 0, "codes": []},
  "out_of_range_values": 0,
  "indicator_coverage": {...},
  "api_latency_seconds": 12.3,
  "total_duration_seconds": 45.6,
  "overall_score": 95.0,
  "is_verified": true
}
```

---

## Deployment to Streamlit Community Cloud

### Files

- `requirements.txt` — includes `pycountry`, `streamlit`, `plotly`, `pandas`, `requests`, `statsmodels`, `nbformat`, `pytest`
- `.streamlit/config.toml` — theme, server headless, CORS disabled, usage stats disabled, max upload 200
- `.env.example` — documents all env vars
- `README.md` — this file

### Streamlit Cloud Configuration

1. Connect repository `AliNaderiii/who-health-intelligence` to Streamlit Cloud
2. Main file path: `src/who_health_intelligence/dashboard/app.py`
3. Python version: 3.9+
4. Environment variables (via Streamlit Cloud secrets or env):
   ```
   WHO_DATA_MODE=live
   WHO_API_BASE_URL=https://ghoapi.azureedge.net/api/
   WHO_API_TIMEOUT=30
   WHO_API_MAX_RETRIES=3
   WHO_REFRESH_TTL=3600
   WHO_DB_PATH=data/who_health_data.db
   ```
5. No secrets required for public WHO GHO API

### SQLite Persistence Limitation on Streamlit Cloud

**Important:** Streamlit Community Cloud's local filesystem is ephemeral. SQLite file `data/who_health_data.db` is **not persistent** across deploys/reboots. On each app start or Streamlit Cloud sleep/wake, the database may be empty.

**Current deployment handling:**
- Dashboard attempts real WHO API extraction on refresh (if network allows from Cloud)
- If API fails and no cached snapshot, shows graceful error with fix instructions, no synthetic data
- For demo purposes, a real API snapshot with extraction timestamp should be committed or generated via CI, clearly showing timestamp

**Recommended next steps for persistent production storage:**
- **PostgreSQL** — e.g., Supabase, Neon, AWS RDS
- **Supabase** — PostgreSQL + storage, Streamlit integration docs
- **S3-compatible object storage** — store `data_quality_report.json` and DB snapshots, load on startup
- **Managed database** — e.g., Streamlit's support for external DB via secrets.toml

Document this limitation clearly in dashboard methodology panel (implemented).

For now, deployment uses real API snapshot and clearly shows extraction timestamp in status panel.

---

## Data Freshness Behavior

- Extraction timestamp UTC shown in status panel and quality report
- Dashboard caching TTL via `WHO_REFRESH_TTL` (default 3600s) avoids repeated API calls per widget interaction
- Refresh button triggers real API refresh, shows progress, reports success/failure, displays new timestamp, clears caches
- If LIVE API fails:
  - No cached real snapshot: stop gracefully, red failed panel, error message, API status, how to fix, no synthetic
  - Cached real snapshot exists: label **STALE REAL DATA** amber panel, show original extraction timestamp, API failure reason, suggest retry
- DEMO mode: yellow banner with explicit synthetic disclaimer

---

## Limitations

- This project is descriptive analytics software, **not a validated AI prediction system**
- Correlation does not imply causation — all association views labeled as descriptive association, not causal inference
- Country averages are **unweighted country-level averages** (each country equal weight). Population-weighted averages require population data, not currently included. If population data integrated, will be clearly labeled
- WHO data may contain missing values, reporting gaps, methodological changes, revisions
- Indicator definitions and units must be checked against WHO official source before external use
- API availability and SSL/network config can affect live extraction
- Gender, age, geographic disaggregation availability varies by indicator
- Country and territory mappings may not cover every WHO reporting entity; unmapped tracked in quality report, mapping coverage % shown in dashboard
- Sample/bootstrap data is for development and demonstration only, explicitly requires `WHO_DATA_MODE=demo`
- Dashboard is **not a medical decision-support tool**, not for clinical decisions
- SQLite not persistent on Streamlit Cloud — see deployment section

---

## Responsible Use Disclaimer

**Medical Disclaimer:**

- This dashboard is **not a medical decision-support tool**.
- It must **not be used for clinical diagnosis or treatment decisions**.
- WHO data may be revised.
- Reporting gaps may exist.
- Country comparisons may be affected by methodology and availability.
- **Correlation does not imply causation**.
- The dashboard provides analytical context, not medical advice.

**Correlation vs Causation:**

- All correlation/association analyses are **descriptive associations** only.
- Show sample size (number of countries), correlation method (Pearson), missing-value handling (pairwise deletion), selected year, selected indicator, clear non-causal warning.
- Observed correlations may be driven by shared confounders (e.g., GDP, healthcare investment) and should not be interpreted as causal relationships.

**Ethics:**

- Interpret trends with attention to reporting practices, data completeness, uncertainty
- Avoid causal claims from descriptive charts or correlations alone
- Document extraction dates, indicator definitions, filters, aggregation methods
- Avoid stigmatizing countries, regions, populations, health systems based on incomplete data
- Consult domain experts and official WHO metadata before using results in reports, policy, operational planning

---

## Testing Instructions

```bash
export PYTHONPATH=src:.
pytest tests/ -v
pytest tests/test_etl.py -v
pytest tests/test_services.py -v
pytest tests/test_data_quality.py -v
```

### Test Coverage (per spec)

Tests cover (mocked API, no live WHO calls for test suite):
- Successful API response
- API timeout
- API retry
- HTTP 4xx, 5xx
- Malformed JSON
- Missing response keys
- Pagination
- Invalid indicator
- Empty response
- Missing values, invalid numeric values, duplicate rows, duplicate key prevention
- Country mapping (pycountry + internal fallback)
- Data-quality thresholds, SQLite transaction behavior, idempotent repeated loading
- Live mode failure, demo mode explicit activation, stale real-data fallback, no silent synthetic fallback
- Dashboard data-status logic

Unit tests mock API requests via `unittest.mock`.

**Run complete suite before committing:**

```bash
pytest tests/ -v --tb=short
python -m py_compile src/who_health_intelligence/**/*.py
WHO_DATA_MODE=demo python scripts/bootstrap_data.py  # explicit demo
WHO_DATA_MODE=demo python -m pytest tests/test_etl.py -k demo -v  # demo behavior
```

---

## Notebook

Generated via `python scripts/generate_notebook.py` or `python main.py notebook`.

Notebook uses same reusable source modules as production pipeline:
- Connects to real WHO API when LIVE mode enabled
- Supports SAMPLE or DEMO mode explicitly
- Shows extraction timestamp, source URL, indicator definitions, transformation steps, data-quality results, database loading, limitations, avoids fabricated results, uses relative paths, valid nbformat 4

Validate with:

```python
import nbformat
nb = nbformat.read("WHO_Data_Extraction_ETL.ipynb", as_version=4)
nbformat.validate(nb)
```

---

## Project Positioning

**WHO Global Health Intelligence Platform — Public Health Data Engineering, Epidemiological Analytics, and Interactive Business Intelligence.**

Not described as AI prediction system.

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Author

**Ali Naderi** — Repository: https://github.com/AliNaderiii/who-health-intelligence — Focus: public health data engineering, epidemiological analytics, interactive business intelligence

---

## Attribution

Data source attribution belongs to **World Health Organization Global Health Observatory**. This repository is independent open-source software and does not imply WHO endorsement.

API endpoint used: `https://ghoapi.azureedge.net/api/` (validated, configurable via `WHO_API_BASE_URL`). Indicator codes used: `WHOSIS_000001` (Life expectancy), `NCDMORT3070` (Probability of premature death from major NCDs), `UHC_INDEX_REPORTED` (UHC coverage index).

Live extraction test result: endpoint validated via `python main.py validate-api` — shows reachable status and per-indicator validation (actual live HTTP depends on network; mocked in tests).

Known limitations documented above: Streamlit Cloud SQLite ephemerality, WHO data revisions, reporting gaps, unweighted averages, correlation not causation, not medical decision-support.

---

## Deployment Instructions Summary

1. Set env vars: `WHO_DATA_MODE=live`, `WHO_API_BASE_URL`, `WHO_API_TIMEOUT=30`, `WHO_API_MAX_RETRIES=3`, `WHO_REFRESH_TTL=3600`, `WHO_DB_PATH`
2. Install: `pip install -r requirements.txt`
3. Validate API: `python main.py validate-api`
4. ETL LIVE: `WHO_DATA_MODE=live python main.py etl`
5. Dashboard: `WHO_DATA_MODE=live streamlit run src/who_health_intelligence/dashboard/app.py`
6. For Streamlit Cloud: connect repo, set main file, set env vars in secrets, note SQLite non-persistent, consider PostgreSQL/Supabase/S3 for persistence
7. Data quality report: `reports/data_quality_report.json` and DB table `data_quality_results`
8. Refresh button in dashboard triggers real API refresh, shows progress, clears cache, no duplicates
