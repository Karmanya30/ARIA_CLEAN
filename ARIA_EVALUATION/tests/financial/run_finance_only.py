"""Runs only the modules/finance sections of run_financial_validation (no equity_research)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import run_financial_validation as V
from harness import Rec
for name, fn, pre in [("sip_emi", V.sec_sip_emi, "SIP"), ("tax", V.sec_tax, "TAX"), ("engine", V.sec_engine, "ENG")]:
    r = Rec(name, pre); fn(r); r.save()
