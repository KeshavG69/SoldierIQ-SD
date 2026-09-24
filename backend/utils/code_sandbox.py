"""
Job-scoped code sandbox on the server's own container.

Each generation job gets a private working directory. Model-written code runs in a
separate subprocess (never exec'd inside the API process), with that directory as cwd,
a hard timeout, and truncated output. Files persist in the directory for the life of the
job; Python variables do not persist between calls (each call is a fresh interpreter).

Pattern ported from enterprise-fastapi's pre-E2B python_repl_tool, but out-of-process:
- no process-wide os.chdir races between concurrent jobs
- a crash, infinite loop or memory blow-up in model code can't take the API worker down
"""

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logger import logger

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PPTX_SKILL_DIR = BACKEND_ROOT / "pptx"
NODE_MODULES_DIR = BACKEND_ROOT / "pptx_runtime" / "node_modules"

DEFAULT_TIMEOUT_S = int(os.getenv("CODE_SANDBOX_TIMEOUT_S", "240"))
STDOUT_TAIL = 6000
STDERR_TAIL = 3000


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…(truncated)…\n" + text[-limit:]


class CodeSandbox:
    """A private working directory plus helpers to run Python / shell inside it"""

    def __init__(self, job_id: str):
        self.job_id = job_id
        # resolve(): on macOS the temp dir sits behind a /var -> /private/var symlink
        self.dir = Path(tempfile.mkdtemp(prefix=f"sandbox_{job_id[:8]}_")).resolve()
        self._scripts_dir = self.dir / ".scripts"
        self._scripts_dir.mkdir()
        logger.info(f"🧪 Sandbox for job {job_id} at {self.dir}")

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def env(self) -> Dict[str, str]:
        """Subprocess env: backend venv first on PATH, Node packages resolvable, skill dir exported"""
        env = os.environ.copy()
        venv_bin = str(Path(sys.executable).parent)
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        env["NODE_PATH"] = str(NODE_MODULES_DIR)
        env["SKILL_DIR"] = str(PPTX_SKILL_DIR)
        env["HOME"] = str(self.dir)  # LibreOffice & friends write caches under HOME
        env["PYTHONUNBUFFERED"] = "1"
        # Never leak server secrets into model-written code
        for key in list(env):
            if any(s in key.upper() for s in ("API_KEY", "SECRET", "PASSWORD", "TOKEN", "POSTGRES_URL", "MONGODB_URL", "ACCESS_KEY")):
                env.pop(key, None)
        return env

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _snapshot(self) -> Dict[str, tuple]:
        files = {}
        for p in self.dir.rglob("*"):
            if p.is_file() and ".scripts" not in p.parts:
                st = p.stat()
                files[str(p.relative_to(self.dir))] = (st.st_size, st.st_mtime)
        return files

    async def _run(self, argv: List[str], timeout: int) -> Dict[str, Any]:
        before = self._snapshot()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.dir),
            env=self.env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group so a timeout kills children too
        )
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            out, err = await proc.communicate()

        after = self._snapshot()
        changed = sorted(f for f, meta in after.items() if before.get(f) != meta)
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        result: Dict[str, Any] = {
            "success": proc.returncode == 0 and not timed_out,
            "exit_code": proc.returncode,
            "stdout": _tail(stdout, STDOUT_TAIL) or "(no output)",
            "stderr": _tail(stderr, STDERR_TAIL),
            "new_or_changed_files": changed,
            "working_dir": str(self.dir),
        }
        if timed_out:
            result["error"] = f"Timed out after {timeout}s and was killed. Split the work into smaller steps."
        return result

    async def run_python(self, code: str, timeout: int = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
        digest = hashlib.sha256(code.encode()).hexdigest()[:12]
        script = self._scripts_dir / f"s_{digest}.py"
        script.write_text(code, encoding="utf-8")
        return await self._run([sys.executable, str(script)], timeout)

    async def run_shell(self, command: str, timeout: int = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
        return await self._run(["bash", "-c", command], timeout)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def path(self, relative: str) -> Path:
        """Resolve a path inside the sandbox; refuses anything that escapes it"""
        p = (self.dir / relative).resolve()
        if self.dir not in p.parents and p != self.dir:
            raise ValueError(f"Path escapes the sandbox: {relative}")
        return p

    def find_latest(self, suffix: str) -> Optional[Path]:
        candidates = [p for p in self.dir.rglob(f"*{suffix}") if ".scripts" not in p.parts]
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        logger.info(f"🧹 Sandbox for job {self.job_id} removed")
