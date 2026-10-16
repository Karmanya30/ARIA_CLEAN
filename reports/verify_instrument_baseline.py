"""Run instrument tests with pre-memory backend code loaded in memory only.
Leaves the user's working instrument modules and tests untouched.
"""
import importlib.abc
import importlib.util
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
paths = ["ai/llm/groq_client.py", "core/session.py", "core/orchestrator.py",
         "api/routes/chat.py", "api/routes/live.py", "api/routes/avatar.py",
         "modules/equity_research/intelligence/agents.py"]
sources = {}
for path in paths:
    result = subprocess.run(["git", "show", "HEAD:" + path], cwd=root, capture_output=True, check=True)
    sources[path[:-3].replace("/", ".")] = (path, result.stdout.decode("utf-8"))

class Baseline(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in sources:
            return importlib.util.spec_from_loader(fullname, self)
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        path, source = sources[module.__name__]
        module.__file__ = str(root / path)
        exec(compile(source, module.__file__, "exec"), module.__dict__)

sys.meta_path.insert(0, Baseline())
import pytest
raise SystemExit(pytest.main(["tests/market/test_instruments.py", "-m", "not network", "-q", "--disable-warnings", "--tb=short"]))
