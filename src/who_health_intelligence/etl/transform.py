"""
Data transformation module for WHO health indicator data.

Handles the conversion of raw WHO GHO API JSON records into clean,
typed, validated DataFrames ready for persistence and analysis.
"""

from typing import Dict, List, Optional, Any
import pandas as pd

from ..utils.config import WHO_INDICATORS, setup_logging
from .schema import validate_raw_api_records, validate_transformed_dataframe

logger = setup_logging(__name__)

# WHO Gender code mapping
GENDER_MAP = {
    'SEX_BTSX': 'Both sexes',
    'SEX_MLE': 'Male',
    'SEX_FMLE': 'Female',
    'BTSX': 'Both sexes',
    'MLE': 'Male',
    'FMLE': 'Female',
    '': 'Total',
    None: 'Total'
}


def transform_indicator_records(
    records: List[Dict[str, Any]],
    indicator_name: str,
    indicator_code: Optional[str] = None
) -> pd.DataFrame:
    """
    Transform raw API records for a single indicator into a clean DataFrame.
    
    Processing steps:
    1. Validate raw records
    2. Select and rename relevant columns
    3. Normalize gender codes
    4. Add indicator metadata
    5. Clean missing values
    6. Optimize data types for memory efficiency
    7. Validate transformed output
    
    Args:
        records: Raw JSON records from WHO GHO API
        indicator_name: Internal indicator name (e.g., 'NCD_MORTALITY')
        indicator_code: Optional WHO API indicator code
        
    Returns:
        Cleaned and validated DataFrame
    """
    if not records:
        logger.warning(f"No records to transform for {indicator_name}")
        return pd.DataFrame()
    
    # Step 1: Validate raw records
    validated_records, validation_stats = validate_raw_api_records(
        records, indicator_name
    )
    
    if not validated_records:
        logger.error(f"All records failed validation for {indicator_name}")
        return pd.DataFrame()
    
    # Step 2: Create DataFrame and select columns
    df = pd.DataFrame(validated_records)
    
    # Build column mapping based on available columns
    col_mapping = {}
    column_map = {
        'SpatialDim': 'CountryCode',
        'TimeDim': 'Year',
        'Dim1': 'Gender',
        'NumericValue': 'Value',
    }
    
    for source, target in column_map.items():
        if source in df.columns:
            col_mapping[source] = target
    
    df = df[list(col_mapping.keys())].rename(columns=col_mapping)
    
    # Step 3: Normalize gender codes
    if 'Gender' in df.columns:
        df['Gender'] = df['Gender'].map(
            lambda x: GENDER_MAP.get(x, x if x else 'Total')
        )
    else:
        df['Gender'] = 'Both sexes'
    
    # Step 4: Add indicator metadata
    df['Indicator'] = indicator_name
    df['IndicatorCode'] = indicator_code or WHO_INDICATORS.get(
        indicator_name, {}
    ).get('code', '')
    df['IndicatorDescription'] = WHO_INDICATORS.get(
        indicator_name, {}
    ).get('description', '')
    
    # Step 5: Clean missing values
    df = df.dropna(subset=['Value', 'CountryCode', 'Year'])
    
    # Filter out aggregate records (GLOBAL, WORLD)
    df = df[~df['CountryCode'].isin(['GLOBAL', 'WORLD', 'EUR', 'AFR', 'AMR', 'EMR', 'SEAR', 'WPR'])]
    
    # Step 6: Optimize data types
    df = _optimize_dtypes(df)
    
    # Step 7: Validate transformed output
    validation_result = validate_transformed_dataframe(df)
    
    if not validation_result['is_valid']:
        logger.error(
            f"Transformed data validation failed for {indicator_name}: "
            f"{validation_result['errors']}"
        )
    
    logger.info(
        f"Transformed {indicator_name}: {len(df)} rows, "
        f"{df['CountryCode'].nunique()} countries, "
        f"{df['Year'].nunique()} years"
    )
    
    return df


def _optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimize DataFrame column data types for memory efficiency.
    
    Converts:
    - String columns to categorical where cardinality is low
    - Year to int32
    - Value to float32
    
    Args:
        df: Input DataFrame
        
    Returns:
        DataFrame with optimized data types
    """
    df = df.copy()
    
    # Convert Year to int32
    if 'Year' in df.columns:
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').astype('int32')
    
    # Convert Value to float32
    if 'Value' in df.columns:
        df['Value'] = pd.to_numeric(df['Value'], errors='coerce').astype('float32')
    
    # Convert low-cardinality string columns to categorical
    categorical_cols = ['CountryCode', 'Gender', 'Indicator', 'IndicatorCode', 'Continent']
    for col in categorical_cols:
        if col in df.columns:
            nunique = df[col].nunique()
            if nunique < len(df) * 0.5:  # Convert if < 50% unique
                df[col] = df[col].astype('category')
    
    # Drop rows with NaN values in Value
    df = df.dropna(subset=['Value'])
    
    return df


def merge_indicator_dataframes(
    dataframes: Dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """
    Merge multiple indicator DataFrames into a single unified DataFrame.
    
    Args:
        dataframes: Dictionary mapping indicator names to their DataFrames
        
    Returns:
        Unified DataFrame with all indicators
    """
    valid_dfs = [
        df for df in dataframes.values()
        if df is not None and not df.empty
    ]
    
    if not valid_dfs:
        logger.error("No valid DataFrames to merge")
        return pd.DataFrame()
    
    merged = pd.concat(valid_dfs, ignore_index=True)
    
    # Sort for optimal compression and query performance
    sort_cols = ['Indicator', 'CountryCode', 'Year']
    existing_sort_cols = [c for c in sort_cols if c in merged.columns]
    if existing_sort_cols:
        merged = merged.sort_values(existing_sort_cols).reset_index(drop=True)
    
    logger.info(
        f"Merged {len(valid_dfs)} indicator DataFrames: "
        f"{len(merged)} total rows"
    )
    
    return merged
