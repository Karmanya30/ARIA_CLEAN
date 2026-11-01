"""Clarification of generic company requests before the entity lookup."""
import re


def generic_company_request(text: str) -> bool:
    """Ask for a company only when the user has not supplied an entity."""
    from shared.company_resolver import resolve_company
    generic = (re.search(r"\b(?:a|any|some) company(?:[\'’]s)?\b", text, re.I)
               and re.search(r"\b(?:analys[ei]|analy[sz]e|analysis|fundamentals?|financials?|valuation)\b", text, re.I))
    if not generic or resolve_company(text):
        return False
    if re.search(r"\b(?:called|named|such as|like|for example)\b|:", text, re.I):
        return False
    if re.search(r"\bfor\s+(?!(?:me|us|you|my|a|an|the|any|this|that|example)\b)[A-Z][\w.&-]*", text):
        return False
    return True
