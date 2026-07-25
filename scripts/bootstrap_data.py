#!/usr/bin/env python3
"""
Bootstrap script to populate the database with realistic WHO health data.

Used when the WHO GHO API is unreachable or for initial development setup.
Generates data matching the statistical profile of real WHO GHO data.

This produces SYNTHETIC data for development/testing only. In production,
the ETL pipeline (main.py etl) should be used to extract real data.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.metadata import (
    COUNTRY_CONTINENT_MAP,
    COUNTRY_NAMES,
    normalize_geography
)
from src.who_health_intelligence.etl.loader import DatabaseLoader


def _generate_ncd_mortality(countries: list, years: list) -> pd.DataFrame:
    """
    Generate NCD mortality data with realistic distributions.
    
    NCD mortality probability (ages 30-70) typically ranges 4-53%,
    with regional patterns: higher in Eastern Europe/Central Asia,
    lower in high-income countries.
    """
    rng = np.random.default_rng(seed=42)
    
    # Regional baseline means (realistic WHO patterns)
    regional_baselines = {
        'Africa': 22.0,
        'Americas': 16.0,
        'Asia': 19.0,
        'Europe': 20.0,
        'Oceania': 14.0,
    }
    
    # Country-specific random effects
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


def _generate_uhc_coverage(countries: list, years: list) -> pd.DataFrame:
    """
    Generate UHC coverage index data with realistic distributions.
    
    UHC index ranges 0-100, with high-income countries typically 70-92
    and low-income countries 20-50.
    """
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


def bootstrap_database(db_path: str = None):
    """Generate and load synthetic WHO health data into the database."""
    from src.who_health_intelligence.utils.config import DATABASE_PATH
    
    if db_path is None:
        db_path = DATABASE_PATH
    
    print(f"Bootstrapping database at: {db_path}")
    
    countries = list(COUNTRY_NAMES.keys())
    
    # Generate NCD mortality (2000-2021, 196 countries)
    ncd_countries = countries[:196]
    ncd_years = list(range(2000, 2022))
    ncd_records = _generate_ncd_mortality(ncd_countries, ncd_years)
    
    # Generate UHC coverage (2000-2023, all countries)
    uhc_years = list(range(2000, 2024))
    uhc_records = _generate_uhc_coverage(countries, uhc_years)
    
    # Transform to DataFrames
    from src.who_health_intelligence.etl.transform import transform_indicator_records
    
    ncd_df = transform_indicator_records(ncd_records, "NCD_MORTALITY", "NCDMORT3070")
    uhc_df = transform_indicator_records(uhc_records, "UHC_COVERAGE", "UHC_INDEX_REPORTED")
    
    # Normalize geography
    ncd_df = normalize_geography(ncd_df)
    uhc_df = normalize_geography(uhc_df)
    
    print(f"  NCD_MORTALITY: {len(ncd_df)} records, {ncd_df['CountryCode'].nunique()} countries")
    print(f"  UHC_COVERAGE: {len(uhc_df)} records, {uhc_df['CountryCode'].nunique()} countries")
    
    # Load into database
    loader = DatabaseLoader(db_path)
    total = loader.load_all_indicators(
        pd.concat([ncd_df, uhc_df], ignore_index=True),
        replace_all=True
    )
    
    print(f"  Total loaded: {total} records")
    
    loader.log_etl_run(
        indicator='BOOTSTRAP',
        records_loaded=total,
        status='success',
        duration_seconds=0,
        notes='Synthetic data for development/testing'
    )
    
    return total


if __name__ == "__main__":
    count = bootstrap_database()
    print(f"\nBootstrap complete: {count} records loaded")
    print("Launch dashboard: streamlit run src/who_health_intelligence/dashboard/app.py")
