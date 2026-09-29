"""
Human-readable labels for tool calls, sent with tool.started / tool.completed
stream events so the chat can show a live timeline of what the agent is doing
(like enterprise's StreamingToolCalls).

Covers every tool the chat agent can have: knowledge-base / graph search, TAK,
the Composio setup tools, and every Composio action (labels + logos come from
the connector catalog, so new apps need no code here).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.logger import logger
from clients.composio_connectors import get_catalog

# Built-in tools: (running label, done label, icon)
_BUILTIN: Dict[str, tuple] = {
    "search_knowledge_base": ("Searching your documents", "Searched your documents", "search"),
    "place_tak_marker": ("Placing a marker on the TAK map", "Placed a marker on the TAK map", "map"),
    "send_tak_message": ("Sending a TAK message", "Sent a TAK message", "message"),
    "create_tak_route": ("Creating a TAK route", "Created a TAK route", "route"),
}

# Argument keys worth showing under the label, most informative first.
_DETAIL_KEYS = (
    "query", "q", "search", "subject", "recipient_email", "to", "channel", "title",
    "summary", "name", "message", "text", "issue_key", "callsign", "route_name",
    "service_name", "task_description",
)
_MAX_DETAIL = 90


def _detail(args: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    for key in _DETAIL_KEYS:
        value = args.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            text = " ".join(str(value).split())
            return text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 1] + "…"
    return None


def _sentence(name: str) -> str:
    words = (name or "tool").replace("-", "_").split("_")
    return " ".join(words).strip().capitalize()


async def _action_index() -> Dict[str, Dict[str, Any]]:
    """{lowercased action code: {title, app, logo}} from the cached catalog."""
    catalog = await get_catalog()
    index: Dict[str, Dict[str, Any]] = {}
    for tool in catalog["tools"]:
        for action in catalog["actions_by_tool"].get(tool["id"], []):
            index[action["code"].lower()] = {
                "title": action["title"],
                "app": tool["title"],
                "logo": tool["logo"],
            }
    return index


async def _app_by_service(service: Optional[str]) -> Optional[Dict[str, Any]]:
    if not service:
        return None
    from clients.composio_action_selector import resolve_tool
    return await resolve_tool(service)


async def describe_tool(tool_name: Optional[str], tool_args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"label", "done_label", "detail", "app", "logo", "icon"} for one call."""
    name = tool_name or ""
    detail = _detail(tool_args)
    try:
        if name in _BUILTIN:
            running, done, icon = _BUILTIN[name]
            return {"label": running, "done_label": done, "detail": detail, "app": None, "logo": None, "icon": icon}

        if name in ("setup_composio_service", "select_additional_actions"):
            service = (tool_args or {}).get("service_name") or (tool_args or {}).get("required_service")
            app = await _app_by_service(service)
            title = app["title"] if app else _sentence(service or "app")
            if name == "setup_composio_service":
                running, done = f"Setting up {title}", f"Set up {title}"
            else:
                running, done = f"Enabling {title} actions", f"Enabled {title} actions"
            return {
                "label": running, "done_label": done,
                "detail": _detail({"task_description": (tool_args or {}).get("task_description")}),
                "app": title, "logo": app["logo"] if app else None, "icon": "plug",
            }

        action = (await _action_index()).get(name.lower())
        if action:
            return {
                "label": action["title"], "done_label": action["title"], "detail": detail,
                "app": action["app"], "logo": action["logo"], "icon": "app",
            }
    except Exception as e:  # display metadata must never break the stream
        logger.warning(f"describe_tool({name}) failed: {e}")

    label = _sentence(name)
    return {"label": label, "done_label": label, "detail": detail, "app": None, "logo": None, "icon": "tool"}
