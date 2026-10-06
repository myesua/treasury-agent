"""Kit 2 — Intent-Bound Purchase Agent decision + card-control payload (pure).

Same FlowCFO brain as Kit 1, different actuator: virtual-card controls.
Policy enforced by card limits/allowlists (the only thing that can actually
block an authorization), never by prompt. Model reads terms; code prices,
decides, and builds the payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass
class TermsOption:
    name: str  # "annual" | "monthly"
    total_cost: D
    weeks_until_reserve_breach: int | None  # None = never breaches


@dataclass
class PurchaseDecision:
    choice: str
    annual_saving_pct: D
    reconsider_on: str  # date string: when to revisit
    reason: str
    card_policy: dict


def evaluate_terms(
    annual_total: D,
    monthly_total_per_year: D,
    min_reserve: D,
    projected_reserve_by_week: dict[int, D],
    reconsider_weeks: int = 12,
) -> PurchaseDecision:
    """Annual is cheaper but can breach the floor; monthly preserves optionality."""
    saving = ((monthly_total_per_year - annual_total) / monthly_total_per_year * 100).quantize(D("0.1")) \
        if monthly_total_per_year > 0 else D("0")
    breach_week: int | None = None
    for week in sorted(projected_reserve_by_week):
        if projected_reserve_by_week[week] < min_reserve:
            breach_week = week
            break
    if breach_week is None:
        choice, reason = "annual", f"takes the {saving}% saving with no reserve breach in window"
    else:
        choice = "monthly"
        reason = (f"annual breaches minimum reserve in week {breach_week}; "
                  f"monthly costs more but keeps cash and the cancel option")
    return PurchaseDecision(
        choice=choice,
        annual_saving_pct=saving,
        reconsider_on=f"+{reconsider_weeks}w",
        reason=reason,
        card_policy=build_card_policy(choice),
    )


def build_card_policy(choice: str, monthly_cap: D = D("500")) -> dict:
    """Card controls that ENFORCE the decision. Amounts are major units."""
    if choice == "annual":
        return {"mode": "single_use", "per_transaction_limit": None, "note": "one annual charge, then freeze"}
    return {
        "mode": "recurring_cap",
        "per_transaction_limit": str(monthly_cap),  # inclusive: == limit clears, +0.01 fails
        "all_time_limit": str(monthly_cap * 12),
        "currency_allowlist": ["USD"],
        "merchant_categories": ["software", "saas"],
        "freeze_after": "reconsider-date",
    }


def auth_outcome(amount: D, policy: dict) -> tuple[str, str]:
    """Simulated authorization verdict for the demo (mirrors sandbox semantics)."""
    cap = policy.get("per_transaction_limit")
    if cap is not None and amount > D(str(cap)):
        return "FAILED", "LIMIT_EXCEEDED"
    return "CLEARING", "accepted"
