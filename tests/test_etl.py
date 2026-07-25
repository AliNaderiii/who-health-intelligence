"""Unit tests for ETL/API/database behavior without live WHO API calls."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.api import client as client_module
from src.who_health_intelligence.api.client import WHOAPIClient
from src.who_health_intelligence.etl.loader import DatabaseLoader
from src.who_health_intelligence.etl.metadata import normalize_geography
from src.who_health_intelligence.etl.schema import validate_transformed_dataframe
from src.who_health_intelligence.etl.transform import transform_indicator_records


class MockResponse:
    """Small response double for WHOAPIClient tests."""

    def __init__(self, payload=None, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


def sample_raw_records():
    return [
        {"SpatialDim": "USA", "TimeDim": "2020", "Dim1": "SEX_BTSX", "NumericValue": "78.5"},
        {"SpatialDim": "GBR", "TimeDim": "2020", "Dim1": "SEX_BTSX", "NumericValue": "81.0"},
    ]


def sample_loaded_df():
    transformed = transform_indicator_records(sample_raw_records(), "LIFE_EXPECTANCY", "WHOSIS_000001")
    return normalize_geography(transformed)


def test_api_response_parsing_with_mocked_response(monkeypatch):
    calls = []
    payload = {"value": sample_raw_records()}
    client = WHOAPIClient(base_url="https://example.invalid/api", timeout=5, max_retries=0)

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return MockResponse(payload)

    monkeypatch.setattr(client.session, "get", fake_get)

    parsed = client._fetch_page("WHOSIS_000001", skip=10, top=50)

    assert parsed == payload
    assert calls == [
        {
            "url": "https://example.invalid/api/WHOSIS_000001",
            "params": {"$skip": 10, "$top": 50},
            "timeout": 5,
        }
    ]


def test_empty_api_response_handling(monkeypatch):
    client = WHOAPIClient(base_url="https://example.invalid/api", timeout=5, max_retries=0)
    monkeypatch.setattr(client, "_fetch_page", lambda indicator_code, skip=0, top=1000: {"value": []})

    records = client.extract_indicator("WHOSIS_000001")

    assert records == []


def test_invalid_json_handling(monkeypatch):
    client = WHOAPIClient(base_url="https://example.invalid/api", timeout=5, max_retries=0)
    error = json.JSONDecodeError("invalid", "not-json", 0)
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: MockResponse(json_error=error))

    with pytest.raises(json.JSONDecodeError):
        client._fetch_page("WHOSIS_000001")


def test_retry_behavior_is_configured_with_mocked_requests_session(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.mounted = {}

        def mount(self, prefix, adapter):
            self.mounted[prefix] = adapter

    fake_session = FakeSession()
    monkeypatch.setattr(client_module.requests, "Session", lambda: fake_session)

    WHOAPIClient(base_url="https://example.invalid/api", max_retries=4)

    assert fake_session.mounted["https://"].max_retries.total == 4
    assert 500 in fake_session.mounted["https://"].max_retries.status_forcelist
    assert set(fake_session.mounted["http://"].max_retries.allowed_methods) == {"GET"}


def test_missing_columns_validation():
    df = pd.DataFrame({"CountryCode": ["USA"], "Year": [2020], "Indicator": ["X"]})

    result = validate_transformed_dataframe(df)

    assert result["is_valid"] is False
    assert any("Missing required columns" in error for error in result["errors"])


def test_year_conversion_and_country_mapping():
    transformed = transform_indicator_records(sample_raw_records(), "LIFE_EXPECTANCY", "WHOSIS_000001")
    mapped = normalize_geography(transformed)

    assert str(transformed["Year"].dtype) == "int32"
    assert str(transformed["Value"].dtype) == "float32"
    assert mapped.loc[mapped["CountryCode"].astype(str) == "USA", "Continent"].iloc[0] == "Americas"
    assert mapped.loc[mapped["CountryCode"].astype(str) == "GBR", "Country"].iloc[0] == "United Kingdom"


def test_empty_dataframe_load_behavior(tmp_path):
    loader = DatabaseLoader(str(tmp_path / "empty.db"))

    assert loader.load_dataframe(pd.DataFrame()) == 0
    assert loader.query("SELECT COUNT(*) AS n FROM health_indicators").iloc[0]["n"] == 0


def test_sqlite_write_and_read_behavior(tmp_path):
    loader = DatabaseLoader(str(tmp_path / "health.db"))
    df = sample_loaded_df()

    loaded = loader.load_all_indicators(df, replace_all=True)
    read_back = loader.query("SELECT CountryCode, Year, Indicator, Value, Continent FROM health_indicators")

    assert loaded == 2
    assert len(read_back) == 2
    assert set(read_back["CountryCode"]) == {"USA", "GBR"}


def test_idempotent_pipeline_execution_replaces_existing_rows(tmp_path):
    loader = DatabaseLoader(str(tmp_path / "idempotent.db"))
    df = sample_loaded_df()

    first_count = loader.load_all_indicators(df, replace_all=True)
    second_count = loader.load_all_indicators(df, replace_all=True)
    table_count = loader.query("SELECT COUNT(*) AS n FROM health_indicators").iloc[0]["n"]

    assert first_count == 2
    assert second_count == 2
    assert table_count == 2


def test_duplicate_existing_rows_removed_by_replace_before_insert(tmp_path):
    loader = DatabaseLoader(str(tmp_path / "replace.db"))
    df = sample_loaded_df()
    modified = df.copy()
    modified.loc[modified["CountryCode"].astype(str) == "USA", "Value"] = 79.5

    loader.load_all_indicators(df, replace_all=True)
    loader.load_all_indicators(modified, replace_all=True)
    rows = loader.query("SELECT CountryCode, Value FROM health_indicators WHERE CountryCode = 'USA'")

    assert len(rows) == 1
    assert rows.iloc[0]["Value"] == pytest.approx(79.5)
