"""Demo API: Kit 1 treasury + Kit 2 purchase over the decision engine.

Sandbox-backed routes call Airwallex; /demo/* routes run fully offline on
fixtures so the video never depends on network.
"""
from __future__ import annotations

import os
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.services.purchase import auth_outcome, build_card_policy, evaluate_terms
from app.services.treasury import Obligation, TreasuryPolicy, TreasuryState, decide, safe_to_spend

app = FastAPI(title="treasury-agent", version="0.1.0")


def _client():
    from app.services.airwallex_client import AirwallexClient

    c = AirwallexClient()
    if not c.client_id or not c.api_key or "put_" in c.client_id:
        raise RuntimeError("live sandbox not configured — see docs/SETUP.md")
    return c

BASE = os.path.dirname(os.path.dirname(__file__))
app.mount("/sim", StaticFiles(directory=os.path.join(BASE, "simulator"), html=True), name="sim")


class BriefIn(BaseModel):
    preset: str = "kit1"


KIT1_FIXTURES = [
    {"id": "ship", "label": "Shipping invoice (ops stop without it)", "amount": "3000", "currency": "USD", "due_hours": 24, "stops_operations": True},
    {"id": "supplier", "label": "Supplier EUR, waiting on payment", "amount": "2000", "currency": "EUR", "due_hours": 12, "time_sensitive": True},
    {"id": "tool", "label": "Small tool renewal", "amount": "200", "currency": "USD", "due_hours": 200},
    {"id": "ads", "label": "Ad platform top-up", "amount": "1500", "currency": "USD", "due_hours": 48},
    {"id": "loan", "label": "Founder loan repayment", "amount": "4000", "currency": "USD", "due_hours": 70},
]


@app.get("/api/health")
def health():
    return {"ok": True, "kits": ["kit1", "kit2"]}


@app.post("/api/kit1/decide")
def kit1(body: BriefIn):
    obs = [
        Obligation(o["id"], o["label"], Decimal(o["amount"]), o["currency"], o["due_hours"],
                   stops_operations=o.get("stops_operations", False), time_sensitive=o.get("time_sensitive", False))
        for o in KIT1_FIXTURES
    ]
    cash = {"USD": Decimal("10000"), "EUR": Decimal("5000")}
    policy = TreasuryPolicy()
    decisions = decide(obs, cash, policy)
    return {
        "safe_usd": str(safe_to_spend(cash["USD"], policy.reserve_floor)),
        "decisions": [vars(d) | {"amount": str(d.amount)} for d in decisions],
        "live": False,
    }


class TermsIn(BaseModel):
    annual_total: str = "9840"
    monthly_year_total: str = "12000"
    reserve_week7: str = "4200"


@app.post("/api/kit2/evaluate")
def kit2(body: TermsIn):
    d = evaluate_terms(Decimal(body.annual_total), Decimal(body.monthly_year_total),
                       Decimal("5000"), {7: Decimal(body.reserve_week7)})
    price = Decimal("99") if d.choice == "monthly" else Decimal("9840")
    verdict, reason = auth_outcome(price, d.card_policy)
    return {
        "choice": d.choice, "reason": d.reason, "reconsider_on": d.reconsider_on,
        "card_policy": d.card_policy,
        "simulated_charge": {"amount": str(price), "verdict": verdict, "reason": reason},
        "live": False,
    }


@app.get("/", response_class=HTMLResponse)
def root():
    return '<meta http-equiv="refresh" content="0;url=/sim/">'


# --- live sandbox routes (need .env; 501-style JSON when unconfigured) ---
@app.get("/api/live/balances")
def live_balances():
    try:
        return {"balances": _client().balances(), "live": True}
    except Exception as e:
        return {"error": str(e)[:200], "live": False}


class DepositIn(BaseModel):
    currency: str = "USD"
    amount: str = "5000"


@app.post("/api/kit1/deposit-recalc")
def kit1_recalc(body: DepositIn):
    """Simulate a deposit landing, then recalculate only pending decisions."""
    from decimal import Decimal

    obs = [
        Obligation(o["id"], o["label"], Decimal(o["amount"]), o["currency"], o["due_hours"],
                   stops_operations=o.get("stops_operations", False), time_sensitive=o.get("time_sensitive", False))
        for o in KIT1_FIXTURES
    ]
    st = TreasuryState(cash_by_currency={"USD": Decimal("100"), "EUR": Decimal("100")})
    st.decisions = decide(obs, st.cash_by_currency, TreasuryPolicy())  # cash-starved first pass
    before = [d.action for d in st.decisions]
    fresh = st.recalculate_on_deposit(body.currency, Decimal(body.amount), obs, TreasuryPolicy())
    return {
        "before": before,
        "fresh": [vars(d) | {"amount": str(d.amount)} for d in fresh],
        "cash": {k: str(v) for k, v in st.cash_by_currency.items()},
        "live": False,
    }


class CardSimIn(BaseModel):
    card_policy: dict = {}
    charge_amount: str = "99"


@app.post("/api/kit2/simulate-charge")
def kit2_charge(body: CardSimIn):
    from decimal import Decimal

    policy = body.card_policy or build_card_policy("monthly")
    verdict, reason = auth_outcome(Decimal(body.charge_amount), policy)
    return {"amount": body.charge_amount, "verdict": verdict, "reason": reason, "live": False}


class ExecuteIn(BaseModel):
    decisions: list[dict] = []
    approved_obligations: list[str] = []  # obligation ids the person approved


@app.post("/api/kit1/execute")
def kit1_execute(body: ExecuteIn):
    """Approval-gated execution plan. Live money movement happens in the
    build-week pass against the funded sandbox; this endpoint proves the
    gating + idempotency contract offline."""
    from decimal import Decimal

    from app.services.execute import Executor

    ex = Executor()
    plan = []
    for d in body.decisions:
        amt = Decimal(str(d.get("amount", "0")))
        oid = str(d.get("obligation_id", "x"))
        gate = ex.gate(d.get("action", ""), amt, d.get("currency", "USD"))
        if gate and oid not in body.approved_obligations:
            plan.append({"decision": d, "status": "awaiting_person", "approval_id": gate.id,
                         "needs": f"person approves {amt} {d.get('currency', 'USD')} (over {ex.autonomous_limit} limit)"})
        else:
            rid = f"demo-{oid}"
            first = ex.claim_request_id(rid)
            plan.append({"decision": d, "status": "locked" if first else "duplicate_blocked",
                         "request_id": rid})
    return {"plan": plan, "live": False}


class LiveConvertIn(BaseModel):
    buy_amount_eur: str = "50"
    supplier_iban: str = "DE89370400440532013000"
    supplier_swift: str = "DEUTDEFF"
    supplier_name: str = "Demo Supplier GmbH"
    transfer_amount_eur: str = "20"


@app.post("/api/kit1/execute-live")
def kit1_execute_live(body: LiveConvertIn):
    """Kit 1 centerpiece: FX quote -> convert (single-use quote) -> supplier
    beneficiary -> transfer -> simulated settlement. Small sandbox amounts."""
    from app.services.airwallex_client import new_request_id

    try:
        c = _client()
    except Exception as e:
        return {"error": str(e)[:200], "live": False}
    trail: dict = {"live": True, "steps": {}}
    try:
        q = c.fx_quote("EUR", "USD", body.buy_amount_eur)
        quote_id = q.get("quote_id") or (q.get("data") or {}).get("quote_id", "")
        trail["steps"]["quote"] = {"quote_id": quote_id, "buy": body.buy_amount_eur}
        conv = c.fx_convert("EUR", "USD", body.buy_amount_eur, quote_id)
        trail["steps"]["conversion"] = {"id": conv.get("id", ""), "status": conv.get("status", "")}
        import time as _time

        ben, ben_id, last_err = {}, "", None
        ben_rid = new_request_id()  # one id for all retries: duplicates rejected, never double-created
        for _ in range(3):
            try:
                ben = c.post("/api/v1/beneficiaries/create", {
                    "beneficiary": {
                        "entity_type": "COMPANY",
                        "beneficiary_name": body.supplier_name,
                        "bank_details": {"account_name": body.supplier_name, "iban": body.supplier_iban,
                                        "swift_code": body.supplier_swift,
                                        "bank_country_code": "DE", "account_currency": "EUR"},
                        "address": {"country_code": "DE", "city": "Berlin", "street_address": "1 Demo Strasse",
                                    "postcode": "10115"},
                    },
                    "transfer_methods": ["SWIFT"],
                }, request_id=ben_rid)
                last_err = None
                break
            except Exception as e:
                last_err = e
                _time.sleep(3)
        if last_err is not None:
            raise last_err
        ben_id = ben.get("id") or ben.get("beneficiary_id", "")
        trail["steps"]["beneficiary"] = {"id": ben_id}
        tr = c.post("/api/v1/transfers/create", {
            "source_currency": "EUR",
            "transfer_currency": "EUR", "transfer_amount": float(body.transfer_amount_eur),
            "transfer_method": "SWIFT", "beneficiary_id": ben_id,
            "reason": "supplier_payment", "reference": "SUP-2026-001",
        }, request_id=new_request_id())
        tid = tr.get("id") or tr.get("transfer_id", "")
        trail["steps"]["transfer"] = {"id": tid, "status": tr.get("status", "")}
        sent = c.post(f"/api/v1/simulation/transfers/{tid}/transition",
                      {"next_status": "SENT"}, request_id=new_request_id())
        trail["steps"]["sim_sent"] = {"status": sent.get("status", sent)}
        paid = c.post(f"/api/v1/simulation/transfers/{tid}/transition",
                      {"next_status": "PAID"}, request_id=new_request_id())
        trail["steps"]["sim_paid"] = {"status": paid.get("status", paid)}
        return trail
    except Exception as e:
        msg = str(e)
        detail = ""
        try:
            import httpx as _hx

            if isinstance(e, _hx.HTTPStatusError) and e.response is not None:
                detail = e.response.text[:400]
        except Exception:
            pass
        trail["steps"]["failed_at"] = msg[:160]
        trail["error"] = msg[:200]
        trail["detail"] = detail
        trail["live"] = False
        return trail


class LiveIssuingIn(BaseModel):
    first_name: str = "Demo"
    last_name: str = "Founder"
    email: str = "demo-founder@example.com"


@app.post("/api/kit2/setup-live")
def kit2_setup_live(body: LiveIssuingIn):
    """Create a real cardholder + virtual card in the sandbox, then freeze it.
    Proves the issuing path end to end. Sandbox only.
    NOTE: sandbox account needs issuing enabled (devhelp@airwallex.com) —
    without it, card create returns 'not allowed to set card type'."""
    try:
        c = _client()
    except Exception as e:
        return {"error": str(e)[:200], "live": False}

    def call(path: str, payload: dict):
        from app.services.airwallex_client import new_request_id

        try:
            return {"ok": True, "data": c.post(path, payload, request_id=new_request_id())}
        except Exception as e:
            msg = str(e)
            detail = ""
            try:
                import httpx as _hx

                if isinstance(e, _hx.HTTPStatusError) and e.response is not None:
                    detail = e.response.text[:300]
            except Exception:
                pass
            return {"ok": False, "error": msg[:160], "detail": detail}

    holder = call("/api/v1/issuing/cardholders/create", {
        "type": "DELEGATE", "email": body.email,
        "first_name": body.first_name, "last_name": body.last_name})
    if not holder["ok"]:
        return {"error": holder["error"], "detail": holder.get("detail", ""), "live": False,
                "hint": "cardholder create failed — check payload shape"}
    hid = holder["data"].get("id") or holder["data"].get("cardholder_id", "")
    card = call("/api/v1/issuing/cards/create", {
        "cardholder_id": hid, "created_by": f"{body.first_name} {body.last_name}",
        "form_factor": "VIRTUAL", "is_personalized": True,
        "program": {"purpose": "COMMERCIAL", "type": "PREPAID"},
        "authorization_controls": {
            "allowed_transaction_count": "MULTIPLE",
            "transaction_limits": {"currency": "USD", "limits": [
                {"amount": 500, "interval": "PER_TRANSACTION"},
                {"amount": 6000, "interval": "ALL_TIME"}]},
            "allowed_currencies": ["USD"]}})
    if not card["ok"]:
        return {"cardholder": holder["data"], "error": card["error"], "detail": card.get("detail", ""),
                "live": False,
                "hint": ("issuing API works (holder READY) but no card program type is enabled on "
                         "this sandbox account — ask devhelp@airwallex.com to enable an allowed "
                         "program type (PREPAID) per the issuing integration checklist")}
    cid = card["data"].get("card_id", "")
    frozen = call(f"/api/v1/issuing/cards/{cid}/update", {"card_status": "INACTIVE"})
    return {"cardholder": holder["data"], "card": card["data"],
            "frozen": frozen.get("data", frozen), "live": True}
