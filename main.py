from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from compiler_gate_routes import register_compiler_gate_routes

VERSION = "2026-08-04-live-menu-parity-test-folder-v2-compiler-gate"
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

app = FastAPI(title="PMD Live Menu / Compiler Parity Tester", version=VERSION)
register_compiler_gate_routes(app)


def _check_token(token: str | None) -> None:
    expected = os.getenv("TESTER_ACCESS_TOKEN", "").strip()
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="Invalid tester token")


def _app_root() -> Path:
    explicit = os.getenv("PMD_APP_ROOT", "").strip()
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    candidates.extend([
        HERE.parent.parent,
        HERE.parent,
        Path.cwd(),
        Path.cwd().parent,
    ])
    for candidate in candidates:
        if (candidate / "app" / "services" / "grok_cart_builder.py").exists():
            return candidate
    raise RuntimeError(
        "Could not find the full PizzaMan Dan app root. Set PMD_APP_ROOT to the folder that contains app/services/grok_cart_builder.py."
    )


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.getenv("TESTER_TIMEOUT_SECONDS", "900")),
        check=False,
    )
    parsed: Any = None
    stdout = proc.stdout.strip()
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = None
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_json": parsed,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-20000:],
        "command": command,
        "cwd": str(cwd),
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_parity_sync(store_number: int, order_type: str, skip_round_trips: bool) -> dict[str, Any]:
    root = _app_root()
    out = RESULTS / f"parity_store{store_number}_{order_type}_{_timestamp()}.json"
    command = [
        sys.executable,
        str(HERE / "live_menu_parity_test.py"),
        "--store-number", str(store_number),
        "--order-type", order_type,
        "--output", str(out),
    ]
    if skip_round_trips:
        command.append("--skip-round-trips")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    result = _run_command(command, cwd=root, env=env)
    result["report_file"] = str(out)
    return result


def _run_prompt_sync(js_path: str | None) -> dict[str, Any]:
    path = Path(js_path).expanduser().resolve() if js_path else (HERE / "input" / "current_lab.js")
    if not path.exists():
        return {"ok": False, "error": "JS file not found", "file": str(path)}
    out = RESULTS / f"prompt_leak_{_timestamp()}.json"
    command = [
        sys.executable,
        str(HERE / "prompt_leak_test.py"),
        "--js", str(path),
        "--output", str(out),
    ]
    result = _run_command(command, cwd=HERE, env=dict(os.environ))
    result["report_file"] = str(out)
    return result


@app.get("/health")
async def health() -> dict[str, Any]:
    root = None
    error = None
    try:
        root = str(_app_root())
    except Exception as exc:
        error = str(exc)
    return {
        "ok": error is None,
        "version": VERSION,
        "app_root": root,
        "app_root_error": error,
        "token_required": bool(os.getenv("TESTER_ACCESS_TOKEN", "").strip()),
        "tests": {
            "live_menu_parity": "read-only; no price and no submit",
            "prompt_leak": "static scan; live phone still required",
        },
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return """<!doctype html>
<html><head><meta charset='utf-8'><title>PMD Live Menu Parity Tester</title>
<style>
body{font-family:Arial,sans-serif;margin:24px;max-width:1200px}button{margin:5px;padding:10px 14px}.primary{font-weight:bold}input{padding:8px;width:260px}pre{background:#111;color:#eee;padding:16px;white-space:pre-wrap;min-height:180px}.muted{color:#666}.bad{color:#a00}.good{color:#070}
</style></head><body>
<h1>PMD Live Menu / Compiler Parity Tester</h1>
<p class='muted'>Tester only. The parity runs compile locally against the current cache/code. They do not price or submit. The prompt scan is static and does not replace a phone call.</p>
<p>Token: <input id='token' placeholder='optional TESTER_ACCESS_TOKEN'></p>
<p>
<button class='primary' onclick="runParity(1,'P',false)">Run Store 1 Pickup Full</button>
<button onclick="runParity(1,'D',false)">Run Store 1 Delivery Full</button>
<button class='primary' onclick="runParity(21,'P',false)">Run Store 21 Pickup Full</button>
<button onclick="runParity(21,'D',false)">Run Store 21 Delivery Full</button>
</p>
<p>
<button onclick="runParity(1,'P',true)">Store 1 Pickup Structural Only</button>
<button onclick="runParity(21,'P',true)">Store 21 Pickup Structural Only</button>
<button class='primary' onclick="runPrompt()">Run Stop-and-Wait Prompt Scan</button>
<button class='primary' onclick="runCompilerGate()">Run Full Compiler Test</button>
<button onclick="health()">Health</button>
</p>
<div id='status' class='muted'>Ready.</div><pre id='out'></pre>
<script>
function token(){return document.getElementById('token').value.trim()}
function show(x){document.getElementById('out').textContent=JSON.stringify(x,null,2)}
async function call(url){document.getElementById('status').textContent='Running...'; const r=await fetch(url); let x; try{x=await r.json()}catch(e){x={ok:false,http:r.status,text:await r.text()}} show(x); document.getElementById('status').textContent=x.ok?'PASS':'FAIL';}
function runParity(store,ot,skip){let u=`/run-parity?store_number=${store}&order_type=${ot}&skip_round_trips=${skip}&token=${encodeURIComponent(token())}`;call(u)}
function runPrompt(){call(`/run-prompt-scan?token=${encodeURIComponent(token())}`)}
function runCompilerGate(){window.location.href=`/compiler-gate?token=${encodeURIComponent(token())}`}
function health(){call('/health')}
</script></body></html>"""


@app.get("/run-parity")
async def run_parity(
    store_number: int = Query(..., ge=1),
    order_type: str = Query(..., pattern="^[PD]$"),
    skip_round_trips: bool = False,
    token: str | None = None,
) -> dict[str, Any]:
    _check_token(token)
    return await asyncio.to_thread(_run_parity_sync, store_number, order_type, skip_round_trips)


@app.get("/run-prompt-scan")
async def run_prompt_scan(token: str | None = None, js_path: str | None = None) -> dict[str, Any]:
    _check_token(token)
    return await asyncio.to_thread(_run_prompt_sync, js_path)
