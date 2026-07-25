"""Tests for centralized project configuration."""

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.config as config


def test_required_configuration_values_exist():
    assert config.WHO_API_BASE_URL.startswith("https://")
    assert config.WHO_INDICATORS
    assert config.DEFAULT_INDICATORS
    assert isinstance(config.DATABASE_PATH, Path)
    assert isinstance(config.RAW_DATA_PATH, Path)
    assert isinstance(config.PROCESSED_DATA_PATH, Path)
    assert isinstance(config.METADATA_PATH, Path)
    assert config.DEFAULT_RETRY_COUNT >= 0
    assert config.DEFAULT_REQUEST_TIMEOUT > 0
    assert config.APPLICATION_TITLE == "WHO Global Health Intelligence Platform"
    assert config.PROJECT_VERSION


def test_paths_are_centralized_and_created():
    for path in [config.DATA_DIR, config.RAW_DATA_PATH, config.PROCESSED_DATA_PATH, config.METADATA_PATH, config.LOGS_DIR]:
        assert isinstance(path, Path)
        assert path.exists()
        assert path.is_dir()


def test_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("WHO_DATA_DIR", str(tmp_path / "data_override"))
    monkeypatch.setenv("WHO_DB_PATH", str(tmp_path / "custom.db"))
    monkeypatch.setenv("WHO_API_BASE_URL", "https://example.invalid/api/")
    monkeypatch.setenv("WHO_RETRY_COUNT", "5")
    monkeypatch.setenv("WHO_REQUEST_TIMEOUT", "45")

    reloaded = importlib.reload(config)

    assert reloaded.DATA_DIR == (tmp_path / "data_override").resolve()
    assert reloaded.DATABASE_PATH == (tmp_path / "custom.db").resolve()
    assert reloaded.WHO_API_BASE_URL == "https://example.invalid/api/"
    assert reloaded.DEFAULT_RETRY_COUNT == 5
    assert reloaded.DEFAULT_REQUEST_TIMEOUT == 45

    monkeypatch.delenv("WHO_DATA_DIR")
    monkeypatch.delenv("WHO_DB_PATH")
    monkeypatch.delenv("WHO_API_BASE_URL")
    monkeypatch.delenv("WHO_RETRY_COUNT")
    monkeypatch.delenv("WHO_REQUEST_TIMEOUT")
    importlib.reload(config)


def test_legacy_config_import_reexports_central_values():
    from src.who_health_intelligence.utils import config as legacy_config

    assert legacy_config.WHO_API_BASE_URL == config.WHO_API_BASE_URL
    assert legacy_config.DATABASE_PATH == config.DATABASE_PATH
    assert legacy_config.RAW_DATA_PATH == config.RAW_DATA_PATH
    assert legacy_config.PROJECT_VERSION == config.PROJECT_VERSION
