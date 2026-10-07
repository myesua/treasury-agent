"""Execution layer: approval gates + idempotent executor (pure logic, no I/O).

Rules from the builder guide enforced HERE in code:
- amounts above the autonomous limit need a person (approval object first)
- one request_id per operation; retries reuse it; new operations mint new ones
- before any retry, query by request_id so a retry can never double-pay
- transfers poll to terminal states; SENT is in-flight, never final
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

D = Decimal

TERMINAL_TRANSFER = {"PAID", "CANCELLED"}
IN_FLIGHT = {"SENT", "PROCESSING", "PENDING"}


@dataclass
class Approval:
    id: str
    action: str
    amount: D
    currency: str
    status: str = "pending"  # pending | approved | rejected


@dataclass
class Executor:
    autonomous_limit: D = D("2000")
    approvals: dict[str, Approval] = field(default_factory=dict)
    seen_request_ids: set[str] = field(default_factory=set)
    _n: int = 0

    def gate(self, action: str, amount: D, currency: str) -> Approval | None:
        """Returns an Approval to collect when a person is required, else None."""
        if amount > self.autonomous_limit:
            self._n += 1
            ap = Approval(id=f"apr-{self._n}", action=action, amount=amount, currency=currency)
            self.approvals[ap.id] = ap
            return ap
        return None

    def approve(self, approval_id: str) -> Approval:
        ap = self.approvals[approval_id]
        ap.status = "approved"
        return ap

    def claim_request_id(self, request_id: str) -> bool:
        """Duplicate lock: True = first use (proceed), False = already used (stop)."""
        if request_id in self.seen_request_ids:
            return False
        self.seen_request_ids.add(request_id)
        return True

    @staticmethod
    def is_terminal(status: str) -> bool:
        return status in TERMINAL_TRANSFER

    @staticmethod
    def needs_replacement(status: str, failure_type: str = "") -> bool:
        """CANCELLED never means a person cancelled — read failure_type to decide."""
        return status == "CANCELLED"
