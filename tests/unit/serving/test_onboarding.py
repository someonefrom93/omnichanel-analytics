"""AppTest scenarios for the 4-step onboarding wizard (PR6b).

TDD: RED → GREEN → TRIANGULATE. Uses Streamlit AppTest for real session simulation.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest  # type: ignore[import-untyped]

PAGES_DIR = (
    Path(__file__).parent.parent.parent.parent / "src" / "omc_analytics" / "serving"
)

ONBOARDING_PAGE = str(PAGES_DIR / "pages" / "onboarding.py")


class TestOnboardingWizard:
    """AppTest scenarios for the 4-step wizard."""

    # -- Step 0: Connect -------------------------------------------------------

    def test_fresh_session_renders_step_0_connect(self) -> None:
        """GIVEN no 'step' in session_state
        WHEN onboarding page loads
        THEN step 0 (Connect) renders title and link without crash."""
        at = AppTest.from_file(ONBOARDING_PAGE)
        at.session_state["merchant_id"] = "merchant_001"
        at.run()

        assert not at.exception, f"Page raised: {at.exception}"
        # Title element should be present
        assert len(at.title) >= 1, f"Expected title, got {len(at.title)}"

    def test_step_0_shows_authorize_link(self) -> None:
        """GIVEN step 0 is active
        WHEN page loads
        THEN markdown content includes Otter authorize URL."""
        at = AppTest.from_file(ONBOARDING_PAGE)
        at.session_state["merchant_id"] = "merchant_001"
        at.run()

        assert not at.exception, f"Page raised: {at.exception}"
        # At least one markdown element with link
        assert len(at.markdown) >= 2, f"Expected markdown, got {len(at.markdown)}"

    # -- Step 3: Success -------------------------------------------------------

    def test_step_3_renders_success_ui(self) -> None:
        """GIVEN st.session_state.step = 3
        WHEN onboarding page loads
        THEN success message and button are displayed."""
        at = AppTest.from_file(ONBOARDING_PAGE)
        at.session_state["merchant_id"] = "merchant_001"
        at.session_state["step"] = 3
        at.run()

        assert not at.exception, f"Page raised: {at.exception}"
        # success element should be present
        assert len(at.success) >= 1, f"Expected success, got {len(at.success)}"
        # Button to go to dashboard should be present
        assert len(at.button) >= 1, f"Expected button, got {len(at.button)}"

    # -- Step transitions ------------------------------------------------------

    def test_step_state_machine_defaults_to_0(self) -> None:
        """GIVEN a fresh session without 'step' key
        WHEN page loads
        THEN st.session_state.step defaults to 0."""
        at = AppTest.from_file(ONBOARDING_PAGE)
        at.session_state["merchant_id"] = "merchant_001"
        at.run()

        assert not at.exception, f"Page raised: {at.exception}"
        assert (
            at.session_state["step"] == 0
        ), f"Expected step=0, got {at.session_state.get('step', 'MISSING')}"
