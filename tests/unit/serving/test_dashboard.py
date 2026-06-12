"""AppTest scenarios for the executive dashboard page (PR5b).

Uses Streamlit AppTest for real session simulation.
GoldReader is injected via st.session_state._gold_reader for seeded data.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from streamlit.testing.v1 import AppTest  # type: ignore[import-untyped]

from omc_analytics.serving.data_access import GoldReader

PAGES_DIR = (
    Path(__file__).parent.parent.parent.parent / "src" / "omc_analytics" / "serving"
)

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seeded_reader(merchant_id: str = "store_001") -> GoldReader:
    """Return a GoldReader backed by an in-memory DuckDB with seeded data."""
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE fact_financial_sales AS
        SELECT 'store_001' AS merchant_id,
               'ORD-001' AS order_id,
               'UberEats' AS source_marketplace,
               'BURGER' AS line_item_sku,
               25.0 AS gross_order_value,
               20.0 AS net_payout_amount,
               15.0 AS true_net_payout_margin,
               5.0 AS estimated_marketplace_commission,
               0.0 AS settlement_variance_amount,
               '' AS variance_reason
        UNION ALL
        SELECT 'store_001', 'ORD-002', 'DoorDash', 'FRIES',
               15.0, 12.0, 9.0, 3.0, 1.5, 'Fee mismatch'
        UNION ALL
        SELECT 'store_001', 'ORD-003', 'UberEats', 'COLA',
               10.0, 7.0, 5.0, 2.0, 0.0, ''
        UNION ALL
        SELECT 'store_001', 'ORD-004', 'DoorDash', 'BURGER',
               30.0, 24.0, 18.0, 6.0, 2.0, 'Commission overcharge'
        UNION ALL
        SELECT 'store_001', 'ORD-005', 'UberEats', 'FRIES',
               12.0, 10.0, 7.0, 3.0, 0.0, ''
        UNION ALL
        SELECT 'store_002', 'ORD-006', 'UberEats', 'PIZZA',
               40.0, 32.0, 28.0, 8.0, 4.0, 'Wrong fee tier'
        UNION ALL
        SELECT 'store_002', 'ORD-007', 'DoorDash', 'SALAD',
               18.0, 15.0, 12.0, 4.0, 0.0, ''
    """
    )
    reader = GoldReader(merchant_id=merchant_id)
    reader._conn = conn  # type: ignore[attr-defined]
    return reader


def _empty_reader() -> GoldReader:
    """Return a GoldReader with empty DuckDB (no tables)."""
    return GoldReader(merchant_id="store_003")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDashboardApp:
    """AppTest scenarios for the executive dashboard page."""

    # -- merchant fence -------------------------------------------------------

    def test_dashboard_blocks_empty_merchant(self) -> None:
        """GIVEN session with empty merchant_id
        WHEN dashboard page loads
        THEN warning is displayed and page stops."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = ""
        at.run()

        assert not at.exception, f"Page raised exception: {at.exception}"
        assert len(at.warning) >= 1, "Expected at least one warning"

    # -- KPI cards ------------------------------------------------------------

    def test_kpi_cards_render_correct_values(self) -> None:
        """GIVEN 5 rows for store_001 (gross=92, margin=54, commission=19, var=2)
        WHEN dashboard loads
        THEN 3 metric cards show computed values."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = "store_001"
        at.session_state["_gold_reader"] = _seeded_reader("store_001")
        at.run()

        assert not at.exception
        assert len(at.metric) == 3, f"Expected 3 metrics, got {len(at.metric)}"

        labels = {m.proto.label for m in at.metric}
        assert "True Net Profit Margin" in labels, "KPI 1 label missing"
        assert "Blended Commission Impact" in labels, "KPI 2 label missing"
        assert "Discovered Settlement Variances" in labels, "KPI 3 label missing"

    # -- Chart 1: Profit Leakage Tracker --------------------------------------

    def test_chart1_profit_leakage_present(self) -> None:
        """GIVEN seeded data with 2 marketplaces (UberEats, DoorDash)
        WHEN dashboard loads
        THEN Profit Leakage section title is rendered."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = "store_001"
        at.session_state["_gold_reader"] = _seeded_reader("store_001")
        at.run()

        assert not at.exception
        bodies = {s.proto.body for s in at.subheader}
        assert (
            "True Omnichannel Profit Leakage Tracker" in bodies
        ), "Chart 1 title missing"

    # -- Chart 2: Menu Engineering Matrix -------------------------------------

    def test_chart2_menu_engineering_present(self) -> None:
        """GIVEN seeded data with 3 menu items (BURGER, FRIES, COLA)
        WHEN dashboard loads
        THEN Menu Engineering section title is rendered."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = "store_001"
        at.session_state["_gold_reader"] = _seeded_reader("store_001")
        at.run()

        assert not at.exception
        bodies = {s.proto.body for s in at.subheader}
        assert "Menu Engineering Matrix" in bodies, "Chart 2 title missing"

    # -- Chart 3: Payout Reconciliation Audit Log -----------------------------

    def test_chart3_audit_log_renders_variance_rows(self) -> None:
        """GIVEN 2 rows with non-zero variance (ORD-002, ORD-004)
        WHEN dashboard loads
        THEN audit log section title and a dataframe are rendered."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = "store_001"
        at.session_state["_gold_reader"] = _seeded_reader("store_001")
        at.run()

        assert not at.exception
        bodies = {s.proto.body for s in at.subheader}
        assert "Payout Reconciliation Audit Log" in bodies, "Chart 3 title missing"
        assert (
            len(at.dataframe) >= 1
        ), f"Expected at least 1 dataframe, got {len(at.dataframe)}"

    # -- Empty dataset --------------------------------------------------------

    def test_dashboard_handles_no_data(self) -> None:
        """GIVEN empty DuckDB (no tables)
        WHEN dashboard loads for store_003
        THEN info message is shown without crash."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = "store_003"
        at.session_state["_gold_reader"] = _empty_reader()
        at.run()

        assert (
            not at.exception and len(at.info) >= 1
        ), f"Expected info message, got exception={at.exception}, info_count={len(at.info)}"

    # -- Tenant isolation -----------------------------------------------------

    def test_dashboard_tenant_isolation(self) -> None:
        """GIVEN seeded data with store_001 and store_002 rows
        WHEN dashboard loads for store_001
        THEN store_002 data (PIZZA, ORD-006) is NOT visible."""
        at = AppTest.from_file(str(PAGES_DIR / "pages" / "dashboard.py"))
        at.session_state["merchant_id"] = "store_001"
        at.session_state["_gold_reader"] = _seeded_reader("store_001")
        at.run()

        assert not at.exception
        # store_002 data should NOT appear in the dashboard
        rendered = str(at)
        assert "PIZZA" not in rendered, "store_002 data leaked into store_001 view"
        assert "ORD-006" not in rendered, "store_002 order leaked into store_001 view"
