"""
Data quality monitoring for WHO health indicator data.

Provides comprehensive data quality checks, summary statistics, and
quality reports for the ETL pipeline and dashboard.

Quality report includes:
- Row count
- Country count
- Year range
- Missing-value count
- Duplicate count
- Invalid-value count
- Unmapped country count
- Indicator coverage
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..etl.metadata import COUNTRY_CONTINENT_MAP
from ..utils.config import setup_logging

logger = setup_logging(__name__)


class DataQualityReport:
    """
    Generates comprehensive data quality reports for WHO health data.

    Tracks data completeness, consistency, accuracy, and timeliness
    metrics across the dataset.
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def generate_full_report(self) -> Dict[str, Any]:
        """Generate a complete data quality report."""
        report = {
            "generated_at": self.timestamp,
            "overview": self._get_overview(),
            "completeness": self._assess_completeness(),
            "consistency": self._assess_consistency(),
            "accuracy": self._assess_accuracy(),
            "indicator_summary": self._get_indicator_summary(),
            "indicator_coverage": self._get_indicator_coverage(),
            "temporal_coverage": self._assess_temporal_coverage(),
            "geographic_coverage": self._assess_geographic_coverage(),
            "unmapped_countries": self._get_unmapped_countries(),
            "overall_score": self._calculate_overall_score(),
        }

        logger.info(
            "Data quality report generated. Overall score: %.1f/100",
            report["overall_score"],
        )
        return report

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def _get_overview(self) -> Dict[str, Any]:
        return {
            "total_rows": len(self.df),
            "total_columns": len(self.df.columns),
            "memory_usage_mb": round(self.df.memory_usage(deep=True).sum() / 1024**2, 2) if not self.df.empty else 0,
            "indicators": self.df["Indicator"].nunique() if "Indicator" in self.df.columns else 0,
            "countries": self.df["CountryCode"].nunique() if "CountryCode" in self.df.columns else 0,
            "year_range": (
                int(self.df["Year"].min()) if "Year" in self.df.columns and not self.df.empty else None,
                int(self.df["Year"].max()) if "Year" in self.df.columns and not self.df.empty else None,
            ),
        }

    # ------------------------------------------------------------------
    # Completeness
    # ------------------------------------------------------------------

    def _assess_completeness(self) -> Dict[str, Any]:
        completeness: Dict[str, Any] = {}
        for col in self.df.columns:
            null_count = int(self.df[col].isna().sum())
            null_pct = round(null_count / len(self.df) * 100, 2) if len(self.df) > 0 else 0
            completeness[col] = {
                "null_count": null_count,
                "null_percentage": null_pct,
                "completeness_score": round(100 - null_pct, 2),
            }

        total_cells = len(self.df) * len(self.df.columns)
        total_nulls = int(self.df.isna().sum().sum())
        overall = round((1 - total_nulls / total_cells) * 100, 2) if total_cells > 0 else 0

        return {
            "overall_completeness_pct": overall,
            "total_null_cells": total_nulls,
            "per_column": completeness,
        }

    # ------------------------------------------------------------------
    # Consistency (duplicates)
    # ------------------------------------------------------------------

    def _assess_consistency(self) -> Dict[str, Any]:
        dup_count = int(self.df.duplicated().sum())

        type_issues: List[str] = []
        if "Value" in self.df.columns:
            non_numeric = self.df["Value"].apply(
                lambda x: not isinstance(x, (int, float, np.integer, np.floating))
            ).sum()
            if non_numeric > 0:
                type_issues.append(f"Value column has {non_numeric} non-numeric entries")

        if "Year" in self.df.columns:
            non_int = self.df["Year"].apply(
                lambda x: not isinstance(x, (int, np.integer))
            ).sum()
            if non_int > 0:
                type_issues.append(f"Year column has {non_int} non-integer entries")

        return {
            "duplicate_rows": dup_count,
            "duplicate_pct": round(dup_count / len(self.df) * 100, 2) if len(self.df) > 0 else 0,
            "type_issues": type_issues,
            "is_consistent": dup_count == 0 and len(type_issues) == 0,
        }

    # ------------------------------------------------------------------
    # Accuracy (invalid values + outliers)
    # ------------------------------------------------------------------

    def _assess_accuracy(self) -> Dict[str, Any]:
        issues: List[str] = []
        invalid_count = 0

        if "Value" in self.df.columns and "Indicator" in self.df.columns:
            # Count invalid values (NaN, inf)
            if not self.df.empty:
                invalid_count = int(
                    self.df["Value"].isna().sum() + np.isinf(self.df["Value"].dropna()).sum()
                )

            for indicator in self.df["Indicator"].unique():
                subset = self.df[self.df["Indicator"] == indicator]
                values = subset["Value"].dropna()
                if values.empty:
                    continue

                q1 = values.quantile(0.25)
                q3 = values.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 3 * iqr
                upper = q3 + 3 * iqr
                outliers = int(((values < lower) | (values > upper)).sum())
                if outliers > 0:
                    issues.append(
                        f"{indicator}: {outliers} potential outliers (outside [{lower:.2f}, {upper:.2f}])"
                    )

        return {
            "issues": issues,
            "invalid_value_count": invalid_count,
            "is_accurate": len(issues) == 0 and invalid_count == 0,
        }

    # ------------------------------------------------------------------
    # Indicator summary
    # ------------------------------------------------------------------

    def _get_indicator_summary(self) -> List[Dict[str, Any]]:
        if "Indicator" not in self.df.columns or "Value" not in self.df.columns:
            return []

        summaries: List[Dict[str, Any]] = []
        for indicator in self.df["Indicator"].unique():
            subset = self.df[self.df["Indicator"] == indicator]
            values = subset["Value"].dropna()
            summaries.append(
                {
                    "indicator": str(indicator),
                    "row_count": len(subset),
                    "country_count": subset["CountryCode"].nunique() if "CountryCode" in subset.columns else 0,
                    "year_count": subset["Year"].nunique() if "Year" in subset.columns else 0,
                    "value_mean": round(float(values.mean()), 4) if len(values) > 0 else None,
                    "value_min": round(float(values.min()), 4) if len(values) > 0 else None,
                    "value_max": round(float(values.max()), 4) if len(values) > 0 else None,
                    "value_std": round(float(values.std()), 4) if len(values) > 0 else None,
                    "null_count": int(subset["Value"].isna().sum()),
                }
            )
        return summaries

    # ------------------------------------------------------------------
    # Indicator coverage
    # ------------------------------------------------------------------

    def _get_indicator_coverage(self) -> Dict[str, Any]:
        """
        Compute indicator coverage: for each indicator, what fraction of
        countries × years have data.
        """
        if self.df.empty or "Indicator" not in self.df.columns:
            return {"indicators": {}, "overall_coverage_pct": 0.0}

        all_countries = self.df["CountryCode"].nunique()
        all_years = self.df["Year"].nunique()
        max_possible = all_countries * all_years

        coverage: Dict[str, float] = {}
        if max_possible > 0:
            for indicator in self.df["Indicator"].unique():
                subset = self.df[self.df["Indicator"] == indicator]
                # Count unique country-year pairs
                if "CountryCode" in subset.columns and "Year" in subset.columns:
                    actual = subset[["CountryCode", "Year"]].drop_duplicates().shape[0]
                    coverage[str(indicator)] = round(actual / max_possible * 100, 1)
                else:
                    coverage[str(indicator)] = 0.0

        overall = round(sum(coverage.values()) / len(coverage), 1) if coverage else 0.0
        return {"indicators": coverage, "overall_coverage_pct": overall}

    # ------------------------------------------------------------------
    # Temporal coverage
    # ------------------------------------------------------------------

    def _assess_temporal_coverage(self) -> Dict[str, Any]:
        if "Year" not in self.df.columns or self.df.empty:
            return {"years_covered": 0, "year_gaps": [], "year_range": (None, None), "has_gaps": False}

        years = sorted(self.df["Year"].dropna().unique())
        expected = set(range(int(min(years)), int(max(years)) + 1))
        actual = set(int(y) for y in years)
        gaps = sorted(expected - actual)

        return {
            "years_covered": len(years),
            "year_range": (int(min(years)), int(max(years))),
            "year_gaps": [int(y) for y in gaps],
            "has_gaps": len(gaps) > 0,
        }

    # ------------------------------------------------------------------
    # Geographic coverage
    # ------------------------------------------------------------------

    def _assess_geographic_coverage(self) -> Dict[str, Any]:
        if "CountryCode" not in self.df.columns:
            return {"countries": 0, "continents": 0, "has_aggregate_records": False, "expected_countries": 194}

        countries = self.df["CountryCode"].nunique()
        continents = self.df["Continent"].nunique() if "Continent" in self.df.columns else 0
        has_aggregates = bool(self.df["CountryCode"].isin(["GLOBAL", "WORLD"]).any())

        return {
            "countries": countries,
            "continents": continents,
            "has_aggregate_records": has_aggregates,
            "expected_countries": 194,
        }

    # ------------------------------------------------------------------
    # Unmapped countries
    # ------------------------------------------------------------------

    def _get_unmapped_countries(self) -> Dict[str, Any]:
        """
        Count country codes that are not in the ISO 3166-1 mapping
        (i.e., continent = 'Unknown').
        """
        if "CountryCode" not in self.df.columns:
            return {"count": 0, "codes": []}

        if "Continent" in self.df.columns:
            unmapped = self.df[self.df["Continent"].isin(["Unknown", "nan", ""])]["CountryCode"].unique()
        else:
            unmapped = [
                c for c in self.df["CountryCode"].unique()
                if c not in COUNTRY_CONTINENT_MAP
            ]

        unmapped_list = sorted(str(c) for c in unmapped)
        return {"count": len(unmapped_list), "codes": unmapped_list}

    # ------------------------------------------------------------------
    # Overall score
    # ------------------------------------------------------------------

    def _calculate_overall_score(self) -> float:
        scores: List[tuple] = []

        completeness = self._assess_completeness()
        scores.append(("completeness", completeness["overall_completeness_pct"], 0.35))

        consistency = self._assess_consistency()
        consistency_score = 100 if consistency["is_consistent"] else max(0, 100 - consistency["duplicate_pct"] * 10)
        scores.append(("consistency", consistency_score, 0.25))

        coverage = self._assess_geographic_coverage()
        coverage_score = min(100, coverage["countries"] / coverage["expected_countries"] * 100)
        scores.append(("coverage", coverage_score, 0.25))

        accuracy = self._assess_accuracy()
        accuracy_score = 100 if accuracy["is_accurate"] else max(0, 100 - accuracy["invalid_value_count"] * 0.1)
        scores.append(("accuracy", accuracy_score, 0.15))

        return round(sum(s * w for _, s, w in scores), 1)

    # ------------------------------------------------------------------
    # Markdown export
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Generate a markdown-formatted quality report."""
        r = self.generate_full_report()

        lines = [
            "# WHO Health Data Quality Report",
            f"**Generated:** {r['generated_at']}",
            f"**Overall Score:** {r['overall_score']}/100",
            "",
            "## Dataset Overview",
            f"- Total rows: {r['overview']['total_rows']:,}",
            f"- Indicators: {r['overview']['indicators']}",
            f"- Countries: {r['overview']['countries']}",
            f"- Year range: {r['overview']['year_range'][0]}-{r['overview']['year_range'][1]}",
            f"- Memory usage: {r['overview']['memory_usage_mb']:.2f} MB",
            "",
            "## Completeness",
            f"- Overall: {r['completeness']['overall_completeness_pct']}%",
            f"- Total null cells: {r['completeness']['total_null_cells']:,}",
            "",
            "## Consistency",
            f"- Duplicate rows: {r['consistency']['duplicate_rows']}",
            f"- Type issues: {len(r['consistency']['type_issues'])}",
            "",
            "## Accuracy",
            f"- Invalid values: {r['accuracy']['invalid_value_count']}",
            f"- Outlier issues: {len(r['accuracy']['issues'])}",
            "",
            "## Geographic Coverage",
            f"- Countries: {r['geographic_coverage']['countries']}",
            f"- Continents: {r['geographic_coverage']['continents']}",
            f"- Unmapped countries: {r['unmapped_countries']['count']} ({', '.join(r['unmapped_countries']['codes'][:5])}{'...' if len(r['unmapped_countries']['codes']) > 5 else ''})",
            "",
            "## Temporal Coverage",
            f"- Years covered: {r['temporal_coverage']['years_covered']}",
            f"- Year range: {r['temporal_coverage']['year_range'][0]}-{r['temporal_coverage']['year_range'][1]}",
            f"- Year gaps: {r['temporal_coverage']['year_gaps'] if r['temporal_coverage']['has_gaps'] else 'None'}",
            "",
            "## Indicator Coverage",
            f"- Overall coverage: {r['indicator_coverage']['overall_coverage_pct']}%",
            "",
            "## Indicator Summary",
            "| Indicator | Rows | Countries | Mean | Min | Max |",
            "|-----------|------|-----------|------|-----|-----|",
        ]

        for ind in r["indicator_summary"]:
            lines.append(
                f"| {ind['indicator']} | {ind['row_count']:,} | "
                f"{ind['country_count']} | {ind['value_mean']} | "
                f"{ind['value_min']} | {ind['value_max']} |"
            )

        return "\n".join(lines)
