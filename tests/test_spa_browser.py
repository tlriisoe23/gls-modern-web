"""Runs the headless-browser XSS + accessibility suite (tests/spa_a11y_xss.mjs).

Starts uvicorn on a free port against a throwaway copy of the sample DB. Skipped when
Node.js or Playwright is not installed. Set AXE_CORE_PATH to an ``axe.min.js`` to add a
full axe-core WCAG 2.2 AA scan.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "spa_a11y_xss.mjs"


def _playwright_available() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    probe = "try{require('playwright')}catch(e){require('playwright-core')}"
    return subprocess.run([node, "-e", probe], cwd=ROOT, capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _playwright_available(), reason="node + playwright not available")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_spa_xss_and_accessibility(db_path: Path):
    port = _free_port()
    env = {**os.environ, "GLS9_DB_PATH": str(db_path), "PYTHONPATH": str(ROOT)}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("uvicorn did not start")
        res = subprocess.run(
            ["node", str(SCRIPT)], cwd=ROOT, env={**os.environ, "BASE_URL": base}, capture_output=True, text=True, timeout=300
        )
        assert res.returncode == 0, res.stdout[-6000:] + res.stderr[-3000:]
    finally:
        server.terminate()
        server.wait(timeout=10)
