"""Editing a document spec: the operations, applied in order, on the pod.

A document is edited by naming blocks, not by resending it. The model that wrote a
twelve-section report should be able to say "replace the chart in b14 with a line chart"
without reproducing eleven sections it is not changing — reproducing them is how a small
correction turns into a full rewrite, a full rewrite is how a detail gets silently dropped,
and both cost a turn.

Every operation names existing content by id. Ids are minted once and never renumbered, so
`b7` still means the same block after three inserts above it.

Applied here rather than in the sandbox because this is where validation already lives: an
op that names a block that does not exist should fail before a sandbox is even woken.
"""

from __future__ import annotations

from typing import Any, Dict, List

from docgen.spec import Block, DocumentSpec, Slide

OPS = ("insert", "replace", "update", "delete", "move", "set", "insert_slide", "delete_slide")

# Document-level fields an edit may set. Not `content` — that is what the block ops are
# for, and allowing it here would make "set" a silent whole-document replace.
SETTABLE = ("title", "subtitle", "footer", "brand", "filename")


class OpError(ValueError):
    """An operation that cannot be applied, phrased so the model can fix it."""


def _require(op: Dict[str, Any], *names: str) -> List[Any]:
    # Presence, not truth: `{"op":"set","path":"footer","value":""}` clears the footer, and
    # a falsiness check would reject it as missing the one thing the edit is for.
    missing = [n for n in names if op.get(n) is None]
    if missing:
        raise OpError(f"{op.get('op')} needs {', '.join(missing)}")
    return [op[n] for n in names]


def _locate(spec: DocumentSpec, block_id: str):
    item, container = spec.find(block_id)
    if item is None:
        known = ", ".join(b.id for b in spec._every_block() if getattr(b, "id", None))
        raise OpError(f"no block {block_id!r} in this document; ids are: {known or 'none'}")
    return item, container


def _mint(spec: DocumentSpec, raw: Dict[str, Any], kind: str):
    """Build a Block or Slide from raw JSON, giving it a fresh id.

    An id supplied by the model is discarded: ids are the store's to assign, and a
    hand-written one could collide with a block that already exists.
    """
    raw = {k: v for k, v in dict(raw).items() if k != "id"}
    made = Slide(**raw) if kind == "slide" else Block(**raw)
    prefix = "s" if kind == "slide" else "b"
    made.id, spec.next_id = f"{prefix}{spec.next_id}", spec.next_id + 1
    if isinstance(made, Slide):
        for block in made.blocks:
            block.id, spec.next_id = f"b{spec.next_id}", spec.next_id + 1
    return made


def apply(spec: DocumentSpec, ops: List[Dict[str, Any]]) -> tuple[DocumentSpec, List[str]]:
    """Apply `ops` to `spec` in order, returning the new spec and a note per operation.

    Order matters and is the caller's: `delete b7` then `insert after b6` means something
    different from the reverse. Anything that fails raises, and the caller rebuilds nothing
    — a half-applied edit is worse than a rejected one.
    """
    if not isinstance(ops, list) or not ops:
        raise OpError("edit needs a non-empty list of ops")

    notes: List[str] = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise OpError(f"ops[{i}] must be an object")
        kind = op.get("op")
        if kind not in OPS:
            raise OpError(f"ops[{i}]: unknown op {kind!r}; use one of {', '.join(OPS)}")
        try:
            notes.append(_ONE[kind](spec, op))
        except OpError as exc:
            raise OpError(f"ops[{i}] ({kind}): {exc}") from None

    spec.assign_ids()
    return spec, notes


def _insert(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    (blocks,) = _require(op, "blocks")
    if not isinstance(blocks, list) or not blocks:
        raise OpError("blocks must be a non-empty list")

    after = op.get("after")
    if after in (None, "", "end", "start"):
        container = spec.content
        at = 0 if after == "start" else len(container)
    else:
        anchor, container = _locate(spec, str(after))
        at = container.index(anchor) + 1

    # A slide's blocks hold blocks; the document's content holds slides for a deck.
    kind = "slide" if (spec.format == "pptx" and container is spec.content) else "block"
    made = [_mint(spec, b, kind) for b in blocks]
    container[at:at] = made
    return f"inserted {', '.join(m.id for m in made)}"


def _replace(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    block_id, new = _require(op, "id", "block")
    old, container = _locate(spec, str(block_id))
    kind = "slide" if isinstance(old, Slide) else "block"
    made = _mint(spec, new, kind)
    # The id is kept, so anything else in the edit that names it still works. The id minted
    # for `made` is simply spent — ids are monotonic and a gap costs nothing, where reusing
    # one risks two blocks answering to the same name.
    made.id = old.id
    container[container.index(old)] = made
    return f"replaced {old.id}"


def _update(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    block_id, changes = _require(op, "id", "set")
    if not isinstance(changes, dict) or not changes:
        raise OpError("set must be a non-empty object of fields to change")
    target, _ = _locate(spec, str(block_id))

    # A shallow merge, deliberately: "set text" should not require resending the chart's
    # categories, and a deep merge into a list is ambiguous (append or replace?) in a way
    # that would guess wrong half the time. To change a list, send the whole list.
    raw = target.model_dump(exclude_none=True)
    raw.update({k: v for k, v in changes.items() if k != "id"})
    rebuilt = (Slide if isinstance(target, Slide) else Block)(**raw)
    rebuilt.id = target.id
    container = spec.find(target.id)[1]
    container[container.index(target)] = rebuilt
    return f"updated {target.id} ({', '.join(sorted(changes))})"


def _delete(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    ids = op.get("ids") or ([op["id"]] if op.get("id") else None)
    if not ids:
        raise OpError("delete needs ids")
    for block_id in ids:
        target, container = _locate(spec, str(block_id))
        container.remove(target)
    if not spec.content:
        raise OpError("that would delete every block; a document needs content")
    return f"deleted {', '.join(str(i) for i in ids)}"


def _move(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    (block_id,) = _require(op, "id")
    target, container = _locate(spec, str(block_id))
    after = op.get("after")
    container.remove(target)
    if after in (None, "", "end"):
        container.append(target)
    elif after == "start":
        container.insert(0, target)
    else:
        anchor, anchor_container = _locate(spec, str(after))
        if anchor_container is not container:
            raise OpError(f"{block_id} and {after} are not in the same slide or document")
        anchor_container.insert(anchor_container.index(anchor) + 1, target)
    return f"moved {block_id} after {after or 'end'}"


def _set(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    path, value = _require(op, "path", "value")
    if path not in SETTABLE:
        raise OpError(f"cannot set {path!r}; settable: {', '.join(SETTABLE)}. "
                      "Use insert/replace/update/delete to change content.")
    setattr(spec, str(path), value)
    return f"set {path}"


def _insert_slide(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    if spec.format != "pptx":
        raise OpError("insert_slide is only for decks; use insert")
    (slide,) = _require(op, "slide")
    return _insert(spec, {"op": "insert", "after": op.get("after"), "blocks": [slide]})


def _delete_slide(spec: DocumentSpec, op: Dict[str, Any]) -> str:
    if spec.format != "pptx":
        raise OpError("delete_slide is only for decks; use delete")
    return _delete(spec, {"op": "delete", "ids": op.get("ids") or [op.get("id")]})


_ONE = {
    "insert": _insert, "replace": _replace, "update": _update, "delete": _delete,
    "move": _move, "set": _set, "insert_slide": _insert_slide, "delete_slide": _delete_slide,
}
