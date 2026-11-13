"""Registry of OSINT tools.

Each tool module decorates its functions with @osint_tool. The registry knows
each tool's group, tier and required server settings, so a tool whose API key
is missing is simply not offered to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from app.settings import settings


@dataclass(frozen=True)
class OsintTool:
    name: str
    fn: Callable
    group: str
    tier: int
    requires: tuple[str, ...] = field(default_factory=tuple)
    summary: str = ""

    @property
    def missing_keys(self) -> list[str]:
        return [k for k in self.requires if not getattr(settings, k, "")]

    @property
    def enabled(self) -> bool:
        return not self.missing_keys


_TOOLS: dict[str, OsintTool] = {}


def osint_tool(group: str, tier: int = 1, requires: Iterable[str] = (), summary: str = ""):
    def deco(fn: Callable) -> Callable:
        doc = (fn.__doc__ or "").strip().splitlines()
        _TOOLS[fn.__name__] = OsintTool(
            name=fn.__name__,
            fn=fn,
            group=group,
            tier=tier,
            requires=tuple(requires),
            summary=summary or (doc[0] if doc else ""),
        )
        return fn

    return deco


def _load() -> None:
    # Importing the modules registers their tools.
    from osint.tools import (  # noqa: F401
        conflict,
        country,
        cyber,
        hazards,
        history,
        humanitarian,
        infrastructure,
        military,
        news,
        social,
    )


_loaded = False


def all_tools() -> dict[str, OsintTool]:
    global _loaded
    if not _loaded:
        _load()
        _loaded = True
    return dict(_TOOLS)


def get_osint_tools(tiers: Iterable[int] = (1, 2), groups: Optional[Iterable[str]] = None) -> list[Callable]:
    """Enabled tool functions for the agent, filtered by tier and group."""
    tiers = set(tiers)
    groups = set(groups) if groups else None
    return [
        t.fn
        for t in all_tools().values()
        if t.enabled and t.tier in tiers and (groups is None or t.group in groups)
    ]


def catalog() -> list[dict]:
    """A description of every tool, enabled or not (for the future search tool)."""
    return [
        {
            "name": t.name,
            "group": t.group,
            "tier": t.tier,
            "summary": t.summary,
            "enabled": t.enabled,
            "missing_keys": t.missing_keys,
        }
        for t in sorted(all_tools().values(), key=lambda x: (x.tier, x.group, x.name))
    ]
