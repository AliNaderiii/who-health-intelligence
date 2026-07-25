"""
Reusable descriptive analytics functions for WHO health indicator data.

All functions return tidy pandas DataFrames suitable for Plotly, Streamlit, and
notebook use. These utilities provide descriptive epidemiological analytics only;
they do not estimate causal effects and should not be presented as prediction or
medical decision-support outputs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

VALUE_COLUMN = "Value"
COUNTRY_COLUMN = "CountryCode"
YEAR_COLUMN = "Year"
INDICATOR_COLUMN = "Indicator"
GENDER_COLUMN = "Gender"
CONTINENT_COLUMN = "Continent"
POPULATION_COLUMN = "Population"

AGGREGATION_METADATA_COLUMNS = [
    "UnitOfAnalysis",
    "WeightingMethod",
    "MissingDataBehavior",
    "AnalysisType",
]


def _empty(columns: Sequence[str]) -> pd.DataFrame:
    """Return an empty DataFrame with a stable column order."""
    return pd.DataFrame(columns=list(columns))


def _ensure_columns(df: pd.DataFrame, required: Sequence[str]) -> None:
    """Raise ValueError if required columns are missing."""
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _filter_common(
    df: pd.DataFrame,
    indicators: Optional[Sequence[str]] = None,
    years: Optional[Sequence[int] | Tuple[int, int]] = None,
    gender: Optional[str] = "Both sexes",
) -> pd.DataFrame:
    """Apply standard indicator/year/gender filters without mutating input."""
    filtered = df.copy()

    if indicators is not None and INDICATOR_COLUMN in filtered.columns:
        filtered = filtered[filtered[INDICATOR_COLUMN].isin(indicators)]

    if years is not None and YEAR_COLUMN in filtered.columns:
        if isinstance(years, tuple) and len(years) == 2:
            filtered = filtered[(filtered[YEAR_COLUMN] >= years[0]) & (filtered[YEAR_COLUMN] <= years[1])]
        elif isinstance(years, (int, np.integer)):
            filtered = filtered[filtered[YEAR_COLUMN] == int(years)]
        else:
            filtered = filtered[filtered[YEAR_COLUMN].isin(list(years))]

    if gender is not None and GENDER_COLUMN in filtered.columns:
        gender_subset = filtered[filtered[GENDER_COLUMN] == gender]
        if not gender_subset.empty:
            filtered = gender_subset

    return filtered.copy()


def _add_metadata(
    df: pd.DataFrame,
    *,
    unit: str,
    weighting: str,
    missing: str,
    analysis_type: str = "Descriptive",
) -> pd.DataFrame:
    """Attach explicit interpretation metadata to an analytical DataFrame."""
    result = df.copy()
    result["UnitOfAnalysis"] = unit
    result["WeightingMethod"] = weighting
    result["MissingDataBehavior"] = missing
    result["AnalysisType"] = analysis_type
    return result


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    """Compute a finite weighted mean, returning NaN if weights are unusable."""
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce")
    valid = numeric_values.notna() & numeric_weights.notna() & np.isfinite(numeric_values) & np.isfinite(numeric_weights) & (numeric_weights > 0)
    if not valid.any():
        return float("nan")
    return float(np.average(numeric_values[valid], weights=numeric_weights[valid]))


def aggregate_country_level(
    df: pd.DataFrame,
    indicators: Optional[Sequence[str]] = None,
    years: Optional[Sequence[int] | Tuple[int, int]] = None,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Aggregate observations to one row per country, indicator, and year.

    Unit of analysis:
        Country-year-indicator.
    Weighting method:
        Unweighted arithmetic mean across duplicate rows within the same
        country-year-indicator after optional gender filtering. Each retained
        observation contributes equally.
    Missing data behavior:
        Rows with missing/non-numeric values are excluded from the mean. Groups
        with no valid numeric values are omitted.
    Descriptive or inferential:
        Descriptive only; no causal or predictive inference is performed.
    """
    required = [COUNTRY_COLUMN, YEAR_COLUMN, INDICATOR_COLUMN, value_column]
    _ensure_columns(df, required)

    filtered = _filter_common(df, indicators=indicators, years=years, gender=gender)
    if filtered.empty:
        return _empty([COUNTRY_COLUMN, "Country", CONTINENT_COLUMN, INDICATOR_COLUMN, YEAR_COLUMN, value_column, "RecordCount", *AGGREGATION_METADATA_COLUMNS])

    filtered[value_column] = pd.to_numeric(filtered[value_column], errors="coerce")
    filtered = filtered.dropna(subset=[value_column])
    if filtered.empty:
        return _empty([COUNTRY_COLUMN, "Country", CONTINENT_COLUMN, INDICATOR_COLUMN, YEAR_COLUMN, value_column, "RecordCount", *AGGREGATION_METADATA_COLUMNS])

    group_columns = [COUNTRY_COLUMN, INDICATOR_COLUMN, YEAR_COLUMN]
    optional_columns = [column for column in ["Country", CONTINENT_COLUMN] if column in filtered.columns]
    grouped = (
        filtered.groupby(group_columns, observed=False)
        .agg(
            **{
                value_column: (value_column, "mean"),
                "RecordCount": (value_column, "count"),
                **{column: (column, "first") for column in optional_columns},
            }
        )
        .reset_index()
    )

    ordered = [COUNTRY_COLUMN]
    if "Country" in grouped.columns:
        ordered.append("Country")
    if CONTINENT_COLUMN in grouped.columns:
        ordered.append(CONTINENT_COLUMN)
    ordered.extend([INDICATOR_COLUMN, YEAR_COLUMN, value_column, "RecordCount"])
    grouped = grouped[ordered].sort_values([INDICATOR_COLUMN, YEAR_COLUMN, COUNTRY_COLUMN]).reset_index(drop=True)
    return _add_metadata(
        grouped,
        unit="Country-year-indicator",
        weighting="Unweighted mean across retained records within each country-year-indicator",
        missing="Rows with missing/non-numeric values are excluded; empty groups are omitted",
    )


def aggregate_continent_level(
    df: pd.DataFrame,
    population_df: Optional[pd.DataFrame] = None,
    indicators: Optional[Sequence[str]] = None,
    years: Optional[Sequence[int] | Tuple[int, int]] = None,
    gender: Optional[str] = "Both sexes",
    weighting: str = "unweighted",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Aggregate country-level values to continent, indicator, and year.

    Unit of analysis:
        Continent-year-indicator, based on country-level records.
    Weighting method:
        ``unweighted`` gives each country one equal contribution. ``population``
        uses country-year population weights when ``population_df`` contains
        CountryCode, Year, and Population; countries without valid population
        weights are excluded from the weighted mean.
    Missing data behavior:
        Missing/non-numeric indicator values are excluded. For population
        weighting, missing/non-positive population weights are excluded and
        coverage counts are reported.
    Descriptive or inferential:
        Descriptive only; no causal or predictive inference is performed.
    """
    country = aggregate_country_level(df, indicators=indicators, years=years, gender=gender, value_column=value_column)
    if country.empty:
        return _empty([CONTINENT_COLUMN, INDICATOR_COLUMN, YEAR_COLUMN, value_column, "CountryCount", "RecordCount", *AGGREGATION_METADATA_COLUMNS])
    if CONTINENT_COLUMN not in country.columns:
        raise ValueError("Continent column is required for continent-level aggregation")

    country = country[~country[CONTINENT_COLUMN].isin(["Unknown", "nan", "", None])].copy()
    if country.empty:
        return _empty([CONTINENT_COLUMN, INDICATOR_COLUMN, YEAR_COLUMN, value_column, "CountryCount", "RecordCount", *AGGREGATION_METADATA_COLUMNS])

    weighting_norm = weighting.lower()
    group_columns = [CONTINENT_COLUMN, INDICATOR_COLUMN, YEAR_COLUMN]

    if weighting_norm == "population" and population_df is not None and not population_df.empty:
        _ensure_columns(population_df, [COUNTRY_COLUMN, YEAR_COLUMN, POPULATION_COLUMN])
        pop = population_df[[COUNTRY_COLUMN, YEAR_COLUMN, POPULATION_COLUMN]].copy()
        merged = country.merge(pop, on=[COUNTRY_COLUMN, YEAR_COLUMN], how="left")

        rows: List[Dict[str, Any]] = []
        for keys, group in merged.groupby(group_columns, observed=False):
            weighted_value = _weighted_mean(group[value_column], group[POPULATION_COLUMN])
            valid_weights = pd.to_numeric(group[POPULATION_COLUMN], errors="coerce")
            valid_weight_mask = valid_weights.notna() & np.isfinite(valid_weights) & (valid_weights > 0) & group[value_column].notna()
            rows.append(
                {
                    CONTINENT_COLUMN: keys[0],
                    INDICATOR_COLUMN: keys[1],
                    YEAR_COLUMN: keys[2],
                    value_column: weighted_value,
                    "CountryCount": int(group[COUNTRY_COLUMN].nunique()),
                    "WeightedCountryCount": int(valid_weight_mask.sum()),
                    "PopulationTotal": float(valid_weights[valid_weight_mask].sum()) if valid_weight_mask.any() else 0.0,
                    "RecordCount": int(group["RecordCount"].sum()) if "RecordCount" in group.columns else int(len(group)),
                }
            )
        result = pd.DataFrame(rows).dropna(subset=[value_column])
        result = result.sort_values([INDICATOR_COLUMN, YEAR_COLUMN, CONTINENT_COLUMN]).reset_index(drop=True)
        return _add_metadata(
            result,
            unit="Continent-year-indicator",
            weighting="Population-weighted by country-year Population",
            missing="Missing values and invalid/non-positive population weights are excluded from weighted means",
        )

    result = (
        country.groupby(group_columns, observed=False)
        .agg(
            **{
                value_column: (value_column, "mean"),
                "CountryCount": (COUNTRY_COLUMN, "nunique"),
                "RecordCount": ("RecordCount", "sum"),
            }
        )
        .reset_index()
        .sort_values([INDICATOR_COLUMN, YEAR_COLUMN, CONTINENT_COLUMN])
        .reset_index(drop=True)
    )
    return _add_metadata(
        result,
        unit="Continent-year-indicator",
        weighting="Unweighted country-level mean; each country contributes equally",
        missing="Countries with missing/non-numeric indicator values are excluded from means",
    )


def compute_unweighted_averages(
    df: pd.DataFrame,
    group_by: Sequence[str] = (INDICATOR_COLUMN, YEAR_COLUMN),
    indicators: Optional[Sequence[str]] = None,
    years: Optional[Sequence[int] | Tuple[int, int]] = None,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Compute unweighted averages for configurable groups.

    Unit of analysis:
        Country-level observations within each requested group.
    Weighting method:
        Unweighted arithmetic mean; each country-level value contributes equally
        regardless of population size.
    Missing data behavior:
        Missing/non-numeric values are excluded from the mean and counted in
        ``MissingValueCount``.
    Descriptive or inferential:
        Descriptive only; no causal, inferential, or predictive claim is made.
    """
    country = aggregate_country_level(df, indicators=indicators, years=years, gender=gender, value_column=value_column)
    if country.empty:
        return _empty([*group_by, "MeanValue", "MedianValue", "StdValue", "CountryCount", "MissingValueCount", *AGGREGATION_METADATA_COLUMNS])

    group_columns = [column for column in group_by if column in country.columns]
    if not group_columns:
        raise ValueError("At least one group_by column must exist in the data")

    result = (
        country.groupby(group_columns, observed=False)
        .agg(
            MeanValue=(value_column, "mean"),
            MedianValue=(value_column, "median"),
            StdValue=(value_column, "std"),
            MinValue=(value_column, "min"),
            MaxValue=(value_column, "max"),
            CountryCount=(COUNTRY_COLUMN, "nunique"),
            MissingValueCount=(value_column, lambda x: int(x.isna().sum())),
        )
        .reset_index()
    )
    return _add_metadata(
        result,
        unit="Country-level records grouped by " + ", ".join(group_columns),
        weighting="Unweighted country-level arithmetic mean",
        missing="Missing/non-numeric values are excluded from summary statistics",
    )


def compute_population_weighted_averages(
    df: pd.DataFrame,
    population_df: Optional[pd.DataFrame],
    group_by: Sequence[str] = (INDICATOR_COLUMN, YEAR_COLUMN),
    indicators: Optional[Sequence[str]] = None,
    years: Optional[Sequence[int] | Tuple[int, int]] = None,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Compute population-weighted averages when population data are available.

    Unit of analysis:
        Country-level observations within each requested group.
    Weighting method:
        Country-year values are weighted by ``Population`` from
        ``population_df``. If no population data are provided, an empty DataFrame
        is returned with the expected schema.
    Missing data behavior:
        Missing/non-numeric values and missing/non-positive population weights
        are excluded. ``CountryCount`` and ``WeightedCountryCount`` document
        coverage.
    Descriptive or inferential:
        Descriptive only; population weighting changes aggregation but does not
        imply causation or model-based inference.
    """
    output_columns = [*group_by, "WeightedMeanValue", "CountryCount", "WeightedCountryCount", "PopulationTotal", *AGGREGATION_METADATA_COLUMNS]
    if population_df is None or population_df.empty:
        return _empty(output_columns)

    _ensure_columns(population_df, [COUNTRY_COLUMN, YEAR_COLUMN, POPULATION_COLUMN])
    country = aggregate_country_level(df, indicators=indicators, years=years, gender=gender, value_column=value_column)
    if country.empty:
        return _empty(output_columns)

    merged = country.merge(population_df[[COUNTRY_COLUMN, YEAR_COLUMN, POPULATION_COLUMN]], on=[COUNTRY_COLUMN, YEAR_COLUMN], how="left")
    group_columns = [column for column in group_by if column in merged.columns]
    if not group_columns:
        raise ValueError("At least one group_by column must exist in the data")

    rows: List[Dict[str, Any]] = []
    for keys, group in merged.groupby(group_columns, observed=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        numeric_population = pd.to_numeric(group[POPULATION_COLUMN], errors="coerce")
        valid_mask = group[value_column].notna() & numeric_population.notna() & np.isfinite(numeric_population) & (numeric_population > 0)
        row = {column: value for column, value in zip(group_columns, keys)}
        row.update(
            {
                "WeightedMeanValue": _weighted_mean(group[value_column], group[POPULATION_COLUMN]),
                "CountryCount": int(group[COUNTRY_COLUMN].nunique()),
                "WeightedCountryCount": int(valid_mask.sum()),
                "PopulationTotal": float(numeric_population[valid_mask].sum()) if valid_mask.any() else 0.0,
            }
        )
        rows.append(row)

    result = pd.DataFrame(rows).dropna(subset=["WeightedMeanValue"])
    if not result.empty:
        result = result.sort_values(group_columns).reset_index(drop=True)
    return _add_metadata(
        result,
        unit="Country-level records grouped by " + ", ".join(group_columns),
        weighting="Population-weighted country-year mean using Population",
        missing="Missing values and invalid/non-positive population weights are excluded",
    )


def calculate_year_over_year_change(
    df: pd.DataFrame,
    group_columns: Sequence[str] = (COUNTRY_COLUMN, INDICATOR_COLUMN),
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Calculate year-over-year absolute and percent change.

    Unit of analysis:
        One time series per ``group_columns`` combination.
    Weighting method:
        No weighting is applied; changes are computed from observed values.
    Missing data behavior:
        Rows are sorted by year. Missing current or previous values yield missing
        change values; percent change is missing when previous value is zero.
    Descriptive or inferential:
        Descriptive temporal comparison only, not a forecast or causal estimate.
    """
    required = [YEAR_COLUMN, value_column, *group_columns]
    _ensure_columns(df, required)
    result = df.copy()
    result[value_column] = pd.to_numeric(result[value_column], errors="coerce")
    result = result.sort_values([*group_columns, YEAR_COLUMN]).reset_index(drop=True)
    result["PreviousValue"] = result.groupby(list(group_columns), observed=False)[value_column].shift(1)
    result["PreviousYear"] = result.groupby(list(group_columns), observed=False)[YEAR_COLUMN].shift(1)
    result["YoYChange"] = result[value_column] - result["PreviousValue"]
    result["YoYPercentChange"] = np.where(
        result["PreviousValue"].notna() & (result["PreviousValue"] != 0),
        (result["YoYChange"] / result["PreviousValue"]) * 100,
        np.nan,
    )
    return _add_metadata(
        result,
        unit="Time series row within each " + ", ".join(group_columns),
        weighting="No weighting; direct year-over-year difference",
        missing="Missing current/previous values produce missing change values",
    )


def calculate_trends(
    df: pd.DataFrame,
    group_columns: Sequence[str] = (COUNTRY_COLUMN, INDICATOR_COLUMN),
    value_column: str = VALUE_COLUMN,
    min_points: int = 3,
) -> pd.DataFrame:
    """
    Calculate simple linear trend summaries by group.

    Unit of analysis:
        One fitted descriptive line per ``group_columns`` combination.
    Weighting method:
        Unweighted ordinary least squares via ``numpy.polyfit``; each available
        year contributes equally.
    Missing data behavior:
        Missing/non-numeric values are excluded. Groups with fewer than
        ``min_points`` valid observations are omitted.
    Descriptive or inferential:
        Descriptive trend summary only. Slopes are not validated forecasts,
        causal effects, or clinical decision rules.
    """
    required = [YEAR_COLUMN, value_column, *group_columns]
    _ensure_columns(df, required)
    working = df.copy()
    working[value_column] = pd.to_numeric(working[value_column], errors="coerce")
    working[YEAR_COLUMN] = pd.to_numeric(working[YEAR_COLUMN], errors="coerce")
    working = working.dropna(subset=[YEAR_COLUMN, value_column])

    rows: List[Dict[str, Any]] = []
    for keys, group in working.groupby(list(group_columns), observed=False):
        if len(group) < min_points:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        x = group[YEAR_COLUMN].astype(float).to_numpy()
        y = group[value_column].astype(float).to_numpy()
        if len(np.unique(x)) < 2:
            continue
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        row = {column: value for column, value in zip(group_columns, keys)}
        row.update(
            {
                "StartYear": int(np.min(x)),
                "EndYear": int(np.max(x)),
                "ObservationCount": int(len(group)),
                "SlopePerYear": float(slope),
                "Intercept": float(intercept),
                "RSquared": float(r_squared) if not np.isnan(r_squared) else np.nan,
                "TrendDirection": "Increasing" if slope > 0 else "Decreasing" if slope < 0 else "Flat",
            }
        )
        rows.append(row)

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(list(group_columns)).reset_index(drop=True)
    return _add_metadata(
        result,
        unit="Grouped time series",
        weighting="Unweighted linear trend; each year contributes equally",
        missing=f"Missing values excluded; groups require at least {min_points} valid observations",
    )


def rank_countries(
    df: pd.DataFrame,
    indicator: str,
    year: int,
    top_n: Optional[int] = 20,
    ascending: bool = False,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Rank countries for a selected indicator and year.

    Unit of analysis:
        Country-year-indicator.
    Weighting method:
        No weighting; countries are ranked by their country-level value.
    Missing data behavior:
        Missing/non-numeric values are excluded before ranking.
    Descriptive or inferential:
        Descriptive ranking only; ranks do not imply causation or clinical
        decision value.
    """
    country = aggregate_country_level(df, indicators=[indicator], years=[year], gender=gender, value_column=value_column)
    if country.empty:
        return country
    ranked = country.dropna(subset=[value_column]).sort_values(value_column, ascending=ascending).reset_index(drop=True)
    if top_n is not None:
        ranked = ranked.head(top_n).copy()
    ranked.insert(0, "Rank", range(1, len(ranked) + 1))
    return _add_metadata(
        ranked,
        unit="Country-year-indicator",
        weighting="No weighting; direct ranking of country-level values",
        missing="Countries with missing/non-numeric values are excluded",
    )


def prepare_time_series(
    df: pd.DataFrame,
    indicator: str,
    group_by: Optional[Sequence[str]] = None,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Prepare time-series data for charts.

    Unit of analysis:
        Yearly country-level values, optionally grouped by additional columns
        such as Continent or CountryCode.
    Weighting method:
        Unweighted arithmetic summaries; each country-level value contributes
        equally within year/group.
    Missing data behavior:
        Missing/non-numeric values are excluded from summaries.
    Descriptive or inferential:
        Descriptive time-series preparation only.
    """
    group_by = list(group_by or [])
    country = aggregate_country_level(df, indicators=[indicator], gender=gender, value_column=value_column)
    if country.empty:
        return _empty([*group_by, YEAR_COLUMN, "MeanValue", "MedianValue", "StdValue", "P25", "P75", "CountryCount", *AGGREGATION_METADATA_COLUMNS])
    group_columns = [column for column in [*group_by, YEAR_COLUMN] if column in country.columns]
    result = (
        country.groupby(group_columns, observed=False)[value_column]
        .agg(
            MeanValue="mean",
            MedianValue="median",
            StdValue="std",
            P25=lambda x: x.quantile(0.25),
            P75=lambda x: x.quantile(0.75),
            CountryCount="count",
        )
        .reset_index()
        .sort_values(group_columns)
        .reset_index(drop=True)
    )
    return _add_metadata(
        result,
        unit="Year" + (" grouped by " + ", ".join(group_by) if group_by else ""),
        weighting="Unweighted country-level summaries",
        missing="Missing/non-numeric values are excluded from summaries",
    )


def compare_indicators(
    df: pd.DataFrame,
    indicators: Sequence[str],
    year: int,
    entity: str = COUNTRY_COLUMN,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Build a wide comparison table for multiple indicators.

    Unit of analysis:
        Entity-year row, where entity is typically CountryCode or Continent.
    Weighting method:
        Country-level values are unweighted. If comparing continents, values are
        first averaged using unweighted country means.
    Missing data behavior:
        Missing indicator values remain as NaN in the wide table so the
        dashboard can display incomplete coverage transparently.
    Descriptive or inferential:
        Descriptive comparison only; cross-indicator differences are not causal
        estimates.
    """
    if entity == CONTINENT_COLUMN:
        base = aggregate_continent_level(df, indicators=indicators, years=[year], gender=gender, weighting="unweighted", value_column=value_column)
    else:
        base = aggregate_country_level(df, indicators=indicators, years=[year], gender=gender, value_column=value_column)
    if base.empty:
        return pd.DataFrame()
    if entity not in base.columns:
        raise ValueError(f"Entity column '{entity}' is not available")

    index_columns = [entity]
    for optional in ["Country", CONTINENT_COLUMN, YEAR_COLUMN]:
        if optional in base.columns and optional not in index_columns and not (entity == CONTINENT_COLUMN and optional == CONTINENT_COLUMN):
            index_columns.append(optional)

    wide = base.pivot_table(index=index_columns, columns=INDICATOR_COLUMN, values=value_column, aggfunc="mean").reset_index()
    wide.columns.name = None
    return _add_metadata(
        wide,
        unit=f"{entity}-year",
        weighting="Unweighted values; continent comparisons use unweighted country means",
        missing="Missing indicator values are retained as NaN",
    )


def analyze_correlation(
    df: pd.DataFrame,
    indicator_x: str,
    indicator_y: str,
    year: int,
    entity: str = COUNTRY_COLUMN,
    gender: Optional[str] = "Both sexes",
    value_column: str = VALUE_COLUMN,
) -> pd.DataFrame:
    """
    Prepare paired indicator values and descriptive correlation statistics.

    Unit of analysis:
        Entity-year paired observations, usually countries in a selected year.
    Weighting method:
        Unweighted Pearson correlation; each paired entity contributes equally.
    Missing data behavior:
        Entities missing either indicator are excluded pairwise. At least three
        paired observations are required for a correlation coefficient.
    Descriptive or inferential:
        Descriptive association only. Correlation does not imply causation and
        this function must not be interpreted as a causal model.
    """
    comparison = compare_indicators(df, [indicator_x, indicator_y], year, entity=entity, gender=gender, value_column=value_column)
    output_columns = [entity, "Value_X", "Value_Y", "PearsonR", "PairCount", *AGGREGATION_METADATA_COLUMNS]
    if comparison.empty or indicator_x not in comparison.columns or indicator_y not in comparison.columns:
        return _empty(output_columns)

    paired = comparison.dropna(subset=[indicator_x, indicator_y]).copy()
    if paired.empty:
        return _empty(output_columns)
    paired = paired.rename(columns={indicator_x: "Value_X", indicator_y: "Value_Y"})
    pair_count = len(paired)
    pearson_r = float(paired["Value_X"].corr(paired["Value_Y"])) if pair_count >= 3 else np.nan
    paired["IndicatorX"] = indicator_x
    paired["IndicatorY"] = indicator_y
    paired["PearsonR"] = pearson_r
    paired["PairCount"] = pair_count
    paired.attrs["pearson_r"] = pearson_r
    paired.attrs["pair_count"] = pair_count
    return _add_metadata(
        paired,
        unit=f"{entity}-year paired indicators",
        weighting="Unweighted Pearson correlation; each paired entity contributes equally",
        missing="Pairwise deletion: entities missing either indicator are excluded",
        analysis_type="Descriptive association, not causation",
    )
