from modules.finance import personal

P = {"monthly_income": 120000, "risk_tolerance": "Conservative", "age": 30,
     "expenses": {"rent": 30000, "food": 15000, "other": 15000}, "assets": {"stocks": 200000, "mf": 100000, "cash": 100000, "fd": 100000, "gold": 100000},
     "goals": [{"name": "House", "target": 5e6, "years": 4}]}


def test_empty_profile():
    assert personal.stock_fit({}, 50, 1.5, "weak") is None
    assert personal.learner_context({}) == ""
    assert personal.market_caption({}) is None


def test_conservative_with_volatile_stock():
    fit = personal.stock_fit(P, 45, 1.4, "weak")
    assert "poor fit" in fit["lines"][0]
    sizing = next(l for l in fit["lines"] if l.startswith("Sizing"))
    assert "₹25k-₹50k" in sizing and "₹5.0L" in sizing  # 5-10% of 5L investable
    assert next(l for l in fit["lines"] if l.startswith("Horizon")).endswith("(aim for 5+).")
    assert fit["caveat"]


def test_learner_and_caption():
    ctx = personal.learner_context(P)
    assert "₹1-2L" in ctx and "SIP of ₹" in ctx and "200000" not in ctx
    assert "equity" in personal.market_caption(P)
