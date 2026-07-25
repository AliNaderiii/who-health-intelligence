"""
Main ETL pipeline orchestrator for WHO health data.

Coordinates the full Extract-Transform-Load workflow including:
- API data extraction
- Data transformation and validation
- Geographic metadata enrichment
- Idempotent database loading
- Data quality reporting
"""

import time
from typing import Dict, List, Optional, Any
import pandas as pd

from ..api.client import WHOAPIClient
from ..utils.config import (
    WHO_INDICATORS,
    DEFAULT_INDICATORS,
    DATABASE_PATH,
    setup_logging
)
from .transform import transform_indicator_records, merge_indicator_dataframes
from .metadata import normalize_geography
from .loader import DatabaseLoader
from .quality import DataQualityReport

logger = setup_logging(__name__)


class WHOETLPipeline:
    """
    Orchestrates the complete ETL pipeline for WHO health indicator data.
    
    Usage:
        pipeline = WHOETLPipeline()
        report = pipeline.run(indicators=['NCD_MORTALITY', 'UHC_COVERAGE'])
        print(report['quality_score'])
    
    Attributes:
        client: WHO API client instance
        loader: Database loader instance
        data_dir: Path to data directory
    """
    
    def __init__(
        self,
        db_path: str = DATABASE_PATH,
        api_client: Optional[WHOAPIClient] = None
    ):
        """
        Initialize the ETL pipeline.
        
        Args:
            db_path: Path to the SQLite database
            api_client: Optional pre-configured API client
        """
        self.client = api_client or WHOAPIClient()
        self.loader = DatabaseLoader(db_path)
        self.results: Dict[str, Any] = {}
    
    def run(
        self,
        indicators: Optional[List[str]] = None,
        replace: bool = True,
        generate_quality_report: bool = True
    ) -> Dict[str, Any]:
        """
        Execute the full ETL pipeline.
        
        Args:
            indicators: List of indicator names to extract. 
                       Defaults to DEFAULT_INDICATORS.
            replace: If True, replace existing data in database
            generate_quality_report: If True, generate quality report after loading
            
        Returns:
            Dictionary with pipeline results including quality metrics
        """
        if indicators is None:
            indicators = DEFAULT_INDICATORS
        
        start_time = time.time()
        
        logger.info(f"Starting ETL pipeline for {len(indicators)} indicators")
        logger.info(f"Indicators: {indicators}")
        
        results = {
            'indicators': indicators,
            'extraction': {},
            'transformation': {},
            'loading': {},
            'quality_report': None,
            'total_duration_seconds': 0,
            'status': 'running'
        }
        
        try:
            # Step 1: Extract
            logger.info("=" * 60)
            logger.info("STEP 1: EXTRACT")
            logger.info("=" * 60)
            
            raw_data = {}
            for indicator_name in indicators:
                if indicator_name not in WHO_INDICATORS:
                    logger.warning(f"Unknown indicator: {indicator_name}")
                    continue
                
                indicator_code = WHO_INDICATORS[indicator_name]['code']
                extract_start = time.time()
                
                try:
                    records = self.client.extract_indicator(indicator_code)
                    raw_data[indicator_name] = records
                    
                    results['extraction'][indicator_name] = {
                        'records_extracted': len(records),
                        'status': 'success',
                        'duration_seconds': round(time.time() - extract_start, 2)
                    }
                    
                except Exception as e:
                    logger.error(f"Extraction failed for {indicator_name}: {e}")
                    raw_data[indicator_name] = []
                    results['extraction'][indicator_name] = {
                        'records_extracted': 0,
                        'status': 'failed',
                        'error': str(e),
                        'duration_seconds': round(time.time() - extract_start, 2)
                    }
            
            # Step 2: Transform
            logger.info("=" * 60)
            logger.info("STEP 2: TRANSFORM")
            logger.info("=" * 60)
            
            transformed_dfs = {}
            for indicator_name, records in raw_data.items():
                transform_start = time.time()
                
                if not records:
                    logger.warning(f"No records for {indicator_name}, skipping transform")
                    results['transformation'][indicator_name] = {
                        'records_transformed': 0,
                        'status': 'skipped'
                    }
                    continue
                
                indicator_code = WHO_INDICATORS.get(indicator_name, {}).get('code', '')
                df = transform_indicator_records(records, indicator_name, indicator_code)
                
                # Normalize geography
                df = normalize_geography(df)
                
                transformed_dfs[indicator_name] = df
                
                results['transformation'][indicator_name] = {
                    'records_transformed': len(df),
                    'countries': df['CountryCode'].nunique() if not df.empty else 0,
                    'years': sorted(df['Year'].unique().tolist()) if not df.empty else [],
                    'status': 'success',
                    'duration_seconds': round(time.time() - transform_start, 2)
                }
            
            if not transformed_dfs:
                logger.error("No data was successfully transformed")
                results['status'] = 'failed'
                results['error'] = 'No data transformed'
                return results
            
            # Merge all indicator data
            merged_df = merge_indicator_dataframes(transformed_dfs)
            
            # Step 3: Load
            logger.info("=" * 60)
            logger.info("STEP 3: LOAD")
            logger.info("=" * 60)
            
            load_start = time.time()
            records_loaded = self.loader.load_all_indicators(merged_df, replace_all=replace)
            
            results['loading'] = {
                'records_loaded': records_loaded,
                'status': 'success',
                'duration_seconds': round(time.time() - load_start, 2)
            }
            
            # Log ETL run in metadata
            total_duration = round(time.time() - start_time, 2)
            self.loader.log_etl_run(
                indicator='ALL',
                records_loaded=records_loaded,
                status='success',
                duration_seconds=total_duration
            )
            
            # Step 4: Quality Report
            if generate_quality_report:
                logger.info("=" * 60)
                logger.info("STEP 4: DATA QUALITY REPORT")
                logger.info("=" * 60)
                
                quality_report = DataQualityReport(merged_df)
                report = quality_report.generate_full_report()
                results['quality_report'] = report
                
                # Save markdown report
                md_report = quality_report.to_markdown()
                results['quality_report_md'] = md_report
            
            results['status'] = 'success'
            results['total_duration_seconds'] = round(time.time() - start_time, 2)
            
            logger.info(
                f"ETL pipeline completed successfully in "
                f"{results['total_duration_seconds']}s"
            )
            
        except Exception as e:
            logger.error(f"ETL pipeline failed: {e}")
            results['status'] = 'failed'
            results['error'] = str(e)
            results['total_duration_seconds'] = round(time.time() - start_time, 2)
        
        self.results = results
        return results
    
    def load_from_existing_db(self) -> pd.DataFrame:
        """
        Load data from the existing database.
        
        Returns:
            DataFrame with all data from the health_indicators table
        """
        return self.loader.query("SELECT * FROM health_indicators")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the latest pipeline run."""
        if not self.results:
            return {'status': 'no_run', 'message': 'No pipeline run recorded'}
        
        return {
            'status': self.results.get('status'),
            'indicators': self.results.get('indicators'),
            'total_records': self.results.get('loading', {}).get('records_loaded', 0),
            'duration_seconds': self.results.get('total_duration_seconds', 0),
            'quality_score': (
                self.results.get('quality_report', {}).get('overall_score', 0)
                if self.results.get('quality_report') else 0
            )
        }
