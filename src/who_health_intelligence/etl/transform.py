"""
Data transformation module - Production LIVE mode.

Handles conversion of raw WHO GHO API JSON into clean DataFrames
with snake_case columns required by spec plus legacy CamelCase for backward compat.

Outputs columns:
- country_code, country_name, continent, year, gender, indicator, indicator_code,
  value, unit, source, extracted_at, pipeline_version
- plus legacy: CountryCode, Country, Year, Gender, Indicator, IndicatorCode,
  IndicatorDescription, Value, Continent, SourceTimestamp
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from ..utils.config import PIPELINE_VERSION, WHO_INDICATORS, WHO_API_BASE_URL, setup_logging
from .schema import validate_raw_api_records, validate_transformed_dataframe

logger = setup_logging(__name__)

GENDER_MAP = {
    "SEX_BTSX": "Both sexes",
    "SEX_MLE": "Male",
    "SEX_FMLE": "Female",
    "BTSX": "Both sexes",
    "MLE": "Male",
    "FMLE": "Female",
    "": "Total",
    None: "Total",
}

# Known aggregate codes to exclude from country-level analysis
AGGREGATE_CODES = {
    "GLOBAL",
    "WORLD",
    "EUR",
    "AFR",
    "AMR",
    "EMR",
    "SEAR",
    "WPR",
    "AFRO",
    "AMRO",
    "EMRO",
    "EURO",
    "SEARO",
    "WPRO",
    "WB_LI",
    "WB_LMI",
    "WB_UMI",
    "WB_HI",
    "WB_X",
}


def transform_indicator_records(
    records: List[Dict[str, Any]],
    indicator_name: str,
    indicator_code: Optional[str] = None,
    extracted_at: Optional[str] = None,
) -> pd.DataFrame:
    """
    Transform raw API records into clean DataFrame with both snake and legacy columns.

    Steps:
    1. Validate raw records
    2. Select and rename columns to CountryCode, Year, Gender, Value (legacy)
    3. Normalize gender codes
    4. Add indicator metadata (name, code, description, unit, source, pipeline_version, extracted_at)
    5. Clean missing values and filter aggregates
    6. Optimize dtypes
    7. Add snake_case columns required by spec
    8. Validate
    """
    if not records:
        logger.warning(f"No records to transform for {indicator_name}")
        return pd.DataFrame()

    validated_records, validation_stats = validate_raw_api_records(records, indicator_name)

    if not validated_records:
        logger.error(f"All records failed validation for {indicator_name}")
        return pd.DataFrame()

    df = pd.DataFrame(validated_records)

    # Map raw columns to legacy CamelCase
    col_mapping = {}
    column_map = {
        "SpatialDim": "CountryCode",
        "TimeDim": "Year",
        "Dim1": "Gender",
        "NumericValue": "Value",
    }
    for source, target in column_map.items():
        if source in df.columns:
            col_mapping[source] = target

    if not col_mapping:
        logger.error(f"No mappable columns found for {indicator_name}, got {list(df.columns)}")
        return pd.DataFrame()

    df = df[list(col_mapping.keys())].rename(columns=col_mapping)

    # Normalize gender
    if "Gender" in df.columns:
        df["Gender"] = df["Gender"].map(lambda x: GENDER_MAP.get(x, x if x else "Total"))
    else:
        df["Gender"] = "Both sexes"

    # Indicator metadata - legacy
    df["Indicator"] = indicator_name
    df["IndicatorCode"] = indicator_code or WHO_INDICATORS.get(indicator_name, {}).get("code", "")
    df["IndicatorDescription"] = WHO_INDICATORS.get(indicator_name, {}).get("description", "")

    # Clean missing
    df = df.dropna(subset=["Value", "CountryCode", "Year"])

    # Filter aggregates
    df = df[~df["CountryCode"].isin(AGGREGATE_CODES)]

    # Optimize dtypes for legacy columns
    df = _optimize_dtypes(df)

    # Add snake_case columns required by spec + additional metadata
    indicator_meta = WHO_INDICATORS.get(indicator_name, {})
    unit = indicator_meta.get("unit", "")
    source = f"WHO GHO OData API - {WHO_API_BASE_URL}{indicator_code or ''}"
    extracted_at_val = extracted_at or datetime.now(timezone.utc).isoformat()

    # Populate snake_case from legacy (ensure consistency)
    df["country_code"] = df["CountryCode"].astype(str)
    df["country_name"] = None  # Will be populated by geography normalization
    df["continent"] = None  # Will be populated by geography normalization
    df["year"] = df["Year"]
    df["gender"] = df["Gender"]
    df["indicator"] = df["Indicator"]
    df["indicator_code"] = df["IndicatorCode"]
    df["value"] = df["Value"]
    df["unit"] = unit
    df["source"] = source
    df["extracted_at"] = extracted_at_val
    df["pipeline_version"] = PIPELINE_VERSION

    # Also keep legacy additional fields for backward compat
    df["SourceTimestamp"] = extracted_at_val

    # Validate transformed output (uses legacy columns check)
    validation_result = validate_transformed_dataframe(df)

    if not validation_result["is_valid"]:
        logger.error(
            f"Transformed data validation failed for {indicator_name}: {validation_result['errors']}"
        )

    logger.info(
        f"Transformed {indicator_name}: {len(df)} rows, "
        f"{df['CountryCode'].nunique() if not df.empty else 0} countries, "
        f"{df['Year'].nunique() if not df.empty else 0} years"
    )

    return df


def _optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("int32")

    if "Value" in df.columns:
        df["Value"] = pd.to_numeric(df["Value"], errors="coerce").astype("float32")

    categorical_cols = ["CountryCode", "Gender", "Indicator", "IndicatorCode", "Continent"]
    for col in categorical_cols:
        if col in df.columns:
            nunique = df[col].nunique()
            if nunique < len(df) * 0.5:
                df[col] = df[col].astype("category")

    df = df.dropna(subset=["Value"])

    return df


def merge_indicator_dataframes(dataframes: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    valid_dfs = [df for df in dataframes.values() if df is not None and not df.empty]

    if not valid_dfs:
        logger.error("No valid DataFrames to merge")
        return pd.DataFrame()

    merged = pd.concat(valid_dfs, ignore_index=True)

    # Sort for optimal query performance
    sort_cols = ["Indicator", "CountryCode", "Year"]
    existing_sort_cols = [c for c in sort_cols if c in merged.columns]
    if existing_sort_cols:
        merged = merged.sort_values(existing_sort_cols).reset_index(drop=True)

    logger.info(f"Merged {len(valid_dfs)} indicator DataFrames: {len(merged)} total rows")

    return merged
