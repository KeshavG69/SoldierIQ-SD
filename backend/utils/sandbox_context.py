"""Which chat session (and whose) the agent's sandbox tools are running for.

Tools read the session, org and user from ContextVars, so build_document needs no
hidden arguments the model could get wrong. routers/chat.py sets them from the
signed-in user before the agent runs. (PriceIQ keeps these in python_repl_tool.py;
SoldierIQ has no Python tool, so they live here.)
"""

from __future__ import annotations

import contextvars
from typing import Dict

_current_session_id = contextvars.ContextVar("sandbox_session_id", default="default")
_current_org_id = contextvars.ContextVar("sandbox_org_id", default="")
_current_user_id = contextvars.ContextVar("sandbox_user_id", default="")


def set_session_context(session_id: str, org_id: str = "", user_id: str = "") -> None:
    """Bind the chat session and its owner for the tools. Call before running the agent."""
    _current_session_id.set(session_id or "default")
    _current_org_id.set(str(org_id or ""))
    _current_user_id.set(str(user_id or ""))


def get_session_context() -> Dict[str, str]:
    return {
        "session_id": _current_session_id.get(),
        "org_id": _current_org_id.get(),
        "user_id": _current_user_id.get(),
    }


async def sandbox_for_this_session():
    """The current session's sandbox, created on first use."""
    from utils.e2b_sandbox import get_or_resume_sandbox

    ctx = get_session_context()
    return await get_or_resume_sandbox(
        ctx["session_id"], org_id=ctx["org_id"], user_id=ctx["user_id"]
    )
