import numpy as np
import pytest

from avatar_engine.replicas import DEFAULT_ID, ReplicaError


def test_default_replica_created_once(engine):
    assert engine.store.get(DEFAULT_ID)["name"] == "ARIA (default)"
    assert (engine.store.path(DEFAULT_ID) / "prep.pkl").exists()
    assert (engine.store.path(DEFAULT_ID) / "preview.jpg").stat().st_size > 1000
    assert [r["id"] for r in engine.store.list()] == [DEFAULT_ID]


def test_create_list_delete(engine, face_png):
    m = engine.store.create("me.png", face_png.read_bytes(), name="Me")
    assert m["kind"] == "photo" and m["name"] == "Me"
    assert [r["id"] for r in engine.store.list()][0] == DEFAULT_ID and len(engine.store.list()) == 2
    d = engine.store.path(m["id"])
    assert (d / "prep.pkl").exists() and (d / "source.png").exists()
    engine.store.delete(m["id"])
    assert not d.exists()
    with pytest.raises(ReplicaError) as e:
        engine.store.get(m["id"])
    assert e.value.status == 404


def test_rejects_bad_input_and_path_traversal(engine):
    with pytest.raises(ReplicaError):
        engine.store.create("x.exe", b"abc")
    with pytest.raises(ReplicaError):
        engine.store.create("x.png", b"")
    for bad in ("../x", "a/b", "", "a" * 50):
        with pytest.raises(ReplicaError):
            engine.store.get(bad)
    with pytest.raises(ReplicaError):
        engine.store.delete(DEFAULT_ID)


def test_failed_prepare_leaves_nothing_behind(engine):
    n = len(list(engine.store.root.iterdir()))
    with pytest.raises(ReplicaError):          # not an image: the fake backend cannot read it
        engine.store.create("x.png", b"not an image")
    assert len(list(engine.store.root.iterdir())) == n


def test_http_endpoints(client, face_png):
    assert client.get("/health").json()["replica_default"] == DEFAULT_ID
    r = client.post("/replicas", files={"file": ("a.png", face_png.read_bytes(), "image/png")}, data={"name": "A"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert client.get(f"/replicas/{rid}/preview").headers["content-type"] == "image/jpeg"
    assert any(x["id"] == rid for x in client.get("/replicas").json())
    assert client.delete(f"/replicas/{rid}").status_code == 200
    assert client.get(f"/replicas/{rid}/preview").status_code == 404
    assert client.delete(f"/replicas/{DEFAULT_ID}").status_code == 400
    assert client.post("/replicas", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400
