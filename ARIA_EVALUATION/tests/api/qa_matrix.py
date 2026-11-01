"""Endpoint matrix for ARIA's HTTP API (QA agent, Phase A).

One table, two consumers:
  * test_endpoint_matrix.py  - in-process (FastAPI TestClient, scratch SQLite DB), run by pytest.
  * run_matrix.py            - the same cases against a live isolated instance (e.g. http://127.0.0.1:8012).

Each case: id, op ("METHOD /openapi/path"), kind (valid|invalid|missing|oversized|abuse), request kwargs
(httpx style; a callable is evaluated lazily so big payloads are not held in memory), ok = acceptable status codes.
`net=True` means the endpoint needs live market data; 503 (upstream unavailable) is then also acceptable.
`known` = defect id from QA_REPORT.md for behaviour that currently fails the rule "4xx, never 5xx, no stack trace".
"""
from __future__ import annotations

O = "qa-owner-1"          # synthetic owner / session id (private mode: any string is a capability)
S = "qa-session-1"
CSV = (b"Date,Narration,Withdrawal Amt.,Deposit Amt.\n"
       b"01/05/2024,ZOMATO ORDER,250.50,\n02/05/2024,SALARY ACME,,50000\n03/05/2024,ELECTRICITY BILL,2400,\n")
TXN = {"session_id": O, "date": "2026-01-15", "category": "food", "amount": 450.0, "merchant": "Cafe", "channel": "upi"}
DEFAULT_ORIGIN = "http://localhost:8012"


def c(cid, op, kind, ok, net=False, known=None, **req):
    return {"id": cid, "op": op, "kind": kind, "ok": set(ok), "net": net, "known": known, "req": req}


def big(n):  # lazily built oversized payloads
    return lambda: b"x" * n


CASES = [
    # ---- chat ---------------------------------------------------------------------------------------------------
    c("chat-valid", "POST /api/chat", "valid", [200], json={"query": "What is a SIP?", "session_id": S, "owner_id": O}),
    c("chat-empty-query", "POST /api/chat", "invalid", [422], json={"query": "", "session_id": S}),
    c("chat-blank-query", "POST /api/chat", "invalid", [422], json={"query": "   ", "session_id": S}),
    c("chat-missing-session", "POST /api/chat", "missing", [422], json={"query": "hi"}),
    c("chat-wrong-type", "POST /api/chat", "invalid", [422], json={"query": 123, "session_id": S}),
    c("chat-long-query", "POST /api/chat", "oversized", [422], json={"query": "a" * 20001, "session_id": S}),
    c("chat-long-session", "POST /api/chat", "oversized", [422], json={"query": "hi", "session_id": "s" * 201}),
    c("chat-bad-channel", "POST /api/chat", "invalid", [422], json={"query": "hi", "session_id": S, "channel": "nope"}),
    c("chat-history-too-long", "POST /api/chat", "oversized", [422], json={"query": "hi", "session_id": S, "history": [{}] * 21}),
    c("chat-not-json", "POST /api/chat", "invalid", [422], content=b"{not json", headers={"content-type": "application/json"}),
    c("chat-body-13MB", "POST /api/chat", "oversized", [413], content=big(13 * 1024 * 1024), headers={"content-type": "application/json"}),
    c("chat-bad-mode", "POST /api/chat", "invalid", [200, 422], json={"query": "hi", "session_id": S, "mode": "bogus"}),
    c("chat-injection", "POST /api/chat", "abuse", [200], json={"query": "'; DROP TABLE users;-- <script>alert(1)</script>", "session_id": S, "owner_id": O}),
    c("history-valid", "GET /api/chat/history", "valid", [200], params={"session_id": S, "owner_id": O}),
    c("history-missing", "GET /api/chat/history", "missing", [422]),
    c("history-unknown-session", "GET /api/chat/history", "invalid", [200, 404], params={"session_id": "does-not-exist"}),
    c("context-disabled", "GET /api/chat/context", "valid", [404], params={"session_id": S, "query": "x"}),
    c("context-missing", "GET /api/chat/context", "missing", [422]),
    c("clear-valid", "POST /api/chat/clear", "valid", [200], json={"session_id": "qa-clear-1", "owner_id": O}),
    c("clear-missing-key", "POST /api/chat/clear", "missing", [422], json={}, known="QA-001"),
    c("clear-wrong-type", "POST /api/chat/clear", "invalid", [422], json={"session_id": 5}),
    c("clear-list-body", "POST /api/chat/clear", "invalid", [422], json=["a"]),
    # ---- feedback -----------------------------------------------------------------------------------------------
    c("feedback-status", "GET /api/feedback/status", "valid", [200]),
    c("feedback-valid-unconfigured", "POST /api/feedback", "valid", [503],
      json={"name": "QA", "email": "qa@example.com", "discovery": "friend", "category": "bug", "message": "synthetic feedback body"},
      headers={"origin": DEFAULT_ORIGIN}),
    c("feedback-no-origin", "POST /api/feedback", "invalid", [403],
      json={"name": "QA", "email": "qa@example.com", "discovery": "friend", "category": "bug", "message": "synthetic feedback body"}),
    c("feedback-missing-fields", "POST /api/feedback", "missing", [422], json={"name": "QA"}, headers={"origin": DEFAULT_ORIGIN}),
    c("feedback-bad-email", "POST /api/feedback", "invalid", [422],
      json={"name": "QA", "email": "not-an-email", "discovery": "x", "category": "bug", "message": "synthetic feedback body"}, headers={"origin": DEFAULT_ORIGIN}),
    c("feedback-header-injection", "POST /api/feedback", "abuse", [422],
      json={"name": "QA\r\nBcc: x@evil.test", "email": "qa@example.com", "discovery": "x", "category": "bug", "message": "synthetic feedback body"}, headers={"origin": DEFAULT_ORIGIN}),
    c("feedback-long-message", "POST /api/feedback", "oversized", [422],
      json={"name": "QA", "email": "qa@example.com", "discovery": "x", "category": "bug", "message": "m" * 5001}, headers={"origin": DEFAULT_ORIGIN}),
    c("feedback-extra-field", "POST /api/feedback", "invalid", [422],
      json={"name": "QA", "email": "qa@example.com", "discovery": "x", "category": "bug", "message": "synthetic feedback body", "bcc": "x@y.z"}, headers={"origin": DEFAULT_ORIGIN}),
    # ---- voice / audio ------------------------------------------------------------------------------------------
    c("transcribe-no-file", "POST /api/voice/transcribe", "missing", [422]),
    c("transcribe-empty", "POST /api/voice/transcribe", "invalid", [422], files={"file": ("a.wav", b"", "audio/wav")}),
    c("transcribe-11MB", "POST /api/voice/transcribe", "oversized", [413], files={"file": ("a.wav", big(11 * 1024 * 1024), "audio/wav")}),
    c("transcribe-garbage", "POST /api/voice/transcribe", "invalid", [415, 422, 502], files={"file": ("a.wav", b"not audio at all", "audio/wav")}),
    c("audio-unknown-token", "GET /api/audio/{token}", "invalid", [404], path="/api/audio/deadbeef"),
    c("audio-traversal-token", "GET /api/audio/{token}", "abuse", [404], path="/api/audio/..%2F..%2Fetc%2Fpasswd"),
    # ---- profile ------------------------------------------------------------------------------------------------
    c("profile-save", "POST /api/profile", "valid", [200], json={"session_id": O, "monthly_income": 85000, "age": 31}),
    c("profile-get", "GET /api/profile", "valid", [200], params={"session_id": O}),
    c("profile-get-missing", "GET /api/profile", "missing", [422]),
    c("profile-summary", "GET /api/profile/summary", "valid", [200], params={"session_id": O}),
    c("profile-summary-missing", "GET /api/profile/summary", "missing", [422]),
    c("profile-save-missing-session", "POST /api/profile", "missing", [422], json={"monthly_income": 1}),
    c("profile-negative-income", "POST /api/profile", "invalid", [422], json={"session_id": O, "monthly_income": -5}),
    c("profile-string-income", "POST /api/profile", "invalid", [422], json={"session_id": O, "monthly_income": "lots"}),
    c("profile-huge-income", "POST /api/profile", "invalid", [422], json={"session_id": O, "monthly_income": 1e300}),
    c("profile-age-200", "POST /api/profile", "invalid", [422], json={"session_id": O, "age": 200}),
    c("profile-nan", "POST /api/profile", "invalid", [422], content=b'{"session_id":"qa-owner-1","monthly_income":NaN}', headers={"content-type": "application/json"}),
    c("profile-long-session", "POST /api/profile", "oversized", [422], json={"session_id": "s" * 201}),
    c("profile-delete-style", "DELETE /api/profile/style", "valid", [200], params={"session_id": O}),
    c("profile-delete-style-missing", "DELETE /api/profile/style", "missing", [422]),
    c("profile-delete", "DELETE /api/profile", "valid", [200], params={"session_id": "qa-delete-me"}),
    c("profile-delete-missing", "DELETE /api/profile", "missing", [422]),
    # ---- transactions -------------------------------------------------------------------------------------------
    c("txn-add", "POST /api/transactions", "valid", [200], json=TXN),
    c("txn-list", "GET /api/transactions", "valid", [200], params={"session_id": O}),
    c("txn-list-missing", "GET /api/transactions", "missing", [422]),
    c("txn-insights", "GET /api/transactions/insights", "valid", [200], params={"session_id": O}),
    c("txn-insights-missing", "GET /api/transactions/insights", "missing", [422]),
    c("txn-bad-category", "POST /api/transactions", "invalid", [422], json={**TXN, "category": "gambling"}),
    c("txn-zero", "POST /api/transactions", "invalid", [422], json={**TXN, "amount": 0}),
    c("txn-negative", "POST /api/transactions", "invalid", [422], json={**TXN, "amount": -10}),
    c("txn-1e12", "POST /api/transactions", "oversized", [422], json={**TXN, "amount": 1e12}),
    c("txn-nan", "POST /api/transactions", "invalid", [422], content=b'{"session_id":"x","date":"2026-01-01","category":"food","amount":NaN}', headers={"content-type": "application/json"}),
    c("txn-bad-date", "POST /api/transactions", "invalid", [422], json={**TXN, "date": "31-31-2026"}),
    c("txn-bad-channel", "POST /api/transactions", "invalid", [422], json={**TXN, "channel": "bitcoin"}),
    c("txn-long-merchant", "POST /api/transactions", "oversized", [422], json={**TXN, "merchant": "m" * 301}),
    c("txn-missing-fields", "POST /api/transactions", "missing", [422], json={"session_id": O}),
    c("txn-sample", "POST /api/transactions/sample", "valid", [200], json={"session_id": "qa-sample-1"}),
    c("txn-sample-missing", "POST /api/transactions/sample", "missing", [422], json={}),
    c("txn-parse-valid", "POST /api/transactions/parse", "valid", [200], data={"session_id": O}, files={"file": ("statement.csv", CSV, "text/csv")}),
    c("txn-parse-no-file", "POST /api/transactions/parse", "missing", [422], data={"session_id": O}),
    c("txn-parse-no-session", "POST /api/transactions/parse", "missing", [422], files={"file": ("s.csv", CSV, "text/csv")}),
    c("txn-parse-empty", "POST /api/transactions/parse", "invalid", [400, 422], data={"session_id": O}, files={"file": ("s.csv", b"", "text/csv")}),
    c("txn-parse-garbage-binary", "POST /api/transactions/parse", "invalid", [400, 415, 422], data={"session_id": O}, files={"file": ("s.xlsx", b"\x00\x01\x02garbage", "application/octet-stream")}),
    c("txn-parse-exe", "POST /api/transactions/parse", "invalid", [400, 415, 422], data={"session_id": O}, files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")}),
    c("txn-parse-6MB", "POST /api/transactions/parse", "oversized", [413], data={"session_id": O}, files={"file": ("big.csv", big(6 * 1024 * 1024), "text/csv")}),
    c("txn-parse-13MB", "POST /api/transactions/parse", "oversized", [413], data={"session_id": O}, files={"file": ("big.csv", big(13 * 1024 * 1024), "text/csv")}),
    c("txn-parse-formula-cells", "POST /api/transactions/parse", "abuse", [200, 400, 422], data={"session_id": O},
      files={"file": ("f.csv", b"Date,Narration,Withdrawal Amt.,Deposit Amt.\n01/05/2024,=cmd|' /C calc'!A0,10,\n", "text/csv")}),
    c("txn-import-unknown", "POST /api/transactions/import", "invalid", [404], json={"session_id": O, "import_id": "nope"}),
    c("txn-import-missing", "POST /api/transactions/import", "missing", [422], json={"session_id": O}),
    c("txn-clear", "DELETE /api/transactions", "valid", [200], params={"session_id": "qa-clear-txn"}),
    c("txn-clear-missing", "DELETE /api/transactions", "missing", [422]),
    # ---- progress / quiz ----------------------------------------------------------------------------------------
    c("progress-valid", "GET /api/progress", "valid", [200], params={"session_id": O}),
    c("progress-missing", "GET /api/progress", "missing", [422]),
    c("quiz-valid", "POST /api/quiz/answer", "valid", [200], json={"session_id": O, "concept_id": "sip", "is_correct": True}),
    c("quiz-missing", "POST /api/quiz/answer", "missing", [422], json={"session_id": O}),
    c("quiz-bad-bool", "POST /api/quiz/answer", "invalid", [422], json={"session_id": O, "concept_id": "sip", "is_correct": "maybe"}),
    c("quiz-unknown-concept", "POST /api/quiz/answer", "invalid", [400, 404, 422], json={"session_id": O, "concept_id": "no-such-concept", "is_correct": True}, known="QA-002"),
    c("quiz-huge-concept", "POST /api/quiz/answer", "oversized", [400, 404, 422], json={"session_id": O, "concept_id": "c" * 100000, "is_correct": True}, known="QA-002"),
    # ---- avatar -------------------------------------------------------------------------------------------------
    c("avatar-render", "GET /avatar/render", "valid", [200]),
    c("avatar-render-bad-token", "GET /avatar/render", "invalid", [200, 404], params={"audio_token": "nope"}),
    c("avatar-live", "GET /avatar/live", "valid", [200]),
    c("avatar-face", "GET /avatar/face.png", "valid", [200, 404]),
    c("avatar-glasses", "GET /avatar/glasses.png", "valid", [200, 404]),
    c("avatar-office", "GET /avatar/office.webp", "valid", [200, 404]),
    c("avatar-seated", "GET /avatar/seated-office.webp", "valid", [200, 404]),
    c("avatar-wide", "GET /avatar/office-wide-glasses.webp", "valid", [200, 404]),
    c("avatar-model", "GET /avatar/model.glb", "valid", [200, 404]),
    # ---- research -----------------------------------------------------------------------------------------------
    c("intel-valid", "GET /api/research/intelligence", "valid", [200, 404], net=True, params={"q": "Reliance Industries", "owner_id": O}),
    c("intel-empty", "GET /api/research/intelligence", "invalid", [404, 422], params={"q": ""}),
    c("intel-missing", "GET /api/research/intelligence", "missing", [422]),
    c("intel-huge-q", "GET /api/research/intelligence", "oversized", [200, 404, 414, 422], params={"q": "a" * 5000}),
    c("sentiment-valid", "POST /api/research/sentiment", "valid", [200], json={"texts": ["Profit rose sharply", "Fraud probe widens"]}),
    c("sentiment-empty", "POST /api/research/sentiment", "invalid", [200, 422], json={"texts": []}),
    c("sentiment-51", "POST /api/research/sentiment", "oversized", [422], json={"texts": ["a"] * 51}),
    c("sentiment-nonstring", "POST /api/research/sentiment", "invalid", [422], json={"texts": [1, 2]}),
    c("sentiment-missing", "POST /api/research/sentiment", "missing", [422], json={}),
    c("reports-list", "GET /api/research/reports", "valid", [200], params={"owner_id": O}),
    c("reports-list-missing", "GET /api/research/reports", "missing", [422]),
    c("report-get-unknown", "GET /api/research/reports/{report_id}", "invalid", [404], path="/api/research/reports/nope", params={"owner_id": O}),
    c("report-get-missing-owner", "GET /api/research/reports/{report_id}", "missing", [422], path="/api/research/reports/nope"),
    c("report-delete-unknown", "DELETE /api/research/reports/{report_id}", "invalid", [404], path="/api/research/reports/nope", params={"owner_id": O}),
    c("report-delete-missing-owner", "DELETE /api/research/reports/{report_id}", "missing", [422], path="/api/research/reports/nope"),
    c("report-html-unknown", "GET /api/research/reports/{report_id}/html", "invalid", [404], path="/api/research/reports/nope/html", params={"owner_id": O}),
    c("report-html-bad-kind", "GET /api/research/reports/{report_id}/html", "invalid", [400, 404], path="/api/research/reports/nope/html", params={"owner_id": O, "kind": "zzz"}),
    c("report-dl-bad-format", "GET /api/research/reports/{report_id}/download", "invalid", [400], path="/api/research/reports/nope/download", params={"owner_id": O, "format": "exe"}),
    c("report-dl-unknown", "GET /api/research/reports/{report_id}/download", "invalid", [404], path="/api/research/reports/nope/download", params={"owner_id": O}),
    c("report-regen-unknown", "POST /api/research/reports/{report_id}/regenerate", "invalid", [404], path="/api/research/reports/nope/regenerate", json={"owner_id": O}),
    c("report-regen-missing-owner", "POST /api/research/reports/{report_id}/regenerate", "missing", [422], path="/api/research/reports/nope/regenerate", json={}),
    # ---- forecast validation / scenario backtest ------------------------------------------------------------------
    c("val-start-bad-symbol", "POST /api/research/validation", "invalid", [422], json={"symbol": "bad symbol!"}),
    c("val-start-bad-symbol-slash", "POST /api/research/validation/", "invalid", [422], json={"symbol": "../etc"}),
    c("val-start-missing", "POST /api/research/validation", "missing", [422], json={}),
    c("val-latest", "GET /api/research/validation/latest", "valid", [200], params={"symbol": "QAFAKE.NS"}),
    c("val-latest-bad-symbol", "GET /api/research/validation/latest", "invalid", [422], params={"symbol": "x y"}),
    c("val-latest-missing", "GET /api/research/validation/latest", "missing", [422]),
    c("val-universe-summary", "GET /api/research/validation/universe/summary", "valid", [200]),
    c("val-universe-unknown", "GET /api/research/validation/universe/{symbol}", "invalid", [404], path="/api/research/validation/universe/QAFAKE.NS"),
    c("val-universe-bad", "GET /api/research/validation/universe/{symbol}", "invalid", [404, 422], path="/api/research/validation/universe/a%20b"),
    c("val-run-unknown", "GET /api/research/validation/{run_id}", "invalid", [404], path="/api/research/validation/nope"),
    c("val-cancel-unknown", "POST /api/research/validation/{run_id}/cancel", "invalid", [404], path="/api/research/validation/nope/cancel"),
    c("sb-start-bad-symbol", "POST /api/research/scenario-backtest", "invalid", [422], json={"symbol": "bad symbol!"}),
    c("sb-start-bad-symbol-slash", "POST /api/research/scenario-backtest/", "invalid", [422], json={"symbol": "x" * 30}),
    c("sb-universe-summary", "GET /api/research/scenario-backtest/universe/summary", "valid", [200]),
    c("sb-result-unknown", "GET /api/research/scenario-backtest/{symbol}", "invalid", [404], path="/api/research/scenario-backtest/QAFAKE"),
    c("sb-result-bad", "GET /api/research/scenario-backtest/{symbol}", "invalid", [422], path="/api/research/scenario-backtest/a%20b"),
    # ---- markets ------------------------------------------------------------------------------------------------
    c("mk-overview", "GET /api/markets/overview", "valid", [200, 503], net=True),
    c("mk-movers", "GET /api/markets/movers", "valid", [200, 503], net=True),
    c("mk-sectors", "GET /api/markets/sectors", "valid", [200, 503], net=True),
    c("mk-news", "GET /api/markets/news", "valid", [200, 503], net=True),
    c("mk-chart", "GET /api/markets/chart", "valid", [200, 503], net=True, params={"symbol": "RELIANCE.NS", "range": "1M"}),
    c("mk-chart-bad-range", "GET /api/markets/chart", "invalid", [422], params={"symbol": "RELIANCE.NS", "range": "99Y"}),
    c("mk-chart-bad-symbol", "GET /api/markets/chart", "invalid", [422], params={"symbol": "../../x"}),
    c("mk-chart-missing", "GET /api/markets/chart", "missing", [422]),
    c("mk-quote", "GET /api/markets/quote", "valid", [200, 503], net=True, params={"symbol": "RELIANCE.NS"}),
    c("mk-quote-bad-symbol", "GET /api/markets/quote", "invalid", [422], params={"symbol": "a b"}),
    c("mk-quote-missing", "GET /api/markets/quote", "missing", [422]),
    c("mk-search", "GET /api/markets/search", "valid", [200], params={"q": "tata"}),
    c("mk-search-long", "GET /api/markets/search", "oversized", [422], params={"q": "t" * 61}),
    c("mk-search-missing", "GET /api/markets/search", "missing", [422]),
    # ---- instruments --------------------------------------------------------------------------------------------
    c("ins-search", "GET /api/instruments/search", "valid", [200], params={"q": "reliance"}),
    c("ins-search-bad-limit", "GET /api/instruments/search", "invalid", [422], params={"q": "a", "limit": 0}),
    c("ins-search-bad-type", "GET /api/instruments/search", "invalid", [200, 422], params={"q": "a", "type": "zzz"}),
    c("ins-search-long", "GET /api/instruments/search", "oversized", [422], params={"q": "a" * 81}),
    c("ins-browse", "GET /api/instruments/browse", "valid", [200], params={"type": "stock", "page_size": 5, "prices": "false"}),
    c("ins-browse-bad-page", "GET /api/instruments/browse", "invalid", [422], params={"page": 0}),
    c("ins-browse-big-page", "GET /api/instruments/browse", "oversized", [422], params={"page_size": 201}),
    c("ins-browse-bad-type", "GET /api/instruments/browse", "invalid", [200, 422], params={"type": "zzz", "prices": "false"}),
    c("ins-ask-valid", "POST /api/instruments/ask", "valid", [200, 404, 503], net=True, json={"id": "stock:RELIANCE.NS", "question": "Is it expensive?", "session_id": S, "owner_id": O}),
    c("ins-ask-missing", "POST /api/instruments/ask", "missing", [422], json={"id": "stock:RELIANCE.NS"}),
    c("ins-ask-long", "POST /api/instruments/ask", "oversized", [422], json={"id": "stock:X", "question": "q" * 1501, "session_id": S}),
    c("ins-ask-bad-id", "POST /api/instruments/ask", "invalid", [404], json={"id": "garbage", "question": "hi", "session_id": S}),
    c("ins-quote", "GET /api/instruments/{instrument_id}/quote", "valid", [200, 503], net=True, path="/api/instruments/stock:RELIANCE.NS/quote"),
    c("ins-quote-bad-id", "GET /api/instruments/{instrument_id}/quote", "invalid", [404], path="/api/instruments/garbage/quote"),
    c("ins-chart", "GET /api/instruments/{instrument_id}/chart", "valid", [200, 503], net=True, path="/api/instruments/stock:RELIANCE.NS/chart", params={"range": "1y"}),
    c("ins-chart-bad-range", "GET /api/instruments/{instrument_id}/chart", "invalid", [422], path="/api/instruments/stock:RELIANCE.NS/chart", params={"range": "99y"}),
    c("ins-profile", "GET /api/instruments/{instrument_id}/profile", "valid", [200, 503], net=True, path="/api/instruments/stock:RELIANCE.NS/profile"),
    c("ins-profile-bad-id", "GET /api/instruments/{instrument_id}/profile", "invalid", [404], path="/api/instruments/nope:zz/profile"),
    c("ins-sip", "GET /api/instruments/{instrument_id}/sip", "valid", [200, 422, 503], net=True, path="/api/instruments/stock:RELIANCE.NS/sip", params={"monthly": 5000, "years": 5}),
    c("ins-sip-low", "GET /api/instruments/{instrument_id}/sip", "invalid", [422], path="/api/instruments/stock:RELIANCE.NS/sip", params={"monthly": 5}),
    c("ins-sip-years", "GET /api/instruments/{instrument_id}/sip", "invalid", [422], path="/api/instruments/stock:RELIANCE.NS/sip", params={"years": 31}),
    c("ins-sip-nan", "GET /api/instruments/{instrument_id}/sip", "invalid", [422], path="/api/instruments/stock:RELIANCE.NS/sip", params={"monthly": "nan"}),
    c("ins-sip-inf", "GET /api/instruments/{instrument_id}/sip", "abuse", [422], path="/api/instruments/stock:RELIANCE.NS/sip", params={"years": "inf"}),
    # ---- auth + health in private mode ----------------------------------------------------------------------------
    c("auth-session", "GET /api/auth/session", "valid", [200]),
    c("auth-register-private", "POST /api/auth/register", "invalid", [404], json={"email": "a@example.com", "password": "synthetic-password-1"}),
    c("auth-login-private", "POST /api/auth/login", "invalid", [404], json={"email": "a@example.com", "password": "synthetic-password-1"}),
    c("auth-google-private", "POST /api/auth/google", "invalid", [404, 503], json={"credential": "x" * 20}),
    c("auth-google-link-private", "POST /api/auth/google/link", "invalid", [401], json={"credential": "x" * 20}),
    c("auth-logout-private", "POST /api/auth/logout", "invalid", [404]),
    c("auth-logout-all-private", "POST /api/auth/logout-all", "invalid", [404]),
    c("health", "GET /api/health", "valid", [200]),
]


def expected_ops_from_openapi(spec: dict) -> set[str]:
    return {f"{m.upper()} {p}" for p, ms in spec["paths"].items() for m in ms}


def covered_ops() -> set[str]:
    return {k["op"] for k in CASES}
