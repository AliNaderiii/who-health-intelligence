"""
Country and continent metadata normalization.

Provides mapping between ISO 3166-1 alpha-3 country codes, country names,
and continent/region classifications. Supports WHO member state coverage.
"""

from typing import Dict, Optional
import pandas as pd

from ..utils.config import setup_logging

logger = setup_logging(__name__)


# ISO 3166-1 alpha-3 to continent mapping
# Source: Standard geographic classification
COUNTRY_CONTINENT_MAP: Dict[str, str] = {
    # Africa
    'DZA': 'Africa', 'AGO': 'Africa', 'BEN': 'Africa', 'BWA': 'Africa',
    'BFA': 'Africa', 'BDI': 'Africa', 'CPV': 'Africa', 'CMR': 'Africa',
    'CAF': 'Africa', 'TCD': 'Africa', 'COM': 'Africa', 'COG': 'Africa',
    'COD': 'Africa', 'CIV': 'Africa', 'DJI': 'Africa', 'EGY': 'Africa',
    'GNQ': 'Africa', 'ERI': 'Africa', 'SWZ': 'Africa', 'ETH': 'Africa',
    'GAB': 'Africa', 'GMB': 'Africa', 'GHA': 'Africa', 'GIN': 'Africa',
    'GNB': 'Africa', 'KEN': 'Africa', 'LSO': 'Africa', 'LBR': 'Africa',
    'LBY': 'Africa', 'MDG': 'Africa', 'MWI': 'Africa', 'MLI': 'Africa',
    'MRT': 'Africa', 'MUS': 'Africa', 'MAR': 'Africa', 'MOZ': 'Africa',
    'NAM': 'Africa', 'NER': 'Africa', 'NGA': 'Africa', 'RWA': 'Africa',
    'STP': 'Africa', 'SEN': 'Africa', 'SYC': 'Africa', 'SLE': 'Africa',
    'SOM': 'Africa', 'ZAF': 'Africa', 'SSD': 'Africa', 'SDN': 'Africa',
    'TZA': 'Africa', 'TGO': 'Africa', 'TUN': 'Africa', 'UGA': 'Africa',
    'ZMB': 'Africa', 'ZWE': 'Africa',
    
    # Americas
    'ATG': 'Americas', 'ARG': 'Americas', 'BHS': 'Americas', 'BRB': 'Americas',
    'BLZ': 'Americas', 'BOL': 'Americas', 'BRA': 'Americas', 'CAN': 'Americas',
    'CHL': 'Americas', 'COL': 'Americas', 'CRI': 'Americas', 'CUB': 'Americas',
    'DMA': 'Americas', 'DOM': 'Americas', 'ECU': 'Americas', 'SLV': 'Americas',
    'GRD': 'Americas', 'GTM': 'Americas', 'GUY': 'Americas', 'HTI': 'Americas',
    'HND': 'Americas', 'JAM': 'Americas', 'MEX': 'Americas', 'NIC': 'Americas',
    'PAN': 'Americas', 'PRY': 'Americas', 'PER': 'Americas', 'KNA': 'Americas',
    'LCA': 'Americas', 'VCT': 'Americas', 'SUR': 'Americas', 'TTO': 'Americas',
    'USA': 'Americas', 'URY': 'Americas', 'VEN': 'Americas',
    
    # Asia
    'AFG': 'Asia', 'ARM': 'Asia', 'AZE': 'Asia', 'BHR': 'Asia',
    'BGD': 'Asia', 'BTN': 'Asia', 'BRN': 'Asia', 'KHM': 'Asia',
    'CHN': 'Asia', 'CYP': 'Asia', 'PRK': 'Asia', 'GEO': 'Asia',
    'IND': 'Asia', 'IDN': 'Asia', 'IRN': 'Asia', 'IRQ': 'Asia',
    'ISR': 'Asia', 'JPN': 'Asia', 'JOR': 'Asia', 'KAZ': 'Asia',
    'KWT': 'Asia', 'KGZ': 'Asia', 'LAO': 'Asia', 'LBN': 'Asia',
    'MYS': 'Asia', 'MDV': 'Asia', 'MNG': 'Asia', 'MMR': 'Asia',
    'NPL': 'Asia', 'OMN': 'Asia', 'PAK': 'Asia', 'PHL': 'Asia',
    'QAT': 'Asia', 'KOR': 'Asia', 'SAU': 'Asia', 'SGP': 'Asia',
    'LKA': 'Asia', 'SYR': 'Asia', 'TJK': 'Asia', 'THA': 'Asia',
    'TLS': 'Asia', 'TUR': 'Asia', 'TKM': 'Asia', 'ARE': 'Asia',
    'UZB': 'Asia', 'VNM': 'Asia', 'YEM': 'Asia',
    
    # Europe
    'ALB': 'Europe', 'AND': 'Europe', 'AUT': 'Europe', 'BLR': 'Europe',
    'BEL': 'Europe', 'BIH': 'Europe', 'BGR': 'Europe', 'HRV': 'Europe',
    'CZE': 'Europe', 'DNK': 'Europe', 'EST': 'Europe', 'FIN': 'Europe',
    'FRA': 'Europe', 'DEU': 'Europe', 'GRC': 'Europe', 'HUN': 'Europe',
    'ISL': 'Europe', 'IRL': 'Europe', 'ITA': 'Europe', 'LVA': 'Europe',
    'LTU': 'Europe', 'LUX': 'Europe', 'MLT': 'Europe', 'MDA': 'Europe',
    'MCO': 'Europe', 'MNE': 'Europe', 'NLD': 'Europe', 'MKD': 'Europe',
    'NOR': 'Europe', 'POL': 'Europe', 'PRT': 'Europe', 'ROU': 'Europe',
    'RUS': 'Europe', 'SMR': 'Europe', 'SRB': 'Europe', 'SVK': 'Europe',
    'SVN': 'Europe', 'ESP': 'Europe', 'SWE': 'Europe', 'CHE': 'Europe',
    'UKR': 'Europe', 'GBR': 'Europe',
    
    # Oceania
    'AUS': 'Oceania', 'FJI': 'Oceania', 'KIR': 'Oceania', 'MHL': 'Oceania',
    'FSM': 'Oceania', 'NRU': 'Oceania', 'NZL': 'Oceania', 'PLW': 'Oceania',
    'PNG': 'Oceania', 'WSM': 'Oceania', 'SLB': 'Oceania', 'TON': 'Oceania',
    'TUV': 'Oceania', 'VUT': 'Oceania',
}

# Country name mapping (ISO code to display name)
COUNTRY_NAMES: Dict[str, str] = {
    'AFG': 'Afghanistan', 'ALB': 'Albania', 'DZA': 'Algeria', 'AND': 'Andorra',
    'AGO': 'Angola', 'ATG': 'Antigua and Barbuda', 'ARG': 'Argentina',
    'ARM': 'Armenia', 'AUS': 'Australia', 'AUT': 'Austria', 'AZE': 'Azerbaijan',
    'BHS': 'Bahamas', 'BHR': 'Bahrain', 'BGD': 'Bangladesh', 'BRB': 'Barbados',
    'BLR': 'Belarus', 'BEL': 'Belgium', 'BLZ': 'Belize', 'BEN': 'Benin',
    'BTN': 'Bhutan', 'BOL': 'Bolivia', 'BIH': 'Bosnia and Herzegovina',
    'BWA': 'Botswana', 'BRA': 'Brazil', 'BRN': 'Brunei', 'BGR': 'Bulgaria',
    'BFA': 'Burkina Faso', 'BDI': 'Burundi', 'CPV': 'Cabo Verde', 'KHM': 'Cambodia',
    'CMR': 'Cameroon', 'CAN': 'Canada', 'CAF': 'Central African Republic',
    'TCD': 'Chad', 'CHL': 'Chile', 'CHN': 'China', 'COL': 'Colombia',
    'COM': 'Comoros', 'COG': 'Congo', 'COD': 'DR Congo', 'CRI': 'Costa Rica',
    'CIV': "Cote d'Ivoire", 'HRV': 'Croatia', 'CUB': 'Cuba', 'CYP': 'Cyprus',
    'CZE': 'Czechia', 'DNK': 'Denmark', 'DJI': 'Djibouti', 'DMA': 'Dominica',
    'DOM': 'Dominican Republic', 'ECU': 'Ecuador', 'EGY': 'Egypt',
    'SLV': 'El Salvador', 'GNQ': 'Equatorial Guinea', 'ERI': 'Eritrea',
    'EST': 'Estonia', 'SWZ': 'Eswatini', 'ETH': 'Ethiopia', 'FJI': 'Fiji',
    'FIN': 'Finland', 'FRA': 'France', 'GAB': 'Gabon', 'GMB': 'Gambia',
    'GEO': 'Georgia', 'DEU': 'Germany', 'GHA': 'Ghana', 'GRC': 'Greece',
    'GRD': 'Grenada', 'GTM': 'Guatemala', 'GIN': 'Guinea', 'GNB': 'Guinea-Bissau',
    'GUY': 'Guyana', 'HTI': 'Haiti', 'HND': 'Honduras', 'HUN': 'Hungary',
    'ISL': 'Iceland', 'IND': 'India', 'IDN': 'Indonesia', 'IRN': 'Iran',
    'IRQ': 'Iraq', 'IRL': 'Ireland', 'ISR': 'Israel', 'ITA': 'Italy',
    'JAM': 'Jamaica', 'JPN': 'Japan', 'JOR': 'Jordan', 'KAZ': 'Kazakhstan',
    'KEN': 'Kenya', 'KIR': 'Kiribati', 'PRK': 'North Korea', 'KOR': 'South Korea',
    'KWT': 'Kuwait', 'KGZ': 'Kyrgyzstan', 'LAO': 'Laos', 'LVA': 'Latvia',
    'LBN': 'Lebanon', 'LSO': 'Lesotho', 'LBR': 'Liberia', 'LBY': 'Libya',
    'LTU': 'Lithuania', 'LUX': 'Luxembourg', 'MDG': 'Madagascar', 'MWI': 'Malawi',
    'MYS': 'Malaysia', 'MDV': 'Maldives', 'MLI': 'Mali', 'MLT': 'Malta',
    'MHL': 'Marshall Islands', 'MRT': 'Mauritania', 'MUS': 'Mauritius',
    'MEX': 'Mexico', 'FSM': 'Micronesia', 'MDA': 'Moldova', 'MCO': 'Monaco',
    'MNG': 'Mongolia', 'MNE': 'Montenegro', 'MAR': 'Morocco', 'MOZ': 'Mozambique',
    'MMR': 'Myanmar', 'NAM': 'Namibia', 'NRU': 'Nauru', 'NPL': 'Nepal',
    'NLD': 'Netherlands', 'NZL': 'New Zealand', 'NIC': 'Nicaragua',
    'NER': 'Niger', 'NGA': 'Nigeria', 'MKD': 'North Macedonia', 'NOR': 'Norway',
    'OMN': 'Oman', 'PAK': 'Pakistan', 'PLW': 'Palau', 'PAN': 'Panama',
    'PNG': 'Papua New Guinea', 'PRY': 'Paraguay', 'PER': 'Peru', 'PHL': 'Philippines',
    'POL': 'Poland', 'PRT': 'Portugal', 'QAT': 'Qatar', 'ROU': 'Romania',
    'RUS': 'Russia', 'RWA': 'Rwanda', 'KNA': 'Saint Kitts and Nevis',
    'LCA': 'Saint Lucia', 'VCT': 'Saint Vincent and the Grenadines',
    'WSM': 'Samoa', 'SMR': 'San Marino', 'STP': 'Sao Tome and Principe',
    'SAU': 'Saudi Arabia', 'SEN': 'Senegal', 'SRB': 'Serbia', 'SYC': 'Seychelles',
    'SLE': 'Sierra Leone', 'SGP': 'Singapore', 'SVK': 'Slovakia', 'SVN': 'Slovenia',
    'SLB': 'Solomon Islands', 'SOM': 'Somalia', 'ZAF': 'South Africa',
    'SSD': 'South Sudan', 'ESP': 'Spain', 'LKA': 'Sri Lanka', 'SDN': 'Sudan',
    'SUR': 'Suriname', 'SWE': 'Sweden', 'CHE': 'Switzerland', 'SYR': 'Syria',
    'TJK': 'Tajikistan', 'TZA': 'Tanzania', 'THA': 'Thailand', 'TLS': 'Timor-Leste',
    'TGO': 'Togo', 'TON': 'Tonga', 'TTO': 'Trinidad and Tobago', 'TUN': 'Tunisia',
    'TUR': 'Turkey', 'TKM': 'Turkmenistan', 'TUV': 'Tuvalu', 'UGA': 'Uganda',
    'UKR': 'Ukraine', 'ARE': 'United Arab Emirates', 'GBR': 'United Kingdom',
    'USA': 'United States', 'URY': 'Uruguay', 'UZB': 'Uzbekistan', 'VUT': 'Vanuatu',
    'VEN': 'Venezuela', 'VNM': 'Vietnam', 'YEM': 'Yemen', 'ZMB': 'Zambia',
    'ZWE': 'Zimbabwe',
}


def get_country_name(iso_code: str) -> str:
    """Get the full country name for an ISO 3166-1 alpha-3 code."""
    return COUNTRY_NAMES.get(iso_code, iso_code)


def get_continent(iso_code: str) -> str:
    """Get the continent for an ISO 3166-1 alpha-3 code."""
    return COUNTRY_CONTINENT_MAP.get(iso_code, 'Unknown')


def normalize_geography(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add country name and continent columns to a DataFrame.
    
    Args:
        df: DataFrame with 'CountryCode' column
        
    Returns:
        DataFrame with added 'Country' and 'Continent' columns
    """
    df = df.copy()
    
    if 'CountryCode' not in df.columns:
        logger.warning("DataFrame missing CountryCode column, cannot normalize geography")
        return df
    
    # Add country name
    df['Country'] = df['CountryCode'].map(get_country_name)
    
    # Add continent
    df['Continent'] = df['CountryCode'].map(get_continent)
    
    # Log coverage
    unknown_countries = df[df['Continent'] == 'Unknown']['CountryCode'].unique()
    if len(unknown_countries) > 0:
        logger.warning(f"Unknown country codes: {list(unknown_countries)}")
    
    return df


def get_country_metadata_df() -> pd.DataFrame:
    """
    Generate a reference DataFrame with country metadata.
    
    Returns:
        DataFrame with columns: CountryCode, Country, Continent
    """
    records = []
    for code, name in COUNTRY_NAMES.items():
        continent = COUNTRY_CONTINENT_MAP.get(code, 'Unknown')
        records.append({
            'CountryCode': code,
            'Country': name,
            'Continent': continent
        })
    
    return pd.DataFrame(records)
