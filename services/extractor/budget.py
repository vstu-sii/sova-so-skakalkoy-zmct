"""Atomic per-owner daily budgets for the single-worker Delivery prototype."""
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass
class Usage:
    requests: int = 0
    tokens: int = 0


@dataclass
class Reservation:
    usage: Usage
    tokens: int
    tier: str
    reason: str
    settled: bool = False


class DailyBudget:
    def __init__(self, standard, economy, *, day=None):
        if any(x < 0 for x in (*standard, *economy)):
            raise ValueError("daily limits must be nonnegative")
        self.limits = {"standard": standard, "economy": economy}
        self.day = day or (lambda: datetime.now(timezone.utc).date())
        self.current_day = None
        self.usage = {}
        self.lock = Lock()

    def reserve(self, owner, tokens):
        if tokens <= 0:
            raise ValueError("token reservation must be positive")
        with self.lock:
            today = self.day()
            if today != self.current_day:
                self.current_day = today
                self.usage.clear()
            reason = "within_budget"
            for tier, (request_limit, token_limit) in self.limits.items():
                usage = self.usage.setdefault((owner, tier), Usage())
                if usage.requests >= request_limit or usage.tokens + tokens > token_limit:
                    if tier == "standard":
                        reason = "requests" if usage.requests >= request_limit else "tokens"
                    continue
                usage.requests += 1
                usage.tokens += tokens
                return Reservation(usage, tokens, tier, reason), reason
            return None, reason

    def settle(self, reservation, actual_tokens):
        """Missing or invalid accounting retains the worst-case reservation."""
        with self.lock:
            if reservation.settled:
                raise ValueError("reservation already settled")
            reservation.settled = True
            if type(actual_tokens) is int and actual_tokens >= 0:
                reservation.usage.tokens += actual_tokens - reservation.tokens
