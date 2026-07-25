"""
Live data quality reporting for WHO Health Intelligence Platform.

Generates comprehensive data-quality report as required:

- Extraction timestamp in UTC
- API response status
- Indicator status
- Number of raw records
- Number of processed records
- Number of countries
- Number of years
- Year range
- Missing values
- Invalid numeric values
- Duplicate rows
- Duplicate key groups
- Unmapped countries
- Out-of-range values
- Indicator coverage
- API latency
- Total extraction duration

Saves as reports/data_quality_report.json
Also stores latest report in database (data_quality_results table)

Fail or warn clearly when quality thresholds not met.
Don't label as verified unless checks passed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..utils.config import REPORTS_DIR, setup_logging, WHO_INDICATORS
from .metadata import get_mapping_coverage_report

try:
    from data_quality import (
        generate_data_quality_summary,
        detect_duplicates,
        detect_invalid_numeric_values,
        profile_missing_values,
        report_unmapped_countries,
        analyze_indicator_coverage,
    )
except ModuleNotFoundError:
    from src.data_quality import (
        generate_data_quality_summary,
        detect_duplicates,
        detect_invalid_numeric_values,
        profile_missing_values,
        report_unmapped_countries,
        analyze_indicator_coverage,
    )

logger = setup_logging(__name__)


def generate_live_quality_report(
    df: pd.DataFrame,
    extraction_metadata: Dict[str, Any],
    data_mode: str = "live",
) -> Dict[str, Any]:
    """
    Generate full live data-quality report combining ETL metadata and data profiling.

    Args:
        df: processed DataFrame (after transform + geography normalization)
        extraction_metadata: dict with:
            - extraction_timestamp_utc (str)
            - api_status (dict indicator -> status code or overall)
            - indicator_status (dict indicator -> success/failed + record counts)
            - raw_records (int total raw from API)
            - processed_records (int after transform)
            - api_latency_seconds (float total)
            - total_duration_seconds (float total pipeline)
            - api_calls (int)
            - pages_fetched (int)
        data_mode: live/demo/stale

    Returns:
        Comprehensive dict report with all required fields
    """
    extraction_ts = extraction_metadata.get(
        "extraction_timestamp_utc", datetime.now(timezone.utc).isoformat()
    )

    # Basic counts from df
    # Support both snake and legacy column names
    country_col = "country_code" if "country_code" in df.columns else "CountryCode" if "CountryCode" in df.columns else None
    year_col = "year" if "year" in df.columns else "Year" if "Year" in df.columns else None
    value_col = "value" if "value" in df.columns else "Value" if "Value" in df.columns else "Value"
    indicator_col = "indicator" if "indicator" in df.columns else "Indicator" if "Indicator" in df.columns else "Indicator"

    n_countries = 0
    n_years = 0
    year_range: tuple = (None, None)
    if not df.empty:
        if country_col:
            n_countries = int(df[country_col].nunique())
        if year_col:
            years_series = pd.to_numeric(df[year_col], errors="coerce").dropna()
            if not years_series.empty:
                n_years = int(years_series.nunique())
                year_range = (int(years_series.min()), int(years_series.max()))

    # Use reusable data_quality functions for deep profiling
    summary = generate_data_quality_summary(df)

    # Extract required sub-metrics
    completeness = summary.get("completeness", {})
    missing_values = completeness.get("total_null_cells", 0)

    # Invalid numeric
    invalid_info = summary.get("accuracy", {}).get("invalid_numeric_values", {})
    invalid_numeric = invalid_info.get("invalid_value_count", 0) if isinstance(invalid_info, dict) else 0

    # Duplicates
    consistency = summary.get("consistency", {})
    duplicate_rows = consistency.get("duplicate_rows", 0)
    duplicate_key_groups = consistency.get("duplicate_key_rows", 0)

    # Duplicate detection using explicit function for key groups
    dup_report = detect_duplicates(df)
    duplicate_rows = dup_report.get("duplicate_rows", duplicate_rows)
    duplicate_key_groups = dup_report.get("duplicate_key_rows", duplicate_key_groups)

    # Unmapped countries
    unmapped_report = report_unmapped_countries(df)
    mapping_coverage = get_mapping_coverage_report(df)

    # Out-of-range values: collect from invalid_numeric range_issues
    out_of_range = 0
    range_issues = {}
    if isinstance(invalid_info, dict) and "columns" in invalid_info:
        for col, info in invalid_info["columns"].items():
            if isinstance(info, dict):
                out_of_range += info.get("below_min_count", 0) + info.get("above_max_count", 0)
                if info.get("range_issues"):
                    range_issues[col] = info["range_issues"]

    # Indicator coverage
    indicator_coverage_raw = analyze_indicator_coverage(df)
    indicator_coverage = indicator_coverage_raw.get("indicators", {}) if isinstance(indicator_coverage_raw, dict) else {}

    # Build final report
    raw_records = extraction_metadata.get("raw_records", extraction_metadata.get("total_raw", 0))
    processed_records = len(df)

    # API status handling
    api_status = extraction_metadata.get("api_status", "unknown")
    indicator_status = extraction_metadata.get("indicator_status", {})

    # Overall quality score from summary
    overall_score = summary.get("overall_score", 0.0)

    report: Dict[str, Any] = {
        "extraction_timestamp_utc": extraction_ts,
        "extraction_timestamp": extraction_ts,
        "data_mode": data_mode,
        "api_status": api_status,
        "api_response_status": api_status,
        "indicator_status": indicator_status,
        "raw_records": raw_records,
        "number_of_raw_records": raw_records,
        "processed_records": processed_records,
        "number_of_processed_records": processed_records,
        "countries": n_countries,
        "number_of_countries": n_countries,
        "years": n_years,
        "number_of_years": n_years,
        "year_range": year_range,
        "year_range_str": f"{year_range[0]}–{year_range[1]}" if year_range[0] and year_range[1] else "N/A",
        "missing_values": missing_values,
        "invalid_numeric_values": invalid_numeric,
        "invalid_numeric": invalid_numeric,
        "duplicate_rows": duplicate_rows,
        "duplicate_key_groups": duplicate_key_groups,
        "unmapped_countries": {
            "count": unmapped_report.get("count", 0),
            "codes": unmapped_report.get("codes", []),
            "details": unmapped_report.get("details", []),
            "mapping_coverage": mapping_coverage,
        },
        "out_of_range_values": out_of_range,
        "out_of_range_details": range_issues,
        "indicator_coverage": indicator_coverage,
        "indicator_coverage_overall_pct": summary.get("indicator_coverage", {}).get("overall_coverage_pct", 0.0)
        if isinstance(summary.get("indicator_coverage"), dict)
        else 0.0,
        "api_latency_seconds": extraction_metadata.get("api_latency_seconds", 0.0),
        "api_latency": extraction_metadata.get("api_latency_seconds", 0.0),
        "total_duration_seconds": extraction_metadata.get("total_duration_seconds", 0.0),
        "total_extraction_duration": extraction_metadata.get("total_duration_seconds", 0.0),
        "api_calls": extraction_metadata.get("api_calls", 0),
        "pages_fetched": extraction_metadata.get("pages_fetched", 0),
        "overall_score": overall_score,
        "quality_score": overall_score,
        "is_verified": overall_score >= 80 and missing_values == 0 and invalid_numeric == 0 and duplicate_rows == 0,
        "verification_status": "verified" if overall_score >= 80 else "warnings" if overall_score >= 50 else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": extraction_metadata.get("pipeline_version", "4.0.0"),
        "thresholds": {
            "min_overall_score": 50,
            "max_null_pct": 5.0,
            "max_duplicate_pct": 1.0,
        },
        # Include full underlying summary for deep inspection
        "full_data_quality_summary": summary,
    }

    # Determine quality verdict
    issues = []
    if overall_score < 50:
        issues.append(f"Overall quality score {overall_score} below threshold 50")
    if duplicate_rows > 0:
        issues.append(f"Found {duplicate_rows} duplicate rows")
    if invalid_numeric > 0:
        issues.append(f"Found {invalid_numeric} invalid numeric values")
    if missing_values > 0:
        # Calculate missing percentage
        total_cells = df.shape[0] * df.shape[1] if not df.empty else 1
        missing_pct = (missing_values / total_cells * 100) if total_cells else 0
        if missing_pct > 5:
            issues.append(f"Missing values {missing_values} ({missing_pct:.1f}%) exceeds 5% threshold")

    report["quality_issues"] = issues
    report["has_critical_issues"] = len([i for i in issues if "score" in i.lower() or "invalid" in i.lower()]) > 0

    return report


def save_quality_report_json(report: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
    """
    Save report as reports/data_quality_report.json as required.
    """
    if output_path is None:
        output_path = REPORTS_DIR / "data_quality_report.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info(f"Saved data quality report JSON to {output_path} (score={report.get('overall_score')})")
    return output_path


def fail_or_warn_on_quality(report: Dict[str, Any]) -> str:
    """
    Determine if pipeline should fail or warn based on quality thresholds.
    Returns: "pass", "warn", "fail"
    """
    score = report.get("overall_score", 0)
    if score < 30:
        return "fail"
    elif score < 50 or report.get("has_critical_issues"):
        return "warn"
    else:
        return "pass"
