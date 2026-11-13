"""The agent's two OSINT tools: search_osint_tools and run_osint_tool.

They front the whole OSINT catalog (backend/osint, 40+ tools) so the agent's
tool list and prompt stay small and fixed; see osint/dispatch.py.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agno.tools import tool
from agno.tools.function import Function


@tool(stop_after_tool_call=False)
async def search_osint_tools(query: str, limit: int = 6) -> str:
    """Find the open-source intelligence tools that fit a task: live conflict and strike reports, military
    air posture, airspace, chokepoint shipping, hotspots, country risk and briefs, news with source
    corroboration, claim verification, sanctions screening, cyber threats, internet outages, disasters,
    radiation, displacement, health outbreaks, prediction markets and more.

    Call this before answering any question about current world events, security or military activity,
    then call run_osint_tool with the best result. Results include each tool's parameters.

    Args:
        query: What you need, in plain words, e.g. "ship traffic through the Strait of Hormuz" or
            "is this company sanctioned".
        limit: Maximum tools to return (1-10, default 6).
    """
    import json

    from osint.dispatch import search

    return json.dumps(await search(query, limit), ensure_ascii=False, default=str)


async def _run_osint_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """Run one OSINT tool found with search_osint_tools.

    Args:
        tool_name: The tool name exactly as search_osint_tools returned it, e.g. "get_chokepoint_status".
        arguments: The tool's parameters as a JSON object matching its schema; {} for none.
    """
    from osint.dispatch import run

    return await run(tool_name, arguments)


# Explicit schema: Agno would otherwise derive one from the type hints that rejects a free-form
# `arguments` object (the same problem Kroolo's run_composio_action solved this way).
run_osint_tool = Function(
    name="run_osint_tool",
    description=(
        "Run one open-source intelligence tool found with search_osint_tools and return its result: a JSON "
        "envelope with status (ok / partial / unavailable), sources with fetch times, data, and notes "
        "(caveats to pass on). If it returns 'invalid arguments', fix them using the returned parameters "
        "and call again."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {"type": "string",
                          "description": 'The tool name exactly as search_osint_tools returned it, e.g. "get_chokepoint_status".'},
            "arguments": {"type": "object", "additionalProperties": True,
                          "description": "The tool's parameters as a JSON object matching its schema; {} for none."},
        },
        "required": ["tool_name"],
    },
    entrypoint=_run_osint_tool,
    skip_entrypoint_processing=True,
)
