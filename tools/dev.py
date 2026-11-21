"""Start the gateway API (:8000) and the frontend (:3000) together. Ctrl+C stops both.

python tools/dev.py          Next.js dev server with hot reload
python tools/dev.py --prod   production frontend (run `make build` first); faster, best for demos
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

from lmqa_models.envfile import ROOT, apply_to_process

COLORS = {"api": "\033[36m", "web": "\033[35m"}
RESET = "\033[0m"


def _pump(name: str, proc: subprocess.Popen[bytes]) -> None:
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        print(f"{COLORS[name]}{name:>3}{RESET} | {raw.decode(errors='replace').rstrip()}", flush=True)


def main() -> int:
    prod = "--prod" in sys.argv
    apply_to_process()
    env = dict(os.environ)
    env["PORT"] = "3000"
    env.setdefault("LMQA_API_INTERNAL_URL", "http://127.0.0.1:8000")
    procs = {
        "api": subprocess.Popen(
            [sys.executable, "-m", "gateway"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ),
        "web": subprocess.Popen(  # noqa: S603 - fixed argv, no user input
            ["pnpm", "start" if prod else "dev"],  # noqa: S607 - pnpm resolved from PATH on purpose
            cwd=ROOT / "frontend",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ),
    }
    for name, proc in procs.items():
        threading.Thread(target=_pump, args=(name, proc), daemon=True).start()
    print("\n  App:  http://localhost:3000   (use this address, not 127.0.0.1: Auth0 returns to localhost)")
    print("  API:  http://127.0.0.1:8000/docs\n  Ctrl+C stops both\n", flush=True)
    code = 0
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(0.5)
        code = next(p.returncode for p in procs.values() if p.returncode is not None) or 0
    except KeyboardInterrupt:
        pass
    finally:
        for name, proc in procs.items():
            if proc.poll() is None:
                if name == "web":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
        for proc in procs.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return code


if __name__ == "__main__":
    sys.exit(main())
