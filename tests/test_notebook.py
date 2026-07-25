"""
Tests for the notebook generator (scripts/generate_notebook.py) - Production LIVE mode.

Verifies that generated notebook:
- Is valid nbformat 4
- Contains required sections (including LIVE/DEMO handling)
- Has no hardcoded Windows paths
- Uses pathlib
- Supports LIVE/DEMO modes (SAMPLE_MODE backward compat + DEMO_MODE)
- Imports from source modules, shows extraction timestamp, source URL, indicator definitions, quality results
- Validates with nbformat
"""

import json
import sys
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="module")
def generated_notebook(tmp_path_factory):
    output = tmp_path_factory.mktemp("notebooks") / "test_notebook.ipynb"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_notebook.py"), "--output", str(output)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"Notebook generation failed: {result.stderr}\n{result.stdout}"
    assert output.exists(), "Notebook file was not created"
    with open(output, "r", encoding="utf-8") as f:
        nb = json.load(f)
    return nb


class TestNotebookValidity:
    def test_is_valid_nbformat(self, generated_notebook):
        import nbformat
        nbformat.validate(generated_notebook)

    def test_has_cells(self, generated_notebook):
        assert len(generated_notebook["cells"]) > 0

    def test_has_code_and_markdown_cells(self, generated_notebook):
        cell_types = {c["cell_type"] for c in generated_notebook["cells"]}
        assert "code" in cell_types
        assert "markdown" in cell_types

    def test_kernel_metadata(self, generated_notebook):
        assert "kernelspec" in generated_notebook["metadata"]
        assert generated_notebook["metadata"]["kernelspec"]["language"] == "python"


class TestRequiredSections:
    # Old sections + new LIVE/DEMO sections should be present - flexible substring matching
    EXPECTED_SECTIONS_SUBSTRINGS = [
        "Project Overview",
        "Research and Engineering Objective",
        "WHO API Source",  # covers both old and new official defs
        "Indicator Definitions",
        "Environment Setup",
        "Robust API Extraction",
        "Retry",  # covers "Retry and Error Handling" and new "API Client Features — Retry, Timeout, Error Handling"
        "Error Handling",
        "Raw Response Inspection",
        "Schema Validation",
        "Data Transformation",
        "Missing",  # missing-value analysis
        "Country and Geographic",  # covers new heading "Country and Geographic Metadata"
        "Geographic Metadata",
        "Memory Optimization",
        "SQLite Loading",
        "Data Quality Report",
        "Exploratory Analysis",
        "Interactive Visualization",
        "Limitations",
        "Conclusion",
    ]

    def test_all_sections_present(self, generated_notebook):
        headings = []
        for cell in generated_notebook["cells"]:
            if cell["cell_type"] == "markdown":
                src = cell["source"]
                if isinstance(src, list):
                    src = "".join(src)
                for line in src.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("## "):
                        text = stripped.lstrip("#").strip()
                        if text and text[0].isdigit():
                            # Remove leading "1. "
                            parts = text.split(". ", 1)
                            if len(parts) > 1:
                                text = parts[1]
                        headings.append(text)

        for expected in self.EXPECTED_SECTIONS_SUBSTRINGS:
            found = any(expected.lower() in h.lower() for h in headings)
            assert found, f"Section containing '{expected}' not found. Headings: {headings}"

    def test_section_count(self, generated_notebook):
        headings = []
        for cell in generated_notebook["cells"]:
            if cell["cell_type"] == "markdown":
                src = cell["source"]
                if isinstance(src, list):
                    src = "".join(src)
                for line in src.splitlines():
                    if line.strip().startswith("## "):
                        headings.append(line.strip())
        assert len(headings) >= 18


class TestNoHardcodedPaths:
    def test_no_windows_paths(self, generated_notebook):
        content = json.dumps(generated_notebook)
        disallowed = ["D:\\", "D:/", "C:\\"]
        for prefix in disallowed:
            assert prefix not in content

    def test_uses_pathlib(self, generated_notebook):
        code_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "Path" in code_content or "pathlib" in code_content


class TestSourceModuleReuse:
    def test_imports_from_source(self, generated_notebook):
        code_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "from src.who_health_intelligence" in code_content or "from who_health_intelligence" in code_content

    def test_uses_api_client(self, generated_notebook):
        code_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "WHOAPIClient" in code_content

    def test_uses_etl_modules(self, generated_notebook):
        code_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "DatabaseLoader" in code_content
        assert "DataQualityReport" in code_content
        assert "transform_indicator_records" in code_content


class TestLiveDemoModes:
    def test_demo_or_live_mode_variable(self, generated_notebook):
        code_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        # New notebook uses DEMO_MODE and LIVE_MODE, old used SAMPLE_MODE - support either
        assert ("DEMO_MODE" in code_content or "LIVE_MODE" in code_content or "SAMPLE_MODE" in code_content)

    def test_sample_or_demo_mode_documented(self, generated_notebook):
        md_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "markdown"
        )
        has_demo_doc = "DEMO" in md_content or "demo" in md_content.lower()
        has_sample_doc = "SAMPLE_MODE" in md_content or "sample mode" in md_content.lower()
        has_live_doc = "LIVE" in md_content or "live" in md_content.lower()
        assert has_demo_doc or has_sample_doc or has_live_doc

    def test_shows_extraction_timestamp_and_source_url(self, generated_notebook):
        all_content = json.dumps(generated_notebook).lower()
        assert "extraction_timestamp" in all_content or "extraction timestamp" in all_content
        assert "source_url" in all_content or "source url" in all_content or "who_api_base_url" in all_content

    def test_shows_indicator_definitions(self, generated_notebook):
        all_content = json.dumps(generated_notebook)
        assert "WHO_INDICATORS" in all_content or "official_definition" in all_content.lower()

    def test_shows_data_quality_results(self, generated_notebook):
        all_content = json.dumps(generated_notebook).lower()
        assert "data_quality" in all_content or "quality report" in all_content

    def test_uses_relative_paths(self, generated_notebook):
        code_content = " ".join(
            "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        # Should use Path.cwd() or relative pathlib, not hardcoded Windows
        assert "Path" in code_content


class TestNoFabricatedResults:
    def test_no_fake_numbers_in_markdown(self, generated_notebook):
        for cell in generated_notebook["cells"]:
            if cell["cell_type"] == "markdown":
                content = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
                assert "18,096 records" not in content
                assert "The data shows exactly" not in content
