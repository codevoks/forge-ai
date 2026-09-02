"""Hierarchical rate/token/currency budgets: tenant/workspace daily ceilings
nesting per-operation reservations. Reservation is atomic (a single
conditional `UPDATE` in `infrastructure/budget_repositories.py`), so
concurrent operations racing against the same ceiling can never both
succeed past the limit. Reserve happens before work; settle/release
happen after — actual usage never silently exceeds what was reserved
without a corresponding ledger adjustment.

The auto-provisioned default policy caps `max_currency_minor_per_day` at
zero: any component that has not been given an explicit, higher policy
can never spend real money, matching the zero-cost default everywhere
else in Forge. Deterministic fake providers/tools estimate and settle
zero currency, so the budget machinery is fully exercised (real atomic
reservations, real usage counters) without ever tripping that ceiling.
"""

from dataclasses import dataclass
from enum import StrEnum

DEFAULT_MAX_REQUESTS_PER_DAY = 100_000
DEFAULT_MAX_TOKENS_PER_DAY = 10_000_000
DEFAULT_MAX_CURRENCY_MINOR_PER_DAY = 0


class BudgetScope(StrEnum):
    TENANT = "tenant"
    WORKSPACE = "workspace"


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"


@dataclass(frozen=True)
class BudgetEstimate:
    requests: int = 1
    tokens: int = 0
    currency_minor: int = 0

    def __post_init__(self) -> None:
        if self.requests < 0 or self.tokens < 0 or self.currency_minor < 0:
            raise ValueError("Budget estimates must be non-negative.")
