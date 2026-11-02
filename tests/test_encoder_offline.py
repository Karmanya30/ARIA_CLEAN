"""REL-01: the encoder is loaded from disk first, so an unreachable Hugging Face hub cannot stall the first request."""
from shared import vector_store


def test_the_local_copy_is_tried_first_and_the_network_only_when_it_is_missing(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, name, device=None, local_files_only=False):
            calls.append(local_files_only)
            if local_files_only:
                raise OSError("not on disk")

    monkeypatch.setattr(vector_store, "SentenceTransformer", Fake)
    monkeypatch.setattr(vector_store, "_encoder", None)
    vector_store._get_encoder()
    assert calls == [True, False]  # local first; the download is the fallback
    monkeypatch.setattr(vector_store, "_encoder", None)
    calls.clear()

    class OnDisk(Fake):
        def __init__(self, name, device=None, local_files_only=False):
            calls.append(local_files_only)

    monkeypatch.setattr(vector_store, "SentenceTransformer", OnDisk)
    vector_store._get_encoder()
    assert calls == [True]  # found locally: no network call at all
