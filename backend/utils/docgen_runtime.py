"""Make sure the session's sandbox runs THIS deploy's docgen, and say where it is.

Ported from PriceIQ / Kroolo's enterprise-fastapi. The E2B template (backend/e2b.Dockerfile)
bakes docgen and the runners into /opt/priceiq with a content hash. SoldierIQ currently
reuses PriceIQ's template (same E2B team), so the paths keep PriceIQ's names; the only
docgen change here (default author "SoldierIQ") makes the hashes differ, so each fresh box
gets this deploy's docgen uploaded (~2s) until a SoldierIQ template is built from
backend/e2b.Dockerfile. When this
deploy's docgen differs from the image's (a code change without a template
rebuild) or the box is from E2B's stock template, the current docgen is
uploaded into /home/user/.priceiq/docgen-rt and verified there by the same hash.
"""

from __future__ import annotations

import functools
import shlex
from pathlib import Path
from typing import Any, Dict, NamedTuple

from app.logger import logger
from docgen.staleness import compute as _compute

_REPO = Path(__file__).resolve().parent.parent
_LOCAL_DOCGEN = _REPO / "docgen"
_LOCAL_RUNNERS = (_REPO / "sandbox" / "runner.py", _REPO / "sandbox" / "docgen_build.py")

# Baked by e2b.Dockerfile: root and the runtime user resolve python3 differently.
_TEMPLATE_PYTHON = "/opt/priceiq/python"
_TEMPLATE_ROOT = "/opt/priceiq"
# /opt is read-only at runtime, so a repair lands here.
_UPLOAD_ROOT = "/home/user/.priceiq/docgen-rt"
_SHA_FILE = "docgen.sha"

# sandbox_id -> Runtime already verified in this process (saves a ~0.3s probe per build).
_verified: Dict[str, "Runtime"] = {}


class Runtime(NamedTuple):
    python: str
    docgen_build: str
    root: str


@functools.lru_cache(maxsize=1)
def local_sha() -> str:
    return _compute(_LOCAL_DOCGEN, _LOCAL_RUNNERS)


async def ensure_docgen_ready(sbx) -> Runtime:
    """Where to run docgen in this sandbox, uploading it first if the box is behind."""
    want = local_sha()
    cached = _verified.get(sbx.sandbox_id)
    if cached is not None:
        return cached

    # One round trip for all three facts.
    probe = (
        f"test -x {_TEMPLATE_PYTHON} && echo PY || echo NOPY; "
        f"cat {_TEMPLATE_ROOT}/{_SHA_FILE} 2>/dev/null || echo NOSHA; "
        f"cat {_UPLOAD_ROOT}/{_SHA_FILE} 2>/dev/null || echo NOUPLOAD"
    )
    result = await sbx.commands.run(probe, timeout=60)
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    python = _TEMPLATE_PYTHON if (lines and lines[0] == "PY") else "python3"
    baked = lines[1] if len(lines) > 1 else "NOSHA"
    uploaded = lines[2] if len(lines) > 2 else "NOUPLOAD"

    if baked == want:
        root = _TEMPLATE_ROOT
    elif uploaded == want:
        root = _UPLOAD_ROOT
    else:
        if baked != "NOSHA":
            logger.info(
                f"[docgen] template docgen is {baked}, this deploy is {want} — uploading to "
                f"{sbx.sandbox_id}. Build a SoldierIQ E2B template to skip this on fresh boxes."
            )
        await _upload(sbx, python, want)
        root = _UPLOAD_ROOT

    # The runner is invoked by its path under `root`, so `import docgen` resolves
    # there before the template's .pth entry.
    runtime = Runtime(python, f"{root}/docgen_build.py", root)
    if len(_verified) > 1024:
        _verified.clear()
    _verified[sbx.sandbox_id] = runtime
    return runtime


async def _upload(sbx, python: str, want: str) -> None:
    """Ship this deploy's docgen into the sandbox and prove it arrived intact."""
    entries: list[Dict[str, Any]] = [
        {"path": f"{_UPLOAD_ROOT}/docgen/{path.relative_to(_LOCAL_DOCGEN).as_posix()}",
         "data": path.read_bytes()}
        for path in sorted(_LOCAL_DOCGEN.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    entries += [{"path": f"{_UPLOAD_ROOT}/{runner.name}", "data": runner.read_bytes()}
                for runner in _LOCAL_RUNNERS]
    directories = sorted({str(Path(entry["path"]).parent) for entry in entries})
    quoted = " ".join(shlex.quote(d) for d in directories)
    # Wiped first, so a module deleted upstream can't linger from an earlier upload.
    await sbx.commands.run(f"rm -rf {shlex.quote(_UPLOAD_ROOT)} && mkdir -p {quoted}", timeout=60)
    await sbx.files.write_files(entries, request_timeout=120.0)
    # Recomputed inside the sandbox over what actually landed, and written last, so a
    # half-finished upload can never read as complete on the next turn.
    verify = await sbx.commands.run(
        f"{python} {_UPLOAD_ROOT}/docgen/staleness.py {_UPLOAD_ROOT}/docgen "
        f"{_UPLOAD_ROOT}/runner.py {_UPLOAD_ROOT}/docgen_build.py "
        f"| tee {_UPLOAD_ROOT}/{_SHA_FILE}",
        timeout=60,
    )
    got = (verify.stdout or "").strip().splitlines()[-1:] or [""]
    if got[0] != want:
        raise RuntimeError(
            f"the docgen upload did not verify inside the sandbox ({got[0]!r} != {want!r})"
        )
