"""
scripts/build_concept_kb.py

Builds the FAISS index for Module 2's concept knowledge base from
data/raw/concepts_kb/concepts.json.

Usage:
    python -m scripts.build_concept_kb
"""
from __future__ import annotations

import json

from config.paths import CONCEPTS_KB_FILE
from shared import vector_store

NAMESPACE = "concepts"


def main() -> None:
    concepts = json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8"))

    texts = []
    metadata = []
    for c in concepts:
        blob = f"{c['canonical_name']}. {' '.join(c['aliases'])}. {c['seed_definition']}"
        texts.append(blob)
        metadata.append(c)

    vector_store.build_index(NAMESPACE, texts, metadata)
    print(f"Indexed {len(concepts)} concepts -> data/vector_store/{NAMESPACE}/")


if __name__ == "__main__":
    main()
