import re
from typing import Dict, List, Any, Optional


def _parse_numeric(value: Any) -> Optional[float]:
    """Convert a string like '1,89,062' or '12.5%' to float. Returns None if not parseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        clean = value.replace(",", "").replace("%", "").strip()
        if clean in ("", "-", "--", "N/A"):
            return None
        try:
            return float(clean)
        except ValueError:
            return None
    return None


def _fy_to_mar(fy_str: str) -> Optional[str]:
    """
    Convert a fiscal year mention to screener's 'Mar YYYY' column label.
    Examples:
        'FY22-23'  → 'Mar 2023'
        'FY 2023'  → 'Mar 2023'
        '22-23'    → 'Mar 2023'
        '2023'     → 'Mar 2023'
    Returns None if the year cannot be determined.
    """
    fy_str = fy_str.strip().upper().replace("FY", "").strip()

    # Match 'XX-YY' or 'XXXX-YY' patterns
    m = re.match(r"(\d{2,4})-(\d{2,4})", fy_str)
    if m:
        end_part = m.group(2)
        end_year = int(end_part) if len(end_part) == 4 else 2000 + int(end_part)
        return f"Mar {end_year}"

    # Match single 4-digit year
    m = re.match(r"(\d{4})", fy_str)
    if m:
        return f"Mar {m.group(1)}"

    # Match 2-digit year
    m = re.match(r"(\d{2})", fy_str)
    if m:
        return f"Mar {2000 + int(m.group(1))}"

    return None


def _pick_row(table: dict, *keys: str) -> dict:
    """
    Return the first year-keyed dict found for any of the given row keys
    (case-insensitive). Falls back to an empty dict.
    """
    table_lower = {k.lower(): v for k, v in table.items() if k != "__columns__"}
    for key in keys:
        val = table_lower.get(key.lower())
        if val and isinstance(val, dict):
            return val
    return {}


def _row_to_series(row_dict: dict, columns: List[str]) -> List[Optional[float]]:
    """Convert a year-keyed row dict to an ordered list aligned with columns."""
    return [_parse_numeric(row_dict.get(col)) for col in columns]


def normalize_screener_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes raw year-keyed screener data into two forms:
    - 'series': ordered list of floats (aligned with columns)
    - 'by_year': {year_label: float} for targeted year lookups
    - 'columns': the list of year labels

    Handles both regular companies and banks.
    """
    if "error" in raw_data:
        return raw_data

    quarterly  = raw_data.get("quarterly_results", {})
    profit_loss = raw_data.get("profit_loss", {})
    balance_sheet = raw_data.get("balance_sheet", {})

    pl_cols = profit_loss.get("__columns__", [])
    bs_cols = balance_sheet.get("__columns__", [])
    q_cols  = quarterly.get("__columns__", [])

    # Revenue
    revenue_row = (
        _pick_row(profit_loss, "Sales", "Revenue", "Net Interest Income", "Interest Earned")
        or _pick_row(quarterly, "Sales", "Revenue")
    )
    revenue_cols = pl_cols or q_cols

    # Net Profit
    profit_row = (
        _pick_row(profit_loss, "Net Profit", "Profit after Tax", "PAT")
        or _pick_row(quarterly, "Net Profit", "Profit after Tax")
    )
    profit_cols = pl_cols or q_cols

    # Debt / Borrowings
    debt_row = _pick_row(
        balance_sheet,
        "Borrowings",        # standard companies
        "Borrowing",         # banks (singular on screener)
        "Total Debt",
        "Long Term Borrowings",
    )

    # Equity
    equity_row = _pick_row(
        balance_sheet,
        "Share Capital",
        "Equity Capital",
        "Shareholders Equity",
        "Net Worth",
        "Reserves",
    )

    def build(row: dict, cols: List[str]) -> Dict[str, Any]:
        series = _row_to_series(row, cols)
        by_year = {col: val for col, val in zip(cols, series) if val is not None}
        return {"series": series, "by_year": by_year, "columns": cols}

    return {
        "revenue":    build(revenue_row, revenue_cols),
        "net_profit": build(profit_row, profit_cols),
        "debt":       build(debt_row, bs_cols),
        "equity":     build(equity_row, bs_cols),
    }


def get_value_for_fy(normalized_field: Dict[str, Any], fy_str: str) -> Optional[float]:
    """
    Look up a specific fiscal year value from a normalized field.
    e.g. get_value_for_fy(data['debt'], 'FY22-23') → 189062.0
    """
    label = _fy_to_mar(fy_str)
    if label is None:
        return None
    return normalized_field.get("by_year", {}).get(label)

