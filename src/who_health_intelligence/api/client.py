"""
WHO Global Health Observatory (GHO) API Client.

Provides robust extraction of health indicators from the WHO GHO OData API
with comprehensive error handling, retry logic, and response validation.

API Documentation: https://www.who.int/data/gho/info/gho-odata-api
"""

import time
from typing import Dict, List, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.config import (
    WHO_API_BASE_URL,
    API_TIMEOUT_SECONDS,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_BASE,
    WHO_INDICATORS,
    setup_logging
)

logger = setup_logging(__name__)


class WHOAPIClient:
    """
    Client for interacting with the WHO GHO OData API.
    
    Implements robust HTTP session management with automatic retries,
    timeout handling, and response validation.
    
    Attributes:
        base_url: Base URL for WHO GHO API
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        session: HTTP session with retry configuration
    """
    
    def __init__(
        self,
        base_url: str = WHO_API_BASE_URL,
        timeout: int = API_TIMEOUT_SECONDS,
        max_retries: int = API_MAX_RETRIES
    ):
        """
        Initialize the WHO API client.
        
        Args:
            base_url: Base URL for the API
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        """
        Create an HTTP session with automatic retry configuration.
        
        Implements exponential backoff for transient failures (5xx, timeouts,
        connection errors).
        
        Returns:
            Configured requests.Session instance
        """
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=API_RETRY_BACKOFF_BASE,
            status_forcelist=[429, 500, 502, 503, 504],  # Rate limit + server errors
            allowed_methods=["GET"],  # Only retry GET requests
            raise_on_status=False
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Set default headers
        session.headers.update({
            "User-Agent": "WHO-Health-Intelligence-Platform/2.0",
            "Accept": "application/json"
        })
        
        return session
    
    def extract_indicator(
        self,
        indicator_code: str,
        filters: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract data for a specific WHO indicator.
        
        Args:
            indicator_code: WHO GHO indicator code (e.g., 'WHOSIS_000001')
            filters: Optional OData filters (e.g., {'SpatialDim': 'USA'})
            
        Returns:
            List of JSON records from the API response
            
        Raises:
            requests.exceptions.RequestException: If all retry attempts fail
            ValueError: If response structure is invalid
        """
        url = f"{self.base_url}/{indicator_code}"
        
        logger.info(f"Extracting indicator: {indicator_code}")
        logger.debug(f"URL: {url}, Filters: {filters}")
        
        try:
            response = self.session.get(
                url,
                params=filters,
                timeout=self.timeout
            )
            
            # Check HTTP status
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            
            # Validate response structure
            if not isinstance(data, dict):
                raise ValueError(f"Unexpected response type: {type(data)}")
            
            if 'value' not in data:
                raise ValueError("Response missing 'value' key")
            
            records = data['value']
            
            if not isinstance(records, list):
                raise ValueError(f"'value' field is not a list: {type(records)}")
            
            logger.info(f"Successfully extracted {len(records)} records for {indicator_code}")
            
            return records
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout extracting {indicator_code} after {self.timeout}s")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error extracting {indicator_code}: {e}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error extracting {indicator_code}: {e}")
            raise
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response structure for {indicator_code}: {e}")
            raise
    
    def extract_multiple_indicators(
        self,
        indicator_names: List[str],
        indicators_map: Optional[Dict[str, Dict[str, str]]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract data for multiple indicators with progress tracking.
        
        Args:
            indicator_names: List of internal indicator names
            indicators_map: Optional custom indicator mapping
            
        Returns:
            Dictionary mapping indicator names to their extracted records
        """
        if indicators_map is None:
            indicators_map = WHO_INDICATORS
        
        results = {}
        total = len(indicator_names)
        
        for idx, name in enumerate(indicator_names, 1):
            if name not in indicators_map:
                logger.warning(f"Unknown indicator: {name}, skipping")
                continue
            
            code = indicators_map[name]['code']
            logger.info(f"[{idx}/{total}] Processing {name} ({code})")
            
            try:
                records = self.extract_indicator(code)
                results[name] = records
                
                # Rate limiting: pause between requests
                if idx < total:
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Failed to extract {name}: {e}")
                results[name] = []  # Store empty list for failed extractions
        
        return results
    
    def get_indicator_metadata(self, indicator_code: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve metadata for a specific indicator.
        
        Args:
            indicator_code: WHO GHO indicator code
            
        Returns:
            Indicator metadata dictionary or None if not found
        """
        url = f"{self.base_url}/{indicator_code}"
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            # Metadata is typically in the response headers or first record
            if 'value' in data and data['value']:
                first_record = data['value'][0]
                # Extract metadata fields
                metadata = {
                    'indicator_code': indicator_code,
                    'sample_fields': list(first_record.keys()),
                    'record_count': len(data['value'])
                }
                return metadata
                
        except Exception as e:
            logger.error(f"Failed to get metadata for {indicator_code}: {e}")
        
        return None
    
    def test_connection(self) -> bool:
        """
        Test API connectivity with a lightweight request.
        
        Returns:
            True if connection successful, False otherwise
        """
        test_indicators = ["WHOSIS_000001", "NCDMORT3070", "UHC_INDEX_REPORTED"]
        
        for code in test_indicators:
            try:
                url = f"{self.base_url}/{code}"
                response = self.session.head(url, timeout=5)
                if response.status_code < 400:
                    logger.info(f"API connection test successful (tested {code})")
                    return True
            except Exception as e:
                logger.debug(f"Test failed for {code}: {e}")
                continue
        
        logger.warning("API connection test failed for all test indicators")
        return False
    
    def close(self):
        """Close the HTTP session."""
        self.session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
