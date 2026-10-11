"""Universe of NSE + BSE listed equities for the validation sweep.

Sources are the exchanges' own public files only:
  NSE  https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv   (all listed equities, ISIN)
  BSE  api.bseindia.com ListofScripData (active equity scrips) - sits behind a WAF and usually answers 403 to
       scripts - so the fallback is BSE's public daily Bhavcopy download, which lists every scrip that TRADED
       that day (scrips with no trade on that day are therefore missing; this undercounts BSE, it never invents).
  NSE  Nifty 500 constituents (ind_nifty500list.csv) only to order the sweep.
The merged list is cached to data/forecast_universe/universe.parquet and refreshed after 7 days.
"""
from __future__ import annotations

import datetime as dt
import io
import time
from dataclasses import asdict, dataclass

import pandas as pd
import requests
from loguru import logger

from config.paths import DATA_DIR

UNIVERSE_DIR = DATA_DIR / "forecast_universe"
CACHE = UNIVERSE_DIR / "universe.parquet"
MAX_AGE_S = 7 * 86400
NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
BSE_API = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry="
           "&segment=Equity&status=Active")
BSE_BHAV = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36",
           "Accept": "text/csv,application/json,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
BSE_HEADERS = {**HEADERS, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
COLUMNS = ["symbol", "yahoo_symbol", "exchange", "name", "isin", "series", "also_on", "bse_yahoo_symbol",
           "traded_value", "nifty500"]


@dataclass
class UniverseEntry:
    symbol: str
    yahoo_symbol: str
    exchange: str  # 'NSE' | 'BSE'
    name: str
    isin: str | None = None
    series: str | None = None
    also_on: str | None = None  # 'BSE' when an NSE-primary company is also listed on BSE
    bse_yahoo_symbol: str | None = None
    traded_value: float | None = None  # BSE bhavcopy turnover on the retrieval day (liquidity proxy)
    nifty500: bool = False


def _get(url: str, headers: dict, tries: int = 3, timeout: int = 60) -> requests.Response:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code in (401, 403, 404):  # a WAF or a missing file will not change on retry
                break
        except requests.RequestException as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def _isin(x) -> str | None:
    x = str(x or "").strip().upper()
    return x if len(x) == 12 and x.startswith("IN") else None


def parse_nse(text: str) -> list[UniverseEntry]:
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    df.columns = [c.strip().upper() for c in df.columns]
    return [UniverseEntry(symbol=str(r["SYMBOL"]).strip(), yahoo_symbol=f"{str(r['SYMBOL']).strip()}.NS",
                          exchange="NSE", name=str(r["NAME OF COMPANY"]).strip(), isin=_isin(r.get("ISIN NUMBER")),
                          series=str(r["SERIES"]).strip())
            for _, r in df.iterrows() if str(r["SYMBOL"]).strip() not in ("", "nan")]


def parse_bse_api(payload: list[dict]) -> list[UniverseEntry]:
    """ListofScripData rows: SCRIP_CD, Scrip_Name, scrip_id, Issuer_Name, ISIN_NUMBER, GROUP, Status."""
    out = []
    for r in payload:
        code = str(r.get("SCRIP_CD", "")).strip()
        if not code or str(r.get("Status", "Active")).strip().lower() != "active":
            continue
        out.append(UniverseEntry(symbol=str(r.get("scrip_id") or code).strip(), yahoo_symbol=f"{code}.BO",
                                 exchange="BSE", name=str(r.get("Issuer_Name") or r.get("Scrip_Name") or "").strip(),
                                 isin=_isin(r.get("ISIN_NUMBER")), series=str(r.get("GROUP") or "").strip() or None))
    return out


def parse_bse_bhav(text: str) -> list[UniverseEntry]:
    """Bhavcopy rows. Keeps equity-type ISINs only (INExxxxx01xxx): bonds, units and debentures are dropped."""
    df = pd.read_csv(io.StringIO(text), dtype=str)
    out = []
    for _, r in df.iterrows():
        isin = _isin(r.get("ISIN"))
        if r.get("FinInstrmTp") != "STK" or not isin or isin[7:9] != "01":
            continue
        tv = pd.to_numeric(r.get("TtlTrfVal"), errors="coerce")
        out.append(UniverseEntry(symbol=str(r["TckrSymb"]).strip(), yahoo_symbol=f"{str(r['FinInstrmId']).strip()}.BO",
                                 exchange="BSE", name=str(r["FinInstrmNm"]).strip(), isin=isin,
                                 series=str(r.get("SctySrs") or "").strip() or None,
                                 traded_value=None if pd.isna(tv) else float(tv)))
    return out


def fetch_nse() -> list[UniverseEntry]:
    return parse_nse(_get(NSE_URL, HEADERS).text)


def fetch_bse() -> tuple[list[UniverseEntry], str]:
    try:
        return parse_bse_api(_get(BSE_API, BSE_HEADERS, tries=1).json()), "api"
    except Exception as e:
        logger.warning(f"BSE ListofScripData unavailable ({str(e)[:80]}); using the daily Bhavcopy download")
    today = dt.date.today()
    for back in range(1, 10):
        d = today - dt.timedelta(days=back)
        if d.weekday() > 4:
            continue
        try:
            return parse_bse_bhav(_get(BSE_BHAV.format(d=d), BSE_HEADERS, tries=1).text), f"bhavcopy {d}"
        except Exception:
            continue
    raise RuntimeError("no BSE source reachable")


def fetch_nifty500() -> set[str]:
    df = pd.read_csv(io.StringIO(_get(NIFTY500_URL, HEADERS).text))
    return set(df["Symbol"].astype(str).str.strip())


def merge(nse: list[UniverseEntry], bse: list[UniverseEntry], nifty500: set[str] | None = None) -> list[UniverseEntry]:
    """Dedupe by ISIN preferring NSE: a company on both keeps its NSE entry and records the BSE code.
    BSE-only companies (and any entry without an ISIN) are kept."""
    bse_by_isin = {e.isin: e for e in bse if e.isin}
    seen: set[str] = set()
    out: list[UniverseEntry] = []
    for e in nse:
        if e.isin and e.isin in seen:  # same ISIN on two NSE series rows
            continue
        b = bse_by_isin.get(e.isin) if e.isin else None
        if e.isin:
            seen.add(e.isin)
        if b:
            e.also_on, e.bse_yahoo_symbol, e.traded_value = "BSE", b.yahoo_symbol, b.traded_value
        e.nifty500 = bool(nifty500) and e.symbol in nifty500
        out.append(e)
    for b in bse:
        if b.isin and b.isin in seen:
            continue
        if b.isin:
            seen.add(b.isin)
        out.append(b)
    return out


def _to_frame(entries: list[UniverseEntry], retrieved: str, notes: str) -> pd.DataFrame:
    df = pd.DataFrame([asdict(e) for e in entries], columns=COLUMNS)
    df["retrieved_at_utc"] = retrieved
    df.attrs.update(retrieved_at_utc=retrieved, notes=notes)
    return df


def _from_frame(df: pd.DataFrame) -> list[UniverseEntry]:
    out = []
    for r in df.to_dict("records"):
        out.append(UniverseEntry(**{k: (None if pd.isna(v) else v) for k, v in r.items() if k in COLUMNS}))
    return out


def _fallback_tables() -> list[UniverseEntry]:
    """Last resort: the symbol tables ARIA already ships (company resolver + peer groups)."""
    names: dict[str, str] = {}
    try:
        from modules.equity_research.intelligence.data import PEER_GROUPS

        for g in PEER_GROUPS.values():
            for s in g:
                names[s.upper()] = s
    except Exception as e:
        logger.warning(f"PEER_GROUPS unavailable: {e}")
    try:
        from shared import company_resolver as cr

        for attr in ("COMPANIES", "NSE_SYMBOLS", "SYMBOLS"):
            tbl = getattr(cr, attr, None)
            if isinstance(tbl, dict):
                for k, v in tbl.items():
                    sym = str(v if isinstance(v, str) else k).upper().replace(".NS", "")
                    names.setdefault(sym, str(k))
    except Exception as e:
        logger.warning(f"company_resolver unavailable: {e}")
    return [UniverseEntry(symbol=s, yahoo_symbol=f"{s}.NS", exchange="NSE", name=n) for s, n in sorted(names.items())]


def discover_universe(refresh: bool = False) -> list[UniverseEntry]:
    """Cached (<7 days) merged universe; refetch when stale or `refresh`. An unreachable source falls back to
    the last cache, then to ARIA's own symbol tables (small), and the counts are logged either way."""
    old = None
    if CACHE.exists():
        old = pd.read_parquet(CACHE)
        if not refresh and time.time() - CACHE.stat().st_mtime < MAX_AGE_S:
            return _from_frame(old)
    try:
        nse = fetch_nse()
        bse, bse_src = fetch_bse()
        try:
            n500 = fetch_nifty500()
        except Exception as e:
            logger.warning(f"Nifty 500 list unavailable ({str(e)[:80]}); ordering by liquidity proxy only")
            n500 = set()
        merged = merge(nse, bse, n500)
        overlap = sum(e.also_on == "BSE" for e in merged)
        notes = f"NSE {len(nse)}; BSE {len(bse)} via {bse_src}; overlap by ISIN {overlap}; final {len(merged)}"
        logger.info("universe: " + notes)
        UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
        df = _to_frame(merged, dt.datetime.now(dt.timezone.utc).isoformat(), notes)
        df.to_parquet(CACHE, index=False)
        (UNIVERSE_DIR / "universe_meta.txt").write_text(f"retrieved_at_utc={df.attrs['retrieved_at_utc']}\n{notes}\n")
        return merged
    except Exception as e:
        if old is not None:
            logger.warning(f"universe refresh failed ({str(e)[:100]}); using the cache from {CACHE}")
            return _from_frame(old)
        fb = _fallback_tables()
        logger.error(f"universe sources unreachable and no cache; ARIA's own symbol tables give only {len(fb)} names")
        return fb


# -- sweep summary -------------------------------------------------------------------------------------------
SWEEP_HORIZONS = (5, 21, 63)
COMPLETED = ("ok_beats_baseline", "no_model_beats_baseline", "insufficient_evidence")
DATA_REASONS = ("no_data", "insufficient_history", "stale", "all_zero_volume", "bad_data", "download_error")


def outcome_of(status: str, reason: str | None) -> str:
    """Single coverage label: the data-failure reason for data_unavailable, else the run status."""
    return (reason or "bad_data") if status == "data_unavailable" else status


def _best(hr):
    c = [m for m in hr.results if m.vs_baseline is not None and m.vs_baseline.mae_improvement_pct is not None]
    return max(c, key=lambda m: m.vs_baseline.mae_improvement_pct) if c else None


def _test_impr(hr, m) -> float | None:
    b = hr.baseline_results[0].test.mae_ret if hr.baseline_results else None
    return None if m is None or not b or m.test.mae_ret is None else float((b - m.test.mae_ret) / b * 100)


def summary_row(e: UniverseEntry, state: dict, run) -> dict:
    """One row per symbol from its sweep state entry and (if any) its stored RunResult."""
    st = state.get("status", "not_run")
    row = {"symbol": e.symbol, "yahoo_symbol": e.yahoo_symbol, "exchange": e.exchange, "name": e.name,
           "isin": e.isin, "status": st, "reason": state.get("reason"), "outcome": outcome_of(st, state.get("reason")),
           "seconds": state.get("seconds"), "n_bars": None, "first_bar": None, "last_bar": None,
           "gaps": None, "outliers": None, "zero_volume_days": None, "split_consistent": None}
    d = getattr(run, "dataset", None)
    if d:
        q = d.quality
        row.update(n_bars=d.n_bars, first_bar=d.first_bar, last_bar=d.last_bar, gaps=q.gaps, outliers=q.outliers,
                   zero_volume_days=q.zero_volume_days, split_consistent=q.split_consistency_ok)
    hrs = {h.horizon: h for h in (run.horizons if run else [])}
    for h in SWEEP_HORIZONS:
        hr = hrs.get(h)
        sel = next((m for m in hr.results if m.model == hr.selected_model), None) if hr else None
        best = _best(hr) if hr else None
        ref = sel or best
        vs = ref.vs_baseline if ref else None
        row.update({f"status_h{h}": hr.status if hr else None, f"selected_h{h}": hr.selected_model if hr else None,
                    f"best_model_h{h}": best.model if best else None,
                    f"best_impr_h{h}": best.vs_baseline.mae_improvement_pct if best else None,
                    f"best_dm_p_h{h}": best.vs_baseline.dm_p if best else None,
                    f"sel_dm_p_h{h}": sel.vs_baseline.dm_p if sel and sel.vs_baseline else None,
                    f"sel_dm_p_test_h{h}": sel.vs_baseline.dm_p_test if sel and sel.vs_baseline else None,
                    f"sel_test_impr_h{h}": _test_impr(hr, sel) if hr else None,
                    f"cov90_h{h}": ref.test.coverage_90 if ref else None,
                    f"regime_warnings_h{h}": len(ref.regime_warnings) if ref else None,
                    f"_ps_h{h}": [m.vs_baseline.dm_p for m in hr.results
                                  if m.vs_baseline is not None and m.vs_baseline.dm_p is not None] if hr else []})
    return row


def build_summary(entries: list[UniverseEntry], states: dict[str, dict], load_run) -> pd.DataFrame:
    """Summary of every attempted symbol. `load_run(yahoo_symbol)` returns its latest RunResult or None.
    Adds Benjamini-Hochberg columns: fdr_val_h<h> (selected model survives BH, q=0.05, over ALL stock x model
    validation p-values of that horizon) and fdr_test_h<h> (BH over the selected models' held-out test p-values)."""
    from . import metrics

    rows = [summary_row(e, states[e.yahoo_symbol], load_run(e.yahoo_symbol) if states[e.yahoo_symbol].get("status")
                        in COMPLETED + ("data_unavailable", "failed", "timeout") else None)
            for e in entries if e.yahoo_symbol in states]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for h in SWEEP_HORIZONS:
        flat = [(i, p) for i, ps in enumerate(df[f"_ps_h{h}"]) for p in ps]
        rej = metrics.fdr_bh([p for _, p in flat])
        # a stock's selected model passes when its own p-value is below the largest p-value BH rejected
        crit = max([p for (_, p), r in zip(flat, rej) if r], default=-1.0)
        for col in (f"sel_dm_p_h{h}", f"sel_dm_p_test_h{h}"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        sp = df[f"sel_dm_p_h{h}"]
        df[f"fdr_val_h{h}"] = (df[f"status_h{h}"] == "ok_beats_baseline") & (sp <= crit)
        tp = df[f"sel_dm_p_test_h{h}"].where(df[f"status_h{h}"] == "ok_beats_baseline")
        df[f"fdr_test_h{h}"] = pd.Series(metrics.fdr_bh(tp.to_numpy(float)), index=df.index)
        df = df.drop(columns=f"_ps_h{h}")
    return df


def _boot_median_ci(x, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float] | None:
    import numpy as np

    x = np.asarray([v for v in x if v is not None and v == v], float)
    if len(x) < 5:
        return None
    rng = np.random.default_rng(seed)
    med = np.median(x[rng.integers(0, len(x), (n_boot, len(x)))], axis=1)
    return float(np.median(x)), float(np.quantile(med, 0.025)), float(np.quantile(med, 0.975))


def _pct(a, b) -> str:
    return "n/a" if not b else f"{100 * a / b:.1f}%"


def write_report(df: pd.DataFrame, n_universe: int, path, note: str = "") -> str:
    import numpy as np

    from . import models

    done = df[df.status.isin(COMPLETED)] if len(df) else df
    L = [f"# Universe validation sweep", "", note, "",
         "## Coverage", "",
         f"- Companies in the discovered universe: {n_universe}",
         f"- Attempted: {len(df)}; completed (a validation run produced): {len(done)}", "",
         "| outcome | companies |", "|---|---|"]
    if len(df):
        for k, v in df.outcome.value_counts().items():
            L.append(f"| {k} | {v} |")
        L += ["", "Completed means a full walk-forward run; the rest were not validated, for the stated reason. "
              "no_data = Yahoo returned nothing (often delisted or a wrong code); insufficient_history = fewer than "
              "1260 daily bars; stale = last bar older than 30 days (suspended/delisted).", "",
              "## History length (completed runs, daily bars)", ""]
        nb = done.n_bars.dropna()
        if len(nb):
            q = nb.quantile([0, .1, .25, .5, .75, .9, 1])
            L.append("min / p10 / p25 / median / p75 / p90 / max = " + " / ".join(f"{v:.0f}" for v in q))
            L.append(f"Share with more than 2500 bars (history long enough for deep models): "
                     f"{_pct((nb > 2500).sum(), len(nb))}")
    L += ["", "## Beating the random-walk baseline", "",
          "Raw = the engine's own verdict (selection on the validation segment, 95% block-bootstrap CI below zero). "
          "Validation-FDR = the selected model also survives Benjamini-Hochberg (q=0.05) over ALL stock x model "
          "Diebold-Mariano p-values of that horizon. Test-confirmed = the selected model also beats the baseline on "
          "the held-out test segment (BH q=0.05 over the selected models' test p-values).", "",
          "| horizon | completed | raw ok_beats_baseline | after validation-FDR | confirmed on held-out test | "
          "median improvement, selected model on test (95% bootstrap CI) | median best-model improvement on validation "
          "(selection-biased) |", "|---|---|---|---|---|---|---|"]
    fam = {k: v.family for k, v in models.ZOO.items()}
    for h in SWEEP_HORIZONS:
        if not len(done):
            break
        ok = done[f"status_h{h}"] == "ok_beats_baseline"
        ci = _boot_median_ci(done.loc[ok, f"sel_test_impr_h{h}"])
        bi = _boot_median_ci(done[f"best_impr_h{h}"])
        f = lambda c: "n/a" if c is None else f"{c[0]:.2f}% [{c[1]:.2f}, {c[2]:.2f}]"  # noqa: E731
        L.append(f"| {h}d | {done[f'status_h{h}'].notna().sum()} | {_pct(ok.sum(), len(done))} ({ok.sum()}) | "
                 f"{_pct(done[f'fdr_val_h{h}'].sum(), len(done))} ({int(done[f'fdr_val_h{h}'].sum())}) | "
                 f"{_pct(done[f'fdr_test_h{h}'].sum(), len(done))} ({int(done[f'fdr_test_h{h}'].sum())}) | "
                 f"{f(ci)} | {f(bi)} |")
    L += ["", "## Which model families win", ""]
    for h in SWEEP_HORIZONS:
        if not len(done):
            break
        sel = done.loc[done[f"selected_h{h}"].notna(), f"selected_h{h}"]
        if len(sel):
            top = ", ".join(f"{m} {n}" for m, n in sel.value_counts().head(6).items())
            fams = ", ".join(f"{k} {v}" for k, v in sel.map(lambda m: fam.get(m, "?")).value_counts().items())
            L.append(f"- {h}d: {len(sel)} selections. By model: {top}. By family: {fams}.")
        else:
            L.append(f"- {h}d: no model was selected anywhere.")
    L += ["", "## Prediction intervals and regimes", ""]
    for h in SWEEP_HORIZONS:
        if not len(done):
            break
        c = done[f"cov90_h{h}"].dropna()
        w = done[f"regime_warnings_h{h}"].dropna()
        if len(c):
            L.append(f"- {h}d: median held-out coverage of the nominal 90% interval = {c.median():.3f} "
                     f"(mean {c.mean():.3f}); {_pct(((c >= .85) & (c <= .95)).sum(), len(c))} of stocks within 85-95%. "
                     f"Regime stability: {_pct((w > 0).sum(), len(w))} of reference models have at least one regime "
                     "bucket with fewer than 30 test observations (regime results unreliable there).")
    L += ["", "## Honesty section", "",
          "- Statistical power: each stock has roughly 4 years of validation and 2 of test data; h-day targets overlap, "
          "so the effective sample is n/h. Small true edges cannot be detected per stock; a non-win is not proof of no skill.",
          "- Multiple testing: with thousands of stocks x models x horizons, some wins occur by chance. At q=0.05 "
          "about 5% of rejections among the tests may be false even after BH, and BH assumes independence or positive "
          "dependence; stocks share market factors, so p-values are correlated.",
          "- Selection bias: the best-model columns pick the maximum over several models on the validation segment and "
          "overstate skill; only the test-confirmed column uses data the selection never saw.",
          "- Survivorship bias: only companies listed now are in the universe; delisted, merged and renamed companies "
          "are absent, which flatters any strategy. The BSE list is built from one day's Bhavcopy, so BSE scrips that did "
          "not trade that day are missing.",
          "- Yahoo data limits: adjusted prices are revised after the fact, not point-in-time; BSE-only and small-cap "
          "history can be thin, gapped or mis-adjusted; data-quality flags are in summary.parquet.",
          "- Nothing here is a trading edge. Errors are in forecast log returns and exclude costs, liquidity and "
          "capacity. Aggregate shares describe the models' validation, not expected profit."]
    text = "\n".join(L) + "\n"
    from pathlib import Path

    Path(path).write_text(text, encoding="utf-8")
    return text
