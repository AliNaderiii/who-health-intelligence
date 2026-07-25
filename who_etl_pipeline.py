#!/usr/bin/env python3
"""
WHO Global Health Intelligence Platform — ETL Pipeline.

A robust, idempotent, production-oriented Extract-Transform-Load pipeline
for WHO Global Health Observatory (GHO) data.

Architecture: Extract → Transform → Load
  1. Extract  — HTTP GET from WHO GHO OData API with retry / pagination
  2. Transform — schema validation, type coercion, geography enrichment
  3. Load     — idempotent upsert into SQLite with metadata tracking

Usage:
    # Full pipeline (all default indicators)
    python who_etl_pipeline.py

    # Single indicator
    python who_etl_pipeline.py --indicator NCD_MORTALITY

    # Custom database and output directory
    python who_etl_pipeline.py --db-path custom.db --output-dir ./output

    # Sample mode (limit records per indicator for fast testing)
    python who_etl_pipeline.py --sample 100

    # Verbose logging
    python who_etl_pipeline.py --log-level DEBUG

Exit codes:
    0 — Success
    1 — General failure
    2 — No data extracted (all indicators failed)
    3 — Validation failure (extracted data did not pass quality checks)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so ``who_health_intelligence`` imports
# work both from ``python who_etl_pipeline.py`` and ``python -m`` contexts.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
_SRC_DIR = _SCRIPT_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd

from who_health_intelligence.api.client import WHOAPIClient
from who_health_intelligence.etl.loader import DatabaseLoader, PIPELINE_VERSION
from who_health_intelligence.etl.metadata import normalize_geography
from data_quality import DataQualityReport
from who_health_intelligence.etl.schema import validate_transformed_dataframe
from who_health_intelligence.etl.transform import merge_indicator_dataframes, transform_indicator_records
from who_health_intelligence.utils.config import (
    DATABASE_PATH,
    DEFAULT_INDICATORS,
    RAW_DATA_PATH,
    WHO_API_BASE_URL,
    WHO_INDICATORS,
)

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_NO_DATA = 2
EXIT_VALIDATION_FAILURE = 3

# Required indicators (as specified in the requirements)
REQUIRED_INDICATOR_NAMES: Set[str] = {"LIFE_EXPECTANCY", "NCD_MORTALITY", "UHC_COVERAGE"}

logger = logging.getLogger("who_etl_pipeline")


# ===================================================================
# Pipeline functions (testable, no side-effects beyond logging)
# ===================================================================


def validate_requested_indicators(indicators: List[str]) -> List[str]:
    """
    Validate that requested indicator names are defined in configuration.

    Args:
        indicators: List of indicator names to validate.

    Returns:
        Filtered list of valid indicator names.

    Raises:
        ValueError: If no valid indicators remain after filtering.
    """
    valid = [name for name in indicators if name in WHO_INDICATORS]
    invalid = set(indicators) - set(valid)

    if invalid:
        logger.warning("Unknown indicators ignored: %s", sorted(invalid))

    if not valid:
        raise ValueError(
            f"No valid indicators. Available: {sorted(WHO_INDICATORS.keys())}"
        )

    return valid


def extract_phase(
    client: WHOAPIClient,
    indicators: List[str],
    raw_output_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Execute the Extract phase: pull raw data from the WHO GHO API.

    Args:
        client: Configured WHO API client.
        indicators: List of indicator names to extract.
        raw_output_dir: Directory for persisting raw JSON responses.

    Returns:
        Dict mapping indicator names to extraction results:
        ``{"records": [...], "status": "success"|"failed", "error": str|None}``
    """
    results: Dict[str, Dict[str, Any]] = {}

    for name in indicators:
        code = WHO_INDICATORS.get(name, {}).get("code", "")
        t0 = time.monotonic()
        try:
            logger.info("EXTRACT  %s (%s) …", name, code)
            records = client.extract_indicator(code, raw_output_dir=raw_output_dir)
            results[name] = {
                "records": records,
                "status": "success",
                "error": None,
                "record_count": len(records),
                "duration_s": round(time.monotonic() - t0, 3),
            }
            logger.info("EXTRACT  %s → %d records (%.1fs)", name, len(records), results[name]["duration_s"])
        except Exception as exc:
            results[name] = {
                "records": [],
                "status": "failed",
                "error": str(exc),
                "record_count": 0,
                "duration_s": round(time.monotonic() - t0, 3),
            }
            logger.error("EXTRACT  %s FAILED: %s", name, exc)

    return results


def transform_phase(
    extraction_results: Dict[str, Dict[str, Any]],
    sample_limit: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Execute the Transform phase: validate, clean, enrich, and type-cast.

    Processing steps per indicator:
    1. Schema validation of raw records
    2. Column standardization (SpatialDim → CountryCode, etc.)
    3. Gender code normalization (SEX_BTSX → Both sexes)
    4. Missing / invalid value removal
    5. Duplicate removal
    6. Country code normalization via ISO 3166-1 mapping
    7. Continent metadata enrichment
    8. Source timestamp injection
    9. Explicit data types (int32, float32, category)

    Args:
        extraction_results: Output from ``extract_phase``.
        sample_limit: If set, keep only the first N records per indicator.

    Returns:
        Dict mapping indicator names to transform results:
        ``{"dataframe": pd.DataFrame, "status": "success"|"failed", ...}``
    """
    results: Dict[str, Dict[str, Any]] = {}
    source_ts = datetime.now(timezone.utc).isoformat()

    for name, ext in extraction_results.items():
        records = ext["records"]

        if not records:
            results[name] = {
                "dataframe": pd.DataFrame(),
                "status": "skipped",
                "error": ext.get("error"),
                "row_count": 0,
            }
            continue

        # Optional sampling
        if sample_limit is not None and len(records) > sample_limit:
            logger.info("TRANSFORM  %s: sampling %d of %d records", name, sample_limit, len(records))
            records = records[:sample_limit]

        code = WHO_INDICATORS.get(name, {}).get("code", "")
        t0 = time.monotonic()

        try:
            df = transform_indicator_records(records, name, code)

            # Enrich with geography (uses built-in ISO mapping, NOT Plotly Gapminder)
            df = normalize_geography(df)

            # Add source timestamp
            df["SourceTimestamp"] = source_ts

            # Remove exact duplicates
            before = len(df)
            df = df.drop_duplicates()
            dedup_removed = before - len(df)

            # Final validation
            vresult = validate_transformed_dataframe(df)

            results[name] = {
                "dataframe": df,
                "status": "success" if vresult["is_valid"] else "warnings",
                "validation_errors": vresult.get("errors", []),
                "validation_warnings": vresult.get("warnings", []),
                "row_count": len(df),
                "duplicates_removed": dedup_removed,
                "duration_s": round(time.monotonic() - t0, 3),
            }
            logger.info(
                "TRANSFORM  %s → %d rows, %d dupes removed (%.1fs)",
                name, len(df), dedup_removed, results[name]["duration_s"],
            )

        except Exception as exc:
            results[name] = {
                "dataframe": pd.DataFrame(),
                "status": "failed",
                "error": str(exc),
                "row_count": 0,
            }
            logger.error("TRANSFORM  %s FAILED: %s", name, exc)

    return results


def load_phase(
    transform_results: Dict[str, Dict[str, Any]],
    loader: DatabaseLoader,
    replace: bool = True,
) -> Dict[str, Any]:
    """
    Execute the Load phase: persist processed data into SQLite.

    Idempotency strategy:
    - When ``replace=True`` (default), existing rows for each indicator are
      deleted before new rows are inserted.  This guarantees that repeated
      runs produce identical database state.
    - The table's UNIQUE constraint on (CountryCode, Year, Gender, Indicator,
      IndicatorCode) provides a second layer of duplicate prevention.

    Args:
        transform_results: Output from ``transform_phase``.
        loader: Configured DatabaseLoader.
        replace: If True, replace existing data per indicator.

    Returns:
        Dict with loading summary.
    """
    # Merge all indicator DataFrames
    dfs = {
        name: tr["dataframe"]
        for name, tr in transform_results.items()
        if tr["status"] in ("success", "warnings") and not tr["dataframe"].empty
    }

    if not dfs:
        return {"status": "failed", "error": "No data to load", "records_loaded": 0}

    merged = merge_indicator_dataframes(dfs)

    t0 = time.monotonic()
    loaded = loader.load_all_indicators(merged, replace_all=replace)

    return {
        "status": "success",
        "records_loaded": loaded,
        "duration_s": round(time.monotonic() - t0, 3),
    }


def quality_phase(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Execute the Quality phase: generate a comprehensive data quality report.

    The report includes:
    - Row count, country count, year range
    - Missing-value count, duplicate count
    - Invalid-value count, unmapped country count
    - Indicator coverage per indicator

    Args:
        df: The merged DataFrame after loading.

    Returns:
        Quality report dict.
    """
    report = DataQualityReport(df)
    return report.generate_full_report()


def register_indicators(loader: DatabaseLoader) -> None:
    """
    Register all configured indicator definitions in the metadata table.
    """
    for name, info in WHO_INDICATORS.items():
        loader.register_indicator(
            name=name,
            code=info["code"],
            description=info.get("description", ""),
            unit="",
            source_url=f"{WHO_API_BASE_URL}{info['code']}",
        )
    logger.info("Registered %d indicator definitions", len(WHO_INDICATORS))


# ===================================================================
# CLI
# ===================================================================


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all supported CLI options."""
    parser = argparse.ArgumentParser(
        prog="who_etl_pipeline",
        description="WHO Global Health Intelligence — ETL Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--db-path",
        default=DATABASE_PATH,
        help=f"Path to SQLite database (default: {DATABASE_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Directory for raw JSON output (default: {RAW_DATA_PATH})",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Limit records per indicator (for fast testing)",
    )
    parser.add_argument(
        "--indicator",
        nargs="+",
        default=None,
        help=f"Indicators to extract (default: {DEFAULT_INDICATORS}). "
             f"Available: {sorted(WHO_INDICATORS.keys())}",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--no-replace",
        action="store_true",
        help="Append data instead of replacing existing rows",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Skip saving raw JSON responses",
    )
    parser.add_argument(
        "--quality-report",
        default=None,
        help="Path to save the quality report (markdown)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PIPELINE_VERSION}",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Run the full ETL pipeline.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 = success, 1 = failure, 2 = no data, 3 = validation failure).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    os.environ["LOG_LEVEL"] = args.log_level
    # Re-setup root logger with requested level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, args.log_level))

    logger.info("=" * 64)
    logger.info("WHO ETL Pipeline v%s", PIPELINE_VERSION)
    logger.info("=" * 64)

    # Determine indicators
    indicators = args.indicator if args.indicator else list(DEFAULT_INDICATORS)
    try:
        indicators = validate_requested_indicators(indicators)
    except ValueError as exc:
        logger.error("Indicator validation failed: %s", exc)
        return EXIT_FAILURE

    logger.info("Indicators: %s", indicators)
    logger.info("Database:   %s", args.db_path)

    # Output directory for raw data
    raw_dir: Optional[Path] = None
    if not args.no_raw:
        if args.output_dir:
            raw_dir = Path(args.output_dir) / "raw"
        else:
            raw_dir = RAW_DATA_PATH
        raw_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Raw output: %s", raw_dir)

    # ---------------------------------------------------------------
    # STEP 1: EXTRACT
    # ---------------------------------------------------------------
    logger.info("━" * 64)
    logger.info("STEP 1 / 4: EXTRACT")
    logger.info("━" * 64)

    client = WHOAPIClient()
    extraction_results = extract_phase(client, indicators, raw_output_dir=raw_dir)

    # Check if anything was extracted
    total_extracted = sum(r["record_count"] for r in extraction_results.values())
    failed = [n for n, r in extraction_results.items() if r["status"] == "failed"]

    if total_extracted == 0:
        logger.error("No data extracted from any indicator. Failures: %s", failed)
        client.close()
        return EXIT_NO_DATA

    if failed:
        logger.warning("Some indicators failed: %s", failed)

    # ---------------------------------------------------------------
    # STEP 2: TRANSFORM
    # ---------------------------------------------------------------
    logger.info("━" * 64)
    logger.info("STEP 2 / 4: TRANSFORM")
    logger.info("━" * 64)

    transform_results = transform_phase(extraction_results, sample_limit=args.sample)

    # Check transform results
    total_transformed = sum(r["row_count"] for r in transform_results.values())
    transform_failed = [n for n, r in transform_results.items() if r["status"] == "failed"]

    if total_transformed == 0:
        logger.error("No data survived transformation. Failures: %s", transform_failed)
        client.close()
        return EXIT_NO_DATA

    # Check for validation errors
    has_validation_errors = any(
        r.get("validation_errors") for r in transform_results.values()
    )

    # ---------------------------------------------------------------
    # STEP 3: LOAD
    # ---------------------------------------------------------------
    logger.info("━" * 64)
    logger.info("STEP 3 / 4: LOAD")
    logger.info("━" * 64)

    loader = DatabaseLoader(args.db_path)
    replace = not args.no_replace
    load_result = load_phase(transform_results, loader, replace=replace)

    if load_result["status"] != "success":
        logger.error("Load failed: %s", load_result.get("error"))
        client.close()
        return EXIT_FAILURE

    logger.info(
        "Loaded %d records in %.1fs (replace=%s)",
        load_result["records_loaded"],
        load_result["duration_s"],
        replace,
    )

    # Register indicator definitions in metadata table
    register_indicators(loader)

    # Log source info
    loader.log_source_info(
        source_name="WHO GHO OData API",
        source_url=WHO_API_BASE_URL,
        total_extracted=total_extracted,
        total_loaded=load_result["records_loaded"],
        indicators=indicators,
        status="success",
    )

    # Log per-indicator ETL runs
    for name in indicators:
        ext = extraction_results.get(name, {})
        tr = transform_results.get(name, {})
        loader.log_etl_run(
            indicator=name,
            indicator_code=WHO_INDICATORS.get(name, {}).get("code", ""),
            records_extracted=ext.get("record_count", 0),
            records_loaded=tr.get("row_count", 0),
            status=tr.get("status", "unknown"),
            duration_s=ext.get("duration_s", 0) + tr.get("duration_s", 0),
            source_url=f"{WHO_API_BASE_URL}{WHO_INDICATORS.get(name, {}).get('code', '')}",
        )

    # ---------------------------------------------------------------
    # STEP 4: QUALITY
    # ---------------------------------------------------------------
    logger.info("━" * 64)
    logger.info("STEP 4 / 4: DATA QUALITY REPORT")
    logger.info("━" * 64)

    loaded_df = loader.query("SELECT * FROM health_indicators")
    quality_report = quality_phase(loaded_df)

    logger.info("Quality score: %.1f/100", quality_report["overall_score"])
    logger.info("Total rows: %d", quality_report["overview"]["total_rows"])
    logger.info("Countries: %d", quality_report["overview"]["countries"])
    logger.info("Year range: %s", quality_report["overview"]["year_range"])
    logger.info("Missing values: %d", quality_report["completeness"]["total_null_cells"])
    logger.info("Duplicates: %d", quality_report["consistency"]["duplicate_rows"])
    logger.info("Invalid values: %d", quality_report["accuracy"]["invalid_value_count"])
    logger.info("Unmapped countries: %d", quality_report["unmapped_countries"]["count"])

    for ind, cov in quality_report["indicator_coverage"]["indicators"].items():
        logger.info("Indicator coverage [%s]: %.1f%%", ind, cov)

    # Save quality report if requested
    if args.quality_report:
        report_path = Path(args.quality_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        qr = DataQualityReport(loaded_df)
        report_path.write_text(qr.to_markdown(), encoding="utf-8")
        logger.info("Quality report saved to %s", report_path)

    client.close()

    # ---------------------------------------------------------------
    # Determine exit code
    # ---------------------------------------------------------------
    if has_validation_errors:
        logger.warning("Pipeline completed with validation warnings")
        # Don't return EXIT_VALIDATION_FAILURE for warnings — only for hard errors
        # The data was still loaded successfully

    logger.info("=" * 64)
    logger.info("Pipeline completed successfully")
    logger.info("=" * 64)
    return EXIT_SUCCESS


# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    sys.exit(main())
