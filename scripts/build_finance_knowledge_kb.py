"""
scripts/build_finance_knowledge_kb.py

Builds the FAISS index for the Stage 10 "finance_knowledge" grounding
namespace from data/raw/finance_knowledge/knowledge_base.json -- broader,
general finance-topic grounding for finance_prompt/tutor_prompt/
market_prompt's generic LLM fallback, distinct from
scripts/build_concept_kb.py's 50-concept Module 2 TAXAL tutor KB.

Usage:
    python -m scripts.build_finance_knowledge_kb
"""
from __future__ import annotations

import json

from config.paths import FINANCE_KNOWLEDGE_KB_FILE
from shared import vector_store

NAMESPACE = "finance_knowledge"


def main() -> None:
    entries = json.loads(FINANCE_KNOWLEDGE_KB_FILE.read_text(encoding="utf-8"))

    texts = []
    metadata = []
    for entry in entries:
        blob = f"{entry['title']}. {entry['content']}"
        texts.append(blob)
        metadata.append(entry)

    vector_store.build_index(NAMESPACE, texts, metadata)
    print(f"Indexed {len(entries)} finance-knowledge entries -> data/vector_store/{NAMESPACE}/")


if __name__ == "__main__":
    main()
