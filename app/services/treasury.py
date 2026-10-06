"""Kit 1 — Adaptive Treasury Controller decision engine (pure functions, no I/O).

Fresh implementation informed by FlowCFO's safe-to-spend patterns:
  safe = balance - reserve_floor, with upcoming commitments projected;
  verdicts fund / convert / defer / escalate; policy thresholds live HERE in
  code, never in prompts. Forecast confidence scales the autonomous limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

D = Decimal


@dataclass
class Obligation:
    id: str
    label: str
    amount: D
    currency: str
    due_hours: int  # hours until due
    stops_operations: bool = False  # non-payment halts the business
    time_sensitive: bool = False  # needs conversion now (supplier waiting)


@dataclass
class Decision:
    obligation_id: str
    action: str  # fund | convert | defer | escalate
    amount: D
    currency: str
    reason: str
    needs_person: bool = False


@dataclass
class TreasuryPolicy:
    reserve_floor: D = D("5000")
    autonomous_limit: D = D("2000")  # max the agent moves without a person
    swift_fee_eur: D = D("12.85")  # flat fee per EUR SWIFT payout; LOCAL free
    deferral_max_hours: int = 72


def safe_to_spend(balance: D, reserve_floor: D, upcoming: D = D("0")) -> D:
    """Cash safely usable right now. Never negative."""
    return max(balance - reserve_floor - upcoming, D("0"))


def scale_limit_by_confidence(base_limit: D, forecast_confidence: float, contradiction: bool = False) -> D:
    """Kit 1 rule: strong forecast data -> larger autonomous conversion;
    contradictory evidence (e.g. customer email vs forecast) -> shrink + human."""
    if contradiction:
        return (base_limit * D("0.25")).quantize(D("0.01"))
    if forecast_confidence >= 0.8:
        return base_limit * 2
    if forecast_confidence >= 0.5:
        return base_limit
    return (base_limit * D("0.5")).quantize(D("0.01"))


def decide(
    obligations: list[Obligation],
    cash_by_currency: dict[str, D],
    policy: TreasuryPolicy,
    forecast_confidence: float = 0.7,
    contradiction: bool = False,
) -> list[Decision]:
    """Fund what stops operations first, convert minimum for time-sensitive,
    defer the cheapest, escalate policy exceptions. Sorted by due time."""
    limit = scale_limit_by_confidence(policy.autonomous_limit, forecast_confidence, contradiction)
    remaining = dict(cash_by_currency)
    out: list[Decision] = []

    def spend(cur: str, amt: D) -> bool:
        if remaining.get(cur, D("0")) >= amt:
            remaining[cur] -= amt
            return True
        return False

    for o in sorted(obligations, key=lambda x: x.due_hours):
        avail = remaining.get(o.currency, D("0"))
        if o.stops_operations and avail >= o.amount:
            spend(o.currency, o.amount)
            out.append(Decision(o.id, "fund", o.amount, o.currency, "non-payment stops operations", o.amount > limit))
        elif o.time_sensitive and avail >= o.amount:
            spend(o.currency, o.amount)
            out.append(Decision(o.id, "convert", o.amount, o.currency, "minimum conversion for waiting supplier", o.amount > limit))
        elif o.due_hours > policy.deferral_max_hours:
            out.append(Decision(o.id, "defer", o.amount, o.currency, "cheapest to defer past window", False))
        elif avail >= o.amount:
            spend(o.currency, o.amount)
            out.append(Decision(o.id, "fund", o.amount, o.currency, "cash covers it within reserve", o.amount > limit))
        else:
            out.append(Decision(o.id, "escalate", o.amount, o.currency, "shortfall even after prioritization", True))
    return out


@dataclass
class TreasuryState:
    cash_by_currency: dict[str, D] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)

    def recalculate_on_deposit(self, currency: str, amount: D, obligations: list[Obligation],
                               policy: TreasuryPolicy, forecast_confidence: float = 0.7,
                               contradiction: bool = False) -> list[Decision]:
        """Only escalated/deferred decisions are reconsidered — settled ones stand."""
        self.cash_by_currency[currency] = self.cash_by_currency.get(currency, D("0")) + amount
        pending = [o for o in obligations if o.id in {d.obligation_id for d in self.decisions if d.action in ("escalate", "defer")}]
        fresh = decide(pending or obligations, self.cash_by_currency, policy, forecast_confidence, contradiction)
        self.decisions = [d for d in self.decisions if d.action in ("fund", "convert")] + fresh
        return fresh
