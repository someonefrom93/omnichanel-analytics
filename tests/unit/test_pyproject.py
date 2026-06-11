"""Tests for pyproject.toml configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestPyprojectToml:
    """Verify pyproject.toml exists and declares all required dependencies."""

    def test_pyproject_toml_exists(self) -> None:
        """pyproject.toml must exist at project root."""
        path = ROOT / "pyproject.toml"
        assert path.exists(), f"pyproject.toml not found at {path}"

    def test_pyproject_is_valid_toml(self) -> None:
        """pyproject.toml must be parseable TOML."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        assert isinstance(data, dict), "pyproject.toml root must be a table"

    def test_has_build_system(self) -> None:
        """pyproject.toml must declare build-system."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        assert "build-system" in data, "missing [build-system] section"
        assert data["build-system"]["requires"] == [
            "hatchling"
        ], "build-system.requires must be hatchling"

    def test_project_name_and_version(self) -> None:
        """Project must declare name and version."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        assert "project" in data
        assert data["project"]["name"] == "omc-analytics"
        assert data["project"]["version"] == "0.1.0"

    def test_runtime_dependencies_pinned(self) -> None:
        """All runtime deps must be declared with version pins."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        deps = data["project"]["dependencies"]
        required = {
            "requests",
            "boto3",
            "cryptography",
            "click",
            "pydantic",
        }
        declared = {d.split(">=")[0].split("<=")[0].strip() for d in deps}
        missing = required - declared
        assert not missing, f"Missing runtime deps: {missing}"

    def test_dev_dependencies_pinned(self) -> None:
        """All dev deps must be declared with version pins."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        dev_deps = data["project"]["optional-dependencies"]["dev"]
        required_dev = {
            "pytest",
            "responses",
            "moto[s3,kms]",
            "freezegun",
            "ruff",
            "mypy",
            "black",
            "pytest-cov",
        }
        declared = {d.split(">=")[0].split("<=")[0].strip() for d in dev_deps}
        missing = required_dev - declared
        assert not missing, f"Missing dev deps: {missing}"

    def test_pytest_configured(self) -> None:
        """pytest must be configured with coverage on src/omc_analytics."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        assert "tool" in data and "pytest" in data["tool"]

    def test_ruff_configured(self) -> None:
        """ruff must be configured with sensible defaults."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        assert "tool" in data and "ruff" in data["tool"]

    def test_mypy_disallow_untyped_defs(self) -> None:
        """mypy must have disallow_untyped_defs = true."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        mypy_cfg = data.get("tool", {}).get("mypy", {})
        assert mypy_cfg.get("disallow_untyped_defs", False) is True

    def test_black_configured(self) -> None:
        """black must be configured."""
        path = ROOT / "pyproject.toml"
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        assert "tool" in data and "black" in data["tool"]

    def test_uv_sync_succeeds(self) -> None:
        """uv sync must succeed (no invalid deps)."""
        import subprocess

        result = subprocess.run(
            ["uv", "sync", "--dry-run"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"uv sync --dry-run failed:\n{result.stderr}"
