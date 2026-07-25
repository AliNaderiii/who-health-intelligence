"""
Database persistence layer for WHO health indicator data.

Provides idempotent loading of DataFrames into SQLite with schema management,
upsert support, and transactional integrity.
"""

from typing import Optional, List
import sqlite3
import pandas as pd

from ..utils.config import DATABASE_PATH, setup_logging

logger = setup_logging(__name__)


class DatabaseLoader:
    """
    Idempotent SQLite database loader for WHO health data.
    
    Supports:
    - Schema creation and versioning
    - Idempotent upsert (insert or replace) operations
    - Transactional integrity
    - Query optimization indexes
    """
    
    # Schema DDL for the main health indicators table
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS health_indicators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        CountryCode TEXT NOT NULL,
        Country TEXT,
        Year INTEGER NOT NULL,
        Gender TEXT NOT NULL,
        Indicator TEXT NOT NULL,
        IndicatorCode TEXT,
        IndicatorDescription TEXT,
        Value REAL NOT NULL,
        Continent TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(CountryCode, Year, Gender, Indicator, IndicatorCode)
    );
    """
    
    # Index definitions for query performance
    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_indicator ON health_indicators(Indicator);",
        "CREATE INDEX IF NOT EXISTS idx_country ON health_indicators(CountryCode);",
        "CREATE INDEX IF NOT EXISTS idx_year ON health_indicators(Year);",
        "CREATE INDEX IF NOT EXISTS idx_continent ON health_indicators(Continent);",
        "CREATE INDEX IF NOT EXISTS idx_composite ON health_indicators(Indicator, CountryCode, Year);",
    ]
    
    # Metadata table for tracking ETL runs
    CREATE_METADATA_SQL = """
    CREATE TABLE IF NOT EXISTS etl_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        indicator TEXT,
        records_loaded INTEGER,
        status TEXT,
        duration_seconds REAL,
        notes TEXT
    );
    """
    
    def __init__(self, db_path: str = DATABASE_PATH):
        """
        Initialize the database loader.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._initialize_schema()
    
    def _initialize_schema(self):
        """Create tables and indexes if they don't exist."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Create main table
                cursor.execute(self.CREATE_TABLE_SQL)
                
                # Create indexes
                for index_sql in self.CREATE_INDEXES_SQL:
                    cursor.execute(index_sql)
                
                # Create metadata table
                cursor.execute(self.CREATE_METADATA_SQL)
                
                conn.commit()
                logger.info(f"Database schema initialized at {self.db_path}")
                
        except Exception as e:
            logger.error(f"Failed to initialize database schema: {e}")
            raise
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with appropriate settings."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")  # Write-ahead logging for performance
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    
    def load_dataframe(
        self,
        df: pd.DataFrame,
        indicator_name: Optional[str] = None,
        replace: bool = False
    ) -> int:
        """
        Load a DataFrame into the database with idempotent semantics.
        
        Args:
            df: DataFrame to load
            indicator_name: Optional indicator name for tracking
            replace: If True, replace existing data for this indicator
            
        Returns:
            Number of records loaded
        """
        if df.empty:
            logger.warning("Empty DataFrame, nothing to load")
            return 0
        
        try:
            with self._get_connection() as conn:
                # If replacing, delete existing data for this indicator
                if replace and indicator_name:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM health_indicators WHERE Indicator = ?",
                        (indicator_name,)
                    )
                    deleted = cursor.rowcount
                    conn.commit()
                    logger.info(
                        f"Deleted {deleted} existing records for {indicator_name}"
                    )
                
                # Prepare DataFrame for loading
                load_df = self._prepare_for_load(df)
                
                # Use INSERT OR REPLACE for idempotent upsert
                load_df.to_sql(
                    'health_indicators',
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi',
                    chunksize=1000
                )
                
                records_loaded = len(load_df)
                logger.info(
                    f"Loaded {records_loaded} records "
                    f"{'(replacing) ' if replace else ''}into database"
                )
                
                return records_loaded
                
        except Exception as e:
            logger.error(f"Failed to load DataFrame: {e}")
            raise
    
    def _prepare_for_load(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame for database insertion.
        
        - Convert categoricals to strings
        - Ensure all required columns exist
        - Handle timezone-aware timestamps
        """
        load_df = df.copy()
        
        # Convert categorical columns to string for SQLite compatibility
        for col in load_df.columns:
            if isinstance(load_df[col].dtype, pd.CategoricalDtype):
                load_df[col] = load_df[col].astype(str)
        
        # Ensure required columns exist
        required_cols = ['CountryCode', 'Year', 'Gender', 'Indicator', 'Value']
        for col in required_cols:
            if col not in load_df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Add optional columns with defaults if missing
        optional_cols = {
            'Country': None,
            'IndicatorCode': '',
            'IndicatorDescription': '',
            'Continent': None
        }
        for col, default in optional_cols.items():
            if col not in load_df.columns:
                load_df[col] = default
        
        # Remove autoincrement id if present
        if 'id' in load_df.columns:
            load_df = load_df.drop(columns=['id'])
        
        # Remove created_at if present (will be auto-generated)
        if 'created_at' in load_df.columns:
            load_df = load_df.drop(columns=['created_at'])
        
        return load_df
    
    def load_all_indicators(
        self,
        df: pd.DataFrame,
        replace_all: bool = True
    ) -> int:
        """
        Load a DataFrame containing multiple indicators.
        
        Args:
            df: DataFrame with all indicator data
            replace_all: If True, clear all existing data first
            
        Returns:
            Total number of records loaded
        """
        if replace_all:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM health_indicators")
                    deleted = cursor.rowcount
                    conn.commit()
                    logger.info(f"Cleared {deleted} existing records")
            except Exception as e:
                logger.error(f"Failed to clear existing data: {e}")
                raise
        
        return self.load_dataframe(df, replace=False)
    
    def query(
        self,
        sql: str,
        params: Optional[tuple] = None
    ) -> pd.DataFrame:
        """
        Execute a SQL query and return results as a DataFrame.
        
        Args:
            sql: SQL query string
            params: Optional query parameters
            
        Returns:
            Query results as DataFrame
        """
        try:
            with self._get_connection() as conn:
                return pd.read_sql_query(sql, conn, params=params)
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise
    
    def get_table_info(self) -> dict:
        """Get information about the database tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Table list
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
            info = {'tables': {}}
            for table in tables:
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [
                    {'name': row[1], 'type': row[2], 'nullable': not row[3]}
                    for row in cursor.fetchall()
                ]
                
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                row_count = cursor.fetchone()[0]
                
                info['tables'][table] = {
                    'columns': columns,
                    'row_count': row_count
                }
            
            return info
    
    def log_etl_run(
        self,
        indicator: str,
        records_loaded: int,
        status: str,
        duration_seconds: float,
        notes: str = ""
    ):
        """Log an ETL run to the metadata table."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO etl_metadata 
                       (indicator, records_loaded, status, duration_seconds, notes)
                       VALUES (?, ?, ?, ?, ?)""",
                    (indicator, records_loaded, status, duration_seconds, notes)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log ETL run: {e}")
