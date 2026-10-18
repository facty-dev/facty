#!/usr/bin/env python3
# test_dotenv.py — the dotenv setup (engine/dotenv.py + the `facty env`
# command): parsing, the setdefault semantics (the real environment —
# including the VMs' host-secret placeholders — always wins), the
# machine-local vs project files, the status/exports shapes (never
# values), and the gitignore guard. No real secrets involved.
#
# Usage: python3 engine/test_dotenv.py   (or: ./facty test / make dss-test)

import os
import sys
import tempfile
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import dotenv  # noqa: E402
import cli     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}"
          + (f" — {detail}" if detail and not ok else ""))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        machine = tmp / "machine.env"
        project = tmp / "project.env"

        # ── parse ─────────────────────────────────────────────────────
        text = (
            "# a comment\n"
            "\n"
            "PLAIN=value\n"
            "export EXPORTED=with-export\n"
            "QUOTED=\"double quoted\"\n"
            "SINGLE='single quoted'\n"
            "SPACED = padded value \n"
            "not-a-key-line\n"
            "EMPTY=\n"
        )
        parsed = dotenv.parse(text)
        check("parse: comments/blanks/export/quotes/spacing",
              parsed == {"PLAIN": "value", "EXPORTED": "with-export",
                         "QUOTED": "double quoted", "SINGLE": "single quoted",
                         "SPACED": "padded value", "EMPTY": ""},
              str(parsed))

        # ── load: setdefault + the file order ─────────────────────────
        machine.write_text("SHARED=from-machine\nSHELL_WINS=from-machine\n"
                           "MACHINE_ONLY=m\n")
        project.write_text("SHARED=from-project\nPROJECT_ONLY=p\n")
        env = {"SHELL_WINS": "shell"}
        loaded = dotenv.load(paths=(machine, project), environ=env)
        check("load: the machine-local file wins over the project file",
              env["SHARED"] == "from-machine")
        check("load: setdefault — the real environment always wins",
              env["SHELL_WINS"] == "shell")
        check("load: both files load; pre-set keys are not reported",
              dict(loaded) == {"SHARED": str(machine),
                               "MACHINE_ONLY": str(machine),
                               "PROJECT_ONLY": str(project)},
              str(loaded))
        check("load: a missing file is fine",
              dotenv.load(paths=(tmp / "nope.env",), environ={}) == [])

        # ── status: origins, never values ─────────────────────────────
        # (status/exports read the module-level file constants — point
        # them at the tmp files)
        real_files = (dotenv.MACHINE_FILE, dotenv.PROJECT_FILE)
        dotenv.MACHINE_FILE = machine
        dotenv.PROJECT_FILE = project
        try:
            machine.write_text("UPRELIC_API_KEY=secret-value\nSHARED=x\n")
            st = dict(dotenv.status(environ={}))
            check("status: the origin is reported, never the value",
                  st.get("UPRELIC_API_KEY") == str(machine)
                  and "secret-value" not in str(st), str(st))
            env2 = {"MISTRAL_API_KEY": "<placeholder>"}  # not in the files
            st2 = dict(dotenv.status(environ=env2))
            check("status: an environment-only key reports 'environment'",
                  st2.get("MISTRAL_API_KEY") == "environment", str(st2))
            st3 = dict(dotenv.status(environ={}))
            check("status: an unset key reports None",
                  st3.get("MISTRAL_API_KEY") is None, str(st3))
        finally:
            dotenv.MACHINE_FILE, dotenv.PROJECT_FILE = real_files

        # ── exports: the eval-hoist shape ─────────────────────────────
        import shlex
        env3 = {"UPRELIC_API_KEY": "upr_test'key",
                "MISTRAL_API_KEY": "plain"}
        out = dotenv.exports(environ=env3)
        quoted = shlex.quote("upr_test'key")
        check("exports: quoted export lines for the set keys",
              out == f"export UPRELIC_API_KEY={quoted}\n"
                     "export MISTRAL_API_KEY=plain", repr(out))
        check("exports: an empty environment prints nothing",
              dotenv.exports(environ={}) == "")

        # ── the CLI: facty env (status + --exports) ───────────────────
        saved = {k: os.environ.get(k) for k in dotenv.KNOWN_KEYS}
        for k in dotenv.KNOWN_KEYS:
            os.environ.pop(k, None)
        try:
            real_status = dotenv.status
            real_exports = dotenv.exports

            def file_status(environ=None):
                return real_status(environ={"UPRELIC_API_KEY": "x"})

            dotenv.status = file_status
            dotenv.exports = lambda environ=None: "export UPRELIC_API_KEY=x"
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.cmd_env(type("A", (), {"exports": False})())
            out = buf.getvalue()
            check("facty env: the status prints origins, never values",
                  rc == 0 and "UPRELIC_API_KEY" in out
                  and "environment" in out
                  and "~/.facty/.env" in out, out)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.cmd_env(type("A", (), {"exports": True})())
            out = buf.getvalue()
            check("facty env --exports: prints the export lines",
                  rc == 0 and out.startswith("export UPRELIC_API_KEY="),
                  out)
        finally:
            dotenv.status = real_status
            dotenv.exports = real_exports
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)

        # ── the gitignore guard ───────────────────────────────────────
        gitignore = (ENGINE_DIR.parent / ".gitignore").read_text()
        check(".gitignore: .env is ignored (never committed)",
              any(line.strip() == ".env"
                  for line in gitignore.splitlines()))

    failed = len(RESULTS) - sum(RESULTS)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
