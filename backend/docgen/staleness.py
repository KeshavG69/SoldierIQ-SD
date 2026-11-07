"""One content hash for docgen, computed identically on the API pod and in the sandbox image.

docgen exists in two places — this repo, which the pod imports, and the E2B image, which
actually builds documents. When they disagree the pod is deploying code that never reaches
the thing doing the work, and the symptom is a document in last week's styling with no error
anywhere.

The image used to hash a tar of /opt/priceiq/docgen in a form the pod could not reproduce, so
nothing ever compared the two. This module is the single definition of "which docgen is
this": stdlib only, so it runs as a script inside the image at build time and imports on the
pod, and both get the same answer by construction rather than by two implementations
agreeing.

    # in the image, at build time
    python3 staleness.py /opt/priceiq/docgen /opt/priceiq/runner.py /opt/priceiq/docgen_build.py

    # on the pod
    from docgen.staleness import compute
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Iterable

# Names, not just bytes: a file that is renamed or deleted has to change the hash, and
# hashing contents alone would miss both.
_SEP = b"\0"


def compute(docgen_dir: Path | str, runners: Iterable[Path | str]) -> str:
    """A stable short hash of the docgen package plus the sandbox runners.

    Sorted, so directory iteration order cannot change the answer between a Linux image and
    a macOS checkout. __pycache__ is excluded because it is generated, differs per
    interpreter, and is not what gets shipped.
    """
    root = Path(docgen_dir)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(f"docgen/{path.relative_to(root).as_posix()}".encode() + _SEP)
        digest.update(path.read_bytes() + _SEP)
    for runner in sorted(Path(r) for r in runners):
        digest.update(runner.name.encode() + _SEP)
        digest.update(runner.read_bytes() + _SEP)
    return digest.hexdigest()[:16]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: staleness.py <docgen_dir> <runner.py>...", file=sys.stderr)
        raise SystemExit(2)
    print(compute(sys.argv[1], sys.argv[2:]))
