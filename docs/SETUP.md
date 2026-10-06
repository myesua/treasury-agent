# Sandbox setup (do once, ~10 min — all yours, all in the web app)

1. Sign up at https://sandbox.airwallex.com — business name MUST be
   `New Business Sandbox` or `Sandbox Business` (anything else stays In review).
2. Log in to the sandbox web app. Go Account > Developer > API keys.
   Create a key scoped to what the agent needs. Copy Client ID + API key.
3. `cp .env.example .env` here and paste both values. Never commit `.env`.
4. `python scripts/sandbox_spike.py` — expect: login ok, 0+ accounts.
5. Empty accounts = connected but unfunded. Create a USD Global Account,
   then simulate a 25000 deposit (major units). Balance posts immediately
   even if the response says PENDING.
6. Optional: connect agent MCPs (already in opencode config):
   docs (no login) https://mcp.sandbox.airwallex.com/docs
   developer (sandbox login) https://mcp.sandbox.airwallex.com/developer

If something fails, stop — do not build on a broken setup. Checklist:
business In review (name?), key scopes, MCP login done, funded account exists.
