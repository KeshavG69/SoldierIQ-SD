"""LibreOffice conversion with a profile built once per process.

`recalc.py` boots soffice twice per workbook — once with `--terminate_after_init` purely to
materialise a user profile, then again to do the work — at a 30s timeout each. The profile is
identical every time, so it is built here on first use and reused for the life of the pod.
"""

import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_shim: Optional[Path] = None

# A stable path, not a per-process temp dir: `recalc.py` runs as a separate subprocess on
# every call, so an in-process cache would rebuild the profile every time. Booting soffice
# once purely to materialise a profile costs a 30s-timeout round trip, and the profile it
# produces is byte-identical every time.
#
# The E2B image bakes a profile at _BAKED so a sandbox never pays that boot. It cannot be
# baked into /tmp: a live probe of the built template found /tmp empty on a fresh sandbox
# even though the image had written there, so the baked copy has to live somewhere that
# survives — and it is only used when it is actually present, which keeps the API pod (no
# /opt/priceiq) on the temp path it has always used.
_BAKED = Path("/opt/priceiq/lo-profile")


def _profile_dir() -> Path:
    override = os.getenv("DOCGEN_LO_PROFILE_DIR")
    if override:
        return Path(override)
    if (_BAKED / "user" / "basic" / "Standard").is_dir():
        return _BAKED
    return Path(tempfile.gettempdir()) / "priceiq-lo-profile"


PROFILE_DIR = _profile_dir()
MACRO_DIR = PROFILE_DIR / "user" / "basic" / "Standard"

CONVERT_TIMEOUT_S = int(os.getenv("DOCGEN_SOFFICE_TIMEOUT_S", "120"))


class SofficeUnavailable(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("soffice") is not None


def _needs_shim() -> bool:
    try:
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close()
        return False
    except OSError:
        return True


def _ensure_shim() -> Optional[Path]:
    """Some sandboxes deny AF_UNIX; LibreOffice aborts rather than degrading."""
    global _shim
    if _shim is not None:
        return _shim or None
    so = Path(tempfile.gettempdir()) / "lo_socket_shim.so"
    if so.exists():
        _shim = so
        return so
    src = Path(tempfile.gettempdir()) / "lo_socket_shim.c"
    try:
        src.write_text(_SHIM_SOURCE)
        subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(so), str(src), "-ldl"],
                       check=True, capture_output=True, timeout=60)
        _shim = so
    except Exception as exc:
        logger.warning("docgen: socket shim unavailable (%s); continuing without it", exc)
        _shim = Path("")
    finally:
        src.unlink(missing_ok=True)
    return _shim or None


def _env() -> dict:
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    if _needs_shim():
        shim = _ensure_shim()
        if shim:
            env["LD_PRELOAD"] = str(shim)
    return env


def profile_ready() -> bool:
    return MACRO_DIR.is_dir()


def profile_dir(macro: Optional[str] = None, macro_name: str = "Module1.xba",
                timeout: int = 60) -> Path:
    """Build the LibreOffice profile once per pod and reuse it.

    Two processes can race here — the recalc subprocess and an in-process convert — so the
    boot is done under a lock and the result is checked rather than assumed.
    """
    with _lock:
        if not profile_ready():
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    ["soffice", f"-env:UserInstallation={PROFILE_DIR.as_uri()}",
                     "--headless", "--terminate_after_init"],
                    env=_env(), capture_output=True, timeout=timeout,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                raise SofficeUnavailable(f"could not build a LibreOffice profile: {exc}") from exc
        if macro is not None:
            if not MACRO_DIR.is_dir():
                raise SofficeUnavailable(
                    "LibreOffice did not create a usable profile directory")
            target = MACRO_DIR / macro_name
            if not target.exists() or target.read_text() != macro:
                target.write_text(macro)
    return PROFILE_DIR


def run(args: List[str], timeout: int = CONVERT_TIMEOUT_S) -> subprocess.CompletedProcess:
    if not available():
        raise SofficeUnavailable("soffice is not on PATH")
    cmd = ["soffice", f"-env:UserInstallation={profile_dir().as_uri()}", "--headless",
           "--norestore", "--invisible"] + args
    return subprocess.run(cmd, env=_env(), capture_output=True, timeout=timeout)


def to_pdf(path, out_dir=None, timeout: int = CONVERT_TIMEOUT_S) -> Path:
    src = Path(path).resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="docgen-pdf-"))
    out.mkdir(parents=True, exist_ok=True)
    res = run(["--convert-to", "pdf", "--outdir", str(out), str(src)], timeout=timeout)
    pdf = out / (src.stem + ".pdf")
    if not pdf.exists():
        raise SofficeUnavailable(
            f"conversion produced no pdf: {res.stderr.decode('utf-8', 'replace')[:400]}"
        )
    return pdf


_SHIM_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <sys/socket.h>

static int (*real_socket)(int, int, int) = 0;

int socket(int domain, int type, int protocol) {
    if (!real_socket) real_socket = dlsym(RTLD_NEXT, "socket");
    if (domain == AF_UNIX) { errno = EAFNOSUPPORT; return -1; }
    return real_socket(domain, type, protocol);
}
"""
