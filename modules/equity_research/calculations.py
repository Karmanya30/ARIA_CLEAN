from typing import Dict, Any, Optional, List


def _get_field_series(data: Dict[str, Any], field: str) -> List[Optional[float]]:
    """Extract the ordered series from a normalized field."""
    field_data = data.get(field, {})
    if isinstance(field_data, dict):
        return field_data.get("series", [])
    # Legacy: plain list
    return field_data if isinstance(field_data, list) else []


def _latest_two(series: List[Optional[float]]):
    """Return (latest, previous) non-None values from the end of the series."""
    non_null = [v for v in series if v is not None]
    if len(non_null) < 2:
        return None, None
    return non_null[-1], non_null[-2]


def calculate_revenue_growth(data: Dict[str, Any]) -> Optional[float]:
    """Revenue growth % between the latest two annual periods."""
    latest, prev = _latest_two(_get_field_series(data, "revenue"))
    if latest is None or prev is None or prev == 0:
        return None
    return ((latest - prev) / abs(prev)) * 100.0


def calculate_profit_growth(data: Dict[str, Any]) -> Optional[float]:
    """Net profit growth % between the latest two annual periods."""
    latest, prev = _latest_two(_get_field_series(data, "net_profit"))
    if latest is None or prev is None or prev == 0:
        return None
    return ((latest - prev) / abs(prev)) * 100.0


def calculate_debt_change(data: Dict[str, Any]) -> Optional[float]:
    """Absolute change in debt/borrowings between the latest two annual periods."""
    latest, prev = _latest_two(_get_field_series(data, "debt"))
    if latest is None or prev is None:
        return None
    return latest - prev


def calculate_de_ratio(data: Dict[str, Any]) -> Optional[float]:
    """Debt-to-equity ratio for the latest period."""
    debt_series  = _get_field_series(data, "debt")
    equity_series = _get_field_series(data, "equity")

    debt_non_null   = [v for v in debt_series if v is not None]
    equity_non_null = [v for v in equity_series if v is not None]

    if not debt_non_null or not equity_non_null:
        return None
    latest_debt   = debt_non_null[-1]
    latest_equity = equity_non_null[-1]
    if latest_equity == 0:
        return None
    return latest_debt / latest_equity

