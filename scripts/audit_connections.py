"""Read-only public data and optional synthetic LLM probes. Never prints keys/bodies."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
from pathlib import Path
import requests


def check(name, action):
    started = time.monotonic()
    try:
        details = action()
        return {"name": name, "status": "VERIFIED", "seconds": round(time.monotonic() - started, 2), **details}
    except Exception as exc:
        return {"name": name, "status": "NOT VERIFIED", "seconds": round(time.monotonic() - started, 2),
                "error_type": type(exc).__name__, "http_status": getattr(exc, "status_code", None)}


def public(url, validate):
    response = requests.get(url, timeout=15, headers={"User-Agent": "ARIA-evaluation/1.0"})
    response.raise_for_status()
    if not validate(response):
        raise ValueError("Unexpected provider schema")
    return {"http_status": response.status_code, "schema_checked": True}


def groq():
    from ai.llm.groq_client import _make_groq_client
    from config.settings import MODEL_NAME
    response = _make_groq_client().with_options(timeout=15, max_retries=0).chat.completions.create(
        model=MODEL_NAME, messages=[{"role": "user", "content": "Synthetic connectivity test. Reply exactly ARIA_AUDIT_OK."}], max_completion_tokens=256)
    if "ARIA_AUDIT_OK" not in (response.choices[0].message.content or ""):
        raise ValueError("Unexpected provider response")
    return {"model": response.model, "synthetic_only": True}


def gemini():
    from google import genai
    from config.settings import GEMINI_API_KEY, GEMINI_MODEL_NAME
    if not GEMINI_API_KEY:
        raise RuntimeError("No configured credential")
    with genai.Client(api_key=GEMINI_API_KEY, http_options={"timeout": 15000}) as client:
        response = client.models.generate_content(model=GEMINI_MODEL_NAME,
            contents="Synthetic connectivity test. Reply exactly ARIA_AUDIT_OK.", config={"max_output_tokens": 256, "temperature": 0})
        if "ARIA_AUDIT_OK" not in (response.text or ""):
            raise ValueError("Unexpected provider response")
    return {"model": GEMINI_MODEL_NAME, "synthetic_only": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    probes = [
        ("AMFI NAV", lambda: public("https://www.amfiindia.com/spages/NAVAll.txt", lambda r: "Scheme Code" in r.text and len(r.content) > 10000)),
        ("mfapi history", lambda: public("https://api.mfapi.in/mf/119551", lambda r: bool(r.json().get("data")))),
        ("CoinGecko", lambda: public("https://api.coingecko.com/api/v3/ping", lambda r: "gecko_says" in r.json())),
        ("Yahoo chart", lambda: public("https://query1.finance.yahoo.com/v8/finance/chart/TCS.NS?range=1mo&interval=1d", lambda r: bool(r.json()["chart"]["result"][0]["timestamp"]))),
        ("FRED", lambda: public("https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDIRLTLT01STM", lambda r: "INDIRLTLT01STM" in r.text and "observation_date" in r.text)),
    ]
    if args.llm:
        probes.extend([("Groq", groq), ("Gemini", gemini)])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda item: check(*item), probes))
    path = Path(".audit/live-connections.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"results": results, "limitations": "Connectivity/schema only; not market accuracy, freshness, grounded answers or browser voice/video. Tavus and ngrok not started."}, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return int(any(result["status"] != "VERIFIED" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
