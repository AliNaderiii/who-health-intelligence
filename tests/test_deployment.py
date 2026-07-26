"""
Deployment-configuration and startup tests.

Covers the Streamlit Community Cloud requirements:
- Pinned Python runtime (3.12) declared at repository root
- Runtime requirements contain only packages imported by the deployed app
- Test-only packages live in requirements-dev.txt
- The dashboard module does not run the ETL pipeline at import time
- The controlled loader never substitutes synthetic data in LIVE mode
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.who_health_intelligence.dashboard import services as svc

APP_PATH = PROJECT_ROOT / "src" / "who_health_intelligence" / "dashboard" / "app.py"


def _requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        for sep in ("==", ">=", "<=", "~=", ">", "<"):
            if sep in line:
                line = line.split(sep, 1)[0]
                break
        names.add(line.strip().lower())
    return names


class TestPythonRuntimeDeclaration:
    def test_runtime_txt_exists_with_python_312(self):
        runtime = PROJECT_ROOT / "runtime.txt"
        assert runtime.exists(), "runtime.txt must exist at the repository root"
        assert runtime.read_text(encoding="utf-8").strip() == "python-3.12"

    def test_python_version_file_matches(self):
        version_file = PROJECT_ROOT / ".python-version"
        assert version_file.exists(), ".python-version must exist for uv-based builders"
        assert version_file.read_text(encoding="utf-8").strip() == "3.12"


class TestRequirements:
    def test_runtime_requirements_are_minimal(self):
        runtime_reqs = _requirement_names(PROJECT_ROOT / "requirements.txt")
        required = {"streamlit", "pandas", "numpy", "plotly", "requests", "pycountry"}
        assert required.issubset(runtime_reqs)

    def test_test_only_packages_not_in_runtime_requirements(self):
        runtime_reqs = _requirement_names(PROJECT_ROOT / "requirements.txt")
        for pkg in ("pytest", "pyflakes", "nbformat", "jupyter", "ipykernel"):
            assert pkg not in runtime_reqs, f"{pkg} must not be a runtime dependency"

    def test_dev_requirements_exist_and_include_test_tooling(self):
        dev_path = PROJECT_ROOT / "requirements-dev.txt"
        assert dev_path.exists()
        dev_reqs = _requirement_names(dev_path)
        assert {"pytest", "nbformat"}.issubset(dev_reqs)

    def test_no_python_314_only_constraints(self):
        text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "python_version >= \"3.13\"" not in text
        assert "3.14" not in text

    def test_all_pins_are_valid(self):
        for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert "==" in line, f"Runtime dependency must be pinned: {line}"
            name, version = line.split("==", 1)
            assert name.strip() and version.strip()
            assert " " not in name.strip()


class TestDashboardStartup:
    def test_app_does_not_run_etl_at_import_time(self):
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        module_level_calls = []
        for node in tree.body:
            # Function/class bodies are deferred; `if`/`with` blocks are UI event
            # handlers (e.g. the Refresh Data button) and are user-triggered.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    module_level_calls.append(ast.unparse(sub.func))
        for forbidden in ("WHOETLPipeline", "svc.trigger_live_refresh", "svc.load_full_dataset"):
            assert not any(
                forbidden in call for call in module_level_calls
            ), f"{forbidden} must not be invoked at import time"

    def test_app_uses_controlled_cached_loader(self):
        source = APP_PATH.read_text(encoding="utf-8")
        assert "svc.load_dashboard_data" in source
        assert "@st.cache_data" in source

    def test_app_declares_all_required_status_labels(self):
        source = APP_PATH.read_text(encoding="utf-8")
        for label in (
            "LIVE",
            "DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS",
            "STALE REAL DATA",
            "LIVE DATA UNAVAILABLE",
        ):
            assert label in source, f"Dashboard must display the {label} status"

    def test_app_has_no_hardcoded_local_paths(self):
        source = APP_PATH.read_text(encoding="utf-8")
        for bad in ("C:\\", "D:\\", "/Users/", "/home/"):
            assert bad not in source


class TestControlledLoader:
    def test_auto_bootstrap_default_enabled(self, monkeypatch):
        monkeypatch.delenv("WHO_AUTO_BOOTSTRAP", raising=False)
        assert svc.auto_bootstrap_enabled() is True

    def test_auto_bootstrap_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("WHO_AUTO_BOOTSTRAP", "false")
        assert svc.auto_bootstrap_enabled() is False

    def test_database_has_records_false_for_missing_file(self, tmp_path):
        assert svc.database_has_records(str(tmp_path / "missing.db")) is False

    def test_live_mode_api_failure_returns_no_synthetic_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHO_DATA_MODE", "live")
        monkeypatch.setattr(
            svc,
            "trigger_live_refresh",
            lambda db_path=None, indicators=None: {
                "success": False,
                "status": "failed",
                "failure_reason": "API failed and no cached real snapshot",
            },
        )
        df, meta = svc.load_dashboard_data(str(tmp_path / "no_such.db"))
        assert df.empty, "LIVE mode must never substitute synthetic data"
        assert meta["bootstrap_attempted"] is True
        assert "API failed" in str(meta.get("failure_reason"))

    def test_demo_mode_does_not_trigger_live_extraction(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHO_DATA_MODE", "demo")
        called = {"value": False}

        def _fail(*_args, **_kwargs):
            called["value"] = True
            raise AssertionError("DEMO mode must not call the live API")

        monkeypatch.setattr(svc, "trigger_live_refresh", _fail)
        df, _meta = svc.load_dashboard_data(str(tmp_path / "no_such.db"))
        assert df.empty
        assert called["value"] is False

    def test_bootstrap_disabled_skips_extraction(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHO_DATA_MODE", "live")
        monkeypatch.setenv("WHO_AUTO_BOOTSTRAP", "false")
        monkeypatch.setattr(
            svc,
            "trigger_live_refresh",
            lambda *a, **k: pytest.fail("extraction must be skipped"),
        )
        df, meta = svc.load_dashboard_data(str(tmp_path / "no_such.db"))
        assert df.empty
        assert meta["bootstrap_attempted"] is False


class TestEnvironmentDocumentation:
    def test_env_example_documents_required_variables(self):
        text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        for key in (
            "WHO_DATA_MODE=live",
            "WHO_API_BASE_URL=https://ghoapi.azureedge.net/api/",
            "WHO_API_TIMEOUT=30",
            "WHO_API_MAX_RETRIES=3",
            "WHO_REFRESH_TTL=3600",
            "WHO_DB_PATH=data/who_health_data.db",
        ):
            assert key in text, f"{key} must be documented in .env.example"

    def test_env_example_has_no_windows_paths(self):
        text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "C:\\" not in text and "D:\\" not in text


class TestDashboardRenderedStates:
    """End-to-end render checks using Streamlit's headless AppTest harness."""

    @staticmethod
    def _render_text(monkeypatch, mode: str, db_path: str) -> str:
        pytest.importorskip("streamlit.testing.v1")
        from streamlit.testing.v1 import AppTest

        monkeypatch.setenv("WHO_DATA_MODE", mode)
        monkeypatch.setenv("WHO_DB_PATH", db_path)
        monkeypatch.setenv("WHO_AUTO_BOOTSTRAP", "false")
        app = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
        assert not app.exception, f"Dashboard raised before rendering: {app.exception}"
        return " ".join(
            [m.value for m in app.markdown]
            + [e.value for e in app.error]
            + [i.value for i in app.info]
        )

    def test_live_mode_without_snapshot_reports_unavailable(self, tmp_path, monkeypatch):
        text = self._render_text(monkeypatch, "live", str(tmp_path / "missing.db"))
        assert "LIVE DATA UNAVAILABLE" in text
        assert "DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS" not in text

    def test_demo_mode_shows_explicit_demo_banner(self, tmp_path, monkeypatch):
        text = self._render_text(monkeypatch, "demo", str(tmp_path / "missing.db"))
        assert "DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS" in text

    def test_live_mode_with_real_snapshot_renders_status_panel(self, tmp_path, monkeypatch):
        from src.who_health_intelligence.etl.loader import DatabaseLoader

        db_path = tmp_path / "snapshot.db"
        rows = []
        for code, name, continent in (
            ("USA", "United States", "Americas"),
            ("GBR", "United Kingdom", "Europe"),
            ("NGA", "Nigeria", "Africa"),
        ):
            for year in (2019, 2020):
                rows.append(
                    {
                        "country_code": code,
                        "country_name": name,
                        "continent": continent,
                        "year": year,
                        "gender": "Both sexes",
                        "indicator": "LIFE_EXPECTANCY",
                        "indicator_code": "WHOSIS_000001",
                        "value": 70.0 + year % 10,
                        "unit": "years",
                        "source": "WHO GHO OData API https://ghoapi.azureedge.net/api/WHOSIS_000001",
                        "extracted_at": "2026-01-01T00:00:00Z",
                        "pipeline_version": "4.0.0",
                    }
                )
        loader = DatabaseLoader(str(db_path))
        loader.load_all_indicators(pd.DataFrame(rows), replace_all=True)
        loader.log_source_info(
            source_name="WHO GHO OData API",
            source_url="https://ghoapi.azureedge.net/api/",
            total_extracted=len(rows),
            total_loaded=len(rows),
            indicators=["LIFE_EXPECTANCY"],
            status="success",
        )
        loader.log_etl_run(
            indicator="LIFE_EXPECTANCY",
            records_loaded=len(rows),
            status="success",
            duration_seconds=1.0,
        )

        text = self._render_text(monkeypatch, "live", str(db_path))
        assert "Data Status Panel" in text
        assert "Refresh Data" in text
        assert "DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS" not in text
