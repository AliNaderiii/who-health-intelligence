"""Tests for reusable analytics functions in src.analytics."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics import (
    aggregate_continent_level,
    aggregate_country_level,
    analyze_correlation,
    calculate_trends,
    calculate_year_over_year_change,
    compare_indicators,
    compute_population_weighted_averages,
    compute_unweighted_averages,
    prepare_time_series,
    rank_countries,
)


def sample_health_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CountryCode": ["USA", "USA", "GBR", "GBR", "FRA", "FRA", "USA", "GBR", "FRA", "USA", "GBR", "FRA"],
            "Country": ["United States", "United States", "United Kingdom", "United Kingdom", "France", "France", "United States", "United Kingdom", "France", "United States", "United Kingdom", "France"],
            "Continent": ["Americas", "Americas", "Europe", "Europe", "Europe", "Europe", "Americas", "Europe", "Europe", "Americas", "Europe", "Europe"],
            "Year": [2020, 2021, 2020, 2021, 2020, 2021, 2020, 2020, 2020, 2021, 2021, 2021],
            "Gender": ["Both sexes"] * 12,
            "Indicator": ["LIFE_EXPECTANCY", "LIFE_EXPECTANCY", "LIFE_EXPECTANCY", "LIFE_EXPECTANCY", "LIFE_EXPECTANCY", "LIFE_EXPECTANCY", "UHC_COVERAGE", "UHC_COVERAGE", "UHC_COVERAGE", "UHC_COVERAGE", "UHC_COVERAGE", "UHC_COVERAGE"],
            "Value": [78.0, 79.0, 81.0, 82.0, 82.0, 83.0, 85.0, 90.0, 88.0, 86.0, 91.0, np.nan],
        }
    )


def population_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CountryCode": ["USA", "GBR", "FRA", "USA", "GBR", "FRA"],
            "Year": [2020, 2020, 2020, 2021, 2021, 2021],
            "Population": [330_000_000, 67_000_000, 65_000_000, 331_000_000, 68_000_000, 66_000_000],
        }
    )


def assert_metadata_columns(df: pd.DataFrame) -> None:
    for column in ["UnitOfAnalysis", "WeightingMethod", "MissingDataBehavior", "AnalysisType"]:
        assert column in df.columns


def test_country_level_aggregation_returns_tidy_country_year_indicator_rows():
    result = aggregate_country_level(sample_health_df(), indicators=["LIFE_EXPECTANCY"], years=[2020])

    assert len(result) == 3
    assert set(["CountryCode", "Country", "Continent", "Indicator", "Year", "Value", "RecordCount"]).issubset(result.columns)
    assert result["UnitOfAnalysis"].eq("Country-year-indicator").all()
    assert_metadata_columns(result)


def test_continent_level_unweighted_aggregation():
    result = aggregate_continent_level(sample_health_df(), indicators=["LIFE_EXPECTANCY"], years=[2020])

    europe = result[(result["Continent"] == "Europe") & (result["Indicator"] == "LIFE_EXPECTANCY")].iloc[0]
    assert europe["Value"] == 81.5
    assert europe["CountryCount"] == 2
    assert "Unweighted" in europe["WeightingMethod"]


def test_unweighted_averages_exclude_missing_values():
    result = compute_unweighted_averages(sample_health_df(), indicators=["UHC_COVERAGE"], years=[2021])

    row = result.iloc[0]
    assert row["MeanValue"] == 88.5
    assert row["CountryCount"] == 2
    assert "Unweighted" in row["WeightingMethod"]


def test_population_weighted_averages_when_population_exists():
    result = compute_population_weighted_averages(
        sample_health_df(),
        population_df(),
        indicators=["LIFE_EXPECTANCY"],
        years=[2020],
    )

    assert not result.empty
    row = result.iloc[0]
    expected = np.average([78.0, 81.0, 82.0], weights=[330_000_000, 67_000_000, 65_000_000])
    assert row["WeightedMeanValue"] == expected
    assert row["WeightedCountryCount"] == 3
    assert "Population-weighted" in row["WeightingMethod"]


def test_population_weighted_averages_empty_without_population_data():
    result = compute_population_weighted_averages(sample_health_df(), None)

    assert result.empty
    assert "WeightedMeanValue" in result.columns


def test_year_over_year_change():
    country = aggregate_country_level(sample_health_df(), indicators=["LIFE_EXPECTANCY"])
    result = calculate_year_over_year_change(country)
    usa_2021 = result[(result["CountryCode"] == "USA") & (result["Year"] == 2021)].iloc[0]

    assert usa_2021["PreviousValue"] == 78.0
    assert usa_2021["YoYChange"] == 1.0
    assert round(usa_2021["YoYPercentChange"], 3) == round(1 / 78 * 100, 3)


def test_trend_calculations_are_descriptive():
    df = pd.concat(
        [
            sample_health_df(),
            pd.DataFrame(
                {
                    "CountryCode": ["USA", "GBR", "FRA"],
                    "Country": ["United States", "United Kingdom", "France"],
                    "Continent": ["Americas", "Europe", "Europe"],
                    "Year": [2022, 2022, 2022],
                    "Gender": ["Both sexes"] * 3,
                    "Indicator": ["LIFE_EXPECTANCY"] * 3,
                    "Value": [80.0, 83.0, 84.0],
                }
            ),
        ],
        ignore_index=True,
    )
    country = aggregate_country_level(df, indicators=["LIFE_EXPECTANCY"])
    result = calculate_trends(country)

    usa = result[(result["CountryCode"] == "USA") & (result["Indicator"] == "LIFE_EXPECTANCY")].iloc[0]
    assert usa["SlopePerYear"] > 0
    assert usa["TrendDirection"] == "Increasing"
    assert "Descriptive" in usa["AnalysisType"]


def test_country_ranking():
    result = rank_countries(sample_health_df(), "LIFE_EXPECTANCY", 2020, top_n=2)

    assert result["Rank"].tolist() == [1, 2]
    assert result.iloc[0]["CountryCode"] == "FRA"
    assert_metadata_columns(result)


def test_time_series_preparation():
    result = prepare_time_series(sample_health_df(), "LIFE_EXPECTANCY")

    assert result["Year"].tolist() == [2020, 2021]
    assert set(["MeanValue", "MedianValue", "StdValue", "P25", "P75", "CountryCount"]).issubset(result.columns)
    assert result.loc[result["Year"] == 2020, "CountryCount"].iloc[0] == 3


def test_indicator_comparison():
    result = compare_indicators(sample_health_df(), ["LIFE_EXPECTANCY", "UHC_COVERAGE"], 2020)

    assert set(["CountryCode", "LIFE_EXPECTANCY", "UHC_COVERAGE"]).issubset(result.columns)
    assert len(result) == 3
    assert "causal" not in " ".join(result["AnalysisType"].astype(str)).lower()


def test_correlation_analysis_is_descriptive_not_causal():
    result = analyze_correlation(sample_health_df(), "LIFE_EXPECTANCY", "UHC_COVERAGE", 2020)

    assert len(result) == 3
    assert "PearsonR" in result.columns
    assert result["PairCount"].iloc[0] == 3
    assert "not causation" in result["AnalysisType"].iloc[0]
    assert np.isfinite(result.attrs["pearson_r"])
