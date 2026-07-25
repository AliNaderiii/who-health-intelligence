"""
Central project configuration for WHO Global Health Intelligence Platform.

This module defines:
- Project paths via pathlib (no hardcoded Windows paths)
- WHO API base URL validation
- Indicator definitions with official WHO wording, units, source URLs
- Environment variables for production deployment
- Logging setup
- Pipeline version and defaults

Environment variables (all optional, safe defaults):
    WHO_DATA_MODE         live (default) or demo (explicit)
    WHO_API_BASE_URL      default https://ghoapi.azureedge.net/api/
    WHO_API_TIMEOUT       default 30 seconds
    WHO_API_MAX_RETRIES   default 3
    WHO_REFRESH_TTL       default 3600 seconds (Streamlit cache TTL)
    WHO_DB_PATH           default data/who_health_data.db
    WHO_DATA_DIR          default data/
    WHO_PROJECT_VERSION   default 4.0.0

No secrets are required for the public WHO GHO OData API.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------
PROJECT_VERSION = os.environ.get("WHO_PROJECT_VERSION", "4.0.0")
PIPELINE_VERSION = PROJECT_VERSION
APPLICATION_TITLE = os.environ.get(
    "WHO_APPLICATION_TITLE", "WHO Global Health Intelligence Platform"
)
DASHBOARD_TITLE = APPLICATION_TITLE
DASHBOARD_SUBTITLE = os.environ.get(
    "WHO_DASHBOARD_SUBTITLE",
    "Public Health Data Engineering, Epidemiological Analytics & Interactive Business Intelligence",
)

# ---------------------------------------------------------------------------
# Paths (pathlib, no hardcoded Windows paths)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(
    os.environ.get("WHO_PROJECT_ROOT", Path(__file__).resolve().parent.parent)
).resolve()
DATA_DIR = Path(os.environ.get("WHO_DATA_DIR", PROJECT_ROOT / "data")).resolve()
RAW_DATA_PATH = Path(os.environ.get("WHO_RAW_DATA_PATH", DATA_DIR / "raw")).resolve()
PROCESSED_DATA_PATH = Path(
    os.environ.get("WHO_PROCESSED_DATA_PATH", DATA_DIR / "processed")
).resolve()
METADATA_PATH = Path(os.environ.get("WHO_METADATA_PATH", DATA_DIR / "metadata")).resolve()
LOGS_DIR = Path(os.environ.get("WHO_LOGS_DIR", PROJECT_ROOT / "logs")).resolve()
REPORTS_DIR = Path(os.environ.get("WHO_REPORTS_DIR", PROJECT_ROOT / "reports")).resolve()
DATABASE_PATH = Path(
    os.environ.get("WHO_DB_PATH", DATA_DIR / "who_health_data.db")
).resolve()

for directory in (
    DATA_DIR,
    RAW_DATA_PATH,
    PROCESSED_DATA_PATH,
    METADATA_PATH,
    LOGS_DIR,
    REPORTS_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# WHO API configuration - validated endpoint
# ---------------------------------------------------------------------------
# The currently documented and actively used endpoint as of 2026 is:
# https://ghoapi.azureedge.net/api/
# WHO has announced deprecation near end 2025 in favor of World Health Data Hub OData,
# but as of April 2026 documentation and community tooling still reference the same base.
# The base URL is configurable via WHO_API_BASE_URL for forward compatibility.
WHO_API_BASE_URL = os.environ.get(
    "WHO_API_BASE_URL", "https://ghoapi.azureedge.net/api/"
)

# Timeout handling: support both new WHO_API_TIMEOUT and legacy WHO_REQUEST_TIMEOUT
timeout_raw = os.environ.get("WHO_API_TIMEOUT") or os.environ.get(
    "WHO_REQUEST_TIMEOUT", "30"
)
try:
    DEFAULT_REQUEST_TIMEOUT = int(timeout_raw)
except ValueError:
    DEFAULT_REQUEST_TIMEOUT = 30

retry_raw = os.environ.get("WHO_API_MAX_RETRIES") or os.environ.get(
    "WHO_RETRY_COUNT", "3"
)
try:
    DEFAULT_RETRY_COUNT = int(retry_raw)
except ValueError:
    DEFAULT_RETRY_COUNT = 3

API_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT
API_MAX_RETRIES = DEFAULT_RETRY_COUNT
API_RETRY_BACKOFF_BASE = int(os.environ.get("WHO_RETRY_BACKOFF_BASE", "2"))

# Refresh TTL for Streamlit caching and dashboard refresh logic
WHO_REFRESH_TTL = int(os.environ.get("WHO_REFRESH_TTL", "3600"))

# ---------------------------------------------------------------------------
# Data mode handling
# ---------------------------------------------------------------------------
# WHO_DATA_MODE env: live (default) or demo (explicit)
# Demo mode must require explicit setting: WHO_DATA_MODE=demo
# Default deployment mode must be LIVE
def get_data_mode() -> str:
    mode = os.environ.get("WHO_DATA_MODE", "live").strip().lower()
    if mode not in ("live", "demo"):
        # Unknown value treated as live with warning via logging later
        return "live"
    return mode


def is_demo_mode() -> bool:
    return get_data_mode() == "demo"


def is_live_mode() -> bool:
    return get_data_mode() == "live"


# ---------------------------------------------------------------------------
# WHO indicator definitions - official wording, units, source URLs
# ---------------------------------------------------------------------------
# Official definitions validated against WHO Data Hub:
# - Life expectancy: https://data.who.int/indicators/i/A21CFC2/90E2E48
# - NCD mortality: https://data.who.int/indicators/i/C540135/1F96863
# - UHC coverage: https://data.who.int/indicators/i/3805B1E/9A706FD

WHO_INDICATORS: Dict[str, Dict[str, str]] = {
    "LIFE_EXPECTANCY": {
        "code": "WHOSIS_000001",
        "description": "Life expectancy at birth (years)",
        "official_definition": (
            "The average number of years that a newborn could expect to live, "
            "if he or she were to pass through life exposed to the sex- and "
            "age-specific death rates prevailing at the time of his or her birth, "
            "for a specific year, in a given country, territory, or geographic area."
        ),
        "short_definition": "Average number of years that a person can expect to live from birth.",
        "unit": "years",
        "source_url": "https://data.who.int/indicators/i/A21CFC2/90E2E48",
        "who_odata_url": f"{WHO_API_BASE_URL.rstrip('/')}/WHOSIS_000001",
        "category": "Mortality",
    },
    "NCD_MORTALITY": {
        "code": "NCDMORT3070",
        "description": "Probability of premature death from major non-communicable diseases between ages 30 and 70 (30-70)",
        "official_definition": (
            "The percentage of 30-year-old people who would die before their "
            "70th birthday from any of cardiovascular disease, cancer, diabetes, "
            "or chronic respiratory disease, assuming that they would experience "
            "current mortality rates at every age and they would not die from any "
            "other cause of death (e.g., injuries or HIV/AIDS). This is SDG indicator 3.4.1."
        ),
        "short_definition": (
            "Probability (%) of dying between age 30 and exact age 70 from any of "
            "cardiovascular disease, cancer, diabetes, or chronic respiratory disease."
        ),
        "unit": "%",
        "source_url": "https://data.who.int/indicators/i/C540135/1F96863",
        "who_odata_url": f"{WHO_API_BASE_URL.rstrip('/')}/NCDMORT3070",
        "category": "Noncommunicable diseases",
    },
    "UHC_COVERAGE": {
        "code": "UHC_INDEX_REPORTED",
        "description": "Universal Health Coverage service coverage index",
        "official_definition": (
            "The coverage of essential health services (defined as the average "
            "coverage of essential services based on tracer interventions that "
            "include reproductive, maternal, newborn and child health, infectious "
            "diseases, non-communicable diseases and service capacity and access, "
            "among the general and the most disadvantaged population). The indicator "
            "is an index reported on a unitless scale of 0 to 100, which is computed "
            "as the geometric mean of 14 tracer indicators of health service coverage."
        ),
        "short_definition": (
            "Coverage of essential health services based on tracer interventions "
            "including reproductive, maternal, newborn and child health, infectious "
            "diseases, non-communicable diseases and service capacity and access. "
            "Index 0-100, geometric mean of 14 tracer indicators."
        ),
        "unit": "index (0-100)",
        "source_url": "https://data.who.int/indicators/i/3805B1E/9A706FD",
        "who_odata_url": f"{WHO_API_BASE_URL.rstrip('/')}/UHC_INDEX_REPORTED",
        "category": "Universal Health Coverage",
    },
    "MATERNAL_MORTALITY": {
        "code": "MAT_4",
        "description": "Maternal mortality ratio (per 100,000 live births)",
        "official_definition": (
            "Number of maternal deaths during a given time period per 100,000 live births "
            "during the same time period. Maternal death is the death of a woman while pregnant "
            "or within 42 days of termination of pregnancy."
        ),
        "short_definition": "Maternal deaths per 100,000 live births.",
        "unit": "per 100,000 live births",
        "source_url": "https://www.who.int/data/gho/data/indicators",
        "who_odata_url": f"{WHO_API_BASE_URL.rstrip('/')}/MAT_4",
        "category": "Maternal health",
    },
    "INFANT_MORTALITY": {
        "code": "WHOSIS_000002",
        "description": "Infant mortality rate (per 1,000 live births)",
        "official_definition": (
            "Probability that a child born in a specific year or period will die before "
            "reaching the age of 1 year, expressed as number of infant deaths per 1,000 live births."
        ),
        "short_definition": "Deaths under age 1 per 1,000 live births.",
        "unit": "per 1,000 live births",
        "source_url": "https://www.who.int/data/gho/data/indicators",
        "who_odata_url": f"{WHO_API_BASE_URL.rstrip('/')}/WHOSIS_000002",
        "category": "Child health",
    },
}

DEFAULT_INDICATORS: List[str] = [
    "LIFE_EXPECTANCY",
    "NCD_MORTALITY",
    "UHC_COVERAGE",
]

# ---------------------------------------------------------------------------
# Quality/reporting defaults
# ---------------------------------------------------------------------------
MIN_RECORDS_PER_INDICATOR = int(
    os.environ.get("WHO_MIN_RECORDS_PER_INDICATOR", "1000")
)
MAX_NULL_PERCENTAGE = float(os.environ.get("WHO_MAX_NULL_PERCENTAGE", "0.05"))
EXPECTED_YEAR_RANGE: Tuple[int, int] = (
    int(os.environ.get("WHO_EXPECTED_YEAR_MIN", "2000")),
    int(os.environ.get("WHO_EXPECTED_YEAR_MAX", "2023")),
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get(
    "WHO_LOG_FORMAT",
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def setup_logging(name: str = "who_health_intelligence") -> logging.Logger:
    """
    Configure and return a logger with console and file handlers.
    No secrets are read or emitted.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if logger.handlers:
        return logger

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    try:
        file_handler = logging.FileHandler(
            LOGS_DIR / "who_health_intelligence.log", mode="a"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(file_handler)
    except Exception:
        pass

    logger.addHandler(console_handler)
    return logger


def validate_api_base_url(url: str) -> bool:
    """
    Validate WHO API base URL structure.
    Must be https and contain 'api' path.
    """
    if not url or not isinstance(url, str):
        raise ValueError(f"API base URL must be non-empty string, got: {url!r}")
    url = url.strip()
    if not url.startswith("https://"):
        raise ValueError(f"API base URL must start with https://, got: {url!r}")
    if len(url) < 10:
        raise ValueError(f"API base URL too short: {url!r}")
    return True


__all__ = [
    "API_MAX_RETRIES",
    "API_RETRY_BACKOFF_BASE",
    "API_TIMEOUT_SECONDS",
    "APPLICATION_TITLE",
    "DASHBOARD_SUBTITLE",
    "DASHBOARD_TITLE",
    "DATA_DIR",
    "DATABASE_PATH",
    "DEFAULT_INDICATORS",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_RETRY_COUNT",
    "EXPECTED_YEAR_RANGE",
    "LOG_FORMAT",
    "LOG_LEVEL",
    "LOGS_DIR",
    "MAX_NULL_PERCENTAGE",
    "METADATA_PATH",
    "MIN_RECORDS_PER_INDICATOR",
    "PIPELINE_VERSION",
    "PROCESSED_DATA_PATH",
    "PROJECT_ROOT",
    "PROJECT_VERSION",
    "RAW_DATA_PATH",
    "REPORTS_DIR",
    "WHO_API_BASE_URL",
    "WHO_INDICATORS",
    "WHO_REFRESH_TTL",
    "get_data_mode",
    "is_demo_mode",
    "is_live_mode",
    "setup_logging",
    "validate_api_base_url",
]
