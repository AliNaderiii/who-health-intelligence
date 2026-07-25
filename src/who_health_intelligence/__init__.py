"""
WHO Global Health Intelligence Platform

A production-oriented public health data platform for extracting, transforming,
analyzing, and visualizing World Health Organization (WHO) Global Health Observatory
(GHO) data.

Modules:
    - api: WHO GHO API client with robust error handling
    - etl: Extract-Transform-Load pipeline with idempotent loading
    - dashboard: Streamlit-based analytics dashboard
    - utils: Shared utilities and configuration
"""

try:
    from config import PROJECT_VERSION
except ModuleNotFoundError:  # pragma: no cover - supports repo-root imports
    from src.config import PROJECT_VERSION

__version__ = PROJECT_VERSION
__author__ = "WHO Health Intelligence Team"
__license__ = "MIT"
