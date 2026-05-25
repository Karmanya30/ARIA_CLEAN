from typing import Callable, Optional
from ai.analysis.calculations import (
    calculate_revenue_growth,
    calculate_profit_growth,
    calculate_debt_change,
    calculate_de_ratio
)

def route_metric(query: str) -> Optional[str]:
    """
    Routes a query string to the appropriate calculation identifier based on keywords.
    """
    query = query.lower()
    
    if "revenue growth" in query or "sales growth" in query or "difference in revenue" in query:
        return "calculate_revenue_growth"
    elif "profit change" in query or "profit growth" in query or "net profit" in query:
        return "calculate_profit_growth"
    elif "debt change" in query or "change in debt" in query or "difference in" in query and "debt" in query:
        return "calculate_debt_change"
    elif "debt to equity" in query or "d/e ratio" in query:
        return "calculate_de_ratio"
        
    return None

def get_calculation_function(identifier: str) -> Optional[Callable]:
    """
    Returns the calculation function for a given identifier.
    """
    func_map = {
        "calculate_revenue_growth": calculate_revenue_growth,
        "calculate_profit_growth": calculate_profit_growth,
        "calculate_debt_change": calculate_debt_change,
        "calculate_de_ratio": calculate_de_ratio
    }
    return func_map.get(identifier)

