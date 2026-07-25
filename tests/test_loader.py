"""
Tests for the database loader module.
"""

import pytest
import pandas as pd
import sqlite3
import tempfile
import os

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.loader import DatabaseLoader


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sample_df():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame({
        'CountryCode': ['USA', 'GBR', 'FRA', 'DEU', 'JPN'],
        'Country': ['United States', 'United Kingdom', 'France', 'Germany', 'Japan'],
        'Year': [2020, 2020, 2020, 2020, 2020],
        'Gender': ['Both sexes'] * 5,
        'Indicator': ['LIFE_EXPECTANCY'] * 5,
        'IndicatorCode': ['WHOSIS_000001'] * 5,
        'IndicatorDescription': ['Life expectancy'] * 5,
        'Value': [78.5, 81.0, 82.0, 80.5, 84.0],
        'Continent': ['Americas', 'Europe', 'Europe', 'Europe', 'Asia']
    })


class TestDatabaseLoader:
    """Tests for the DatabaseLoader class."""

    def test_initialization(self, temp_db):
        """Loader should create database with proper schema."""
        loader = DatabaseLoader(temp_db)

        # Verify tables exist
        info = loader.get_table_info()
        assert 'health_indicators' in info['tables']
        assert 'etl_metadata' in info['tables']

    def test_load_dataframe(self, temp_db, sample_df):
        """Should load DataFrame into database."""
        loader = DatabaseLoader(temp_db)
        count = loader.load_dataframe(sample_df)

        assert count == 5

        # Verify data was loaded
        result = loader.query("SELECT COUNT(*) as cnt FROM health_indicators")
        assert result['cnt'].iloc[0] == 5

    def test_load_empty_dataframe(self, temp_db):
        """Should handle empty DataFrame gracefully."""
        loader = DatabaseLoader(temp_db)
        count = loader.load_dataframe(pd.DataFrame())

        assert count == 0

    def test_idempotent_load_with_replace(self, temp_db, sample_df):
        """Replace mode should clear existing data for indicator."""
        loader = DatabaseLoader(temp_db)

        # First load
        loader.load_dataframe(sample_df)
        assert loader.query("SELECT COUNT(*) as cnt FROM health_indicators")['cnt'].iloc[0] == 5

        # Load again with replace
        loader.load_dataframe(sample_df, indicator_name='LIFE_EXPECTANCY', replace=True)
        assert loader.query("SELECT COUNT(*) as cnt FROM health_indicators")['cnt'].iloc[0] == 5

    def test_load_all_indicators(self, temp_db, sample_df):
        """Should load all data with optional replace_all."""
        loader = DatabaseLoader(temp_db)

        # First load
        count1 = loader.load_all_indicators(sample_df, replace_all=True)
        assert count1 == 5

        # Load again (replace)
        count2 = loader.load_all_indicators(sample_df, replace_all=True)
        assert count2 == 5

        # Verify no duplicates
        result = loader.query("SELECT COUNT(*) as cnt FROM health_indicators")
        assert result['cnt'].iloc[0] == 5

    def test_query(self, temp_db, sample_df):
        """Query should return DataFrame."""
        loader = DatabaseLoader(temp_db)
        loader.load_dataframe(sample_df)

        result = loader.query(
            "SELECT * FROM health_indicators WHERE CountryCode = ?",
            ('USA',)
        )

        assert len(result) == 1
        assert result.iloc[0]['CountryCode'] == 'USA'

    def test_get_table_info(self, temp_db, sample_df):
        """Should return table metadata."""
        loader = DatabaseLoader(temp_db)
        loader.load_dataframe(sample_df)

        info = loader.get_table_info()

        assert 'health_indicators' in info['tables']
        assert info['tables']['health_indicators']['row_count'] == 5
        assert len(info['tables']['health_indicators']['columns']) > 0

    def test_log_etl_run(self, temp_db):
        """Should log ETL run metadata."""
        loader = DatabaseLoader(temp_db)
        loader.log_etl_run(
            indicator='TEST',
            records_loaded=100,
            status='success',
            duration_seconds=5.5,
            notes='Test run'
        )

        result = loader.query("SELECT * FROM etl_metadata")
        assert len(result) == 1
        assert result.iloc[0]['indicator'] == 'TEST'
        assert result.iloc[0]['records_loaded'] == 100

    def test_categorical_conversion(self, temp_db):
        """Categorical columns should be converted for SQLite."""
        loader = DatabaseLoader(temp_db)

        df = pd.DataFrame({
            'CountryCode': pd.Categorical(['USA', 'GBR']),
            'Year': [2020, 2020],
            'Gender': pd.Categorical(['Both sexes', 'Both sexes']),
            'Indicator': pd.Categorical(['TEST', 'TEST']),
            'Value': [78.5, 81.0]
        })

        count = loader.load_dataframe(df)
        assert count == 2
