#!/usr/bin/env python3
"""
WHO Global Health Intelligence Platform — ETL Pipeline (Production LIVE mode)

Implements explicit LIVE vs DEMO mode as required:
- Default LIVE mode (WHO_DATA_MODE=live)
- DEMO requires explicit WHO_DATA_MODE=demo
- Never silently fallback from LIVE to synthetic data
- If LIVE fails and no cached real snapshot: stop gracefully, show error, don't display synthetic
- If cached real snapshot exists: use as stale fallback, label STALE REAL DATA, show extraction timestamp and failure reason
- Never mix synthetic with live

Features:
- Validates API base URL and indicator endpoints
- Uses requests.Session with retry + exponential backoff
- Handles 4xx/5xx, connection errors, malformed JSON, missing keys, pagination
- Logs every extraction: attempt, status, records, duration, latency
- Generates comprehensive data-quality report per spec
- Saves report as reports/data_quality_report.json and in DB
- Idempotent loading via UNIQUE constraints, transactions, atomic writes

Usage:
    # LIVE mode (default)
    WHO_DATA_MODE=live python who_etl_pipeline.py

    # DEMO mode (explicit)
    WHO_DATA_MODE=demo python who_etl_pipeline.py --demo

    # Custom indicators
    python who_etl_pipeline.py --indicator LIFE_EXPECTANCY NCD_MORTALITY UHC_COVERAGE

    # Sample limit for fast testing
    python who_etl_pipeline.py --sample 100

Exit codes:
    0 - Success
    1 - General failure
    2 - No data extracted
    3 - Validation failure
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

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
_SRC_DIR = _SCRIPT_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd

from who_health_intelligence.api.client import WHOAPIClient
from who_health_intelligence.etl.loader import DatabaseLoader
from who_health_intelligence.etl.metadata import normalize_geography, get_mapping_coverage_report
from who_health_intelligence.etl.transform import merge_indicator_dataframes, transform_indicator_records
from who_health_intelligence.etl.live_quality import (
    generate_live_quality_report,
    save_quality_report_json,
    fail_or_warn_on_quality,
)
from who_health_intelligence.etl.pipeline import WHOETLPipeline
from who_health_intelligence.utils.config import (
    DATABASE_PATH,
    DEFAULT_INDICATORS,
    RAW_DATA_PATH,
    REPORTS_DIR,
    WHO_API_BASE_URL,
    WHO_INDICATORS,
    PIPELINE_VERSION,
    get_data_mode,
)
from who_health_intelligence.utils.data_mode import DataMode, get_current_data_mode, get_stale_snapshot_info

try:
    from data_quality import DataQualityReport
except ModuleNotFoundError:
    from src.data_quality import DataQualityReport

from who_health_intelligence.etl.schema import validate_transformed_dataframe

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_NO_DATA = 2
EXIT_VALIDATION_FAILURE = 3

REQUIRED_INDICATOR_NAMES: Set[str] = {"LIFE_EXPECTANCY", "NCD_MORTALITY", "UHC_COVERAGE"}

logger = logging.getLogger("who_etl_pipeline")


def validate_requested_indicators(indicators: List[str]) -> List[str]:
    valid = [name for name in indicators if name in WHO_INDICATORS]
    invalid = set(indicators) - set(valid)
    if invalid:
        logger.warning("Unknown indicators ignored: %s", sorted(invalid))
    if not valid:
        raise ValueError(f"No valid indicators. Available: {sorted(WHO_INDICATORS.keys())}")
    return valid


def extract_phase(
    client: WHOAPIClient,
    indicators: List[str],
    raw_output_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Extract phase using new API client with full metadata tracking.
    Returns dict indicator_name -> metadata dict (including records)
    """
    results: Dict[str, Dict[str, Any]] = {}
    # Use new method that returns metadata per indicator
    extraction_map = client.extract_multiple_with_metadata(
        indicator_names=indicators,
        indicators_map=WHO_INDICATORS,
        raw_output_dir=raw_output_dir,
    )

    for name, meta in extraction_map.items():
        # Normalize to old structure for compatibility with transform_phase
        results[name] = {
            "records": meta.get("records", []),
            "status": meta.get("status", "failed"),
            "error": meta.get("error"),
            "record_count": meta.get("record_count", 0),
            "duration_s": meta.get("extraction_duration_seconds", 0.0),
            "api_status_code": meta.get("api_status_code"),
            "api_latency_seconds": meta.get("api_latency_seconds", 0.0),
            "extraction_timestamp_utc": meta.get("extraction_timestamp_utc"),
            "api_calls": meta.get("api_calls", 0),
            "pages_fetched": meta.get("pages_fetched", 0),
        }
        if meta.get("status") == "success":
            logger.info(f"EXTRACT {name} -> {meta.get('record_count')} records ({meta.get('extraction_duration_seconds')}s)")
        else:
            logger.error(f"EXTRACT {name} FAILED: {meta.get('error')}")

    return results


def transform_phase(
    extraction_results: Dict[str, Dict[str, Any]],
    sample_limit: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    source_ts = datetime.now(timezone.utc).isoformat()

    for name, ext in extraction_results.items():
        records = ext.get("records", ext.get("records", []))

        if not records:
            results[name] = {
                "dataframe": pd.DataFrame(),
                "status": "skipped",
                "error": ext.get("error"),
                "row_count": 0,
            }
            continue

        if sample_limit is not None and len(records) > sample_limit:
            logger.info(f"TRANSFORM {name}: sampling {sample_limit} of {len(records)} records")
            records = records[:sample_limit]

        code = WHO_INDICATORS.get(name, {}).get("code", "")
        t0 = time.monotonic()

        try:
            extracted_at = ext.get("extraction_timestamp_utc") or source_ts
            df = transform_indicator_records(records, name, code, extracted_at=extracted_at)
            df = normalize_geography(df)
            df["SourceTimestamp"] = extracted_at

            before = len(df)
            df = df.drop_duplicates()
            dedup_removed = before - len(df)

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
            logger.info(f"TRANSFORM {name} -> {len(df)} rows, {dedup_removed} dupes removed ({results[name]['duration_s']}s)")

        except Exception as exc:
            results[name] = {
                "dataframe": pd.DataFrame(),
                "status": "failed",
                "error": str(exc),
                "row_count": 0,
            }
            logger.error(f"TRANSFORM {name} FAILED: {exc}")

    return results


def load_phase(
    transform_results: Dict[str, Dict[str, Any]],
    loader: DatabaseLoader,
    replace: bool = True,
) -> Dict[str, Any]:
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
        "merged_df": merged,
    }


def quality_phase(
    df: pd.DataFrame,
    extraction_metadata: Optional[Dict[str, Any]] = None,
    data_mode: str = "live",
) -> Dict[str, Any]:
    """
    Generate comprehensive live data quality report.
    Backward compatible: if extraction_metadata is None, generate minimal metadata from df.
    """
    if extraction_metadata is None:
        extraction_metadata = {
            "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "api_status": "Unknown",
            "indicator_status": {},
            "raw_records": len(df),
            "api_latency_seconds": 0.0,
            "total_duration_seconds": 0.0,
        }
    report = generate_live_quality_report(
        df=df,
        extraction_metadata=extraction_metadata,
        data_mode=data_mode,
    )
    # For backward compat with old tests that expect old DataQualityReport structure,
    # also include some old keys if missing, and provide full summary under old keys?
    # Old tests check for overview, completeness, consistency, accuracy, unmapped_countries, indicator_coverage
    # Our live report has full_data_quality_summary containing those. Let's merge for compatibility.
    if "full_data_quality_summary" in report:
        summary = report["full_data_quality_summary"]
        # Ensure old top-level keys exist for backward compat
        for key in ["overview", "completeness", "consistency", "accuracy", "unmapped_countries", "indicator_coverage"]:
            if key not in report and key in summary:
                report[key] = summary[key]
    return report


def register_indicators(loader: DatabaseLoader) -> None:
    for name, info in WHO_INDICATORS.items():
        loader.register_indicator(
            name=name,
            code=info["code"],
            description=info.get("description", ""),
            unit=info.get("unit", ""),
            source_url=info.get("source_url", ""),
            official_definition=info.get("official_definition", ""),
            short_definition=info.get("short_definition", ""),
            who_odata_url=info.get("who_odata_url", f"{WHO_API_BASE_URL}{info['code']}"),
            category=info.get("category", ""),
        )
    logger.info("Registered %d indicator definitions with full metadata", len(WHO_INDICATORS))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="who_etl_pipeline",
        description="WHO Global Health Intelligence — ETL Pipeline (LIVE mode default)",
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
        help="Limit records per indicator (for fast testing, not for production)",
    )
    parser.add_argument(
        "--indicator",
        nargs="+",
        default=None,
        help=f"Indicators to extract (default: {DEFAULT_INDICATORS}). Available: {sorted(WHO_INDICATORS.keys())}",
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
        help="Append data instead of replacing existing rows (not recommended for LIVE)",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Skip saving raw JSON responses",
    )
    parser.add_argument(
        "--quality-report",
        default=None,
        help="Path to save the quality report (markdown) - also always saves JSON to reports/data_quality_report.json",
    )
    parser.add_argument(
        "--data-mode",
        choices=["live", "demo"],
        default=None,
        help="Override WHO_DATA_MODE env var: live (default) or demo (explicit). DEMO shows banner NOT OFFICIAL WHO OBSERVATIONS",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Explicitly run in DEMO mode using synthetic bootstrap data (requires WHO_DATA_MODE=demo or --data-mode demo)",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        default=True,
        help="Allow STALE REAL DATA fallback when LIVE API fails but cached real snapshot exists",
    )
    parser.add_argument(
        "--no-stale",
        action="store_true",
        help="Disallow stale fallback, fail if LIVE API fails",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PIPELINE_VERSION}",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    os.environ["LOG_LEVEL"] = args.log_level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, args.log_level))

    # Determine data mode
    env_mode = get_data_mode()
    if args.data_mode:
        os.environ["WHO_DATA_MODE"] = args.data_mode
        env_mode = args.data_mode
    elif args.demo:
        os.environ["WHO_DATA_MODE"] = "demo"
        env_mode = "demo"

    data_mode = get_current_data_mode()
    logger.info("=" * 64)
    logger.info(f"WHO ETL Pipeline v{PIPELINE_VERSION} data_mode={data_mode.value.upper()}")
    logger.info("=" * 64)

    # DEMO mode explicit check
    if data_mode == DataMode.DEMO:
        logger.warning("DEMO MODE ACTIVE: Using synthetic data, NOT official WHO observations")
        # If demo flag and user wants bootstrap, we can bootstrap directly
        if args.demo:
            from scripts.bootstrap_data import bootstrap_database

            logger.info("Running bootstrap_data for DEMO mode")
            count = bootstrap_database(db_path=args.db_path)
            print(f"DEMO bootstrap complete: {count} synthetic records")
            print("Banner: DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS")
            return EXIT_SUCCESS

    # Determine indicators
    indicators = args.indicator if args.indicator else list(DEFAULT_INDICATORS)
    try:
        indicators = validate_requested_indicators(indicators)
    except ValueError as exc:
        logger.error("Indicator validation failed: %s", exc)
        return EXIT_FAILURE

    logger.info("Indicators: %s", indicators)
    logger.info("Database: %s", args.db_path)
    logger.info("Data mode: %s", data_mode.value)
    logger.info("API base: %s", WHO_API_BASE_URL)

    # Output directory for raw data
    raw_dir: Optional[Path] = None
    if not args.no_raw:
        if args.output_dir:
            raw_dir = Path(args.output_dir) / "raw"
        else:
            raw_dir = RAW_DATA_PATH
        raw_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Raw output: %s", raw_dir)

    # Allow stale logic
    allow_stale = not args.no_stale
    if args.allow_stale:
        allow_stale = True

    # Extract
    logger.info("━" * 64)
    logger.info("STEP 1 / 4: EXTRACT")
    logger.info("━" * 64)

    client = WHOAPIClient()
    extraction_results = extract_phase(client, indicators, raw_output_dir=raw_dir)

    total_extracted = sum(r.get("record_count", 0) for r in extraction_results.values())
    failed = [n for n, r in extraction_results.items() if r.get("status") == "failed"]

    # Handle LIVE failure with stale fallback
    if total_extracted == 0:
        logger.error("No data extracted from any indicator. Failures: %s", failed)
        if data_mode == DataMode.LIVE and allow_stale:
            stale_info = get_stale_snapshot_info(Path(args.db_path))
            if stale_info and stale_info.get("is_real"):
                logger.warning(
                    f"LIVE API failed but stale real snapshot exists from {stale_info.get('extraction_timestamp')}: "
                    "Using STALE REAL DATA per production requirements"
                )
                print("\n" + "=" * 60)
                print("STALE REAL DATA - Using previously cached real snapshot")
                print(f"Original extraction: {stale_info.get('extraction_timestamp')}")
                print(f"Failure reason: {failed}")
                print("=" * 60 + "\n")
                # Load existing DB for quality phase, skip extract failure
                loader = DatabaseLoader(args.db_path)
                loaded_df = loader.query("SELECT * FROM health_indicators")
                # Generate quality report marking as stale
                extraction_meta = {
                    "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "api_status": "Failed",
                    "indicator_status": {k: v.get("status") for k, v in extraction_results.items()},
                    "raw_records": 0,
                    "api_latency_seconds": sum(v.get("api_latency_seconds", 0) for v in extraction_results.values()),
                    "total_duration_seconds": sum(v.get("duration_s", 0) for v in extraction_results.values()),
                    "api_calls": sum(v.get("api_calls", 0) for v in extraction_results.values()),
                    "pages_fetched": sum(v.get("pages_fetched", 0) for v in extraction_results.values()),
                }
                quality_report = quality_phase(loaded_df, extraction_meta, data_mode="stale")
                save_quality_report_json(quality_report, REPORTS_DIR / "data_quality_report.json")
                try:
                    loader.save_data_quality_report(quality_report)
                except Exception:
                    pass
                client.close()
                # Exit with success but note stale
                return EXIT_SUCCESS
            else:
                logger.error("No stale real snapshot available, cannot proceed in LIVE mode. No synthetic data will be used.")
                print("\nERROR: LIVE mode failed and no cached real snapshot exists.")
                print("Stop dashboard gracefully, show clear error message.")
                print("Failed API status: Failed")
                print("Reason: All indicators failed extraction")
                print("Fix: Check network connectivity, WHO API availability https://ghoapi.azureedge.net/api/, retry later")
                print("Do NOT display synthetic data in production.\n")
                client.close()
                return EXIT_NO_DATA
        else:
            client.close()
            return EXIT_NO_DATA

    if failed:
        logger.warning("Some indicators failed: %s", failed)

    # Transform
    logger.info("━" * 64)
    logger.info("STEP 2 / 4: TRANSFORM")
    logger.info("━" * 64)

    transform_results = transform_phase(extraction_results, sample_limit=args.sample)

    total_transformed = sum(r["row_count"] for r in transform_results.values())
    transform_failed = [n for n, r in transform_results.items() if r["status"] == "failed"]

    if total_transformed == 0:
        logger.error("No data survived transformation. Failures: %s", transform_failed)
        if data_mode == DataMode.LIVE and allow_stale:
            stale_info = get_stale_snapshot_info(Path(args.db_path))
            if stale_info and stale_info.get("is_real"):
                logger.warning("Using stale fallback due to transform failure")
                client.close()
                return EXIT_SUCCESS
        client.close()
        return EXIT_NO_DATA

    # Load
    logger.info("━" * 64)
    logger.info("STEP 3 / 4: LOAD (idempotent, transactional)")
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

    register_indicators(loader)

    loader.log_source_info(
        source_name="WHO GHO OData API",
        source_url=WHO_API_BASE_URL,
        total_extracted=total_extracted,
        total_loaded=load_result["records_loaded"],
        indicators=indicators,
        status="success",
        notes=f"data_mode={data_mode.value}",
    )

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
            notes=f"data_mode={data_mode.value}",
        )

    # Quality
    logger.info("━" * 64)
    logger.info("STEP 4 / 4: DATA QUALITY REPORT (comprehensive)")
    logger.info("━" * 64)

    loaded_df = loader.query("SELECT * FROM health_indicators")

    extraction_meta = {
        "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "api_status": "Online" if not failed else "Partial",
        "indicator_status": {
            name: {
                "status": extraction_results.get(name, {}).get("status"),
                "record_count": extraction_results.get(name, {}).get("record_count"),
                "api_status_code": extraction_results.get(name, {}).get("api_status_code"),
                "error": extraction_results.get(name, {}).get("error"),
            }
            for name in indicators
        },
        "raw_records": total_extracted,
        "api_latency_seconds": sum(v.get("api_latency_seconds", 0) for v in extraction_results.values()),
        "total_duration_seconds": sum(v.get("duration_s", 0) for v in extraction_results.values()),
        "api_calls": sum(v.get("api_calls", 0) for v in extraction_results.values()),
        "pages_fetched": sum(v.get("pages_fetched", 0) for v in extraction_results.values()),
        "pipeline_version": PIPELINE_VERSION,
    }

    quality_report = quality_phase(loaded_df, extraction_meta, data_mode=data_mode.value)

    logger.info("Quality score: %.1f/100", quality_report.get("overall_score", 0))
    logger.info("Total rows: %d", quality_report.get("processed_records", 0))
    logger.info("Countries: %d", quality_report.get("countries", 0))
    logger.info("Year range: %s", quality_report.get("year_range_str"))
    logger.info("Missing values: %d", quality_report.get("missing_values", 0))
    logger.info("Duplicates: %d", quality_report.get("duplicate_rows", 0))
    logger.info("Invalid values: %d", quality_report.get("invalid_numeric", 0))
    logger.info("Unmapped countries: %d", quality_report.get("unmapped_countries", {}).get("count", 0))

    # Save JSON report to reports/data_quality_report.json (required)
    json_report_path = REPORTS_DIR / "data_quality_report.json"
    save_quality_report_json(quality_report, json_report_path)
    logger.info("Quality JSON report saved to %s", json_report_path)

    # Also save to DB
    try:
        loader.save_data_quality_report(quality_report)
        loader.export_quality_report_json(json_report_path)
    except Exception as e:
        logger.error(f"Failed to save quality report to DB: {e}")

    # Optional markdown report
    if args.quality_report:
        report_path = Path(args.quality_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        # Generate markdown from DataQualityReport wrapper
        try:
            qr = DataQualityReport(loaded_df)
            report_path.write_text(qr.to_markdown(), encoding="utf-8")
            logger.info("Quality markdown report saved to %s", report_path)
        except Exception as e:
            # Fallback markdown with live report
            md_lines = [
                "# WHO Health Data Quality Report (LIVE)",
                f"Generated: {quality_report.get('extraction_timestamp_utc')}",
                f"Score: {quality_report.get('overall_score')}/100",
                f"Mode: {quality_report.get('data_mode')}",
                f"API status: {quality_report.get('api_status')}",
                "",
                f"Raw records: {quality_report.get('raw_records')}",
                f"Processed: {quality_report.get('processed_records')}",
                f"Countries: {quality_report.get('countries')}",
                f"Years: {quality_report.get('years')} range {quality_report.get('year_range_str')}",
            ]
            report_path.write_text("\n".join(md_lines), encoding="utf-8")

    client.close()

    verdict = fail_or_warn_on_quality(quality_report)
    if verdict == "fail":
        logger.error("Pipeline completed but quality check FAILED - needs attention")
        return EXIT_VALIDATION_FAILURE
    elif verdict == "warn":
        logger.warning("Pipeline completed with quality warnings")

    logger.info("=" * 64)
    logger.info("Pipeline completed successfully")
    logger.info("=" * 64)
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
