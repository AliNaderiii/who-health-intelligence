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
│   │   └── app.py                 # Interactive analytics UI
│   ├── utils/                      # Shared utilities
│   │   └── config.py              # Configuration management
│   └── tests/                      # Unit tests
├── tests/                          # Integration tests
├── scripts/                        # Utility scripts
├── notebooks/                      # Jupyter analysis notebooks
├── data/                           # SQLite database (generated)
├── logs/                           # ETL pipeline logs
├── main.py                         # CLI entry point
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

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
# Extract and load all default indicators
python main.py etl

# Extract specific indicators
python main.py etl --indicators NCD_MORTALITY UHC_COVERAGE LIFE_EXPECTANCY

# Generate quality report
python main.py quality --output data/quality_report.md
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

The interactive Streamlit dashboard provides:

### 🗺️ Geographic Analysis
- Choropleth maps of health indicators by country
- Country rankings and continental summaries

### 📈 Temporal Trends
- Time-series analysis with confidence intervals
- Multi-country trend comparison

### 👥 Demographic Analysis
- Gender-based comparisons
- Demographic breakdown by indicator

### 🔗 Cross-Indicator Correlation
- Scatter plots with trend lines
- Pearson correlation coefficients

### 📋 Data Explorer
- Filterable data tables
- Summary statistics
- CSV export

### ℹ️ Methodology
- Transparent data source documentation
- Processing pipeline description
- Limitations and caveats

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
# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_transform.py -v
pytest tests/test_schema.py -v
pytest tests/test_loader.py -v
pytest tests/test_quality.py -v
pytest tests/test_metadata.py -v
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
