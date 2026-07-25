"""
Tests for the notebook generator (scripts/generate_notebook.py).

Verifies that the generated notebook:
- Is a valid nbformat 4 notebook
- Contains all 18 required sections
- Has no hardcoded Windows paths
- Uses pathlib for file operations
- Supports SAMPLE_MODE
- Imports from source modules
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
    """Generate a notebook and return its parsed content."""
    output = tmp_path_factory.mktemp("notebooks") / "test_notebook.ipynb"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_notebook.py"),
         "--output", str(output)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"Notebook generation failed: {result.stderr}"
    assert output.exists(), "Notebook file was not created"

    with open(output, "r", encoding="utf-8") as f:
        nb = json.load(f)
    return nb


class TestNotebookValidity:
    """Test that the generated notebook is structurally valid."""

    def test_is_valid_nbformat(self, generated_notebook):
        """Notebook should be valid nbformat 4."""
        import nbformat
        nbformat.validate(generated_notebook)

    def test_has_cells(self, generated_notebook):
        """Notebook should have cells."""
        assert len(generated_notebook["cells"]) > 0

    def test_has_code_and_markdown_cells(self, generated_notebook):
        """Notebook should have both code and markdown cells."""
        cell_types = {c["cell_type"] for c in generated_notebook["cells"]}
        assert "code" in cell_types
        assert "markdown" in cell_types

    def test_kernel_metadata(self, generated_notebook):
        """Notebook should have kernel metadata."""
        assert "kernelspec" in generated_notebook["metadata"]
        assert generated_notebook["metadata"]["kernelspec"]["language"] == "python"


class TestRequiredSections:
    """Test that all 18 required sections are present."""

    EXPECTED_SECTIONS = [
        "Project Overview",
        "Research and Engineering Objective",
        "WHO API Source and Indicator Definitions",
        "Environment Setup",
        "Robust API Extraction",
        "Retry and Error Handling",
        "Raw Response Inspection",
        "Schema Validation",
        "Data Transformation",
        "Missing-Value Analysis",
        "Country and Continent Normalization",
        "Memory Optimization",
        "SQLite Loading",
        "Data Quality Report",
        "Exploratory Analysis",
        "Interactive Visualization Examples",
        "Limitations and Reproducibility Notes",
        "Conclusion and Next Steps",
    ]

    def test_all_sections_present(self, generated_notebook):
        """All 18 required sections should be present as markdown headings."""
        # Collect all section headings from markdown cells
        headings = []
        for cell in generated_notebook["cells"]:
            if cell["cell_type"] == "markdown":
                for line in cell["source"]:
                    stripped = line.strip()
                    if stripped.startswith("## "):
                        # Remove "## " and any leading number like "1. "
                        text = stripped.lstrip("#").strip()
                        # Remove leading number prefix
                        if text and text[0].isdigit():
                            text = text.split(". ", 1)[-1]
                        headings.append(text)

        for expected in self.EXPECTED_SECTIONS:
            found = any(expected.lower() in h.lower() for h in headings)
            assert found, f"Section '{expected}' not found. Headings found: {headings}"

    def test_section_count(self, generated_notebook):
        """Should have at least 18 sections."""
        headings = []
        for cell in generated_notebook["cells"]:
            if cell["cell_type"] == "markdown":
                for line in cell["source"]:
                    if line.strip().startswith("## "):
                        headings.append(line.strip())
        assert len(headings) >= 18


class TestNoHardcodedPaths:
    """Test that no hardcoded Windows paths exist."""

    def test_no_windows_paths(self, generated_notebook):
        """Should not contain D:\\ or other hardcoded Windows paths."""
        content = json.dumps(generated_notebook)
        assert "D:\\" not in content
        assert "D:/" not in content
        assert "C:\\" not in content

    def test_uses_pathlib(self, generated_notebook):
        """Should use pathlib for path operations."""
        code_content = " ".join(
            c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "Path" in code_content or "pathlib" in code_content


class TestSourceModuleReuse:
    """Test that the notebook reuses functions from source modules."""

    def test_imports_from_source(self, generated_notebook):
        """Should import from who_health_intelligence modules."""
        code_content = " ".join(
            c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "from src.who_health_intelligence" in code_content or \
               "from who_health_intelligence" in code_content

    def test_uses_api_client(self, generated_notebook):
        """Should use the WHOAPIClient from source."""
        code_content = " ".join(
            c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "WHOAPIClient" in code_content

    def test_uses_etl_modules(self, generated_notebook):
        """Should use ETL modules from source."""
        code_content = " ".join(
            c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "DatabaseLoader" in code_content
        assert "DataQualityReport" in code_content
        assert "transform_indicator_records" in code_content


class TestSampleMode:
    """Test that SAMPLE_MODE is supported."""

    def test_sample_mode_variable(self, generated_notebook):
        """Should define SAMPLE_MODE variable."""
        code_content = " ".join(
            c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            for c in generated_notebook["cells"]
            if c["cell_type"] == "code"
        )
        assert "SAMPLE_MODE" in code_content

    def test_sample_mode_documented(self, generated_notebook):
        """Should document SAMPLE_MODE in markdown."""
        md_content = " ".join(
            c["source"] if isinstance(c["source"], str) else "".join(c["source"])
            for c in generated_notebook["cells"]
            if c["cell_type"] == "markdown"
        )
        assert "SAMPLE_MODE" in md_content or "sample mode" in md_content.lower()


class TestNoFabricatedResults:
    """Test that the notebook doesn't contain fabricated results."""

    def test_no_fake_numbers_in_markdown(self, generated_notebook):
        """Markdown cells should not contain pre-computed result numbers."""
        # Check that markdown cells don't contain specific fabricated metrics
        for cell in generated_notebook["cells"]:
            if cell["cell_type"] == "markdown":
                content = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
                # Should not claim specific data results in static text
                # (these are examples of what would be fabricated)
                assert "18,096 records" not in content  # exact record count from old data
                assert "The data shows exactly" not in content
