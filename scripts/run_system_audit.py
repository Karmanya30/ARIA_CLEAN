"""Repeatable Windows audit. Run from the repository with the test environment.

--live permits small synthetic Groq/Gemini calls; Tavus/ngrok are never started.
Every failed check is recorded, remaining checks run, and the exit code fails.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Permit synthetic LLM connectivity and intent probes")
    args = parser.parse_args()
    output = ROOT / ".audit" / "rerun"
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DB_URL": "sqlite:///" + (output / "bootstrap.db").as_posix(), "ARIA_WARMUP": "0",
           "ARIA_MEMORY_SEMANTIC": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ARIA_AUTH_MODE": "private"}
    npm = "npm.cmd" if os.name == "nt" else "npm"
    checks = [
        ("inventory", [sys.executable, "-m", "scripts.audit_inventory"], ROOT),
        ("regression", [sys.executable, "-m", "pytest", "-q", f"--junitxml={output / 'regression.xml'}"], ROOT),
        ("build", [npm, "run", "build"], ROOT / "web"),
        ("lint", [npm, "run", "lint"], ROOT / "web"),
        ("browser", [npm, "run", "test:e2e"], ROOT / "web"),
        ("account_browser", [npm, "run", "test:accounts"], ROOT / "web"),
        ("restart", [sys.executable, "-m", "scripts.audit_restart"], ROOT),
        ("account_restart", [sys.executable, "-m", "scripts.audit_account_restart"], ROOT),
        ("native_memory", [sys.executable, "-m", "scripts.evaluate_context_memory"], ROOT),
        ("dependency_consistency", [sys.executable, "-m", "pip", "check"], ROOT),
        ("python_advisories", [sys.executable, "-m", "pip_audit", "--format", "json"], ROOT),
        ("npm_advisories", [npm, "audit", "--json"], ROOT / "web"),
        ("connections", [sys.executable, "-m", "scripts.audit_connections", *(["--llm"] if args.live else [])], ROOT),
    ]
    if args.live:
        checks.append(("live_intent", [sys.executable, "-m", "scripts.evaluate_intent_resolver", "--live", "--output", str(output / "intent.json")], ROOT))
    results = []
    for name, command, cwd in checks:
        started = time.monotonic()
        try:
            with (output / f"{name}.log").open("w", encoding="utf-8") as log:
                completed = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            status = "PASS" if completed.returncode == 0 else "FAIL"
            results.append({"check": name, "status": status, "exit_code": completed.returncode, "seconds": round(time.monotonic() - started, 2)})
        except OSError as exc:
            results.append({"check": name, "status": "NOT VERIFIED", "error_type": type(exc).__name__})
        print(f"{name}: {results[-1]['status']}", flush=True)
        (output / "summary.json").write_text(json.dumps({"checks": results, "live_llm_enabled": args.live,
            "limitations": "A passing process is not proof that every workflow/provider is verified. Inspect metrics, skipped tests, advisories, connection statuses, warnings, and SYSTEM_AUDIT.md."}, indent=2), encoding="utf-8")
    return int(any(row["status"] != "PASS" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
