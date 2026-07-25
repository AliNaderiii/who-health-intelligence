import requests
import sqlite3
import pandas as pd 
import logging
from typing import Dict, List, Optional
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WHO_ETL_Pipeline")

class WHODataExtractor:
    """
    A robust ETL pipeline for extracting, transforming, and loading 
    Global Health indicators from the WHO GHO OData API.
    """
    
    BASE_URL = "https://ghoapi.azureedge.net/api/"
    
    def __init__(self, db_path: str = "who_data.db"):
        """
        Initializes the pipeline with a target SQLite database path.
        
        Args:
            db_path (str): The local path to the SQLite database.
        """
        self.db_path = db_path
        self.indicators = {
            "Life_Expectancy": "WHOSIS_000001",
            "NCD_Mortality": "NCDMORT3070",
            "UHC_Coverage": "UHC_INDEX_REPORTED"
        }
        
    def extract_indicator(self, indicator_code: str, max_retries: int = 3) -> List[Dict]:
        """
        Extracts data for a specific indicator from the WHO API with retry logic.
        
        Args:
            indicator_code (str): The WHO GHO indicator code.
            max_retries (int): Maximum number of retry attempts for network failures.
            
        Returns:
            List[Dict]: A list of dictionary records representing the JSON data.
        """
        url = f"{self.BASE_URL}{indicator_code}"
        records = []
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Extracting data for {indicator_code}. Attempt {attempt + 1}...")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                if 'value' in data:
                    records = data['value']
                    logger.info(f"Successfully extracted {len(records)} records for {indicator_code}.")
                    return records
                else:
                    logger.warning(f"Unexpected JSON structure for {indicator_code}: 'value' key missing.")
                    return []
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"HTTP request failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt) # Exponential backoff
                else:
                    logger.error(f"Failed to extract {indicator_code} after {max_retries} attempts.")
                    
        return records

    def transform_data(self, records: List[Dict], indicator_name: str) -> pd.DataFrame:
        """
        Transforms the raw JSON records into a clean, memory-efficient Pandas DataFrame.
        
        Args:
            records (List[Dict]): The raw JSON records.
            indicator_name (str): The human-readable name of the indicator.
            
        Returns:
            pd.DataFrame: The cleaned and optimized DataFrame.
        """
        if not records:
            return pd.DataFrame()
            
        df = pd.DataFrame(records)
        
        # Select and rename relevant columns
        cols_to_keep = {
            'SpatialDim': 'CountryCode',
            'TimeDim': 'Year',
            'Dim1': 'Gender',
            'NumericValue': 'Value'
        }
        
        # Keep only existing columns
        existing_cols = {k: v for k, v in cols_to_keep.items() if k in df.columns}
        df = df[list(existing_cols.keys())].rename(columns=existing_cols)
        
        # Add indicator name column
        df['Indicator'] = indicator_name
        
        # Clean missing values
        df = df.dropna(subset=['Value', 'CountryCode', 'Year'])
        
        # Handle gender column if missing
        if 'Gender' not in df.columns:
            df['Gender'] = 'Total'
        else:
            df['Gender'] = df['Gender'].fillna('Total')
            
        # Memory Efficiency: Downcast data types
        df['Year'] = df['Year'].astype('int32')
        df['CountryCode'] = df['CountryCode'].astype('category')
        df['Gender'] = df['Gender'].astype('category')
        df['Indicator'] = df['Indicator'].astype('category')
        df['Value'] = pd.to_numeric(df['Value'], errors='coerce').astype('float32')
        
        # Drop any remaining NaNs introduced by to_numeric
        df = df.dropna(subset=['Value'])
        
        logger.info(f"Transformed {indicator_name} data. Final shape: {df.shape}. Memory usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
        return df

    def load_data(self, df: pd.DataFrame, table_name: str = "health_indicators"):
        """
        Loads the transformed DataFrame into a SQLite database.
        
        Args:
            df (pd.DataFrame): The transformed DataFrame.
            table_name (str): The name of the target SQLite table.
        """
        if df.empty:
            logger.warning("Empty DataFrame provided. Skipping load step.")
            return
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                df.to_sql(table_name, conn, if_exists='append', index=False)
                logger.info(f"Successfully loaded {len(df)} records into {table_name} table.")
        except Exception as e:
            logger.error(f"Failed to load data into database: {e}")

    def run_pipeline(self):
        """
        Executes the full ETL pipeline for all defined indicators.
        """
        logger.info("Starting WHO ETL Pipeline...")
        
        # Initialize/clear database table
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS health_indicators")
                conn.commit()
        except Exception as e:
            logger.error(f"Error resetting database: {e}")

        for name, code in self.indicators.items():
            # 1. Extract
            raw_data = self.extract_indicator(code)
            
            # 2. Transform
            clean_df = self.transform_data(raw_data, name)
            
            # 3. Load
            self.load_data(clean_df)
            
        logger.info("WHO ETL Pipeline execution completed.")

if __name__ == "__main__":
    extractor = WHODataExtractor(db_path="who_data.db")
    extractor.run_pipeline()

