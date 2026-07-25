"""
Configuration management for WHO Health Intelligence Platform.

Centralizes all configuration parameters including API endpoints, database paths,
indicator definitions, and logging settings.
"""

import os
from pathlib import Path
from typing import Dict, List
import logging

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Database configuration
DATABASE_PATH = os.environ.get(
    "WHO_DB_PATH",
    str(DATA_DIR / "who_health_data.db")
)

# WHO GHO API configuration
WHO_API_BASE_URL = "https://ghoapi.azureedge.net/api/"
API_TIMEOUT_SECONDS = 30
API_MAX_RETRIES = 3
API_RETRY_BACKOFF_BASE = 2  # Exponential backoff base

# WHO Indicator Definitions
# Format: {internal_name: {"code": api_code, "description": human_readable_desc}}
WHO_INDICATORS: Dict[str, Dict[str, str]] = {
    "LIFE_EXPECTANCY": {
        "code": "WHOSIS_000001",
        "description": "Life expectancy at birth (years)"
    },
    "NCD_MORTALITY": {
        "code": "NCDMORT3070",
        "description": "Probability of dying from NCDs between ages 30-70 (%)"
    },
    "UHC_COVERAGE": {
        "code": "UHC_INDEX_REPORTED",
        "description": "Universal Health Coverage service index (1-100)"
    },
    "MATERNAL_MORTALITY": {
        "code": "MAT_4",
        "description": "Maternal mortality ratio (per 100,000 live births)"
    },
    "INFANT_MORTALITY": {
        "code": "WHOSIS_000002",
        "description": "Infant mortality rate (per 1,000 live births)"
    }
}

# Default indicators to extract (subset for faster initial load)
DEFAULT_INDICATORS: List[str] = [
    "LIFE_EXPECTANCY",
    "NCD_MORTALITY",
    "UHC_COVERAGE"
]

# Logging configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Data quality thresholds
MIN_RECORDS_PER_INDICATOR = 1000
MAX_NULL_PERCENTAGE = 0.05  # 5%
EXPECTED_YEAR_RANGE = (2000, 2023)

# Dashboard configuration
DASHBOARD_TITLE = "WHO Global Health Intelligence Platform"
DASHBOARD_SUBTITLE = "Public Health Data Engineering & Epidemiological Analytics"

def setup_logging(name: str = "who_health_intelligence") -> logging.Logger:
    """
    Configure and return a logger with both file and console handlers.
    
    Args:
        name: Logger name (typically module name)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(LOG_FORMAT)
    console_handler.setFormatter(console_formatter)
    
    # File handler
    log_file = LOGS_DIR / "who_health_intelligence.log"
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(LOG_FORMAT)
    file_handler.setFormatter(file_formatter)
    
    # Add handlers if not already present
    if not logger.handlers:
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    return logger
