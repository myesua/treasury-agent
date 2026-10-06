# treasury-agent

Kit 1 (Adaptive Treasury Controller) + Kit 2 (Intent-Bound Purchase Agent) on
Airwallex sandbox. Airwallex Agentic Banking Hackathon entry.

## Run (offline demo, zero keys)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
uvicorn app.main:app --port 3002
# open http://localhost:3002
```

## Run (live sandbox)

```bash
cp .env.example .env  # paste sandbox Client ID + API key
python scripts/sandbox_spike.py
```

Fresh decision engine written for this hackathon, informed by FlowCFO's
safe-to-spend patterns. Policy thresholds live in code, never prompts.
Amounts are major units throughout (100 = one hundred dollars).
