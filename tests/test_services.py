"""
Tests for the dashboard data services module.

These tests verify that all data logic works correctly independent
of the Streamlit UI layer.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root on path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.dashboard import services as svc


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def sample_df():
    """Minimal valid health-indicator DataFrame."""
    return pd.DataFrame({
        "CountryCode": ["USA", "USA", "GBR", "GBR", "NGA", "NGA",
                         "USA", "GBR", "NGA"],
        "Country": ["United States"] * 3 + ["United Kingdom"] * 3 + ["Nigeria"] * 3,
        "Year": [2020, 2021, 2020, 2021, 2020, 2021, 2020, 2020, 2020],
        "Gender": ["Both sexes"] * 9,
        "Indicator": ["NCD_MORTALITY"] * 6 + ["UHC_COVERAGE"] * 3,
        "IndicatorCode": ["NCDMORT3070"] * 6 + ["UHC_INDEX_REPORTED"] * 3,
        "IndicatorDescription": ["NCD mortality 30-70 (%)"] * 6 + ["UHC index"] * 3,
        "Value": [15.0, 14.5, 18.0, 17.5, 25.0, 24.0, 70.0, 72.0, 40.0],
        "Continent": ["Americas"] * 3 + ["Europe"] * 3 + ["Africa"] * 3,
    })


@pytest.fixture
def multi_gender_df():
    """DataFrame with multiple genders for the same country/year."""
    return pd.DataFrame({
        "CountryCode": ["USA", "USA", "USA", "GBR", "GBR", "GBR"],
        "Country": ["United States"] * 3 + ["United Kingdom"] * 3,
        "Year": [2020] * 6,
        "Gender": ["Both sexes", "Male", "Female"] * 2,
        "Indicator": ["NCD_MORTALITY"] * 6,
        "IndicatorCode": ["NCDMORT3070"] * 6,
        "IndicatorDescription": ["NCD mortality"] * 6,
        "Value": [15.0, 18.0, 12.0, 18.0, 21.0, 15.0],
        "Continent": ["Americas"] * 3 + ["Europe"] * 3,
    })


@pytest.fixture
def empty_df():
    return pd.DataFrame()


# ================================================================
# Label helpers
# ================================================================

class TestLabelHelpers:
    def test_indicator_short_name_known(self):
        assert svc.indicator_short_name("NCD_MORTALITY") == "NCD Mortality (30-70)"
        assert svc.indicator_short_name("UHC_COVERAGE") == "UHC Coverage Index"

    def test_indicator_short_name_unknown_falls_back(self):
        result = svc.indicator_short_name("SOME_NEW_INDICATOR")
        assert result == "Some New Indicator"

    def test_indicator_description(self):
        desc = svc.indicator_description("NCD_MORTALITY")
        assert "30-70" in desc

    def test_is_higher_better(self):
        assert svc.is_higher_better("UHC_COVERAGE") is True
        assert svc.is_higher_better("NCD_MORTALITY") is False

    def test_indicator_unit(self):
        assert svc.indicator_unit("NCD_MORTALITY") == "%"
        assert svc.indicator_unit("LIFE_EXPECTANCY") == "years"


# ================================================================
# Data loading
# ================================================================

class TestLoadDataset:
    def test_load_missing_db(self, tmp_path):
        df, meta = svc.load_full_dataset(str(tmp_path / "nonexistent.db"))
        assert df.empty
        assert meta["status"] == "error"
        assert "not found" in meta["error"].lower()

    def test_load_empty_db(self, tmp_path):
        db_file = tmp_path / "empty.db"
        db_file.write_bytes(b"")
        df, meta = svc.load_full_dataset(str(db_file))
        assert df.empty
        assert meta["status"] == "error"

    def test_load_valid_db(self, sample_df, tmp_path):
        from src.who_health_intelligence.etl.loader import DatabaseLoader
        db_path = str(tmp_path / "test.db")
        loader = DatabaseLoader(db_path)
        loader.load_dataframe(sample_df)

        df, meta = svc.load_full_dataset(db_path)
        assert not df.empty
        assert meta["status"] == "ok"
        assert meta["row_count"] > 0


# ================================================================
# Filter options
# ================================================================

class TestFilterOptions:
    def test_returns_all_keys(self, sample_df):
        opts = svc.get_filter_options(sample_df)
        assert set(opts.keys()) == {"years", "countries", "continents", "indicators", "genders"}

    def test_years_sorted(self, sample_df):
        opts = svc.get_filter_options(sample_df)
        assert opts["years"] == sorted(opts["years"])

    def test_indicators_present(self, sample_df):
        opts = svc.get_filter_options(sample_df)
        assert "NCD_MORTALITY" in opts["indicators"]

    def test_empty_df(self, empty_df):
        opts = svc.get_filter_options(empty_df)
        assert opts["years"] == []
        assert opts["indicators"] == []


# ================================================================
# Apply filters
# ================================================================

class TestApplyFilters:
    def test_filter_by_indicator(self, sample_df):
        result = svc.apply_filters(sample_df, indicators=["NCD_MORTALITY"])
        assert (result["Indicator"] == "NCD_MORTALITY").all()

    def test_filter_by_year_range(self, sample_df):
        result = svc.apply_filters(sample_df, year_range=(2021, 2021))
        assert (result["Year"] == 2021).all()

    def test_filter_by_continent(self, sample_df):
        result = svc.apply_filters(sample_df, continents=["Africa"])
        assert (result["Continent"] == "Africa").all()

    def test_filter_by_country(self, sample_df):
        result = svc.apply_filters(sample_df, countries=["USA"])
        assert (result["CountryCode"] == "USA").all()

    def test_filter_by_gender(self, sample_df):
        result = svc.apply_filters(sample_df, genders=["Both sexes"])
        assert (result["Gender"] == "Both sexes").all()

    def test_empty_df(self, empty_df):
        result = svc.apply_filters(empty_df, indicators=["X"])
        assert result.empty

    def test_no_match_returns_empty(self, sample_df):
        result = svc.apply_filters(sample_df, indicators=["NONEXISTENT"])
        assert result.empty


# ================================================================
# KPIs
# ================================================================

class TestKPIs:
    def test_kpis_basic(self, sample_df):
        kpis = svc.compute_kpis(sample_df, sample_df, 2020)
        assert kpis["n_countries"] >= 1
        assert kpis["selected_year"] == 2020
        assert kpis["n_records"] > 0

    def test_kpis_empty(self, empty_df):
        kpis = svc.compute_kpis(empty_df, empty_df, 2020)
        assert kpis["n_countries"] == 0

    def test_reporting_coverage(self, sample_df):
        kpis = svc.compute_kpis(sample_df, sample_df, 2020)
        assert 0 <= kpis["reporting_coverage_pct"] <= 100

    def test_missing_value_rate(self):
        df = pd.DataFrame({
            "CountryCode": ["A", "B", "C"],
            "Year": [2020, 2020, 2020],
            "Gender": ["Both sexes"] * 3,
            "Indicator": ["X"] * 3,
            "Value": [1.0, None, 3.0],
            "Continent": ["Europe"] * 3,
        })
        kpis = svc.compute_kpis(df, df, 2020)
        assert 30 <= kpis["missing_value_rate_pct"] <= 40


# ================================================================
# Aggregation
# ================================================================

class TestAggregation:
    def test_unweighted_average(self, sample_df):
        avg = svc.compute_unweighted_average(sample_df, "NCD_MORTALITY", 2020)
        assert avg is not None
        assert abs(avg - (15 + 18 + 25) / 3) < 0.01

    def test_unweighted_average_missing_indicator(self, sample_df):
        avg = svc.compute_unweighted_average(sample_df, "NONEXISTENT", 2020)
        assert avg is None

    def test_population_weighted_no_data(self, sample_df):
        result = svc.compute_population_weighted_average(
            sample_df, "NCD_MORTALITY", 2020, population_df=None
        )
        assert result is None

    def test_population_weighted_with_data(self, sample_df):
        pop_df = pd.DataFrame({
            "CountryCode": ["USA", "GBR", "NGA"],
            "Year": [2020, 2020, 2020],
            "Population": [330_000_000, 67_000_000, 206_000_000],
        })
        result = svc.compute_population_weighted_average(
            sample_df, "NCD_MORTALITY", 2020, population_df=pop_df
        )
        assert result is not None
        expected = (15 * 330 + 18 * 67 + 25 * 206) / (330 + 67 + 206)
        assert abs(result - expected) < 0.1


# ================================================================
# Analytical view builders
# ================================================================

class TestGeospatial:
    def test_basic(self, sample_df):
        result = svc.build_geospatial_data(sample_df, "NCD_MORTALITY", 2020)
        assert not result.empty
        assert "CountryCode" in result.columns
        assert "Value" in result.columns

    def test_deduplicates_gender(self, multi_gender_df):
        result = svc.build_geospatial_data(multi_gender_df, "NCD_MORTALITY", 2020)
        assert (result["Gender"] == "Both sexes").all()

    def test_no_data(self, sample_df):
        result = svc.build_geospatial_data(sample_df, "NCD_MORTALITY", 2099)
        assert result.empty


class TestRanking:
    def test_ranking_returns_sorted(self, sample_df):
        result = svc.build_ranking_data(sample_df, "NCD_MORTALITY", 2020, ascending=True)
        assert not result.empty
        assert "Rank" in result.columns
        assert result["Value"].iloc[0] <= result["Value"].iloc[-1]

    def test_top_n_limit(self, sample_df):
        result = svc.build_ranking_data(sample_df, "NCD_MORTALITY", 2020, top_n=2)
        assert len(result) <= 2


class TestTimeSeries:
    def test_basic(self, sample_df):
        ts = svc.build_time_series_data(sample_df, "NCD_MORTALITY")
        assert not ts.empty
        assert "Year" in ts.columns
        assert "mean" in ts.columns
        assert "std" in ts.columns
        assert "n_countries" in ts.columns

    def test_empty(self, sample_df):
        ts = svc.build_time_series_data(sample_df, "NONEXISTENT")
        assert ts.empty


class TestDistribution:
    def test_basic(self, sample_df):
        result = svc.build_distribution_data(sample_df, "NCD_MORTALITY", 2020)
        assert not result.empty


class TestCorrelation:
    def test_correlation(self, sample_df):
        merged, r = svc.build_correlation_data(
            sample_df, "NCD_MORTALITY", "UHC_COVERAGE", 2020
        )
        assert not merged.empty
        assert not np.isnan(r)
        assert -1 <= r <= 1

    def test_correlation_insufficient_data(self, sample_df):
        merged, r = svc.build_correlation_data(
            sample_df, "NCD_MORTALITY", "NONEXISTENT", 2020
        )
        assert merged.empty


class TestOLSTrendline:
    """The dependency-light replacement for plotly.express trendline='ols'."""

    def test_perfect_fit_recovers_slope_and_intercept(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [3.0 * v + 2.0 for v in x]
        trend = svc.compute_ols_trendline(x, y)

        assert trend is not None
        assert trend["slope"] == pytest.approx(3.0)
        assert trend["intercept"] == pytest.approx(2.0)
        assert trend["r_squared"] == pytest.approx(1.0)
        assert trend["n_observations"] == 5
        assert trend["n_dropped"] == 0
        assert "numpy.polyfit" in trend["method"]

    def test_line_endpoints_span_observed_x_range(self):
        x = [10.0, 20.0, 30.0, 40.0]
        y = [1.0, 2.5, 2.0, 4.0]
        trend = svc.compute_ols_trendline(x, y)

        assert trend is not None
        assert trend["x_line"][0] == pytest.approx(10.0)
        assert trend["x_line"][-1] == pytest.approx(40.0)
        assert len(trend["x_line"]) == len(trend["y_line"])
        assert np.all(np.isfinite(trend["y_line"]))

    def test_negative_slope_and_r_squared_bounds(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        y = [10.0, 8.5, 8.0, 6.5, 5.0, 4.0]
        trend = svc.compute_ols_trendline(x, y)

        assert trend is not None
        assert trend["slope"] < 0
        assert 0.0 <= trend["r_squared"] <= 1.0

    def test_missing_values_are_dropped_pairwise(self):
        x = [1.0, 2.0, np.nan, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, np.nan, 10.0]
        trend = svc.compute_ols_trendline(x, y)

        assert trend is not None
        assert trend["n_observations"] == 3
        assert trend["n_dropped"] == 2
        assert trend["slope"] == pytest.approx(2.0)

    def test_returns_none_below_minimum_observations(self):
        assert svc.compute_ols_trendline([1.0, 2.0], [3.0, 4.0]) is None
        assert svc.compute_ols_trendline([], []) is None

    def test_returns_none_when_all_values_missing(self):
        assert svc.compute_ols_trendline([np.nan] * 5, [np.nan] * 5) is None

    def test_returns_none_for_zero_variance_x(self):
        assert svc.compute_ols_trendline([5.0, 5.0, 5.0, 5.0], [1.0, 2.0, 3.0, 4.0]) is None

    def test_returns_none_on_mismatched_lengths(self):
        assert svc.compute_ols_trendline([1.0, 2.0, 3.0], [1.0, 2.0]) is None

    def test_handles_infinite_values_without_crashing(self):
        x = [1.0, 2.0, 3.0, 4.0, np.inf]
        y = [2.0, 4.0, 6.0, 8.0, 1.0]
        trend = svc.compute_ols_trendline(x, y)

        assert trend is not None
        assert trend["n_observations"] == 4
        assert trend["n_dropped"] == 1

    def test_accepts_pandas_series_from_correlation_data(self, sample_df):
        merged, _r = svc.build_correlation_data(
            sample_df, "NCD_MORTALITY", "UHC_COVERAGE", 2020
        )
        trend = svc.compute_ols_trendline(merged["Value_X"], merged["Value_Y"])

        assert trend is not None
        assert trend["n_observations"] == len(merged)

    def test_minimum_observations_constant_is_three(self):
        assert svc.MIN_CORRELATION_OBSERVATIONS == 3


class TestCountryProfile:
    def test_basic(self, sample_df):
        profile = svc.build_country_profile(sample_df, "USA")
        assert not profile.empty
        assert (profile["CountryCode"] == "USA").all()

    def test_missing_country(self, sample_df):
        profile = svc.build_country_profile(sample_df, "ZZZ")
        assert profile.empty


# ================================================================
# Quality / metadata / summary / export
# ================================================================

class TestQualityReport:
    def test_basic(self, sample_df):
        report = svc.compute_quality_report(sample_df)
        assert "overall_score" in report
        assert 0 <= report["overall_score"] <= 100

    def test_empty(self, empty_df):
        report = svc.compute_quality_report(empty_df)
        assert report["overall_score"] == 0


class TestMetadata:
    def test_metadata_keys(self, sample_df):
        db_meta = {
            "extraction_date": "2026-01-01",
            "loaded_at": "now",
            "row_count": 9,
            "status": "ok",
            "db_path": "/tmp/x",
        }
        meta = svc.get_data_source_metadata(db_meta, sample_df)
        assert "source" in meta
        assert "year_range" in meta
        assert "total_records" in meta


class TestBuildSummary:
    def test_basic(self, sample_df):
        summary = svc.build_data_summary(sample_df, {})
        assert "records" in summary.lower()
        assert "countries" in summary.lower()

    def test_empty(self, empty_df):
        summary = svc.build_data_summary(empty_df, {})
        assert "no data" in summary.lower()


class TestExportCSV:
    def test_returns_bytes(self, sample_df):
        result = svc.build_export_csv(sample_df)
        assert isinstance(result, bytes)
        assert b"CountryCode" in result
