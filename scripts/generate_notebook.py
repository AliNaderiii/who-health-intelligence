#!/usr/bin/env python3
"""
WHO Global Health Intelligence Platform — Notebook Generator.

Generates a valid Jupyter Notebook (``WHO_Data_Extraction_ETL.ipynb``)
using the ``nbformat`` library.  The notebook demonstrates the full
ETL pipeline, data quality analysis, and exploratory analytics workflow.

Usage:
    # From repository root
    python scripts/generate_notebook.py

    # Custom output path
    python scripts/generate_notebook.py --output notebooks/WHO_Data_Extraction_ETL.ipynb

The generated notebook:
- Reuses functions from ``src/who_health_intelligence/``
- Uses ``pathlib`` for all file paths
- Supports a ``SAMPLE_MODE`` flag for offline / network-unavailable runs
- Does NOT fabricate results; all displayed data comes from actual execution
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

logger = logging.getLogger(__name__)

# ====================================================================
# Helper functions
# ====================================================================

def _md(source: str) -> nbformat.NotebookNode:
    """Create a markdown cell."""
    return new_markdown_cell(source=source.strip())


def _code(source: str) -> nbformat.NotebookNode:
    """Create a code cell."""
    return new_code_cell(source=source.strip())


def _build_notebook() -> nbformat.NotebookNode:
    """
    Build the full notebook with all 18 required sections.

    Returns:
        A valid nbformat NotebookNode (nbformat 4.5).
    """
    cells: List[nbformat.NotebookNode] = []

    # ----------------------------------------------------------------
    # 1. Project Overview
    # ----------------------------------------------------------------
    cells.append(_md("""# WHO Data Extraction & ETL Pipeline

## 1. Project Overview

This notebook demonstrates the complete data engineering pipeline for the
**WHO Global Health Intelligence Platform** — a production-oriented public
health data platform that extracts, validates, transforms, and loads
epidemiological data from the World Health Organization (WHO) Global Health
Observatory (GHO).

**What this notebook covers:**
- Robust API extraction with retry logic and pagination
- Schema validation and data quality monitoring
- Data transformation with type optimization
- Country and continent metadata normalization
- Idempotent SQLite persistence
- Exploratory data analysis and visualization

**Important:** This notebook presents **descriptive analytics only**. It does
not contain validated predictive models or AI/ML capabilities."""))

    # ----------------------------------------------------------------
    # 2. Research and Engineering Objective
    # ----------------------------------------------------------------
    cells.append(_md("""## 2. Research and Engineering Objective

### Engineering Objective
Build a reliable, testable ETL pipeline that:
1. Extracts health indicator data from the WHO GHO OData API
2. Validates data against expected schemas and value ranges
3. Transforms raw API responses into clean, typed DataFrames
4. Enriches data with geographic metadata (ISO 3166-1 country codes → continents)
5. Loads data into SQLite with idempotent semantics
6. Generates comprehensive data quality reports

### Analytical Objective
Enable public health analysts to:
- Explore health indicators across countries, years, and demographic groups
- Identify geographic patterns and temporal trends
- Compare indicators across regions
- Export filtered data for further analysis"""))

    # ----------------------------------------------------------------
    # 3. WHO API Source and Indicator Definitions
    # ----------------------------------------------------------------
    cells.append(_md("""## 3. WHO API Source and Indicator Definitions

### Data Source
- **Provider:** World Health Organization — Global Health Observatory (GHO)
- **API:** WHO GHO OData v2 protocol (base URL loaded from centralized configuration)
- **Documentation:** https://www.who.int/data/gho/info/gho-odata-api

### Indicators

| Name | API Code | Description |
|------|----------|-------------|
| Life Expectancy | `WHOSIS_000001` | Life expectancy at birth (years) |
| NCD Mortality | `NCDMORT3070` | Probability of dying from NCDs ages 30-70 (%) |
| UHC Coverage | `UHC_INDEX_REPORTED` | Universal Health Coverage service index (1-100) |"""))

    cells.append(_code("""# Display the indicator definitions from configuration
from src.who_health_intelligence.utils.config import WHO_INDICATORS

print("Configured indicators:")
print("-" * 60)
for name, info in WHO_INDICATORS.items():
    print(f"  {name}")
    print(f"    Code: {info['code']}")
    print(f"    Description: {info['description']}")
    print()"""))

    # ----------------------------------------------------------------
    # 4. Environment Setup
    # ----------------------------------------------------------------
    cells.append(_md("""## 4. Environment Setup

Configure paths, imports, and the sample mode flag.

**Sample mode:** When `SAMPLE_MODE = True`, the notebook uses pre-loaded
data from the SQLite database instead of calling the WHO API. This allows
the notebook to run in environments without network access."""))

    cells.append(_code("""import sys
from pathlib import Path

# Project root (repository root)
PROJECT_ROOT = Path.cwd()
SRC_DIR = PROJECT_ROOT / "src"

# Ensure src/ is on the path
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Centralized project paths
from src.config import DATA_DIR, RAW_DATA_PATH, PROCESSED_DATA_PATH, METADATA_PATH, DATABASE_PATH

# Sample mode: use existing database data instead of calling the API
# Set to True if the WHO API is unreachable from your environment
SAMPLE_MODE = True  # Change to False to attempt live API extraction

print(f"Project root: {PROJECT_ROOT}")
print(f"Data directory: {DATA_DIR}")
print(f"Sample mode: {SAMPLE_MODE}")"""))

    cells.append(_code("""# Standard library imports
import json
import logging
import time
from datetime import datetime, timezone

# Third-party imports
import pandas as pd
import numpy as np

# Project imports — reuse functions from source modules
from src.who_health_intelligence.utils.config import (
    WHO_INDICATORS,
    DATABASE_PATH,
    WHO_API_BASE_URL,
    DEFAULT_INDICATORS,
    RAW_DATA_PATH,
    PROCESSED_DATA_PATH,
)
from src.who_health_intelligence.api.client import WHOAPIClient
from src.who_health_intelligence.etl.schema import (
    validate_raw_api_records,
    validate_transformed_dataframe,
)
from src.who_health_intelligence.etl.transform import (
    transform_indicator_records,
    merge_indicator_dataframes,
)
from src.who_health_intelligence.etl.metadata import (
    normalize_geography,
    get_country_metadata_df,
    COUNTRY_CONTINENT_MAP,
)
from src.who_health_intelligence.etl.loader import DatabaseLoader
from src.data_quality import DataQualityReport
from src.analytics import aggregate_continent_level, prepare_time_series

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("notebook")

print("All imports successful.")"""))

    # ----------------------------------------------------------------
    # 5. Robust API Extraction
    # ----------------------------------------------------------------
    cells.append(_md("""## 5. Robust API Extraction

The `WHOAPIClient` provides robust HTTP extraction with:
- Automatic retry with exponential backoff
- Configurable timeouts
- JSON schema validation on responses
- OData pagination support ($skip / $top)
- Structured logging

When `SAMPLE_MODE` is True, we skip live extraction and load from the
existing database."""))

    cells.append(_code("""# Initialize the API client
client = WHOAPIClient()

print(f"API base URL: {client.base_url}")
print(f"Timeout: {client.timeout}s")
print(f"Max retries: {client.max_retries}")

# Validate indicator codes before extraction
for name, info in WHO_INDICATORS.items():
    try:
        client.validate_indicator_code(info["code"])
        print(f"  ✓ {name} ({info['code']}) — valid")
    except ValueError as e:
        print(f"  ✗ {name} ({info['code']}) — INVALID: {e}")"""))

    cells.append(_code("""# Extract data (or load from database in sample mode)
raw_data = {}

if SAMPLE_MODE:
    logger.info("SAMPLE_MODE: Loading data from existing database")
    db_path = str(DATABASE_PATH)
    loader = DatabaseLoader(db_path)
    df_existing = loader.query("SELECT * FROM health_indicators")

    if df_existing.empty:
        logger.warning("Database is empty. Run 'python scripts/bootstrap_data.py' first.")
    else:
        # Group existing data by indicator to simulate extraction
        for indicator in df_existing["Indicator"].unique():
            subset = df_existing[df_existing["Indicator"] == indicator]
            # Reconstruct pseudo-raw records from the loaded data
            records = []
            for _, row in subset.iterrows():
                records.append({
                    "SpatialDim": row.get("CountryCode", ""),
                    "TimeDim": int(row.get("Year", 0)),
                    "Dim1": row.get("Gender", "BTSX"),
                    "NumericValue": float(row.get("Value", 0)),
                })
            raw_data[indicator] = records
            logger.info("  Loaded %d records for %s from database", len(records), indicator)
else:
    logger.info("Extracting live data from WHO GHO API")
    # Create raw output directory
    raw_dir = RAW_DATA_PATH
    raw_dir.mkdir(parents=True, exist_ok=True)

    for name in DEFAULT_INDICATORS:
        code = WHO_INDICATORS[name]["code"]
        try:
            records = client.extract_indicator(code, raw_output_dir=raw_dir)
            raw_data[name] = records
            logger.info("Extracted %d records for %s", len(records), name)
        except Exception as e:
            logger.error("Failed to extract %s: %s", name, e)
            raw_data[name] = []

print(f"\\nIndicators with data: {list(raw_data.keys())}")
for name, records in raw_data.items():
    print(f"  {name}: {len(records)} records")"""))

    # ----------------------------------------------------------------
    # 6. Retry and Error Handling
    # ----------------------------------------------------------------
    cells.append(_md("""## 6. Retry and Error Handling

The API client uses exponential backoff for transient failures. The retry
strategy covers:
- HTTP 429 (rate limiting)
- HTTP 500, 502, 503, 504 (server errors)
- Connection errors and timeouts"""))

    cells.append(_code("""# Demonstrate error handling with a deliberately invalid request
# (This does NOT call the API — it shows how the client handles failures)

print("Error handling demonstration:")
print()

# 1. Invalid indicator code
try:
    client.validate_indicator_code("")
except ValueError as e:
    print(f"  Empty code → ValueError: {e}")

try:
    client.validate_indicator_code("A")
except ValueError as e:
    print(f"  Too-short code → ValueError: {e}")

try:
    client.validate_indicator_code("BAD CODE!")
except ValueError as e:
    print(f"  Invalid chars → ValueError: {e}")

# 2. Valid code passes validation
try:
    client.validate_indicator_code("WHOSIS_000001")
    print(f"  Valid code → OK")
except ValueError as e:
    print(f"  Unexpected error: {e}")

print()
print("The client's retry strategy uses urllib3.util.retry.Retry with:")
print("  - Exponential backoff (factor=2)")
print("  - Status codes: 429, 500, 502, 503, 504")
print("  - Only GET methods retried")"""))

    # ----------------------------------------------------------------
    # 7. Raw Response Inspection
    # ----------------------------------------------------------------
    cells.append(_md("""## 7. Raw Response Inspection

Examine the structure of raw API records. Each record from the WHO GHO
OData API contains fields like `SpatialDim` (country code), `TimeDim`
(year), `Dim1` (gender/demographic), and `NumericValue`."""))

    cells.append(_code("""# Inspect raw records for each indicator
for name, records in raw_data.items():
    if not records:
        print(f"{name}: No records available")
        continue

    print(f"\\n{'=' * 60}")
    print(f"Indicator: {name} ({len(records)} records)")
    print(f"{'=' * 60}")

    # Show first record structure
    first = records[0]
    print(f"\\nAvailable fields: {sorted(first.keys())}")
    print(f"\\nFirst record:")
    for key, value in first.items():
        print(f"  {key}: {value!r}")

    # Show unique values for key fields
    spatial_vals = set(r.get("SpatialDim", "") for r in records[:500])
    time_vals = set(r.get("TimeDim", "") for r in records[:500])
    dim_vals = set(r.get("Dim1", "") for r in records[:500])
    print(f"\\nSample unique values (first 500 records):")
    print(f"  SpatialDim (countries): {len(spatial_vals)} unique — sample: {sorted(spatial_vals)[:5]}")
    print(f"  TimeDim (years): {sorted(time_vals)[:5]} ... {sorted(time_vals)[-5:]}")
    print(f"  Dim1 (demographics): {sorted(dim_vals)}")"""))

    # ----------------------------------------------------------------
    # 8. Schema Validation
    # ----------------------------------------------------------------
    cells.append(_md("""## 8. Schema Validation

Before transformation, raw records are validated against expected schema
requirements:
- Required fields: `SpatialDim`, `TimeDim`, `NumericValue`
- Numeric values must be finite (not NaN/Inf)
- Records missing required fields are counted and filtered"""))

    cells.append(_code("""# Validate raw records for each indicator
for name, records in raw_data.items():
    if not records:
        continue

    validated, stats = validate_raw_api_records(records, name)

    print(f"\\n{name}:")
    print(f"  Total records: {stats['total']}")
    print(f"  Valid: {stats['valid']}")
    print(f"  Missing SpatialDim: {stats['missing_spatial']}")
    print(f"  Missing TimeDim: {stats['missing_time']}")
    print(f"  Missing NumericValue: {stats['missing_value']}")
    print(f"  Invalid values: {stats['invalid_value']}")

    # Update raw_data with validated records only
    raw_data[name] = validated"""))

    # ----------------------------------------------------------------
    # 9. Data Transformation
    # ----------------------------------------------------------------
    cells.append(_md("""## 9. Data Transformation

Transformation steps for each indicator:
1. Select and rename relevant columns (`SpatialDim` → `CountryCode`, etc.)
2. Normalize gender codes (`SEX_BTSX` → `Both sexes`)
3. Add indicator metadata (name, code, description)
4. Remove missing values and aggregate records
5. Optimize data types for memory efficiency
6. Validate transformed output"""))

    cells.append(_code("""# Transform raw records into clean DataFrames
transformed_dfs = {}

for name, records in raw_data.items():
    if not records:
        print(f"  {name}: No records to transform")
        continue

    code = WHO_INDICATORS.get(name, {}).get("code", "")
    df = transform_indicator_records(records, name, code)

    if not df.empty:
        transformed_dfs[name] = df
        print(f"  {name}: {len(df)} rows, "
              f"{df['CountryCode'].nunique()} countries, "
              f"{df['Year'].nunique()} years")
    else:
        print(f"  {name}: Transformation produced empty DataFrame")

print(f"\\nTotal indicators transformed: {len(transformed_dfs)}")"""))

    # ----------------------------------------------------------------
    # 10. Missing-Value Analysis
    # ----------------------------------------------------------------
    cells.append(_md("""## 10. Missing-Value Analysis

Analyze missing data patterns across the transformed dataset."""))

    cells.append(_code("""# Merge all transformed DataFrames
if transformed_dfs:
    merged_df = merge_indicator_dataframes(transformed_dfs)
else:
    # Fall back to loading from database
    db_path = str(DATABASE_PATH)
    if Path(db_path).exists():
        loader = DatabaseLoader(db_path)
        merged_df = loader.query("SELECT * FROM health_indicators")
    else:
        merged_df = pd.DataFrame()

if merged_df.empty:
    print("No data available for analysis.")
else:
    print(f"Dataset: {len(merged_df):,} rows, {len(merged_df.columns)} columns")
    print(f"\\nMissing values per column:")
    print("-" * 40)
    for col in merged_df.columns:
        null_count = merged_df[col].isna().sum()
        null_pct = null_count / len(merged_df) * 100
        print(f"  {col:25s}: {null_count:>6,} ({null_pct:5.2f}%)")

    print(f"\\nDuplicate rows: {merged_df.duplicated().sum()}")"""))

    # ----------------------------------------------------------------
    # 11. Country and Continent Normalization
    # ----------------------------------------------------------------
    cells.append(_md("""## 11. Country and Continent Normalization

Country codes follow **ISO 3166-1 alpha-3**. The metadata module maps each
code to a country name and continent using a built-in mapping (not Plotly
Gapminder data)."""))

    cells.append(_code("""# Show the metadata mapping coverage
metadata_df = get_country_metadata_df()
print(f"Country metadata: {len(metadata_df)} countries mapped")
print(f"Continents: {metadata_df['Continent'].unique().tolist()}")

# Normalize geography in the merged dataset
if not merged_df.empty:
    if "Continent" not in merged_df.columns or merged_df["Continent"].isna().all():
        merged_df = normalize_geography(merged_df)

    # Show geographic distribution
    print(f"\\nGeographic distribution:")
    if "Continent" in merged_df.columns:
        continent_counts = merged_df["Continent"].value_counts()
        for continent, count in continent_counts.items():
            print(f"  {continent}: {count:,} records ({merged_df[merged_df['Continent'] == continent]['CountryCode'].nunique()} countries)")

    # Show unmapped countries
    if "Continent" in merged_df.columns:
        unmapped = merged_df[merged_df["Continent"].isin(["Unknown", "nan"])]["CountryCode"].unique()
        if len(unmapped) > 0:
            print(f"\\n  Unmapped country codes: {sorted(unmapped)}")
        else:
            print(f"\\n  All country codes successfully mapped ✓")"""))

    # ----------------------------------------------------------------
    # 12. Memory Optimization
    # ----------------------------------------------------------------
    cells.append(_md("""## 12. Memory Optimization

The transformation pipeline optimizes memory usage by:
- Converting `Year` to `int32` (from int64)
- Converting `Value` to `float32` (from float64)
- Converting low-cardinality string columns to `category` dtype

This reduces memory usage by up to 50-70% for large datasets."""))

    cells.append(_code("""if not merged_df.empty:
    memory_mb = merged_df.memory_usage(deep=True).sum() / 1024**2
    print(f"Current memory usage: {memory_mb:.2f} MB")
    print(f"\\nColumn dtypes:")
    for col in merged_df.columns:
        dtype = merged_df[col].dtype
        size_kb = merged_df[col].memory_usage(deep=True) / 1024
        print(f"  {col:25s}: {str(dtype):12s} ({size_kb:.1f} KB)")

    print(f"\\nTotal records: {len(merged_df):,}")
    print(f"Total memory: {memory_mb:.2f} MB")"""))

    # ----------------------------------------------------------------
    # 13. SQLite Loading
    # ----------------------------------------------------------------
    cells.append(_md("""## 13. SQLite Loading

The `DatabaseLoader` provides idempotent loading into SQLite:
- Explicit schema with typed columns
- UNIQUE constraint prevents duplicates
- WAL journal mode for concurrent read performance
- Metadata tables track indicator definitions and ETL runs

**Idempotency decision:** We use `replace=True` (delete-then-insert per
indicator). This ensures that repeated runs with the same data produce
identical database state. The alternative (INSERT OR IGNORE) would silently
skip new data if the schema changes."""))

    cells.append(_code("""# Load into SQLite (using a temporary database for this notebook)
notebook_db = str(PROCESSED_DATA_PATH / "notebook_temp.db")

if not merged_df.empty:
    loader = DatabaseLoader(notebook_db)
    loaded_count = loader.load_all_indicators(merged_df, replace_all=True)
    print(f"Loaded {loaded_count:,} records into {notebook_db}")

    # Verify idempotency: reload and check count
    loaded_again = loader.load_all_indicators(merged_df, replace_all=True)
    info = loader.get_table_info()
    final_count = info["tables"]["health_indicators"]["row_count"]
    print(f"Reload verification: {final_count:,} rows (should equal {loaded_count:,})")
    assert final_count == loaded_count, "Idempotency check failed!"
    print("✓ Idempotency verified")

    # Show database schema
    print(f"\\nDatabase tables:")
    for table, tinfo in info["tables"].items():
        print(f"  {table}: {tinfo['row_count']} rows, {len(tinfo['columns'])} columns")
else:
    print("No data to load.")"""))

    # ----------------------------------------------------------------
    # 14. Data Quality Report
    # ----------------------------------------------------------------
    cells.append(_md("""## 14. Data Quality Report

Comprehensive quality assessment including:
- Completeness (missing-value rates)
- Consistency (duplicates, type issues)
- Accuracy (invalid values, outliers)
- Geographic and temporal coverage
- Indicator coverage"""))

    cells.append(_code("""if not merged_df.empty:
    quality = DataQualityReport(merged_df)
    report = quality.generate_full_report()

    print("=" * 60)
    print("DATA QUALITY REPORT")
    print("=" * 60)
    print(f"\\nOverall Score: {report['overall_score']}/100")

    print(f"\\n--- Overview ---")
    print(f"  Rows: {report['overview']['total_rows']:,}")
    print(f"  Columns: {report['overview']['total_columns']}")
    print(f"  Indicators: {report['overview']['indicators']}")
    print(f"  Countries: {report['overview']['countries']}")
    print(f"  Year range: {report['overview']['year_range']}")

    print(f"\\n--- Completeness ---")
    print(f"  Overall: {report['completeness']['overall_completeness_pct']:.1f}%")
    print(f"  Total null cells: {report['completeness']['total_null_cells']:,}")

    print(f"\\n--- Consistency ---")
    print(f"  Duplicate rows: {report['consistency']['duplicate_rows']}")
    print(f"  Consistent: {'Yes' if report['consistency']['is_consistent'] else 'No'}")

    print(f"\\n--- Accuracy ---")
    print(f"  Invalid values: {report['accuracy']['invalid_value_count']}")
    print(f"  Outlier issues: {len(report['accuracy']['issues'])}")

    print(f"\\n--- Geographic Coverage ---")
    print(f"  Countries: {report['geographic_coverage']['countries']}")
    print(f"  Continents: {report['geographic_coverage']['continents']}")
    print(f"  Unmapped: {report['unmapped_countries']['count']}")

    print(f"\\n--- Indicator Coverage ---")
    for ind, cov in report["indicator_coverage"]["indicators"].items():
        print(f"  {ind}: {cov:.1f}%")

    print(f"\\n--- Indicator Summary ---")
    for ind in report["indicator_summary"]:
        print(f"  {ind['indicator']}: {ind['row_count']:,} rows, "
              f"{ind['country_count']} countries, "
              f"mean={ind['value_mean']}")
else:
    print("No data available for quality report.")"""))

    # ----------------------------------------------------------------
    # 15. Exploratory Analysis
    # ----------------------------------------------------------------
    cells.append(_md("""## 15. Exploratory Analysis

Descriptive statistics and patterns in the data.

**Note:** This is exploratory analysis of the data as received from WHO.
Results are computed from actual data — nothing is fabricated."""))

    cells.append(_code("""if not merged_df.empty:
    # Per-indicator descriptive statistics
    print("=== Per-Indicator Descriptive Statistics ===\\n")
    for indicator in merged_df["Indicator"].unique():
        subset = merged_df[merged_df["Indicator"] == indicator]
        print(f"--- {indicator} ---")
        print(f"  Records: {len(subset):,}")
        print(f"  Countries: {subset['CountryCode'].nunique()}")
        print(f"  Years: {int(subset['Year'].min())} to {int(subset['Year'].max())}")
        print(f"  Genders: {subset['Gender'].unique().tolist()}")
        print(f"  Value: mean={subset['Value'].mean():.2f}, "
              f"median={subset['Value'].median():.2f}, "
              f"min={subset['Value'].min():.2f}, "
              f"max={subset['Value'].max():.2f}")
        print()"""))

    cells.append(_code("""if not merged_df.empty and "Continent" in merged_df.columns:
    # Continental comparison
    print("=== Continental Comparison (Both sexes, latest year) ===\\n")

    latest_year = int(merged_df["Year"].max())
    both_sexes = merged_df[
        (merged_df["Year"] == latest_year) &
        (merged_df["Gender"] == "Both sexes")
    ]

    if not both_sexes.empty:
        continental = aggregate_continent_level(
            merged_df,
            years=[latest_year],
            gender="Both sexes",
            weighting="unweighted",
        )
        display_cols = ["Continent", "Indicator", "Value", "CountryCount", "WeightingMethod"]
        print(continental[display_cols].round({"Value": 2}))
    else:
        print("No data for 'Both sexes' in the latest year.")
        print("Showing available data with reusable analytics helper:")
        continental = aggregate_continent_level(merged_df, years=[latest_year], gender=None)
        display_cols = ["Continent", "Indicator", "Value", "CountryCount", "WeightingMethod"]
        print(continental[display_cols].round({"Value": 2}))"""))

    # ----------------------------------------------------------------
    # 16. Interactive Visualization Examples
    # ----------------------------------------------------------------
    cells.append(_md("""## 16. Interactive Visualization Examples

Examples using Plotly for interactive charts. These visualizations present
the actual data — no fabricated or synthetic results."""))

    cells.append(_code("""try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    print("Plotly not available. Install with: pip install plotly")

if HAS_PLOTLY and not merged_df.empty:
    print("Plotly available — visualization cells will render charts.")
else:
    print("Skipping visualizations (Plotly unavailable or no data).")"""))

    cells.append(_code("""if HAS_PLOTLY and not merged_df.empty and "Continent" in merged_df.columns:
    # Choropleth map example
    indicator_to_plot = merged_df["Indicator"].iloc[0]
    latest = merged_df[
        (merged_df["Indicator"] == indicator_to_plot) &
        (merged_df["Year"] == merged_df["Year"].max()) &
        (merged_df["Gender"] == "Both sexes")
    ].dropna(subset=["Value"])

    if not latest.empty:
        fig = px.choropleth(
            latest,
            locations="CountryCode",
            color="Value",
            hover_name="Country" if "Country" in latest.columns else "CountryCode",
            color_continuous_scale="RdYlGn",
            title=f"{indicator_to_plot} — {int(latest['Year'].max())}",
            height=500,
        )
        fig.update_layout(
            geo=dict(showframe=True, showcoastlines=True, projection_type="natural earth"),
            margin=dict(l=0, r=0, t=40, b=0),
        )
        fig.show()
    else:
        print(f"No map data available for {indicator_to_plot}")"""))

    cells.append(_code("""if HAS_PLOTLY and not merged_df.empty:
    # Time-series trend example
    indicator_to_plot = merged_df["Indicator"].iloc[0]
    trend = merged_df[merged_df["Indicator"] == indicator_to_plot]

    if not trend.empty:
        yearly = prepare_time_series(merged_df, indicator_to_plot)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=yearly["Year"], y=yearly["MeanValue"],
            mode="lines+markers", name="Mean",
            line=dict(color="#2563eb", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=yearly["Year"], y=yearly["MeanValue"] + yearly["StdValue"],
            mode="lines", line=dict(width=0), showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=yearly["Year"], y=yearly["MeanValue"] - yearly["StdValue"],
            mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(37,99,235,0.1)",
            name="±1 SD",
        ))
        fig.update_layout(
            title=f"{indicator_to_plot} — Global Trend (unweighted mean)",
            xaxis_title="Year",
            yaxis_title=indicator_to_plot,
            template="plotly_white",
            height=400,
        )
        fig.show()"""))

    cells.append(_code("""if HAS_PLOTLY and not merged_df.empty and "Continent" in merged_df.columns:
    # Distribution by continent (box plot)
    indicator_to_plot = merged_df["Indicator"].iloc[0]
    latest = merged_df[
        (merged_df["Indicator"] == indicator_to_plot) &
        (merged_df["Year"] == merged_df["Year"].max()) &
        (merged_df["Gender"] == "Both sexes")
    ].dropna(subset=["Value"])

    if not latest.empty:
        fig = px.box(
            latest,
            x="Continent",
            y="Value",
            color="Continent",
            title=f"{indicator_to_plot} Distribution by Continent — {int(latest['Year'].max())}",
            height=400,
        )
        fig.update_layout(template="plotly_white", showlegend=False)
        fig.show()"""))

    # ----------------------------------------------------------------
    # 17. Limitations and Reproducibility Notes
    # ----------------------------------------------------------------
    cells.append(_md("""## 17. Limitations and Reproducibility Notes

### Data Limitations
- **API availability:** The WHO GHO API may be unreachable from some
  networks (SSL errors, firewalls). Use `SAMPLE_MODE = True` in such cases.
- **Indicator coverage:** Not all indicators have data for all countries
  and years. Some indicators lack gender-specific breakdowns.
- **Country code mapping:** ISO 3166-1 alpha-3 codes are used. Some
  WHO-specific aggregate codes (e.g., WB_HI, AFR) are excluded from
  country-level analysis.
- **Aggregate records:** Records for GLOBAL, WORLD, and regional aggregates
  are filtered out to avoid double-counting.

### Methodology Notes
- All cross-country averages are **unweighted** (each country counts equally).
  Population-weighted averages require external population data.
- Correlation analysis shows **statistical associations only** — not causation.
- Year-over-year changes may reflect reporting improvements rather than
  actual health changes.

### Reproducibility
- This notebook can be reproduced by running `python scripts/generate_notebook.py`
  from the repository root, then executing all cells.
- Set `SAMPLE_MODE = True` for offline runs; `SAMPLE_MODE = False` for
  live API extraction (requires network access to `ghoapi.azureedge.net`).
- The ETL pipeline is idempotent: running it multiple times produces
  the same database state.
- All code reuses functions from `src/who_health_intelligence/` — no
  duplicated logic.

### No Fabricated Results
- All data displayed in this notebook comes from actual execution of the
  code cells above.
- If a cell produces no output, it means no data was available for that
  analysis — the result is not fabricated.
- This notebook does not contain validated predictive models or AI/ML
  capabilities."""))

    # ----------------------------------------------------------------
    # 18. Conclusion and Next Steps
    # ----------------------------------------------------------------
    cells.append(_md("""## 18. Conclusion and Next Steps

### What We Built
- A **robust ETL pipeline** that extracts WHO GHO data with retry logic,
  pagination, and schema validation
- A **data quality monitoring** system that tracks completeness, consistency,
  accuracy, and coverage
- An **idempotent SQLite loader** with metadata tables for tracking ETL runs
- **Exploratory analytics** with interactive Plotly visualizations

### Next Steps
1. **Launch the interactive dashboard:**
   ```bash
   streamlit run src/who_health_intelligence/dashboard/app.py
   ```

2. **Run the full ETL pipeline from CLI:**
   ```bash
   python who_etl_pipeline.py --indicator NCD_MORTALITY UHC_COVERAGE
   ```

3. **Explore additional indicators** by adding them to `WHO_INDICATORS`
   in `src/who_health_intelligence/utils/config.py`

4. **Integrate population data** (e.g., World Bank) to enable
   population-weighted averages

5. **Set up scheduled ETL runs** to keep the database current

### Project Structure
```
who-health-intelligence/
├── who_etl_pipeline.py          # Standalone ETL CLI
├── src/who_health_intelligence/
│   ├── api/client.py            # WHO GHO API client
│   ├── etl/                     # ETL modules
│   │   ├── pipeline.py          # Pipeline orchestrator
│   │   ├── transform.py         # Data transformation
│   │   ├── schema.py            # Schema validation
│   │   ├── loader.py            # SQLite persistence
│   │   ├── metadata.py          # Country/continent mapping
│   │   └── quality.py           # Data quality monitoring
│   ├── dashboard/
│   │   ├── services.py          # Data services layer
│   │   └── app.py               # Streamlit dashboard
│   └── utils/config.py          # Configuration
├── scripts/
│   ├── generate_notebook.py     # This notebook generator
│   └── bootstrap_data.py        # Development data bootstrap
├── tests/                       # 112 automated tests
└── data/                        # SQLite database
```"""))

    # ----------------------------------------------------------------
    # Build the notebook
    # ----------------------------------------------------------------
    nb = new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.11.0",
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "codemirror_mode": {"name": "ipython", "version": 3},
                "pygments_lexer": "ipython3",
                "nbconvert_exporter": "python",
            },
        },
    )

    return nb


# ====================================================================
# Main entry point
# ====================================================================


def generate_notebook(output_path: str = "WHO_Data_Extraction_ETL.ipynb") -> Path:
    """
    Generate the WHO Data Extraction & ETL notebook.

    Args:
        output_path: Path to save the generated notebook.

    Returns:
        Path to the generated file.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    nb = _build_notebook()

    # Validate the notebook before writing
    nbformat.validate(nb)

    with open(output, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    logger.info("Notebook generated: %s (%d cells)", output, len(nb.cells))
    return output


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate the WHO Data Extraction & ETL notebook",
    )
    parser.add_argument(
        "--output",
        default="WHO_Data_Extraction_ETL.ipynb",
        help="Output notebook path (default: WHO_Data_Extraction_ETL.ipynb)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    output = generate_notebook(args.output)
    print(f"Notebook generated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
