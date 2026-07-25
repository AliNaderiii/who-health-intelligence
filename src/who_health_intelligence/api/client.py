"""
WHO Global Health Observatory (GHO) API Client.

Provides robust extraction of health indicators from the WHO GHO OData API
with comprehensive error handling, retry logic, pagination, and response
validation.

API Documentation: https://www.who.int/data/gho/info/gho-odata-api
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.config import (
    WHO_API_BASE_URL,
    API_TIMEOUT_SECONDS,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_BASE,
    WHO_INDICATORS,
    setup_logging,
)

logger = setup_logging(__name__)

# WHO GHO OData API response schema requirements
REQUIRED_TOP_LEVEL_KEYS: Set[str] = {"value"}
REQUIRED_RECORD_KEYS: Set[str] = {"SpatialDim", "TimeDim", "NumericValue"}

# Default pagination size for OData $top parameter
DEFAULT_PAGE_SIZE: int = 1000
# Maximum pages to fetch per indicator (safety limit)
MAX_PAGES_PER_INDICATOR: int = 100


class WHOAPIClient:
    """
    Client for interacting with the WHO GHO OData API.

    Implements:
    - Robust HTTP session management with automatic retries
    - Exponential backoff for transient failures
    - Timeout handling
    - OData pagination ($skip / $top)
    - JSON schema validation
    - Raw response persistence

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
        max_retries: int = API_MAX_RETRIES,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = self._create_session()

    # ------------------------------------------------------------------
    # Session setup
    # ------------------------------------------------------------------

    def _create_session(self) -> requests.Session:
        """
        Create an HTTP session with automatic retry configuration.

        Implements exponential backoff for transient failures (5xx, timeouts,
        connection errors).
        """
        session = requests.Session()

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=API_RETRY_BACKOFF_BASE,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        session.headers.update(
            {
                "User-Agent": "WHO-Health-Intelligence-Platform/3.0",
                "Accept": "application/json",
            }
        )

        return session

    # ------------------------------------------------------------------
    # Indicator code validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_indicator_code(indicator_code: str) -> bool:
        """
        Validate that an indicator code is non-empty and looks well-formed.

        WHO GHO indicator codes are alphanumeric, typically 8-20 characters.
        This performs a structural check, not an existence check.

        Args:
            indicator_code: The code to validate.

        Returns:
            True if the code passes structural validation.

        Raises:
            ValueError: If the code is empty or contains invalid characters.
        """
        if not indicator_code or not isinstance(indicator_code, str):
            raise ValueError(f"Indicator code must be a non-empty string, got: {indicator_code!r}")

        stripped = indicator_code.strip()
        if len(stripped) < 3:
            raise ValueError(f"Indicator code too short: {stripped!r}")

        # Allow alphanumeric + underscore
        if not all(c.isalnum() or c == "_" for c in stripped):
            raise ValueError(
                f"Indicator code contains invalid characters: {stripped!r}"
            )

        return True

    # ------------------------------------------------------------------
    # Core extraction (single page)
    # ------------------------------------------------------------------

    def _fetch_page(
        self,
        indicator_code: str,
        skip: int = 0,
        top: int = DEFAULT_PAGE_SIZE,
    ) -> Dict[str, Any]:
        """
        Fetch a single page of OData results.

        Args:
            indicator_code: WHO GHO indicator code.
            skip: Number of records to skip (OData $skip).
            top: Maximum records per page (OData $top).

        Returns:
            Parsed JSON response dict.

        Raises:
            requests.exceptions.RequestException: On network/HTTP errors.
            ValueError: On invalid response structure.
        """
        url = f"{self.base_url}/{indicator_code}"
        params: Dict[str, Any] = {"$skip": skip, "$top": top}

        logger.debug("GET %s params=%s", url, params)

        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()

        data = response.json()

        # --- JSON schema checks ---
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict response, got {type(data).__name__}")

        if REQUIRED_TOP_LEVEL_KEYS - data.keys():
            raise ValueError(
                f"Response missing required keys: {REQUIRED_TOP_LEVEL_KEYS - data.keys()}"
            )

        records = data["value"]
        if not isinstance(records, list):
            raise ValueError(f"'value' field is not a list, got {type(records).__name__}")

        # Spot-check first record for required keys
        if records:
            first = records[0]
            if not isinstance(first, dict):
                raise ValueError(f"Record is not a dict: {type(first).__name__}")
            missing = REQUIRED_RECORD_KEYS - first.keys()
            if missing:
                logger.warning(
                    "First record for %s missing expected keys: %s",
                    indicator_code,
                    missing,
                )

        return data

    # ------------------------------------------------------------------
    # Paginated extraction
    # ------------------------------------------------------------------

    def extract_indicator(
        self,
        indicator_code: str,
        filters: Optional[Dict[str, str]] = None,
        raw_output_dir: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract ALL data for a specific WHO indicator, handling pagination.

        The WHO GHO OData API may return thousands of records. This method
        pages through the full result set using $skip / $top.

        Args:
            indicator_code: WHO GHO indicator code (e.g., 'WHOSIS_000001').
            filters: Optional OData filter dict (currently informational).
            raw_output_dir: If provided, save raw JSON response to this dir.

        Returns:
            Complete list of JSON records for the indicator.

        Raises:
            ValueError: If indicator_code is invalid.
            requests.exceptions.RequestException: On network failure.
        """
        self.validate_indicator_code(indicator_code)

        logger.info("Extracting indicator: %s", indicator_code)

        all_records: List[Dict[str, Any]] = []
        page = 0
        skip = 0

        while page < MAX_PAGES_PER_INDICATOR:
            try:
                data = self._fetch_page(indicator_code, skip=skip, top=DEFAULT_PAGE_SIZE)
            except requests.exceptions.RequestException:
                # On first page, propagate. On subsequent pages, return what we have.
                if page == 0:
                    raise
                logger.warning(
                    "Pagination failed at page %d for %s; returning %d records collected so far",
                    page,
                    indicator_code,
                    len(all_records),
                )
                break
            except ValueError:
                if page == 0:
                    raise
                logger.warning(
                    "Schema validation failed at page %d for %s; returning %d records",
                    page,
                    indicator_code,
                    len(all_records),
                )
                break

            records = data["value"]
            all_records.extend(records)
            page += 1

            logger.debug(
                "Page %d: fetched %d records (total: %d)",
                page,
                len(records),
                len(all_records),
            )

            # Stop if this page returned fewer than page size (last page)
            if len(records) < DEFAULT_PAGE_SIZE:
                break

            skip += DEFAULT_PAGE_SIZE

        logger.info(
            "Extracted %d total records for %s across %d page(s)",
            len(all_records),
            indicator_code,
            page,
        )

        # Save raw response
        if raw_output_dir is not None:
            self._save_raw_response(indicator_code, all_records, raw_output_dir)

        return all_records

    # ------------------------------------------------------------------
    # Raw data persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _save_raw_response(
        indicator_code: str,
        records: List[Dict[str, Any]],
        output_dir: Path,
    ) -> Path:
        """
        Save raw API records to a JSON file under ``output_dir``.

        Args:
            indicator_code: Indicator code (used in filename).
            records: List of JSON records.
            output_dir: Directory to save the file.

        Returns:
            Path to the saved file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{indicator_code}_{timestamp}.json"
        filepath = output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "indicator_code": indicator_code,
                    "extracted_at": timestamp,
                    "record_count": len(records),
                    "value": records,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        logger.info("Saved raw response: %s (%d records)", filepath, len(records))
        return filepath

    # ------------------------------------------------------------------
    # Multi-indicator extraction
    # ------------------------------------------------------------------

    def extract_multiple_indicators(
        self,
        indicator_names: List[str],
        indicators_map: Optional[Dict[str, Dict[str, str]]] = None,
        raw_output_dir: Optional[Path] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract data for multiple indicators with progress tracking.

        Args:
            indicator_names: List of internal indicator names.
            indicators_map: Optional custom indicator mapping.
            raw_output_dir: If provided, save raw responses for each indicator.

        Returns:
            Dict mapping indicator names to their extracted records.
        """
        if indicators_map is None:
            indicators_map = WHO_INDICATORS

        results: Dict[str, List[Dict[str, Any]]] = {}
        total = len(indicator_names)

        for idx, name in enumerate(indicator_names, 1):
            if name not in indicators_map:
                logger.warning("Unknown indicator: %s, skipping", name)
                continue

            code = indicators_map[name]["code"]
            logger.info("[%d/%d] Processing %s (%s)", idx, total, name, code)

            try:
                records = self.extract_indicator(code, raw_output_dir=raw_output_dir)
                results[name] = records

                # Rate limiting between requests
                if idx < total:
                    time.sleep(1)

            except Exception as e:
                logger.error("Failed to extract %s: %s", name, e)
                results[name] = []

        return results

    # ------------------------------------------------------------------
    # Metadata / health
    # ------------------------------------------------------------------

    def get_indicator_metadata(self, indicator_code: str) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for a specific indicator."""
        url = f"{self.base_url}/{indicator_code}"

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            if "value" in data and data["value"]:
                first_record = data["value"][0]
                return {
                    "indicator_code": indicator_code,
                    "sample_fields": list(first_record.keys()),
                    "record_count": len(data["value"]),
                }
        except Exception as e:
            logger.error("Failed to get metadata for %s: %s", indicator_code, e)

        return None

    def test_connection(self) -> bool:
        """
        Test API connectivity with a lightweight HEAD request.

        Returns:
            True if at least one indicator endpoint responds.
        """
        for code in ["WHOSIS_000001", "NCDMORT3070", "UHC_INDEX_REPORTED"]:
            try:
                url = f"{self.base_url}/{code}"
                response = self.session.head(url, timeout=5)
                if response.status_code < 400:
                    logger.info("API connection test successful (tested %s)", code)
                    return True
            except Exception as e:
                logger.debug("Test failed for %s: %s", code, e)
                continue

        logger.warning("API connection test failed for all test indicators")
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the HTTP session."""
        self.session.close()

    def __enter__(self) -> "WHOAPIClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
