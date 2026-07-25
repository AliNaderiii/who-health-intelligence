"""
Tests for schema validation module.
"""

import pytest
import pandas as pd
import numpy as np

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.schema import (
    validate_raw_api_records,
    validate_transformed_dataframe,
    validate_indicator_values
)


class TestValidateRawApiRecords:
    """Tests for raw API record validation."""

    def test_valid_records(self):
        """All valid records should pass validation."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'NumericValue': 78.5, 'Dim1': 'SEX_BTSX'},
            {'SpatialDim': 'GBR', 'TimeDim': 2020, 'NumericValue': 81.0, 'Dim1': 'SEX_FMLE'},
        ]

        validated, stats = validate_raw_api_records(records, "TEST")

        assert len(validated) == 2
        assert stats['valid'] == 2
        assert stats['total'] == 2

    def test_missing_spatial_dim(self):
        """Records without SpatialDim should be filtered."""
        records = [
            {'TimeDim': 2020, 'NumericValue': 78.5},
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'NumericValue': 78.5},
        ]

        validated, stats = validate_raw_api_records(records, "TEST")

        assert len(validated) == 1
        assert stats['missing_spatial'] == 1

    def test_missing_numeric_value(self):
        """Records without NumericValue should be filtered."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'Dim1': 'BTSX'},
        ]

        validated, stats = validate_raw_api_records(records, "TEST")

        assert len(validated) == 0
        assert stats['missing_value'] == 1

    def test_nan_values_filtered(self):
        """NaN numeric values should be filtered."""
        records = [
            {'SpatialDim': 'USA', 'TimeDim': 2020, 'NumericValue': float('nan')},
            {'SpatialDim': 'GBR', 'TimeDim': 2020, 'NumericValue': 80.0},
        ]

        validated, stats = validate_raw_api_records(records, "TEST")

        assert len(validated) == 1
        assert stats['invalid_value'] == 1

    def test_empty_records(self):
        """Empty input should return empty output."""
        validated, stats = validate_raw_api_records([], "TEST")

        assert len(validated) == 0
        assert stats['total'] == 0


class TestValidateTransformedDataframe:
    """Tests for transformed DataFrame validation."""

    def test_valid_dataframe(self):
        """A well-formed DataFrame should pass validation."""
        df = pd.DataFrame({
            'CountryCode': ['USA', 'GBR', 'FRA'],
            'Year': [2020, 2020, 2020],
            'Gender': ['Both sexes', 'Both sexes', 'Both sexes'],
            'Indicator': ['TEST', 'TEST', 'TEST'],
            'Value': [78.5, 81.0, 82.0]
        })

        result = validate_transformed_dataframe(df)

        assert result['is_valid'] is True
        assert result['row_count'] == 3
        assert len(result['errors']) == 0

    def test_empty_dataframe(self):
        """Empty DataFrame should fail validation."""
        df = pd.DataFrame()

        result = validate_transformed_dataframe(df)

        assert result['is_valid'] is False
        assert any('empty' in e.lower() for e in result['errors'])

    def test_missing_required_columns(self):
        """DataFrame missing required columns should fail."""
        df = pd.DataFrame({
            'CountryCode': ['USA'],
            'Value': [78.5]
        })

        result = validate_transformed_dataframe(df)

        assert result['is_valid'] is False
        assert any('Missing' in e for e in result['errors'])

    def test_duplicate_rows_warning(self):
        """Duplicate rows should generate warnings."""
        df = pd.DataFrame({
            'CountryCode': ['USA', 'USA'],
            'Year': [2020, 2020],
            'Gender': ['Both sexes', 'Both sexes'],
            'Indicator': ['TEST', 'TEST'],
            'Value': [78.5, 78.5]
        })

        result = validate_transformed_dataframe(df)

        assert result['is_valid'] is True
        assert any('duplicate' in w.lower() for w in result['warnings'])


class TestValidateIndicatorValues:
    """Tests for indicator-specific value validation."""

    def test_life_expectancy_in_range(self):
        """Life expectancy values in valid range should pass."""
        df = pd.DataFrame({
            'Indicator': ['LIFE_EXPECTANCY'] * 3,
            'Value': [78.5, 81.0, 65.0]
        })

        result = validate_indicator_values(df, 'LIFE_EXPECTANCY')
        assert result['is_valid'] is True

    def test_life_expectancy_out_of_range(self):
        """Life expectancy values outside valid range should fail."""
        df = pd.DataFrame({
            'Indicator': ['LIFE_EXPECTANCY'] * 3,
            'Value': [78.5, 200.0, 65.0]  # 200 is out of range
        })

        result = validate_indicator_values(df, 'LIFE_EXPECTANCY')
        assert result['is_valid'] is False

    def test_ncd_mortality_range(self):
        """NCD mortality should be 0-100%."""
        df = pd.DataFrame({
            'Indicator': ['NCD_MORTALITY'] * 2,
            'Value': [15.0, 45.0]
        })

        result = validate_indicator_values(df, 'NCD_MORTALITY')
        assert result['is_valid'] is True

    def test_unknown_indicator(self):
        """Unknown indicator should note no range defined."""
        df = pd.DataFrame({
            'Indicator': ['UNKNOWN'] * 2,
            'Value': [50.0, 60.0]
        })

        result = validate_indicator_values(df, 'UNKNOWN')
        assert any('No known range' in issue for issue in result['issues'])
