"""
Tests for the metadata/normalization module.
"""

import pandas as pd

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.etl.metadata import (
    get_country_name,
    get_continent,
    normalize_geography,
    get_country_metadata_df,
    COUNTRY_CONTINENT_MAP,
    COUNTRY_NAMES
)


class TestCountryMetadata:
    """Tests for country metadata functions."""

    def test_get_country_name(self):
        """Should return correct country name for known codes."""
        assert get_country_name('USA') == 'United States'
        assert get_country_name('GBR') == 'United Kingdom'
        assert get_country_name('CHN') == 'China'
        assert get_country_name('BRA') == 'Brazil'

    def test_get_country_name_unknown(self):
        """Should return code itself for unknown codes."""
        result = get_country_name('XXX')
        assert result == 'XXX'

    def test_get_continent(self):
        """Should return correct continent for known codes."""
        assert get_continent('USA') == 'Americas'
        assert get_continent('GBR') == 'Europe'
        assert get_continent('CHN') == 'Asia'
        assert get_continent('NGA') == 'Africa'
        assert get_continent('AUS') == 'Oceania'

    def test_get_continent_unknown(self):
        """Should return 'Unknown' for unknown codes."""
        assert get_continent('XXX') == 'Unknown'

    def test_all_countries_have_continents(self):
        """All countries in COUNTRY_NAMES should have continent mapping."""
        for code in COUNTRY_NAMES:
            continent = COUNTRY_CONTINENT_MAP.get(code)
            assert continent is not None, f"Missing continent for {code}"

    def test_normalize_geography(self):
        """Should add Country and Continent columns."""
        df = pd.DataFrame({
            'CountryCode': ['USA', 'GBR', 'NGA', 'XXX'],
            'Value': [78.5, 81.0, 55.0, 70.0]
        })

        result = normalize_geography(df)

        assert 'Country' in result.columns
        assert 'Continent' in result.columns
        assert result[result['CountryCode'] == 'USA']['Country'].iloc[0] == 'United States'
        assert result[result['CountryCode'] == 'USA']['Continent'].iloc[0] == 'Americas'
        assert result[result['CountryCode'] == 'XXX']['Continent'].iloc[0] == 'Unknown'

    def test_get_country_metadata_df(self):
        """Should return complete metadata DataFrame."""
        df = get_country_metadata_df()

        assert 'CountryCode' in df.columns
        assert 'Country' in df.columns
        assert 'Continent' in df.columns
        assert len(df) == len(COUNTRY_NAMES)
        assert len(df) > 150  # Should have at least 150 countries
