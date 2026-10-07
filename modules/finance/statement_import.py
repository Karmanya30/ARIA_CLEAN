"""Bank/card statement and transaction-file parsing (pure functions, no I/O, no logging).

parse_statement(filename, data) -> {"format", "rows", "skipped", "warnings"}; summarize(rows) -> period,
summary and suggested profile. Row = {date ISO, merchant, amount (>0), direction 'debit'|'credit', category}.
Categories use the profile expense keys (food, rent, transport, utilities, entertainment, health, education,
other) plus emi / investment (debits reported separately) and income / credit (credits). to_store_category()
maps them to the forecaster's names (housing, medical, ...). Transaction contents are never logged.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

SUPPORTED = ".csv, .tsv, .txt, .xlsx, .xlsm, .xls, .pdf, .json, .ofx"
EXPENSE_KEYS = ("food", "rent", "transport", "utilities", "entertainment", "health", "education", "other")
MAX_ROWS = 20000
_STORE_CAT = {"rent": "housing", "health": "medical", "education": "other"}


class StatementError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def to_store_category(cat: str) -> str:
    return _STORE_CAT.get(cat, cat)


# ── cells ────────────────────────────────────────────────────────────────
_DATE_FORMATS = (
    "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%Y/%m/%d",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%d %B %Y", "%d-%B-%Y", "%b %d, %Y", "%d/%b/%Y", "%d%b%Y",
)


def parse_date(v: Any) -> str | None:
    """ISO date from a string, datetime or Excel serial; ambiguous numeric formats are day-first (India)."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:  # Excel serial (1954-2119)
            return (date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
        return None
    s = re.sub(r"[T\s]+\d{1,2}:\d{2}.*$", "", str(v).strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_amount(v: Any) -> float | None:
    """Signed float: handles ₹/Rs/INR, commas, (parentheses) and -negatives, trailing Dr (negative) / Cr."""
    if v is None or isinstance(v, bool) or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")") or "-" in s[:2]
    m = re.search(r"(dr|cr)\.?\s*$", s, re.I)
    if m:
        neg = neg or m.group(1).lower() == "dr"
    s = re.sub(r"(?i)rs\.?|inr|₹|[,\s()+-]|(dr|cr)\.?\s*$", "", s)
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


# ── header detection ─────────────────────────────────────────────────────
def _role(cell: Any) -> str | None:
    t = re.sub(r"[^a-z/ ]", " ", str(cell or "").lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return None
    if "balance" in t:
        return "balance"
    if any(w in t for w in ("chq", "cheque", "ref")):
        return "ref"
    if "date" in t:
        return "valdate" if "value" in t else "date"
    if t in ("dr/cr", "cr/dr", "type", "txn type", "transaction type", "debit/credit", "credit/debit"):
        return "drcr"
    if t.startswith(("withdraw", "debit")) or t == "dr":
        return "debit"
    if t.startswith(("deposit", "credit")) or t == "cr":
        return "credit"
    if "amount" in t:
        return "amount"
    if any(w in t for w in ("narration", "description", "particulars", "remarks", "details", "payee", "merchant")):
        return "desc"
    return None


def find_header(grid: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(grid[:40]):
        cols: dict[str, int] = {}
        for j, cell in enumerate(row):
            r = _role(cell)
            if r and r not in cols:
                cols[r] = j
        if "valdate" in cols and "date" not in cols:
            cols["date"] = cols["valdate"]
        if "date" in cols and ({"amount", "debit", "credit"} & cols.keys()):
            return i, cols
    return None


# ── categorisation / cleaning ────────────────────────────────────────────
_RULES = [  # first match wins; \b keeps short words (vi, ola, gas) from matching inside others
    ("investment", r"\bsip\b|mutual fund|zerodha|groww|\bnps\b|\bppf\b|\bmf\b"),
    ("emi", r"\bemi\b|\bloan\b|\bach\b|\bnach\b|\becs\b"),
    ("rent", r"\brent\b|landlord"),
    ("health", r"pharmac|hospital|apollo|clinic|insurance premium|medplus|\bdoctor\b|\blab\b"),
    ("education", r"school|college|tuition|udemy|coursera|university"),
    ("food", r"swiggy|zomato|restaurant|bigbasket|grocer|\bcafe\b|dominos|mcdonald|blinkit|zepto|dmart|\bfood\b"),
    ("transport", r"\buber\b|\bola\b|\bfuel\b|petrol|diesel|irctc|\bmetro\b|\brapido\b|fastag|redbus"),
    ("utilities", r"electric|bescom|airtel|\bjio\b|\bvi\b|vodafone|broadband|\bgas\b|\bwater\b|\bbsnl\b|recharge"),
    ("entertainment", r"netflix|prime|hotstar|spotify|bookmyshow|\bpvr\b|youtube|inox"),
]
_INCOME = re.compile(r"salary|payroll|\bsal\b", re.I)
_NOISE = {"upi", "imps", "neft", "rtgs", "ach", "pos", "ecom", "payment", "pay", "to", "from", "transfer", "ref",
          "dr", "cr", "txn", "pur", "debit", "credit", "atm", "by", "via", "mob", "ib", "nach", "trf", "paid"}
_SKIP_NARR = re.compile(r"opening balance|closing balance|brought forward|carried forward|\bb/f\b|\bc/f\b|^total|"
                        r"balance (b|c)/?f|statement summary", re.I)


def categorize(narration: str, direction: str) -> str:
    n = narration.lower()
    if direction == "credit":
        return "income" if _INCOME.search(n) else "credit"
    return next((c for c, p in _RULES if re.search(p, n)), "other")


def clean_merchant(narration: str) -> str:
    toks = []
    for t in re.split(r"[\s/\-_*:|,]+", narration.strip()):
        if (len(t) < 2 or "@" in t or re.fullmatch(r"\d{4,}", t) or re.fullmatch(r"[A-Za-z]{4}0[A-Za-z0-9]{3,}", t)
                or t.lower() in _NOISE or re.search(r"\d{6,}", t)):
            continue
        toks.append(t)
    out = " ".join(toks)
    out = out.title() if out.isupper() else out
    return out[:40].strip() or "Unknown"


# ── rows ─────────────────────────────────────────────────────────────────
def _grid_rows(grid: list[list[Any]], hdr: tuple[int, dict[str, int]]) -> tuple[list[dict], int]:
    start, c = hdr
    raws, skipped = [], 0
    get = lambda row, k: row[c[k]] if k in c and c[k] < len(row) else None  # noqa: E731
    for row in grid[start + 1:]:
        if not any(x not in (None, "") for x in row):
            continue
        iso, narr = parse_date(get(row, "date")), str(get(row, "desc") or "").strip()
        if iso is None or _SKIP_NARR.search(narr):
            skipped += 1
            continue
        d, cr = parse_amount(get(row, "debit")), parse_amount(get(row, "credit"))
        direction, amt = None, None
        if d or cr:
            direction, amt = ("debit", abs(d)) if d else ("credit", abs(cr))
        elif (a := parse_amount(get(row, "amount"))) is not None and a != 0:
            amt, mark = a, str(get(row, "drcr") or "").strip().lower()
            if mark[:1] in ("d", "w"):
                direction, amt = "debit", abs(a)
            elif mark[:1] == "c":
                direction, amt = "credit", abs(a)
        if amt is None:
            skipped += 1
            continue
        raws.append({"date": iso, "narr": narr, "amt": amt, "dir": direction, "ref": str(get(row, "ref") or "")})
    return raws, skipped


_AMT = re.compile(r"^\(?-?(?:₹|Rs\.?|INR)?[\d,]*\d\.\d{1,2}\)?(?:Dr|Cr)?\.?$", re.I)
_LINE_DATE = re.compile(r"^\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ,]*\d{2,4}|\d{4}-\d{2}-\d{2})\s+(.*)$")


_GLUED = re.compile(r"\d[\d,]*\.\d{2}")


def _text_rows(lines: list[str]) -> tuple[list[dict], int]:
    """Lines that start with a date and end with amount(s): `date narration amount [balance]`."""
    raws, skipped, prev_bal, open_row = [], 0, None, False
    for line in lines:
        m = _LINE_DATE.match(line)
        if not m:
            # a wrapped narration: undated, no amount, right after a transaction line
            if open_row and line.strip() and not _AMT.match(line.split()[-1]) and not _SKIP_NARR.search(line):
                raws[-1]["narr"] += " " + line.strip()
            else:
                open_row = False
            continue
        iso = parse_date(m.group(1).strip().replace(",", ""))
        toks, amts = [], []
        for t in m.group(2).split():  # split amounts glued together like '30,000.000.00'
            parts = _GLUED.findall(t)
            toks += parts if len(parts) > 1 and "".join(parts) == t else [t]
        open_row = False
        while toks and len(amts) < 3:
            if toks[-1].lower() in ("dr", "cr") and len(toks) > 1 and _AMT.match(toks[-2]):
                amts.insert(0, toks[-2] + toks[-1])
                del toks[-2:]
            elif _AMT.match(toks[-1]):
                amts.insert(0, toks.pop())
            else:
                break
        if toks and parse_date(toks[0]) and not _AMT.match(toks[0]):  # value-date column
            toks = toks[1:]
        narr = " ".join(toks)
        if iso is None or not amts or _SKIP_NARR.search(narr):
            skipped += 1
            continue
        nums = [parse_amount(a) for a in amts]
        bal = abs(nums[-1]) if len(nums) > 1 else None
        cands = nums[:-1] if len(nums) > 1 else nums
        pick = next((n for n in cands if n), cands[0])
        direction = None
        if re.search(r"dr\.?$", amts[0], re.I):
            direction = "debit"
        elif re.search(r"cr\.?$", amts[0], re.I):
            direction = "credit"
        elif bal is not None and prev_bal is not None:  # ponytail: balance delta; first row falls back to column/signed/debit
            direction = "credit" if bal > prev_bal else "debit"
        elif len(cands) == 2 and sum(1 for n in cands if n) == 1:  # withdrawal | deposit columns
            direction = "credit" if cands[1] else "debit"
        elif pick < 0:
            direction = "debit"
        else:
            direction = "credit" if _INCOME.search(narr) else "debit"
        prev_bal = bal if bal is not None else prev_bal
        raws.append({"date": iso, "narr": narr, "amt": abs(pick), "dir": direction, "ref": ""})
        open_row = True
    return raws, skipped


def _finalize(raws: list[dict], skipped: int, warnings: list[str]) -> dict:
    undecided = [r for r in raws if r["dir"] is None]
    has_neg = any(r["amt"] < 0 for r in undecided)
    if undecided and not has_neg:
        warnings.append("Amounts had no debit/credit marker and no negatives, so they were treated as spending.")
    rows, seen = [], set()
    for r in raws:
        direction = r["dir"] or ("debit" if r["amt"] < 0 or not has_neg and not _INCOME.search(r["narr"]) else "credit")
        key = (r["date"], abs(r["amt"]), direction, r["narr"], r["ref"])
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        rows.append({"date": r["date"], "merchant": clean_merchant(r["narr"]), "amount": round(abs(r["amt"]), 2),
                     "direction": direction, "category": categorize(r["narr"], direction)})
        if len(rows) > MAX_ROWS:
            raise StatementError(f"This file has more than {MAX_ROWS:,} transactions. Please upload a shorter period.")
    return {"rows": rows, "skipped": skipped, "warnings": warnings}


def _from_grids(grids: list[list[list[Any]]], warnings: list[str]) -> dict | None:
    for grid in grids:
        hdr = find_header(grid)
        if hdr:
            raws, skipped = _grid_rows(grid, hdr)
            if raws:
                return _finalize(raws, skipped, warnings)
    return None


# ── readers ──────────────────────────────────────────────────────────────
def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _delimited(text: str) -> list[list[str]]:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _xlsx_grids(data: bytes) -> list[list[list[Any]]]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise StatementError("This Excel file could not be opened. It may be corrupt or password-protected.")
    return [[list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]


def _xls_grids(data: bytes) -> list[list[list[Any]]]:
    try:
        import pandas as pd

        sheets = pd.read_excel(io.BytesIO(data), header=None, sheet_name=None, dtype=object)
    except Exception:
        raise StatementError("Old .xls files can't be read here. Please re-save the file as .xlsx or CSV and upload again.")
    return [df.where(df.notna(), None).values.tolist() for df in sheets.values()]


def _pdf_lines(data: bytes, layout: bool = True) -> list[str]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise StatementError("This PDF is password-protected. Please remove the password (or download an unlocked "
                                 "copy from your bank) and upload again.")
        text = "\n".join((p.extract_text(extraction_mode="layout") if layout else p.extract_text()) or "" for p in reader.pages)
    except StatementError:
        raise
    except Exception:
        raise StatementError("This PDF could not be read. Try downloading the statement as CSV or Excel instead.")
    if len(text.strip()) < 20:
        raise StatementError("This PDF looks like a scan or image, so there is no text to read. Please download the "
                             "statement as CSV, Excel or a text-based PDF from your bank.")
    return text.splitlines()


def _json_grid(data: bytes) -> list[list[Any]]:
    try:
        obj = json.loads(decode(data))
    except ValueError:
        raise StatementError("This JSON file is not valid.")
    if isinstance(obj, dict):
        obj = next((v for v in obj.values() if isinstance(v, list)), [])
    if not isinstance(obj, list) or not all(isinstance(o, dict) for o in obj):
        raise StatementError("JSON must be a list of transaction objects.")
    keys = list(dict.fromkeys(k for o in obj for k in o))
    return [keys] + [[o.get(k) for k in keys] for o in obj]


def _ofx_grid(text: str) -> list[list[Any]]:
    tag = lambda b, t: (m.group(1).strip() if (m := re.search(rf"<{t}>([^<\r\n]*)", b)) else "")  # noqa: E731
    rows = [["date", "description", "amount"]]
    for b in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|$)", text, re.S):
        d = tag(b, "DTPOSTED")[:8]
        rows.append([f"{d[:4]}-{d[4:6]}-{d[6:8]}", tag(b, "NAME") or tag(b, "MEMO"), tag(b, "TRNAMT")])
    return rows


def parse_statement(filename: str, data: bytes) -> dict:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in SUPPORTED.replace(" ", "").split(","):
        raise StatementError(f"Unsupported file type. Supported formats: {SUPPORTED}.", 415)
    warnings: list[str] = []
    result = None
    if ext in (".xlsx", ".xlsm"):
        result = _from_grids(_xlsx_grids(data), warnings)
    elif ext == ".xls":
        result = _from_grids(_xls_grids(data), warnings)
    elif ext == ".json":
        result = _from_grids([_json_grid(data)], warnings)
    elif ext == ".pdf":
        raws, skipped = _text_rows(_pdf_lines(data))
        if not raws:  # layout mode found nothing: try pypdf's plain reading order
            raws, skipped = _text_rows(_pdf_lines(data, layout=False))
        result = _finalize(raws, skipped, warnings) if raws else None
    else:  # csv / tsv / txt / ofx: sniff delimited, then fall back to free-text lines
        text = decode(data)
        grid = _ofx_grid(text) if ext == ".ofx" else _delimited(text)
        result = _from_grids([grid], warnings)
        if result is None:
            raws, skipped = _text_rows(text.splitlines())
            result = _finalize(raws, skipped, warnings) if raws else None
    if result is None or not result["rows"]:
        raise StatementError("I couldn't find any transactions in this file. It needs a date column and an amount "
                             "(or debit/credit) column, or lines that start with a date and end with an amount.")
    return {"format": ext.lstrip("."), **result}


# ── summary ──────────────────────────────────────────────────────────────
def summarize(rows: list[dict]) -> dict:
    dates = sorted(r["date"] for r in rows)
    d0, d1 = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    months = (d1.year - d0.year) * 12 + d1.month - d0.month + 1
    by_cat: dict[str, float] = {}
    for r in rows:
        if r["direction"] == "debit" and r["category"] in EXPENSE_KEYS:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
    total = lambda pred: round(sum(r["amount"] for r in rows if pred(r)), 2)  # noqa: E731
    income, salary = total(lambda r: r["direction"] == "credit"), total(lambda r: r["category"] == "income")
    monthly_avg = {k: round(v / months, 2) for k, v in by_cat.items()}
    enough = (d1 - d0).days >= 27  # ponytail: about a month of data before suggesting expenses
    return {
        "period": {"from": dates[0], "to": dates[-1], "months": months},
        "summary": {
            "expenses_by_category": {k: round(v, 2) for k, v in by_cat.items()},
            "monthly_avg": monthly_avg,
            "total_expenses": round(sum(by_cat.values()), 2),
            "total_income": income,
            "avg_monthly_income": round(income / months, 2),
            "emi_total": total(lambda r: r["direction"] == "debit" and r["category"] == "emi"),
            "investment_total": total(lambda r: r["direction"] == "debit" and r["category"] == "investment"),
        },
        "suggested_profile": {
            "expenses": {k: round(v) for k, v in monthly_avg.items()} if enough else {},
            "monthly_income": round(salary / months) if salary else None,
        },
    }
