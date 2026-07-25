# 🏥 WHO Global Health Intelligence Platform

### Public Health Data Engineering, Epidemiological Analytics & Interactive Business Intelligence

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Overview

A **production-oriented public health data platform** that extracts, validates, transforms, and visualizes epidemiological data from the World Health Organization (WHO) Global Health Observatory (GHO).

This platform provides:

- **Robust API extraction** from the WHO GHO OData API with retry logic and error handling
- **Clean ETL pipeline** with schema validation and idempotent database loading
- **Data quality monitoring** with completeness, consistency, and accuracy metrics
- **Interactive analytics dashboard** built with Streamlit and Plotly
- **Geographic, temporal, demographic, and cross-indicator analysis**
- **Transparent methodology** with clear documentation of limitations

> **Important:** This is a **descriptive analytics platform**. It does **not** contain validated predictive models or claim AI/ML capabilities. All analyses show observed patterns in data, not predictions.

---

## Architecture

```
who-health-intelligence/
├── src/who_health_intelligence/    # Main package
│   ├── api/                        # WHO GHO API client
│   │   └── client.py              # HTTP extraction with retry logic
│   ├── etl/                        # ETL pipeline
│   │   ├── pipeline.py            # Main orchestrator
│   │   ├── transform.py           # Data transformation
│   │   ├── schema.py              # Schema validation
│   │   ├── loader.py              # SQLite persistence
│   │   ├── metadata.py            # Country/continent normalization
│   │   └── quality.py             # Data quality monitoring
│   ├── dashboard/                  # Streamlit dashboard
│   │   ├── services.py            # Data layer (loading, filtering, analysis)
│   │   └── app.py                 # UI orchestration only
│   └── utils/                      # Shared utilities
│       └── config.py              # Configuration management
├── tests/                          # Automated tests (94 tests)
├── scripts/                        # Utility scripts
│   └── bootstrap_data.py          # Development data bootstrap
├── notebooks/                      # Jupyter analysis notebooks
├── data/                           # SQLite database (generated)
├── logs/                           # ETL pipeline logs
├── main.py                         # CLI entry point
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

### Separation of concerns

The dashboard follows strict layering:

- **`services.py`** — All data logic: loading, filtering, KPI computation,
  analytical view builders, quality reporting, metadata. Independent of
  Streamlit so it is testable and reusable.
- **`app.py`** — Pure UI orchestration: layout, filters, chart rendering,
  graceful error handling. No data transformation logic.

---

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/AliNaderiii/who-health-intelligence.git
cd who-health-intelligence

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the ETL Pipeline

```bash
# Extract and load all default indicators (requires WHO API access)
python main.py etl

# Extract specific indicators
python main.py etl --indicators NCD_MORTALITY UHC_COVERAGE LIFE_EXPECTANCY

# Generate quality report
python main.py quality --output data/quality_report.md

# Development / offline: bootstrap with synthetic sample data
python scripts/bootstrap_data.py
```

### 3. Launch the Dashboard

```bash
# Option 1: Via CLI
python main.py dashboard

# Option 2: Direct Streamlit
streamlit run src/who_health_intelligence/dashboard/app.py
```

### 4. Generate Analysis Notebook

```bash
python main.py notebook
```

---

## Data Sources

| Source | Description | URL |
|--------|-------------|-----|
| WHO GHO OData API | Global health indicators | `https://ghoapi.azureedge.net/api/` |

### Available Indicators

| Indicator | API Code | Description |
|-----------|----------|-------------|
| Life Expectancy | `WHOSIS_000001` | Life expectancy at birth (years) |
| NCD Mortality | `NCDMORT3070` | Probability of dying from NCDs ages 30-70 (%) |
| UHC Coverage | `UHC_INDEX_REPORTED` | Universal Health Coverage service index (1-100) |

---

## Dashboard Features

The interactive Streamlit dashboard provides 8 analytical views, a methodology
panel, and a data quality panel. All aggregation uses clearly labeled
**unweighted country-level averages**. Population-weighted averages are
supported in the services layer but require external population data.

### 🗺️ Geographic — Choropleth Map
Interactive world map with per-indicator coloring and unweighted regional
summaries.

### 🏆 Country Ranking
Horizontal bar chart ranking countries by selected indicator value.

### 📈 Temporal Trend
Global time-series with ±1 SD confidence band and per-country trend lines.
Clearly labeled as unweighted country-level means.

### 📊 Indicator Comparison
Side-by-side comparison of multiple indicators across countries via a pivot table.

### 🏳️ Country Profile
Deep-dive into a single country's time-series across all selected indicators.

### 📉 Distribution Analysis
Histograms and box plots showing value distributions by region.

### 🔗 Statistical Association
Scatter plots with OLS trend lines and Pearson *r*. Labeled as **statistical
association, not causation**. Uses the terminology "Data-Driven Observation"
rather than "AI Insight".

### 📋 Data Explorer
Filterable data table, summary statistics, and CSV export.

### Additional panels
- **Methodology** — Data source, extraction date, indicator definitions,
  missing data handling, geographic mapping, aggregation method.
- **Data Quality** — Quality score, completeness per column, temporal coverage.

---

## ETL Pipeline

### Processing Steps

1. **Extract** — HTTP GET from WHO GHO API with exponential backoff retry
2. **Validate** — Schema validation and value range checks per indicator
3. **Transform** — Gender code normalization, type optimization, null handling
4. **Enrich** — Country name and continent metadata mapping (ISO 3166-1)
5. **Load** — Idempotent upsert into SQLite with UNIQUE constraints
6. **Monitor** — Data quality scoring and reporting

### Data Quality

The platform monitors:
- **Completeness:** Null rate tracking per column
- **Consistency:** Duplicate detection and type validation
- **Accuracy:** Value range checks and outlier detection
- **Coverage:** Geographic and temporal completeness

---

## Testing

```bash
# Run all tests (94 tests across 6 modules)
pytest tests/ -v

# Run specific test modules
pytest tests/test_services.py -v    # Dashboard data services (45 tests)
pytest tests/test_transform.py -v   # ETL transform
pytest tests/test_schema.py -v      # Schema validation
pytest tests/test_loader.py -v      # Database loader
pytest tests/test_quality.py -v     # Data quality
pytest tests/test_metadata.py -v    # Country/continent metadata
```

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.9+ |
| Data Processing | Pandas, NumPy |
| API Client | Requests (with urllib3 retry) |
| Database | SQLite (WAL mode) |
| Dashboard | Streamlit |
| Visualization | Plotly |
| Testing | Pytest |
| Notebooks | Jupyter |

---

## Limitations & Caveats

- **Data availability** varies by country, year, and indicator
- **API accessibility** may be limited in some network environments
- **Gender breakdowns** are not available for all indicators
- **Country codes** follow ISO 3166-1 alpha-3; some territories may not be represented
- **Correlation analysis** shows statistical associations only — **not causation**
- **Year-over-year changes** may reflect reporting improvements rather than actual health changes

### No Predictive Claims

This platform is a **public health data engineering and analytics tool**. It does **not** claim to be:
- An AI prediction platform
- A machine learning system
- A validated forecasting tool

Any future predictive capabilities would require proper time-series validation,
evaluation metrics, uncertainty handling, and clear disclosure of experimental status.

---

## CLI Reference

```
python main.py [command] [options]

Commands:
  etl         Run the ETL pipeline
  quality     Generate data quality report
  info        Show database information
  dashboard   Launch Streamlit dashboard
  notebook    Generate analysis notebook

Options:
  --db PATH             Database path (default: data/who_health_data.db)
  --indicators LIST     Indicators to extract (space-separated)
  --no-replace          Append instead of replacing data
  --quality-report PATH Save quality report to file
  --port PORT           Dashboard server port (default: 8501)
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- **Data:** World Health Organization Global Health Observatory (WHO GHO)
- **API:** WHO GHO OData API
- **Visualization:** Plotly, Streamlit

---

## Contributing

This is a data engineering project focused on:
- Clean, testable, modular code
- Transparent methodology
- No fabricated metrics or claims
- Proper attribution of data sources
