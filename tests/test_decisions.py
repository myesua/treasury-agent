"""Kit 1 + Kit 2 decision-engine tests (pure functions, no network)."""
from decimal import Decimal as D

from app.services.purchase import auth_outcome, build_card_policy, evaluate_terms
from app.services.treasury import (
    Obligation,
    TreasuryPolicy,
    TreasuryState,
    decide,
    safe_to_spend,
    scale_limit_by_confidence,
)


def test_safe_never_negative():
    assert safe_to_spend(D("1000"), D("5000")) == D("0")
    assert safe_to_spend(D("10000"), D("5000"), D("1000")) == D("4000")


def test_confidence_scales_limit():
    base = D("2000")
    assert scale_limit_by_confidence(base, 0.9) == D("4000")
    assert scale_limit_by_confidence(base, 0.6) == D("2000")
    assert scale_limit_by_confidence(base, 0.9, contradiction=True) == D("500.00")


def test_kit1_priorities():
    obs = [
        Obligation("ship", "Shipping invoice", D("3000"), "USD", 24, stops_operations=True),
        Obligation("supplier", "Supplier EUR", D("2000"), "EUR", 12, time_sensitive=True),
        Obligation("cheap", "Small tool", D("200"), "USD", 200),
    ]
    out = decide(obs, {"USD": D("10000"), "EUR": D("5000")}, TreasuryPolicy())
    by_id = {d.obligation_id: d.action for d in out}
    assert by_id["ship"] == "fund"
    assert by_id["supplier"] == "convert"
    assert by_id["cheap"] == "defer"


def test_kit1_escalates_shortfall():
    obs = [Obligation("big", "Huge bill", D("999999"), "USD", 10, stops_operations=True)]
    out = decide(obs, {"USD": D("100")}, TreasuryPolicy())
    assert out[0].action == "escalate" and out[0].needs_person


def test_recalculate_only_pending():
    st = TreasuryState(cash_by_currency={"USD": D("100")})
    obs = [Obligation("big", "Huge bill", D("5000"), "USD", 10)]
    st.decisions = decide(obs, st.cash_by_currency, TreasuryPolicy())
    assert st.decisions[0].action == "escalate"
    fresh = st.recalculate_on_deposit("USD", D("10000"), obs, TreasuryPolicy())
    assert any(d.action == "fund" for d in fresh)


def test_kit2_monthly_when_annual_breaches():
    d = evaluate_terms(D("9840"), D("12000"), D("5000"), {7: D("4200"), 12: D("6000")})
    assert d.choice == "monthly" and "week 7" in d.reason
    assert d.card_policy["mode"] == "recurring_cap"


def test_kit2_annual_when_safe():
    d = evaluate_terms(D("9840"), D("12000"), D("5000"), {7: D("9000")})
    assert d.choice == "annual"


def test_card_limits_inclusive():
    assert auth_outcome(D("100"), build_card_policy("monthly", D("100"))) == ("CLEARING", "accepted")
    assert auth_outcome(D("100.01"), build_card_policy("monthly", D("100")))[0] == "FAILED"


def test_live_client_refuses_without_creds(monkeypatch):
    import os

    from app.services.airwallex_client import AirwallexClient

    monkeypatch.setenv("AWX_CLIENT_ID", "")
    monkeypatch.setenv("AWX_API_KEY", "")
    c = AirwallexClient(client_id="", api_key="")
    try:
        c.login()
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "credentials missing" in str(e)
    assert os.getenv("AWX_BASE_URL", "https://api.sandbox.airwallex.com").startswith("https://")
