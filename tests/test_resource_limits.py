"""Exercise raw ASGI bodies, concurrency and admission without cloud calls."""
import asyncio
import pytest
from api.resource_limits import ResourceLimits


def run(coro):
    return asyncio.run(coro)


async def request(app, chunks=(b"hello",), headers=(), path="/api/chat", peer="local", receive_override=None):
    messages = [{"type": "http.request", "body": chunk, "more_body": i < len(chunks)-1} for i, chunk in enumerate(chunks)]
    output = []
    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}
    async def send(message):
        output.append(message)
    await app({"type": "http", "method": "POST", "path": path, "headers": headers, "client": (peer, 1)}, receive_override or receive, send)
    return output


async def echo(scope, receive, send):
    data = b""
    while True:
        message = await receive()
        data += message.get("body", b"")
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": data})


@pytest.mark.parametrize("headers,chunks", [([], (b"123", b"456")), ([(b"content-length", b"1")], (b"123456",)), ([(b"content-length", b"6")], (b"",))])
def test_actual_and_declared_body_limits_before_handler(headers, chunks):
    async def forbidden(*args):
        pytest.fail("oversized body reached handler/parser")
    app = ResourceLimits(forbidden, max_bytes=5, rate=0)
    result = run(request(app, chunks, headers))
    assert result[0]["status"] == 413 and app.active == 0


@pytest.mark.parametrize("headers", [[(b"content-length", b"-1")], [(b"content-length", b"bad")], [(b"content-length", b"1"), (b"content-length", b"2")]])
def test_invalid_content_length(headers):
    assert run(request(ResourceLimits(echo, rate=0), headers=headers))[0]["status"] == 400


def test_chunked_body_replayed_exactly_at_limit():
    output = run(request(ResourceLimits(echo, max_bytes=6, rate=0), (b"123", b"456")))
    assert output[0]["status"] == 200 and output[-1]["body"] == b"123456"


def test_slow_upload_timeout_releases_slot():
    async def slow():
        await asyncio.sleep(10)
    app = ResourceLimits(echo, rate=0, body_timeout=.01)
    assert run(request(app, receive_override=slow))[0]["status"] == 408
    assert app.active == 0


def test_concurrent_admission_rejects_then_recovers():
    async def exercise():
        entered, finish = asyncio.Event(), asyncio.Event()
        async def blocked(*args):
            entered.set()
            await finish.wait()
            await echo(*args)
        app = ResourceLimits(blocked, max_active=1, rate=0)
        first = asyncio.create_task(request(app))
        await entered.wait()
        assert (await request(app))[0]["status"] == 503
        finish.set()
        assert (await first)[0]["status"] == 200
        assert (await request(app))[0]["status"] == 200 and app.active == 0
    run(exercise())


def test_rate_limits_real_peer_and_resets(monkeypatch):
    now = [100.]
    monkeypatch.setattr("api.resource_limits.time.monotonic", lambda: now[0])
    app = ResourceLimits(echo, rate=1)
    assert run(request(app))[0]["status"] == 200
    assert run(request(app, headers=[(b"x-forwarded-for", b"new-client")]))[0]["status"] == 429
    assert run(request(app, peer="different"))[0]["status"] == 200
    now[0] += 61
    assert run(request(app))[0]["status"] == 200


def test_tavus_callback_has_same_body_boundary():
    assert run(request(ResourceLimits(echo, max_bytes=2, rate=0), path="/v1/session/chat/completions"))[0]["status"] == 413


def test_spooled_large_body_is_replayed_without_loss():
    content = b"a" * (2 * 1024 * 1024)
    result = run(request(ResourceLimits(echo, rate=0), chunks=(content,)))
    assert result[-1]["body"] == content


def test_handler_failure_releases_admission_slot():
    async def failing(*args):
        raise RuntimeError("handler failure")
    app = ResourceLimits(failing, rate=0)
    with pytest.raises(RuntimeError, match="handler failure"):
        run(request(app))
    assert app.active == 0
