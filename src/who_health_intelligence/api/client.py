"""
WHO Global Health Observatory (GHO) API Client - Production version.

Implements explicit LIVE data mode requirements:

- Validate API base URL
- Validate each indicator endpoint
- Use requests.Session with retry + exponential backoff
- Configurable timeout/retries via env vars
- Handle HTTP 4xx/5xx, connection errors, malformed JSON, missing keys
- Support OData pagination ($skip/$top and @odata.nextLink)
- Log every extraction attempt, response status, record count, duration, latency
- Avoid excessive API calls via rate limiting and caching avoidance

API Documentation: https://www.who.int/data/gho/info/gho-odata-api
Current base URL (as of 2026): https://ghoapi.azureedge.net/api/
This module validates that the base URL is syntactically correct and
attempts to verify reachability. Actual network availability may vary.

Indicator codes verified:
- WHOSIS_000001 - Life expectancy at birth (years)
- NCDMORT3070  - Probability of premature death from major NCDs (SDG 3.4.1)
- UHC_INDEX_REPORTED - UHC service coverage index (SDG 3.8.1)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
    validate_api_base_url,
)

logger = setup_logging(__name__)

# WHO GHO OData response schema requirements
REQUIRED_TOP_LEVEL_KEYS: Set[str] = {"value"}
REQUIRED_RECORD_KEYS: Set[str] = {"SpatialDim", "TimeDim", "NumericValue"}

DEFAULT_PAGE_SIZE: int = 1000
MAX_PAGES_PER_INDICATOR: int = 100
RATE_LIMIT_SECONDS: float = 1.0  # avoid excessive calls


class WHOAPIError(Exception):
    """Base exception for WHO API client errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, indicator: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.indicator = indicator


class WHOAPISchemaError(WHOAPIError):
    """Raised when response JSON is malformed or missing required keys."""


class WHOAPIClient:
    """
    Production-grade client for WHO GHO OData API.

    Features:
    - Session with retry + exponential backoff
    - Configurable timeout
    - Base URL validation
    - Per-indicator validation
    - Pagination via $skip/$top and @odata.nextLink
    - Detailed logging of every attempt, status, records, duration, latency
    - Safe handling of 4xx/5xx, timeouts, malformed JSON
    """

    def __init__(
        self,
        base_url: str = WHO_API_BASE_URL,
        timeout: int = API_TIMEOUT_SECONDS,
        max_retries: int = API_MAX_RETRIES,
        backoff_base: int = API_RETRY_BACKOFF_BASE,
    ):
        # Validate base URL
        try:
            validate_api_base_url(base_url)
        except ValueError as e:
            logger.error(f"Invalid API base URL {base_url!r}: {e}")
            raise

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.session = self._create_session()
        logger.info(
            f"WHOAPIClient initialized: base_url={self.base_url}, timeout={self.timeout}s, "
            f"max_retries={self.max_retries}, backoff={self.backoff_base}"
        )

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.backoff_base,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": f"WHO-Health-Intelligence-Platform/{self._get_version()} "
                "(LIVE mode; contact: gho_info@who.int dashboard)",
                "Accept": "application/json",
            }
        )
        return session

    @staticmethod
    def _get_version() -> str:
        try:
            from ..utils.config import PIPELINE_VERSION

            return PIPELINE_VERSION
        except Exception:
            return "4.0.0"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def validate_indicator_code(indicator_code: str) -> bool:
        if not indicator_code or not isinstance(indicator_code, str):
            raise ValueError(f"Indicator code must be non-empty string, got: {indicator_code!r}")
        stripped = indicator_code.strip()
        if len(stripped) < 3:
            raise ValueError(f"Indicator code too short: {stripped!r}")
        if not all(c.isalnum() or c == "_" for c in stripped):
            raise ValueError(f"Indicator code contains invalid characters: {stripped!r}")
        return True

    def validate_base_url_reachable(self) -> Tuple[bool, str]:
        """
        Lightweight check if base URL is reachable.
        Returns (reachable, message).
        """
        try:
            url = f"{self.base_url}/Indicator"
            start = time.monotonic()
            resp = self.session.get(url, params={"$top": 1}, timeout=10)
            latency = time.monotonic() - start
            if resp.status_code < 400:
                logger.info(f"API base URL reachable: {self.base_url} ({resp.status_code}) latency={latency:.2f}s")
                return True, f"OK {resp.status_code} latency={latency:.2f}s"
            else:
                msg = f"Base URL returned status {resp.status_code}"
                logger.warning(msg)
                return False, msg
        except requests.exceptions.Timeout:
            msg = f"Timeout checking base URL {self.base_url}"
            logger.warning(msg)
            return False, msg
        except requests.exceptions.ConnectionError as e:
            msg = f"Connection error for base URL {self.base_url}: {e}"
            logger.warning(msg)
            return False, msg
        except Exception as e:
            msg = f"Failed to validate base URL {self.base_url}: {e}"
            logger.warning(msg)
            return False, msg

    def validate_indicator_endpoint(self, indicator_code: str) -> Tuple[bool, str, Optional[int]]:
        """
        Validate that a specific indicator endpoint exists and returns expected structure.
        Returns (is_valid, message, sample_record_count)
        """
        try:
            self.validate_indicator_code(indicator_code)
        except ValueError as e:
            return False, str(e), None

        url = f"{self.base_url}/{indicator_code}"
        try:
            start = time.monotonic()
            resp = self.session.get(url, params={"$top": 2}, timeout=self.timeout)
            latency = time.monotonic() - start
            logger.info(
                f"Validating indicator {indicator_code}: GET {url} -> {resp.status_code} "
                f"latency={latency:.2f}s duration logged"
            )

            if resp.status_code == 404:
                return False, f"Indicator {indicator_code} not found (404)", None
            if resp.status_code >= 400:
                return False, f"Indicator {indicator_code} endpoint returned {resp.status_code}", None

            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                return False, f"Malformed JSON for {indicator_code}: {e}", None

            if not isinstance(data, dict):
                return False, f"Expected dict response for {indicator_code}, got {type(data).__name__}", None
            if "value" not in data:
                return False, f"Missing 'value' key for {indicator_code}, keys={list(data.keys())}", None
            if not isinstance(data["value"], list):
                return False, f"'value' not a list for {indicator_code}", None

            count = len(data["value"])
            if count == 0:
                logger.warning(f"Indicator {indicator_code} returned 0 records (may be valid if filtered)")
                return True, f"Endpoint valid but 0 sample records latency={latency:.2f}s", 0

            # Check first record structure
            first = data["value"][0]
            missing = REQUIRED_RECORD_KEYS - set(first.keys()) if isinstance(first, dict) else REQUIRED_RECORD_KEYS
            if missing:
                logger.warning(f"Indicator {indicator_code} first record missing keys: {missing}")

            return True, f"OK latency={latency:.2f}s sample_records={count}", count

        except requests.exceptions.Timeout:
            return False, f"Timeout validating {indicator_code}", None
        except requests.exceptions.ConnectionError as e:
            return False, f"Connection error validating {indicator_code}: {e}", None
        except Exception as e:
            return False, f"Validation failed for {indicator_code}: {e}", None

    # ------------------------------------------------------------------
    # Core page fetch with detailed logging
    # ------------------------------------------------------------------
    def _fetch_page(
        self,
        indicator_code: str,
        skip: int = 0,
        top: int = DEFAULT_PAGE_SIZE,
    ) -> Tuple[Dict[str, Any], float, int]:
        """
        Fetch a single page with latency tracking.
        Returns (json_data, latency_seconds, status_code)
        Raises WHOAPIError on failures.
        """
        url = f"{self.base_url}/{indicator_code}"
        params: Dict[str, Any] = {"$skip": skip, "$top": top}

        logger.info(f"EXTRACTION ATTEMPT: indicator={indicator_code} url={url} params={params} timeout={self.timeout}s")
        start = time.monotonic()
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            duration = time.monotonic() - start
            logger.error(
                f"API TIMEOUT: indicator={indicator_code} url={url} timeout={self.timeout}s duration={duration:.2f}s error={e}"
            )
            raise WHOAPIError(f"Timeout after {self.timeout}s for {indicator_code}", indicator=indicator_code) from e
        except requests.exceptions.ConnectionError as e:
            duration = time.monotonic() - start
            logger.error(
                f"API CONNECTION ERROR: indicator={indicator_code} url={url} duration={duration:.2f}s error={e}"
            )
            raise WHOAPIError(f"Connection error for {indicator_code}: {e}", indicator=indicator_code) from e
        except Exception as e:
            duration = time.monotonic() - start
            logger.error(f"API UNEXPECTED ERROR: indicator={indicator_code} error={e} duration={duration:.2f}s")
            raise WHOAPIError(f"Unexpected error for {indicator_code}: {e}", indicator=indicator_code) from e

        latency = time.monotonic() - start
        status = response.status_code
        logger.info(
            f"API RESPONSE: indicator={indicator_code} status={status} latency={latency:.2f}s "
            f"bytes={len(response.content)} url={response.url}"
        )

        # Handle HTTP 4xx and 5xx
        if status >= 400:
            # Log detailed failure
            body_preview = response.text[:500]
            logger.error(
                f"API HTTP ERROR: indicator={indicator_code} status={status} body_preview={body_preview} latency={latency:.2f}s"
            )
            if 400 <= status < 500:
                raise WHOAPIError(
                    f"HTTP {status} client error for {indicator_code}: {body_preview}",
                    status_code=status,
                    indicator=indicator_code,
                )
            else:
                raise WHOAPIError(
                    f"HTTP {status} server error for {indicator_code}: {body_preview}",
                    status_code=status,
                    indicator=indicator_code,
                )

        # Parse JSON with malformed handling
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"API MALFORMED JSON: indicator={indicator_code} status={status} error={e} body={response.text[:500]}")
            raise WHOAPISchemaError(f"Malformed JSON for {indicator_code}: {e}", status_code=status, indicator=indicator_code) from e

        # Validate response structure
        if not isinstance(data, dict):
            msg = f"Expected dict response, got {type(data).__name__} for {indicator_code}"
            logger.error(msg)
            raise WHOAPISchemaError(msg, status_code=status, indicator=indicator_code)

        if REQUIRED_TOP_LEVEL_KEYS - data.keys():
            missing = REQUIRED_TOP_LEVEL_KEYS - data.keys()
            msg = f"Response missing required keys {missing} for {indicator_code}, has {list(data.keys())}"
            logger.error(msg)
            raise WHOAPISchemaError(msg, status_code=status, indicator=indicator_code)

        records = data["value"]
        if not isinstance(records, list):
            msg = f"'value' field is not a list for {indicator_code}, got {type(records).__name__}"
            logger.error(msg)
            raise WHOAPISchemaError(msg, status_code=status, indicator=indicator_code)

        if records:
            first = records[0]
            if not isinstance(first, dict):
                msg = f"Record is not a dict for {indicator_code}: {type(first).__name__}"
                logger.error(msg)
                raise WHOAPISchemaError(msg, status_code=status, indicator=indicator_code)
            missing = REQUIRED_RECORD_KEYS - first.keys()
            if missing:
                logger.warning(f"First record for {indicator_code} missing expected keys: {missing}")

        logger.info(
            f"EXTRACTION SUCCESS: indicator={indicator_code} page_records={len(records)} "
            f"status={status} latency={latency:.2f}s skip={skip} top={top}"
        )

        return data, latency, status

    def _fetch_page_with_nextlink(
        self,
        url: str,
    ) -> Tuple[Dict[str, Any], float, int, Optional[str]]:
        """
        Fetch using explicit nextLink URL (for OData @odata.nextLink support).
        Returns (data, latency, status, next_link)
        """
        logger.info(f"EXTRACTION ATTEMPT (nextLink): url={url}")
        start = time.monotonic()
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            duration = time.monotonic() - start
            logger.error(f"API TIMEOUT nextLink: url={url} duration={duration:.2f}s")
            raise WHOAPIError(f"Timeout fetching nextLink {url}") from e
        except Exception as e:
            duration = time.monotonic() - start
            logger.error(f"API ERROR nextLink: url={url} error={e} duration={duration:.2f}s")
            raise WHOAPIError(f"Error fetching nextLink {url}: {e}") from e

        latency = time.monotonic() - start
        status = response.status_code
        logger.info(f"API RESPONSE nextLink: status={status} latency={latency:.2f}s url={url}")

        if status >= 400:
            raise WHOAPIError(f"HTTP {status} for nextLink {url}", status_code=status)

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise WHOAPISchemaError(f"Malformed JSON for nextLink {url}: {e}") from e

        if not isinstance(data, dict) or "value" not in data:
            raise WHOAPISchemaError(f"Invalid response structure for nextLink {url}")

        next_link = data.get("@odata.nextLink") or data.get("odata.nextLink")
        return data, latency, status, next_link

    # ------------------------------------------------------------------
    # Public extraction with metadata
    # ------------------------------------------------------------------
    def extract_indicator_with_metadata(
        self,
        indicator_code: str,
        raw_output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Extract indicator with full metadata tracking as required for data-quality report.

        Returns dict:
        {
            records: List[dict],
            status: success|failed,
            error: Optional[str],
            record_count: int,
            raw_record_count: int,
            api_status_code: int,
            api_latency_seconds: float,
            extraction_duration_seconds: float,
            pages_fetched: int,
            api_calls: int,
            extraction_timestamp_utc: str,
        }
        """
        self.validate_indicator_code(indicator_code)
        extraction_start = time.monotonic()
        timestamp_utc = datetime.now(timezone.utc).isoformat()
        logger.info(f"START EXTRACTION: indicator={indicator_code} timestamp={timestamp_utc}")

        all_records: List[Dict[str, Any]] = []
        total_latency = 0.0
        pages = 0
        api_calls = 0
        last_status = None
        error_msg = None

        try:
            # First page using standard $skip/$top
            skip = 0
            while pages < MAX_PAGES_PER_INDICATOR:
                try:
                    data, latency, status = self._fetch_page(indicator_code, skip=skip, top=DEFAULT_PAGE_SIZE)
                    total_latency += latency
                    api_calls += 1
                    last_status = status
                    pages += 1

                    records = data["value"]
                    all_records.extend(records)

                    # Check for OData nextLink (some WHO endpoints use this)
                    next_link = data.get("@odata.nextLink") or data.get("odata.nextLink")
                    if next_link:
                        logger.info(f"PAGINATION: indicator={indicator_code} nextLink found, switching to nextLink pagination")
                        # Follow nextLink chain
                        current_link = next_link
                        while current_link and pages < MAX_PAGES_PER_INDICATOR:
                            d, lat, st, nxt = self._fetch_page_with_nextlink(current_link)
                            total_latency += lat
                            api_calls += 1
                            last_status = st
                            pages += 1
                            all_records.extend(d.get("value", []))
                            current_link = nxt
                            if len(d.get("value", [])) < DEFAULT_PAGE_SIZE and not nxt:
                                break
                        break

                    logger.info(
                        f"PAGINATION PROGRESS: indicator={indicator_code} page={pages} "
                        f"page_records={len(records)} total_records={len(all_records)}"
                    )

                    if len(records) < DEFAULT_PAGE_SIZE:
                        # Last page
                        break
                    skip += DEFAULT_PAGE_SIZE

                except WHOAPIError as e:
                    error_msg = str(e)
                    last_status = e.status_code
                    if pages == 0:
                        # First page failed -> propagate failure
                        raise
                    else:
                        logger.warning(
                            f"PAGINATION FAILED at page {pages+1} for {indicator_code}: {e}; "
                            f"returning {len(all_records)} records collected so far"
                        )
                        break

            duration = time.monotonic() - extraction_start
            logger.info(
                f"EXTRACTION COMPLETE: indicator={indicator_code} total_records={len(all_records)} "
                f"pages={pages} api_calls={api_calls} total_latency={total_latency:.2f}s duration={duration:.2f}s status={last_status}"
            )

            if raw_output_dir is not None:
                self._save_raw_response(indicator_code, all_records, raw_output_dir)

            return {
                "records": all_records,
                "status": "success",
                "error": None,
                "record_count": len(all_records),
                "raw_record_count": len(all_records),
                "api_status_code": last_status,
                "api_latency_seconds": round(total_latency, 3),
                "extraction_duration_seconds": round(duration, 3),
                "pages_fetched": pages,
                "api_calls": api_calls,
                "extraction_timestamp_utc": timestamp_utc,
            }

        except Exception as e:
            duration = time.monotonic() - extraction_start
            logger.error(
                f"EXTRACTION FAILED: indicator={indicator_code} duration={duration:.2f}s "
                f"api_calls={api_calls} error={e} latency={total_latency:.2f}s"
            )
            return {
                "records": [],
                "status": "failed",
                "error": str(e),
                "record_count": 0,
                "raw_record_count": 0,
                "api_status_code": getattr(e, "status_code", None),
                "api_latency_seconds": round(total_latency, 3),
                "extraction_duration_seconds": round(duration, 3),
                "pages_fetched": pages,
                "api_calls": api_calls,
                "extraction_timestamp_utc": timestamp_utc,
            }

    def extract_indicator(
        self,
        indicator_code: str,
        filters: Optional[Dict[str, str]] = None,
        raw_output_dir: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """
        Backward compatible method returning just records.
        Uses extract_indicator_with_metadata internally.
        """
        result = self.extract_indicator_with_metadata(indicator_code, raw_output_dir=raw_output_dir)
        if result["status"] != "success":
            # Raise if first page failed to preserve previous behavior for pipeline error handling
            if result["record_count"] == 0 and result["error"]:
                raise WHOAPIError(result["error"], status_code=result.get("api_status_code"), indicator=indicator_code)
        return result["records"]

    # ------------------------------------------------------------------
    # Raw persistence
    # ------------------------------------------------------------------
    @staticmethod
    def _save_raw_response(
        indicator_code: str,
        records: List[Dict[str, Any]],
        output_dir: Path,
    ) -> Path:
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
        logger.info(f"Saved raw response: {filepath} ({len(records)} records)")
        return filepath

    # ------------------------------------------------------------------
    # Multi-indicator with tracking
    # ------------------------------------------------------------------
    def extract_multiple_indicators(
        self,
        indicator_names: List[str],
        indicators_map: Optional[Dict[str, Dict[str, str]]] = None,
        raw_output_dir: Optional[Path] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        if indicators_map is None:
            indicators_map = WHO_INDICATORS
        results: Dict[str, List[Dict[str, Any]]] = {}
        total = len(indicator_names)
        for idx, name in enumerate(indicator_names, 1):
            if name not in indicators_map:
                logger.warning(f"Unknown indicator: {name}, skipping")
                continue
            code = indicators_map[name]["code"]
            logger.info(f"[{idx}/{total}] Processing {name} ({code})")
            try:
                records = self.extract_indicator(code, raw_output_dir=raw_output_dir)
                results[name] = records
                if idx < total:
                    logger.info(f"Rate limiting: sleeping {RATE_LIMIT_SECONDS}s to avoid excessive API calls")
                    time.sleep(RATE_LIMIT_SECONDS)
            except Exception as e:
                logger.error(f"Failed to extract {name}: {e}")
                results[name] = []
        return results

    def extract_multiple_with_metadata(
        self,
        indicator_names: List[str],
        indicators_map: Optional[Dict[str, Dict[str, str]]] = None,
        raw_output_dir: Optional[Path] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract multiple indicators with full metadata for data-quality report.
        Returns dict mapping indicator_name -> metadata dict from extract_indicator_with_metadata
        """
        if indicators_map is None:
            indicators_map = WHO_INDICATORS
        results: Dict[str, Dict[str, Any]] = {}
        total = len(indicator_names)
        for idx, name in enumerate(indicator_names, 1):
            if name not in indicators_map:
                logger.warning(f"Unknown indicator: {name}, skipping")
                results[name] = {
                    "records": [],
                    "status": "failed",
                    "error": f"Unknown indicator {name}",
                    "record_count": 0,
                    "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
                continue
            code = indicators_map[name]["code"]
            logger.info(f"[{idx}/{total}] Processing {name} ({code}) with metadata tracking")
            meta = self.extract_indicator_with_metadata(code, raw_output_dir=raw_output_dir)
            results[name] = meta
            if idx < total:
                time.sleep(RATE_LIMIT_SECONDS)
        return results

    # ------------------------------------------------------------------
    # Health / metadata
    # ------------------------------------------------------------------
    def get_indicator_metadata(self, indicator_code: str) -> Optional[Dict[str, Any]]:
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
            logger.error(f"Failed to get metadata for {indicator_code}: {e}")
        return None

    def test_connection(self) -> bool:
        for code in ["WHOSIS_000001", "NCDMORT3070", "UHC_INDEX_REPORTED"]:
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "WHOAPIClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
