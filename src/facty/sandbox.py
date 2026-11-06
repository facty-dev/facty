"""Sandbox: programmatic execution of LLM-written code (the "codemode" path).

The LLM may WRITE code (induction side); the code RUNS under our control, never
in an interactive chat session, and never in the verdict path. Two backends:

  smolvm   the real isolation: the code runs inside the SmolVM micro-VM booted
           from the root Dockerfile (`smolvm machine exec --name facty -- ...`).
           Used automatically when the `smolvm` binary + the `facty` machine exist.
  local    dev fallback: `python -I` subprocess in a temp cwd with a minimal env
           and a hard timeout. NOT network-isolated — only for trusted local dev
           (`--dev`); the SmolVM backend is the zero-data-trust path.

API: run_code(code, *, files: dict[str, bytes], timeout=30, backend="auto")
  → {ok, exit_code, stdout, stderr, backend, seconds}
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SMOLVM_MACHINE = os.environ.get("FACTY_SANDBOX_VM", "facty")

_machine_ready: bool = False  # create ONCE per process, then reuse — no VM thrash


def _smolvm_available() -> bool:
    return shutil.which("smolvm") is not None


def ensure_machine() -> None:
    """Create the SmolVM machine once per process and reuse it across calls/tests
    (`smolvm machine create --net --name facty` + start). Rebuilding the VM per
    sandbox call would thrash compute; the VM is a long-lived session."""
    global _machine_ready
    if _machine_ready or not _smolvm_available():
        return
    subprocess.run(["smolvm", "machine", "create", "--net", "--name", SMOLVM_MACHINE],
                   capture_output=True, timeout=120, check=False)
    subprocess.run(["smolvm", "machine", "start", "--name", SMOLVM_MACHINE],
                   capture_output=True, timeout=120, check=False)
    _machine_ready = True


def _run_local(code: str, files: dict[str, bytes], timeout: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="facty-sandbox-") as td:
        for name, data in files.items():
            (Path(td) / name).write_bytes(data)
        (Path(td) / "main.py").write_text(code)
        env = {"PATH": "/usr/bin:/bin", "HOME": td, "LANG": "C.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1"}
        # the evidence file is materialized in cwd; pass its name as argv[1]
        argv1 = sorted(files)[0] if files else None
        cmd = ["python3", "-I", "main.py"] + ([argv1] if argv1 else [])
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, cwd=td, env=env,
                               capture_output=True, text=True, timeout=timeout)
            return {"ok": p.returncode == 0, "exit_code": p.returncode,
                    "stdout": p.stdout, "stderr": p.stderr, "backend": "local",
                    "seconds": round(time.monotonic() - t0, 2)}
        except subprocess.TimeoutExpired as e:
            return {"ok": False, "exit_code": -1, "stdout": e.stdout or "",
                    "stderr": (e.stderr or "") + f"\nTIMEOUT after {timeout}s",
                    "backend": "local", "seconds": round(time.monotonic() - t0, 2)}


def _run_smolvm(code: str, files: dict[str, bytes], timeout: float) -> dict:
    """Code + files travel over stdin as a JSON payload; a tiny bootstrap inside
    the VM materializes them in a tempdir and runs the code with `python -I -`."""
    import base64
    import json as _json
    payload = _json.dumps({
        "code": code,
        "files": {n: base64.b64encode(d).decode() for n, d in files.items()},
    })
    bootstrap = (
        "import base64,json,os,subprocess,sys,tempfile\n"
        "p=json.loads(sys.stdin.readline());d=tempfile.mkdtemp()\n"
        "for n,b in p['files'].items():\n"
        "    fp=os.path.join(d,n);os.makedirs(os.path.dirname(fp),exist_ok=True) if os.path.dirname(n) else None\n"
        "    open(fp,'wb').write(base64.b64decode(b))\n"
        "open(os.path.join(d,'main.py'),'w').write(p['code'])\n"
        "argv=[os.path.join(d,n) for n in sorted(p['files'])]\n"
        "r=subprocess.run([sys.executable,'-I',os.path.join(d,'main.py')]+argv,cwd=d,capture_output=True,text=True,timeout=int(p.get('timeout',120)))\n"
        "sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)\n"
    )
    payload = _json.dumps({"code": code, "timeout": int(timeout),
                           "files": {n: base64.b64encode(d).decode() for n, d in files.items()}})
    t0 = time.monotonic()
    try:
        p = subprocess.run(
            ["smolvm", "machine", "exec", "--name", SMOLVM_MACHINE, "--",
             "python3", "-I", "-"],
            input=payload + "\n" + bootstrap,
            capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "exit_code": -1, "stdout": e.stdout or "",
                "stderr": (e.stderr or "") + f"\nTIMEOUT after {timeout}s",
                "backend": "smolvm", "seconds": round(time.monotonic() - t0, 2)}
    return {"ok": p.returncode == 0, "exit_code": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr, "backend": "smolvm",
            "seconds": round(time.monotonic() - t0, 2)}


def run_code(code: str, files: dict[str, bytes] | None = None,
             timeout: float = 30.0, backend: str = "auto") -> dict:
    files = files or {}
    if backend == "auto":
        backend = "smolvm" if _smolvm_available() else "local"
    if backend == "smolvm":
        if not _smolvm_available():
            return {"ok": False, "exit_code": -1, "stdout": "",
                    "stderr": "smolvm binary not found — install SmolVM or use backend=local (--dev)",
                    "backend": "smolvm", "seconds": 0.0}
        ensure_machine()  # create once, reuse across calls
        return _run_smolvm(code, files, timeout)
    return _run_local(code, files, timeout)
