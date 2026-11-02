"""Routing latency per architecture variant (A..H): runs evaluation/intent_understanding/run_benchmark.py (unchanged) as a subprocess in
replay mode (cached model answers, never a provider call), BelowNormal priority, scratch DB. Output: results/routing_<arch>_<rep>.json."""
import subprocess, sys, tempfile, shutil, time, json
from common import ROOT, RESULTS, safe_env

archs = sys.argv[1].split(",") if len(sys.argv) > 1 else list("ABCDEH")
reps = int(sys.argv[2]) if len(sys.argv) > 2 else 2
BELOW_NORMAL = 0x00004000
for arch in archs:
    for rep in range(reps):
        scratch = tempfile.mkdtemp(prefix="aria_perf_")
        out = RESULTS / f"routing_{arch}_{rep}.json"
        t = time.time()
        try:
            p = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-X", "utf8", str(ROOT / "evaluation/intent_understanding/run_benchmark.py"),
                                "--arch", arch, "--split", "all", "--llm", "replay", "--out", str(out)],
                               cwd=ROOT, env=safe_env(scratch), capture_output=True, text=True, timeout=900, creationflags=BELOW_NORMAL)
            print(arch, rep, f"{time.time()-t:.0f}s rc={p.returncode}", p.stdout[-300:].strip(), p.stderr[-300:].strip() if p.returncode else "", flush=True)
        except subprocess.TimeoutExpired:
            print(arch, rep, "TIMEOUT", flush=True)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
