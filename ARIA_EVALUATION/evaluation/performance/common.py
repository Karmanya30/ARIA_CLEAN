"""Shared safe-environment setup for the performance scripts: scratch DB, private auth, no provider keys, no network."""
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = Path(__file__).resolve().parent / "results"


def safe_env(scratch: str, **extra) -> dict:
    env = dict(os.environ)
    env.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", ARIA_AUTH_MODE="private", ARIA_WARMUP="0", ARIA_SCRATCH=scratch,
               DB_URL=f"sqlite:///{scratch}/perf.db".replace("\\", "/"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               GROQ_API_KEY="", GEMINI_API_KEY="", HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
               NO_PROXY="127.0.0.1,localhost", ARIA_INTENT_RESOLVER="0")
    env.update({k: str(v) for k, v in extra.items()})
    return env


def lower_priority():
    """BelowNormal priority for this process (Windows, ctypes; psutil is not installed in the project venv)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass


def rss_mb() -> int:
    """Working set (MB) and peak working set of this process via GetProcessMemoryInfo."""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    k = ctypes.windll.kernel32; k.GetCurrentProcess.restype = wintypes.HANDLE
    f = ctypes.windll.psapi.GetProcessMemoryInfo; f.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]; f(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.WorkingSetSize / 1e6)


def peak_rss_mb() -> int:
    import ctypes
    from ctypes import wintypes
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", ctypes.c_size_t), ("f", ctypes.c_size_t)]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    k = ctypes.windll.kernel32; k.GetCurrentProcess.restype = wintypes.HANDLE
    f = ctypes.windll.psapi.GetProcessMemoryInfo; f.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]; f(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.PeakWorkingSetSize / 1e6)


def avail_mb() -> int:
    import ctypes
    class MS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong),
                    ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ev", ctypes.c_ulonglong)]
    m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ap / 1e6)


def block_network():
    """Make accidental outbound network use fail fast (loopback stays allowed: asyncio and the test server need it). curl_cffi is made
    unimportable (it bypasses Python sockets) and yfinance's Ticker/download raise."""
    import socket
    real_connect, real_cc, real_gai = socket.socket.connect, socket.create_connection, socket.getaddrinfo
    local = ("127.0.0.1", "localhost", "::1", "0.0.0.0", "")

    def connect(self, addr):
        if isinstance(addr, tuple) and str(addr[0]) in local:
            return real_connect(self, addr)
        raise OSError("network blocked by performance harness")

    def cc(addr, *a, **k):
        if str(addr[0]) in local:
            return real_cc(addr, *a, **k)
        raise OSError("network blocked by performance harness")

    def gai(host, *a, **k):
        if host is None or str(host) in local:
            return real_gai(host, *a, **k)
        raise OSError("network blocked by performance harness")
    socket.socket.connect, socket.create_connection, socket.getaddrinfo = connect, cc, gai
    sys.modules["curl_cffi"] = None
    try:
        import yfinance as yf
        def boom(*a, **k):
            raise OSError("yfinance blocked by performance harness")
        for n in ("Ticker", "download", "Tickers", "Search"):
            if hasattr(yf, n):
                setattr(yf, n, boom)
    except Exception:
        pass


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)
