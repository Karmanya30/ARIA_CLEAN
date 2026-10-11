import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.equity_research.forecast import store
from shared import user_store as us


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    """Point user_store at a throwaway SQLite file and the parquet root at tmp_path."""
    path = tmp_path / "t.db"
    eng = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})
    us.Base.metadata.create_all(eng)
    monkeypatch.setattr(us, "_engine", eng)
    monkeypatch.setattr(us, "_SessionLocal", sessionmaker(bind=eng))
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return path
