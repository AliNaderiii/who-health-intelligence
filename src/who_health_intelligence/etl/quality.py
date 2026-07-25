"""
Data quality monitoring for WHO health indicator data.

Provides comprehensive data quality checks, summary statistics, and
quality reports for the ETL pipeline and dashboard.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from ..utils.config import setup_logging

logger = setup_logging(__name__)


class DataQualityReport:
    """
    Generates comprehensive data quality reports for WHO health data.
    
    Tracks data completeness, consistency, accuracy, and timeliness
    metrics across the dataset.
    """
    
    def __init__(self, df: pd.DataFrame):
        """
        Initialize with a DataFrame to analyze.
        
        Args:
            df: The DataFrame to generate quality metrics for
        """
        self.df = df
        self.timestamp = datetime.utcnow().isoformat()
        self.report: Dict[str, Any] = {}
    
    def generate_full_report(self) -> Dict[str, Any]:
        """
        Generate a complete data quality report.
        
        Returns:
            Dictionary containing all quality metrics and assessments
        """
        self.report = {
            'generated_at': self.timestamp,
            'overview': self._get_overview(),
            'completeness': self._assess_completeness(),
            'consistency': self._assess_consistency(),
            'accuracy': self._assess_accuracy(),
            'indicator_summary': self._get_indicator_summary(),
            'temporal_coverage': self._assess_temporal_coverage(),
            'geographic_coverage': self._assess_geographic_coverage(),
            'overall_score': self._calculate_overall_score()
        }
        
        logger.info(
            f"Data quality report generated. Overall score: "
            f"{self.report['overall_score']:.1f}/100"
        )
        
        return self.report
    
    def _get_overview(self) -> Dict[str, Any]:
        """Get basic dataset overview metrics."""
        return {
            'total_rows': len(self.df),
            'total_columns': len(self.df.columns),
            'memory_usage_mb': round(
                self.df.memory_usage(deep=True).sum() / 1024**2, 2
            ),
            'indicators': self.df['Indicator'].nunique() if 'Indicator' in self.df.columns else 0,
            'countries': self.df['CountryCode'].nunique() if 'CountryCode' in self.df.columns else 0,
            'year_range': (
                int(self.df['Year'].min()) if 'Year' in self.df.columns else None,
                int(self.df['Year'].max()) if 'Year' in self.df.columns else None
            )
        }
    
    def _assess_completeness(self) -> Dict[str, Any]:
        """Assess data completeness (null rates, coverage gaps)."""
        completeness = {}
        
        for col in self.df.columns:
            null_count = int(self.df[col].isna().sum())
            null_pct = round(null_count / len(self.df) * 100, 2)
            completeness[col] = {
                'null_count': null_count,
                'null_percentage': null_pct,
                'completeness_score': round(100 - null_pct, 2)
            }
        
        # Overall completeness
        total_cells = len(self.df) * len(self.df.columns)
        total_nulls = int(self.df.isna().sum().sum())
        overall_completeness = round((1 - total_nulls / total_cells) * 100, 2) if total_cells > 0 else 0
        
        return {
            'overall_completeness_pct': overall_completeness,
            'total_null_cells': total_nulls,
            'per_column': completeness
        }
    
    def _assess_consistency(self) -> Dict[str, Any]:
        """Assess data consistency (duplicates, type consistency)."""
        dup_count = int(self.df.duplicated().sum())
        
        # Check for consistent data types per column
        type_issues = []
        if 'Value' in self.df.columns:
            non_numeric = self.df['Value'].apply(
                lambda x: not isinstance(x, (int, float, np.integer, np.floating))
            ).sum()
            if non_numeric > 0:
                type_issues.append(f"Value column has {non_numeric} non-numeric entries")
        
        if 'Year' in self.df.columns:
            non_int = self.df['Year'].apply(
                lambda x: not isinstance(x, (int, np.integer))
            ).sum()
            if non_int > 0:
                type_issues.append(f"Year column has {non_int} non-integer entries")
        
        return {
            'duplicate_rows': dup_count,
            'duplicate_pct': round(dup_count / len(self.df) * 100, 2) if len(self.df) > 0 else 0,
            'type_issues': type_issues,
            'is_consistent': dup_count == 0 and len(type_issues) == 0
        }
    
    def _assess_accuracy(self) -> Dict[str, Any]:
        """Assess data accuracy (value range checks, outlier detection)."""
        accuracy_issues = []
        
        if 'Value' in self.df.columns and 'Indicator' in self.df.columns:
            for indicator in self.df['Indicator'].unique():
                subset = self.df[self.df['Indicator'] == indicator]
                values = subset['Value'].dropna()
                
                if len(values) == 0:
                    continue
                
                # Basic outlier detection using IQR
                q1 = values.quantile(0.25)
                q3 = values.quantile(0.75)
                iqr = q3 - q1
                lower_bound = q1 - 3 * iqr
                upper_bound = q3 + 3 * iqr
                
                outliers = ((values < lower_bound) | (values > upper_bound)).sum()
                if outliers > 0:
                    accuracy_issues.append(
                        f"{indicator}: {outliers} potential outliers "
                        f"(outside [{lower_bound:.2f}, {upper_bound:.2f}])"
                    )
        
        return {
            'issues': accuracy_issues,
            'is_accurate': len(accuracy_issues) == 0
        }
    
    def _get_indicator_summary(self) -> List[Dict[str, Any]]:
        """Get per-indicator summary statistics."""
        if 'Indicator' not in self.df.columns or 'Value' not in self.df.columns:
            return []
        
        summaries = []
        for indicator in self.df['Indicator'].unique():
            subset = self.df[self.df['Indicator'] == indicator]
            values = subset['Value'].dropna()
            
            summary = {
                'indicator': str(indicator),
                'row_count': len(subset),
                'country_count': subset['CountryCode'].nunique() if 'CountryCode' in subset.columns else 0,
                'year_count': subset['Year'].nunique() if 'Year' in subset.columns else 0,
                'value_mean': round(float(values.mean()), 4) if len(values) > 0 else None,
                'value_min': round(float(values.min()), 4) if len(values) > 0 else None,
                'value_max': round(float(values.max()), 4) if len(values) > 0 else None,
                'value_std': round(float(values.std()), 4) if len(values) > 0 else None,
                'null_count': int(subset['Value'].isna().sum())
            }
            summaries.append(summary)
        
        return summaries
    
    def _assess_temporal_coverage(self) -> Dict[str, Any]:
        """Assess temporal coverage and gaps."""
        if 'Year' not in self.df.columns:
            return {'years_covered': 0, 'gaps': []}
        
        years = sorted(self.df['Year'].unique())
        expected_years = set(range(min(years), max(years) + 1))
        actual_years = set(years)
        gaps = sorted(expected_years - actual_years)
        
        return {
            'years_covered': len(years),
            'year_range': (int(min(years)), int(max(years))),
            'year_gaps': [int(y) for y in gaps],
            'has_gaps': len(gaps) > 0
        }
    
    def _assess_geographic_coverage(self) -> Dict[str, Any]:
        """Assess geographic coverage."""
        if 'CountryCode' not in self.df.columns:
            return {'countries': 0, 'continents': 0}
        
        countries = self.df['CountryCode'].nunique()
        continents = self.df['Continent'].nunique() if 'Continent' in self.df.columns else 0
        
        # Check for 'GLOBAL' or regional aggregates
        has_aggregates = self.df['CountryCode'].isin(['GLOBAL', 'WORLD']).any()
        
        return {
            'countries': countries,
            'continents': continents,
            'has_aggregate_records': has_aggregates,
            'expected_countries': 194  # WHO member states
        }
    
    def _calculate_overall_score(self) -> float:
        """Calculate an overall data quality score (0-100)."""
        scores = []
        
        # Completeness score (40% weight)
        completeness = self._assess_completeness()
        scores.append(('completeness', completeness['overall_completeness_pct'], 0.4))
        
        # Consistency score (30% weight)
        consistency = self._assess_consistency()
        consistency_score = 100 if consistency['is_consistent'] else max(0, 100 - consistency['duplicate_pct'] * 10)
        scores.append(('consistency', consistency_score, 0.3))
        
        # Coverage score (30% weight)
        coverage = self._assess_geographic_coverage()
        coverage_score = min(100, coverage['countries'] / coverage['expected_countries'] * 100)
        scores.append(('coverage', coverage_score, 0.3))
        
        overall = sum(score * weight for _, score, weight in scores)
        return round(overall, 1)
    
    def to_markdown(self) -> str:
        """Generate a markdown-formatted quality report."""
        report = self.generate_full_report()
        
        lines = [
            "# WHO Health Data Quality Report",
            f"**Generated:** {report['generated_at']}",
            f"**Overall Score:** {report['overall_score']}/100",
            "",
            "## Dataset Overview",
            f"- Total rows: {report['overview']['total_rows']:,}",
            f"- Indicators: {report['overview']['indicators']}",
            f"- Countries: {report['overview']['countries']}",
            f"- Year range: {report['overview']['year_range'][0]}-{report['overview']['year_range'][1]}",
            f"- Memory usage: {report['overview']['memory_usage_mb']:.2f} MB",
            "",
            "## Completeness",
            f"- Overall: {report['completeness']['overall_completeness_pct']}%",
            f"- Total null cells: {report['completeness']['total_null_cells']:,}",
            "",
            "## Consistency",
            f"- Duplicate rows: {report['consistency']['duplicate_rows']}",
            f"- Type issues: {len(report['consistency']['type_issues'])}",
            "",
            "## Geographic Coverage",
            f"- Countries: {report['geographic_coverage']['countries']}",
            f"- Continents: {report['geographic_coverage']['continents']}",
            "",
            "## Temporal Coverage",
            f"- Years covered: {report['temporal_coverage']['years_covered']}",
            f"- Year range: {report['temporal_coverage']['year_range'][0]}-{report['temporal_coverage']['year_range'][1]}",
            f"- Year gaps: {report['temporal_coverage']['year_gaps'] if report['temporal_coverage']['has_gaps'] else 'None'}",
            "",
            "## Indicator Summary",
            "| Indicator | Rows | Countries | Mean | Min | Max |",
            "|-----------|------|-----------|------|-----|-----|"
        ]
        
        for ind in report['indicator_summary']:
            lines.append(
                f"| {ind['indicator']} | {ind['row_count']:,} | "
                f"{ind['country_count']} | {ind['value_mean']} | "
                f"{ind['value_min']} | {ind['value_max']} |"
            )
        
        return '\n'.join(lines)
