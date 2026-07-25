"""
Reusable data quality utilities for WHO health indicator datasets.

The functions in this module return structured dictionaries/lists and do not
print to stdout. They are intended for reuse by the ETL pipeline, Streamlit
services, and generated notebooks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:  # Supports execution with PYTHONPATH=src
    from who_health_intelligence.etl.metadata import COUNTRY_CONTINENT_MAP
except ModuleNotFoundError:  # Supports tests/imports as src.data_quality
    from src.who_health_intelligence.etl.metadata import COUNTRY_CONTINENT_MAP


DEFAULT_REQUIRED_COLUMNS: Tuple[str, ...] = (
    "CountryCode",
    "Year",
    "Gender",
    "Indicator",
    "Value",
)

DEFAULT_SCHEMA: Dict[str, str] = {
    "CountryCode": "string",
    "Country": "string",
    "Year": "integer",
    "Gender": "string",
    "Indicator": "string",
    "IndicatorCode": "string",
    "Value": "numeric",
    "Continent": "string",
}

DEFAULT_RECORD_KEY: Tuple[str, ...] = (
    "CountryCode",
    "Year",
    "Gender",
    "Indicator",
    "IndicatorCode",
)

DEFAULT_VALUE_RANGES: Dict[str, Dict[str, float]] = {
    "LIFE_EXPECTANCY": {"min": 0.0, "max": 120.0},
    "NCD_MORTALITY": {"min": 0.0, "max": 100.0},
    "UHC_COVERAGE": {"min": 0.0, "max": 100.0},
    "MATERNAL_MORTALITY": {"min": 0.0, "max": 5000.0},
    "INFANT_MORTALITY": {"min": 0.0, "max": 500.0},
}


def _sample_records(df: pd.DataFrame, limit: int = 10) -> List[Dict[str, Any]]:
    """Return a JSON-serializable sample of rows from a DataFrame."""
    if df.empty:
        return []
    sample = df.head(limit).replace({np.nan: None})
    return sample.to_dict(orient="records")


def _json_default(value: Any) -> Any:
    """JSON serializer for pandas/numpy scalar values."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return str(value)


def validate_required_columns(
    df: pd.DataFrame,
    required_columns: Sequence[str] = DEFAULT_REQUIRED_COLUMNS,
) -> Dict[str, Any]:
    """Validate that required columns are present."""
    present = list(df.columns)
    missing = [col for col in required_columns if col not in df.columns]
    return {
        "is_valid": len(missing) == 0,
        "required_columns": list(required_columns),
        "present_columns": present,
        "missing_columns": missing,
        "extra_columns": [col for col in present if col not in required_columns],
    }


def validate_data_types(
    df: pd.DataFrame,
    expected_types: Mapping[str, str] = DEFAULT_SCHEMA,
) -> Dict[str, Any]:
    """
    Validate DataFrame column types.

    Supported expected type labels: ``numeric``, ``integer``, ``string``,
    ``datetime``, ``boolean``, and ``category``.
    """
    columns: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for column, expected in expected_types.items():
        if column not in df.columns:
            continue

        series = df[column]
        actual_dtype = str(series.dtype)
        expected_norm = expected.lower()
        non_null = series.dropna()

        if expected_norm == "numeric":
            coerced = pd.to_numeric(non_null, errors="coerce")
            invalid_count = int(coerced.isna().sum())
            valid = invalid_count == 0
        elif expected_norm == "integer":
            coerced = pd.to_numeric(non_null, errors="coerce")
            invalid_numeric = coerced.isna()
            non_integer = ~np.isclose(coerced.dropna() % 1, 0)
            invalid_count = int(invalid_numeric.sum() + non_integer.sum())
            valid = invalid_count == 0
        elif expected_norm == "string":
            invalid_count = int(non_null.map(lambda x: not isinstance(x, str)).sum())
            is_categorical = isinstance(series.dtype, pd.CategoricalDtype)
            valid = invalid_count == 0 or pd.api.types.is_string_dtype(series) or is_categorical
            if is_categorical:
                invalid_count = 0
        elif expected_norm == "datetime":
            coerced = pd.to_datetime(non_null, errors="coerce")
            invalid_count = int(coerced.isna().sum())
            valid = invalid_count == 0
        elif expected_norm == "boolean":
            valid_values = {True, False, 0, 1, "true", "false", "True", "False"}
            invalid_count = int(non_null.map(lambda x: x not in valid_values).sum())
            valid = invalid_count == 0
        elif expected_norm == "category":
            invalid_count = 0
            valid = isinstance(series.dtype, pd.CategoricalDtype)
        else:
            invalid_count = 0
            valid = True

        columns[column] = {
            "expected_type": expected,
            "actual_dtype": actual_dtype,
            "is_valid": bool(valid),
            "invalid_count": invalid_count,
        }
        if not valid:
            errors.append(
                f"Column '{column}' expected {expected}, found {invalid_count} invalid values "
                f"(dtype={actual_dtype})"
            )

    return {"is_valid": len(errors) == 0, "columns": columns, "errors": errors}


def validate_schema(
    df: pd.DataFrame,
    required_columns: Sequence[str] = DEFAULT_REQUIRED_COLUMNS,
    expected_types: Mapping[str, str] = DEFAULT_SCHEMA,
) -> Dict[str, Any]:
    """Run required-column and data-type validation together."""
    required = validate_required_columns(df, required_columns)
    type_schema = {k: v for k, v in expected_types.items() if k in df.columns}
    types = validate_data_types(df, type_schema)
    errors = []
    if required["missing_columns"]:
        errors.append(f"Missing required columns: {required['missing_columns']}")
    errors.extend(types["errors"])
    return {
        "is_valid": required["is_valid"] and types["is_valid"],
        "required_columns": required,
        "data_types": types,
        "errors": errors,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
    }


def profile_missing_values(df: pd.DataFrame) -> Dict[str, Any]:
    """Profile missing values by column and overall."""
    row_count = len(df)
    column_count = len(df.columns)
    total_cells = row_count * column_count
    total_missing = int(df.isna().sum().sum()) if total_cells else 0

    per_column: Dict[str, Dict[str, Any]] = {}
    for column in df.columns:
        missing = int(df[column].isna().sum())
        pct = round((missing / row_count) * 100, 2) if row_count else 0.0
        per_column[column] = {
            "missing_count": missing,
            "missing_percentage": pct,
            "non_missing_count": int(row_count - missing),
            "completeness_percentage": round(100.0 - pct, 2),
        }

    completeness = round((1 - total_missing / total_cells) * 100, 2) if total_cells else 0.0
    return {
        "row_count": int(row_count),
        "column_count": int(column_count),
        "total_cells": int(total_cells),
        "total_missing": total_missing,
        "overall_completeness_pct": completeness,
        "per_column": per_column,
    }


def detect_duplicates(
    df: pd.DataFrame,
    subset: Optional[Sequence[str]] = None,
    sample_limit: int = 10,
) -> Dict[str, Any]:
    """Detect full-row duplicates and key-level duplicates."""
    full_mask = df.duplicated(keep="first")
    available_subset = [col for col in (subset or DEFAULT_RECORD_KEY) if col in df.columns]
    key_mask = df.duplicated(subset=available_subset, keep="first") if available_subset else full_mask

    duplicate_rows = df[full_mask]
    duplicate_keys = df[key_mask]
    return {
        "duplicate_rows": int(full_mask.sum()),
        "duplicate_pct": round((int(full_mask.sum()) / len(df)) * 100, 2) if len(df) else 0.0,
        "key_columns": available_subset,
        "duplicate_key_rows": int(key_mask.sum()),
        "has_duplicates": bool(full_mask.any() or key_mask.any()),
        "sample_duplicate_rows": _sample_records(duplicate_rows, sample_limit),
        "sample_duplicate_key_rows": _sample_records(duplicate_keys, sample_limit),
    }


def detect_invalid_numeric_values(
    df: pd.DataFrame,
    numeric_columns: Sequence[str] = ("Value",),
    value_ranges: Optional[Mapping[str, Mapping[str, float]]] = DEFAULT_VALUE_RANGES,
    indicator_column: str = "Indicator",
    sample_limit: int = 10,
) -> Dict[str, Any]:
    """Detect non-numeric, missing, infinite, and out-of-range numeric values."""
    results: Dict[str, Any] = {"columns": {}, "invalid_value_count": 0, "sample_invalid_rows": []}
    invalid_indices: set[int] = set()

    for column in numeric_columns:
        if column not in df.columns:
            results["columns"][column] = {"exists": False, "invalid_count": 0}
            continue

        raw = df[column]
        coerced = pd.to_numeric(raw, errors="coerce")
        missing_mask = raw.isna()
        non_numeric_mask = coerced.isna() & ~missing_mask
        finite_mask = pd.Series(np.isfinite(coerced), index=df.index).fillna(False)
        infinite_mask = coerced.notna() & ~finite_mask
        invalid_mask = missing_mask | non_numeric_mask | infinite_mask

        below_count = 0
        above_count = 0
        range_issues: Dict[str, Dict[str, Any]] = {}
        if value_ranges and indicator_column in df.columns:
            for indicator, bounds in value_ranges.items():
                indicator_mask = df[indicator_column] == indicator
                if not indicator_mask.any():
                    continue
                min_value = bounds.get("min")
                max_value = bounds.get("max")
                below_mask = indicator_mask & coerced.notna() & (coerced < min_value) if min_value is not None else pd.Series(False, index=df.index)
                above_mask = indicator_mask & coerced.notna() & (coerced > max_value) if max_value is not None else pd.Series(False, index=df.index)
                below = int(below_mask.sum())
                above = int(above_mask.sum())
                if below or above:
                    range_issues[indicator] = {
                        "min": min_value,
                        "max": max_value,
                        "below_min_count": below,
                        "above_max_count": above,
                    }
                below_count += below
                above_count += above
                invalid_mask = invalid_mask | below_mask | above_mask

        indices = set(df.index[invalid_mask].tolist())
        invalid_indices.update(indices)
        invalid_count = int(invalid_mask.sum())
        results["columns"][column] = {
            "exists": True,
            "missing_count": int(missing_mask.sum()),
            "non_numeric_count": int(non_numeric_mask.sum()),
            "infinite_count": int(infinite_mask.sum()),
            "below_min_count": below_count,
            "above_max_count": above_count,
            "invalid_count": invalid_count,
            "range_issues": range_issues,
        }

    results["invalid_value_count"] = len(invalid_indices)
    results["is_valid"] = len(invalid_indices) == 0
    if invalid_indices:
        results["sample_invalid_rows"] = _sample_records(df.loc[sorted(invalid_indices)], sample_limit)
    return results


def validate_year_range(
    df: pd.DataFrame,
    year_column: str = "Year",
    min_year: int = 1900,
    max_year: int = 2030,
) -> Dict[str, Any]:
    """Validate year values and report temporal coverage/gaps."""
    if year_column not in df.columns:
        return {
            "is_valid": False,
            "error": f"Missing year column: {year_column}",
            "years_covered": 0,
            "year_range": (None, None),
            "year_gaps": [],
            "has_gaps": False,
            "invalid_year_count": 0,
        }

    coerced = pd.to_numeric(df[year_column], errors="coerce")
    invalid_mask = coerced.isna() | ~np.isclose(coerced.dropna().reindex(coerced.index).fillna(0) % 1, 0)
    below_mask = coerced.notna() & (coerced < min_year)
    above_mask = coerced.notna() & (coerced > max_year)
    valid_years = sorted(int(y) for y in coerced[~invalid_mask & ~below_mask & ~above_mask].dropna().unique())

    if valid_years:
        expected = set(range(min(valid_years), max(valid_years) + 1))
        gaps = sorted(expected - set(valid_years))
        year_range: Tuple[Optional[int], Optional[int]] = (min(valid_years), max(valid_years))
    else:
        gaps = []
        year_range = (None, None)

    invalid_count = int((invalid_mask | below_mask | above_mask).sum())
    return {
        "is_valid": invalid_count == 0,
        "years_covered": len(valid_years),
        "year_range": year_range,
        "year_gaps": [int(y) for y in gaps],
        "has_gaps": len(gaps) > 0,
        "min_allowed_year": int(min_year),
        "max_allowed_year": int(max_year),
        "below_min_count": int(below_mask.sum()),
        "above_max_count": int(above_mask.sum()),
        "invalid_year_count": invalid_count,
    }


def validate_country_codes(
    df: pd.DataFrame,
    country_column: str = "CountryCode",
    valid_country_codes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Validate country codes against a supplied or default ISO-like mapping."""
    if country_column not in df.columns:
        return {"is_valid": False, "error": f"Missing country column: {country_column}", "invalid_codes": []}

    valid_codes = set(valid_country_codes or COUNTRY_CONTINENT_MAP.keys())
    codes = sorted(str(code) for code in df[country_column].dropna().unique())
    invalid_codes = [code for code in codes if code not in valid_codes]
    malformed_codes = [code for code in codes if len(code) != 3 or not code.isalpha() or not code.isupper()]
    return {
        "is_valid": len(invalid_codes) == 0,
        "country_count": len(codes),
        "valid_country_count": len(codes) - len(invalid_codes),
        "invalid_country_count": len(invalid_codes),
        "invalid_codes": invalid_codes,
        "malformed_codes": malformed_codes,
    }


def analyze_indicator_coverage(
    df: pd.DataFrame,
    indicator_column: str = "Indicator",
    country_column: str = "CountryCode",
    year_column: str = "Year",
) -> Dict[str, Any]:
    """Analyze country-year coverage for each indicator."""
    required = {indicator_column, country_column, year_column}
    if df.empty or not required.issubset(df.columns):
        return {"indicators": {}, "overall_coverage_pct": 0.0, "error": "Insufficient columns or empty data" if df.empty else "Missing required coverage columns"}

    country_count = int(df[country_column].nunique())
    year_count = int(df[year_column].nunique())
    max_possible = country_count * year_count
    indicators: Dict[str, Dict[str, Any]] = {}

    for indicator in sorted(str(i) for i in df[indicator_column].dropna().unique()):
        subset = df[df[indicator_column].astype(str) == indicator]
        actual_pairs = int(subset[[country_column, year_column]].drop_duplicates().shape[0])
        coverage_pct = round((actual_pairs / max_possible) * 100, 1) if max_possible else 0.0
        years = sorted(int(y) for y in pd.to_numeric(subset[year_column], errors="coerce").dropna().unique())
        indicators[indicator] = {
            "row_count": int(len(subset)),
            "country_count": int(subset[country_column].nunique()),
            "year_count": int(subset[year_column].nunique()),
            "country_year_pairs": actual_pairs,
            "max_possible_country_year_pairs": int(max_possible),
            "coverage_pct": coverage_pct,
            "year_range": (min(years), max(years)) if years else (None, None),
        }

    overall = round(sum(item["coverage_pct"] for item in indicators.values()) / len(indicators), 1) if indicators else 0.0
    return {"indicators": indicators, "overall_coverage_pct": overall}


def report_unmapped_countries(
    df: pd.DataFrame,
    country_column: str = "CountryCode",
    continent_column: str = "Continent",
    valid_country_codes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Report countries that are not mapped to a known continent/country list."""
    if country_column not in df.columns:
        return {"count": 0, "codes": [], "details": []}

    valid_codes = set(valid_country_codes or COUNTRY_CONTINENT_MAP.keys())
    if continent_column in df.columns:
        continent = df[continent_column].astype(str).str.strip()
        unmapped_mask = continent.isin(["", "Unknown", "nan", "None", "NaN"])
        unmapped_codes = set(str(code) for code in df.loc[unmapped_mask, country_column].dropna().unique())
    else:
        unmapped_codes = set()

    unmapped_codes.update(str(code) for code in df[country_column].dropna().unique() if str(code) not in valid_codes)
    codes = sorted(unmapped_codes)
    details = []
    for code in codes:
        subset = df[df[country_column].astype(str) == code]
        details.append({
            "country_code": code,
            "row_count": int(len(subset)),
            "indicators": sorted(str(i) for i in subset["Indicator"].dropna().unique()) if "Indicator" in subset.columns else [],
        })
    return {"count": len(codes), "codes": codes, "details": details}


def _indicator_summary(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if "Indicator" not in df.columns or "Value" not in df.columns:
        return []

    summaries: List[Dict[str, Any]] = []
    numeric_values = pd.to_numeric(df["Value"], errors="coerce")
    working = df.copy()
    working["_numeric_value"] = numeric_values
    for indicator in sorted(str(i) for i in working["Indicator"].dropna().unique()):
        subset = working[working["Indicator"].astype(str) == indicator]
        values = subset["_numeric_value"].dropna()
        summaries.append({
            "indicator": indicator,
            "row_count": int(len(subset)),
            "country_count": int(subset["CountryCode"].nunique()) if "CountryCode" in subset.columns else 0,
            "year_count": int(subset["Year"].nunique()) if "Year" in subset.columns else 0,
            "value_mean": round(float(values.mean()), 4) if len(values) else None,
            "value_min": round(float(values.min()), 4) if len(values) else None,
            "value_max": round(float(values.max()), 4) if len(values) else None,
            "value_std": round(float(values.std()), 4) if len(values) else None,
            "null_count": int(subset["Value"].isna().sum()),
        })
    return summaries


def _geographic_coverage(df: pd.DataFrame) -> Dict[str, Any]:
    if "CountryCode" not in df.columns:
        return {"countries": 0, "continents": 0, "has_aggregate_records": False, "expected_countries": len(COUNTRY_CONTINENT_MAP)}
    return {
        "countries": int(df["CountryCode"].nunique()),
        "continents": int(df["Continent"].nunique()) if "Continent" in df.columns else 0,
        "has_aggregate_records": bool(df["CountryCode"].isin(["GLOBAL", "WORLD"]).any()),
        "expected_countries": len(COUNTRY_CONTINENT_MAP),
    }


def _overview(df: pd.DataFrame) -> Dict[str, Any]:
    years = pd.to_numeric(df["Year"], errors="coerce").dropna() if "Year" in df.columns else pd.Series(dtype=float)
    return {
        "total_rows": int(len(df)),
        "total_columns": int(len(df.columns)),
        "memory_usage_mb": round(float(df.memory_usage(deep=True).sum()) / 1024**2, 2) if not df.empty else 0,
        "indicators": int(df["Indicator"].nunique()) if "Indicator" in df.columns else 0,
        "countries": int(df["CountryCode"].nunique()) if "CountryCode" in df.columns else 0,
        "year_range": (int(years.min()), int(years.max())) if not years.empty else (None, None),
    }


def _overall_score(summary: Mapping[str, Any]) -> float:
    completeness = float(summary["completeness"].get("overall_completeness_pct", 0.0))
    duplicate_pct = float(summary["consistency"].get("duplicate_pct", 0.0))
    consistency_score = 100.0 if not summary["consistency"].get("has_duplicates") and not summary["consistency"].get("type_issues") else max(0.0, 100.0 - duplicate_pct * 10)
    geographic = summary["geographic_coverage"]
    expected_countries = max(int(geographic.get("expected_countries", 1)), 1)
    coverage_score = min(100.0, float(geographic.get("countries", 0)) / expected_countries * 100.0)
    invalid_count = int(summary["accuracy"].get("invalid_value_count", 0))
    accuracy_score = 100.0 if invalid_count == 0 else max(0.0, 100.0 - invalid_count * 0.1)
    return round(completeness * 0.35 + consistency_score * 0.25 + coverage_score * 0.25 + accuracy_score * 0.15, 1)


def generate_data_quality_summary(
    df: pd.DataFrame,
    required_columns: Sequence[str] = DEFAULT_REQUIRED_COLUMNS,
    expected_types: Mapping[str, str] = DEFAULT_SCHEMA,
    min_year: int = 1900,
    max_year: int = 2030,
) -> Dict[str, Any]:
    """Generate a structured end-to-end data quality summary."""
    schema = validate_schema(df, required_columns=required_columns, expected_types=expected_types)
    missing = profile_missing_values(df)
    duplicates = detect_duplicates(df)
    numeric = detect_invalid_numeric_values(df)
    years = validate_year_range(df, min_year=min_year, max_year=max_year)
    countries = validate_country_codes(df)
    coverage_analysis = analyze_indicator_coverage(df)
    coverage = {
        "indicators": {
            indicator: details.get("coverage_pct", 0.0)
            for indicator, details in coverage_analysis.get("indicators", {}).items()
        },
        "details": coverage_analysis.get("indicators", {}),
        "overall_coverage_pct": coverage_analysis.get("overall_coverage_pct", 0.0),
    }
    if "error" in coverage_analysis:
        coverage["error"] = coverage_analysis["error"]
    unmapped = report_unmapped_countries(df)

    consistency = {
        "duplicate_rows": duplicates["duplicate_rows"],
        "duplicate_pct": duplicates["duplicate_pct"],
        "duplicate_key_rows": duplicates["duplicate_key_rows"],
        "type_issues": schema["data_types"]["errors"],
        "has_duplicates": duplicates["has_duplicates"],
        "is_consistent": not duplicates["has_duplicates"] and len(schema["data_types"]["errors"]) == 0,
    }
    accuracy = {
        "issues": [
            f"{col}: {info['invalid_count']} invalid values"
            for col, info in numeric["columns"].items()
            if info.get("invalid_count", 0) > 0
        ],
        "invalid_value_count": numeric["invalid_value_count"],
        "invalid_numeric_values": numeric,
        "year_range_validation": years,
        "country_code_validation": countries,
        "is_accurate": numeric["invalid_value_count"] == 0 and years.get("is_valid", False) and countries.get("is_valid", False),
    }

    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_validation": schema,
        "overview": _overview(df),
        "completeness": {
            "overall_completeness_pct": missing["overall_completeness_pct"],
            "total_null_cells": missing["total_missing"],
            "per_column": {
                column: {
                    "null_count": values["missing_count"],
                    "null_percentage": values["missing_percentage"],
                    "completeness_score": values["completeness_percentage"],
                }
                for column, values in missing["per_column"].items()
            },
            "missing_value_profile": missing,
        },
        "consistency": consistency,
        "accuracy": accuracy,
        "indicator_summary": _indicator_summary(df),
        "indicator_coverage": coverage,
        "temporal_coverage": years,
        "geographic_coverage": _geographic_coverage(df),
        "unmapped_countries": unmapped,
    }
    summary["overall_score"] = _overall_score(summary)
    return summary


def export_json_report(report: Mapping[str, Any], output_path: str | Path, indent: int = 2) -> Path:
    """Export a structured data quality report to JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=indent, default=_json_default), encoding="utf-8")
    return path


class DataQualityReport:
    """Compatibility wrapper around the reusable quality functions."""

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def generate_full_report(self) -> Dict[str, Any]:
        """Generate a complete structured data quality report."""
        return generate_data_quality_summary(self.df)

    def to_json(self, output_path: str | Path) -> Path:
        """Export the full report to JSON."""
        return export_json_report(self.generate_full_report(), output_path)

    def to_markdown(self) -> str:
        """Generate a markdown-formatted quality report."""
        report = self.generate_full_report()
        overview = report["overview"]
        temporal = report["temporal_coverage"]
        unmapped = report["unmapped_countries"]
        unmapped_preview = ", ".join(unmapped["codes"][:5])
        if len(unmapped["codes"]) > 5:
            unmapped_preview += "..."

        lines = [
            "# WHO Health Data Quality Report",
            f"**Generated:** {report['generated_at']}",
            f"**Overall Score:** {report['overall_score']}/100",
            "",
            "## Dataset Overview",
            f"- Total rows: {overview['total_rows']:,}",
            f"- Indicators: {overview['indicators']}",
            f"- Countries: {overview['countries']}",
            f"- Year range: {overview['year_range'][0]}-{overview['year_range'][1]}",
            f"- Memory usage: {overview['memory_usage_mb']:.2f} MB",
            "",
            "## Completeness",
            f"- Overall: {report['completeness']['overall_completeness_pct']}%",
            f"- Total null cells: {report['completeness']['total_null_cells']:,}",
            "",
            "## Consistency",
            f"- Duplicate rows: {report['consistency']['duplicate_rows']}",
            f"- Duplicate key rows: {report['consistency']['duplicate_key_rows']}",
            f"- Type issues: {len(report['consistency']['type_issues'])}",
            "",
            "## Accuracy",
            f"- Invalid numeric values: {report['accuracy']['invalid_value_count']}",
            f"- Year validation passed: {report['accuracy']['year_range_validation']['is_valid']}",
            f"- Country-code validation passed: {report['accuracy']['country_code_validation']['is_valid']}",
            "",
            "## Geographic Coverage",
            f"- Countries: {report['geographic_coverage']['countries']}",
            f"- Continents: {report['geographic_coverage']['continents']}",
            f"- Unmapped countries: {unmapped['count']} ({unmapped_preview})",
            "",
            "## Temporal Coverage",
            f"- Years covered: {temporal['years_covered']}",
            f"- Year range: {temporal['year_range'][0]}-{temporal['year_range'][1]}",
            f"- Year gaps: {temporal['year_gaps'] if temporal['has_gaps'] else 'None'}",
            "",
            "## Indicator Coverage",
            f"- Overall coverage: {report['indicator_coverage']['overall_coverage_pct']}%",
            "",
            "## Indicator Summary",
            "| Indicator | Rows | Countries | Mean | Min | Max |",
            "|-----------|------|-----------|------|-----|-----|",
        ]
        for item in report["indicator_summary"]:
            lines.append(
                f"| {item['indicator']} | {item['row_count']:,} | {item['country_count']} | "
                f"{item['value_mean']} | {item['value_min']} | {item['value_max']} |"
            )
        return "\n".join(lines)
