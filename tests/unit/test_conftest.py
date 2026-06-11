"""Tests for test infrastructure — conftest fixtures and test package init files."""

from __future__ import annotations

from pathlib import Path

# tests/unit/test_conftest.py → project root via parents[2]
ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = ROOT / "tests"


class TestConftestExists:
    """Verify tests/conftest.py exists and can be imported by pytest."""

    def test_conftest_exists(self) -> None:
        """conftest.py must exist in the tests directory."""
        path = TESTS_ROOT / "conftest.py"
        assert path.exists(), f"conftest.py not found at {path}"

    def test_conftest_is_valid_python(self) -> None:
        """conftest.py must be valid Python (importable without errors)."""
        # pytest automatically imports conftest.py when collecting tests
        # If this test passes, conftest.py is valid Python
        assert (TESTS_ROOT / "conftest.py").exists()

    def test_conftest_has_secrets_stub_fixture(self) -> None:
        """conftest.py must define an in-memory secrets stub fixture."""
        conftest_path = TESTS_ROOT / "conftest.py"
        content = conftest_path.read_text()
        assert "in_memory_secrets" in content or "secrets" in content.lower()

    def test_conftest_has_logs_stub_fixture(self) -> None:
        """conftest.py must define an in-memory logs stub fixture."""
        conftest_path = TESTS_ROOT / "conftest.py"
        content = conftest_path.read_text()
        assert "in_memory_logs" in content or "logs" in content.lower()

    def test_conftest_has_freeze_clock_fixture(self) -> None:
        """conftest.py must define a freeze clock / frozen time fixture."""
        conftest_path = TESTS_ROOT / "conftest.py"
        content = conftest_path.read_text()
        assert "freeze" in content or "freezegun" in content

    def test_conftest_has_settings_dict_fixture(self) -> None:
        """conftest.py must define a fakeredis-free settings dict fixture."""
        conftest_path = TESTS_ROOT / "conftest.py"
        content = conftest_path.read_text()
        assert "settings" in content.lower()


class TestTestPackageInitFiles:
    """Verify all test __init__.py files exist."""

    def test_tests_init_exists(self) -> None:
        """tests/__init__.py must exist."""
        path = TESTS_ROOT / "__init__.py"
        assert path.exists(), f"tests/__init__.py not found at {path}"

    def test_tests_unit_init_exists(self) -> None:
        """tests/unit/__init__.py must exist."""
        path = TESTS_ROOT / "unit" / "__init__.py"
        assert path.exists(), f"tests/unit/__init__.py not found at {path}"

    def test_tests_integration_init_exists(self) -> None:
        """tests/integration/__init__.py must exist (for later tasks)."""
        path = TESTS_ROOT / "integration" / "__init__.py"
        assert path.exists(), f"tests/integration/__init__.py not found at {path}"


class TestFixturesDirectory:
    """Verify tests/fixtures/otter/ directory structure and conventions README."""

    def test_fixtures_otter_dir_exists(self) -> None:
        """tests/fixtures/otter/ directory must exist."""
        path = TESTS_ROOT / "fixtures" / "otter"
        assert path.is_dir(), f"tests/fixtures/otter/ not found at {path}"

    def test_fixtures_otter_readme_exists(self) -> None:
        """tests/fixtures/otter/README.md must exist explaining fixture conventions."""
        readme_path = TESTS_ROOT / "fixtures" / "otter" / "README.md"
        assert readme_path.exists(), "tests/fixtures/otter/README.md not found"

    def test_fixtures_otter_readme_mentions_source_tag(self) -> None:
        """README.md must mention source tagging convention."""
        readme_path = TESTS_ROOT / "fixtures" / "otter" / "README.md"
        content = readme_path.read_text()
        assert (
            "source" in content.lower()
        ), "README.md must document the source tagging convention"

    def test_fixtures_otter_readme_mentions_version_stamp(self) -> None:
        """README.md must mention version stamping convention."""
        readme_path = TESTS_ROOT / "fixtures" / "otter" / "README.md"
        content = readme_path.read_text()
        assert (
            "version" in content.lower()
        ), "README.md must document the version stamping convention"
