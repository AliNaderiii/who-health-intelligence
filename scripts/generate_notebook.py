#!/usr/bin/env python3
"""
Generate the WHO Health Analysis Jupyter notebook.

Creates a properly formatted .ipynb file from reusable Python code,
demonstrating the full ETL pipeline, data quality analysis, and
descriptive analytics workflow.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def create_notebook(output_path: str = "notebooks/WHO_Health_Analysis.ipynb"):
    """
    Generate a Jupyter notebook for WHO health data analysis.
    
    Args:
        output_path: Path to save the generated notebook
    """
    notebook = {
        "cells": [],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbformat": 4,
                "nbformat_minor": 5,
                "pygments_lexer": "ipython3",
                "version": "3.11.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }

    def add_markdown(source: str):
        lines = source.split('\n')
        notebook["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [line + "\n" for line in lines[:-1]] + [lines[-1]]
        })

    def add_code(source: str):
        lines = source.split('\n')
        notebook["cells"].append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [line + "\n" for line in lines[:-1]] + [lines[-1]]
        })

    # ---- Title and Introduction ----
    add_markdown("""# WHO Global Health Intelligence Platform
## Data Engineering & Descriptive Analytics

**Purpose:** Extract, validate, and analyze public health data from the WHO Global Health Observatory (GHO).

**Scope:** This notebook demonstrates the data engineering pipeline and descriptive analytics only.
It does **not** contain validated predictive models or machine learning capabilities.""")

    # ---- Setup ----
    add_markdown("""## 1. Environment Setup

Import required libraries and configure the analysis environment.""")

    add_code("""import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path.cwd().parent
sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np
import sqlite3
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

print(f"Python: {sys.version}")
print(f"Pandas: {pd.__version__}")
print(f"NumPy: {np.__version__}")""")

    # ---- Configuration ----
    add_markdown("""## 2. Configuration

Define indicator codes and data sources.""")

    add_code("""# WHO GHO Indicator definitions
INDICATORS = {
    "LIFE_EXPECTANCY": {
        "code": "WHOSIS_000001",
        "description": "Life expectancy at birth (years)"
    },
    "NCD_MORTALITY": {
        "code": "NCDMORT3070",
        "description": "Probability of dying from NCDs between ages 30-70 (%)"
    },
    "UHC_COVERAGE": {
        "code": "UHC_INDEX_REPORTED",
        "description": "Universal Health Coverage service index (1-100)"
    }
}

# Database path
DB_PATH = project_root / "data" / "who_health_data.db"

print("Indicator configuration:")
for name, info in INDICATORS.items():
    print(f"  {name}: {info['code']} - {info['description']}")""")

    # ---- API Extraction ----
    add_markdown("""## 3. API Extraction

Extract data from the WHO GHO OData API with robust error handling.

**API Documentation:** https://www.who.int/data/gho/info/gho-odata-api

**Note:** The API may be unreachable in some environments. The pipeline includes
retry logic with exponential backoff and will load from the existing database
if extraction fails.""")

    add_code("""import requests
import time

def extract_indicator(indicator_code: str, max_retries: int = 3) -> list:
    \"\"\"Extract data for a WHO indicator with retry logic.\"\"\"
    url = f"https://ghoapi.azureedge.net/api/{indicator_code}"
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Extracting {indicator_code} (attempt {attempt + 1})")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            records = data.get('value', [])
            logger.info(f"Extracted {len(records)} records")
            return records
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Extraction failed for {indicator_code}")
                return []

# Try to extract (may fail in sandboxed environments)
try:
    sample_records = extract_indicator("WHOSIS_000001")
    if sample_records:
        print(f"API extraction successful: {len(sample_records)} records")
        print(f"Sample record keys: {list(sample_records[0].keys())}")
    else:
        print("API extraction returned no data (may be unreachable)")
except Exception as e:
    print(f"API extraction error: {e}")
    print("Will use existing database data instead.")""")

    # ---- Data Loading ----
    add_markdown("""## 4. Data Loading

Load data from the SQLite database. The ETL pipeline populates this database
with validated, transformed WHO GHO data.""")

    add_code("""# Load from database
if DB_PATH.exists():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql("SELECT * FROM health_indicators", conn)
    conn.close()
    
    print(f"Loaded {len(df):,} records from database")
    print(f"Shape: {df.shape}")
    print(f"\\nIndicators: {df['Indicator'].unique().tolist()}")
    print(f"Countries: {df['CountryCode'].nunique()}")
    print(f"Year range: {df['Year'].min()} - {df['Year'].max()}")
else:
    print(f"Database not found at {DB_PATH}")
    print("Run 'python main.py etl' to populate the database first.")
    df = pd.DataFrame()""")

    # ---- Data Quality ----
    add_markdown("""## 5. Data Quality Assessment

Validate data completeness, consistency, and accuracy.""")

    add_code("""if not df.empty:
    # Basic quality checks
    print("=== DATA QUALITY REPORT ===")
    print(f"\\nTotal records: {len(df):,}")
    print(f"Missing values: {df.isna().sum().sum():,} cells")
    print(f"Duplicate rows: {df.duplicated().sum()}")
    
    print("\\n--- Per-Column Completeness ---")
    for col in df.columns:
        null_pct = df[col].isna().mean() * 100
        print(f"  {col}: {100 - null_pct:.1f}% complete ({df[col].isna().sum()} nulls)")
    
    print("\\n--- Per-Indicator Summary ---")
    for indicator in df['Indicator'].unique():
        subset = df[df['Indicator'] == indicator]
        print(f"\\n  {indicator}:")
        print(f"    Records: {len(subset):,}")
        print(f"    Countries: {subset['CountryCode'].nunique()}")
        print(f"    Value range: [{subset['Value'].min():.2f}, {subset['Value'].max():.2f}]")
        print(f"    Mean: {subset['Value'].mean():.2f}")""")

    # ---- Descriptive Analytics ----
    add_markdown("""## 6. Descriptive Analytics

Analyze trends and distributions in the data.

**Important:** This is descriptive analytics only. These analyses show observed
patterns in the data and do not constitute predictions or causal claims.""")

    add_code("""if not df.empty:
    # Continental analysis
    if 'Continent' in df.columns:
        print("=== CONTINENTAL ANALYSIS ===")
        
        continent_stats = df.groupby(['Continent', 'Indicator']).agg({
            'Value': ['mean', 'median', 'std', 'count']
        }).round(2)
        
        print(continent_stats)""")

    add_code("""if not df.empty:
    # Temporal trends
    print("=== TEMPORAL TRENDS ===")
    
    yearly_means = df.groupby(['Year', 'Indicator'])['Value'].mean().unstack()
    print("\\nGlobal mean values by year:")
    print(yearly_means.round(2).to_string())""")

    # ---- Gender Analysis ----
    add_markdown("""## 7. Demographic Analysis

Compare health metrics across gender groups where available.""")

    add_code("""if not df.empty:
    print("=== GENDER ANALYSIS ===")
    print(f"\\nGender values in dataset: {df['Gender'].unique().tolist()}")
    
    gender_comparison = df.groupby(['Gender', 'Indicator'])['Value'].agg(
        ['mean', 'median', 'count']
    ).round(2)
    
    print("\\nGender comparison:")
    print(gender_comparison)""")

    # ---- Data Export ----
    add_markdown("""## 8. Data Export

Export processed data for external analysis.""")

    add_code("""if not df.empty:
    # Create a clean export
    export_df = df.copy()
    
    # Summary statistics for export
    summary = export_df.groupby(['Indicator', 'CountryCode', 'Year', 'Gender']).agg({
        'Value': 'mean'
    }).reset_index()
    
    print(f"Export summary shape: {summary.shape}")
    print(f"\\nFirst 10 rows:")
    print(summary.head(10))
    
    # Optionally save to CSV
    # summary.to_csv('who_health_summary.csv', index=False)
    # print("Exported to who_health_summary.csv")""")

    # ---- Methodology ----
    add_markdown("""## 9. Methodology & Limitations

### Data Source
- **Provider:** World Health Organization (WHO) Global Health Observatory
- **API:** WHO GHO OData API (`ghoapi.azureedge.net/api/`)
- **Format:** JSON (OData v2 protocol)

### Processing Pipeline
1. **Extract:** HTTP GET from WHO GHO API with retry logic
2. **Validate:** Schema validation and range checks
3. **Transform:** Gender normalization, type optimization, null handling
4. **Enrich:** Country/continent metadata mapping
5. **Load:** Idempotent upsert into SQLite

### Limitations
- Data availability varies by country and year
- Some indicators may not have gender-specific breakdowns
- Country code mappings follow ISO 3166-1 alpha-3
- Correlation analysis shows statistical associations only, not causation

### No Predictive Claims
This analysis is **descriptive only**. No machine learning models have been
trained or validated. Any future forecasting work would require:
- Proper time-series cross-validation
- Out-of-sample evaluation metrics
- Uncertainty quantification
- Clear disclosure of experimental status""")

    # ---- Conclusion ----
    add_markdown("""---

## Summary

This notebook demonstrates the WHO Health Intelligence data engineering pipeline
and descriptive analytics capabilities. The platform provides:

- **Robust API extraction** with retry logic and error handling
- **Schema validation** and data quality monitoring
- **Idempotent data loading** into SQLite
- **Interactive visualization** via the Streamlit dashboard
- **Transparent methodology** with clear limitations

For interactive analysis, run: `streamlit run src/who_health_intelligence/dashboard/app.py`""")

    # Ensure output directory exists
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=2, ensure_ascii=False)

    logger.info(f"Notebook generated: {output}")
    return str(output)


if __name__ == "__main__":
    output = create_notebook()
    print(f"Notebook saved to: {output}")
