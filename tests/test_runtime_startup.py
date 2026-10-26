"""Version readiness must distinguish a live old API from current ARIA."""
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from api.main import app, _RUNTIME_REVISION
from api.runtime_version import backend_revision


def test_revision_tracks_runtime_source_and_ignores_frontend_and_test_output(tmp_path):
    (tmp_path / "api").mkdir()
    source = tmp_path / "api" / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    before = backend_revision(tmp_path)
    assert len(before) == 64 and backend_revision(tmp_path) == before
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "view.tsx").write_text("new frontend", encoding="utf-8")
    (tmp_path / "api" / "__pycache__").mkdir()
    (tmp_path / "api" / "__pycache__" / "ignored.py").write_text("generated", encoding="utf-8")
    assert backend_revision(tmp_path) == before
    source.write_text("value = 2\n", encoding="utf-8")
    assert backend_revision(tmp_path) != before
    changed = backend_revision(tmp_path)
    (tmp_path / "requirements.txt").write_text("example==1\n", encoding="utf-8")
    assert backend_revision(tmp_path) != changed


def test_revision_tracks_paths_and_config(tmp_path):
    (tmp_path / "core").mkdir()
    source = tmp_path / "core" / "old.py"
    source.write_text("value = 1\n", encoding="utf-8")
    before = backend_revision(tmp_path)
    source.rename(source.with_name("new.py"))
    assert backend_revision(tmp_path) != before
    before = backend_revision(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.py").write_text("setting = 2\n", encoding="utf-8")
    assert backend_revision(tmp_path) != before


def test_health_reports_loaded_revision_and_session_endpoint_exists(monkeypatch):
    monkeypatch.setattr("api.main.backend_revision", lambda: "changed-on-disk")
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok", "revision": _RUNTIME_REVISION}
    assert client.get("/api/auth/session").json()["mode"] == "private"


def test_launcher_readiness_and_workspace_ownership_without_starting_processes():
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell launcher is Windows-specific")
    script = Path(__file__).resolve().parents[1] / "scripts" / "aria_launcher.ps1"
    # Extract only pure readiness/ownership functions; never execute launcher body.
    command = r'''
$ErrorActionPreference = 'Stop'
$tree = [System.Management.Automation.Language.Parser]::ParseFile($env:ARIA_LAUNCHER_TEST_FILE, [ref]$null, [ref]$null)
$names = @('Test-CurrentApi','Test-ReadyApi','Test-OwnedApi')
$tree.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $names}, $true) | ForEach-Object { Invoke-Expression $_.Extent.Text }
$root = 'E:\ARIA'
$expectedRevision = 'current'
$responses = @{}
function Get-Json($url) { $responses[$url] }
$base = 'http://example.test'
$responses["$base/api/health"] = @{status='ok'}
if (Test-ReadyApi $base) { throw 'Old health-only API was accepted' }
$responses["$base/api/health"] = @{status='ok'; revision='current'}
if (Test-ReadyApi $base) { throw 'Missing session service was accepted' }
foreach ($mode in @('private','accounts')) {
  $responses["$base/api/auth/session"] = @{mode=$mode}
  if (-not (Test-ReadyApi $base)) { throw 'Current session service was rejected' }
}
$responses["$base/api/auth/session"] = @{mode='unexpected'}
if (Test-ReadyApi $base) { throw 'Invalid session response was accepted' }
$own = @{CommandLine='"E:\ARIA\.venv\Scripts\python.exe" -m uvicorn api.main:app --port 8000'}
$other = @{CommandLine='"E:\OTHER\.venv\Scripts\python.exe" -m uvicorn api.main:app --port 8000'}
if (-not (Test-OwnedApi $own)) { throw 'Own API not recognized' }
if (Test-OwnedApi $other) { throw 'Another workspace API could be restarted' }
Write-Output 'readiness and ownership checks passed'
'''
    import os
    result = subprocess.run([shell, "-NoProfile", "-Command", command],
                            env={**os.environ, "ARIA_LAUNCHER_TEST_FILE": str(script)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
