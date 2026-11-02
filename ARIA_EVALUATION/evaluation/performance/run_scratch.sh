#!/bin/bash
# usage: run_scratch.sh <script.py> [args]
# Runs one perf script with a scratch SQLite DB, private auth, no provider keys, low priority; deletes the scratch dir afterwards.
# Output is capped (cut/tail) so a chatty library cannot flood the console.
SCR=$(mktemp -d -t aria_perf_XXXX)
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 ARIA_AUTH_MODE=private ARIA_WARMUP=0 GROQ_API_KEY= GEMINI_API_KEY= PYTHONUTF8=1 ARIA_SCRATCH="$(cygpath -m "$SCR")" DB_URL="sqlite:///$(cygpath -m "$SCR")/perf.db"
cd "$(dirname "$0")"
timeout "${PERF_TIMEOUT:-900}" /e/ARIA/.venv/Scripts/python.exe "$@" 2>&1 | grep -v "context_assembled" | cut -c1-400 | tail -n "${PERF_TAIL:-60}"
rm -rf "$SCR"
