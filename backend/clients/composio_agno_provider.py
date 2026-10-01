"""
Composio -> Agno provider.

Composio's SDK hands tools to an agent framework through a "provider" that
wraps each Composio tool schema into that framework's tool type. There is no
official Agno provider for the composio version we pin, so this wraps every
Composio action (e.g. GMAIL_SEND_EMAIL) into an Agno Toolkit with a single
function whose signature mirrors the action's JSON schema. When the agent
calls it, we forward to Composio's execute (already bound to the user).

Ported from enterprise-fastapi/utils/composio_agno_provider.py, minus the
S3/SharePoint attachment rewriting that only applies there.
"""
from __future__ import annotations

import json
import typing as t
from inspect import Signature

from agno.tools.toolkit import Toolkit
from composio.core.provider import AgenticProvider, AgenticProviderExecuteFn
from composio.types import Tool
from composio.utils.shared import get_signature_format_from_schema_params
from pydantic import validate_call


def _strip_empty(params: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
    """LLMs love to pass "" / [] / {} for optional args; many Composio actions
    reject those, so drop them and let the action's defaults apply."""
    return {k: v for k, v in params.items() if v not in (None, "", [], {})}


_GCAL_EVENT_SLUGS = {
    "GOOGLECALENDAR_CREATE_EVENT",
    "GOOGLECALENDAR_UPDATE_EVENT",
    "GOOGLECALENDAR_PATCH_EVENT",
}
_GCAL_EVENT_TYPE_PROPS = {
    "focusTimeProperties": "focusTime",
    "outOfOfficeProperties": "outOfOffice",
    "workingLocationProperties": "workingLocation",
    "birthdayProperties": "birthday",
}
# Page-size style args where 0 means "none" to the API rather than "default".
_ZERO_MEANS_UNSET = (
    "categoryId", "category_id", "maxResults", "max_results", "top", "limit",
    "pageSize", "page_size", "perPage", "per_page",
)


def _sanitize_arguments(slug: str, params: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
    slug = (slug or "").upper()
    if slug in _GCAL_EVENT_SLUGS:
        # Google rejects type-specific property blocks unless eventType matches.
        event_type = params.get("eventType")
        for prop, required_type in _GCAL_EVENT_TYPE_PROPS.items():
            if prop in params and event_type != required_type:
                params.pop(prop, None)
        if params.get("create_meeting_room") is False:
            params.pop("create_meeting_room", None)
    for key in _ZERO_MEANS_UNSET:
        if params.get(key) in (0, "0"):
            params.pop(key, None)
    return params


# Tool results go straight into the model's context. Raw API payloads can be
# huge (20 Gmail messages with include_payload ≈ 340k chars / 85k tokens, which
# blew the LLM timeout), so trim them before the agent sees them.
_MAX_STRING_CHARS = 4_000
_MAX_RESULT_CHARS = 60_000


def _compact(value: t.Any) -> t.Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            # Gmail: `payload` is the raw MIME tree; `messageText` already holds
            # the decoded body, so the payload only adds noise.
            if k == "payload" and "messageText" in value:
                continue
            out[k] = _compact(v)
        return out
    if isinstance(value, list):
        return [_compact(v) for v in value]
    if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
        return value[:_MAX_STRING_CHARS] + f"… [truncated {len(value) - _MAX_STRING_CHARS} chars]"
    return value


_SCOPE_ERROR_MARKERS = (
    "insufficient authentication scopes", "insufficient scope", "insufficient permission",
    "access_token_scope_insufficient", "request had insufficient", "invalid oauth scope",
)


def _explain_permission_error(slug: str, result: t.Any) -> t.Any:
    """Provider said the connection lacks a permission (e.g. the user unticked
    it at Google's consent screen). Say so plainly — it is connected, just
    missing access — instead of passing through a raw 403 blob."""
    if not isinstance(result, dict) or result.get("successful", True):
        return result
    error = str(result.get("error") or "")
    lower = error.lower()
    if any(m in lower for m in _SCOPE_ERROR_MARKERS) or ("403" in lower and "scope" in lower):
        app = (slug or "").split("_")[0].title() or "this app"
        return {
            **result,
            "error": (
                f"{app} is connected but is missing the permission this action needs "
                f"(the user did not grant it). Ask the user to reconnect {app} from "
                f"Connectors and allow access. Details: {error[:300]}"
            ),
        }
    return result


def _serialize_result(result: t.Any) -> str:
    text = json.dumps(_compact(result), default=str)
    if len(text) > _MAX_RESULT_CHARS:
        text = (
            text[:_MAX_RESULT_CHARS]
            + f"… [result truncated: {len(text) - _MAX_RESULT_CHARS} more chars. "
            "Ask for fewer items or a narrower query to see the rest.]"
        )
    return text


class AgnoProvider(AgenticProvider[Toolkit, t.List[Toolkit]], name="agno"):

    def wrap_tool(self, tool: Tool, execute_tool: AgenticProviderExecuteFn) -> Toolkit:
        parameters: t.Dict[str, t.Any] = tool.input_parameters or {}
        params = get_signature_format_from_schema_params(
            schema_params=parameters, skip_default=self.skip_default
        )
        sig = Signature(parameters=params)
        annotations: t.Dict[str, t.Any] = {p.name: p.annotation for p in params}
        annotations["return"] = str

        @validate_call
        def function_template(*args: t.Any, **kwargs: t.Any) -> str:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = _sanitize_arguments(tool.slug, _strip_empty(dict(bound.arguments)))
            result = execute_tool(slug=tool.slug, arguments=arguments)
            return _serialize_result(_explain_permission_error(tool.slug, result))

        func: t.Any = function_template
        func.__signature__ = sig
        func.__annotations__ = annotations
        func.__name__ = tool.slug.lower()

        doc = [tool.description or "", "\nArgs:"]
        for name, info in (parameters.get("properties") or {}).items():
            doc.append(f"    {name} ({info.get('type', 'any')}): {info.get('description', '')}")
        doc.append("\nReturns:\n    str: JSON string with the action result")
        func.__doc__ = "\n".join(doc)

        toolkit = Toolkit(name=tool.slug)
        toolkit.register(func)
        return toolkit

    def wrap_tools(
        self, tools: t.Sequence[Tool], execute_tool: AgenticProviderExecuteFn
    ) -> t.List[Toolkit]:
        return [self.wrap_tool(tool, execute_tool) for tool in tools]


__all__ = ["AgnoProvider"]
