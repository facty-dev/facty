#!/usr/bin/env python3
# dotenv.py — the project's dotenv setup (stdlib-only): machine-local
# secrets, easy to hoist into the VMs and to extend.
#
# Two files, both never committed (`.env` is gitignored):
#   ~/.facty/.env   — machine-local secrets. Keep the REAL keys HERE:
#                     the repo (with a project .env) is mounted into the
#                     gondolin VMs, and a guest must not read them — the
#                     VM's host-secret mechanism injects placeholders and
#                     the host proxy substitutes the real values into
#                     outbound requests.
#   ./.env          — project defaults (non-secret values only).
#
# Load order: ~/.facty/.env first, then ./.env, both via
# os.environ.setdefault — the real environment always wins (a shell
# export, or the VM's host-secret placeholder, is never overridden).
#
# Format: KEY=VALUE per line; `#` comments; blank lines; an optional
# `export ` prefix; optional single/double quotes. No interpolation.
#
# Hoisting into the VMs: `eval "$(./facty env --exports)"` in the
# launching shell — gondolin-pi.sh reads the keys host-side
# (--host-secret KEY@host) and the guest only ever sees placeholders.
# Adding a new key: one line in ~/.facty/.env + (if the VMs must reach
# it) a --host-secret line in gondolin-pi.sh + a row in KNOWN_KEYS.
#
# Library:
#   import dotenv
#   dotenv.load()          # load both files into os.environ
#   dotenv.status()        # [(key, origin)] — never values
#   dotenv.exports()       # "export KEY='value'" lines (secrets!)

import os
import shlex
from pathlib import Path

MACHINE_FILE = Path.home() / ".facty" / ".env"
PROJECT_FILE = Path(".env")  # the CWD — the repo root when run via ./facty

# The keys Facty knows about (add new ones here + in .env.example).
KNOWN_KEYS = ("UPRELIC_API_KEY", "MISTRAL_API_KEY")


def parse(text):
    """Parse dotenv text → an ordered {key: value} dict (no interpolation)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load(paths=None, environ=None):
    """Load the dotenv files into environ (setdefault — the real
    environment wins). Returns [(key, source-path)] for the keys loaded."""
    environ = os.environ if environ is None else environ
    loaded = []
    for path in (paths if paths is not None else (MACHINE_FILE, PROJECT_FILE)):
        path = Path(path)
        if not path.exists():
            continue
        for key, value in parse(path.read_text()).items():
            if key not in environ:
                environ[key] = value
                loaded.append((key, str(path)))
    return loaded


def status(environ=None):
    """[(key, origin)] for the known keys — where each comes from (a file
    path or "environment"), or None when unset. Never values."""
    environ = os.environ if environ is None else environ
    out = []
    for key in KNOWN_KEYS:
        origin = None
        for path in (MACHINE_FILE, PROJECT_FILE):
            if path.exists() and key in parse(path.read_text()):
                origin = str(path)
                break
        if key in environ:
            origin = origin or "environment"
        out.append((key, origin))
    return out


def exports(environ=None):
    """`export KEY='value'` lines for the known keys that are set — for
    `eval "$(./facty env --exports)"` (hoisting into the launching shell
    and the VMs). Prints secrets: the user's own terminal only."""
    environ = os.environ if environ is None else environ
    lines = []
    for key, _origin in status(environ):
        if key in environ:
            lines.append(f"export {key}={shlex.quote(environ[key])}")
    return "\n".join(lines)
