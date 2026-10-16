"""Real account-cookie and revocation checks across isolated API restarts."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid

import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    port = 8768
    base = f"http://127.0.0.1:{port}"
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("Account audit port occupied; existing server was not touched")
    run = "account-restart-" + uuid.uuid4().hex
    env = {**os.environ, "ARIA_AUDIT_RUN": run, "ARIA_AUTH_MODE": "accounts", "ARIA_AUTH_ALLOW_SIGNUP": "1",
           "ARIA_APP_ORIGIN": base, "ARIA_AUDIT_PORT": str(port)}
    command = [sys.executable, "-m", "scripts.audit_server"]
    output = ROOT / ".audit"
    output.mkdir(exist_ok=True)
    processes = []
    client = requests.Session()
    client.headers["Origin"] = base
    def launch(log):
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(process)
        for _ in range(600):
            if process.poll() is not None:
                raise RuntimeError("Account API exited during startup")
            try:
                if client.get(base + "/api/health", timeout=.5).ok:
                    return process
            except requests.RequestException:
                pass
            time.sleep(.1)
        raise TimeoutError("Account API startup timed out")
    def stop(process):
        process.terminate()
        process.wait(timeout=20)
    try:
        with (output / "account-restart-server.log").open("w", encoding="utf-8") as log:
            process = launch(log)
            response = client.post(base + "/api/auth/register", json={"email": uuid.uuid4().hex + "@example.test", "password": secrets.token_urlsafe(24)}, timeout=15)
            assert response.ok
            user = response.json()["user"]
            assert client.post(base + "/api/profile", json={"session_id": user["id"], "monthly_income": 77000}, timeout=15).ok
            stop(process)
            process = launch(log)
            assert client.get(base + "/api/auth/session", timeout=15).json()["user"] == user
            assert client.get(base + "/api/profile", params={"session_id": user["id"]}, timeout=15).json()["profile"]["monthly_income"] == 77000
            # Retain an old cookie to prove DB revocation, not browser deletion.
            old_cookie = client.cookies.get("aria_auth")
            assert client.post(base + "/api/auth/logout-all", json={}, timeout=15).ok
            stop(process)
            process = launch(log)
            client.cookies.set("aria_auth", old_cookie)
            assert client.get(base + "/api/auth/session", timeout=15).json()["user"] is None
            assert client.get(base + "/api/profile", params={"session_id": user["id"]}, timeout=15).status_code == 401
            stop(process)
        result = {"status": "VERIFIED", "checks": ["account cookie survives actual API restart", "account profile persists", "revoked old cookie rejected after another restart"],
                  "database": str(Path(".audit") / "browser" / run / "aria.db")}
        (output / "account-restart-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        client.close()
        for process in processes:
            if process.poll() is None:
                stop(process)


if __name__ == "__main__":
    main()
