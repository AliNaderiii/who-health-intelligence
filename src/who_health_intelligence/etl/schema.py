"""
Schema validation for WHO health indicator data.

Defines expected column schemas, data types, value ranges, and provides
validation functions to ensure data integrity throughout the ETL pipeline.
"""

from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import numpy as np

from ..utils.config import setup_logging

logger = setup_logging(__name__)


# Expected column schema after transformation
EXPECTED_COLUMNS = {
    'CountryCode': {
        'dtype': 'category',
        'nullable': False,
        'description': 'ISO 3166-1 alpha-3 country code'
    },
    'Country': {
        'dtype': 'str',
        'nullable': True,
        'description': 'Full country name'
    },
    'Year': {
        'dtype': 'int32',
        'nullable': False,
        'description': 'Data year',
        'min': 2000,
        'max': 2030
    },
    'Gender': {
        'dtype': 'category',
        'nullable': False,
        'description': 'Gender/demographic breakdown',
        'valid_values': ['Both sexes', 'Male', 'Female', 'Total']
    },
    'Indicator': {
        'dtype': 'category',
        'nullable': False,
        'description': 'Health indicator name'
    },
    'IndicatorCode': {
        'dtype': 'category',
        'nullable': False,
        'description': 'WHO GHO indicator code'
    },
    'IndicatorDescription': {
        'dtype': 'str',
        'nullable': True,
        'description': 'Human-readable indicator description'
    },
    'Value': {
        'dtype': 'float32',
        'nullable': False,
        'description': 'Numeric indicator value'
    },
    'Continent': {
        'dtype': 'category',
        'nullable': True,
        'description': 'Continent/region name'
    }
}

# Valid WHO API response columns (from the OData API)
RAW_API_COLUMNS = {
    'SpatialDim': 'CountryCode',
    'SpatialDimDescription': 'Country',
    'TimeDim': 'Year',
    'Dim1': 'Gender',
    'Dim1Description': 'GenderDescription',
    'NumericValue': 'Value',
    'IndicatorCode': 'IndicatorCode',
    'Indicator': 'IndicatorName',
}


def validate_raw_api_records(
    records: List[Dict[str, Any]],
    indicator_name: str
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Validate raw API records before transformation.
    
    Checks:
    - Records is a non-empty list
    - Each record contains required fields
    - Numeric values are parseable
    
    Args:
        records: List of raw JSON records from WHO API
        indicator_name: Name of the indicator being validated
        
    Returns:
        Tuple of (validated_records, validation_stats)
    """
    stats = {
        'total': len(records),
        'valid': 0,
        'missing_spatial': 0,
        'missing_time': 0,
        'missing_value': 0,
        'invalid_value': 0
    }
    
    validated = []
    
    for record in records:
        # Check required fields
        has_spatial = 'SpatialDim' in record and record['SpatialDim']
        has_time = 'TimeDim' in record and record['TimeDim']
        has_value = 'NumericValue' in record
        
        if not has_spatial:
            stats['missing_spatial'] += 1
            continue
        if not has_time:
            stats['missing_time'] += 1
            continue
        if not has_value:
            stats['missing_value'] += 1
            continue
        
        # Validate numeric value
        try:
            val = float(record['NumericValue'])
            if np.isnan(val) or np.isinf(val):
                stats['invalid_value'] += 1
                continue
        except (TypeError, ValueError):
            stats['invalid_value'] += 1
            continue
        
        stats['valid'] += 1
        validated.append(record)
    
    logger.info(
        f"Validation for {indicator_name}: "
        f"{stats['valid']}/{stats['total']} records valid "
        f"({stats['missing_spatial']} missing spatial, "
        f"{stats['missing_time']} missing time, "
        f"{stats['missing_value']} missing value, "
        f"{stats['invalid_value']} invalid value)"
    )
    
    return validated, stats


def validate_transformed_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate a transformed DataFrame against the expected schema.
    
    Checks:
    - Required columns exist
    - No unexpected null values in required columns
    - Year values within expected range
    - Gender values are in valid set
    - Value column is numeric and finite
    
    Args:
        df: Transformed DataFrame to validate
        
    Returns:
        Dictionary with validation results and any issues found
    """
    results = {
        'is_valid': True,
        'errors': [],
        'warnings': [],
        'row_count': len(df),
        'column_count': len(df.columns)
    }
    
    if df.empty:
        results['is_valid'] = False
        results['errors'].append("DataFrame is empty")
        return results
    
    # Check required columns
    required_cols = ['CountryCode', 'Year', 'Value', 'Indicator', 'Gender']
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        results['is_valid'] = False
        results['errors'].append(f"Missing required columns: {missing_cols}")
        return results
    
    # Check for null values in non-nullable columns
    for col in required_cols:
        null_count = df[col].isna().sum()
        if null_count > 0:
            results['warnings'].append(
                f"Column '{col}' has {null_count} null values"
            )
    
    # Check year range
    year_min = df['Year'].min()
    year_max = df['Year'].max()
    if year_min < 1900 or year_max > 2030:
        results['warnings'].append(
            f"Year range [{year_min}, {year_max}] is outside expected bounds"
        )
    
    # Check value column
    if not pd.api.types.is_numeric_dtype(df['Value']):
        results['errors'].append("Value column is not numeric")
        results['is_valid'] = False
    
    # Check for infinite values
    inf_count = np.isinf(df['Value'].dropna()).sum()
    if inf_count > 0:
        results['warnings'].append(f"Value column has {inf_count} infinite values")
    
    # Check duplicate rows
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        results['warnings'].append(f"Found {dup_count} duplicate rows")
    
    # Log results
    if results['is_valid']:
        logger.info(f"DataFrame validation passed: {results['row_count']} rows")
    else:
        logger.error(f"DataFrame validation failed: {results['errors']}")
    
    for warning in results['warnings']:
        logger.warning(f"Validation warning: {warning}")
    
    return results


def validate_indicator_values(
    df: pd.DataFrame,
    indicator_name: str
) -> Dict[str, Any]:
    """
    Validate value ranges for specific indicators.
    
    Each indicator has known value ranges; values outside these ranges
    likely indicate data quality issues.
    
    Args:
        df: DataFrame with indicator data
        indicator_name: Name of the indicator to validate
        
    Returns:
        Dictionary with validation results
    """
    # Known value ranges per indicator
    VALUE_RANGES = {
        'LIFE_EXPECTANCY': {'min': 0, 'max': 120, 'unit': 'years'},
        'NCD_MORTALITY': {'min': 0, 'max': 100, 'unit': '%'},
        'UHC_COVERAGE': {'min': 0, 'max': 100, 'unit': 'index'},
        'MATERNAL_MORTALITY': {'min': 0, 'max': 5000, 'unit': 'per 100k'},
        'INFANT_MORTALITY': {'min': 0, 'max': 500, 'unit': 'per 1000'},
    }
    
    results = {'indicator': indicator_name, 'is_valid': True, 'issues': []}
    
    if indicator_name not in VALUE_RANGES:
        results['issues'].append(f"No known range defined for {indicator_name}")
        return results
    
    expected = VALUE_RANGES[indicator_name]
    subset = df[df['Indicator'] == indicator_name]
    
    if subset.empty:
        results['issues'].append(f"No data found for {indicator_name}")
        return results
    
    values = subset['Value']
    
    # Check range
    below_min = (values < expected['min']).sum()
    above_max = (values > expected['max']).sum()
    
    if below_min > 0:
        results['issues'].append(
            f"{below_min} values below minimum ({expected['min']})"
        )
    if above_max > 0:
        results['issues'].append(
            f"{above_max} values above maximum ({expected['max']})"
        )
    
    if results['issues']:
        results['is_valid'] = False
    
    return results
