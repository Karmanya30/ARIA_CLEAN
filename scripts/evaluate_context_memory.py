"""Repeatable synthetic retrieval benchmark. Never reads user conversations."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared import conversation_memory as memory, user_store
from core import session


def evaluate():
    with tempfile.TemporaryDirectory(prefix="aria-memory-eval-") as directory:
        engine = create_engine("sqlite:///" + (Path(directory) / "eval.db").as_posix())
        user_store.Base.metadata.create_all(engine)
        previous = user_store._SessionLocal
        old_cache = session._SESSIONS.copy()
        user_store._SessionLocal = sessionmaker(bind=engine)
        token = user_store.current_owner.set("synthetic-evaluation")
        session._SESSIONS.clear()
        try:
            facts = [
                ("Acme WACC assumption is 12.5%", "Acme WACC"),
                ("Copperfin exit multiple is 17.3", "Copperfin exit multiple"),
                ("Orion audit date was 2025-03-17", "Orion audit date"),
                ("Nimbus debt cap is 42 crore", "Nimbus debt cap"),
                ("Cedar revenue target is 900 crore", "Cedar revenue target"),
                ("Falcon margin agreed at 18%", "Falcon margin"),
                ("Harbor risk is customer concentration", "Harbor customer concentration"),
                ("Willow investment thesis depends on exports", "Willow investment thesis"),
            ]
            if os.getenv("ARIA_MEMORY_SEMANTIC", "1") == "1":
                facts.extend([
                    ("Liquidity buffer should cover six months", "cash reserve for emergencies"),
                    ("Retirement is twenty years away", "investment horizon until leaving work"),
                ])
            expected = []
            for i, (fact, query) in enumerate(facts):
                session.execute_turn(f"episode-{i}", fact, lambda: {"response": "Assumption recorded, not verified live data."})
                expected.append(session.get_session(f"episode-{i}")["history"][-1]["message_id"])
            for i in range(30):
                session.execute_turn("distractors", f"Unrelated lunch planning note {i}", lambda: {"response": "OK"})
            scores = []
            for (_, query), target in zip(facts, expected):
                records, _ = memory.retrieve("evaluation-query", query, limit=5)
                ranked = sorted(records, key=lambda r: r["retrieval_score"], reverse=True)[:5]
                ids = [r["id"] for r in ranked]
                rank = ids.index(target) + 1 if target in ids else None
                scores.append({"query": query, "rank": rank})
            return {"fixture": f"{len(facts)} source turns + 30 distractors, cross-conversation, synthetic only",
                    "semantic": os.getenv("ARIA_MEMORY_SEMANTIC", "1"),
                    "queries": len(scores),
                    "recall_at_5": sum(s["rank"] is not None for s in scores) / len(scores),
                    "mrr_at_5": sum(1 / s["rank"] if s["rank"] else 0 for s in scores) / len(scores),
                    "results": scores,
                    "baseline": "No executable pre-change retrieval benchmark was recorded; no improvement claim."}
        finally:
            user_store.current_owner.reset(token)
            user_store._SessionLocal = previous
            session._SESSIONS.clear()
            session._SESSIONS.update(old_cache)
            engine.dispose()

if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
