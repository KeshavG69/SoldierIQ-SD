"""Build one document from a JSON spec, inside the sandbox, and verify it there.

The model used to write 50-200 lines of Python per document and call the docgen builders
itself. docgen was already the component library — Python was merely the transport, and a
lossy one: a measured QA run spent 21 code calls and 19 minutes on a PDF that never
arrived, because each syntax slip or verification finding cost another turn of code
writing. This runner takes a JSON spec instead, so one tool call produces the file.

Dispatch is driven by `inspect.signature` rather than a hand-written table per format. The
first version of this file carried that table and was wrong for three of the four formats
— `Deck(path, title=, subtitle=)` and `Book(path, title=)` are TypeErrors, because a deck's
title is a cover slide and a workbook has none. The builders are the only honest record of
what each block accepts, so they are consulted directly: a kwarg the method does not take
is dropped with a warning instead of raising, so one stray field never costs the document.

Reads a spec file, builds it, runs the layout checks on the result (pdfplumber and
LibreOffice are both in this image, so the rendered pass is real for docx and pptx too),
and prints the same `@@PRICEIQ_RESULT@@` envelope runner.py uses, with `document`,
`verification` and `warnings` added.

Stdlib + docgen only, run as `python3 docgen_build.py <spec.json>`; no pydantic here — the
spec is validated on the pod before it is written, and a second model of the same shape in
two places is two things to keep in step.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import time
import traceback
from pathlib import Path

RESULT_MARKER = "@@PRICEIQ_RESULT@@"
OUT_DIR = Path(os.environ.get("PRICEIQ_OUT_DIR", "/home/user/out"))

# Blocks whose payload is a single string the spec calls `text`, by far the common case.
_TEXT_BLOCKS = {"h1", "h2", "h3", "body", "caption", "section", "title"}

# The four builders disagree about chart kinds: reportlab draws bar/line/donut, pptx and
# openpyxl also answer to column/pie. A spec that says "column" should get a column chart
# everywhere rather than a LayoutError on PDF, so the synonym is resolved per target.
_CHART_ALIASES = {"column": "bar", "pie": "donut"}

# Public builder methods that are lifecycle, not content: the runner calls these itself.
_NOT_BLOCKS = {"save", "close", "slide", "verify", "remaining_in", "notes"}


def _emit(payload: dict) -> int:
    print(RESULT_MARKER + json.dumps(payload, default=str))
    return 0 if payload.get("ok") else 1


def _accepts(method) -> tuple[set[str], bool]:
    """Parameter names of `method`, and whether it takes **kwargs (then nothing is dropped)."""
    try:
        params = inspect.signature(method).parameters
    except (TypeError, ValueError):  # a C-implemented or otherwise unintrospectable callable
        return set(), True
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return set(params), True
    return {n for n, p in params.items() if p.kind is not inspect.Parameter.VAR_POSITIONAL}, False


def _apply(target, block: dict, warnings: list[dict], *, where: str = "") -> None:
    """Call the builder method named by `block["type"]` with the block's own fields.

    The spec's block types ARE the builder's method names on purpose: a new docgen method
    becomes available to the model the moment it exists, with no table to update here.
    """
    kind = block.get("type")
    if not kind or not isinstance(kind, str) or kind.startswith("_"):
        raise ValueError(f"block needs a public 'type', got {kind!r}")
    if kind in _NOT_BLOCKS:
        raise ValueError(f"{kind!r} is a builder method, not a block type")

    method = getattr(target, kind, None)
    if method is None or not callable(method):
        raise ValueError(
            f"{type(target).__name__} has no block type {kind!r}; available: "
            + ", ".join(sorted(n for n in dir(target) if not n.startswith('_')
                               and callable(getattr(target, n, None))))
        )

    # `id` is the editing handle (see the document tool); it is spec metadata, not a kwarg.
    fields = {k: v for k, v in block.items() if k not in ("type", "id")}
    accepted, takes_kwargs = _accepts(method)

    if not takes_kwargs:
        dropped = sorted(set(fields) - accepted)
        for name in dropped:
            warnings.append({"code": "block.field_ignored", "where": where or kind,
                             "detail": f"{type(target).__name__}.{kind} has no {name!r}"})
            fields.pop(name)

    if kind in _TEXT_BLOCKS and "text" in accepted:
        fields.setdefault("text", "")

    # Everything goes by keyword. Every docgen parameter is POSITIONAL_OR_KEYWORD, so this
    # needs no per-method knowledge of argument order — and it keeps `kind` in `fields`,
    # which the chart-alias retry below reads. Only a genuinely positional-only parameter
    # is passed positionally, and docgen has none today.
    args: list = []
    try:
        for name, param in inspect.signature(method).parameters.items():
            if param.kind is inspect.Parameter.POSITIONAL_ONLY and name in fields:
                args.append(fields.pop(name))
    except (TypeError, ValueError):
        pass

    try:
        method(*args, **fields)
    except (ValueError, TypeError) as exc:
        # The four builders disagree about chart kinds — reportlab draws bar/line/donut,
        # pptx and openpyxl also answer to column/pie. A spec saying "column" should get a
        # column chart everywhere rather than failing on PDF alone, so the synonym is tried
        # only after the builder itself has said it does not know the name. Asking the
        # builder beats a table here: it stays right when docgen grows a kind.
        alias = _CHART_ALIASES.get(fields.get("kind")) if kind == "chart" else None
        if not alias or "chart kind" not in str(exc):
            raise
        warnings.append({"code": "chart.kind_aliased", "where": where or kind,
                         "detail": f"{fields['kind']} -> {alias} for {type(target).__name__}"})
        fields["kind"] = alias
        method(*args, **fields)


def _blocks(spec: dict) -> list:
    content = spec.get("content") or []
    if not isinstance(content, list):
        raise ValueError("spec 'content' must be a list of blocks")
    return content


def _build_pdf(spec: dict, path: Path, warnings: list[dict]):
    from docgen.pdf import Report

    doc = Report(str(path), title=spec.get("title", ""), subtitle=spec.get("subtitle", ""),
                 footer=spec.get("footer", ""))
    for i, block in enumerate(_blocks(spec)):
        _apply(doc, block, warnings, where=f"content[{i}]")
    return doc.save()


def _build_docx(spec: dict, path: Path, warnings: list[dict]):
    from docgen.word import Doc

    if spec.get("footer"):
        # Doc has no page furniture (cf. Report._furniture); saying so beats dropping it.
        warnings.append({"code": "footer.unsupported", "where": "footer",
                         "detail": "docx has no footer; the value was not applied"})
    doc = Doc(str(path), title=spec.get("title", ""), subtitle=spec.get("subtitle", ""))
    for i, block in enumerate(_blocks(spec)):
        _apply(doc, block, warnings, where=f"content[{i}]")
    return doc.save()


def _build_pptx(spec: dict, path: Path, warnings: list[dict]):
    from docgen.deck import Deck

    # A deck's title is a cover slide, not a constructor argument. If the spec gives a
    # title and no explicit cover, one is added, so `title` means the same thing in all
    # four formats from the model's side.
    deck = Deck(str(path), footer=spec.get("footer", ""))
    slides = _blocks(spec)
    if spec.get("title") and not any((s or {}).get("type") == "cover" for s in slides):
        deck.cover(spec["title"], spec.get("subtitle", ""))

    for i, slide_spec in enumerate(slides):
        where = f"content[{i}]"
        kind = (slide_spec or {}).get("type")
        if kind == "cover":
            deck.cover(slide_spec.get("title", ""), slide_spec.get("subtitle", ""),
                       meta=slide_spec.get("meta"), kicker=slide_spec.get("kicker", ""),
                       style=slide_spec.get("style", "dark"),
                       wordmark=slide_spec.get("wordmark", ""),
                       motif=slide_spec.get("motif", "circles"),
                       background=slide_spec.get("background"),
                       shapes=slide_spec.get("shapes"),
                       ink=slide_spec.get("ink"))
            continue
        if kind == "divider":
            deck.divider(slide_spec.get("title", ""), slide_spec.get("subtitle", ""),
                         number=slide_spec.get("number"))
            continue
        slide = deck.slide(slide_spec.get("title") or None)
        for j, block in enumerate(slide_spec.get("blocks") or []):
            _apply(slide, block, warnings, where=f"{where}.blocks[{j}]")
        if slide_spec.get("notes"):
            slide.notes(slide_spec["notes"])
    return deck.save()


def _build_xlsx(spec: dict, path: Path, warnings: list[dict]):
    from docgen.book import Book

    if spec.get("title") and not any((b or {}).get("type") == "summary" for b in _blocks(spec)):
        warnings.append({"code": "title.unsupported", "where": "title",
                         "detail": "a workbook has no title page; add a 'summary' block"})
    book = Book(str(path))
    for i, block in enumerate(_blocks(spec)):
        where = f"content[{i}]"
        block = dict(block or {})
        # Book.chart and Book.data_bars take a live worksheet, which JSON cannot carry.
        # The spec names the sheet instead and it is resolved here.
        if block.get("type") in ("chart", "data_bars"):
            name = block.pop("sheet", None) or block.pop("ws", None)
            if name is None:
                raise ValueError(f"{block.get('type')!r} needs a 'sheet' naming the sheet "
                                 "it belongs to")
            try:
                block["ws"] = book.wb[str(name)[:31]]
            except KeyError:
                raise ValueError(
                    f"no sheet named {name!r}; sheets so far: {book.wb.sheetnames}"
                ) from None
        _apply(book, block, warnings, where=where)
    return book.save()


_BUILDERS = {"pdf": _build_pdf, "docx": _build_docx, "pptx": _build_pptx, "xlsx": _build_xlsx}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _emit({"ok": False, "error": {"type": "UsageError",
                                             "message": "usage: docgen_build.py <spec.json>"}})
    started = time.time()
    try:
        spec = json.loads(Path(argv[1]).read_text())
    except Exception as exc:  # noqa: BLE001
        return _emit({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)[:300]}})

    fmt = spec.get("format")
    builder = _BUILDERS.get(fmt)
    if builder is None:
        return _emit({"ok": False, "error": {
            "type": "ValueError",
            "message": f"unknown format {fmt!r}; use one of {sorted(_BUILDERS)}"}})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / Path(str(spec.get("filename") or f"document.{fmt}")).name

    warnings: list[dict] = []

    # The run's brand colours, applied to every builder that reads the active palette.
    brand = spec.get("brand")
    if brand:
        try:
            from docgen.palette import use_brand

            use_brand(brand)
        except Exception as exc:  # noqa: BLE001 - a bad palette must not cost the document
            warnings.append({"code": "brand.ignored", "where": "brand",
                             "detail": f"{type(exc).__name__}: {str(exc)[:160]}"})

    try:
        saved = Path(builder(spec, path, warnings))
    except BaseException as exc:  # noqa: BLE001 - report, never crash
        tb = traceback.format_exc().strip().splitlines()
        return _emit({"ok": False, "elapsed_s": round(time.time() - started, 3),
                      "warnings": warnings,
                      "error": {"type": type(exc).__name__, "message": str(exc)[:600],
                                "traceback_tail": "\n".join(tb[-12:])}})

    try:
        from docgen.checks import run as verify

        report = verify(str(saved))
        verification = {
            "checked": report.checked,
            "skipped": report.skipped,
            "errors": [i.as_dict() for i in report.errors],
            "warnings": [i.as_dict() for i in report.warnings],
        }
    except Exception as exc:  # noqa: BLE001 - verification is advice; never withhold a file for it
        verification = {"checked": [], "skipped": [f"verification failed: {exc}"],
                        "errors": [], "warnings": []}

    size = saved.stat().st_size if saved.exists() else 0
    return _emit({
        "ok": size > 0,
        "elapsed_s": round(time.time() - started, 3),
        "document": {"path": str(saved), "size": size, "format": fmt},
        "verification": verification,
        "warnings": warnings,
        "error": None if size > 0 else {"type": "EmptyDocument",
                                        "message": "the builder produced no bytes"},
    })


if __name__ == "__main__":
    sys.exit(main(sys.argv))
