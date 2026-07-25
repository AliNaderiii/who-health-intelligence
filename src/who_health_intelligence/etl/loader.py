"""
Database persistence layer for WHO health indicator data.

Provides idempotent loading of DataFrames into SQLite with:
- Explicit schema with typed columns and UNIQUE constraints
- Upsert semantics (INSERT OR REPLACE) for idempotency
- Transactional integrity (WAL journal mode)
- Metadata tables for indicators, sources, and ETL run tracking
"""

from typing import Any, Dict, List, Optional
import sqlite3

import pandas as pd

from ..utils.config import DATABASE_PATH, setup_logging

logger = setup_logging(__name__)

# Pipeline version — increment when schema or logic changes
PIPELINE_VERSION = "3.0.0"


class DatabaseLoader:
    """
    Idempotent SQLite database loader for WHO health data.

    Schema design decisions:
    - ``UNIQUE(CountryCode, Year, Gender, Indicator, IndicatorCode)`` ensures
      that re-running the pipeline does not create duplicates.
    - ``INSERT OR REPLACE`` is used on the application side (via pandas
      ``to_sql`` + a pre-delete) so that repeated runs with the same data
      produce the same database state (idempotency).
    - ``created_at`` records when each row was inserted.
    """

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS health_indicators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        CountryCode TEXT NOT NULL,
        Country TEXT,
        Year INTEGER NOT NULL,
        Gender TEXT NOT NULL,
        Indicator TEXT NOT NULL,
        IndicatorCode TEXT NOT NULL,
        IndicatorDescription TEXT,
        Value REAL NOT NULL,
        Continent TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(CountryCode, Year, Gender, Indicator, IndicatorCode)
    );
    """

    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_indicator ON health_indicators(Indicator);",
        "CREATE INDEX IF NOT EXISTS idx_country ON health_indicators(CountryCode);",
        "CREATE INDEX IF NOT EXISTS idx_year ON health_indicators(Year);",
        "CREATE INDEX IF NOT EXISTS idx_continent ON health_indicators(Continent);",
        "CREATE INDEX IF NOT EXISTS idx_composite ON health_indicators(Indicator, CountryCode, Year);",
    ]

    # ETL run tracking
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

    # Indicator definitions table
    CREATE_INDICATOR_DEFS_SQL = """
    CREATE TABLE IF NOT EXISTS indicator_definitions (
        indicator_name TEXT PRIMARY KEY,
        indicator_code TEXT NOT NULL UNIQUE,
        description TEXT,
        unit TEXT,
        source_url TEXT,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    # Source information table
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

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create all tables and indexes if they don't exist."""
        try:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute(self.CREATE_TABLE_SQL)
                for idx_sql in self.CREATE_INDEXES_SQL:
                    cur.execute(idx_sql)
                cur.execute(self.CREATE_ETL_METADATA_SQL)
                cur.execute(self.CREATE_INDICATOR_DEFS_SQL)
                cur.execute(self.CREATE_SOURCE_INFO_SQL)
                conn.commit()
            logger.info("Database schema initialized at %s", self.db_path)
        except Exception as e:
            logger.error("Failed to initialize database schema: %s", e)
            raise

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_dataframe(
        self,
        df: pd.DataFrame,
        indicator_name: Optional[str] = None,
        replace: bool = False,
    ) -> int:
        """
        Load a DataFrame with idempotent semantics.

        When ``replace=True``, existing rows for the given indicator are
        deleted first, then the new data is inserted. This makes repeated
        runs produce the same result (idempotency).

        The UNIQUE constraint on the table also prevents accidental
        duplicates if ``replace=False`` is used.

        Args:
            df: DataFrame to load.
            indicator_name: Indicator name (used for replace scope).
            replace: If True, delete existing rows for this indicator first.

        Returns:
            Number of records loaded.
        """
        if df.empty:
            logger.warning("Empty DataFrame, nothing to load")
            return 0

        replaced = 0
        try:
            with self._get_connection() as conn:
                if replace and indicator_name:
                    cur = conn.cursor()
                    cur.execute(
                        "DELETE FROM health_indicators WHERE Indicator = ?",
                        (indicator_name,),
                    )
                    replaced = cur.rowcount
                    conn.commit()
                    logger.info(
                        "Replaced %d existing records for %s",
                        replaced,
                        indicator_name,
                    )

                load_df = self._prepare_for_load(df)

                load_df.to_sql(
                    "health_indicators",
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=1000,
                )

                loaded = len(load_df)
                logger.info(
                    "Loaded %d records %sinto database",
                    loaded,
                    "(replacing) " if replace else "",
                )
                return loaded

        except Exception as e:
            logger.error("Failed to load DataFrame: %s", e)
            raise

    def _prepare_for_load(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare DataFrame for insertion: convert types, fill defaults."""
        load_df = df.copy()

        for col in load_df.columns:
            if isinstance(load_df[col].dtype, pd.CategoricalDtype):
                load_df[col] = load_df[col].astype(str)

        required = ["CountryCode", "Year", "Gender", "Indicator", "Value"]
        for col in required:
            if col not in load_df.columns:
                raise ValueError(f"Missing required column: {col}")

        defaults = {"Country": None, "IndicatorCode": "", "IndicatorDescription": "", "Continent": None}
        for col, default in defaults.items():
            if col not in load_df.columns:
                load_df[col] = default

        for drop_col in ("id", "created_at"):
            if drop_col in load_df.columns:
                load_df = load_df.drop(columns=[drop_col])

        return load_df

    def load_all_indicators(
        self,
        df: pd.DataFrame,
        replace_all: bool = True,
    ) -> int:
        """Load a multi-indicator DataFrame."""
        if replace_all:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM health_indicators")
                    deleted = cur.rowcount
                    conn.commit()
                    logger.info("Cleared %d existing records", deleted)
            except Exception as e:
                logger.error("Failed to clear existing data: %s", e)
                raise

        return self.load_dataframe(df, replace=False)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(self, sql: str, params: Optional[tuple] = None) -> pd.DataFrame:
        """Execute a SQL query and return results as a DataFrame."""
        try:
            with self._get_connection() as conn:
                return pd.read_sql_query(sql, conn, params=params)
        except Exception as e:
            logger.error("Query failed: %s", e)
            raise

    def get_table_info(self) -> Dict[str, Any]:
        """Return metadata about all tables in the database."""
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
        """Log an ETL run to the ``etl_metadata`` table."""
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
                        PIPELINE_VERSION,
                        source_url,
                        notes,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to log ETL run: %s", e)

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
        """Log overall source information for an ETL run."""
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
                        PIPELINE_VERSION,
                        total_extracted,
                        total_loaded,
                        ", ".join(indicators),
                        status,
                        notes,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to log source info: %s", e)

    def register_indicator(
        self,
        name: str,
        code: str,
        description: str = "",
        unit: str = "",
        source_url: str = "",
    ) -> None:
        """Register an indicator definition (upsert)."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO indicator_definitions
                       (indicator_name, indicator_code, description, unit, source_url)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, code, description, unit, source_url),
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to register indicator %s: %s", name, e)
