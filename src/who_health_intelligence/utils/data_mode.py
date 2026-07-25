"""
Data mode system for WHO Health Intelligence Platform.

Implements explicit LIVE vs DEMO mode handling as required for production:

- LIVE mode is default deployment mode
- DEMO mode requires explicit WHO_DATA_MODE=demo
- Never silently fall back to synthetic data in LIVE mode
- Supports STALE REAL DATA fallback when LIVE fails but cached real snapshot exists
- Clearly labels data mode and tracks extraction metadata
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .config import DATABASE_PATH, REPORTS_DIR, get_data_mode, setup_logging

logger = setup_logging(__name__)


class DataMode(str, Enum):
    LIVE = "live"
    DEMO = "demo"
    STALE = "stale"  # stale real data fallback (not set via env, derived at runtime)

    @classmethod
    def from_env(cls) -> "DataMode":
        mode_str = get_data_mode()
        if mode_str == "demo":
            return cls.DEMO
        return cls.LIVE


class APIStatus(str, Enum):
    ONLINE = "Online"
    FAILED = "Failed"
    PARTIAL = "Partial"
    UNKNOWN = "Unknown"


def validate_demo_explicit() -> bool:
    """
    Returns True if demo mode is explicitly enabled via WHO_DATA_MODE=demo.
    Used to prevent accidental demo usage.
    """
    return os.environ.get("WHO_DATA_MODE", "").strip().lower() == "demo"


def get_current_data_mode() -> DataMode:
    """Get current data mode from environment, default LIVE."""
    return DataMode.from_env()


def get_stale_snapshot_info(db_path: Path = DATABASE_PATH) -> Optional[Dict[str, Any]]:
    """
    Check if a previously fetched real snapshot exists in the database.
    Returns metadata about the stale snapshot if it exists and is real data,
    not synthetic/bootstrap data.

    Real data is identified by:
    - etl_metadata not containing 'BOOTSTRAP' or synthetic notes
    - source_info indicating WHO GHO OData API
    """
    import sqlite3

    if not db_path.exists() or db_path.stat().st_size == 0:
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Check if health_indicators has data
        cur.execute("SELECT COUNT(*) FROM health_indicators")
        count = cur.fetchone()[0]
        if count == 0:
            conn.close()
            return None

        # Try to get latest source_info that is not bootstrap
        try:
            cur.execute(
                """
                SELECT extraction_timestamp, source_name, source_url, total_records_loaded, indicators_extracted, status, notes
                FROM source_info
                WHERE source_name NOT LIKE '%BOOTSTRAP%' AND status='success'
                ORDER BY id DESC LIMIT 1
                """
            )
            row = cur.fetchone()
            if row:
                ts, source_name, source_url, total_loaded, indicators, status, notes = row
                # Ensure it's real WHO data (check source_url contains ghoapi or who.int)
                if source_url and ("ghoapi" in source_url.lower() or "who.int" in source_url.lower() or "who" in source_name.lower()):
                    # Get latest etl_metadata timestamp
                    cur.execute("SELECT run_timestamp FROM etl_metadata ORDER BY id DESC LIMIT 1")
                    etl_row = cur.fetchone()
                    extraction_ts = etl_row[0] if etl_row else ts

                    # Check quality report exists
                    cur.execute("SELECT COUNT(*) FROM data_quality_results")
                    has_quality = cur.fetchone()[0] > 0 if _table_exists(cur, "data_quality_results") else False

                    conn.close()
                    return {
                        "exists": True,
                        "is_real": True,
                        "extraction_timestamp": extraction_ts,
                        "source_name": source_name,
                        "source_url": source_url,
                        "total_records": total_loaded,
                        "indicators": indicators,
                        "status": status,
                        "has_quality_report": has_quality,
                    }
        except Exception as e:
            logger.debug(f"Could not fetch source_info for stale check: {e}")

        # Fallback: check if table has created_at / extracted_at column and use max
        try:
            # Check if any bootstrap marker exists
            cur.execute(
                "SELECT COUNT(*) FROM etl_metadata WHERE indicator='BOOTSTRAP' OR notes LIKE '%synthetic%' OR notes LIKE '%bootstrap%'"
            )
            bootstrap_count = cur.fetchone()[0]
            if bootstrap_count > 0:
                # If only bootstrap data exists, do not treat as real snapshot
                # But if there is also real data, we should check counts
                cur.execute("SELECT COUNT(*) FROM etl_metadata WHERE indicator != 'BOOTSTRAP'")
                real_count = cur.fetchone()[0]
                if real_count == 0:
                    conn.close()
                    return None
        except Exception:
            pass

        # If we have data and no bootstrap-only, treat as possibly real but need extraction time
        try:
            cur.execute("SELECT MAX(created_at) FROM health_indicators")
            latest = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM health_indicators")
            total = cur.fetchone()[0]
            conn.close()
            if total > 0:
                return {
                    "exists": True,
                    "is_real": True,  # assume real if etl_metadata not bootstrap-only
                    "extraction_timestamp": latest,
                    "source_name": "WHO GHO OData API",
                    "source_url": "https://ghoapi.azureedge.net/api/",
                    "total_records": total,
                    "indicators": "unknown",
                    "status": "stale",
                    "has_quality_report": False,
                }
        except Exception:
            conn.close()
            return None

        conn.close()
        return None
    except Exception as e:
        logger.warning(f"Failed to check stale snapshot: {e}")
        return None


def _table_exists(cur, table_name: str) -> bool:
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return cur.fetchone() is not None
    except Exception:
        return False


def get_data_status(
    db_path: Path = DATABASE_PATH,
    api_last_status: Optional[str] = None,
    api_failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build data status dictionary for dashboard status panel.

    Returns:
        {
            data_mode: LIVE / DEMO / STALE REAL DATA
            api_status: Online / Failed / Partial
            last_extraction: timestamp
            source: data source string
            n_records: int
            n_countries: int
            year_range: str
            quality_status: str
            failure_reason: optional
            is_stale: bool
            is_demo: bool
        }
    """
    mode = get_current_data_mode()
    import sqlite3
    import pandas as pd

    status: Dict[str, Any] = {
        "data_mode": mode.value.upper(),
        "api_status": APIStatus.UNKNOWN.value,
        "last_extraction": None,
        "source": "WHO Global Health Observatory (GHO)",
        "n_records": 0,
        "n_countries": 0,
        "year_range": "N/A",
        "quality_status": "Unknown",
        "failure_reason": api_failure_reason,
        "is_stale": False,
        "is_demo": mode == DataMode.DEMO,
        "db_exists": False,
    }

    if not db_path.exists():
        status["api_status"] = APIStatus.FAILED.value if mode == DataMode.LIVE else APIStatus.UNKNOWN.value
        return status

    status["db_exists"] = True

    try:
        conn = sqlite3.connect(str(db_path))
        # Basic counts
        df = pd.read_sql_query("SELECT * FROM health_indicators LIMIT 1000", conn)
        # Need full counts without loading all
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM health_indicators")
        status["n_records"] = cur.fetchone()[0]

        if status["n_records"] == 0:
            conn.close()
            return status

        cur.execute("SELECT COUNT(DISTINCT country_code) FROM health_indicators")
        try:
            status["n_countries"] = cur.fetchone()[0]
        except Exception:
            # fallback to legacy column
            cur.execute("SELECT COUNT(DISTINCT CountryCode) FROM health_indicators")
            status["n_countries"] = cur.fetchone()[0]

        # Year range
        try:
            cur.execute("SELECT MIN(year), MAX(year) FROM health_indicators")
            y_min, y_max = cur.fetchone()
            if y_min and y_max:
                status["year_range"] = f"{int(y_min)}–{int(y_max)}"
        except Exception:
            try:
                cur.execute("SELECT MIN(Year), MAX(Year) FROM health_indicators")
                y_min, y_max = cur.fetchone()
                if y_min and y_max:
                    status["year_range"] = f"{int(y_min)}–{int(y_max)}"
            except Exception:
                pass

        # Last extraction from etl_metadata or source_info
        try:
            cur.execute("SELECT run_timestamp FROM etl_metadata ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                status["last_extraction"] = row[0]
        except Exception:
            pass

        if not status["last_extraction"]:
            try:
                cur.execute("SELECT extraction_timestamp FROM source_info ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    status["last_extraction"] = row[0]
            except Exception:
                pass

        # Check if data is bootstrap/synthetic
        is_synthetic = False
        try:
            cur.execute("SELECT notes, indicator FROM etl_metadata ORDER BY id DESC LIMIT 5")
            rows = cur.fetchall()
            for notes, indicator in rows:
                if indicator == "BOOTSTRAP" or (notes and "synthetic" in notes.lower()):
                    is_synthetic = True
                    break
        except Exception:
            pass

        # Data quality status
        try:
            if _table_exists(cur, "data_quality_results"):
                cur.execute("SELECT overall_score FROM data_quality_results ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    score = row[0]
                    if score >= 80:
                        status["quality_status"] = f"Healthy ({score}/100)"
                    elif score >= 50:
                        status["quality_status"] = f"Warnings ({score}/100)"
                    else:
                        status["quality_status"] = f"Issues ({score}/100)"
                else:
                    status["quality_status"] = "Not assessed"
        except Exception:
            status["quality_status"] = "Unknown"

        conn.close()

        # Determine final data_mode and api_status
        if mode == DataMode.DEMO or is_synthetic:
            status["data_mode"] = "DEMO"
            status["is_demo"] = True
            status["api_status"] = APIStatus.UNKNOWN.value
            status["source"] = "DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS"
        else:
            # LIVE mode logic
            if api_last_status == "failed" or api_failure_reason:
                # Check stale snapshot
                stale_info = get_stale_snapshot_info(db_path)
                if stale_info and stale_info.get("is_real"):
                    status["data_mode"] = "STALE REAL DATA"
                    status["is_stale"] = True
                    status["api_status"] = APIStatus.FAILED.value
                    status["last_extraction"] = stale_info.get("extraction_timestamp") or status["last_extraction"]
                else:
                    status["data_mode"] = "LIVE"
                    status["api_status"] = APIStatus.FAILED.value
                    status["n_records"] = 0
            else:
                status["data_mode"] = "LIVE"
                status["api_status"] = api_last_status or APIStatus.ONLINE.value

    except Exception as e:
        logger.error(f"Failed to get data status: {e}")
        status["api_status"] = APIStatus.FAILED.value if mode == DataMode.LIVE else APIStatus.UNKNOWN.value

    return status


def ensure_live_or_fail(db_path: Path = DATABASE_PATH) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Ensure LIVE mode has real data, or return stale fallback info, or fail.

    Returns:
        (should_proceed: bool, stale_info: Optional[dict], failure_reason: Optional[str])

    - If LIVE mode and no cached real snapshot exists and API failed: should_proceed=False, show error.
    - If LIVE mode and cached real snapshot exists: should_proceed=True with stale_info indicating STALE REAL DATA.
    - If LIVE mode and real data exists and healthy: should_proceed=True, stale_info=None
    - If DEMO mode: should_proceed=True regardless
    """
    mode = get_current_data_mode()
    if mode == DataMode.DEMO:
        return True, None, None

    # LIVE mode
    stale = get_stale_snapshot_info(db_path)
    if not db_path.exists() or db_path.stat().st_size == 0:
        # No snapshot
        return False, None, "No cached real data snapshot exists. API failure requires manual refresh."

    if stale and stale.get("is_real"):
        # We have stale real data, can proceed but label as stale
        return True, stale, None

    # Check if data exists but is synthetic
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM health_indicators")
        count = cur.fetchone()[0]
        if count == 0:
            conn.close()
            return False, None, "Database empty, no real data available."
        # Check if synthetic
        try:
            cur.execute("SELECT COUNT(*) FROM etl_metadata WHERE indicator='BOOTSTRAP'")
            bootstrap_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM etl_metadata")
            total_etl = cur.fetchone()[0]
            conn.close()
            if bootstrap_count > 0 and total_etl == bootstrap_count:
                return False, None, "Only synthetic bootstrap data exists, not real WHO observations. LIVE mode requires real data."
        except Exception:
            conn.close()
    except Exception as e:
        return False, None, f"Database check failed: {e}"

    return True, None, None


__all__ = [
    "DataMode",
    "APIStatus",
    "validate_demo_explicit",
    "get_current_data_mode",
    "get_stale_snapshot_info",
    "get_data_status",
    "ensure_live_or_fail",
]
