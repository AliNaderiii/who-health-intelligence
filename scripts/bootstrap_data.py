#!/usr/bin/env python3
"""
Bootstrap script to populate database with realistic WHO health data - DEMO MODE ONLY

This produces SYNTHETIC data for development/testing only. In production LIVE mode,
the ETL pipeline (main.py etl) must be used to extract real WHO GHO data.

DEMO mode must be explicitly enabled: WHO_DATA_MODE=demo

The UI must visibly show: DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS
Do not allow demo mode to be mistaken for live production data.

Per production requirements:
- Default deployment mode is LIVE
- DEMO requires explicit WHO_DATA_MODE=demo
- Never silently use synthetic in LIVE mode
- Never mix synthetic with live data
- This script should only be used when WHO_DATA_MODE=demo
"""

import os
import sys
from pathlib import Path
import warnings

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.metadata import (
    COUNTRY_CONTINENT_MAP,
    COUNTRY_NAMES,
    normalize_geography
)
from src.who_health_intelligence.etl.loader import DatabaseLoader
from src.who_health_intelligence.utils.config import DATABASE_PATH, get_data_mode
from src.who_health_intelligence.utils.data_mode import DataMode, get_current_data_mode

import numpy as np
import pandas as pd


def _check_demo_explicit():
    """
    Ensure DEMO mode is explicitly enabled.
    If WHO_DATA_MODE != demo, warn and require confirmation or fail.
    """
    mode = get_current_data_mode()
    if mode != DataMode.DEMO:
        # Check if env var explicitly set to demo
        env_val = os.environ.get("WHO_DATA_MODE", "")
        if env_val.lower() != "demo":
            print("ERROR: DEMO bootstrap requires explicit WHO_DATA_MODE=demo")
            print("This script generates synthetic data, NOT official WHO observations.")
            print("To run in DEMO mode, set:")
            print("  export WHO_DATA_MODE=demo")
            print("  python scripts/bootstrap_data.py")
            print("Or:")
            print("  WHO_DATA_MODE=demo python scripts/bootstrap_data.py")
            print("\nDefault production mode is LIVE (WHO_DATA_MODE=live)")
            print("Never silently use synthetic data in LIVE mode.")
            sys.exit(1)
    print("✓ DEMO mode explicitly enabled (WHO_DATA_MODE=demo)")
    print("Banner: DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS")
    return True


def _generate_ncd_mortality(countries: list, years: list):
    rng = np.random.default_rng(seed=42)
    regional_baselines = {
        'Africa': 22.0,
        'Americas': 16.0,
        'Asia': 19.0,
        'Europe': 20.0,
        'Oceania': 14.0,
    }
    country_effects = {}
    for code in countries:
        continent = COUNTRY_CONTINENT_MAP.get(code, 'Unknown')
        base = regional_baselines.get(continent, 20.0)
        country_effects[code] = rng.normal(0, 4.0)

    genders = ['SEX_BTSX', 'SEX_MLE', 'SEX_FMLE']
    gender_offsets = {'SEX_BTSX': 0, 'SEX_MLE': 4.0, 'SEX_FMLE': -3.5}

    records = []
    for code in countries:
        continent = COUNTRY_CONTINENT_MAP.get(code, 'Unknown')
        base = regional_baselines.get(continent, 20.0)
        effect = country_effects[code]
        for year in years:
            year_effect = -0.15 * (year - 2000)
            year_noise = rng.normal(0, 0.5)
            for gender in genders:
                g_offset = gender_offsets[gender]
                value = base + effect + year_effect + year_noise + g_offset
                value = float(np.clip(value, 4.0, 55.0))
                records.append({
                    'SpatialDim': code,
                    'TimeDim': year,
                    'Dim1': gender,
                    'NumericValue': value,
                    'IndicatorCode': 'NCDMORT3070'
                })
    return records


def _generate_uhc_coverage(countries: list, years: list):
    rng = np.random.default_rng(seed=123)
    regional_baselines = {
        'Africa': 40.0,
        'Americas': 65.0,
        'Asia': 55.0,
        'Europe': 78.0,
        'Oceania': 55.0,
    }
    country_effects = {}
    for code in countries:
        continent = COUNTRY_CONTINENT_MAP.get(code, 'Unknown')
        base = regional_baselines.get(continent, 55.0)
        country_effects[code] = rng.normal(0, 8.0)

    records = []
    for code in countries:
        continent = COUNTRY_CONTINENT_MAP.get(code, 'Unknown')
        base = regional_baselines.get(continent, 55.0)
        effect = country_effects[code]
        for year in years:
            year_effect = 0.4 * (year - 2000)
            year_noise = rng.normal(0, 1.0)
            value = base + effect + year_effect + year_noise
            value = float(np.clip(value, 10.0, 95.0))
            records.append({
                'SpatialDim': code,
                'TimeDim': year,
                'Dim1': 'BTSX',
                'NumericValue': value,
                'IndicatorCode': 'UHC_INDEX_REPORTED'
            })
    return records


def _generate_life_expectancy(countries: list, years: list):
    rng = np.random.default_rng(seed=999)
    regional_baselines = {
        'Africa': 60.0,
        'Americas': 75.0,
        'Asia': 70.0,
        'Europe': 78.0,
        'Oceania': 74.0,
    }
    country_effects = {code: rng.normal(0, 5.0) for code in countries}

    records = []
    for code in countries:
        continent = COUNTRY_CONTINENT_MAP.get(code, 'Unknown')
        base = regional_baselines.get(continent, 70.0)
        effect = country_effects[code]
        for year in years:
            year_effect = 0.2 * (year - 2000)
            value = base + effect + year_effect + rng.normal(0, 0.8)
            value = float(np.clip(value, 45.0, 90.0))
            records.append({
                'SpatialDim': code,
                'TimeDim': year,
                'Dim1': 'SEX_BTSX',
                'NumericValue': value,
                'IndicatorCode': 'WHOSIS_000001'
            })
    return records


def bootstrap_database(db_path: str = None):
    """Generate and load synthetic WHO health data - DEMO ONLY."""
    _check_demo_explicit()

    from src.who_health_intelligence.utils.config import DATABASE_PATH

    if db_path is None:
        db_path = DATABASE_PATH

    print(f"Bootstrapping DEMO database at: {db_path}")
    print("This is SYNTHETIC data for development/testing only")
    print("NOT official WHO observations")
    print("Dashboard will show: DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS")

    countries = list(COUNTRY_NAMES.keys())

    ncd_countries = countries[:196]
    ncd_years = list(range(2000, 2022))
    ncd_records = _generate_ncd_mortality(ncd_countries, ncd_years)

    uhc_years = list(range(2000, 2024))
    uhc_records = _generate_uhc_coverage(countries, uhc_years)

    le_years = list(range(2000, 2023))
    le_records = _generate_life_expectancy(countries, le_years)

    from src.who_health_intelligence.etl.transform import transform_indicator_records

    ncd_df = transform_indicator_records(ncd_records, "NCD_MORTALITY", "NCDMORT3070")
    uhc_df = transform_indicator_records(uhc_records, "UHC_COVERAGE", "UHC_INDEX_REPORTED")
    le_df = transform_indicator_records(le_records, "LIFE_EXPECTANCY", "WHOSIS_000001")

    ncd_df = normalize_geography(ncd_df)
    uhc_df = normalize_geography(uhc_df)
    le_df = normalize_geography(le_df)

    print(f"  NCD_MORTALITY: {len(ncd_df)} records, {ncd_df['CountryCode'].nunique()} countries")
    print(f"  UHC_COVERAGE: {len(uhc_df)} records, {uhc_df['CountryCode'].nunique()} countries")
    print(f"  LIFE_EXPECTANCY: {len(le_df)} records, {le_df['CountryCode'].nunique()} countries")

    loader = DatabaseLoader(db_path)
    total = loader.load_all_indicators(
        pd.concat([ncd_df, uhc_df, le_df], ignore_index=True),
        replace_all=True
    )

    print(f"  Total loaded: {total} DEMO records")

    # Mark as BOOTSTRAP synthetic
    loader.log_etl_run(
        indicator='BOOTSTRAP',
        records_loaded=total,
        status='success',
        duration_seconds=0,
        notes='DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS — Synthetic data for development/testing only. WHO_DATA_MODE=demo explicitly required. Never mix with live data.'
    )

    loader.log_source_info(
        source_name="DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS",
        source_url="synthetic_bootstrap_demo_only",
        total_extracted=total,
        total_loaded=total,
        indicators=["NCD_MORTALITY", "UHC_COVERAGE", "LIFE_EXPECTANCY"],
        status="demo",
        notes="Synthetic data for DEMO mode only, not official WHO GHO observations"
    )

    # Register indicators still but mark as demo
    loader.register_all_indicators()

    print("\nDEMO bootstrap complete")
    print("IMPORTANT: Dashboard will show banner DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS")
    print(f"Launch dashboard: WHO_DATA_MODE=demo streamlit run src/who_health_intelligence/dashboard/app.py")
    print("For LIVE production: WHO_DATA_MODE=live python main.py etl")

    return total


if __name__ == "__main__":
    count = bootstrap_database()
    print(f"\nBootstrap complete: {count} DEMO records loaded")
