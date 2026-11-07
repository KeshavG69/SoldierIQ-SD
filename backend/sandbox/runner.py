"""Run one model-written script inside the E2B sandbox and report what happened.

This file is never imported by the backend. utils/python_repl_tool.py uploads it
into the sandbox next to each script and runs `python3 runner.py <script>`. It
prints ONE machine-readable line, so the caller reads the outcome from fields
instead of searching the output for the word "Error":

    @@PRICEIQ_RESULT@@{"ok": false, "error": {"type": "NameError", ...}, "files": [...]}

`files` lists what was created or changed in the output directory during the
run, so the caller knows a document was produced without the model saying so.

Stdlib only: it has to work on any template, including E2B's stock one.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import time
import traceback
from pathlib import Path

RESULT_MARKER = "@@PRICEIQ_RESULT@@"
OUT_DIR = Path(os.environ.get("PRICEIQ_OUT_DIR", "/home/user/out"))
# Enough of a traceback to fix the code, not enough to flood the model's context.
_TRACEBACK_TAIL_LINES = 12
_STDOUT_TAIL_CHARS = 8000


def _snapshot(directory: Path) -> dict[str, tuple[int, float]]:
    if not directory.exists():
        return {}
    out: dict[str, tuple[int, float]] = {}
    for path in directory.rglob("*"):
        if path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue
            out[str(path)] = (stat.st_size, stat.st_mtime)
    return out


class _Tee:
    """Capture output while still passing it to the real stream."""

    def __init__(self, stream):
        self._stream = stream
        self._chunks: list[str] = []

    def write(self, text: str) -> int:
        self._chunks.append(text)
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def value(self) -> str:
        return "".join(self._chunks)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(RESULT_MARKER + json.dumps(
            {"ok": False, "error": {"type": "UsageError", "message": "usage: runner.py <script>"}}))
        return 2

    script = argv[1]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # cwd is the output directory, so a script that saves "report.pdf" with no
    # path lands where s3_upload_tool looks for it.
    os.chdir(OUT_DIR)
    before = _snapshot(OUT_DIR)

    real_out, real_err = sys.stdout, sys.stderr
    tee_out, tee_err = _Tee(real_out), _Tee(real_err)
    sys.stdout, sys.stderr = tee_out, tee_err
    started = time.time()
    error = None
    try:
        # run_path gives the script __name__ == "__main__" and a clean namespace.
        runpy.run_path(script, run_name="__main__")
    except BaseException as exc:  # noqa: BLE001 - every failure is a result, not a crash
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            error = None
        else:
            tb = traceback.format_exc().strip().splitlines()
            error = {
                "type": type(exc).__name__,
                "message": str(exc)[:600],
                "traceback_tail": "\n".join(tb[-_TRACEBACK_TAIL_LINES:]),
            }
    finally:
        sys.stdout, sys.stderr = real_out, real_err

    after = _snapshot(OUT_DIR)
    files = [
        {"name": os.path.relpath(path, OUT_DIR), "size": size}
        for path, (size, mtime) in sorted(after.items())
        if before.get(path) != (size, mtime)
    ]
    payload = {
        "ok": error is None,
        "error": error,
        "elapsed_s": round(time.time() - started, 3),
        "stdout_tail": tee_out.value()[-_STDOUT_TAIL_CHARS:],
        "stderr_tail": tee_err.value()[-_STDOUT_TAIL_CHARS:],
        "files": files,
    }
    print(RESULT_MARKER + json.dumps(payload, default=str))
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
