"""Where do the 1-5 s 'entity' queries spend time? Times the instrument-catalogue search and the data-lookup candidate scan (network blocked: Yahoo search raises at once),
and profiles one slow query with cProfile (top cumulative functions). Output: results/lookup_hotspot.json (+ _profile.txt)"""
import cProfile, io, json, os, pstats, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", HF_HUB_OFFLINE="1")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove()
from modules.market import instruments
from modules.qa import lookup

res = {}
Q = ["market cap of Zomato", "tell me about sip number 3 for beginners", "revenue of Kaynes Technology", "what about infosys", "pe ratio of tcs", "hello there friend"]
t = time.perf_counter(); instruments.catalog(); res["catalog_first_call_s"] = round(time.perf_counter() - t, 2)
res["catalog_items"] = len(instruments.catalog()["items"])
rows = {}
for q in Q:
    xs = []
    for _ in range(4):
        t = time.perf_counter()
        try:
            instruments.search(q)
        except Exception as e:
            pass
        xs.append((time.perf_counter() - t) * 1000)
    rows[q] = {"instruments.search_ms_each": [round(x) for x in xs]}
    ys = []
    for _ in range(4):
        t = time.perf_counter()
        try:
            lookup.candidates(q)
        except Exception:
            pass
        ys.append((time.perf_counter() - t) * 1000)
    rows[q]["lookup.candidates_ms_each"] = [round(x) for x in ys]
    print(q, rows[q], flush=True)
res["per_query"] = rows
pr = cProfile.Profile(); pr.enable()
for _ in range(2):
    try:
        instruments.search("market cap of Zomato")
    except Exception:
        pass
pr.disable(); s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(14)
(RESULTS / "lookup_hotspot_profile.txt").write_text(s.getvalue()[:6000], encoding="utf-8")
(RESULTS / "lookup_hotspot.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
