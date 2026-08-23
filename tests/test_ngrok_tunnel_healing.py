"""api/routes/avatar.py's ngrok tunnel cache -- found broken via a live
Tavus CVI demo run: the tunnel URL is cached as a module-level global for
the API process's whole lifetime, but nothing ever re-checks that the
underlying ngrok.exe process is still alive. Killing ngrok.exe directly
(rather than via pyngrok's own disconnect, e.g. routine cleanup after a
manual test) left the cached URL pointing at a dead tunnel -- every later
Tavus conversation got wired to a callback URL nothing was listening on,
and the call dropped ("Call ended.") shortly after connecting, with no
error surfaced anywhere on our side."""
import api.routes.avatar as avatar


def _reset():
    avatar._NGROK_URL = None


def test_tunnel_is_alive_true_on_any_http_response(monkeypatch):
    class FakeResponse:
        status_code = 404

    monkeypatch.setattr(avatar.requests, "get", lambda *a, **k: FakeResponse())
    assert avatar._tunnel_is_alive("https://fake.ngrok.app") is True


def test_tunnel_is_alive_false_on_connection_error(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise avatar.requests.RequestException("connection refused")

    monkeypatch.setattr(avatar.requests, "get", raise_connection_error)
    assert avatar._tunnel_is_alive("https://fake.ngrok.app") is False


def test_get_ngrok_url_reuses_cached_url_when_alive(monkeypatch):
    _reset()
    avatar._NGROK_URL = "https://still-alive.ngrok.app"
    monkeypatch.setattr(avatar, "_tunnel_is_alive", lambda url: True)

    result = avatar._get_ngrok_url(8000)

    assert result == "https://still-alive.ngrok.app"
    _reset()


def test_get_ngrok_url_reconnects_when_cached_url_is_dead(monkeypatch):
    _reset()
    avatar._NGROK_URL = "https://dead.ngrok.app"
    monkeypatch.setattr(avatar, "_tunnel_is_alive", lambda url: False)

    class FakeTunnel:
        public_url = "https://fresh.ngrok.app"

    monkeypatch.setattr("pyngrok.ngrok.connect", lambda *a, **k: FakeTunnel())

    result = avatar._get_ngrok_url(8000)

    assert result == "https://fresh.ngrok.app"
    _reset()


def test_get_ngrok_url_gives_a_clear_error_for_an_orphaned_ngrok_process(monkeypatch):
    # Found live: a previous API process's ngrok.exe child got
    # force-killed during iterative dev-server restarts, orphaning it
    # still holding this account's static reserved domain. The next
    # tunnel attempt failed with pyngrok's raw "already online" HTTP
    # error, which surfaced to the browser as an opaque "Internal Server
    # Error" -- no indication what actually went wrong or how to fix it.
    from pyngrok.exception import PyngrokNgrokHTTPError

    _reset()

    def raise_already_online(*args, **kwargs):
        # pyngrok's own api_request() bakes the response body into the
        # `error` message string itself (see PyngrokNgrokHTTPError.__str__,
        # which only ever returns that first arg) -- matches the real
        # traceback this was found from.
        body = '{"details": {"err": "failed to start tunnel: the endpoint is already online"}}'
        raise PyngrokNgrokHTTPError(
            f"ngrok client exception, API returned 502: {body}",
            "http://localhost:4040/api/tunnels",
            502,
            "Bad Gateway",
            {},
            body,
        )

    monkeypatch.setattr("pyngrok.ngrok.connect", raise_already_online)

    try:
        avatar._get_ngrok_url(8000)
        assert False, "expected a RuntimeError"
    except RuntimeError as exc:
        assert "orphaned ngrok.exe" in str(exc)
    _reset()
