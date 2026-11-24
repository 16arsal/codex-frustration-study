"""Run the hidden test cases against one copy of the ledger code.

usage: python3 -I runner.py CODE_DIR SUITE SCOPE OUT.json
  SUITE: qa | holdout
  SCOPE: core | all
Runs in its own process so each workspace's `ledger` is imported fresh.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

code_dir, suite, scope, out_path = sys.argv[1:5]
code_dir = os.path.abspath(code_dir)
sys.path.insert(0, code_dir)
sys.dont_write_bytecode = True

import cases  # noqa: E402

TIMEOUT = 5


def cli(args, group):
    """Run `python3 -m ledger <args> <file>`; group is a dict, raw text, or None (path already in args)."""
    path = None
    if group is not None:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write(group if isinstance(group, str) else json.dumps(group))
        args = args + [path]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    try:
        p = subprocess.run([sys.executable, "-m", "ledger", *args], cwd=code_dir, env=env,
                           capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        raise cases.Fail("CLI timed out after 10s")
    finally:
        if path:
            os.unlink(path)


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)

results = []
try:
    import ledger  # noqa: F401
    import_error = None
except Exception as exc:  # noqa: BLE001
    ledger = None
    import_error = f"import ledger failed: {type(exc).__name__}: {exc}"

for t in cases.TESTS:
    if t["suite"] != suite or (scope == "core" and t["scope"] != "core"):
        continue
    r = {"name": t["name"], "scope": t["scope"], "desc": t["desc"]}
    if import_error:
        r.update(ok=False, detail=import_error)
    else:
        signal.alarm(TIMEOUT)
        try:
            t["fn"](ledger, cli)
            r.update(ok=True, detail="")
        except cases.Fail as f:
            r.update(ok=False, detail=str(f))
        except Timeout:
            r.update(ok=False, detail=f"timed out after {TIMEOUT}s")
        except Exception as exc:  # noqa: BLE001
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            r.update(ok=False, detail=f"raised {type(exc).__name__}: {exc} ({os.path.basename(tb.filename)}:{tb.lineno})")
        finally:
            signal.alarm(0)
    results.append(r)

with open(out_path, "w") as f:
    json.dump(results, f, indent=1)
