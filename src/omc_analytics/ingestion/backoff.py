"""RetryPolicy — jittered exponential backoff pure helper.

No time.sleep, no I/O, no clock. Fully deterministic and testable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Jittered exponential backoff policy.

    Attributes:
        max_retries: Maximum number of retry attempts before giving up.
        base_seconds: Base delay in seconds (delay = base * 2^(attempt-1)).
        cap_seconds: Maximum delay cap in seconds.
        jitter: If True, applies full jitter (random in [0, computed_delay]).
    """

    max_retries: int
    base_seconds: float
    cap_seconds: float = 60.0
    jitter: bool = True

    def wait_for(self, attempt: int) -> float:
        """Return the delay to wait for the given attempt number.

        Pure function — returns a float without performing any I/O or sleeping.
        With jitter=True: returns a random value in [0, computed_delay].
        With jitter=False: returns the computed delay exactly.
        """
        computed = min(self.base_seconds * (2 ** (attempt - 1)), self.cap_seconds)
        if self.jitter:
            return random.random() * computed
        return computed

    def should_retry(self, attempt: int) -> bool:
        """Return True if the given attempt number should trigger a retry."""
        return attempt < self.max_retries
