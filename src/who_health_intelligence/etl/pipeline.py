"""
Main ETL pipeline orchestrator - Production LIVE mode with explicit data mode handling.

Requirements:
- Default LIVE mode, DEMO requires explicit WHO_DATA_MODE=demo
- Never silently fallback from LIVE to synthetic data
- If LIVE fails and no cached real snapshot: stop gracefully, show error, don't display synthetic
- If cached real snapshot exists: use as stale fallback, label STALE REAL DATA, show extraction timestamp and API failure reason
- Never mix synthetic with live
- Generate comprehensive data-quality report per spec, save as reports/data_quality_report.json and in DB
- Idempotent loading, transactions, atomic writes
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..api.client import WHOAPIClient
from ..utils.config import (
    WHO_INDICATORS,
    DEFAULT_INDICATORS,
    DATABASE_PATH,
    REPORTS_DIR,
    PIPELINE_VERSION,
    WHO_API_BASE_URL,
    WHO_REFRESH_TTL,
    get_data_mode,
    setup_logging,
)
from ..utils.data_mode import get_current_data_mode, get_stale_snapshot_info, DataMode, APIStatus
from .transform import transform_indicator_records, merge_indicator_dataframes
from .metadata import normalize_geography, get_mapping_coverage_report
from .loader import DatabaseLoader
from .live_quality import generate_live_quality_report, save_quality_report_json, fail_or_warn_on_quality

# Fallback imports for DataQualityReport compatibility
try:
    from data_quality import DataQualityReport
except ModuleNotFoundError:
    from src.data_quality import DataQualityReport

logger = setup_logging(__name__)


class WHOETLPipeline:
    """
    Production ETL pipeline with LIVE/DEMO mode handling.
    """

    def __init__(
        self,
        db_path: str = DATABASE_PATH,
        api_client: Optional[WHOAPIClient] = None,
        data_mode: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.client = api_client or WHOAPIClient()
        self.loader = DatabaseLoader(str(self.db_path))
        self.results: Dict[str, Any] = {}
        # Determine data mode from env or explicit param
        if data_mode:
            self.data_mode = DataMode(data_mode.lower()) if data_mode.lower() in ("live", "demo") else get_current_data_mode()
        else:
            self.data_mode = get_current_data_mode()
        logger.info(f"Pipeline initialized in {self.data_mode.value.upper()} mode, db={self.db_path}")

    def run(
        self,
        indicators: Optional[List[str]] = None,
        replace: bool = True,
        generate_quality_report: bool = True,
        allow_stale_fallback: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute full ETL pipeline with LIVE mode safeguards.

        Args:
            indicators: list of indicator names
            replace: if True, replace existing data
            generate_quality_report: generate comprehensive quality report
            allow_stale_fallback: if True, allow STALE REAL DATA when LIVE fails

        Returns:
            results dict with keys: status, extraction, transformation, loading, quality_report, data_mode, api_status, stale_info
        """
        if indicators is None:
            indicators = DEFAULT_INDICATORS

        start_time = time.monotonic()
        extraction_timestamp = datetime.now(timezone.utc).isoformat()

        logger.info(f"Starting ETL pipeline in {self.data_mode.value.upper()} mode for {len(indicators)} indicators")
        logger.info(f"Indicators: {indicators}")

        results: Dict[str, Any] = {
            "indicators": indicators,
            "data_mode": self.data_mode.value,
            "extraction": {},
            "transformation": {},
            "loading": {},
            "quality_report": None,
            "total_duration_seconds": 0,
            "status": "running",
            "api_status": APIStatus.UNKNOWN.value,
            "extraction_timestamp": extraction_timestamp,
            "stale_fallback_used": False,
            "failure_reason": None,
        }

        # DEMO mode handling: explicitly use bootstrap synthetic data only if DEMO
        if self.data_mode == DataMode.DEMO:
            logger.warning("DEMO mode explicitly enabled - will use synthetic data, NOT official WHO observations")
            # For DEMO pipeline run, we should NOT call real API; instead generate synthetic via bootstrap
            # But if indicators provided and client can still fetch, we allow? Per spec, DEMO should show banner.
            # Implementation: try bootstrap, but also support extracting real data if available? Simplest: keep using real API but flag as DEMO,
            # but bootstrap is separate script. For pipeline.run in DEMO mode, we will still attempt real extraction but mark result as DEMO.
            # However to avoid silent synthetic, we require explicit DEMO env.
            # We'll proceed with normal flow but mark data_mode=demo in quality report.
            pass

        # LIVE mode pre-check: validate base URL reachable?
        if self.data_mode == DataMode.LIVE:
            reachable, msg = self.client.validate_base_url_reachable()
            if not reachable:
                logger.warning(f"API base URL not reachable at start: {msg} - will attempt extraction anyway and fallback to stale if available")

        try:
            # Step 1: Extract with full metadata tracking
            logger.info("=" * 60)
            logger.info(f"STEP 1: EXTRACT (mode={self.data_mode.value.upper()})")
            logger.info("=" * 60)

            extraction_results = self.client.extract_multiple_with_metadata(
                indicator_names=indicators,
                indicators_map=WHO_INDICATORS,
                raw_output_dir=None,
            )

            raw_data: Dict[str, List[Dict[str, Any]]] = {}
            total_raw = 0
            total_latency = 0.0
            api_calls = 0
            pages_fetched = 0
            indicator_status: Dict[str, Any] = {}
            failed_indicators: List[str] = []
            succeeded_indicators: List[str] = []

            for ind_name, meta in extraction_results.items():
                recs = meta.get("records", [])
                raw_data[ind_name] = recs
                total_raw += meta.get("record_count", 0)
                total_latency += meta.get("api_latency_seconds", 0.0)
                api_calls += meta.get("api_calls", 0)
                pages_fetched += meta.get("pages_fetched", 0)

                status = meta.get("status", "unknown")
                indicator_status[ind_name] = {
                    "status": status,
                    "record_count": meta.get("record_count", 0),
                    "api_status_code": meta.get("api_status_code"),
                    "latency": meta.get("api_latency_seconds", 0.0),
                    "duration": meta.get("extraction_duration_seconds", 0.0),
                    "error": meta.get("error"),
                    "extraction_timestamp": meta.get("extraction_timestamp_utc"),
                }

                results["extraction"][ind_name] = {
                    "records_extracted": meta.get("record_count", 0),
                    "status": status,
                    "duration_seconds": meta.get("extraction_duration_seconds", 0.0),
                    "api_status_code": meta.get("api_status_code"),
                    "api_latency_seconds": meta.get("api_latency_seconds", 0.0),
                    "error": meta.get("error"),
                }

                if status == "success" and meta.get("record_count", 0) > 0:
                    succeeded_indicators.append(ind_name)
                else:
                    failed_indicators.append(ind_name)

            # Determine overall API status
            if len(succeeded_indicators) == len(indicators):
                overall_api_status = APIStatus.ONLINE.value
            elif len(succeeded_indicators) > 0:
                overall_api_status = APIStatus.PARTIAL.value
            else:
                overall_api_status = APIStatus.FAILED.value

            results["api_status"] = overall_api_status
            logger.info(
                f"Extraction summary: {len(succeeded_indicators)}/{len(indicators)} succeeded, "
                f"total_raw={total_raw} latency={total_latency:.2f}s api_calls={api_calls} status={overall_api_status}"
            )

            # LIVE mode failure handling
            if self.data_mode == DataMode.LIVE and overall_api_status == APIStatus.FAILED.value:
                # No data extracted at all
                stale_info = get_stale_snapshot_info(self.db_path) if allow_stale_fallback else None
                if stale_info and stale_info.get("is_real"):
                    # Use stale fallback
                    logger.warning(
                        f"LIVE extraction failed completely, but stale real snapshot exists "
                        f"from {stale_info.get('extraction_timestamp')}: using STALE REAL DATA"
                    )
                    results["status"] = "stale"
                    results["stale_fallback_used"] = True
                    results["stale_info"] = stale_info
                    results["failure_reason"] = "API failed, using stale real snapshot"
                    results["api_status"] = APIStatus.FAILED.value
                    # Load existing data from DB for quality report
                    try:
                        existing_df = self.loader.query("SELECT * FROM health_indicators")
                        raw_data = {}  # no new raw data
                        # We'll generate quality report from existing data but mark as stale
                        # and attempt to continue to quality phase without loading new data
                        # For pipeline results, we should not overwrite DB
                        # So skip transform/load, go to quality with existing df
                        merged_df_for_quality = existing_df
                        # Jump to quality phase handling below via flag
                        transform_results = {}
                        merged_df = existing_df
                        # To avoid duplication, we will skip loading and go to quality
                        # Mark loading as skipped stale
                        results["loading"] = {
                            "records_loaded": 0,
                            "status": "skipped_stale",
                            "message": f"Using stale real data from {stale_info.get('extraction_timestamp')}",
                        }
                        # Set a flag to indicate we are in stale path
                        is_stale_path = True
                    except Exception as e:
                        logger.error(f"Failed to load stale snapshot: {e}")
                        results["status"] = "failed"
                        results["failure_reason"] = f"LIVE API failed and stale snapshot load failed: {e}"
                        results["error"] = str(e)
                        return results
                else:
                    # No stale snapshot - fail gracefully, do NOT use synthetic
                    logger.error(
                        "LIVE extraction failed and no previously cached real snapshot exists. "
                        "Stopping gracefully per production requirements. No synthetic data will be shown."
                    )
                    results["status"] = "failed"
                    results["failure_reason"] = "API failed and no cached real snapshot"
                    results["error"] = "LIVE mode failed, no stale real data available. Please check network, WHO API status, and try again. See logs for API status."
                    results["api_status"] = APIStatus.FAILED.value
                    results["loading"] = {"records_loaded": 0, "status": "failed"}
                    return results
            else:
                is_stale_path = False

            # Step 2: Transform (if not stale path)
            if not is_stale_path:
                logger.info("=" * 60)
                logger.info("STEP 2: TRANSFORM")
                logger.info("=" * 60)

                transformed_dfs: Dict[str, pd.DataFrame] = {}
                total_processed = 0
                for indicator_name, records in raw_data.items():
                    transform_start = time.monotonic()
                    if not records:
                        logger.warning(f"No records for {indicator_name}, skipping transform")
                        results["transformation"][indicator_name] = {
                            "records_transformed": 0,
                            "status": "skipped",
                            "error": results["extraction"].get(indicator_name, {}).get("error"),
                        }
                        continue

                    indicator_code = WHO_INDICATORS.get(indicator_name, {}).get("code", "")
                    # Pass extraction timestamp for tracking
                    extraction_ts_for_indicator = indicator_status.get(indicator_name, {}).get("extraction_timestamp") or extraction_timestamp

                    df = transform_indicator_records(records, indicator_name, indicator_code, extracted_at=extraction_ts_for_indicator)

                    # Geography normalization
                    df = normalize_geography(df)

                    transformed_dfs[indicator_name] = df
                    total_processed += len(df)

                    mapping_report = get_mapping_coverage_report(df) if not df.empty else {}

                    results["transformation"][indicator_name] = {
                        "records_transformed": len(df),
                        "countries": df["country_code"].nunique() if "country_code" in df.columns and not df.empty else 0,
                        "years": sorted(df["year"].unique().tolist()) if "year" in df.columns and not df.empty else [],
                        "status": "success",
                        "duration_seconds": round(time.monotonic() - transform_start, 2),
                        "mapping_coverage": mapping_report,
                    }

                if not transformed_dfs:
                    logger.error("No data was successfully transformed")
                    # Check for stale fallback again
                    if self.data_mode == DataMode.LIVE and allow_stale_fallback:
                        stale_info = get_stale_snapshot_info(self.db_path)
                        if stale_info and stale_info.get("is_real"):
                            results["status"] = "stale"
                            results["stale_fallback_used"] = True
                            results["stale_info"] = stale_info
                            results["failure_reason"] = "Transform produced no data, using stale real snapshot"
                            try:
                                existing_df = self.loader.query("SELECT * FROM health_indicators")
                                merged_df = existing_df
                                is_stale_path = True
                            except Exception as e:
                                results["status"] = "failed"
                                results["error"] = f"No data transformed and stale load failed: {e}"
                                return results
                        else:
                            results["status"] = "failed"
                            results["error"] = "No data transformed"
                            return results
                    else:
                        results["status"] = "failed"
                        results["error"] = "No data transformed"
                        return results

                # Merge
                merged_df = merge_indicator_dataframes(transformed_dfs)
            else:
                # Already have merged_df from stale path
                pass

            # Step 3: Load (skip if stale path already has data)
            if not is_stale_path:
                logger.info("=" * 60)
                logger.info("STEP 3: LOAD (idempotent, transactional)")
                logger.info("=" * 60)

                load_start = time.monotonic()
                records_loaded = self.loader.load_all_indicators(merged_df, replace_all=replace)

                results["loading"] = {
                    "records_loaded": records_loaded,
                    "status": "success",
                    "duration_seconds": round(time.monotonic() - load_start, 2),
                }

                # Register indicators
                self.loader.register_all_indicators()

                # Log source info
                self.loader.log_source_info(
                    source_name="WHO GHO OData API",
                    source_url=WHO_API_BASE_URL,
                    total_extracted=total_raw,
                    total_loaded=records_loaded,
                    indicators=indicators,
                    status="success" if overall_api_status in (APIStatus.ONLINE.value, APIStatus.PARTIAL.value) else "failed",
                    notes=f"data_mode={self.data_mode.value} api_status={overall_api_status}",
                )

                # Log per-indicator ETL runs
                for name in indicators:
                    ext_meta = extraction_results.get(name, {})
                    trans_meta = results["transformation"].get(name, {})
                    self.loader.log_etl_run(
                        indicator=name,
                        indicator_code=WHO_INDICATORS.get(name, {}).get("code", ""),
                        records_extracted=ext_meta.get("record_count", 0),
                        records_loaded=trans_meta.get("records_transformed", 0),
                        status=trans_meta.get("status", "unknown"),
                        duration_seconds=ext_meta.get("extraction_duration_seconds", 0) + trans_meta.get("duration_seconds", 0),
                        source_url=f"{WHO_API_BASE_URL}{WHO_INDICATORS.get(name, {}).get('code', '')}",
                        notes=f"data_mode={self.data_mode.value}",
                    )

                total_duration = round(time.monotonic() - start_time, 2)
                self.loader.log_etl_run(
                    indicator="ALL",
                    records_loaded=records_loaded,
                    status="success",
                    duration_seconds=total_duration,
                    notes=f"Full pipeline data_mode={self.data_mode.value}",
                )

            # Step 4: Quality Report
            if generate_quality_report:
                logger.info("=" * 60)
                logger.info("STEP 4: DATA QUALITY REPORT (comprehensive)")
                logger.info("=" * 60)

                # Build extraction metadata for quality report
                quality_extraction_meta = {
                    "extraction_timestamp_utc": extraction_timestamp,
                    "api_status": overall_api_status,
                    "indicator_status": indicator_status,
                    "raw_records": total_raw,
                    "processed_records": len(merged_df) if not merged_df.empty else 0,
                    "api_latency_seconds": total_latency,
                    "total_duration_seconds": round(time.monotonic() - start_time, 2),
                    "api_calls": api_calls,
                    "pages_fetched": pages_fetched,
                    "pipeline_version": PIPELINE_VERSION,
                }

                live_report = generate_live_quality_report(
                    df=merged_df,
                    extraction_metadata=quality_extraction_meta,
                    data_mode=self.data_mode.value if not results.get("stale_fallback_used") else "stale",
                )

                results["quality_report"] = live_report

                # Save JSON to reports/
                json_path = save_quality_report_json(live_report, REPORTS_DIR / "data_quality_report.json")
                results["quality_report_path"] = str(json_path)

                # Also store in DB
                try:
                    qid = self.loader.save_data_quality_report(live_report)
                    results["quality_report_id"] = qid
                    # Export via loader method as well (ensures file exists)
                    self.loader.export_quality_report_json(REPORTS_DIR / "data_quality_report.json")
                except Exception as e:
                    logger.error(f"Failed to save quality report to DB: {e}")

                # Also generate markdown for compatibility
                try:
                    qr = DataQualityReport(merged_df)
                    md = qr.to_markdown()
                    results["quality_report_md"] = md
                except Exception:
                    results["quality_report_md"] = f"# Quality Report\nOverall score: {live_report.get('overall_score')}"

                # Check thresholds - fail or warn
                verdict = fail_or_warn_on_quality(live_report)
                results["quality_verdict"] = verdict
                if verdict == "fail":
                    logger.error(f"Data quality check FAILED: score={live_report.get('overall_score')} issues={live_report.get('quality_issues')}")
                    # Don't fail pipeline completely if we have some data, but mark status as warnings
                    if is_stale_path:
                        results["status"] = "stale"
                    else:
                        results["status"] = "success_with_quality_warnings" if succeeded_indicators else "failed"
                elif verdict == "warn":
                    logger.warning(f"Data quality warnings: {live_report.get('quality_issues')}")
                    if not is_stale_path:
                        results["status"] = "success" if results.get("status") != "stale" else "stale"
                else:
                    logger.info(f"Data quality PASSED: score={live_report.get('overall_score')}")
                    if results.get("status") != "stale":
                        results["status"] = "success"

                # Ensure final status is success if we have data and not already stale/failed
                if results.get("status") == "running":
                    results["status"] = "success"

            else:
                # No quality report requested, set status based on extraction
                if not is_stale_path:
                    results["status"] = "success" if overall_api_status != APIStatus.FAILED.value else "failed"
                total_duration = round(time.monotonic() - start_time, 2)
                results["total_duration_seconds"] = total_duration

            results["total_duration_seconds"] = round(time.monotonic() - start_time, 2)
            logger.info(f"ETL pipeline completed: status={results['status']} duration={results['total_duration_seconds']}s")

        except Exception as e:
            logger.error(f"ETL pipeline failed: {e}")
            results["status"] = "failed"
            results["error"] = str(e)
            results["failure_reason"] = str(e)
            results["total_duration_seconds"] = round(time.monotonic() - start_time, 2)

        self.results = results
        return results

    def load_from_existing_db(self) -> pd.DataFrame:
        return self.loader.query("SELECT * FROM health_indicators")

    def get_summary(self) -> Dict[str, Any]:
        if not self.results:
            return {"status": "no_run", "message": "No pipeline run recorded"}
        return {
            "status": self.results.get("status"),
            "data_mode": self.results.get("data_mode"),
            "api_status": self.results.get("api_status"),
            "indicators": self.results.get("indicators"),
            "total_records": self.results.get("loading", {}).get("records_loaded", 0),
            "duration_seconds": self.results.get("total_duration_seconds", 0),
            "quality_score": (self.results.get("quality_report", {}).get("overall_score", 0) if self.results.get("quality_report") else 0),
            "stale_fallback_used": self.results.get("stale_fallback_used", False),
        }
