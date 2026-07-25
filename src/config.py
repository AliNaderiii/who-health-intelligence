"""
Central project configuration for the WHO Global Health Intelligence Platform.

Configuration is intentionally non-secret. Runtime overrides are read from
environment variables where appropriate; no credentials or tokens are stored in
this repository.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------
PROJECT_VERSION = os.environ.get("WHO_PROJECT_VERSION", "3.0.0")
APPLICATION_TITLE = os.environ.get("WHO_APPLICATION_TITLE", "WHO Global Health Intelligence Platform")
DASHBOARD_TITLE = APPLICATION_TITLE
DASHBOARD_SUBTITLE = os.environ.get(
    "WHO_DASHBOARD_SUBTITLE",
    "Public Health Data Engineering & Epidemiological Analytics",
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(os.environ.get("WHO_PROJECT_ROOT", Path(__file__).resolve().parent.parent)).resolve()
DATA_DIR = Path(os.environ.get("WHO_DATA_DIR", PROJECT_ROOT / "data")).resolve()
RAW_DATA_PATH = Path(os.environ.get("WHO_RAW_DATA_PATH", DATA_DIR / "raw")).resolve()
PROCESSED_DATA_PATH = Path(os.environ.get("WHO_PROCESSED_DATA_PATH", DATA_DIR / "processed")).resolve()
METADATA_PATH = Path(os.environ.get("WHO_METADATA_PATH", DATA_DIR / "metadata")).resolve()
LOGS_DIR = Path(os.environ.get("WHO_LOGS_DIR", PROJECT_ROOT / "logs")).resolve()
DATABASE_PATH = Path(os.environ.get("WHO_DB_PATH", DATA_DIR / "who_health_data.db")).resolve()

for directory in (DATA_DIR, RAW_DATA_PATH, PROCESSED_DATA_PATH, METADATA_PATH, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# WHO API configuration
# ---------------------------------------------------------------------------
WHO_API_BASE_URL = os.environ.get("WHO_API_BASE_URL", "https://ghoapi.azureedge.net/api/")
DEFAULT_REQUEST_TIMEOUT = int(os.environ.get("WHO_REQUEST_TIMEOUT", "30"))
DEFAULT_RETRY_COUNT = int(os.environ.get("WHO_RETRY_COUNT", "3"))
API_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT
API_MAX_RETRIES = DEFAULT_RETRY_COUNT
API_RETRY_BACKOFF_BASE = int(os.environ.get("WHO_RETRY_BACKOFF_BASE", "2"))

# ---------------------------------------------------------------------------
# WHO indicator definitions
# ---------------------------------------------------------------------------
WHO_INDICATORS: Dict[str, Dict[str, str]] = {
    "LIFE_EXPECTANCY": {
        "code": "WHOSIS_000001",
        "description": "Life expectancy at birth (years)",
    },
    "NCD_MORTALITY": {
        "code": "NCDMORT3070",
        "description": "Probability of dying from NCDs between ages 30-70 (%)",
    },
    "UHC_COVERAGE": {
        "code": "UHC_INDEX_REPORTED",
        "description": "Universal Health Coverage service index (1-100)",
    },
    "MATERNAL_MORTALITY": {
        "code": "MAT_4",
        "description": "Maternal mortality ratio (per 100,000 live births)",
    },
    "INFANT_MORTALITY": {
        "code": "WHOSIS_000002",
        "description": "Infant mortality rate (per 1,000 live births)",
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
MIN_RECORDS_PER_INDICATOR = int(os.environ.get("WHO_MIN_RECORDS_PER_INDICATOR", "1000"))
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

    The log file is written under ``LOGS_DIR``. No secrets are read or emitted by
    this configuration helper.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if logger.handlers:
        return logger

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    file_handler = logging.FileHandler(LOGS_DIR / "who_health_intelligence.log", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


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
    "PROCESSED_DATA_PATH",
    "PROJECT_ROOT",
    "PROJECT_VERSION",
    "RAW_DATA_PATH",
    "WHO_API_BASE_URL",
    "WHO_INDICATORS",
    "setup_logging",
]
