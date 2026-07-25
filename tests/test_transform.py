"""
Tests for the ETL transform module.
"""

import pandas as pd
import numpy as np

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.transform import (
    transform_indicator_records,
    merge_indicator_dataframes,
    _optimize_dtypes
)


class TestTransformIndicatorRecords:
    """Tests for the transform_indicator_records function."""

    def test_empty_records(self):
        """Empty input should return empty DataFrame."""
        result = transform_indicator_records([], "TEST_INDICATOR")
        assert result.empty

    def test_basic_transform(self):
        """Basic valid records should be transformed correctly."""
        records = [
            {
                'SpatialDim': 'USA',
                'TimeDim': 2020,
                'Dim1': 'SEX_BTSX',
                'NumericValue': 78.5,
                'IndicatorCode': 'WHOSIS_000001'
            },
            {
                'SpatialDim': 'GBR',
                'TimeDim': 2020,
                'Dim1': 'SEX_FMLE',
                'NumericValue': 82.3,
                'IndicatorCode': 'WHOSIS_000001'
            }
        ]

        result = transform_indicator_records(records, "LIFE_EXPECTANCY", "WHOSIS_000001")

        assert not result.empty
        assert len(result) == 2
        assert 'CountryCode' in result.columns
        assert 'Year' in result.columns
        assert 'Gender' in result.columns
        assert 'Value' in result.columns
        assert 'Indicator' in result.columns
        assert result['Indicator'].iloc[0] == 'LIFE_EXPECTANCY'

    def test_gender_normalization(self):
        """WHO gender codes should be normalized to readable values."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': 78.5},
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'SEX_MLE', 'NumericValue': 76.0},
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'SEX_FMLE', 'NumericValue': 81.0},
        ]

        result = transform_indicator_records(records, "TEST")

        genders = result['Gender'].unique().tolist()
        assert 'Both sexes' in genders
        assert 'Male' in genders
        assert 'Female' in genders
        assert 'SEX_BTSX' not in genders

    def test_missing_required_fields(self):
        """Records missing required fields should be filtered out."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'NumericValue': 78.5},  # Missing Dim1 -> OK, defaults
            {'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': 78.5},  # Missing SpatialDim -> filtered
            {'SpatialDim': 'USA', 'Dim1': 'SEX_BTSX', 'NumericValue': 78.5},  # Missing TimeDim -> filtered
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX'},  # Missing NumericValue -> filtered
        ]

        result = transform_indicator_records(records, "TEST")

        # Only the first record should remain
        assert len(result) == 1
        assert result.iloc[0]['CountryCode'] == 'USA'

    def test_global_records_filtered(self):
        """GLOBAL/WORLD aggregate records should be filtered out."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': 78.5},
            {'SpatialDim': 'GLOBAL', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': 72.0},
            {'SpatialDim': 'WORLD', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': 72.5},
        ]

        result = transform_indicator_records(records, "TEST")

        assert 'GLOBAL' not in result['CountryCode'].values
        assert 'WORLD' not in result['CountryCode'].values
        assert len(result) == 1

    def test_invalid_numeric_values(self):
        """Records with NaN/Inf values should be filtered out."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': 78.5},
            {'SpatialDim': 'GBR', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': float('nan')},
            {'SpatialDim': 'FRA', 'TimeDim': 2020, 'Dim1': 'SEX_BTSX', 'NumericValue': float('inf')},
        ]

        result = transform_indicator_records(records, "TEST")

        assert len(result) == 1
        assert result.iloc[0]['CountryCode'] == 'USA'


class TestMergeDataframes:
    """Tests for merge_indicator_dataframes."""

    def test_merge_multiple(self):
        """Should merge multiple indicator DataFrames."""
        df1 = pd.DataFrame({
            'CountryCode': ['USA', 'GBR'],
            'Year': [2020, 2020],
            'Gender': ['Both sexes', 'Both sexes'],
            'Indicator': ['IND_A', 'IND_A'],
            'Value': [78.5, 80.0]
        })
        df2 = pd.DataFrame({
            'CountryCode': ['USA', 'GBR'],
            'Year': [2020, 2020],
            'Gender': ['Both sexes', 'Both sexes'],
            'Indicator': ['IND_B', 'IND_B'],
            'Value': [50.0, 45.0]
        })

        result = merge_indicator_dataframes({'IND_A': df1, 'IND_B': df2})

        assert len(result) == 4
        assert set(result['Indicator'].unique()) == {'IND_A', 'IND_B'}

    def test_merge_with_empty(self):
        """Should handle empty DataFrames in merge."""
        df1 = pd.DataFrame({
            'CountryCode': ['USA'],
            'Year': [2020],
            'Gender': ['Both sexes'],
            'Indicator': ['IND_A'],
            'Value': [78.5]
        })

        result = merge_indicator_dataframes({'IND_A': df1, 'IND_B': pd.DataFrame()})

        assert len(result) == 1


class TestOptimizeDtypes:
    """Tests for dtype optimization."""

    def test_year_cast_to_int32(self):
        """Year column should be int32."""
        df = pd.DataFrame({
            'CountryCode': ['USA'],
            'Year': [2020],
            'Value': [78.5],
            'Gender': ['Both sexes'],
            'Indicator': ['TEST']
        })

        result = _optimize_dtypes(df)
        assert result['Year'].dtype == np.int32

    def test_value_cast_to_float32(self):
        """Value column should be float32."""
        df = pd.DataFrame({
            'CountryCode': ['USA'],
            'Year': [2020],
            'Value': [78.5],
            'Gender': ['Both sexes'],
            'Indicator': ['TEST']
        })

        result = _optimize_dtypes(df)
        assert result['Value'].dtype == np.float32
