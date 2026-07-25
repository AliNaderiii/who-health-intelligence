

"""Tests for reusable data quality functions."""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ================================================================
# Reusable src.data_quality function tests
# ================================================================

from src.data_quality import (
    detect_duplicates,
    detect_invalid_numeric_values,
    generate_data_quality_summary,
    profile_missing_values,
    validate_required_columns,
    validate_year_range,
)


def test_reusable_quality_missing_columns():
    df = pd.DataFrame({"CountryCode": ["USA"], "Year": [2020]})

    result = validate_required_columns(df)

    assert result["is_valid"] is False
    assert "Value" in result["missing_columns"]
    assert "Indicator" in result["missing_columns"]


def test_reusable_quality_invalid_numeric_values():
    df = pd.DataFrame(
        {
            "CountryCode": ["USA", "GBR", "FRA"],
            "Year": [2020, 2020, 2020],
            "Gender": ["Both sexes"] * 3,
            "Indicator": ["UHC_COVERAGE"] * 3,
            "Value": [95, "not-numeric", 150],
        }
    )

    result = detect_invalid_numeric_values(df)

    assert result["is_valid"] is False
    assert result["columns"]["Value"]["non_numeric_count"] == 1
    assert result["columns"]["Value"]["above_max_count"] == 1


def test_reusable_quality_duplicate_detection():
    df = pd.DataFrame(
        {
            "CountryCode": ["USA", "USA"],
            "Year": [2020, 2020],
            "Gender": ["Both sexes", "Both sexes"],
            "Indicator": ["LIFE_EXPECTANCY", "LIFE_EXPECTANCY"],
            "IndicatorCode": ["WHOSIS_000001", "WHOSIS_000001"],
            "Value": [78.5, 78.5],
        }
    )

    result = detect_duplicates(df)

    assert result["duplicate_rows"] == 1
    assert result["duplicate_key_rows"] == 1
    assert result["has_duplicates"] is True


def test_reusable_quality_year_range_and_empty_dataframe_behavior():
    empty = pd.DataFrame(columns=["CountryCode", "Year", "Gender", "Indicator", "Value"])
    empty_summary = generate_data_quality_summary(empty)

    assert empty_summary["overview"]["total_rows"] == 0
    assert empty_summary["overall_score"] >= 0

    df = pd.DataFrame({"Year": [1999, 2020, 2022]})
    years = validate_year_range(df, min_year=2000, max_year=2023)

    assert years["is_valid"] is False
    assert years["below_min_count"] == 1
    assert years["year_gaps"] == [2021]


def test_reusable_quality_missing_value_profile():
    df = pd.DataFrame({"a": [1, None], "b": [None, 2]})

    result = profile_missing_values(df)

    assert result["total_missing"] == 2
    assert result["overall_completeness_pct"] == 50.0
