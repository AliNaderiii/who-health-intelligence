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

    def test_statsmodels_is_not_a_runtime_dependency(self):
        """
        statsmodels imports scipy internals (`scipy._lib._util._lazywhere`) that were
        removed in newer scipy releases. Shipping it broke the correlation tab in
        production, so it must stay out of the runtime requirement set.
        """
        runtime_reqs = _requirement_names(PROJECT_ROOT / "requirements.txt")
        assert "statsmodels" not in runtime_reqs
        assert "scipy" not in runtime_reqs

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


class TestNoStatsmodelsInProductionCode:
    """
    Regression guard for the Streamlit Cloud crash:
        ImportError: cannot import name '_lazywhere' from 'scipy._lib._util'

    plotly.express `trendline="ols"` imports statsmodels lazily, so the failure only
    surfaced when a user opened the correlation tab. Production code must therefore
    neither import statsmodels/scipy nor request an express trendline.
    """

    PRODUCTION_ROOTS = ("src", "scripts", "main.py", "who_etl_pipeline.py")

    @classmethod
    def _production_python_files(cls) -> list[Path]:
        files: list[Path] = []
        for entry in cls.PRODUCTION_ROOTS:
            path = PROJECT_ROOT / entry
            if path.is_file() and path.suffix == ".py":
                files.append(path)
            elif path.is_dir():
                files.extend(
                    p for p in path.rglob("*.py") if "tests" not in p.parts
                )
        return files

    def test_no_statsmodels_import_in_production_code(self):
        offenders = []
        for path in self._production_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in {"statsmodels", "scipy"}:
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {name}")
        assert not offenders, f"Production code must not import statsmodels/scipy: {offenders}"

    def test_no_plotly_express_ols_trendline(self):
        """Executable code must not pass trendline="ols" (comments may mention it)."""
        offenders = []
        for path in self._production_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "trendline":
                        continue
                    if isinstance(keyword.value, ast.Constant):
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}: trendline={keyword.value.value!r}"
                        )
        assert not offenders, f'plotly.express trendline="ols" must not be used: {offenders}'

    def test_dashboard_uses_numpy_trendline_and_scatter_trace(self):
        source = APP_PATH.read_text(encoding="utf-8")
        assert "svc.compute_ols_trendline" in source
        assert "go.Scatter" in source

    def test_trendline_helper_needs_no_statsmodels_at_runtime(self, monkeypatch):
        """The helper must work even if statsmodels cannot be imported at all."""
        import builtins

        real_import = builtins.__import__

        def _blocked(name, *args, **kwargs):
            if name.split(".")[0] in {"statsmodels", "scipy"}:
                raise ImportError(f"{name} is unavailable in production")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked)
        trend = svc.compute_ols_trendline([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0])
        assert trend is not None
        assert trend["slope"] == pytest.approx(2.0)

    def test_chart_is_labelled_as_descriptive_not_causal(self):
        source = APP_PATH.read_text(encoding="utf-8")
        assert "Descriptive association — not causal inference" in source


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


class TestCorrelationViewRendering:
    """
    End-to-end checks for the association tab, which crashed in production with
    ImportError: cannot import name '_lazywhere' from 'scipy._lib._util'
    while plotly.express resolved trendline="ols" through statsmodels.
    """

    @staticmethod
    def _build_snapshot(db_path: Path, rows: list[dict]) -> None:
        from src.who_health_intelligence.etl.loader import DatabaseLoader

        loader = DatabaseLoader(str(db_path))
        loader.load_all_indicators(pd.DataFrame(rows), replace_all=True)
        loader.log_source_info(
            source_name="WHO GHO OData API",
            source_url="https://ghoapi.azureedge.net/api/",
            total_extracted=len(rows),
            total_loaded=len(rows),
            indicators=sorted({r["indicator"] for r in rows}),
            status="success",
        )

    @staticmethod
    def _row(code: str, name: str, continent: str, year: int, indicator: str, value: float) -> dict:
        codes = {"LIFE_EXPECTANCY": "WHOSIS_000001", "UHC_COVERAGE": "UHC_INDEX_REPORTED"}
        units = {"LIFE_EXPECTANCY": "years", "UHC_COVERAGE": "index (0-100)"}
        return {
            "country_code": code,
            "country_name": name,
            "continent": continent,
            "year": year,
            "gender": "Both sexes",
            "indicator": indicator,
            "indicator_code": codes[indicator],
            "value": value,
            "unit": units[indicator],
            "source": "WHO GHO OData API https://ghoapi.azureedge.net/api/",
            "extracted_at": "2026-01-01T00:00:00Z",
            "pipeline_version": "4.0.0",
        }

    @staticmethod
    def _run_app(monkeypatch, db_path: Path):
        pytest.importorskip("streamlit.testing.v1")
        import importlib

        from streamlit.testing.v1 import AppTest

        monkeypatch.setenv("WHO_DATA_MODE", "live")
        monkeypatch.setenv("WHO_DB_PATH", str(db_path))
        monkeypatch.setenv("WHO_AUTO_BOOTSTRAP", "false")

        # DATABASE_PATH is resolved from the environment at import time and the
        # config modules are already cached by this test session, so they must be
        # reloaded for the app under test to read the temporary snapshot.
        config_modules = [
            "src.config",
            "config",
            "src.who_health_intelligence.utils.config",
            "who_health_intelligence.utils.config",
        ]

        def _reload_config() -> None:
            for module_name in config_modules:
                module = sys.modules.get(module_name)
                if module is not None:
                    importlib.reload(module)

        _reload_config()
        try:
            return AppTest.from_file(str(APP_PATH), default_timeout=180).run()
        finally:
            monkeypatch.delenv("WHO_DB_PATH", raising=False)
            _reload_config()

    @staticmethod
    def _correlation_figure_spec(app):
        import json

        for element in app.get("plotly_chart"):
            raw = getattr(element.proto, "spec", "")
            if not raw:
                continue
            spec = json.loads(raw)
            title = (spec.get("layout", {}).get("title", {}) or {}).get("text", "")
            if "Descriptive association" in title:
                return spec
        return None

    def _correlated_rows(self) -> list[dict]:
        countries = [
            ("USA", "United States", "Americas"),
            ("GBR", "United Kingdom", "Europe"),
            ("NGA", "Nigeria", "Africa"),
            ("BRA", "Brazil", "Americas"),
            ("IND", "India", "Asia"),
            ("JPN", "Japan", "Asia"),
            ("FRA", "France", "Europe"),
            ("KEN", "Kenya", "Africa"),
        ]
        rows = []
        for i, (code, name, continent) in enumerate(countries):
            for year in (2019, 2020):
                rows.append(self._row(code, name, continent, year, "LIFE_EXPECTANCY", 58.0 + i * 2.2))
                rows.append(self._row(code, name, continent, year, "UHC_COVERAGE", 35.0 + i * 4.5))
        return rows

    def test_correlation_tab_renders_without_import_error(self, tmp_path, monkeypatch):
        db_path = tmp_path / "corr.db"
        self._build_snapshot(db_path, self._correlated_rows())
        app = self._run_app(monkeypatch, db_path)

        assert not app.exception, f"Correlation view raised: {app.exception}"
        assert self._correlation_figure_spec(app) is not None, "Association chart was not rendered"

    def test_trendline_is_a_graph_objects_scatter_trace(self, tmp_path, monkeypatch):
        db_path = tmp_path / "corr.db"
        self._build_snapshot(db_path, self._correlated_rows())
        spec = self._correlation_figure_spec(self._run_app(monkeypatch, db_path))

        assert spec is not None
        ols_traces = [d for d in spec["data"] if str(d.get("name", "")).startswith("OLS fit")]
        assert len(ols_traces) == 1, "Exactly one OLS trendline trace is expected"
        assert ols_traces[0]["type"] == "scatter"
        assert ols_traces[0]["mode"] == "lines"
        assert len(ols_traces[0]["x"]) >= 2

    def test_chart_title_states_descriptive_not_causal(self, tmp_path, monkeypatch):
        db_path = tmp_path / "corr.db"
        self._build_snapshot(db_path, self._correlated_rows())
        spec = self._correlation_figure_spec(self._run_app(monkeypatch, db_path))

        assert spec is not None
        assert "Descriptive association — not causal inference" in spec["layout"]["title"]["text"]

    def test_reports_r_sample_size_year_indicators_and_missing_handling(self, tmp_path, monkeypatch):
        db_path = tmp_path / "corr.db"
        self._build_snapshot(db_path, self._correlated_rows())
        app = self._run_app(monkeypatch, db_path)

        text = " ".join([m.value for m in app.markdown])
        metric_labels = {m.label for m in app.metric}

        assert "Correlation coefficient (Pearson r)" in metric_labels
        assert "Sample size (countries)" in metric_labels
        assert "Selected year" in metric_labels
        assert "Pearson" in text
        assert "pairwise deletion" in text
        assert "Life Expectancy" in text and "UHC Coverage Index" in text
        assert "numpy.polyfit" in text
        assert "descriptive association, not causal inference" in text

    def test_insufficient_data_shows_info_and_does_not_crash(self, tmp_path, monkeypatch):
        """Only two countries report both indicators — below the 3-observation minimum."""
        db_path = tmp_path / "sparse.db"
        rows = []
        for code, name, continent in (("USA", "United States", "Americas"), ("GBR", "United Kingdom", "Europe")):
            rows.append(self._row(code, name, continent, 2020, "LIFE_EXPECTANCY", 75.0))
            rows.append(self._row(code, name, continent, 2020, "UHC_COVERAGE", 80.0))
        # A third country reporting only one indicator must be dropped pairwise.
        rows.append(self._row("NGA", "Nigeria", "Africa", 2020, "LIFE_EXPECTANCY", 55.0))
        self._build_snapshot(db_path, rows)

        app = self._run_app(monkeypatch, db_path)

        assert not app.exception, f"Sparse data must not crash the app: {app.exception}"
        infos = [i.value for i in app.info]
        assert any("Insufficient overlapping data" in i for i in infos)
        assert any("at least 3 countries" in i for i in infos)
        assert self._correlation_figure_spec(app) is None

    def test_single_year_snapshot_does_not_crash_year_selector(self, tmp_path, monkeypatch):
        """st.slider raises when min_value == max_value; the app must degrade gracefully."""
        db_path = tmp_path / "one_year.db"
        rows = [
            self._row(code, name, continent, 2020, indicator, value)
            for code, name, continent, le, uhc in (
                ("USA", "United States", "Americas", 78.0, 83.0),
                ("GBR", "United Kingdom", "Europe", 81.0, 87.0),
                ("NGA", "Nigeria", "Africa", 55.0, 42.0),
                ("IND", "India", "Asia", 70.0, 61.0),
            )
            for indicator, value in (("LIFE_EXPECTANCY", le), ("UHC_COVERAGE", uhc))
        ]
        self._build_snapshot(db_path, rows)

        app = self._run_app(monkeypatch, db_path)

        assert not app.exception, f"Single-year snapshot must not crash: {app.exception}"
        assert self._correlation_figure_spec(app) is not None
