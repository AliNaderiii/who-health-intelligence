"""
Tests for the data quality module.
"""

import pytest
import pandas as pd
import numpy as np

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.quality import DataQualityReport


@pytest.fixture
def sample_quality_df():
    """Create a sample DataFrame for quality testing."""
    np.random.seed(42)
    n = 100

    data = {
        'CountryCode': np.random.choice(['USA', 'GBR', 'FRA', 'DEU', 'JPN'], n),
        'Country': np.random.choice(['United States', 'United Kingdom', 'France', 'Germany', 'Japan'], n),
        'Year': np.random.choice(range(2010, 2021), n),
        'Gender': np.random.choice(['Both sexes', 'Male', 'Female'], n),
        'Indicator': np.random.choice(['LIFE_EXPECTANCY', 'NCD_MORTALITY'], n),
        'Value': np.random.uniform(10, 90, n),
        'Continent': np.random.choice(['Americas', 'Europe', 'Asia'], n)
    }

    return pd.DataFrame(data)


class TestDataQualityReport:
    """Tests for the DataQualityReport class."""

    def test_generate_report(self, sample_quality_df):
        """Should generate a complete report."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert 'overview' in result
        assert 'completeness' in result
        assert 'consistency' in result
        assert 'accuracy' in result
        assert 'indicator_summary' in result
        assert 'temporal_coverage' in result
        assert 'geographic_coverage' in result
        assert 'overall_score' in result

    def test_overview_metrics(self, sample_quality_df):
        """Overview should contain correct metrics."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert result['overview']['total_rows'] == 100
        assert result['overview']['indicators'] == 2
        assert result['overview']['countries'] == 5

    def test_completeness_no_nulls(self, sample_quality_df):
        """Data with no nulls should have 100% completeness."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert result['completeness']['overall_completeness_pct'] == 100.0

    def test_completeness_with_nulls(self):
        """Data with nulls should have reduced completeness."""
        df = pd.DataFrame({
            'CountryCode': ['USA', 'GBR', None, 'FRA'],
            'Year': [2020, 2020, 2020, 2020],
            'Gender': ['Both sexes'] * 4,
            'Indicator': ['TEST'] * 4,
            'Value': [78.5, 81.0, None, 82.0]
        })

        report = DataQualityReport(df)
        result = report.generate_full_report()

        assert result['completeness']['overall_completeness_pct'] < 100.0

    def test_consistency_with_duplicates(self):
        """Should detect duplicate rows."""
        df = pd.DataFrame({
            'CountryCode': ['USA', 'USA'],
            'Year': [2020, 2020],
            'Gender': ['Both sexes', 'Both sexes'],
            'Indicator': ['TEST', 'TEST'],
            'Value': [78.5, 78.5]
        })

        report = DataQualityReport(df)
        result = report.generate_full_report()

        assert result['consistency']['duplicate_rows'] == 1
        assert result['consistency']['is_consistent'] is False

    def test_temporal_coverage(self, sample_quality_df):
        """Should report year range and gaps."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert result['temporal_coverage']['years_covered'] > 0
        year_range = result['temporal_coverage']['year_range']
        assert year_range[0] >= 2010
        assert year_range[1] <= 2020

    def test_geographic_coverage(self, sample_quality_df):
        """Should report country and continent counts."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert result['geographic_coverage']['countries'] == 5
        assert result['geographic_coverage']['continents'] == 3

    def test_overall_score_range(self, sample_quality_df):
        """Overall score should be between 0 and 100."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert 0 <= result['overall_score'] <= 100

    def test_markdown_report(self, sample_quality_df):
        """Should generate valid markdown report."""
        report = DataQualityReport(sample_quality_df)
        md = report.to_markdown()

        assert '# WHO Health Data Quality Report' in md
        assert '## Dataset Overview' in md
        assert '## Completeness' in md
        assert '|' in md  # Should contain table formatting

    def test_indicator_summary(self, sample_quality_df):
        """Should generate per-indicator summary."""
        report = DataQualityReport(sample_quality_df)
        result = report.generate_full_report()

        assert len(result['indicator_summary']) == 2
        for summary in result['indicator_summary']:
            assert 'indicator' in summary
            assert 'row_count' in summary
            assert 'value_mean' in summary
