"""
Agno tools for setting up Composio connectors from chat.

Ported from enterprise-fastapi/utils/agno_tools.py (create_composio_auth_tool /
create_smart_action_selector_tool):

- setup_composio_service: the user wants to do something in an app. Enables
  the actions that request needs (smart selection) and reports whether the app
  is connected. If it isn't, the chat UI shows a "Connect <app>" card for the
  result (frontend: ChatArea handles tool.completed for this tool name).
- select_additional_actions: the app is connected but the enabled actions
  don't cover the request; enable the missing ones.

The chat agent is rebuilt for every message (routers/chat.py), so actions
enabled here are usable from the user's NEXT message in the same conversation.
"""
from __future__ import annotations

import json
from typing import Optional

from app.logger import logger
from clients.composio_action_selector import resolve_tool, smart_select_actions, supported_services
from clients.composio_connectors import _get_connection, _refresh_pending

SETUP_TOOL_NAME = "setup_composio_service"


def create_composio_setup_tools(organization_id: Optional[str], user_id: str) -> list:

    async def setup_composio_service(service_name: str, query: str, task_description: str) -> str:
        """Set up a third-party app (Gmail, Slack, Jira, Google Calendar, …) for the user's request:
        enables the app actions the request needs and checks whether the app is connected.
        Call this when the user wants to do something in an app whose tools you don't have.

        Args:
            service_name (str): App key, e.g. "gmail", "slack", "jira", "googlecalendar", "notion".
            query (str): The user's request, verbatim.
            task_description (str): Short description of what needs doing, e.g. "send an email".

        Returns:
            str: JSON with service, already_connected, needs_auth, actions_added and a message.
        """
        try:
            tool = await resolve_tool(service_name)
            if not tool:
                return json.dumps({
                    "error": f"Unsupported service: {service_name}",
                    "supported_services": await supported_services(),
                    "message": "Choose the closest supported service and retry.",
                })

            selection = await smart_select_actions(organization_id, user_id, query, tool["name"], task_description)

            connection = await _get_connection(organization_id, user_id, tool["name"])
            if connection and connection.get("status") != "ACTIVE":
                connection = await _refresh_pending(connection)
            connected = bool(connection and connection.get("status") == "ACTIVE")

            result = {
                "service": tool["name"],
                "service_title": tool["title"],
                "logo": tool["logo"],
                "already_connected": connected,
                "needs_auth": not connected,
                "actions_added": selection.get("added_actions", []),
                "already_enabled_actions": selection.get("already_enabled_actions", []),
                "disconnected_actions": selection.get("disconnected_actions", []),
                "selection": selection.get("message"),
            }
            if not selection.get("success", False):
                result["error"] = selection.get("error")
            if connected:
                result["message"] = (
                    f"{tool['title']} is connected. {selection.get('message', '')} "
                    "The new actions are usable from the user's next message."
                ).strip()
            else:
                result["message"] = (
                    f"{tool['title']} is not connected yet. {selection.get('message', '')} "
                    f"A 'Connect {tool['title']}' button is shown to the user under your reply; "
                    "once they connect, they can send the request again."
                ).strip()
            logger.info(f"🚀 setup_composio_service({tool['name']}): connected={connected}")
            return json.dumps(result)
        except Exception as e:
            logger.error(f"❌ setup_composio_service failed: {e}", exc_info=True)
            return json.dumps({"error": "Setup failed", "message": str(e), "service": service_name})

    async def select_additional_actions(query: str, required_service: str, task_description: str) -> str:
        """Enable more actions for an app that is already connected, when the tools you have
        for it can't do what the user asked.

        Args:
            query (str): The user's request, verbatim.
            required_service (str): App key, e.g. "gmail", "slack".
            task_description (str): Short description of what needs doing.

        Returns:
            str: JSON describing which actions were enabled or disabled.
        """
        try:
            result = await smart_select_actions(organization_id, user_id, query, required_service, task_description)
            if result.get("added_actions"):
                result["message"] = f"{result['message']} They are usable from the user's next message."
            return json.dumps(result)
        except Exception as e:
            logger.error(f"❌ select_additional_actions failed: {e}", exc_info=True)
            return json.dumps({"success": False, "error": "Selection failed", "message": str(e)})

    return [setup_composio_service, select_additional_actions]


def composio_setup_instructions(connected_apps: list[str], supported: list[str]) -> str:
    connected = ", ".join(connected_apps) if connected_apps else "none yet"
    return f"""<composio_setup_workflow>
The user can connect third-party apps. Supported app keys: {", ".join(supported)}.
Apps with tools available to you right now: {connected}.

When the user wants to DO something in an app (send/draft/reply to email, schedule a meeting, post to Slack,
create/update/close a Jira issue, create a Notion page, …) or read their own data there (their inbox, calendar,
issues) and you do NOT have that app's tools, call setup_composio_service(service_name, query, task_description):
  - query = the user's request verbatim; task_description = a short summary, e.g. "send an email".
  - It enables the right actions and tells you whether the app is connected.
  - If needs_auth is true: tell the user in one sentence that they need to connect <App> using the button below,
    then ask again. NEVER print any link or URL yourself — the interface shows the Connect button.
  - If already_connected is true: tell the user <App> is ready and to send their request again (new actions are
    available from their next message).

If you DO have the app's tools but none of them can do what was asked, call select_additional_actions and tell the
user to send the request again.

Infer the app from the request: "send email" → gmail, "schedule a meeting" → googlecalendar, "post in #general" →
slack, "close PROJ-12" → jira. Questions about uploaded documents go to the knowledge base, not these tools.
</composio_setup_workflow>"""
