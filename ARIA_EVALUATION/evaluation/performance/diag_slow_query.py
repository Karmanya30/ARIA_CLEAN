"""Diagnose the 218 s routing latency of 'what about infosys' when the network is unreachable: replays the scenario through the benchmark harness
(arch A, stubbed pipelines) and dumps every thread's stack to a file after 25 s and 90 s."""
import faulthandler, os, sys, json, tempfile
from pathlib import Path
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here)); sys.path.insert(0, str(here.parents[2] / "evaluation/intent_understanding"))
sys.path.insert(0, str(here.parents[2]))
from common import block_network, lower_priority, RESULTS
lower_priority()
dump = open(RESULTS / "diag_slow_query_stacks.txt", "w")
faulthandler.dump_traceback_later(25, repeat=False, file=dump)
import run_benchmark as rb
orig = rb.load
rb.load = lambda split, bench="benchmark_v1.jsonl": [i for i in orig("all", bench) if i["scenario"] == "company_chain"][:2]
sys.argv = ["x", "--arch", "A", "--split", "all", "--llm", "off", "--out", str(Path(tempfile.mkdtemp(prefix="aria_perf_")) / "o.json")]
block_network()
import time
t = time.time()
try:
    rb.main()
finally:
    print("elapsed", round(time.time() - t, 1))
