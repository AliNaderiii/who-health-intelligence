"""
Data quality compatibility layer.

The reusable implementation lives in ``src/data_quality.py`` so it can be used
by the standalone ETL pipeline, dashboard services, and generated notebooks.
This module preserves the historical package import path:
``who_health_intelligence.etl.quality``.
"""

from __future__ import annotations

try:
    from data_quality import (  # type: ignore
        DEFAULT_RECORD_KEY,
        DEFAULT_REQUIRED_COLUMNS,
        DEFAULT_SCHEMA,
        DEFAULT_VALUE_RANGES,
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
except ModuleNotFoundError:
    from src.data_quality import (  # type: ignore
        DEFAULT_RECORD_KEY,
        DEFAULT_REQUIRED_COLUMNS,
        DEFAULT_SCHEMA,
        DEFAULT_VALUE_RANGES,
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

__all__ = [
    "DEFAULT_RECORD_KEY",
    "DEFAULT_REQUIRED_COLUMNS",
    "DEFAULT_SCHEMA",
    "DEFAULT_VALUE_RANGES",
    "DataQualityReport",
    "analyze_indicator_coverage",
    "detect_duplicates",
    "detect_invalid_numeric_values",
    "export_json_report",
    "generate_data_quality_summary",
    "profile_missing_values",
    "report_unmapped_countries",
    "validate_country_codes",
    "validate_data_types",
    "validate_required_columns",
    "validate_schema",
    "validate_year_range",
]
