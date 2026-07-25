"""
Database persistence layer for WHO health indicator data - Production LIVE mode.

Provides idempotent loading with:
- Explicit schema with required columns: country_code, country_name, continent, year, gender, indicator, value, unit, source, extracted_at, pipeline_version
- Also preserves legacy CamelCase columns for backward compatibility with existing dashboard/services until fully migrated
- Unique constraints for idempotency
- Upsert logic (INSERT OR REPLACE + pre-delete for replace mode)
- Transactions, atomic writes, safe temporary DB replacement where appropriate
- Metadata tables: etl_metadata, indicator_definitions, source_info, data_quality_results
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..utils.config import DATABASE_PATH, PIPELINE_VERSION, REPORTS_DIR, setup_logging, WHO_INDICATORS, WHO_API_BASE_URL

logger = setup_logging(__name__)

PIPELINE_VERSION_CONSTANT = PIPELINE_VERSION


class DatabaseLoader:
    """
    Idempotent SQLite loader with production-grade schema.
    """

    # ------------------------------------------------------------------
    # DDL - health_indicators with required snake_case per spec
    # Note: SQLite column names are case-insensitive, so we cannot have both "year" and "Year".
    # We use snake_case as canonical (required) and keep only legacy columns that are
    # case-insensitively distinct: CountryCode, Country, IndicatorCode, IndicatorDescription, SourceTimestamp
    # Services layer normalizes and creates legacy aliases in Python DataFrames after query.
    # ------------------------------------------------------------------
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS health_indicators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        -- Required snake_case columns per spec
        country_code TEXT NOT NULL,
        country_name TEXT,
        continent TEXT,
        year INTEGER NOT NULL,
        gender TEXT NOT NULL,
        indicator TEXT NOT NULL,
        indicator_code TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT,
        source TEXT,
        extracted_at TIMESTAMP,
        pipeline_version TEXT,
        -- Non-conflicting legacy columns for backward compatibility
        CountryCode TEXT,
        Country TEXT,
        IndicatorCode TEXT,
        IndicatorDescription TEXT,
        SourceTimestamp TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(country_code, year, gender, indicator, indicator_code)
    );
    """

    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_indicator ON health_indicators(indicator);",
        "CREATE INDEX IF NOT EXISTS idx_indicator_code ON health_indicators(indicator_code);",
        "CREATE INDEX IF NOT EXISTS idx_country ON health_indicators(country_code);",
        "CREATE INDEX IF NOT EXISTS idx_year ON health_indicators(year);",
        "CREATE INDEX IF NOT EXISTS idx_continent ON health_indicators(continent);",
        "CREATE INDEX IF NOT EXISTS idx_composite ON health_indicators(indicator, country_code, year);",
        "CREATE INDEX IF NOT EXISTS idx_legacy_country ON health_indicators(CountryCode);",
    ]

    CREATE_ETL_METADATA_SQL = """
    CREATE TABLE IF NOT EXISTS etl_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        indicator TEXT,
        indicator_code TEXT,
        records_extracted INTEGER,
        records_loaded INTEGER,
        records_replaced INTEGER,
        status TEXT,
        duration_seconds REAL,
        pipeline_version TEXT,
        source_url TEXT,
        notes TEXT
    );
    """

    CREATE_INDICATOR_DEFS_SQL = """
    CREATE TABLE IF NOT EXISTS indicator_definitions (
        indicator_name TEXT PRIMARY KEY,
        indicator_code TEXT NOT NULL UNIQUE,
        description TEXT,
        official_definition TEXT,
        short_definition TEXT,
        unit TEXT,
        source_url TEXT,
        who_odata_url TEXT,
        category TEXT,
        extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        pipeline_version TEXT
    );
    """

    CREATE_SOURCE_INFO_SQL = """
    CREATE TABLE IF NOT EXISTS source_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        pipeline_version TEXT,
        total_records_extracted INTEGER,
        total_records_loaded INTEGER,
        indicators_extracted TEXT,
        status TEXT,
        notes TEXT
    );
    """

    CREATE_DATA_QUALITY_SQL = """
    CREATE TABLE IF NOT EXISTS data_quality_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        data_mode TEXT,
        api_status TEXT,
        indicator_status TEXT,
        raw_records INTEGER,
        processed_records INTEGER,
        countries INTEGER,
        years INTEGER,
        year_range TEXT,
        missing_values INTEGER,
        invalid_numeric INTEGER,
        duplicate_rows INTEGER,
        duplicate_key_groups INTEGER,
        unmapped_countries TEXT,
        out_of_range_values INTEGER,
        indicator_coverage TEXT,
        api_latency_seconds REAL,
        total_duration_seconds REAL,
        overall_score REAL,
        report_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = str(db_path)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(self.CREATE_TABLE_SQL)
                for idx_sql in self.CREATE_INDEXES_SQL:
                    cur.execute(idx_sql)
                cur.execute(self.CREATE_ETL_METADATA_SQL)
                cur.execute(self.CREATE_INDICATOR_DEFS_SQL)
                cur.execute(self.CREATE_SOURCE_INFO_SQL)
                cur.execute(self.CREATE_DATA_QUALITY_SQL)
                conn.commit()
            logger.info(f"Database schema initialized at {self.db_path} (pipeline v{PIPELINE_VERSION_CONSTANT})")
        except Exception as e:
            logger.error(f"Failed to initialize database schema: {e}")
            raise

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    # ------------------------------------------------------------------
    # Loading with idempotency and atomic writes
    # ------------------------------------------------------------------
    def load_dataframe(
        self,
        df: pd.DataFrame,
        indicator_name: Optional[str] = None,
        replace: bool = False,
    ) -> int:
        if df.empty:
            logger.warning("Empty DataFrame, nothing to load")
            return 0

        replaced = 0
        try:
            with self._get_connection() as conn:
                if replace and indicator_name:
                    cur = conn.cursor()
                    cur.execute(
                        "DELETE FROM health_indicators WHERE indicator = ?",
                        (indicator_name,),
                    )
                    replaced = cur.rowcount
                    conn.commit()
                    logger.info(f"Replaced {replaced} existing records for {indicator_name}")

                load_df = self._prepare_for_load(df)

                # Ensure transaction atomicity
                conn.execute("BEGIN TRANSACTION")
                try:
                    load_df.to_sql(
                        "health_indicators",
                        conn,
                        if_exists="append",
                        index=False,
                        method="multi",
                        chunksize=1000,
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Transaction failed, rolled back: {e}")
                    raise

                loaded = len(load_df)
                logger.info(f"Loaded {loaded} records {'(replacing) ' if replace else ''}into database")
                return loaded

        except Exception as e:
            logger.error(f"Failed to load DataFrame: {e}")
            raise

    def _prepare_for_load(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame for insertion, ensuring snake_case columns per spec.
        Legacy columns that are case-insensitively distinct (CountryCode, Country,
        IndicatorCode, IndicatorDescription, SourceTimestamp) are preserved if available.
        """
        load_df = df.copy()

        # Convert categoricals to string for SQLite compatibility
        for col in load_df.columns:
            if isinstance(load_df[col].dtype, pd.CategoricalDtype):
                load_df[col] = load_df[col].astype(str)

        # Mapping legacy CamelCase -> snake_case for compatibility
        mapping_legacy_to_snake = {
            "CountryCode": "country_code",
            "Country": "country_name",
            "Continent": "continent",
            "Year": "year",
            "Gender": "gender",
            "Indicator": "indicator",
            "IndicatorCode": "indicator_code",
            "Value": "value",
            "IndicatorDescription": "source",
        }
        mapping_snake_to_legacy = {v: k for k, v in mapping_legacy_to_snake.items() if k in ["CountryCode", "Country", "IndicatorCode", "IndicatorDescription"]}

        # Ensure required snake_case columns exist (try to populate from legacy if missing)
        required_snake = ["country_code", "year", "gender", "indicator", "value"]
        for col in required_snake:
            if col not in load_df.columns:
                # Try legacy equivalents
                legacy_candidates = [k for k, v in mapping_legacy_to_snake.items() if v == col]
                found = False
                for legacy in legacy_candidates:
                    if legacy in load_df.columns:
                        load_df[col] = load_df[legacy]
                        found = True
                        break
                if not found:
                    raise ValueError(f"Missing required column: {col}")

        # Populate distinct legacy columns from snake if missing (only those that don't conflict)
        for legacy in ["CountryCode", "Country", "IndicatorCode", "IndicatorDescription"]:
            snake = mapping_legacy_to_snake.get(legacy)
            if snake and snake in load_df.columns and legacy not in load_df.columns:
                load_df[legacy] = load_df[snake]
            elif legacy in load_df.columns and snake and snake not in load_df.columns:
                load_df[snake] = load_df[legacy]

        # Ensure additional required columns per spec have defaults
        defaults = {
            "country_name": None,
            "continent": None,
            "indicator_code": "",
            "unit": "",
            "source": "WHO GHO OData API",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": PIPELINE_VERSION_CONSTANT,
            "Country": None,
            "CountryCode": None,
            "IndicatorCode": "",
            "IndicatorDescription": "",
            "SourceTimestamp": datetime.now(timezone.utc).isoformat(),
        }
        for col, default in defaults.items():
            if col not in load_df.columns:
                load_df[col] = default

        # Type coercion for snake columns
        try:
            load_df["year"] = pd.to_numeric(load_df["year"], errors="coerce").astype("Int64")
        except Exception:
            pass

        try:
            load_df["value"] = pd.to_numeric(load_df["value"], errors="coerce")
        except Exception:
            pass

        # Drop id and created_at if present in input
        for drop_col in ("id", "created_at"):
            if drop_col in load_df.columns:
                load_df = load_df.drop(columns=[drop_col])

        # Only keep columns that exist in table schema to avoid insert mismatch
        allowed_columns = [
            "country_code",
            "country_name",
            "continent",
            "year",
            "gender",
            "indicator",
            "indicator_code",
            "value",
            "unit",
            "source",
            "extracted_at",
            "pipeline_version",
            "CountryCode",
            "Country",
            "IndicatorCode",
            "IndicatorDescription",
            "SourceTimestamp",
        ]
        keep_cols = [c for c in allowed_columns if c in load_df.columns]
        load_df = load_df[keep_cols]

        return load_df

    def _table_exists(self, cur, table_name: str) -> bool:
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            return cur.fetchone() is not None
        except Exception:
            return False

    def load_all_indicators(
        self,
        df: pd.DataFrame,
        replace_all: bool = True,
    ) -> int:
        if replace_all:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    # Use transaction for atomic clear
                    conn.execute("BEGIN TRANSACTION")
                    try:
                        cur.execute("DELETE FROM health_indicators")
                        deleted = cur.rowcount
                        conn.commit()
                        logger.info(f"Cleared {deleted} existing records (atomic transaction)")
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Failed to clear existing data, rolled back: {e}")
                        raise
            except Exception as e:
                logger.error(f"Failed to clear existing data: {e}")
                raise

        return self.load_dataframe(df, replace=False)

    def atomic_replace_database(self, new_db_path: str, backup: bool = True) -> None:
        """
        Safe temporary database replacement: replace current DB with new one atomically.
        Uses file rename which is atomic on POSIX.
        """
        import shutil

        new_path = Path(new_db_path)
        current_path = Path(self.db_path)

        if not new_path.exists():
            raise FileNotFoundError(f"New database file not found: {new_path}")

        # Validate new DB has table
        try:
            conn = sqlite3.connect(str(new_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='health_indicators'")
            if not cur.fetchone():
                conn.close()
                raise ValueError("New database missing health_indicators table")
            conn.close()
        except Exception as e:
            raise ValueError(f"New database validation failed: {e}")

        temp_dir = current_path.parent
        if backup and current_path.exists():
            backup_path = temp_dir / f"{current_path.name}.bak.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            shutil.copy2(str(current_path), str(backup_path))
            logger.info(f"Backed up current database to {backup_path}")

        # Atomic replace via temporary file + rename
        # SQLite WAL may have -wal and -shm files, remove them after replace
        try:
            # Rename new to current (atomic on same filesystem)
            # First, ensure current is removed or use replace
            new_path.replace(current_path)
            logger.info(f"Atomically replaced database {current_path} with {new_path}")
            # Clean WAL files
            for suffix in ["-wal", "-shm"]:
                wal_path = Path(str(current_path) + suffix)
                if wal_path.exists():
                    wal_path.unlink()
                    logger.info(f"Removed WAL file {wal_path}")
        except Exception as e:
            logger.error(f"Atomic replace failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------
    def query(self, sql: str, params: Optional[tuple] = None) -> pd.DataFrame:
        try:
            with self._get_connection() as conn:
                return pd.read_sql_query(sql, conn, params=params)
        except Exception as e:
            logger.error(f"Query failed: {e} SQL={sql}")
            raise

    def get_table_info(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]

            info: Dict[str, Any] = {"tables": {}}
            for table in tables:
                cur.execute(f"PRAGMA table_info({table})")
                columns = [
                    {"name": r[1], "type": r[2], "nullable": not r[3]}
                    for r in cur.fetchall()
                ]
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                row_count = cur.fetchone()[0]
                info["tables"][table] = {"columns": columns, "row_count": row_count}
            return info

    def validate_schema(self) -> Dict[str, Any]:
        """
        Validate that health_indicators has required columns per spec.
        Returns dict with validation result.
        """
        required_columns = [
            "country_code",
            "country_name",
            "continent",
            "year",
            "gender",
            "indicator",
            "value",
            "unit",
            "source",
            "extracted_at",
            "pipeline_version",
        ]
        info = self.get_table_info()
        health_info = info["tables"].get("health_indicators", {})
        present = [c["name"] for c in health_info.get("columns", [])]
        missing = [c for c in required_columns if c not in present]

        # Also check additional tables exist
        required_tables = ["etl_metadata", "indicator_definitions", "source_info", "data_quality_results"]
        missing_tables = [t for t in required_tables if t not in info["tables"]]

        is_valid = len(missing) == 0 and len(missing_tables) == 0
        return {
            "is_valid": is_valid,
            "required_columns": required_columns,
            "present_columns": present,
            "missing_columns": missing,
            "required_tables": required_tables,
            "missing_tables": missing_tables,
            "tables_info": info,
        }

    # ------------------------------------------------------------------
    # Metadata writes
    # ------------------------------------------------------------------
    def log_etl_run(
        self,
        indicator: str,
        records_loaded: int,
        status: str,
        duration_seconds: float,
        notes: str = "",
        indicator_code: str = "",
        records_extracted: int = 0,
        records_replaced: int = 0,
        source_url: str = "",
    ) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO etl_metadata
                       (indicator, indicator_code, records_extracted,
                        records_loaded, records_replaced, status,
                        duration_seconds, pipeline_version, source_url, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        indicator,
                        indicator_code,
                        records_extracted,
                        records_loaded,
                        records_replaced,
                        status,
                        duration_seconds,
                        PIPELINE_VERSION_CONSTANT,
                        source_url,
                        notes,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log ETL run: {e}")

    def log_source_info(
        self,
        source_name: str,
        source_url: str,
        total_extracted: int,
        total_loaded: int,
        indicators: List[str],
        status: str,
        notes: str = "",
    ) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO source_info
                       (source_name, source_url, pipeline_version,
                        total_records_extracted, total_records_loaded,
                        indicators_extracted, status, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_name,
                        source_url,
                        PIPELINE_VERSION_CONSTANT,
                        total_extracted,
                        total_loaded,
                        ", ".join(indicators),
                        status,
                        notes,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log source info: {e}")

    def register_indicator(
        self,
        name: str,
        code: str,
        description: str = "",
        unit: str = "",
        source_url: str = "",
        official_definition: str = "",
        short_definition: str = "",
        who_odata_url: str = "",
        category: str = "",
    ) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO indicator_definitions
                       (indicator_name, indicator_code, description, official_definition,
                        short_definition, unit, source_url, who_odata_url, category,
                        extraction_timestamp, pipeline_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name,
                        code,
                        description,
                        official_definition,
                        short_definition,
                        unit,
                        source_url,
                        who_odata_url,
                        category,
                        datetime.now(timezone.utc).isoformat(),
                        PIPELINE_VERSION_CONSTANT,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to register indicator {name}: {e}")

    def register_all_indicators(self) -> None:
        """Register all indicators from config with full metadata."""
        for name, info in WHO_INDICATORS.items():
            self.register_indicator(
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
        logger.info(f"Registered {len(WHO_INDICATORS)} indicator definitions with full metadata")

    # ------------------------------------------------------------------
    # Data quality results storage
    # ------------------------------------------------------------------
    def save_data_quality_report(self, report: Dict[str, Any]) -> int:
        """
        Save a data quality report to data_quality_results table.
        Report should contain keys as per required spec.
        """
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO data_quality_results
                       (extraction_timestamp, data_mode, api_status, indicator_status,
                        raw_records, processed_records, countries, years, year_range,
                        missing_values, invalid_numeric, duplicate_rows, duplicate_key_groups,
                        unmapped_countries, out_of_range_values, indicator_coverage,
                        api_latency_seconds, total_duration_seconds, overall_score, report_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        report.get("extraction_timestamp_utc") or report.get("extraction_timestamp") or datetime.now(timezone.utc).isoformat(),
                        report.get("data_mode", "live"),
                        report.get("api_status", "unknown"),
                        json.dumps(report.get("indicator_status", {})),
                        report.get("raw_records", 0),
                        report.get("processed_records", 0),
                        report.get("countries", 0),
                        report.get("years", 0),
                        json.dumps(report.get("year_range", {})) if isinstance(report.get("year_range"), (tuple, list, dict)) else str(report.get("year_range", "")),
                        report.get("missing_values", 0),
                        report.get("invalid_numeric", 0),
                        report.get("duplicate_rows", 0),
                        report.get("duplicate_key_groups", 0),
                        json.dumps(report.get("unmapped_countries", {})),
                        report.get("out_of_range_values", 0),
                        json.dumps(report.get("indicator_coverage", {})),
                        report.get("api_latency_seconds", 0.0),
                        report.get("total_duration_seconds", 0.0),
                        report.get("overall_score", 0.0),
                        json.dumps(report, default=str),
                    ),
                )
                conn.commit()
                logger.info(f"Saved data quality report id={cur.lastrowid} score={report.get('overall_score')}")
                return cur.lastrowid
        except Exception as e:
            logger.error(f"Failed to save data quality report: {e}")
            raise

    def get_latest_quality_report(self) -> Optional[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                df = pd.read_sql_query(
                    "SELECT * FROM data_quality_results ORDER BY id DESC LIMIT 1", conn
                )
                if df.empty:
                    return None
                row = df.iloc[0].to_dict()
                # Parse JSON fields back
                for field in ["indicator_status", "unmapped_countries", "indicator_coverage", "report_json", "year_range"]:
                    if field in row and isinstance(row[field], str):
                        try:
                            row[field] = json.loads(row[field])
                        except Exception:
                            pass
                return row
        except Exception as e:
            logger.error(f"Failed to get latest quality report: {e}")
            return None

    def export_quality_report_json(self, output_path: Path = REPORTS_DIR / "data_quality_report.json") -> Path:
        """Export latest report (or generate from current DB state) to JSON file as required."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        latest = self.get_latest_quality_report()
        if latest:
            # Use stored report_json if available
            report_json_str = latest.get("report_json")
            if isinstance(report_json_str, dict):
                content = report_json_str
            elif isinstance(report_json_str, str):
                try:
                    content = json.loads(report_json_str)
                except Exception:
                    content = latest
            else:
                content = latest
        else:
            # Generate minimal report from current DB if no quality report exists
            content = {
                "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "data_mode": "unknown",
                "api_status": "unknown",
                "message": "No quality report in DB, generated minimal snapshot",
            }

        output_path.write_text(json.dumps(content, indent=2, default=str), encoding="utf-8")
        logger.info(f"Exported data quality report to {output_path}")
        return output_path
