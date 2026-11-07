"""The document spec: what the model writes instead of Python, and what an edit edits.

The model used to write 50-200 lines of Python per document and call the docgen builders
itself. docgen was already the component library — Python was merely the transport, and a
lossy one: a measured QA run spent 21 code calls and 19 minutes on a PDF that never
arrived, because each syntax slip or layout finding cost another turn of code writing.

A spec is JSON, so a document survives the turn that made it. It is the identity of the
document: the file is derived from it and can always be rebuilt, in a different sandbox or
a week later, which is what makes editing possible at all.

Validation here is deliberately structural. It rejects what the sandbox cannot even attempt
— an unknown format, content that is not a list, a chart with no numbers — and allows
everything else through, because `sandbox/docgen_build.py` reads the builders' real
signatures and reports unknown fields as warnings. A strict model here would be a second
copy of every docgen signature, and the copy would be the one that went stale.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FORMATS = ("pdf", "docx", "pptx", "xlsx")
Format = Literal["pdf", "docx", "pptx", "xlsx"]

# Blocks that carry data rather than prose, and what they cannot do without.
_REQUIRED_FIELDS = {
    "chart": ("kind", "categories"),
    "table": ("headers", "rows"),
    "kpi_row": ("pairs",),
    "bullets": ("items",),
    "steps": ("items",),
    "timeline": ("items",),
    "sheet": ("name", "headers", "rows"),
    "summary": ("name", "title", "kpis"),
    "data_bars": ("sheet", "column"),
}

_MAX_BLOCKS = 400
_MAX_JSON_BYTES = 2_000_000


class Block(BaseModel):
    """One element of a document — a heading, a table, a chart.

    `type` is the docgen builder method to call, verbatim; the sandbox resolves it against
    the real class, so docgen growing a method makes it available here with no change.
    Extra fields are that method's keyword arguments and are passed straight through.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    id: Optional[str] = None

    @field_validator("type")
    @classmethod
    def _public_method_name(cls, value: str) -> str:
        value = (value or "").strip()
        if not value or value.startswith("_") or not value.replace("_", "").isalnum():
            raise ValueError(f"block type {value!r} is not a docgen block name")
        return value

    @model_validator(mode="after")
    def _has_what_it_needs(self) -> "Block":
        missing = [f for f in _REQUIRED_FIELDS.get(self.type, ())
                   if getattr(self, f, None) in (None, "", [], {})]
        if missing:
            raise ValueError(f"{self.type} block needs {', '.join(missing)}")
        if self.type == "chart":
            # A chart with no numbers is the single most common empty-document cause; it is
            # cheaper to say so here than to render an axis with nothing on it.
            series = getattr(self, "series", None) or getattr(self, "values", None)
            if series in (None, "", [], {}):
                raise ValueError("chart block needs series (or values, for xlsx)")
        return self

    def fields(self) -> Dict[str, Any]:
        """The block as the sandbox will see it — `id` is spec metadata, not a kwarg."""
        return {k: v for k, v in self.model_dump(exclude_none=True).items() if k != "id"}


class Slide(BaseModel):
    """One slide of a deck. `cover` and `divider` are whole-slide kinds; everything else is
    a titled slide holding blocks."""

    model_config = ConfigDict(extra="allow")

    type: Optional[str] = None
    id: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    notes: Optional[str] = None
    blocks: List[Block] = Field(default_factory=list)

    @model_validator(mode="after")
    def _says_something(self) -> "Slide":
        if self.type in ("cover", "divider"):
            if not (self.title or self.subtitle):
                raise ValueError(f"a {self.type} slide needs a title")
            return self
        if not self.title and not self.blocks:
            raise ValueError("a slide needs a title or at least one block")
        return self


class DocumentSpec(BaseModel):
    """A whole document. `content` is blocks for pdf/docx/xlsx and slides for pptx."""

    model_config = ConfigDict(extra="allow")

    format: Format
    filename: str
    title: str = ""
    subtitle: str = ""
    footer: str = ""
    brand: Optional[Dict[str, str]] = None
    content: List[Any] = Field(default_factory=list)
    # Assigned by the store, never by the model: the next free block id for this document.
    next_id: int = 1

    @field_validator("filename")
    @classmethod
    def _bare_name(cls, value: str) -> str:
        # A path here would write outside the output directory the sandbox diffs; only the
        # last component is ever meaningful.
        name = (value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
        if not name or name in (".", ".."):
            raise ValueError("filename must be a plain file name")
        return name

    @model_validator(mode="after")
    def _shaped_for_its_format(self) -> "DocumentSpec":
        if not self.filename.lower().endswith(f".{self.format}"):
            self.filename = f"{self.filename.rsplit('.', 1)[0]}.{self.format}"
        if len(self.content) > _MAX_BLOCKS:
            raise ValueError(f"a document is capped at {_MAX_BLOCKS} blocks; "
                             f"this one has {len(self.content)}")
        if not self.content:
            raise ValueError("a document needs content")

        parsed: List[Any] = []
        for i, item in enumerate(self.content):
            if not isinstance(item, (dict, BaseModel)):
                raise ValueError(f"content[{i}] must be an object, got {type(item).__name__}")
            raw = item if isinstance(item, dict) else item.model_dump()
            try:
                parsed.append(Slide(**raw) if self.format == "pptx" else Block(**raw))
            except ValueError as exc:
                raise ValueError(f"content[{i}]: {exc}") from None
        self.content = parsed
        return self

    # ── identity and serialisation ───────────────────────────────────────────

    def payload(self) -> Dict[str, Any]:
        """What gets written to the sandbox as the spec file."""
        data = self.model_dump(exclude_none=True, exclude={"next_id"})
        data["content"] = [
            item.model_dump(exclude_none=True) if isinstance(item, BaseModel) else item
            for item in self.content
        ]
        return data

    def as_json(self) -> str:
        text = json.dumps(self.payload(), default=str)
        if len(text.encode()) > _MAX_JSON_BYTES:
            raise ValueError("the spec is too large to build; split the document")
        return text

    def sha(self) -> str:
        return hashlib.sha256(
            json.dumps(self.payload(), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    # ── ids ──────────────────────────────────────────────────────────────────

    def assign_ids(self) -> "DocumentSpec":
        """Give every block a stable id, minting only what is missing.

        Ids are never reused or renumbered: they are how an edit names the block it means,
        so `b7` has to survive an insert above it. They live in the spec, so a rebuild —
        even in a fresh sandbox — keeps them.
        """
        used = {b.id for b in self._every_block() if b.id}
        for item in self.content:
            if isinstance(item, Slide):
                if not item.id or item.id in used - {item.id}:
                    item.id, self.next_id = f"s{self.next_id}", self.next_id + 1
                for block in item.blocks:
                    if not block.id:
                        block.id, self.next_id = f"b{self.next_id}", self.next_id + 1
            elif isinstance(item, Block) and not item.id:
                item.id, self.next_id = f"b{self.next_id}", self.next_id + 1
        return self

    def _every_block(self) -> Iterable[BaseModel]:
        for item in self.content:
            yield item
            if isinstance(item, Slide):
                yield from item.blocks

    def find(self, block_id: str):
        """The block or slide with this id, and the list it lives in, or (None, None)."""
        for item in self.content:
            if getattr(item, "id", None) == block_id:
                return item, self.content
            if isinstance(item, Slide):
                for block in item.blocks:
                    if block.id == block_id:
                        return block, item.blocks
        return None, None

    # ── what the model reads back ────────────────────────────────────────────

    def outline(self) -> List[str]:
        """One line per block, not the spec.

        A 30-block spec is 3-5k tokens; this is about 400. The model needs to know what is
        in the document and how to name it, not to re-read every string it just wrote — and
        `show` fetches the full block when it really does.
        """
        lines: List[str] = []
        for item in self.content:
            if isinstance(item, Slide):
                kind = item.type or "slide"
                lines.append(f"{item.id} {kind} {_clip(item.title or '')}".rstrip())
                lines += [f"  {_summarise(b)}" for b in item.blocks]
            else:
                lines.append(_summarise(item))
        return lines


def _clip(text: str, width: int = 60) -> str:
    text = " ".join(str(text).split())
    return f'"{text[:width]}…"' if len(text) > width else (f'"{text}"' if text else "")


def _summarise(block: Block) -> str:
    """`b7 chart bar "Deals by stage" 3 pts` — enough to decide what to edit."""
    extra = ""
    data = block.model_dump(exclude_none=True)
    if block.type == "chart":
        series = data.get("series") or data.get("values") or []
        n = len(series[0]) if series and isinstance(series[0], (list, tuple)) else len(series)
        extra = f"{data.get('kind', '')} {_clip(data.get('title', ''))} {n} pts"
    elif block.type == "table":
        extra = f"{len(data.get('rows') or [])}x{len(data.get('headers') or [])} " \
                f"[{', '.join(str(h) for h in (data.get('headers') or [])[:4])}]"
    elif block.type in ("bullets", "steps", "timeline", "kpi_row", "options", "columns"):
        items = data.get("items") or data.get("pairs") or []
        extra = f"{len(items)} items"
    elif block.type == "sheet":
        extra = f"{data.get('name', '')} {len(data.get('rows') or [])}x" \
                f"{len(data.get('headers') or [])}"
    else:
        extra = _clip(data.get("text", ""))
    return f"{block.id or '-'} {block.type} {extra}".rstrip()
