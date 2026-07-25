"""Tests for the reusable src.data_quality module."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_quality import (
    DataQualityReport,
    analyze_indicator_coverage,
    detect_duplicates,
    detect_invalid_numeric_values,
    export_json_report,
    generate_data_quality_summary,
    profile_missing_values,
    report_unmapped_countries,
    validate_country_codes,
    validate_data_types,
    validate_required_columns,
    validate_schema,
    validate_year_range,
)


def quality_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CountryCode": ["USA", "GBR", "FRA", "XXX", "USA"],
            "Country": ["United States", "United Kingdom", "France", "Unknown", "United States"],
            "Year": [2020, 2020, 2021, 1899, 2020],
            "Gender": ["Both sexes", "Both sexes", "Female", "Male", "Both sexes"],
            "Indicator": ["LIFE_EXPECTANCY", "LIFE_EXPECTANCY", "NCD_MORTALITY", "UHC_COVERAGE", "LIFE_EXPECTANCY"],
            "IndicatorCode": ["WHOSIS_000001", "WHOSIS_000001", "NCDMORT3070", "UHC_INDEX_REPORTED", "WHOSIS_000001"],
            "Value": [78.5, 81.0, -1.0, np.inf, 79.5],
            "Continent": ["Americas", "Europe", "Europe", "Unknown", "Americas"],
        }
    )


def test_required_column_validation_structured_result():
    df = quality_df().drop(columns=["Value"])
    result = validate_required_columns(df)

    assert result["is_valid"] is False
    assert result["missing_columns"] == ["Value"]
    assert "present_columns" in result


def test_data_type_validation_detects_invalid_values():
    df = quality_df().copy()
    df["Year"] = df["Year"].astype(object)
    df.loc[0, "Year"] = "not-a-year"

    result = validate_data_types(df, {"Year": "integer", "Value": "numeric"})

    assert result["is_valid"] is False
    assert result["columns"]["Year"]["invalid_count"] == 1
    assert result["errors"]


def test_schema_validation_combines_required_and_type_checks():
    df = quality_df().copy()
    df["Value"] = ["bad", "81", "20", "50", "78"]

    result = validate_schema(df)

    assert result["is_valid"] is False
    assert any("Value" in err for err in result["errors"])
    assert result["row_count"] == len(df)


def test_missing_value_profile():
    df = quality_df().copy()
    df.loc[1, "Country"] = None

    result = profile_missing_values(df)

    assert result["total_missing"] == 1
    assert result["per_column"]["Country"]["missing_count"] == 1
    assert result["overall_completeness_pct"] < 100


def test_duplicate_detection_for_full_rows_and_record_keys():
    df = quality_df()
    result = detect_duplicates(df)

    assert result["duplicate_rows"] == 0
    assert result["duplicate_key_rows"] == 1
    assert result["has_duplicates"] is True
    assert result["key_columns"]


def test_invalid_numeric_value_detection_includes_ranges_and_infinity():
    result = detect_invalid_numeric_values(quality_df())

    assert result["is_valid"] is False
    assert result["invalid_value_count"] >= 2
    assert result["columns"]["Value"]["infinite_count"] == 1
    assert result["columns"]["Value"]["below_min_count"] == 1


def test_year_range_validation_reports_out_of_range_and_gaps():
    result = validate_year_range(quality_df(), min_year=2000, max_year=2023)

    assert result["is_valid"] is False
    assert result["below_min_count"] == 1
    assert result["year_range"] == (2020, 2021)


def test_country_code_validation_and_unmapped_reporting():
    df = quality_df()

    country_result = validate_country_codes(df)
    unmapped = report_unmapped_countries(df)

    assert country_result["is_valid"] is False
    assert "XXX" in country_result["invalid_codes"]
    assert unmapped["count"] == 1
    assert unmapped["codes"] == ["XXX"]


def test_indicator_coverage_analysis():
    result = analyze_indicator_coverage(quality_df())

    assert result["overall_coverage_pct"] > 0
    assert "LIFE_EXPECTANCY" in result["indicators"]
    assert result["indicators"]["LIFE_EXPECTANCY"]["row_count"] == 3


def test_data_quality_summary_generation_and_wrapper():
    df = quality_df()

    summary = generate_data_quality_summary(df, min_year=2000, max_year=2023)
    wrapper_summary = DataQualityReport(df).generate_full_report()

    for key in ["schema_validation", "completeness", "consistency", "accuracy", "indicator_coverage", "unmapped_countries", "overall_score"]:
        assert key in summary
        assert key in wrapper_summary
    assert 0 <= summary["overall_score"] <= 100


def test_json_report_export(tmp_path):
    report = generate_data_quality_summary(quality_df(), min_year=2000, max_year=2023)
    output = export_json_report(report, tmp_path / "quality" / "report.json")

    assert output.exists()
    loaded = json.loads(output.read_text())
    assert loaded["overview"]["total_rows"] == 5
    assert "generated_at" in loaded
