"""Tests for omc_analytics package skeleton."""

from __future__ import annotations

import pkgutil


class TestPackageSkeleton:
    """Verify the omc_analytics package and all subpackages are importable."""

    def test_omc_analytics_package_importable(self) -> None:
        """The root omc_analytics package must be importable."""
        import omc_analytics

        assert hasattr(omc_analytics, "__name__")
        assert omc_analytics.__name__ == "omc_analytics"

    def test_common_subpackage_importable(self) -> None:
        """The common subpackage must be importable."""
        import omc_analytics.common

        assert hasattr(omc_analytics.common, "__name__")

    def test_ingestion_subpackage_importable(self) -> None:
        """The ingestion subpackage must be importable."""
        import omc_analytics.ingestion

        assert hasattr(omc_analytics.ingestion, "__name__")

    def test_transformation_subpackage_importable(self) -> None:
        """The transformation subpackage must be importable."""
        import omc_analytics.transformation

        assert hasattr(omc_analytics.transformation, "__name__")

    def test_serving_subpackage_importable(self) -> None:
        """The serving subpackage must be importable."""
        import omc_analytics.serving

        assert hasattr(omc_analytics.serving, "__name__")

    def test_all_four_subpackages_present(self) -> None:
        """All four subpackages must exist under omc_analytics."""
        import omc_analytics

        expected = {"common", "ingestion", "transformation", "serving"}
        # Use pkgutil to discover subpackages
        discovered = {
            name
            for _, name, ispkg in pkgutil.iter_modules(omc_analytics.__path__)
            if ispkg
        }
        assert expected.issubset(
            discovered
        ), f"Missing subpackages: {expected - discovered}"

    def test_python_import_succeeds(self) -> None:
        """python -c 'import omc_analytics' must succeed."""
        import subprocess

        result = subprocess.run(
            ["python", "-c", "import omc_analytics"],
            cwd="/Users/juanangeleshernandez/Desktop/mvp_test/omc-analytics",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"import omc_analytics failed:\n{result.stderr}"
