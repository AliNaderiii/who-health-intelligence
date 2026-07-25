"""
Country and geographic metadata normalization - Production LIVE mode.

Requirements:
- Do not rely only on Plotly Gapminder metadata
- Use reliable ISO country metadata source or pycountry
- Normalize ISO Alpha-3, country name, continent, region where available
- Track unmapped countries in data-quality report
- Dashboard must show total countries, mapped, unmapped, mapping coverage %

This module tries to use pycountry if available (added to requirements.txt),
falls back to internal mapping which is comprehensive for WHO member states.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Set
import pandas as pd

from ..utils.config import setup_logging

logger = setup_logging(__name__)

# Try importing pycountry for official ISO metadata
try:
    import pycountry

    HAS_PYCOUNTRY = True
    logger.info("pycountry available, will use for ISO 3166 validation")
except ImportError:
    HAS_PYCOUNTRY = False
    logger.warning("pycountry not available, using internal ISO mapping fallback")

# ------------------------------------------------------------------
# Internal mapping - comprehensive for WHO 194 member states + some territories
# ------------------------------------------------------------------
COUNTRY_CONTINENT_MAP: Dict[str, str] = {
    # Africa
    "DZA": "Africa",
    "AGO": "Africa",
    "BEN": "Africa",
    "BWA": "Africa",
    "BFA": "Africa",
    "BDI": "Africa",
    "CPV": "Africa",
    "CMR": "Africa",
    "CAF": "Africa",
    "TCD": "Africa",
    "COM": "Africa",
    "COG": "Africa",
    "COD": "Africa",
    "CIV": "Africa",
    "DJI": "Africa",
    "EGY": "Africa",
    "GNQ": "Africa",
    "ERI": "Africa",
    "SWZ": "Africa",
    "ETH": "Africa",
    "GAB": "Africa",
    "GMB": "Africa",
    "GHA": "Africa",
    "GIN": "Africa",
    "GNB": "Africa",
    "KEN": "Africa",
    "LSO": "Africa",
    "LBR": "Africa",
    "LBY": "Africa",
    "MDG": "Africa",
    "MWI": "Africa",
    "MLI": "Africa",
    "MRT": "Africa",
    "MUS": "Africa",
    "MAR": "Africa",
    "MOZ": "Africa",
    "NAM": "Africa",
    "NER": "Africa",
    "NGA": "Africa",
    "RWA": "Africa",
    "STP": "Africa",
    "SEN": "Africa",
    "SYC": "Africa",
    "SLE": "Africa",
    "SOM": "Africa",
    "ZAF": "Africa",
    "SSD": "Africa",
    "SDN": "Africa",
    "TZA": "Africa",
    "TGO": "Africa",
    "TUN": "Africa",
    "UGA": "Africa",
    "ZMB": "Africa",
    "ZWE": "Africa",
    # Americas
    "ATG": "Americas",
    "ARG": "Americas",
    "BHS": "Americas",
    "BRB": "Americas",
    "BLZ": "Americas",
    "BOL": "Americas",
    "BRA": "Americas",
    "CAN": "Americas",
    "CHL": "Americas",
    "COL": "Americas",
    "CRI": "Americas",
    "CUB": "Americas",
    "DMA": "Americas",
    "DOM": "Americas",
    "ECU": "Americas",
    "SLV": "Americas",
    "GRD": "Americas",
    "GTM": "Americas",
    "GUY": "Americas",
    "HTI": "Americas",
    "HND": "Americas",
    "JAM": "Americas",
    "MEX": "Americas",
    "NIC": "Americas",
    "PAN": "Americas",
    "PRY": "Americas",
    "PER": "Americas",
    "KNA": "Americas",
    "LCA": "Americas",
    "VCT": "Americas",
    "SUR": "Americas",
    "TTO": "Americas",
    "USA": "Americas",
    "URY": "Americas",
    "VEN": "Americas",
    # Asia
    "AFG": "Asia",
    "ARM": "Asia",
    "AZE": "Asia",
    "BHR": "Asia",
    "BGD": "Asia",
    "BTN": "Asia",
    "BRN": "Asia",
    "KHM": "Asia",
    "CHN": "Asia",
    "CYP": "Asia",
    "PRK": "Asia",
    "GEO": "Asia",
    "IND": "Asia",
    "IDN": "Asia",
    "IRN": "Asia",
    "IRQ": "Asia",
    "ISR": "Asia",
    "JPN": "Asia",
    "JOR": "Asia",
    "KAZ": "Asia",
    "KWT": "Asia",
    "KGZ": "Asia",
    "LAO": "Asia",
    "LBN": "Asia",
    "MYS": "Asia",
    "MDV": "Asia",
    "MNG": "Asia",
    "MMR": "Asia",
    "NPL": "Asia",
    "OMN": "Asia",
    "PAK": "Asia",
    "PHL": "Asia",
    "QAT": "Asia",
    "KOR": "Asia",
    "SAU": "Asia",
    "SGP": "Asia",
    "LKA": "Asia",
    "SYR": "Asia",
    "TJK": "Asia",
    "THA": "Asia",
    "TLS": "Asia",
    "TUR": "Asia",
    "TKM": "Asia",
    "ARE": "Asia",
    "UZB": "Asia",
    "VNM": "Asia",
    "YEM": "Asia",
    # Europe
    "ALB": "Europe",
    "AND": "Europe",
    "AUT": "Europe",
    "BLR": "Europe",
    "BEL": "Europe",
    "BIH": "Europe",
    "BGR": "Europe",
    "HRV": "Europe",
    "CZE": "Europe",
    "DNK": "Europe",
    "EST": "Europe",
    "FIN": "Europe",
    "FRA": "Europe",
    "DEU": "Europe",
    "GRC": "Europe",
    "HUN": "Europe",
    "ISL": "Europe",
    "IRL": "Europe",
    "ITA": "Europe",
    "LVA": "Europe",
    "LTU": "Europe",
    "LUX": "Europe",
    "MLT": "Europe",
    "MDA": "Europe",
    "MCO": "Europe",
    "MNE": "Europe",
    "NLD": "Europe",
    "MKD": "Europe",
    "NOR": "Europe",
    "POL": "Europe",
    "PRT": "Europe",
    "ROU": "Europe",
    "RUS": "Europe",
    "SMR": "Europe",
    "SRB": "Europe",
    "SVK": "Europe",
    "SVN": "Europe",
    "ESP": "Europe",
    "SWE": "Europe",
    "CHE": "Europe",
    "UKR": "Europe",
    "GBR": "Europe",
    # Oceania
    "AUS": "Oceania",
    "FJI": "Oceania",
    "KIR": "Oceania",
    "MHL": "Oceania",
    "FSM": "Oceania",
    "NRU": "Oceania",
    "NZL": "Oceania",
    "PLW": "Oceania",
    "PNG": "Oceania",
    "WSM": "Oceania",
    "SLB": "Oceania",
    "TON": "Oceania",
    "TUV": "Oceania",
    "VUT": "Oceania",
}

COUNTRY_NAMES: Dict[str, str] = {
    "AFG": "Afghanistan",
    "ALB": "Albania",
    "DZA": "Algeria",
    "AND": "Andorra",
    "AGO": "Angola",
    "ATG": "Antigua and Barbuda",
    "ARG": "Argentina",
    "ARM": "Armenia",
    "AUS": "Australia",
    "AUT": "Austria",
    "AZE": "Azerbaijan",
    "BHS": "Bahamas",
    "BHR": "Bahrain",
    "BGD": "Bangladesh",
    "BRB": "Barbados",
    "BLR": "Belarus",
    "BEL": "Belgium",
    "BLZ": "Belize",
    "BEN": "Benin",
    "BTN": "Bhutan",
    "BOL": "Bolivia",
    "BIH": "Bosnia and Herzegovina",
    "BWA": "Botswana",
    "BRA": "Brazil",
    "BRN": "Brunei",
    "BGR": "Bulgaria",
    "BFA": "Burkina Faso",
    "BDI": "Burundi",
    "CPV": "Cabo Verde",
    "KHM": "Cambodia",
    "CMR": "Cameroon",
    "CAN": "Canada",
    "CAF": "Central African Republic",
    "TCD": "Chad",
    "CHL": "Chile",
    "CHN": "China",
    "COL": "Colombia",
    "COM": "Comoros",
    "COG": "Congo",
    "COD": "DR Congo",
    "CRI": "Costa Rica",
    "CIV": "Cote d'Ivoire",
    "HRV": "Croatia",
    "CUB": "Cuba",
    "CYP": "Cyprus",
    "CZE": "Czechia",
    "DNK": "Denmark",
    "DJI": "Djibouti",
    "DMA": "Dominica",
    "DOM": "Dominican Republic",
    "ECU": "Ecuador",
    "EGY": "Egypt",
    "SLV": "El Salvador",
    "GNQ": "Equatorial Guinea",
    "ERI": "Eritrea",
    "EST": "Estonia",
    "SWZ": "Eswatini",
    "ETH": "Ethiopia",
    "FJI": "Fiji",
    "FIN": "Finland",
    "FRA": "France",
    "GAB": "Gabon",
    "GMB": "Gambia",
    "GEO": "Georgia",
    "DEU": "Germany",
    "GHA": "Ghana",
    "GRC": "Greece",
    "GRD": "Grenada",
    "GTM": "Guatemala",
    "GIN": "Guinea",
    "GNB": "Guinea-Bissau",
    "GUY": "Guyana",
    "HTI": "Haiti",
    "HND": "Honduras",
    "HUN": "Hungary",
    "ISL": "Iceland",
    "IND": "India",
    "IDN": "Indonesia",
    "IRN": "Iran",
    "IRQ": "Iraq",
    "IRL": "Ireland",
    "ISR": "Israel",
    "ITA": "Italy",
    "JAM": "Jamaica",
    "JPN": "Japan",
    "JOR": "Jordan",
    "KAZ": "Kazakhstan",
    "KEN": "Kenya",
    "KIR": "Kiribati",
    "PRK": "North Korea",
    "KOR": "South Korea",
    "KWT": "Kuwait",
    "KGZ": "Kyrgyzstan",
    "LAO": "Laos",
    "LVA": "Latvia",
    "LBN": "Lebanon",
    "LSO": "Lesotho",
    "LBR": "Liberia",
    "LBY": "Libya",
    "LTU": "Lithuania",
    "LUX": "Luxembourg",
    "MDG": "Madagascar",
    "MWI": "Malawi",
    "MYS": "Malaysia",
    "MDV": "Maldives",
    "MLI": "Mali",
    "MLT": "Malta",
    "MHL": "Marshall Islands",
    "MRT": "Mauritania",
    "MUS": "Mauritius",
    "MEX": "Mexico",
    "FSM": "Micronesia",
    "MDA": "Moldova",
    "MCO": "Monaco",
    "MNG": "Mongolia",
    "MNE": "Montenegro",
    "MAR": "Morocco",
    "MOZ": "Mozambique",
    "MMR": "Myanmar",
    "NAM": "Namibia",
    "NRU": "Nauru",
    "NPL": "Nepal",
    "NLD": "Netherlands",
    "NZL": "New Zealand",
    "NIC": "Nicaragua",
    "NER": "Niger",
    "NGA": "Nigeria",
    "MKD": "North Macedonia",
    "NOR": "Norway",
    "OMN": "Oman",
    "PAK": "Pakistan",
    "PLW": "Palau",
    "PAN": "Panama",
    "PNG": "Papua New Guinea",
    "PRY": "Paraguay",
    "PER": "Peru",
    "PHL": "Philippines",
    "POL": "Poland",
    "PRT": "Portugal",
    "QAT": "Qatar",
    "ROU": "Romania",
    "RUS": "Russia",
    "RWA": "Rwanda",
    "KNA": "Saint Kitts and Nevis",
    "LCA": "Saint Lucia",
    "VCT": "Saint Vincent and the Grenadines",
    "WSM": "Samoa",
    "SMR": "San Marino",
    "STP": "Sao Tome and Principe",
    "SAU": "Saudi Arabia",
    "SEN": "Senegal",
    "SRB": "Serbia",
    "SYC": "Seychelles",
    "SLE": "Sierra Leone",
    "SGP": "Singapore",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "SLB": "Solomon Islands",
    "SOM": "Somalia",
    "ZAF": "South Africa",
    "SSD": "South Sudan",
    "ESP": "Spain",
    "LKA": "Sri Lanka",
    "SDN": "Sudan",
    "SUR": "Suriname",
    "SWE": "Sweden",
    "CHE": "Switzerland",
    "SYR": "Syria",
    "TJK": "Tajikistan",
    "TZA": "Tanzania",
    "THA": "Thailand",
    "TLS": "Timor-Leste",
    "TGO": "Togo",
    "TON": "Tonga",
    "TTO": "Trinidad and Tobago",
    "TUN": "Tunisia",
    "TUR": "Turkey",
    "TKM": "Turkmenistan",
    "TUV": "Tuvalu",
    "UGA": "Uganda",
    "UKR": "Ukraine",
    "ARE": "United Arab Emirates",
    "GBR": "United Kingdom",
    "USA": "United States",
    "URY": "Uruguay",
    "UZB": "Uzbekistan",
    "VUT": "Vanuatu",
    "VEN": "Venezuela",
    "VNM": "Vietnam",
    "YEM": "Yemen",
    "ZMB": "Zambia",
    "ZWE": "Zimbabwe",
}

# Additional region mapping (UN geoscheme approximation)
COUNTRY_REGION_MAP: Dict[str, str] = {
    # Africa regions
    "DZA": "Northern Africa",
    "EGY": "Northern Africa",
    "LBY": "Northern Africa",
    "MAR": "Northern Africa",
    "SDN": "Northern Africa",
    "TUN": "Northern Africa",
    "BFA": "Western Africa",
    "BEN": "Western Africa",
    "CPV": "Western Africa",
    "CIV": "Western Africa",
    "GMB": "Western Africa",
    "GHA": "Western Africa",
    "GIN": "Western Africa",
    "GNB": "Western Africa",
    "LBR": "Western Africa",
    "MLI": "Western Africa",
    "MRT": "Western Africa",
    "NER": "Western Africa",
    "NGA": "Western Africa",
    "SEN": "Western Africa",
    "SLE": "Western Africa",
    "TGO": "Western Africa",
    # Americas
    "CAN": "Northern America",
    "USA": "Northern America",
    "MEX": "Central America",
    "GTM": "Central America",
    "BLZ": "Central America",
    "SLV": "Central America",
    "HND": "Central America",
    "NIC": "Central America",
    "CRI": "Central America",
    "PAN": "Central America",
    # Asia
    "CHN": "Eastern Asia",
    "JPN": "Eastern Asia",
    "KOR": "Eastern Asia",
    "PRK": "Eastern Asia",
    "MNG": "Eastern Asia",
    "IND": "Southern Asia",
    "PAK": "Southern Asia",
    "BGD": "Southern Asia",
    "NPL": "Southern Asia",
    "LKA": "Southern Asia",
    # Europe
    "DEU": "Western Europe",
    "FRA": "Western Europe",
    "GBR": "Northern Europe",
    "SWE": "Northern Europe",
    "NOR": "Northern Europe",
    # Oceania
    "AUS": "Australia and New Zealand",
    "NZL": "Australia and New Zealand",
}


def get_country_name(iso_code: str) -> str:
    """Get country name using pycountry if available, fallback to internal map."""
    code = iso_code.strip().upper()
    if HAS_PYCOUNTRY:
        try:
            country = pycountry.countries.get(alpha_3=code)
            if country and hasattr(country, "name"):
                return country.name
        except Exception:
            pass
    return COUNTRY_NAMES.get(code, code)


def get_continent(iso_code: str) -> str:
    return COUNTRY_CONTINENT_MAP.get(iso_code.strip().upper(), "Unknown")


def get_region(iso_code: str) -> str:
    """Get sub-region where available."""
    return COUNTRY_REGION_MAP.get(iso_code.strip().upper(), "Unknown")


def get_country_metadata(iso_code: str) -> Dict[str, str]:
    """Return dict with country_code, country_name, continent, region."""
    code = iso_code.strip().upper()
    return {
        "country_code": code,
        "country_name": get_country_name(code),
        "continent": get_continent(code),
        "region": get_region(code),
    }


def normalize_geography(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize geography for both snake_case and legacy CamelCase columns.
    Adds:
    - country_name / Country
    - continent / Continent
    - region (sub-region) where available
    - mapping coverage logging

    Tracks unmapped countries.
    """
    df = df.copy()

    # Determine which column holds country code
    if "country_code" in df.columns:
        code_col = "country_code"
    elif "CountryCode" in df.columns:
        code_col = "CountryCode"
    else:
        logger.warning("DataFrame missing CountryCode/country_code column, cannot normalize geography")
        return df

    # Ensure we have list of codes
    codes = df[code_col].astype(str).str.strip().str.upper().unique()

    # Build mapping dictionaries
    name_map = {code: get_country_name(code) for code in codes}
    continent_map = {code: get_continent(code) for code in codes}
    region_map = {code: get_region(code) for code in codes}

    # Apply to both snake and legacy
    if "country_code" in df.columns:
        df["country_name"] = df["country_code"].astype(str).str.strip().str.upper().map(name_map)
        df["continent"] = df["country_code"].astype(str).str.strip().str.upper().map(continent_map)
        df["region"] = df["country_code"].astype(str).str.strip().str.upper().map(region_map)
    if "CountryCode" in df.columns:
        df["Country"] = df["CountryCode"].astype(str).str.strip().str.upper().map(name_map)
        df["Continent"] = df["CountryCode"].astype(str).str.strip().str.upper().map(continent_map)
        # region for legacy if needed
        if "region" not in df.columns:
            df["region"] = df["CountryCode"].astype(str).str.strip().str.upper().map(region_map)
        else:
            # ensure region column exists
            df["region"] = df["region"].fillna(df["CountryCode"].astype(str).str.strip().str.upper().map(region_map))

    # Log coverage
    unknown_codes = [code for code in codes if continent_map.get(code, "Unknown") == "Unknown"]
    mapped_count = len(codes) - len(unknown_codes)
    total_count = len(codes)
    coverage_pct = (mapped_count / total_count * 100) if total_count > 0 else 0

    if unknown_codes:
        logger.warning(
            f"Geography mapping: {mapped_count}/{total_count} mapped ({coverage_pct:.1f}%), "
            f"unmapped codes: {unknown_codes[:20]}"
        )
    else:
        logger.info(
            f"Geography mapping: all {total_count} countries mapped ({coverage_pct:.1f}% coverage)"
        )

    # Store mapping stats in df attrs for later reporting
    df.attrs["mapping_total"] = total_count
    df.attrs["mapping_mapped"] = mapped_count
    df.attrs["mapping_unmapped"] = len(unknown_codes)
    df.attrs["mapping_coverage_pct"] = coverage_pct
    df.attrs["mapping_unmapped_codes"] = unknown_codes

    return df


def get_country_metadata_df() -> pd.DataFrame:
    records = []
    for code, name in COUNTRY_NAMES.items():
        continent = COUNTRY_CONTINENT_MAP.get(code, "Unknown")
        region = COUNTRY_REGION_MAP.get(code, "Unknown")
        records.append(
            {
                "country_code": code,
                "country_name": name,
                "continent": continent,
                "region": region,
                "CountryCode": code,
                "Country": name,
                "Continent": continent,
            }
        )
    return pd.DataFrame(records)


def get_mapping_coverage_report(df: pd.DataFrame) -> Dict[str, any]:
    """
    Generate report required by dashboard: total countries, mapped, unmapped, coverage %.
    """
    if df.empty:
        return {
            "total_countries": 0,
            "mapped_countries": 0,
            "unmapped_countries": 0,
            "mapping_coverage_pct": 0.0,
            "unmapped_codes": [],
        }

    code_col = "country_code" if "country_code" in df.columns else "CountryCode" if "CountryCode" in df.columns else None
    if not code_col:
        return {
            "total_countries": 0,
            "mapped_countries": 0,
            "unmapped_countries": 0,
            "mapping_coverage_pct": 0.0,
            "unmapped_codes": [],
        }

    codes = df[code_col].astype(str).str.strip().str.upper().unique()
    total = len(codes)
    unmapped = [c for c in codes if get_continent(c) == "Unknown"]
    mapped = total - len(unmapped)
    coverage = (mapped / total * 100) if total > 0 else 0

    return {
        "total_countries": total,
        "mapped_countries": mapped,
        "unmapped_countries": len(unmapped),
        "mapping_coverage_pct": round(coverage, 1),
        "unmapped_codes": sorted(unmapped),
        "mapped_codes": sorted([c for c in codes if c not in unmapped]),
    }
