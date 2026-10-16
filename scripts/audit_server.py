"""Local browser-test entry point. Real API/database; synthetic external providers.

Never use as a deployment entry point. Refuses a database outside .audit.
"""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
run = os.environ.get("ARIA_AUDIT_RUN", "manual")
if not run.replace("-", "").isalnum():
    raise RuntimeError("Invalid audit run ID")
storage = ROOT / ".audit" / "browser" / run
storage.mkdir(parents=True, exist_ok=True)
os.environ["DB_URL"] = "sqlite:///" + (storage / "aria.db").as_posix()
for key in ("ARIA_WARMUP", "ARIA_INTENT_RESOLVER", "ARIA_MEMORY_SEMANTIC", "ARIA_SENTIMENT", "ARIA_FORECAST", "ARIA_SCENARIO_BACKTEST", "FI_NEWS_RSS"):
    os.environ[key] = "0"

from pytest import MonkeyPatch
sys.path.insert(0, str(ROOT / "tests" / "equity_research"))
sys.path.insert(0, str(ROOT / "tests" / "market"))
from _intel_fixtures import good_llm, make_snapshot
from test_instruments import offline
from api.main import app
import core.orchestrator
from modules.equity_research.intelligence import agents, pipeline as intel
from modules.equity_research.intelligence.data import Target

patch = MonkeyPatch()
if os.environ.get("ARIA_AUDIT_GOOGLE") == "1":
    # Browser-only identity adapter. RSA/signature validation is tested separately
    # with the real verifier in tests/test_accounts.py; never a production flag.
    import json
    from api import auth
    os.environ["GOOGLE_CLIENT_ID"] = "synthetic-client.apps.googleusercontent.com"
    patch.setattr(auth, "verify_google", lambda credential: json.loads(credential))
offline.__wrapped__(patch, storage)
report_llm = good_llm()
for name, module in list(sys.modules.items()):
    if name.startswith(("ai.", "core.", "modules.", "shared.")) and hasattr(module, "generate_response"):
        patch.setattr(module, "generate_response", lambda *a, **k: "Synthetic provider reply for browser regression.")
patch.setattr(agents, "generate_response", report_llm)
patch.setattr(intel, "resolve_target", lambda q: Target("TESTCO", "TESTCO.NS", "Test"))
patch.setattr(intel, "gather", lambda target: make_snapshot("operating"))
import ai.llm.groq_client as llm
patch.setattr(llm, "generate_structured", lambda *a, **k: None)
for name in ("api.routes.chat", "api.routes.instruments"):
    patch.setattr(sys.modules[name], "register_later", lambda *a, **k: None)
patch.setattr(core.orchestrator, "_with_news", lambda response: response)

# Fill dashboard snapshots with visibly synthetic numbers; do not start polling.
from datetime import datetime, timezone
from modules.market import live as market_live
meta = {"as_of": "2026-10-01T10:00:00+00:00", "fetched_at": "2026-10-01T10:00:00+00:00", "stale": True, "source": "SYNTHETIC AUDIT FIXTURE", "delay_min": 15}
market_live._started = True
market_live._snap.update({
    "overview": {"items": [{"symbol": "^NSEI", "name": "Nifty 50", "group": "india", "price": 100.0, "change": 1.0, "change_pct": 1.0, "prev_close": 99.0, "currency": "INR", "spark": [99.0, 100.0]}], "last_bar": datetime.now(timezone.utc), "meta": meta},
    "movers": {"gainers": [], "losers": [], "active": [], "meta": meta},
    "sectors": {"sectors": [], "meta": meta},
    "news": {"items": [], "engine": "keywords", "meta": meta},
})
from api.routes import markets
class SyntheticTicker:
    fast_info = {"currency": "INR", "lastPrice": 100.0, "previousClose": 99.0, "dayLow": 98.0, "dayHigh": 101.0, "yearLow": 80.0, "yearHigh": 110.0, "marketCap": 1e9, "lastVolume": 1000}
    def __init__(self, symbol):
        self.symbol = symbol
    def history(self, **kwargs):
        from test_instruments import daily
        return daily(260)
patch.setattr(markets.yf, "Ticker", SyntheticTicker)
patch.setattr(markets, "_yf_info", lambda s: {"shortName": "Synthetic index", "currency": "INR"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("ARIA_AUDIT_PORT", "8765")), log_level="warning")
