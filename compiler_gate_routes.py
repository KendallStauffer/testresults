"""PMD compiler release-gate add-on for the existing Render tester.

This module registers only /compiler-gate routes. It does not replace the
existing tester app, its scenarios, buttons, runner, or root page.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

VERSION = "pmd-compiler-gate-existing-tester-addon-2026-08-04-v1"
HERE = Path(__file__).resolve().parent
RUNS = HERE / "compiler_gate_runs"
RUNS.mkdir(exist_ok=True)

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
ALLOWED_FILES = {
    "compiler_gate_report.json",
    "compiler_gate_failures.json",
    "compiler_gate_cases.csv",
    "compiler_gate_report.html",
    "compiler_gate_manifest.json",
    "catalog_evidence.json",
    "coupon_evidence.json",
    "audit_private_mapping_evidence.json",
    "stdout.txt",
    "stderr.txt",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_token(token: str | None) -> None:
    expected = os.getenv("TESTER_ACCESS_TOKEN", "").strip()
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="Invalid tester token")


def _backend_key_present() -> bool:
    return bool(
        os.getenv("PMD_BACKEND_API_KEY", "").strip()
        or os.getenv("PIZZA_BACKEND_API_KEY", "").strip()
    )


def _safe_job(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        row = JOBS.get(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown compiler-gate job")
        return dict(row)


def _update_job(job_id: str, **values: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values)


def _read_summary(run_dir: Path) -> dict[str, Any] | None:
    report_path = run_dir / "compiler_gate_report.json"
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        summary = report.get("summary")
        return summary if isinstance(summary, dict) else None
    except Exception:
        return None


def _read_stdout(
    proc: subprocess.Popen[str],
    stdout_path: Path,
    job_id: str,
    started: float,
) -> None:
    assert proc.stdout is not None
    with stdout_path.open("w", encoding="utf-8") as output:
        for line in proc.stdout:
            output.write(line)
            output.flush()
            text = line.strip()
            match = re.match(r"\[(\d+)/(\d+)\] completed; failures=(\d+)", text)
            if match:
                completed, total, failed = map(int, match.groups())
                _update_job(
                    job_id,
                    checks_completed=completed,
                    checks_total=total,
                    failures=failed,
                    detail=f"Running exhaustive compile cases: {completed}/{total}",
                    last_activity_at=_now(),
                    elapsed_seconds=int(time.monotonic() - started),
                )


def _worker(job_id: str, store_number: int, order_type: str) -> None:
    started = time.monotonic()
    timeout_seconds = int(os.getenv("TESTER_TIMEOUT_SECONDS", "3600"))
    run_dir = RUNS / (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{job_id[:8]}_store{store_number}_{order_type}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    command = [
        sys.executable,
        "-u",
        str(HERE / "pmd_compiler_release_gate.py"),
        "--store-number",
        str(store_number),
        "--order-type",
        order_type,
        "--output-dir",
        str(run_dir),
    ]
    _update_job(
        job_id,
        status="running",
        started_at=_now(),
        output_dir=str(run_dir),
        detail="Discovering the current catalog, coupon plans, and private compiler mappings",
        last_activity_at=_now(),
    )

    try:
        with stderr_path.open("w", encoding="utf-8") as stderr:
            proc = subprocess.Popen(
                command,
                cwd=str(HERE),
                env=dict(os.environ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=stderr,
                bufsize=1,
            )
            reader = threading.Thread(
                target=_read_stdout,
                args=(proc, stdout_path, job_id, started),
                daemon=True,
            )
            reader.start()

            timed_out = False
            while proc.poll() is None:
                elapsed = int(time.monotonic() - started)
                _update_job(job_id, elapsed_seconds=elapsed)
                if elapsed >= timeout_seconds:
                    timed_out = True
                    proc.kill()
                    break
                time.sleep(1)

            returncode = proc.wait()
            reader.join(timeout=10)

        if timed_out:
            _update_job(
                job_id,
                status="timed_out",
                result_status="ERROR",
                returncode=returncode,
                detail=f"Exceeded TESTER_TIMEOUT_SECONDS={timeout_seconds}",
                elapsed_seconds=int(time.monotonic() - started),
                finished_at=_now(),
            )
            return

        summary = _read_summary(run_dir)
        status_by_code = {0: "PASS", 1: "FAIL", 2: "INCOMPLETE", 3: "ERROR"}
        result_status = (
            str(summary.get("status"))
            if summary and summary.get("status")
            else status_by_code.get(returncode, "ERROR")
        )
        report_urls = {
            filename: f"/compiler-gate/job/{job_id}/file/{filename}"
            for filename in sorted(ALLOWED_FILES)
            if (run_dir / filename).exists()
        }
        _update_job(
            job_id,
            status="finished",
            result_status=result_status,
            returncode=returncode,
            summary=summary,
            detail="Compiler release gate completed. Open the HTML report or failures JSON.",
            elapsed_seconds=int(time.monotonic() - started),
            finished_at=_now(),
            report_urls=report_urls,
        )
    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            result_status="ERROR",
            detail=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=int(time.monotonic() - started),
            finished_at=_now(),
        )


def _page(token: str | None) -> str:
    token_value = html.escape(token or "", quote=True)
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PMD Compiler Release Gate</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px;max-width:1200px;background:#fafafa;color:#222}}
.panel{{border:1px solid #ccc;background:white;padding:14px;margin:12px 0;border-radius:10px}}
button,input,select{{padding:9px;margin:4px;border:1px solid #bbb;border-radius:8px}}
button{{cursor:pointer}}button.primary{{font-weight:700}}
pre{{background:#111;color:#eee;padding:14px;white-space:pre-wrap;border-radius:10px;overflow:auto;min-height:160px}}
a{{margin-right:12px}}.muted{{color:#666}}
</style></head><body>
<h1>PMD Compiler 100% Today Release Gate</h1>
<div class='panel'><b>Compiler-only safety:</b> current catalog and coupon plans are sent to <code>compile-order-list</code>. This page never calls price, submit, payment, card, customer/address writes, direct Redis, or direct oneSystem.<br><b>Strict result:</b> PASS, FAIL, or INCOMPLETE. Missing private mapping proof can never become PASS.</div>
<p><button onclick="location.href='/?token='+encodeURIComponent(document.getElementById('token').value.trim())">Back to Tester</button></p>
<div class='panel'>
Tester token <input id='token' type='password' value='{token_value}' placeholder='optional TESTER_ACCESS_TOKEN'>
Store <input id='store' type='number' value='1' min='1'>
Order type <select id='ot'><option value='P'>Pickup</option><option value='D'>Delivery</option></select>
<button class='primary' onclick='startGate()'>Run Full Compiler Test</button>
<button onclick='health()'>Compiler Gate Health</button>
</div>
<div class='panel'>
<div>Status: <b id='status'>Ready</b></div>
<div>Progress: <span id='progress'>0/0</span></div>
<div>Failures: <span id='failures'>0</span></div>
<div>Elapsed: <span id='elapsed'>0</span> seconds</div>
<div>Detail: <span id='detail'>-</span></div>
<div>Last activity: <span id='activity'>-</span></div>
<div id='links'></div>
</div>
<pre id='out'></pre>
<script>
let timer=null;
function token(){{return document.getElementById('token').value.trim()}}
function show(x){{document.getElementById('out').textContent=JSON.stringify(x,null,2)}}
async function readJson(r){{try{{return await r.json()}}catch(e){{return {{ok:false,http:r.status,text:await r.text()}}}}}}
function setText(id,v){{document.getElementById(id).textContent=(v===undefined||v===null||v==='')?'-':v}}
async function health(){{const r=await fetch('/compiler-gate/health');const x=await readJson(r);show(x);setText('status',x.ok?'READY':'CONFIGURATION ERROR')}}
async function startGate(){{
  if(timer){{clearInterval(timer);timer=null}}
  document.getElementById('links').innerHTML='';
  setText('status','Starting');
  const s=document.getElementById('store').value;
  const ot=document.getElementById('ot').value;
  const r=await fetch(`/compiler-gate/run?store_number=${{s}}&order_type=${{ot}}&token=${{encodeURIComponent(token())}}`);
  const x=await readJson(r);show(x);
  if(!r.ok||!x.job_id){{setText('status','ERROR');return}}
  await poll(x.job_id);timer=setInterval(()=>poll(x.job_id),1000);
}}
async function poll(id){{
  const r=await fetch(`/compiler-gate/job/${{id}}?token=${{encodeURIComponent(token())}}`);
  const x=await readJson(r);show(x);
  setText('status',x.result_status||x.status);
  setText('progress',`${{x.checks_completed||0}}/${{x.checks_total||0}}`);
  setText('failures',x.failures||0);setText('elapsed',x.elapsed_seconds||0);
  setText('detail',x.detail);setText('activity',x.last_activity_at);
  if(x.report_urls){{
    const q=`?token=${{encodeURIComponent(token())}}`;
    document.getElementById('links').innerHTML=Object.entries(x.report_urls).map(([n,u])=>`<a target='_blank' href='${{u}}${{q}}'>${{n}}</a>`).join(' ');
  }}
  if(['finished','failed','timed_out'].includes(x.status)&&timer){{clearInterval(timer);timer=null}}
}}
</script></body></html>"""


def register_compiler_gate_routes(app: FastAPI) -> None:
    """Register the add-on exactly once on an existing FastAPI app."""
    if getattr(app.state, "pmd_compiler_gate_registered", False):
        return
    app.state.pmd_compiler_gate_registered = True

    @app.get("/compiler-gate", response_class=HTMLResponse)
    def compiler_gate_page(token: str | None = None) -> str:
        _check_token(token)
        return _page(token)

    @app.get("/compiler-gate/health")
    def compiler_gate_health() -> dict[str, Any]:
        return {
            "ok": _backend_key_present(),
            "version": VERSION,
            "backend_url": os.getenv(
                "PIZZA_BACKEND_URL",
                "https://pizza-ai-backend.onrender.com",
            ).strip().rstrip("/"),
            "backend_key_present": _backend_key_present(),
            "backend_header": (
                os.getenv("PIZZA_BACKEND_API_KEY_HEADER", "x-pmd-backend-key").strip()
                or "x-pmd-backend-key"
            ),
            "timeout_seconds": int(os.getenv("TESTER_TIMEOUT_SECONDS", "3600")),
            "safety": "compile-only; no price, submit, payment, card, or writes",
        }

    @app.get("/compiler-gate/run")
    def compiler_gate_run(
        store_number: int = Query(1, ge=1),
        order_type: str = Query("P", pattern="^[PD]$"),
        token: str | None = None,
    ) -> dict[str, Any]:
        _check_token(token)
        if not _backend_key_present():
            raise HTTPException(
                status_code=500,
                detail="PMD_BACKEND_API_KEY or PIZZA_BACKEND_API_KEY is not configured",
            )
        gate_script = HERE / "pmd_compiler_release_gate.py"
        if not gate_script.exists():
            raise HTTPException(status_code=500, detail=f"Missing {gate_script.name} beside main.py")
        job_id = uuid.uuid4().hex
        row = {
            "job_id": job_id,
            "status": "queued",
            "result_status": None,
            "store_number": store_number,
            "order_type": order_type,
            "checks_completed": 0,
            "checks_total": 0,
            "failures": 0,
            "elapsed_seconds": 0,
            "created_at": _now(),
            "detail": "Queued",
        }
        with JOBS_LOCK:
            JOBS[job_id] = row
        threading.Thread(
            target=_worker,
            args=(job_id, store_number, order_type),
            daemon=True,
        ).start()
        return row

    @app.get("/compiler-gate/job/{job_id}")
    def compiler_gate_job(job_id: str, token: str | None = None) -> dict[str, Any]:
        _check_token(token)
        return _safe_job(job_id)

    @app.get("/compiler-gate/job/{job_id}/file/{filename}")
    def compiler_gate_file(job_id: str, filename: str, token: str | None = None):
        _check_token(token)
        if filename not in ALLOWED_FILES:
            raise HTTPException(status_code=404, detail="Unknown report file")
        row = _safe_job(job_id)
        output_dir = row.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="Report is not ready")
        parent = Path(str(output_dir)).resolve()
        path = (parent / filename).resolve()
        if path.parent != parent or not path.exists():
            raise HTTPException(status_code=404, detail="Report file is not ready")
        return FileResponse(path)
