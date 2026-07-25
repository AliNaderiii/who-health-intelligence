"""
Tests for the standalone ETL pipeline (who_etl_pipeline.py).

Tests the pipeline's core functions (validate, transform, load, quality)
independently of network access and the Streamlit dashboard.
"""

import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the pipeline module
sys.path.insert(0, str(PROJECT_ROOT))
import who_etl_pipeline as pipeline


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def sample_df():
    """Minimal valid health-indicator DataFrame."""
    return pd.DataFrame({
        "CountryCode": ["USA", "GBR", "NGA", "USA", "GBR", "NGA"],
        "Country": ["United States", "United Kingdom", "Nigeria"] * 2,
        "Year": [2020, 2020, 2020, 2021, 2021, 2021],
        "Gender": ["Both sexes"] * 6,
        "Indicator": ["NCD_MORTALITY"] * 6,
        "IndicatorCode": ["NCDMORT3070"] * 6,
        "IndicatorDescription": ["NCD mortality 30-70 (%)"] * 6,
        "Value": [15.0, 18.0, 25.0, 14.5, 17.5, 24.0],
        "Continent": ["Americas", "Europe", "Africa"] * 2,
    })


@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test.db")


# ================================================================
# validate_requested_indicators
# ================================================================

class TestValidateIndicators:
    def test_valid_indicators(self):
        result = pipeline.validate_requested_indicators(["NCD_MORTALITY", "UHC_COVERAGE"])
        assert result == ["NCD_MORTALITY", "UHC_COVERAGE"]

    def test_invalid_ignored(self):
        result = pipeline.validate_requested_indicators(["NCD_MORTALITY", "NONEXISTENT"])
        assert result == ["NCD_MORTALITY"]

    def test_all_invalid_raises(self):
        with pytest.raises(ValueError, match="No valid indicators"):
            pipeline.validate_requested_indicators(["FAKE_A", "FAKE_B"])

    def test_required_indicators_defined(self):
        """All 3 required indicators must be in WHO_INDICATORS."""
        for name in pipeline.REQUIRED_INDICATOR_NAMES:
            assert name in pipeline.WHO_INDICATORS


# ================================================================
# Transform phase
# ================================================================

class TestTransformPhase:
    def test_empty_extraction(self):
        results = {"TEST": {"records": [], "status": "failed", "error": "no data"}}
        out = pipeline.transform_phase(results)
        assert out["TEST"]["status"] == "skipped"
        assert out["TEST"]["dataframe"].empty

    def test_basic_transform(self):
        records = [
            {"SpatialDim": "USA", "TimeDim": 2020, "Dim1": "SEX_BTSX", "NumericValue": 78.5},
            {"SpatialDim": "GBR", "TimeDim": 2020, "Dim1": "SEX_FMLE", "NumericValue": 82.0},
        ]
        ext = {"LIFE_EXPECTANCY": {"records": records, "status": "success"}}
        out = pipeline.transform_phase(ext)

        assert out["LIFE_EXPECTANCY"]["status"] in ("success", "warnings")
        df = out["LIFE_EXPECTANCY"]["dataframe"]
        assert len(df) == 2
        assert "CountryCode" in df.columns
        assert "Continent" in df.columns
        assert "SourceTimestamp" in df.columns

    def test_sample_limit(self):
        records = [
            {"SpatialDim": f"C{i:03d}", "TimeDim": 2020, "Dim1": "SEX_BTSX", "NumericValue": 70.0 + i}
            for i in range(50)
        ]
        ext = {"LIFE_EXPECTANCY": {"records": records, "status": "success"}}
        out = pipeline.transform_phase(ext, sample_limit=10)

        df = out["LIFE_EXPECTANCY"]["dataframe"]
        assert len(df) <= 10


# ================================================================
# Load phase
# ================================================================

class TestLoadPhase:
    def test_load_basic(self, sample_df, temp_db):
        from who_health_intelligence.etl.loader import DatabaseLoader
        loader = DatabaseLoader(temp_db)

        transform_results = {
            "NCD_MORTALITY": {
                "dataframe": sample_df,
                "status": "success",
                "row_count": len(sample_df),
            }
        }

        result = pipeline.load_phase(transform_results, loader, replace=True)
        assert result["status"] == "success"
        assert result["records_loaded"] == 6

    def test_load_empty(self, temp_db):
        from who_health_intelligence.etl.loader import DatabaseLoader
        loader = DatabaseLoader(temp_db)

        transform_results = {
            "TEST": {"dataframe": pd.DataFrame(), "status": "failed", "row_count": 0}
        }
        result = pipeline.load_phase(transform_results, loader)
        assert result["status"] == "failed"

    def test_idempotent_reload(self, sample_df, temp_db):
        """Loading twice with replace should yield same row count."""
        from who_health_intelligence.etl.loader import DatabaseLoader
        loader = DatabaseLoader(temp_db)

        transform_results = {
            "NCD_MORTALITY": {
                "dataframe": sample_df,
                "status": "success",
                "row_count": len(sample_df),
            }
        }

        # First load
        r1 = pipeline.load_phase(transform_results, loader, replace=True)
        # Second load (same data, replace=True)
        r2 = pipeline.load_phase(transform_results, loader, replace=True)

        assert r1["records_loaded"] == r2["records_loaded"]

        # Verify total rows in DB
        info = loader.get_table_info()
        total = info["tables"]["health_indicators"]["row_count"]
        assert total == len(sample_df)


# ================================================================
# Quality phase
# ================================================================

class TestQualityPhase:
    def test_basic_quality(self, sample_df):
        report = pipeline.quality_phase(sample_df)
        assert "overall_score" in report
        assert 0 <= report["overall_score"] <= 100
        assert report["overview"]["total_rows"] == 6
        assert report["overview"]["countries"] == 3

    def test_quality_includes_all_required_fields(self, sample_df):
        report = pipeline.quality_phase(sample_df)
        # Required fields from the specification
        assert "total_rows" in report["overview"]  # row count
        assert "countries" in report["overview"]  # country count
        assert "year_range" in report["overview"]  # year range
        assert "total_null_cells" in report["completeness"]  # missing-value count
        assert "duplicate_rows" in report["consistency"]  # duplicate count
        assert "invalid_value_count" in report["accuracy"]  # invalid-value count
        assert "count" in report["unmapped_countries"]  # unmapped country count
        assert "indicator_coverage" in report  # indicator coverage


# ================================================================
# CLI argument parsing
# ================================================================

class TestCLI:
    def test_parser_default(self):
        parser = pipeline.build_parser()
        args = parser.parse_args([])
        assert args.log_level == "INFO"
        assert args.indicator is None
        assert args.sample is None
        assert args.no_replace is False

    def test_parser_custom_args(self):
        parser = pipeline.build_parser()
        args = parser.parse_args([
            "--db-path", "/tmp/test.db",
            "--indicator", "NCD_MORTALITY", "UHC_COVERAGE",
            "--sample", "100",
            "--log-level", "DEBUG",
            "--no-replace",
        ])
        assert args.db_path == "/tmp/test.db"
        assert args.indicator == ["NCD_MORTALITY", "UHC_COVERAGE"]
        assert args.sample == 100
        assert args.log_level == "DEBUG"
        assert args.no_replace is True


# ================================================================
# Exit codes
# ================================================================

class TestExitCodes:
    def test_exit_code_constants(self):
        assert pipeline.EXIT_SUCCESS == 0
        assert pipeline.EXIT_FAILURE == 1
        assert pipeline.EXIT_NO_DATA == 2
        assert pipeline.EXIT_VALIDATION_FAILURE == 3

    def test_api_failure_returns_no_data(self):
        """When API is unreachable, main() should return EXIT_NO_DATA."""
        exit_code = pipeline.main([
            "--db-path", "/tmp/test_exit.db",
            "--indicator", "NCD_MORTALITY",
            "--sample", "10",
        ])
        # API is unreachable in sandbox → EXIT_NO_DATA
        assert exit_code == pipeline.EXIT_NO_DATA

    def test_invalid_indicator_returns_failure(self):
        """Invalid indicator names should return EXIT_FAILURE."""
        exit_code = pipeline.main([
            "--db-path", "/tmp/test_invalid.db",
            "--indicator", "COMPLETELY_FAKE_INDICATOR",
        ])
        assert exit_code == pipeline.EXIT_FAILURE


# ================================================================
# Register indicators
# ================================================================

class TestRegisterIndicators:
    def test_registers_all(self, temp_db):
        from who_health_intelligence.etl.loader import DatabaseLoader
        loader = DatabaseLoader(temp_db)
        pipeline.register_indicators(loader)

        defs = loader.query("SELECT * FROM indicator_definitions")
        assert len(defs) == len(pipeline.WHO_INDICATORS)
        for name in pipeline.WHO_INDICATORS:
            assert name in defs["indicator_name"].values
