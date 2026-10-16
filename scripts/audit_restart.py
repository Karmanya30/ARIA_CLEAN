"""Verify isolated API data survives an actual backend process restart."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    run = "restart-" + uuid.uuid4().hex
    env = {**os.environ, "ARIA_AUDIT_RUN": run, "ARIA_AUTH_MODE": "private"}
    owner, session = uuid.uuid4().hex, uuid.uuid4().hex
    base = "http://127.0.0.1:8766"
    output = ROOT / ".audit"
    output.mkdir(exist_ok=True)
    processes = []
    command = [sys.executable, "-c", "import scripts.audit_server as s; import uvicorn; uvicorn.run(s.app, host='127.0.0.1', port=8766, log_level='warning')"]
    def launch(log):
        # Do not attach to a pre-existing server: it could have a real database.
        p = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(p)
        for _ in range(600):
            if p.poll() is not None:
                raise RuntimeError("Isolated API exited during startup")
            try:
                if requests.get(base + "/api/health", timeout=.5).ok:
                    return p
            except requests.RequestException:
                pass
            time.sleep(.1)
        raise TimeoutError("Isolated API startup timed out")
    def stop(p):
        p.terminate()
        p.wait(timeout=20)
    import socket
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 8766)) == 0:
            raise RuntimeError("Audit port is already occupied; no existing server was touched")
    try:
        with (output / "restart-server.log").open("w", encoding="utf-8") as log:
            p = launch(log)
            payload = {"session_id": owner, "age": 34, "monthly_income": 99000, "expenses": {"food": 3000}}
            assert requests.post(base + "/api/profile", json=payload, timeout=15).ok
            assert requests.post(base + "/api/transactions", json={"session_id": owner, "date": "2026-10-01", "category": "food", "amount": 123}, timeout=15).ok
            message = {"session_id": session, "owner_id": owner, "request_id": "restart-request", "query": "ok"}
            assert requests.post(base + "/api/chat", json=message, timeout=15).ok
            statement = "Date,Narration,Debit,Credit\n" + "".join(
                f"01/{m:02d}/2026,SALARY ACME,,50000\n02/{m:02d}/2026,SWIGGY,250,\n" for m in (7, 8, 9))
            parsed = requests.post(base + "/api/transactions/parse", data={"session_id": owner},
                files={"file": ("synthetic-restart.csv", statement.encode(), "text/csv")}, timeout=15)
            assert parsed.ok
            import_request = {"session_id": owner, "import_id": parsed.json()["import_id"], "apply_to_profile": True}
            db = output / "browser" / run / "aria.db"
            audio_bytes = b"RIFF" + b"synthetic-restart-audio" * 10
            audio_source = db.parent / "synthetic.wav"
            audio_source.write_bytes(audio_bytes)
            registered = subprocess.run([sys.executable, "-c",
                "import sys; from api.audio_store import register; print(register(sys.argv[1]))", str(audio_source)],
                cwd=ROOT, env={**env, "DB_URL": "sqlite:///" + db.as_posix()}, capture_output=True, text=True, timeout=30)
            assert registered.returncode == 0
            audio_token = registered.stdout.strip()
            audio_source.unlink()
            assert requests.get(base + "/api/audio/" + audio_token, timeout=15).content == audio_bytes
            with sqlite3.connect(db) as connection:
                assert connection.execute("select monthly_income from financial_profiles where user_id=?", (owner,)).fetchone()[0] == 99000
            stop(p)
            p = launch(log)
            assert requests.get(base + "/api/audio/" + audio_token, timeout=15).content == audio_bytes
            profile = requests.get(base + "/api/profile", params={"session_id": owner}, timeout=15).json()
            assert profile["profile"]["monthly_income"] == 99000 and profile["profile"]["age"] == 34
            assert len(requests.get(base + "/api/transactions", params={"session_id": owner}, timeout=15).json()) == 1
            imported = requests.post(base + "/api/transactions/import", json=import_request, timeout=15)
            assert imported.ok and imported.json() == {"imported": 6, "duplicates": 0, "profile_updated": True}
            assert requests.post(base + "/api/profile", json={"session_id": owner, "monthly_income": 99001}, timeout=15).ok
            assert requests.post(base + "/api/chat", json=message, timeout=15).ok
            params = {"session_id": session, "owner_id": owner}
            assert len(requests.get(base + "/api/chat/history", params=params, timeout=15).json()["history"]) == 1
            assert requests.get(base + "/api/chat/history", params={**params, "owner_id": "stranger"}, timeout=15).status_code == 403
            stop(p)
            p = launch(log)
            assert requests.get(base + "/api/audio/" + audio_token, timeout=15).content == audio_bytes
            replay = requests.post(base + "/api/transactions/import", json=import_request, timeout=15)
            assert replay.ok and replay.json() == imported.json()
            profile = requests.get(base + "/api/profile", params={"session_id": owner}, timeout=15).json()["profile"]
            assert profile["monthly_income"] == 99001 and profile["expenses"] == {"food": 250}
            with sqlite3.connect(db) as connection:
                assert connection.execute("select count(*) from transactions where user_id=?", (owner,)).fetchone()[0] == 7
            stop(p)
        result = {"status": "VERIFIED", "checks": ["profile SQLite values", "profile after backend restart", "transactions after backend restart", "chat retry replay after restart", "history count remains one", "wrong owner rejected after restart", "pending statement preview survives restart", "import receipt survives another restart", "retry does not duplicate transactions or overwrite later profile edit", "completed audio served across three API lifetimes after source removal"], "database": str(db.relative_to(ROOT))}
        (output / "restart-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        for p in processes:
            if p.poll() is None:
                stop(p)


if __name__ == "__main__":
    main()
