#!/usr/bin/env python3
"""
WHO Global Health Intelligence Platform - Main Entry Point.

Provides CLI interface for:
- Running the ETL pipeline
- Generating data quality reports
- Launching the Streamlit dashboard
- Validating database integrity
"""

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.utils.config import (
    DATABASE_PATH,
    DEFAULT_INDICATORS,
    setup_logging
)
from src.who_health_intelligence.etl.pipeline import WHOETLPipeline
from src.who_health_intelligence.etl.loader import DatabaseLoader
from src.who_health_intelligence.etl.quality import DataQualityReport

logger = setup_logging(__name__)


def cmd_etl(args):
    """Run the ETL pipeline."""
    logger.info("Starting ETL pipeline from CLI")

    indicators = args.indicators if args.indicators else DEFAULT_INDICATORS
    replace = not args.no_replace

    pipeline = WHOETLPipeline(db_path=args.db)
    results = pipeline.run(
        indicators=indicators,
        replace=replace,
        generate_quality_report=True
    )

    # Print summary
    print("\n" + "=" * 60)
    print("ETL PIPELINE SUMMARY")
    print("=" * 60)
    print(f"Status: {results['status']}")
    print(f"Duration: {results['total_duration_seconds']:.2f}s")
    print(f"Indicators: {results['indicators']}")

    for name, ext in results.get('extraction', {}).items():
        status = ext.get('status', 'unknown')
        count = ext.get('records_extracted', 0)
        print(f"  Extract [{name}]: {count} records ({status})")

    for name, trans in results.get('transformation', {}).items():
        status = trans.get('status', 'unknown')
        count = trans.get('records_transformed', 0)
        print(f"  Transform [{name}]: {count} records ({status})")

    loading = results.get('loading', {})
    print(f"  Load: {loading.get('records_loaded', 0)} records ({loading.get('status', 'unknown')})")

    if results.get('quality_report'):
        score = results['quality_report']['overall_score']
        print(f"\nData Quality Score: {score}/100")

        # Save quality report
        if args.quality_report:
            report_path = Path(args.quality_report)
            report_path.write_text(results.get('quality_report_md', ''))
            print(f"Quality report saved to: {report_path}")

    return 0 if results['status'] == 'success' else 1


def cmd_quality(args):
    """Generate a data quality report for existing data."""
    loader = DatabaseLoader(args.db)
    df = loader.query("SELECT * FROM health_indicators")

    if df.empty:
        print("No data in database. Run ETL first.")
        return 1

    report = DataQualityReport(df)
    md = report.to_markdown()

    if args.output:
        Path(args.output).write_text(md)
        print(f"Quality report saved to: {args.output}")
    else:
        print(md)

    return 0


def cmd_info(args):
    """Show database information."""
    loader = DatabaseLoader(args.db)
    info = loader.get_table_info()

    print("\n" + "=" * 60)
    print("DATABASE INFORMATION")
    print("=" * 60)
    print(f"Database: {args.db}")
    print(f"Tables: {list(info['tables'].keys())}")

    for table, tinfo in info['tables'].items():
        print(f"\n  Table: {table}")
        print(f"  Rows: {tinfo['row_count']}")
        print(f"  Columns: {len(tinfo['columns'])}")
        for col in tinfo['columns']:
            print(f"    - {col['name']} ({col['type']})")

    # Show indicator summary
    if info['tables']['health_indicators']['row_count'] > 0:
        df = loader.query("SELECT Indicator, COUNT(*) as count FROM health_indicators GROUP BY Indicator")
        print(f"\n  Indicators:")
        for _, row in df.iterrows():
            print(f"    - {row['Indicator']}: {row['count']} records")

    return 0


def cmd_dashboard(args):
    """Launch the Streamlit dashboard."""
    import subprocess
    app_path = PROJECT_ROOT / "src" / "who_health_intelligence" / "dashboard" / "app.py"
    cmd = ["streamlit", "run", str(app_path)]
    if args.port:
        cmd.extend(["--server.port", str(args.port)])
    subprocess.run(cmd)
    return 0


def cmd_notebook(args):
    """Generate the analysis notebook."""
    from scripts.generate_notebook import create_notebook
    output_path = args.output or "notebooks/WHO_Health_Analysis.ipynb"
    create_notebook(output_path)
    print(f"Notebook generated: {output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="WHO Global Health Intelligence Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py etl                          # Run full ETL pipeline
  python main.py etl --indicators NCD_MORTALITY UHC_COVERAGE
  python main.py quality                      # Generate quality report
  python main.py info                         # Show database info
  python main.py dashboard                    # Launch Streamlit dashboard
  python main.py notebook                     # Generate analysis notebook
        """
    )

    parser.add_argument(
        '--db',
        default=str(DATABASE_PATH),
        help=f'Database path (default: {DATABASE_PATH})'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # ETL command
    etl_parser = subparsers.add_parser('etl', help='Run the ETL pipeline')
    etl_parser.add_argument(
        '--indicators',
        nargs='+',
        help=f'Indicators to extract (default: {DEFAULT_INDICATORS})'
    )
    etl_parser.add_argument(
        '--no-replace',
        action='store_true',
        help='Append to existing data instead of replacing'
    )
    etl_parser.add_argument(
        '--quality-report',
        help='Path to save quality report (markdown)'
    )

    # Quality command
    quality_parser = subparsers.add_parser('quality', help='Generate data quality report')
    quality_parser.add_argument('--output', help='Output file path')

    # Info command
    subparsers.add_parser('info', help='Show database information')

    # Dashboard command
    dashboard_parser = subparsers.add_parser('dashboard', help='Launch Streamlit dashboard')
    dashboard_parser.add_argument('--port', type=int, default=8501, help='Server port')

    # Notebook command
    notebook_parser = subparsers.add_parser('notebook', help='Generate analysis notebook')
    notebook_parser.add_argument('--output', help='Output notebook path')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        'etl': cmd_etl,
        'quality': cmd_quality,
        'info': cmd_info,
        'dashboard': cmd_dashboard,
        'notebook': cmd_notebook
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
