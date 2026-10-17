"""Offline administrator tool: protect an existing private owner with an account.

Run only against the operator's local SQLite database. This is deliberately not
an HTTP account-claim endpoint. It never merges owners or overwrites accounts.
"""
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import sqlite3

from sqlalchemy import text


def provision(owner_id: str, email: str, password: str, backup_dir: Path) -> dict:
    from api import auth
    from shared import user_store as store

    credentials = auth.Credentials(email=email, password=password)
    email = auth._email(credentials.email)
    if not owner_id or len(owner_id) > 128:
        raise ValueError("An existing private owner ID is required")
    if store._engine.url.get_backend_name() != "sqlite":
        raise ValueError("This tool supports local SQLite databases only")
    database = Path(store._engine.url.database).resolve()
    if not database.is_file():
        raise ValueError("The existing database was not found")
    # Online backup includes committed WAL contents without copying live DB files.
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ("before-account-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".db")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    encoded = auth.password_hash(credentials.password)
    with store._SessionLocal() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        if db.get(store.AccountRecord, owner_id) or db.query(store.AccountRecord).filter_by(email=email).first():
            raise ValueError("Account already exists; no account or private data was changed")
        tables = set(db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
        counts = {}
        for table, column in (("financial_profiles", "user_id"), ("transactions", "user_id"),
                              ("research_reports", "owner_id"), ("conversation_style", "owner_id"),
                              ("chat_conversations", "owner_id"), ("audio_artifacts", "owner_id")):
            if table in tables:
                counts[table] = db.execute(text(f'SELECT count(*) FROM "{table}" WHERE "{column}"=:owner'),
                                           {"owner": owner_id}).scalar_one()
        if not any(counts.values()):
            raise ValueError("No existing records belong to this owner; nothing was claimed")
        db.add(store.AccountRecord(id=owner_id, email=email, password_hash=encoded))
        db.commit()
    return {"email": email, "existing_records": counts, "backup": str(backup),
            "original_records_rewritten": False}


def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-file", type=Path, required=True, help="Local JSON containing owner_id")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-file", type=Path, help="Local private file; otherwise prompts without echo")
    parser.add_argument("--backup-dir", type=Path, default=Path(".audit/local-account-backups"))
    args = parser.parse_args()
    owner = json.loads(args.owner_file.read_text(encoding="utf-8"))["owner_id"]
    password = args.password_file.read_text(encoding="utf-8").strip() if args.password_file else getpass.getpass("Password: ")
    result = provision(owner, args.email, password, args.backup_dir)
    print(json.dumps(result, indent=2))  # Password and private owner capability are never logged.


if __name__ == "__main__":
    main()
