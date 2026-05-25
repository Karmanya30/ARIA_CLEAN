import re
from typing import Dict, Any, Optional, List

from ai.data.screener_adapter import get_screener_data
from ai.data.data_normalizer import normalize_screener_data, get_value_for_fy, _fy_to_mar
from ai.analysis.metric_router import route_metric, get_calculation_function
from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import screener_data_prompt


def _extract_fiscal_years(query: str) -> List[str]:
    """
    Pull fiscal year mentions out of a query string.
    Returns a list like ['FY22-23', 'FY21-22'] in the order found.
    """
    # Match: FY22-23, FY 22-23, 2022-23, 22-23, FY2023, etc.
    patterns = [
        r"(?:FY\s*)?(\d{2,4}[-/]\d{2,4})",   # FY22-23 or 2022-23
        r"(?:FY\s*)(\d{4})",                    # FY2023
        r"financial year\s+(\d{4})",            # financial year 2023
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, query, re.IGNORECASE):
            fy = m.group(1).replace("/", "-")
            if fy not in found:
                found.append(fy)
    return found


def _build_year_context(normalized_data: Dict[str, Any], years: List[str]) -> str:
    """
    Build a compact year-labeled context string for the LLM prompt.
    e.g. "Debt: FY22-23 (Mar 2023) = 189,062 Cr  |  FY21-22 (Mar 2022) = 161,603 Cr"
    """
    if not years:
        return ""

    lines = []
    for field, label in [("debt", "Debt/Borrowing"), ("revenue", "Revenue/Sales"),
                         ("net_profit", "Net Profit"), ("equity", "Equity")]:
        field_data = normalized_data.get(field, {})
        if not field_data.get("by_year"):
            continue
        vals = []
        for fy in years:
            v = get_value_for_fy(field_data, fy)
            mar = _fy_to_mar(fy) or fy
            if v is not None:
                vals.append(f"{fy} ({mar}) = {v:,.2f} Cr")
        if vals:
            lines.append(f"{label}: " + "  |  ".join(vals))

    return "\n".join(lines) if lines else ""


def _calculate_year_specific_change(normalized_data: Dict[str, Any],
                                    field: str, years: List[str]) -> Optional[float]:
    """
    Calculate the change between two specified fiscal years for a given field.
    Returns None if either year is missing.
    """
    if len(years) < 2:
        return None
    field_data = normalized_data.get(field, {})
    v1 = get_value_for_fy(field_data, years[0])
    v2 = get_value_for_fy(field_data, years[1])
    if v1 is None or v2 is None:
        return None
    return v1 - v2


def process_financial_query(query: str, company: str) -> Dict[str, Any]:
    """
    Full data-grounded financial pipeline:
    Fetch → Normalize → Extract years → Route → Calculate → LLM(grounded) → Response
    """
    # Step 1: Fetch
    raw_data = get_screener_data(company)
    if "error" in raw_data:
        return {
            "metric": "unknown", "value": None, "normalized_data": {},
            "explanation": f"Could not retrieve data for {company}. {raw_data['error']}",
            "confidence": "low",
        }

    # Step 2: Normalize with year labels
    normalized_data = normalize_screener_data(raw_data)

    # Step 3: Extract specific fiscal years from query
    fiscal_years = _extract_fiscal_years(query)
    year_context = _build_year_context(normalized_data, fiscal_years)

    # Step 4: Route metric
    metric_id = route_metric(query)

    # Determine value: year-specific if years mentioned, else latest-vs-previous
    result = None
    metric_name = "General Analysis"

    if metric_id:
        calc_func = get_calculation_function(metric_id)
        metric_name = metric_id.replace("calculate_", "").replace("_", " ").title()

        # Try year-specific calculation first
        if len(fiscal_years) >= 2 and "debt" in metric_id:
            result = _calculate_year_specific_change(normalized_data, "debt", fiscal_years)
        elif len(fiscal_years) >= 2 and "revenue" in metric_id:
            result = _calculate_year_specific_change(normalized_data, "revenue", fiscal_years)
        elif len(fiscal_years) >= 2 and "profit" in metric_id:
            result = _calculate_year_specific_change(normalized_data, "net_profit", fiscal_years)

        # Fall back to latest-vs-previous if year-specific failed
        if result is None and calc_func:
            result = calc_func(normalized_data)

    # Step 5: Build grounded prompt and call Groq
    # Pass year-labeled context so LLM knows exactly which years to reference
    debt_field = normalized_data.get("debt", {})
    recent_debt = {k: v for k, v in list(debt_field.get("by_year", {}).items())[-6:]}

    profit_field = normalized_data.get("net_profit", {})
    recent_profit = {k: v for k, v in list(profit_field.get("by_year", {}).items())[-6:]}

    revenue_field = normalized_data.get("revenue", {})
    recent_revenue = {k: v for k, v in list(revenue_field.get("by_year", {}).items())[-6:]}

    value_str = f"{result:,.2f} Cr" if result is not None else "N/A"

    grounded_prompt = f"""\
You are ARIA, an Indian financial analysis assistant.

STRICT RULES:
1. Use ONLY the numbers provided below. Do NOT invent any values.
2. All figures are in ₹ Crore (Cr) from Screener.in.
3. Be factual and concise. State source as "Screener.in data".

COMPANY: {company}
USER QUERY: {query}

REAL DATA FROM SCREENER.IN (₹ Crore):
Debt/Borrowings by year: {recent_debt}
Net Profit by year: {recent_profit}
Revenue/Sales by year: {recent_revenue}

{f"YEAR-SPECIFIC DATA FOR QUERY:{chr(10)}{year_context}" if year_context else ""}

COMPUTED RESULT:
Metric: {metric_name}
Value: {value_str}
{f"Fiscal years compared: {' vs '.join(fiscal_years)}" if fiscal_years else ""}

TASK: Write a 3-5 sentence financial analysis. Use this exact format:
Insight: <direct answer with the exact numbers from above>
Analysis: <what these numbers mean>
Recommendation: <one practical takeaway>
Risk: <one relevant risk or caveat>

Stop after Risk.
"""

    explanation = generate_response(grounded_prompt)
    confidence = "high" if result is not None else "medium"

    return {
        "metric": metric_name,
        "value": result,
        "normalized_data": normalized_data,
        "explanation": explanation,
        "confidence": confidence,
    }

