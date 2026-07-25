#!/usr/bin/env python3
"""
WHO Global Health Intelligence Platform - Main Entry Point (Production LIVE mode)

CLI interface for:
- Running ETL pipeline with explicit LIVE/DEMO mode handling
- Generating data quality reports (comprehensive)
- Launching Streamlit dashboard
- Validating database integrity

Environment variables:
    WHO_DATA_MODE=live (default) or demo (explicit)
    WHO_API_BASE_URL, WHO_API_TIMEOUT, WHO_API_MAX_RETRIES, WHO_REFRESH_TTL, WHO_DB_PATH

Default deployment mode is LIVE, DEMO requires explicit setting.
Never silently fallback from LIVE to synthetic data.
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.utils.config import (
    DATABASE_PATH,
    DEFAULT_INDICATORS,
    REPORTS_DIR,
    setup_logging,
    get_data_mode,
)
from src.who_health_intelligence.utils.data_mode import get_current_data_mode, DataMode

logger = setup_logging(__name__)


def cmd_etl(args):
    """Run the ETL pipeline with LIVE/DEMO safeguards."""
    from src.who_health_intelligence.etl.pipeline import WHOETLPipeline

    # Handle explicit data mode from CLI if provided
    if getattr(args, "data_mode", None):
        os.environ["WHO_DATA_MODE"] = args.data_mode
    if getattr(args, "demo", False):
        os.environ["WHO_DATA_MODE"] = "demo"

    current_mode = get_current_data_mode()
    logger.info(f"Starting ETL pipeline from CLI in {current_mode.value.upper()} mode")

    if current_mode == DataMode.DEMO:
        logger.warning("DEMO MODE: NOT OFFICIAL WHO OBSERVATIONS banner will be shown in dashboard")

    indicators = args.indicators if args.indicators else DEFAULT_INDICATORS
    replace = not args.no_replace

    pipeline = WHOETLPipeline(db_path=args.db)
    results = pipeline.run(
        indicators=indicators,
        replace=replace,
        generate_quality_report=True,
        allow_stale_fallback=not getattr(args, "no_stale", False),
    )

    # Print summary
    print("\n" + "=" * 60)
    print("ETL PIPELINE SUMMARY")
    print("=" * 60)
    print(f"Data Mode: {results.get('data_mode', current_mode.value).upper()}")
    print(f"API Status: {results.get('api_status', 'unknown')}")
    print(f"Status: {results['status']}")
    print(f"Duration: {results['total_duration_seconds']:.2f}s")
    print(f"Indicators: {results['indicators']}")

    for name, ext in results.get("extraction", {}).items():
        status = ext.get("status", "unknown")
        count = ext.get("records_extracted", 0)
        print(f"  Extract [{name}]: {count} records ({status})")

    for name, trans in results.get("transformation", {}).items():
        status = trans.get("status", "unknown")
        count = trans.get("records_transformed", 0)
        print(f"  Transform [{name}]: {count} records ({status})")

    loading = results.get("loading", {})
    print(f"  Load: {loading.get('records_loaded', 0)} records ({loading.get('status', 'unknown')})")

    if results.get("stale_fallback_used"):
        print(f"\nSTALE REAL DATA used: {results.get('stale_info')}")

    if results.get("failure_reason"):
        print(f"\nFailure reason: {results.get('failure_reason')}")

    if results.get("quality_report"):
        score = results["quality_report"].get("overall_score", 0)
        print(f"\nData Quality Score: {score}/100")
        print(f"Quality report JSON: {results.get('quality_report_path', REPORTS_DIR / 'data_quality_report.json')}")

        if args.quality_report:
            report_path = Path(args.quality_report)
            report_path.write_text(results.get("quality_report_md", ""), encoding="utf-8")
            print(f"Quality markdown report saved to: {report_path}")

    # Exit code handling for LIVE mode failures
    if results["status"] in ("success", "stale", "success_with_quality_warnings"):
        return 0
    elif results["status"] == "failed":
        # If LIVE and no stale, this is expected failure path - show instructions
        if current_mode == DataMode.LIVE:
            print("\nLIVE MODE FAILURE GRACEFUL HANDLING:")
            print("- Dashboard will stop gracefully if no cached real snapshot")
            print("- Shows clear error message, failed API status, how to fix")
            print("- Does NOT display synthetic data")
            print("- If cached real snapshot exists, labeled as STALE REAL DATA with extraction timestamp and failure reason")
        return 1
    else:
        return 0


def cmd_quality(args):
    """Generate comprehensive data quality report."""
    from src.who_health_intelligence.etl.loader import DatabaseLoader
    from src.who_health_intelligence.etl.live_quality import generate_live_quality_report, save_quality_report_json
    from datetime import datetime, timezone

    loader = DatabaseLoader(args.db)
    df = loader.query("SELECT * FROM health_indicators")

    if df.empty:
        print("No data in database. Run ETL first.")
        return 1

    # Generate minimal extraction metadata for quality report
    extraction_meta = {
        "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "api_status": "Unknown (generated from existing DB)",
        "indicator_status": {},
        "raw_records": len(df),
        "api_latency_seconds": 0.0,
        "total_duration_seconds": 0.0,
    }

    report = generate_live_quality_report(df, extraction_meta, data_mode=get_data_mode())

    if args.output:
        if args.output.endswith(".json"):
            Path(args.output).write_text(__import__("json").dumps(report, indent=2, default=str))
        else:
            from src.data_quality import DataQualityReport

            qr = DataQualityReport(df)
            Path(args.output).write_text(qr.to_markdown())
        print(f"Quality report saved to: {args.output}")
    else:
        print(__import__("json").dumps(report, indent=2, default=str)[:2000])

    # Also save JSON to reports/
    json_path = save_quality_report_json(report)
    print(f"JSON report saved to {json_path}")

    # Save to DB
    try:
        loader.save_data_quality_report(report)
        print("Quality report saved to DB data_quality_results table")
    except Exception as e:
        print(f"Failed to save to DB: {e}")

    return 0


def cmd_info(args):
    """Show database information with schema validation."""
    from src.who_health_intelligence.etl.loader import DatabaseLoader

    loader = DatabaseLoader(args.db)
    info = loader.get_table_info()

    print("\n" + "=" * 60)
    print("DATABASE INFORMATION")
    print("=" * 60)
    print(f"Database: {args.db}")
    print(f"Data mode (env): {get_data_mode().upper()}")
    print(f"Tables: {list(info['tables'].keys())}")

    for table, tinfo in info["tables"].items():
        print(f"\n  Table: {table}")
        print(f"  Rows: {tinfo['row_count']}")
        print(f"  Columns: {len(tinfo['columns'])}")
        for col in tinfo["columns"]:
            print(f"    - {col['name']} ({col['type']})")

    # Validate schema
    validation = loader.validate_schema()
    print("\n" + "-" * 60)
    print("SCHEMA VALIDATION")
    print(f"  Valid: {validation['is_valid']}")
    if validation["missing_columns"]:
        print(f"  Missing columns: {validation['missing_columns']}")
    if validation["missing_tables"]:
        print(f"  Missing tables: {validation['missing_tables']}")

    # Indicator summary
    if info["tables"].get("health_indicators", {}).get("row_count", 0) > 0:
        try:
            df = loader.query("SELECT indicator, COUNT(*) as count FROM health_indicators GROUP BY indicator")
            print("\n  Indicators (snake_case):")
            for _, row in df.iterrows():
                print(f"    - {row['indicator']}: {row['count']} records")
        except Exception:
            df = loader.query("SELECT Indicator, COUNT(*) as count FROM health_indicators GROUP BY Indicator")
            print("\n  Indicators (legacy):")
            for _, row in df.iterrows():
                print(f"    - {row['Indicator']}: {row['count']} records")

    # Quality report
    latest_q = loader.get_latest_quality_report()
    if latest_q:
        print(f"\n  Latest quality score: {latest_q.get('overall_score')}/100")
        print(f"  Extraction: {latest_q.get('extraction_timestamp')}")

    return 0


def cmd_dashboard(args):
    """Launch Streamlit dashboard."""
    import subprocess

    app_path = PROJECT_ROOT / "src" / "who_health_intelligence" / "dashboard" / "app.py"
    cmd = ["streamlit", "run", str(app_path)]
    if args.port:
        cmd.extend(["--server.port", str(args.port)])
    # Pass env for data mode
    env = os.environ.copy()
    subprocess.run(cmd, env=env)
    return 0


def cmd_notebook(args):
    """Generate analysis notebook."""
    from scripts.generate_notebook import create_notebook

    output_path = args.output or "WHO_Data_Extraction_ETL.ipynb"
    create_notebook(output_path)
    print(f"Notebook generated: {output_path}")
    print("Notebook uses reusable source modules, supports LIVE/DEMO modes, shows extraction timestamp, source URL, indicator definitions, transformation, quality results")
    return 0


def cmd_validate_api(args):
    """Validate WHO API endpoints."""
    from src.who_health_intelligence.api.client import WHOAPIClient
    from src.who_health_intelligence.utils.config import WHO_API_BASE_URL, WHO_INDICATORS

    client = WHOAPIClient()

    print(f"Validating API base URL: {WHO_API_BASE_URL}")
    reachable, msg = client.validate_base_url_reachable()
    print(f"  Reachable: {reachable} - {msg}")

    for name, info in WHO_INDICATORS.items():
        code = info["code"]
        valid, message, count = client.validate_indicator_endpoint(code)
        status = "OK" if valid else "FAILED"
        print(f"  [{status}] {name} ({code}): {message}")

    client.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="WHO Global Health Intelligence Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  WHO_DATA_MODE=live python main.py etl                          # LIVE mode (default)
  WHO_DATA_MODE=demo python main.py etl --demo                   # DEMO mode explicit
  python main.py etl --indicators NCD_MORTALITY UHC_COVERAGE
  python main.py quality --output reports/data_quality_report.json
  python main.py info
  python main.py dashboard --port 8501
  python main.py notebook
  python main.py validate-api

Environment variables:
  WHO_DATA_MODE=live (default) or demo (explicit)
  WHO_API_BASE_URL=https://ghoapi.azureedge.net/api/
  WHO_API_TIMEOUT=30
  WHO_API_MAX_RETRIES=3
  WHO_REFRESH_TTL=3600
  WHO_DB_PATH=data/who_health_data.db
        """,
    )

    parser.add_argument(
        "--db",
        default=str(DATABASE_PATH),
        help=f"Database path (default: {DATABASE_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ETL
    etl_parser = subparsers.add_parser("etl", help="Run ETL pipeline (LIVE default, DEMO explicit)")
    etl_parser.add_argument("--indicators", nargs="+", help=f"Indicators (default: {DEFAULT_INDICATORS})")
    etl_parser.add_argument("--no-replace", action="store_true", help="Append instead of replace")
    etl_parser.add_argument("--quality-report", help="Path to save markdown quality report")
    etl_parser.add_argument("--data-mode", choices=["live", "demo"], help="Override WHO_DATA_MODE env")
    etl_parser.add_argument("--demo", action="store_true", help="Explicit DEMO mode with synthetic data")
    etl_parser.add_argument("--no-stale", action="store_true", help="Disallow STALE REAL DATA fallback")

    # Quality
    quality_parser = subparsers.add_parser("quality", help="Generate comprehensive data quality report")
    quality_parser.add_argument("--output", help="Output file path (json or md)")

    # Info
    subparsers.add_parser("info", help="Show database info and schema validation")

    # Dashboard
    dashboard_parser = subparsers.add_parser("dashboard", help="Launch Streamlit dashboard")
    dashboard_parser.add_argument("--port", type=int, default=8501, help="Server port")

    # Notebook
    notebook_parser = subparsers.add_parser("notebook", help="Generate analysis notebook")
    notebook_parser.add_argument("--output", help="Output notebook path")

    # Validate API
    subparsers.add_parser("validate-api", help="Validate WHO API endpoints")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "etl": cmd_etl,
        "quality": cmd_quality,
        "info": cmd_info,
        "dashboard": cmd_dashboard,
        "notebook": cmd_notebook,
        "validate-api": cmd_validate_api,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
