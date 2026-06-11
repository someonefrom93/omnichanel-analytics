"""Tests for RetryPolicy pure helper."""

from __future__ import annotations

import pytest

from omc_analytics.ingestion.backoff import RetryPolicy


class TestRetryPolicyWaitFor:
    """Test RetryPolicy.wait_for() behavior."""

    def test_wait_for_attempt_1_returns_value_in_range_of_base(self) -> None:
        """wait_for(attempt=1) returns a value in [0, base_seconds] when jitter=True."""
        policy = RetryPolicy(
            max_retries=3, base_seconds=2.0, cap_seconds=60.0, jitter=True
        )
        # With jitter, upper bound is base_seconds itself
        for _ in range(100):
            val = policy.wait_for(1)
            assert 0.0 <= val <= 2.0, f"wait_for(1)={val} outside [0, 2.0]"

    def test_wait_for_attempt_3_upper_bound_with_jitter(self) -> None:
        """wait_for(attempt=3) upper bound is base*4=8s with jitter."""
        policy = RetryPolicy(
            max_retries=5, base_seconds=2.0, cap_seconds=60.0, jitter=True
        )
        for _ in range(100):
            val = policy.wait_for(3)
            assert 0.0 <= val <= 8.0, f"wait_for(3)={val} outside [0, 8.0]"

    def test_wait_for_caps_at_cap_seconds(self) -> None:
        """wait_for respects cap_seconds even at high attempt numbers."""
        policy = RetryPolicy(
            max_retries=10, base_seconds=2.0, cap_seconds=10.0, jitter=True
        )
        for attempt in [5, 6, 7, 8, 9, 10]:
            for _ in range(50):
                val = policy.wait_for(attempt)
                assert 0.0 <= val <= 10.0, f"wait_for({attempt})={val} exceeds cap 10.0"

    def test_jitter_false_returns_exact_value(self) -> None:
        """With jitter=False, wait_for returns the computed delay exactly."""
        policy = RetryPolicy(
            max_retries=3, base_seconds=2.0, cap_seconds=60.0, jitter=False
        )
        assert policy.wait_for(1) == 2.0
        assert policy.wait_for(2) == 4.0
        assert policy.wait_for(3) == 8.0

    def test_wait_for_exponential_growth_without_jitter(self) -> None:
        """Without jitter, values grow as base * 2^(attempt-1)."""
        policy = RetryPolicy(
            max_retries=5, base_seconds=1.0, cap_seconds=60.0, jitter=False
        )
        assert policy.wait_for(1) == 1.0
        assert policy.wait_for(2) == 2.0
        assert policy.wait_for(3) == 4.0
        assert policy.wait_for(4) == 8.0

    def test_wait_for_capped_at_cap_without_jitter(self) -> None:
        """Without jitter, values cap at cap_seconds."""
        policy = RetryPolicy(
            max_retries=10, base_seconds=2.0, cap_seconds=10.0, jitter=False
        )
        # attempt 4: base*2^3 = 16, capped at 10
        assert policy.wait_for(4) == 10.0
        assert policy.wait_for(5) == 10.0


class TestRetryPolicyShouldRetry:
    """Test RetryPolicy.should_retry() behavior."""

    def test_should_retry_true_when_attempt_lt_max_retries(self) -> None:
        """should_retry returns True when attempt < max_retries."""
        policy = RetryPolicy(max_retries=3, base_seconds=1.0, cap_seconds=60.0)
        assert policy.should_retry(0) is True
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True

    def test_should_retry_false_at_max_retries_boundary(self) -> None:
        """should_retry returns False when attempt == max_retries."""
        policy = RetryPolicy(max_retries=3, base_seconds=1.0, cap_seconds=60.0)
        assert policy.should_retry(3) is False

    def test_should_retry_false_beyond_max_retries(self) -> None:
        """should_retry returns False when attempt > max_retries."""
        policy = RetryPolicy(max_retries=3, base_seconds=1.0, cap_seconds=60.0)
        assert policy.should_retry(4) is False
        assert policy.should_retry(100) is False


class TestRetryPolicyDeterministic:
    """Test that RetryPolicy is a pure function with no I/O."""

    def test_wait_for_returns_float(self) -> None:
        """wait_for always returns a float."""
        policy = RetryPolicy(
            max_retries=5, base_seconds=2.0, cap_seconds=60.0, jitter=True
        )
        val = policy.wait_for(2)
        assert isinstance(val, float)

    def test_wait_for_non_negative(self) -> None:
        """wait_for never returns a negative value."""
        policy = RetryPolicy(
            max_retries=5, base_seconds=2.0, cap_seconds=60.0, jitter=True
        )
        for attempt in range(1, 6):
            for _ in range(50):
                val = policy.wait_for(attempt)
                assert val >= 0.0, f"wait_for({attempt}) returned negative value {val}"

    def test_frozen_dataclass(self) -> None:
        """RetryPolicy is a frozen dataclass — fields cannot be mutated after creation."""
        policy = RetryPolicy(
            max_retries=3, base_seconds=2.0, cap_seconds=60.0, jitter=True
        )
        with pytest.raises(AttributeError):
            # noinspection PyPropertyAccess
            policy.max_retries = 10  # type: ignore[misc]
