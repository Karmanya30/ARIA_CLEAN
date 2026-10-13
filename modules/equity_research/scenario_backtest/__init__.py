"""Historical scenario backtest: rebuild ARIA's bear/base/bull cases at past fiscal year-ends from point-in-time
data and compare them with what the company later reported. See data.py (cache + quality) and engine.py."""
ENGINE_VERSION = "sb2"  # sb2: yfinance fallback, short-history origins, provider/n_years columns
