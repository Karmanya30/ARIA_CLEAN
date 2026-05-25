"""Thin orchestrator for ARIA."""

from typing import Any

from core.router import route_query
from core.session import save_turn
from modules.finance.pipeline import run_pipeline as finance_pipeline
from modules.market.investment import (
    investment_module,
    is_broad_market_query,
    is_fundamental_query,
    is_investment_query,
)
from modules.market.pipeline import run_pipeline as market_pipeline
from modules.tutor.pipeline import run_pipeline as tutor_pipeline
from shared.company_resolver import resolve_company


def handle_query(query: str, session_id: str = "default", mode: str = "Normal Mode") -> dict[str, Any]:
    """Route a user query to the correct module pipeline."""
    
    if mode == "Conversational Mode":
        from core.session import get_session
        from ai.llm.groq_client import generate_response
        
        session = get_session(session_id)
        history = session.get("history", [])[-3:] # Last 3 turns
        if history:
            history_str = ""
            for i, turn in enumerate(history):
                history_str += f"User: {turn['query']}\n"
            
            prompt = f"""
Given this chat history:
{history_str}

Rewrite the user's follow-up query to be fully self-contained. 
If it refers to a company or topic from the history, explicitly include it in the new query.
If it is already standalone, return it exactly as is.
Return ONLY the rewritten query. Do not add any conversational text.

Follow-up query: {query}
"""
            rewritten = generate_response(prompt, system_prompt="You rewrite queries. Output ONLY the rewritten query.")
            if rewritten and not rewritten.lower().startswith("error"):
                query = rewritten.strip('"\' \n')

    domain = route_query(query)

    # Fundamental financial analysis about a company → screener pipeline
    if is_fundamental_query(query) and resolve_company(query):
        response = finance_pipeline(query)

    # Live stock price / market queries → investment module
    elif is_investment_query(query):
        response = investment_module(query)

    elif domain == "finance":
        response = finance_pipeline(query)
    elif domain == "market":
        response = market_pipeline(query) if is_broad_market_query(query) else investment_module(query)
    elif domain == "tutor":
        response = tutor_pipeline(query)
    else:
        response = tutor_pipeline(query)
        response["domain"] = "general"

    save_turn(session_id, query, response)
    return response


class Orchestrator:
    """Small class wrapper for callers that prefer object style."""

    def handle(self, user_input: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        session_id = str((context or {}).get("session_id", "default"))
        return handle_query(user_input, session_id=session_id)
