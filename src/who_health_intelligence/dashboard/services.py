"""
Data services for WHO Health Intelligence dashboard - Production LIVE mode.

Contains ALL data logic: loading, filtering, aggregation, analysis, metadata,
data mode handling (LIVE/DEMO/STALE), data quality reporting, geographic mapping coverage.

Dashboard app.py focuses purely on UI orchestration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..etl.loader import DatabaseLoader
from ..etl.metadata import get_mapping_coverage_report
from ..utils.config import (
    DATABASE_PATH,
    WHO_API_BASE_URL,
    WHO_INDICATORS,
    WHO_REFRESH_TTL,
    REPORTS_DIR,
    setup_logging,
    get_data_mode,
)
from ..utils.data_mode import get_data_status, get_stale_snapshot_info, get_current_data_mode, DataMode, APIStatus

try:
    import analytics as analytics_utils
    from data_quality import DataQualityReport
except ModuleNotFoundError:
    from src import analytics as analytics_utils
    from src.data_quality import DataQualityReport

logger = setup_logging(__name__)

# Indicator labels
INDICATOR_SHORT_NAMES: Dict[str, str] = {
    "LIFE_EXPECTANCY": "Life Expectancy",
    "NCD_MORTALITY": "NCD Mortality (30-70)",
    "UHC_COVERAGE": "UHC Coverage Index",
    "MATERNAL_MORTALITY": "Maternal Mortality",
    "INFANT_MORTALITY": "Infant Mortality",
}

HIGHER_IS_BETTER: Dict[str, bool] = {
    "LIFE_EXPECTANCY": True,
    "NCD_MORTALITY": False,
    "UHC_COVERAGE": True,
    "MATERNAL_MORTALITY": False,
    "INFANT_MORTALITY": False,
}

INDICATOR_UNITS: Dict[str, str] = {
    "LIFE_EXPECTANCY": "years",
    "NCD_MORTALITY": "%",
    "UHC_COVERAGE": "index (0-100)",
    "MATERNAL_MORTALITY": "per 100,000 live births",
    "INFANT_MORTALITY": "per 1,000 live births",
}

# Minimum number of complete paired observations required before a Pearson
# correlation or an OLS trendline is reported. Below this threshold the views
# must show an explanatory message instead of a statistic.
MIN_CORRELATION_OBSERVATIONS: int = 3


def indicator_short_name(indicator: str) -> str:
    return INDICATOR_SHORT_NAMES.get(indicator, indicator.replace("_", " ").title())


def indicator_description(indicator: str) -> str:
    info = WHO_INDICATORS.get(indicator, {})
    return info.get("description", indicator_short_name(indicator))


def indicator_official_definition(indicator: str) -> str:
    info = WHO_INDICATORS.get(indicator, {})
    return info.get("official_definition", indicator_description(indicator))


def indicator_unit(indicator: str) -> str:
    return INDICATOR_UNITS.get(indicator, WHO_INDICATORS.get(indicator, {}).get("unit", ""))


def is_higher_better(indicator: str) -> bool:
    return HIGHER_IS_BETTER.get(indicator, True)


# ------------------------------------------------------------------
# Column normalization helpers - support both snake_case (new) and CamelCase (legacy)
# ------------------------------------------------------------------
def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure DataFrame has both snake_case and CamelCase columns for compatibility.
    Transforms snake_case to expected legacy names if needed, and vice versa.
    Returns DataFrame with normalized columns for dashboard consumption.
    """
    if df.empty:
        return df

    df = df.copy()

    # Mapping snake -> legacy
    snake_to_legacy = {
        "country_code": "CountryCode",
        "country_name": "Country",
        "continent": "Continent",
        "year": "Year",
        "gender": "Gender",
        "indicator": "Indicator",
        "indicator_code": "IndicatorCode",
        "value": "Value",
    }
    legacy_to_snake = {v: k for k, v in snake_to_legacy.items()}

    # If snake exists but legacy missing, populate legacy
    for snake, legacy in snake_to_legacy.items():
        if snake in df.columns and legacy not in df.columns:
            df[legacy] = df[snake]
        elif legacy in df.columns and snake not in df.columns:
            df[snake] = df[legacy]

    # Ensure Country (country_name) populated from CountryCode mapping if still missing?
    # That will be handled by geography normalization earlier, but fallback to CountryCode
    if "Country" not in df.columns and "CountryCode" in df.columns:
        df["Country"] = df["CountryCode"]
    if "country_name" not in df.columns and "country_code" in df.columns:
        df["country_name"] = df["country_code"]

    return df


# ------------------------------------------------------------------
# Data Loading with LIVE/DEMO/STALE handling
# ------------------------------------------------------------------
def load_full_dataset(db_path: str = DATABASE_PATH) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Load dataset with data mode awareness.
    Returns (DataFrame, metadata_dict) including data_mode, api_status, etc.
    """
    metadata: Dict[str, Any] = {
        "db_path": str(db_path),
        "db_exists": False,
        "db_size_bytes": 0,
        "loaded_at": datetime.now(timezone.utc).isoformat() + "Z",
        "extraction_date": None,
        "row_count": 0,
        "status": "error",
        "error": None,
        "data_mode": get_data_mode().upper(),
        "api_status": APIStatus.UNKNOWN.value,
        "quality_status": "Unknown",
        "is_demo": False,
        "is_stale": False,
    }

    db_file = Path(db_path)
    if not db_file.exists():
        metadata["error"] = f"Database file not found: {db_path}"
        # For LIVE mode, check stale snapshot
        current_mode = get_current_data_mode()
        if current_mode == DataMode.LIVE:
            stale = get_stale_snapshot_info(db_file)
            if stale and stale.get("is_real"):
                metadata["error"] = f"Database file not found but stale real snapshot exists: {stale.get('extraction_timestamp')}"
                metadata["stale_info"] = stale
        return pd.DataFrame(), metadata

    metadata["db_exists"] = True
    try:
        metadata["db_size_bytes"] = db_file.stat().st_size
    except Exception:
        pass

    if db_file.stat().st_size == 0:
        metadata["error"] = "Database file is empty (0 bytes)"
        return pd.DataFrame(), metadata

    try:
        loader = DatabaseLoader(db_path)
        df = loader.query("SELECT * FROM health_indicators")

        if df.empty:
            metadata["error"] = "Database contains no records"
            return df, metadata

        # Normalize columns for dashboard compatibility
        df = _normalize_columns(df)

        # Type normalization using legacy columns (dashboard expects these)
        if "Year" in df.columns:
            df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        if "Value" in df.columns:
            df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
        for col in ["CountryCode", "Country", "Gender", "Indicator", "Continent"]:
            if col in df.columns:
                df[col] = df[col].astype(str).replace("nan", pd.NA)

        metadata["row_count"] = len(df)
        metadata["status"] = "ok"

        # Get extraction date from etl_metadata
        try:
            meta_df = loader.query("SELECT run_timestamp FROM etl_metadata ORDER BY id DESC LIMIT 1")
            if not meta_df.empty:
                metadata["extraction_date"] = str(meta_df.iloc[0]["run_timestamp"])
        except Exception:
            pass

        if metadata["extraction_date"] is None:
            # Try source_info
            try:
                src_df = loader.query("SELECT extraction_timestamp FROM source_info ORDER BY id DESC LIMIT 1")
                if not src_df.empty:
                    metadata["extraction_date"] = str(src_df.iloc[0]["extraction_timestamp"])
            except Exception:
                pass

        if metadata["extraction_date"] is None and "created_at" in df.columns:
            latest = df["created_at"].dropna()
            if len(latest) > 0:
                metadata["extraction_date"] = str(latest.max())

        # Data mode and status via centralized function
        data_status = get_data_status(db_path=Path(db_path))
        metadata.update(
            {
                "data_mode": data_status.get("data_mode", metadata["data_mode"]),
                "api_status": data_status.get("api_status", metadata["api_status"]),
                "quality_status": data_status.get("quality_status", metadata["quality_status"]),
                "is_demo": data_status.get("is_demo", False),
                "is_stale": data_status.get("is_stale", False),
                "n_countries": data_status.get("n_countries", 0),
                "year_range": data_status.get("year_range", "N/A"),
                "failure_reason": data_status.get("failure_reason"),
            }
        )

        # Add mapping coverage
        mapping_report = get_mapping_coverage_report(df)
        metadata["mapping_coverage"] = mapping_report

        # Add latest quality report score
        latest_q = loader.get_latest_quality_report()
        if latest_q:
            metadata["quality_score"] = latest_q.get("overall_score")
            metadata["quality_report"] = latest_q
        else:
            # Try to load JSON report if exists
            json_path = REPORTS_DIR / "data_quality_report.json"
            if json_path.exists():
                try:
                    import json

                    content = json.loads(json_path.read_text(encoding="utf-8"))
                    metadata["quality_score"] = content.get("overall_score", content.get("quality_score"))
                    metadata["quality_report_json"] = content
                except Exception:
                    pass

        return df, metadata

    except Exception as exc:
        metadata["error"] = str(exc)
        logger.error(f"Failed to load dataset: {exc}")
        return pd.DataFrame(), metadata


def get_data_mode_status(
    db_path: str = DATABASE_PATH,
    api_failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrapper for get_data_status with Path handling."""
    return get_data_status(db_path=Path(db_path), api_failure_reason=api_failure_reason)


def auto_bootstrap_enabled() -> bool:
    """
    Whether the dashboard may perform a first-run LIVE extraction when no local
    snapshot exists (e.g. on Streamlit Community Cloud, where the SQLite file is
    not persisted between deployments).

    Controlled by WHO_AUTO_BOOTSTRAP (default: enabled). Never applies to DEMO
    mode and never produces synthetic data.
    """
    import os

    raw = os.environ.get("WHO_AUTO_BOOTSTRAP", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def database_has_records(db_path: str = DATABASE_PATH) -> bool:
    """Cheap check for an existing usable snapshot without loading the dataset."""
    import sqlite3

    db_file = Path(db_path)
    if not db_file.exists() or db_file.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(str(db_file))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='health_indicators'"
            )
            if cur.fetchone() is None:
                return False
            cur.execute("SELECT COUNT(*) FROM health_indicators")
            return int(cur.fetchone()[0]) > 0
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Could not inspect database at {db_path}: {exc}")
        return False


def load_dashboard_data(
    db_path: str = DATABASE_PATH,
    allow_live_bootstrap: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Controlled data-loading entry point used by the dashboard.

    This function is intentionally the ONLY place that may trigger a live WHO
    API extraction for the dashboard. It is never executed at module import
    time, so the Streamlit app can render its shell and status panel first.

    Behaviour:
    - If a local snapshot exists, it is loaded and returned (LIVE or STALE REAL DATA).
    - If LIVE mode is active, no snapshot exists and bootstrapping is allowed,
      a single real WHO API extraction is attempted.
    - If that extraction fails, the failure is reported and NO synthetic data is
      substituted.
    - DEMO mode never triggers an extraction from here.
    """
    df, metadata = load_full_dataset(db_path)

    if not df.empty:
        return df, metadata

    mode = get_current_data_mode()
    if mode != DataMode.LIVE:
        return df, metadata

    if not (allow_live_bootstrap and auto_bootstrap_enabled()):
        metadata["bootstrap_attempted"] = False
        return df, metadata

    logger.info(
        "No local WHO snapshot found in LIVE mode - performing first-run live extraction"
    )
    refresh_result = trigger_live_refresh(db_path=db_path)
    metadata["bootstrap_attempted"] = True
    metadata["bootstrap_result"] = refresh_result

    if not refresh_result.get("success"):
        metadata["failure_reason"] = (
            refresh_result.get("failure_reason")
            or metadata.get("failure_reason")
            or "Live WHO API extraction failed and no cached real snapshot exists."
        )
        metadata["api_status"] = APIStatus.FAILED.value
        return df, metadata

    df, metadata = load_full_dataset(db_path)
    metadata["bootstrap_attempted"] = True
    metadata["bootstrap_result"] = refresh_result
    return df, metadata


# ------------------------------------------------------------------
# Filter options
# ------------------------------------------------------------------
def get_filter_options(df: pd.DataFrame) -> Dict[str, List[Any]]:
    if df.empty:
        return {"years": [], "countries": [], "continents": [], "indicators": [], "genders": []}

    df = _normalize_columns(df)

    # Ensure Year column exists
    year_col = "Year" if "Year" in df.columns else "year" if "year" in df.columns else None
    country_code_col = "CountryCode" if "CountryCode" in df.columns else "country_code"
    country_name_col = "Country" if "Country" in df.columns else "country_name"
    continent_col = "Continent" if "Continent" in df.columns else "continent"
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    gender_col = "Gender" if "Gender" in df.columns else "gender"

    years = sorted(df[year_col].dropna().unique().tolist()) if year_col else []
    # Countries
    if country_code_col in df.columns and country_name_col in df.columns:
        countries = (
            df[[country_code_col, country_name_col]]
            .dropna(subset=[country_code_col])
            .drop_duplicates()
            .sort_values(country_name_col)
        )
        country_options = [
            (row[country_code_col], row.get(country_name_col, row[country_code_col]))
            for _, row in countries.iterrows()
        ]
    else:
        country_options = []

    continents = (
        sorted(c for c in df[continent_col].dropna().unique().tolist() if c not in ("Unknown", "nan", "", "None"))
        if continent_col in df.columns
        else []
    )

    indicators = sorted(df[indicator_col].dropna().unique().tolist()) if indicator_col in df.columns else []
    genders = sorted(df[gender_col].dropna().unique().tolist()) if gender_col in df.columns else []

    return {
        "years": years,
        "countries": country_options,
        "continents": continents,
        "indicators": indicators,
        "genders": genders,
    }


def apply_filters(
    df: pd.DataFrame,
    *,
    indicators: Optional[List[str]] = None,
    year_range: Optional[Tuple[int, int]] = None,
    countries: Optional[List[str]] = None,
    continents: Optional[List[str]] = None,
    genders: Optional[List[str]] = None,
) -> pd.DataFrame:
    if df.empty:
        return df

    df = _normalize_columns(df)

    mask = pd.Series(True, index=df.index)

    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"
    country_col = "CountryCode" if "CountryCode" in df.columns else "country_code"
    continent_col = "Continent" if "Continent" in df.columns else "continent"
    gender_col = "Gender" if "Gender" in df.columns else "gender"

    if indicators:
        mask &= df[indicator_col].isin(indicators)
    if year_range and year_col in df.columns:
        mask &= (df[year_col] >= year_range[0]) & (df[year_col] <= year_range[1])
    if countries and country_col in df.columns:
        mask &= df[country_col].isin(countries)
    if continents and continent_col in df.columns:
        mask &= df[continent_col].isin(continents)
    if genders and gender_col in df.columns:
        mask &= df[gender_col].isin(genders)

    return df.loc[mask].copy()


# ------------------------------------------------------------------
# KPIs
# ------------------------------------------------------------------
def compute_kpis(filtered_df: pd.DataFrame, full_df: pd.DataFrame, selected_year: int) -> Dict[str, Any]:
    if filtered_df.empty:
        return {
            "n_countries": 0,
            "n_indicators": 0,
            "selected_year": selected_year,
            "reporting_coverage_pct": 0.0,
            "missing_value_rate_pct": 0.0,
            "n_records": 0,
        }

    filtered_df = _normalize_columns(filtered_df)
    full_df = _normalize_columns(full_df)

    year_col = "Year" if "Year" in filtered_df.columns else "year"
    country_col = "CountryCode" if "CountryCode" in filtered_df.columns else "country_code"
    indicator_col = "Indicator" if "Indicator" in filtered_df.columns else "indicator"
    value_col = "Value" if "Value" in filtered_df.columns else "value"

    year_df = filtered_df[filtered_df[year_col] == selected_year] if year_col in filtered_df.columns else pd.DataFrame()

    n_countries = year_df[country_col].nunique() if not year_df.empty and country_col in year_df.columns else 0
    n_indicators = filtered_df[indicator_col].nunique() if indicator_col in filtered_df.columns else 0

    total_countries = full_df[country_col].nunique() if not full_df.empty and country_col in full_df.columns else 1
    reporting_coverage_pct = (n_countries / total_countries * 100) if total_countries > 0 else 0

    total_cells = len(filtered_df)
    missing_cells = int(filtered_df[value_col].isna().sum()) if total_cells > 0 and value_col in filtered_df.columns else 0
    missing_value_rate_pct = (missing_cells / total_cells * 100) if total_cells > 0 else 0

    return {
        "n_countries": n_countries,
        "n_indicators": n_indicators,
        "selected_year": selected_year,
        "reporting_coverage_pct": round(reporting_coverage_pct, 1),
        "missing_value_rate_pct": round(missing_value_rate_pct, 2),
        "n_records": len(filtered_df),
    }


# ------------------------------------------------------------------
# Aggregation helpers
# ------------------------------------------------------------------
def compute_unweighted_average(df: pd.DataFrame, indicator: str, year: Optional[int] = None) -> Optional[float]:
    df = _normalize_columns(df)
    years = [year] if year is not None else None
    summary = analytics_utils.compute_unweighted_averages(
        df,
        group_by=["Indicator"] + (["Year"] if year is not None else []),
        indicators=[indicator],
        years=years,
    )
    if summary.empty:
        return None
    value = summary["MeanValue"].dropna()
    return float(value.iloc[0]) if not value.empty else None


def compute_population_weighted_average(
    df: pd.DataFrame, indicator: str, year: Optional[int] = None, population_df: Optional[pd.DataFrame] = None
) -> Optional[float]:
    df = _normalize_columns(df)
    years = [year] if year is not None else None
    summary = analytics_utils.compute_population_weighted_averages(
        df,
        population_df,
        group_by=["Indicator"] + (["Year"] if year is not None else []),
        indicators=[indicator],
        years=years,
    )
    if summary.empty:
        return None
    value = summary["WeightedMeanValue"].dropna()
    return float(value.iloc[0]) if not value.empty else None


# ------------------------------------------------------------------
# Analytical view builders (handle both naming conventions)
# ------------------------------------------------------------------
def build_geospatial_data(df: pd.DataFrame, indicator: str, year: int) -> pd.DataFrame:
    df = _normalize_columns(df)
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"
    gender_col = "Gender" if "Gender" in df.columns else "gender"

    subset = df[(df[indicator_col] == indicator) & (df[year_col] == year)].copy()
    if subset.empty:
        return subset
    if gender_col in subset.columns and "Both sexes" in subset[gender_col].astype(str).values:
        subset = subset[subset[gender_col] == "Both sexes"]
    return subset


def build_ranking_data(df: pd.DataFrame, indicator: str, year: int, top_n: int = 20, ascending: bool = False) -> pd.DataFrame:
    df = _normalize_columns(df)
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"
    gender_col = "Gender" if "Gender" in df.columns else "gender"
    value_col = "Value" if "Value" in df.columns else "value"

    subset = df[(df[indicator_col] == indicator) & (df[year_col] == year)].copy()
    if subset.empty:
        return subset
    if gender_col in subset.columns and "Both sexes" in subset[gender_col].astype(str).values:
        subset = subset[subset[gender_col] == "Both sexes"]

    subset = subset.dropna(subset=[value_col])
    subset = subset.sort_values(value_col, ascending=ascending).head(top_n)

    # Ensure legacy columns for display
    if "Country" in subset.columns:
        subset["Rank"] = range(1, len(subset) + 1)
        cols = [c for c in ["Rank", "Country", "CountryCode", "Continent", "Value"] if c in subset.columns]
        return subset[cols]
    return subset


def build_time_series_data(df: pd.DataFrame, indicator: str, aggregate: str = "mean") -> pd.DataFrame:
    df = _normalize_columns(df)
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    value_col = "Value" if "Value" in df.columns else "value"
    year_col = "Year" if "Year" in df.columns else "year"

    subset = df[df[indicator_col] == indicator]
    if subset.empty:
        return pd.DataFrame()

    agg = (
        subset.groupby(year_col)[value_col]
        .agg(["mean", "median", "std", lambda x: x.quantile(0.25), lambda x: x.quantile(0.75), "count"])
        .reset_index()
    )
    agg.columns = ["Year", "mean", "median", "std", "p25", "p75", "n_countries"]
    return agg


def build_country_time_series(df: pd.DataFrame, indicator: str, countries: Optional[List[str]] = None, top_n: int = 8) -> pd.DataFrame:
    df = _normalize_columns(df)
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    country_col = "CountryCode" if "CountryCode" in df.columns else "country_code"
    value_col = "Value" if "Value" in df.columns else "value"

    subset = df[df[indicator_col] == indicator]
    if subset.empty:
        return subset

    if countries is None:
        top = subset.groupby(country_col)[value_col].mean().nlargest(top_n).index.tolist()
        subset = subset[subset[country_col].isin(top)]
    else:
        subset = subset[subset[country_col].isin(countries)]

    return subset


def build_distribution_data(df: pd.DataFrame, indicator: str, year: int) -> pd.DataFrame:
    df = _normalize_columns(df)
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"
    gender_col = "Gender" if "Gender" in df.columns else "gender"

    subset = df[(df[indicator_col] == indicator) & (df[year_col] == year)].copy()
    if subset.empty:
        return subset
    if gender_col in subset.columns and "Both sexes" in subset[gender_col].astype(str).values:
        subset = subset[subset[gender_col] == "Both sexes"]
    return subset


def build_correlation_data(df: pd.DataFrame, indicator_x: str, indicator_y: str, year: int) -> Tuple[pd.DataFrame, float]:
    df = _normalize_columns(df)
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"
    country_col = "CountryCode" if "CountryCode" in df.columns else "country_code"
    continent_col = "Continent" if "Continent" in df.columns else "continent"
    value_col = "Value" if "Value" in df.columns else "value"
    gender_col = "Gender" if "Gender" in df.columns else "gender"
    country_name_col = "Country" if "Country" in df.columns else "country_name"

    df_x = df[(df[indicator_col] == indicator_x) & (df[year_col] == year)][[country_col, value_col, continent_col]].copy()
    df_x = df_x.rename(columns={value_col: "Value_X"})

    df_y = df[(df[indicator_col] == indicator_y) & (df[year_col] == year)][[country_col, value_col]].copy()
    df_y = df_y.rename(columns={value_col: "Value_Y"})

    full_subset = df[df[year_col] == year]
    if gender_col in full_subset.columns and "Both sexes" in full_subset[gender_col].astype(str).values:
        both_sex = full_subset[full_subset[gender_col] == "Both sexes"]
        if country_name_col in both_sex.columns:
            name_map = both_sex[[country_col, country_name_col]].drop_duplicates()
        else:
            name_map = both_sex[[country_col]].drop_duplicates()
            name_map[country_name_col] = name_map[country_col]
    else:
        if country_name_col in full_subset.columns:
            name_map = full_subset[[country_col, country_name_col]].drop_duplicates()
        else:
            name_map = full_subset[[country_col]].drop_duplicates()
            name_map[country_name_col] = name_map[country_col]

    merged = df_x.merge(df_y, on=country_col, how="inner")
    # Merge country names
    merged = merged.merge(name_map, on=country_col, how="left")
    merged = merged.dropna(subset=["Value_X", "Value_Y"])

    if len(merged) < MIN_CORRELATION_OBSERVATIONS:
        return pd.DataFrame(), float("nan")

    pearson_r = float(merged["Value_X"].corr(merged["Value_Y"]))
    return merged, pearson_r


def compute_ols_trendline(
    x: Any,
    y: Any,
    n_points: int = 100,
) -> Optional[Dict[str, Any]]:
    """
    Fit a simple ordinary-least-squares line y = slope * x + intercept.

    Implemented with ``numpy.polyfit`` (which wraps ``numpy.linalg.lstsq``) so the
    dashboard has **no runtime dependency on statsmodels or scipy**. This avoids the
    ``plotly.express`` ``trendline="ols"`` code path, which imports statsmodels and
    breaks on Streamlit Community Cloud whenever the resolved statsmodels/scipy pair
    is incompatible (``ImportError: cannot import name '_lazywhere'``).

    Unit of analysis:
        Paired entity observations (usually countries in a single year).
    Missing data behavior:
        Pairwise deletion — any pair with a missing or non-finite value in either
        indicator is dropped before fitting.
    Descriptive or inferential:
        Descriptive association only. The fitted line summarises the observed
        relationship and must not be read as causal inference.

    Returns ``None`` when fewer than ``MIN_CORRELATION_OBSERVATIONS`` valid pairs
    remain, or when the fit is not numerically defined (e.g. zero variance in x).
    Callers are expected to surface a message instead of crashing.
    """
    x_arr = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy(dtype=float)
    y_arr = pd.to_numeric(pd.Series(y), errors="coerce").to_numpy(dtype=float)

    if x_arr.size != y_arr.size or x_arr.size == 0:
        return None

    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_valid = x_arr[valid]
    y_valid = y_arr[valid]
    n_valid = int(x_valid.size)
    n_dropped = int(x_arr.size - n_valid)

    if n_valid < MIN_CORRELATION_OBSERVATIONS:
        return None

    # Degenerate geometry: a vertical (or single-point) cloud has no OLS slope.
    if np.ptp(x_valid) == 0:
        return None

    try:
        slope, intercept = np.polyfit(x_valid, y_valid, 1)
    except (np.linalg.LinAlgError, ValueError, TypeError):
        return None

    slope = float(slope)
    intercept = float(intercept)
    if not (np.isfinite(slope) and np.isfinite(intercept)):
        return None

    x_line = np.linspace(float(x_valid.min()), float(x_valid.max()), max(int(n_points), 2))
    y_line = slope * x_line + intercept

    y_pred = slope * x_valid + intercept
    ss_res = float(np.sum((y_valid - y_pred) ** 2))
    ss_tot = float(np.sum((y_valid - y_valid.mean()) ** 2))
    r_squared = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "n_observations": n_valid,
        "n_dropped": n_dropped,
        "x_line": x_line,
        "y_line": y_line,
        "equation": f"y = {slope:.4g}x {'+' if intercept >= 0 else '-'} {abs(intercept):.4g}",
        "method": "Ordinary least squares (numpy.polyfit, degree 1)",
    }


def build_country_profile(df: pd.DataFrame, country_code: str) -> pd.DataFrame:
    df = _normalize_columns(df)
    country_col = "CountryCode" if "CountryCode" in df.columns else "country_code"
    gender_col = "Gender" if "Gender" in df.columns else "gender"
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"

    subset = df[df[country_col] == country_code].copy()
    if subset.empty:
        return subset
    if gender_col in subset.columns and "Both sexes" in subset[gender_col].astype(str).values:
        subset = subset[subset[gender_col] == "Both sexes"]
    return subset.sort_values([indicator_col, year_col])


# ------------------------------------------------------------------
# Data Quality
# ------------------------------------------------------------------
def compute_quality_report(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"overall_score": 0, "error": "No data"}
    df = _normalize_columns(df)
    report = DataQualityReport(df)
    return report.generate_full_report()


def get_latest_comprehensive_quality_report(db_path: str = DATABASE_PATH) -> Optional[Dict[str, Any]]:
    """
    Try to get latest quality report from DB, fallback to JSON file, fallback to generating from current df.
    """
    try:
        loader = DatabaseLoader(db_path)
        latest = loader.get_latest_quality_report()
        if latest:
            return latest
    except Exception:
        pass

    # Try JSON file
    json_path = REPORTS_DIR / "data_quality_report.json"
    if json_path.exists():
        try:
            import json

            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return None


# ------------------------------------------------------------------
# Metadata / Freshness
# ------------------------------------------------------------------
def get_data_source_metadata(db_metadata: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    df = _normalize_columns(df)
    year_col = "Year" if "Year" in df.columns else "year"

    year_min = int(df[year_col].min()) if not df.empty and year_col in df.columns else None
    year_max = int(df[year_col].max()) if not df.empty and year_col in df.columns else None

    return {
        "source": "World Health Organization — Global Health Observatory (GHO)",
        "api": WHO_API_BASE_URL,
        "extraction_date": db_metadata.get("extraction_date"),
        "db_last_modified": db_metadata.get("loaded_at"),
        "year_range": f"{year_min}–{year_max}" if year_min and year_max else "N/A",
        "total_records": db_metadata.get("row_count", 0),
        "db_path": db_metadata.get("db_path"),
        "status": db_metadata.get("status", "unknown"),
        "data_mode": db_metadata.get("data_mode", "LIVE"),
        "api_status": db_metadata.get("api_status", "Unknown"),
        "quality_status": db_metadata.get("quality_status", "Unknown"),
        "is_demo": db_metadata.get("is_demo", False),
        "is_stale": db_metadata.get("is_stale", False),
        "mapping_coverage": db_metadata.get("mapping_coverage", {}),
    }


def build_data_summary(df: pd.DataFrame, metadata: Dict[str, Any]) -> str:
    if df.empty:
        return "No data available."

    df = _normalize_columns(df)
    country_col = "CountryCode" if "CountryCode" in df.columns else "country_code"
    indicator_col = "Indicator" if "Indicator" in df.columns else "indicator"
    year_col = "Year" if "Year" in df.columns else "year"

    n_records = len(df)
    n_countries = df[country_col].nunique() if country_col in df.columns else 0
    n_indicators = df[indicator_col].nunique() if indicator_col in df.columns else 0
    year_min = int(df[year_col].min()) if year_col in df.columns and not df.empty else 0
    year_max = int(df[year_col].max()) if year_col in df.columns and not df.empty else 0
    indicators_list = ", ".join(indicator_short_name(i) for i in sorted(df[indicator_col].unique())) if indicator_col in df.columns else ""

    lines = [
        f"**{n_records:,} records** across **{n_countries} countries**",
        f"**{n_indicators} indicators:** {indicators_list}",
        f"**Years:** {year_min}–{year_max}",
    ]

    extraction = metadata.get("extraction_date")
    if extraction:
        lines.append(f"**Last extraction:** {extraction}")

    # Add mapping coverage
    mapping = metadata.get("mapping_coverage", {})
    if mapping:
        lines.append(
            f"**Mapping:** {mapping.get('mapped_countries', 0)}/{mapping.get('total_countries', 0)} "
            f"({mapping.get('mapping_coverage_pct', 0)}%)"
        )

    return "  ·  ".join(lines)


# ------------------------------------------------------------------
# Refresh logic for dashboard button
# ------------------------------------------------------------------
def trigger_live_refresh(db_path: str = DATABASE_PATH, indicators: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Trigger a real API refresh from dashboard Refresh Data button.
    Returns result dict with success/failure, timestamp, etc.
    Never creates duplicate records due to idempotent loader.

    This function is called from Streamlit dashboard when user clicks Refresh.
    It respects WHO_DATA_MODE and will not use synthetic data in LIVE mode.
    """
    from ..etl.pipeline import WHOETLPipeline

    try:
        pipeline = WHOETLPipeline(db_path=db_path)
        result = pipeline.run(indicators=indicators, replace=True, generate_quality_report=True, allow_stale_fallback=True)
        return {
            "success": result.get("status") in ("success", "stale", "success_with_quality_warnings"),
            "status": result.get("status"),
            "data_mode": result.get("data_mode"),
            "api_status": result.get("api_status"),
            "extraction_timestamp": result.get("extraction_timestamp"),
            "records_loaded": result.get("loading", {}).get("records_loaded", 0),
            "failure_reason": result.get("failure_reason"),
            "quality_score": result.get("quality_report", {}).get("overall_score") if result.get("quality_report") else None,
            "stale_fallback_used": result.get("stale_fallback_used", False),
        }
    except Exception as e:
        logger.error(f"Live refresh failed: {e}")
        return {
            "success": False,
            "status": "failed",
            "failure_reason": str(e),
        }


# ------------------------------------------------------------------
# CSV export
# ------------------------------------------------------------------
def build_export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
