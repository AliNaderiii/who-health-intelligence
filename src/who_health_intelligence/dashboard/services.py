"""
Data services for the WHO Health Intelligence dashboard.

This module contains ALL data logic: loading, filtering, aggregation,
analysis, and metadata retrieval. The dashboard app.py calls these
functions and focuses purely on UI orchestration.

This separation ensures:
- Services are independently testable (no Streamlit dependency)
- Data logic is reusable across CLI, notebook, and dashboard contexts
- UI code remains declarative and easy to maintain
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..etl.loader import DatabaseLoader
from ..utils.config import DATABASE_PATH, WHO_API_BASE_URL, WHO_INDICATORS, setup_logging

try:
    import analytics as analytics_utils
    from data_quality import DataQualityReport
except ModuleNotFoundError:  # pragma: no cover - supports repo-root imports in tests
    from src import analytics as analytics_utils
    from src.data_quality import DataQualityReport

logger = setup_logging(__name__)


# ============================================================
# Indicator Label Helpers
# ============================================================

INDICATOR_SHORT_NAMES: Dict[str, str] = {
    "LIFE_EXPECTANCY": "Life Expectancy",
    "NCD_MORTALITY": "NCD Mortality (30-70)",
    "UHC_COVERAGE": "UHC Coverage Index",
    "MATERNAL_MORTALITY": "Maternal Mortality",
    "INFANT_MORTALITY": "Infant Mortality",
}

# Indicators where lower values are better (affects delta color)
HIGHER_IS_BETTER: Dict[str, bool] = {
    "LIFE_EXPECTANCY": True,
    "NCD_MORTALITY": False,
    "UHC_COVERAGE": True,
    "MATERNAL_MORTALITY": False,
    "INFANT_MORTALITY": False,
}

# Units for display
INDICATOR_UNITS: Dict[str, str] = {
    "LIFE_EXPECTANCY": "years",
    "NCD_MORTALITY": "%",
    "UHC_COVERAGE": "index (1-100)",
    "MATERNAL_MORTALITY": "per 100,000 live births",
    "INFANT_MORTALITY": "per 1,000 live births",
}


def indicator_short_name(indicator: str) -> str:
    """Return a short, human-readable indicator label."""
    return INDICATOR_SHORT_NAMES.get(indicator, indicator.replace("_", " ").title())


def indicator_description(indicator: str) -> str:
    """Return the full description for an indicator."""
    info = WHO_INDICATORS.get(indicator, {})
    return info.get("description", indicator_short_name(indicator))


def indicator_unit(indicator: str) -> str:
    """Return the unit string for an indicator."""
    return INDICATOR_UNITS.get(indicator, "")


def is_higher_better(indicator: str) -> bool:
    """Return True if higher values indicate better outcomes."""
    return HIGHER_IS_BETTER.get(indicator, True)


# ============================================================
# Data Loading
# ============================================================


def load_full_dataset(db_path: str = DATABASE_PATH) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Load the full health indicator dataset from SQLite.

    Returns:
        Tuple of (DataFrame, metadata_dict).
        If the database is missing or empty, returns (empty_df, metadata_with_error).
    """
    metadata: Dict[str, Any] = {
        "db_path": str(db_path),
        "db_exists": False,
        "db_size_bytes": 0,
        "loaded_at": datetime.utcnow().isoformat() + "Z",
        "extraction_date": None,
        "row_count": 0,
        "status": "error",
        "error": None,
    }

    db_file = Path(db_path)
    if not db_file.exists():
        metadata["error"] = f"Database file not found: {db_path}"
        return pd.DataFrame(), metadata

    metadata["db_exists"] = True
    metadata["db_size_bytes"] = db_file.stat().st_size

    if db_file.stat().st_size == 0:
        metadata["error"] = "Database file is empty (0 bytes)"
        return pd.DataFrame(), metadata

    try:
        loader = DatabaseLoader(db_path)
        df = loader.query("SELECT * FROM health_indicators")

        if df.empty:
            metadata["error"] = "Database contains no records"
            return df, metadata

        # Type normalization
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
        for col in ["CountryCode", "Country", "Gender", "Indicator", "Continent"]:
            if col in df.columns:
                df[col] = df[col].astype(str).replace("nan", pd.NA)

        metadata["row_count"] = len(df)
        metadata["status"] = "ok"

        # Try to get extraction date from metadata table
        try:
            meta_df = loader.query(
                "SELECT run_timestamp FROM etl_metadata ORDER BY id DESC LIMIT 1"
            )
            if not meta_df.empty:
                metadata["extraction_date"] = str(meta_df.iloc[0]["run_timestamp"])
        except Exception:
            pass

        # Use max(created_at) as fallback extraction date
        if metadata["extraction_date"] is None and "created_at" in df.columns:
            latest = df["created_at"].dropna()
            if len(latest) > 0:
                metadata["extraction_date"] = str(latest.max())

        return df, metadata

    except Exception as exc:
        metadata["error"] = str(exc)
        logger.error(f"Failed to load dataset: {exc}")
        return pd.DataFrame(), metadata


# ============================================================
# Filter Options
# ============================================================


def get_filter_options(
    df: pd.DataFrame,
) -> Dict[str, List[Any]]:
    """
    Derive available filter options from the loaded dataset.

    Returns a dict with keys: years, countries, continents, indicators, genders.
    """
    if df.empty:
        return {
            "years": [],
            "countries": [],
            "continents": [],
            "indicators": [],
            "genders": [],
        }

    years = sorted(df["Year"].dropna().unique().tolist())
    countries = (
        df[["CountryCode", "Country"]]
        .dropna(subset=["CountryCode"])
        .drop_duplicates()
        .sort_values("Country")
    )
    country_options = [
        (row["CountryCode"], row.get("Country", row["CountryCode"]))
        for _, row in countries.iterrows()
    ]

    continents = sorted(
        c for c in df["Continent"].dropna().unique().tolist()
        if c not in ("Unknown", "nan", "")
    )

    indicators = sorted(df["Indicator"].dropna().unique().tolist())
    genders = sorted(df["Gender"].dropna().unique().tolist())

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
    """
    Apply a set of filters to the dataset.

    Returns the filtered DataFrame (never modifies the input).
    """
    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if indicators:
        mask &= df["Indicator"].isin(indicators)
    if year_range:
        mask &= (df["Year"] >= year_range[0]) & (df["Year"] <= year_range[1])
    if countries:
        mask &= df["CountryCode"].isin(countries)
    if continents:
        mask &= df["Continent"].isin(continents)
    if genders:
        mask &= df["Gender"].isin(genders)

    return df.loc[mask].copy()


# ============================================================
# KPI Computation
# ============================================================


def compute_kpis(
    filtered_df: pd.DataFrame,
    full_df: pd.DataFrame,
    selected_year: int,
) -> Dict[str, Any]:
    """
    Compute KPI summary statistics for the current filter selection.

    Returns a dict suitable for rendering as KPI cards.
    """
    if filtered_df.empty:
        return {
            "n_countries": 0,
            "n_indicators": 0,
            "selected_year": selected_year,
            "reporting_coverage_pct": 0.0,
            "missing_value_rate_pct": 0.0,
            "n_records": 0,
        }

    year_df = filtered_df[filtered_df["Year"] == selected_year]

    n_countries = year_df["CountryCode"].nunique() if not year_df.empty else 0
    n_indicators = filtered_df["Indicator"].nunique()

    # Reporting coverage: % of total countries in dataset that report for selected year
    total_countries = full_df["CountryCode"].nunique() if not full_df.empty else 1
    reporting_coverage_pct = (
        (n_countries / total_countries * 100) if total_countries > 0 else 0
    )

    # Missing-value rate for the Value column in the filtered data
    total_cells = len(filtered_df)
    missing_cells = int(filtered_df["Value"].isna().sum()) if total_cells > 0 else 0
    missing_value_rate_pct = (
        (missing_cells / total_cells * 100) if total_cells > 0 else 0
    )

    return {
        "n_countries": n_countries,
        "n_indicators": n_indicators,
        "selected_year": selected_year,
        "reporting_coverage_pct": round(reporting_coverage_pct, 1),
        "missing_value_rate_pct": round(missing_value_rate_pct, 2),
        "n_records": len(filtered_df),
    }


# ============================================================
# Aggregation Helpers
# ============================================================


def compute_unweighted_average(
    df: pd.DataFrame,
    indicator: str,
    year: Optional[int] = None,
) -> Optional[float]:
    """
    Compute the simple (unweighted) mean across countries for an indicator.

    Each country contributes equally regardless of population size.
    This is the correct aggregation when population data is unavailable.
    """
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
    df: pd.DataFrame,
    indicator: str,
    year: Optional[int] = None,
    population_df: Optional[pd.DataFrame] = None,
) -> Optional[float]:
    """
    Compute population-weighted average for an indicator.

    Returns None if population data is unavailable.
    The caller must provide a population DataFrame with columns:
    ['CountryCode', 'Year', 'Population'].

    NOTE: Population data is NOT included in the current dataset.
    This function exists to support future integration of World Bank
    or UN population data.
    """
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


# ============================================================
# Analytical View Builders
# ============================================================


def build_geospatial_data(
    df: pd.DataFrame,
    indicator: str,
    year: int,
) -> pd.DataFrame:
    """Build a DataFrame ready for a choropleth map."""
    subset = df[
        (df["Indicator"] == indicator) & (df["Year"] == year)
    ].copy()
    if subset.empty:
        return subset
    # Deduplicate in case of multiple genders — take the 'Both sexes' row
    if "Both sexes" in subset["Gender"].values:
        subset = subset[subset["Gender"] == "Both sexes"]
    return subset


def build_ranking_data(
    df: pd.DataFrame,
    indicator: str,
    year: int,
    top_n: int = 20,
    ascending: bool = False,
) -> pd.DataFrame:
    """
    Build a ranked list of countries for an indicator in a given year.

    Args:
        ascending: If True, lower values rank higher (e.g. mortality).
    """
    subset = df[
        (df["Indicator"] == indicator) & (df["Year"] == year)
    ].copy()
    if subset.empty:
        return subset
    if "Both sexes" in subset["Gender"].values:
        subset = subset[subset["Gender"] == "Both sexes"]

    subset = subset.dropna(subset=["Value"])
    subset = subset.sort_values("Value", ascending=ascending).head(top_n)

    if "Country" in subset.columns:
        subset["Rank"] = range(1, len(subset) + 1)
        return subset[["Rank", "Country", "CountryCode", "Continent", "Value"]]
    return subset


def build_time_series_data(
    df: pd.DataFrame,
    indicator: str,
    aggregate: str = "mean",
) -> pd.DataFrame:
    """
    Build global time-series data for an indicator.

    Returns a DataFrame with columns: Year, mean, median, std, p25, p75, n_countries.
    """
    subset = df[df["Indicator"] == indicator]
    if subset.empty:
        return pd.DataFrame()

    agg = (
        subset.groupby("Year")["Value"]
        .agg(["mean", "median", "std", lambda x: x.quantile(0.25), lambda x: x.quantile(0.75), "count"])
        .reset_index()
    )
    agg.columns = ["Year", "mean", "median", "std", "p25", "p75", "n_countries"]
    return agg


def build_country_time_series(
    df: pd.DataFrame,
    indicator: str,
    countries: Optional[List[str]] = None,
    top_n: int = 8,
) -> pd.DataFrame:
    """Build time-series data for specific countries (or top-N by mean)."""
    subset = df[df["Indicator"] == indicator]
    if subset.empty:
        return subset

    if countries is None:
        # Pick top-N countries by mean value
        top = (
            subset.groupby("CountryCode")["Value"]
            .mean()
            .nlargest(top_n)
            .index.tolist()
        )
        subset = subset[subset["CountryCode"].isin(top)]
    else:
        subset = subset[subset["CountryCode"].isin(countries)]

    return subset


def build_distribution_data(
    df: pd.DataFrame,
    indicator: str,
    year: int,
) -> pd.DataFrame:
    """Build data for histogram / distribution analysis."""
    subset = df[
        (df["Indicator"] == indicator) & (df["Year"] == year)
    ].copy()
    if subset.empty:
        return subset
    if "Both sexes" in subset["Gender"].values:
        subset = subset[subset["Gender"] == "Both sexes"]
    return subset


def build_correlation_data(
    df: pd.DataFrame,
    indicator_x: str,
    indicator_y: str,
    year: int,
) -> Tuple[pd.DataFrame, float]:
    """
    Build data for cross-indicator scatter / correlation analysis.

    Returns:
        Tuple of (merged DataFrame for scatter, Pearson r).
        If insufficient data, returns (empty_df, NaN).
    """
    df_x = df[
        (df["Indicator"] == indicator_x) & (df["Year"] == year)
    ][["CountryCode", "Value", "Continent"]].copy()
    df_x = df_x.rename(columns={"Value": "Value_X"})

    df_y = df[
        (df["Indicator"] == indicator_y) & (df["Year"] == year)
    ][["CountryCode", "Value"]].copy()
    df_y = df_y.rename(columns={"Value": "Value_Y"})

    # De-duplicate to one row per country (use 'Both sexes' if available)
    full_subset = df[df["Year"] == year]
    if "Both sexes" in full_subset["Gender"].values:
        both_sex = full_subset[full_subset["Gender"] == "Both sexes"]
        name_map = both_sex[["CountryCode", "Country"]].drop_duplicates()
    else:
        name_map = full_subset[["CountryCode", "Country"]].drop_duplicates()

    merged = df_x.merge(df_y, on="CountryCode", how="inner")
    merged = merged.merge(name_map, on="CountryCode", how="left")
    merged = merged.dropna(subset=["Value_X", "Value_Y"])

    if len(merged) < 3:
        return pd.DataFrame(), float("nan")

    pearson_r = float(merged["Value_X"].corr(merged["Value_Y"]))
    return merged, pearson_r


def build_country_profile(
    df: pd.DataFrame,
    country_code: str,
) -> pd.DataFrame:
    """
    Build a time-series profile for a single country across all indicators.
    """
    subset = df[df["CountryCode"] == country_code].copy()
    if subset.empty:
        return subset
    # Use 'Both sexes' where available
    if "Both sexes" in subset["Gender"].values:
        subset = subset[subset["Gender"] == "Both sexes"]
    return subset.sort_values(["Indicator", "Year"])


# ============================================================
# Data Quality
# ============================================================


def compute_quality_report(df: pd.DataFrame) -> Dict[str, Any]:
    """Generate a data quality report for the given DataFrame."""
    if df.empty:
        return {"overall_score": 0, "error": "No data"}
    report = DataQualityReport(df)
    return report.generate_full_report()


# ============================================================
# Metadata / Freshness
# ============================================================


def get_data_source_metadata(
    db_metadata: Dict[str, Any],
    df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Build a metadata dict describing the data source and freshness.

    Used by the dashboard to display source information.
    """
    year_min = int(df["Year"].min()) if not df.empty else None
    year_max = int(df["Year"].max()) if not df.empty else None

    return {
        "source": "World Health Organization — Global Health Observatory (GHO)",
        "api": WHO_API_BASE_URL,
        "extraction_date": db_metadata.get("extraction_date"),
        "db_last_modified": db_metadata.get("loaded_at"),
        "year_range": f"{year_min}–{year_max}" if year_min and year_max else "N/A",
        "total_records": db_metadata.get("row_count", 0),
        "db_path": db_metadata.get("db_path"),
        "status": db_metadata.get("status", "unknown"),
    }


# ============================================================
# Data Summary
# ============================================================


def build_data_summary(
    df: pd.DataFrame,
    metadata: Dict[str, Any],
) -> str:
    """
    Build a human-readable text summary of the current dataset.

    This is displayed before visualizations so users understand what they see.
    """
    if df.empty:
        return "No data available."

    n_records = len(df)
    n_countries = df["CountryCode"].nunique()
    n_indicators = df["Indicator"].nunique()
    year_min = int(df["Year"].min())
    year_max = int(df["Year"].max())
    indicators_list = ", ".join(
        indicator_short_name(i) for i in sorted(df["Indicator"].unique())
    )

    lines = [
        f"**{n_records:,} records** across **{n_countries} countries**",
        f"**{n_indicators} indicators:** {indicators_list}",
        f"**Years:** {year_min}–{year_max}",
    ]

    extraction = metadata.get("extraction_date")
    if extraction:
        lines.append(f"**Last extraction:** {extraction}")

    return "  ·  ".join(lines)


# ============================================================
# CSV Export Helper
# ============================================================


def build_export_csv(df: pd.DataFrame) -> bytes:
    """Return filtered data as UTF-8 CSV bytes for download."""
    return df.to_csv(index=False).encode("utf-8")
