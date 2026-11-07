"""`build_document` — one tool call produces a delivered, editable document.

Ported from PriceIQ (itself ported from Kroolo's enterprise-fastapi). It replaces the model writing 50-200
lines of reportlab / python-pptx code per document, running it, and then
calling s3_upload_tool: every syntax slip and layout problem cost another turn.

  * A JSON spec, not code. docgen (backend/docgen) is the component library;
    the spec names its blocks, so there is no NameError to debug.
  * Build and deliver in ONE call. The built file is uploaded to iDrive E2
    (chat-documents/<org>/<session>/…) and a presigned download link is in this
    tool's result.
  * The spec is kept (utils/docgen_store.py), so the next instruction can be
    "make the chart a line chart" — an edit by block id, not a rewrite.

The build runs in the session's E2B sandbox (sandbox/docgen_build.py) and is
checked there (overflow, blank pages, margins). Findings come back with the
link as advice; a finished document is never withheld over them.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import mimetypes
import shlex
import time
import uuid
from typing import Any, Dict, List, Optional

from agno.tools import tool
from e2b.sandbox.commands.command_handle import CommandExitException

from app.logger import logger
from app.settings import settings
from clients.idrivee2_client import get_idrivee2_client
from docgen import ops as doc_ops
from docgen.spec import DocumentSpec
from utils import docgen_store
from utils.sandbox_context import get_session_context, sandbox_for_this_session

# Every built document is stored under this prefix, scoped to the org. The download
# endpoint (routers/chat.py) refuses keys outside the caller's own org prefix.
DOCUMENT_KEY_PREFIX = "chat-documents"

_SPEC_DIR = "/home/user/specs"
_RESULT_MARKER = "@@PRICEIQ_RESULT@@"
# A deck conversion through LibreOffice is the slow case at ~7s cold.
_BUILD_TIMEOUT_S = 180

# Two builds in one session must not run at once: soffice shares one profile.
_locks: Dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    if len(_locks) > 512:
        _locks.clear()
    return _locks.setdefault(session_id, asyncio.Lock())


def _slugify(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].strip().lower()
    slug = "".join(c if c.isalnum() else "-" for c in stem).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:48] or "document"


class _TemplateMissingLibraries(RuntimeError):
    pass


async def _run_build(sbx, runtime, spec: DocumentSpec, slug: str) -> Dict[str, Any]:
    """Write the spec into the sandbox, build it there, and return the runner's envelope."""
    spec_path = f"{_SPEC_DIR}/{slug}.json"
    await sbx.files.write(spec_path, spec.as_json())
    started = time.monotonic()
    try:
        result = await sbx.commands.run(
            f"{runtime.python} {runtime.docgen_build} {spec_path}", timeout=_BUILD_TIMEOUT_S
        )
    except CommandExitException as exited:
        # The runner exits 1 on a failed build; its envelope is still on stdout.
        result = exited
    line = next((l for l in (result.stdout or "").splitlines()
                 if l.startswith(_RESULT_MARKER)), None)
    if line is None:
        tail = ((result.stderr or result.stdout or "")[-600:]).strip()
        if "ModuleNotFoundError" in tail:
            raise _TemplateMissingLibraries(tail)
        raise RuntimeError(f"the document builder produced no result in the sandbox: {tail}")
    envelope = json.loads(line[len(_RESULT_MARKER):])
    error = envelope.get("error") or {}
    if not envelope.get("ok") and error.get("type") == "ModuleNotFoundError":
        raise _TemplateMissingLibraries(error.get("message", ""))
    envelope["wall_s"] = round(time.monotonic() - started, 2)
    return envelope


async def _deliver(sbx, path: str, filename: str) -> Dict[str, Any]:
    """Pull the built file out of the sandbox, upload it to iDrive E2, return a download link."""
    from utils.e2b_sandbox import session_storage_id

    file_bytes = bytes(await sbx.files.read(path, format="bytes"))
    if not file_bytes:
        raise RuntimeError(f"the builder wrote an empty file at {path}")
    ctx = get_session_context()
    object_key = (f"{DOCUMENT_KEY_PREFIX}/{ctx['org_id']}/{session_storage_id(ctx['session_id'])}/"
                  f"{uuid.uuid4().hex[:12]}_{filename}")
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    storage = get_idrivee2_client()
    await storage.upload_file(io.BytesIO(file_bytes), object_key, content_type=content_type)
    url = await storage.generate_presigned_url(
        object_key, expiration=settings.CHAT_DOCUMENT_URL_TTL_S, download_filename=filename)
    return {"url": url, "object_key": object_key, "filename": filename,
            "size_bytes": len(file_bytes),
            "file_sha": hashlib.sha256(file_bytes).hexdigest()[:16]}


_PREVIEW_DIR = "/home/user/out/.preview"
_PREVIEW_TIMEOUT_S = 120


async def _deliver_preview(sbx, runtime, path: str, object_key: str) -> Optional[str]:
    """A PDF rendering of a docx / pptx / xlsx for the chat's preview pane.

    LibreOffice is already in the sandbox (docgen's layout checks use it), so the file
    is converted next to where it was built and the PDF is stored beside the original
    as `<object_key>.preview.pdf`. Best effort: a failed conversion only means the
    pane offers Download instead of a preview, so it never fails the build.
    """
    try:
        script = (f"from docgen import soffice; "
                  f"print(soffice.to_pdf({path!r}, {_PREVIEW_DIR!r}))")
        result = await sbx.commands.run(
            f"cd {shlex.quote(runtime.root)} && {runtime.python} -c {shlex.quote(script)}",
            timeout=_PREVIEW_TIMEOUT_S)
        pdf_path = (result.stdout or "").strip().splitlines()[-1]
        data = bytes(await sbx.files.read(pdf_path, format="bytes"))
        if not data:
            return None
        preview_key = f"{object_key}.preview.pdf"
        await get_idrivee2_client().upload_file(
            io.BytesIO(data), preview_key, content_type="application/pdf")
        return preview_key
    except Exception as exc:  # noqa: BLE001 - the document itself is already delivered
        logger.warning(f"[docgen] preview conversion failed for {path}: {exc}")
        return None


def _error_keys(envelope: Dict[str, Any]) -> List[str]:
    verification = envelope.get("verification") or {}
    return sorted({f"{e.get('code')}@{e.get('where')}" for e in verification.get("errors") or []})


def _findings(envelope: Dict[str, Any], previous_errors: Optional[List[str]] = None) -> Dict[str, Any]:
    """Layout findings, phrased so the model fixes what it can and stops on what it can't.

    Warnings are information; errors are a request for one edit; an error that
    survives an edit is declared out of reach, which ends rebuild loops.
    """
    verification = envelope.get("verification") or {}
    errors = verification.get("errors") or []
    warnings = (verification.get("warnings") or []) + (envelope.get("warnings") or [])
    out: Dict[str, Any] = {}
    if warnings:
        out["layout_warnings"] = warnings[:6]
    if not errors:
        if warnings:
            out["fix_note"] = ("Warnings only. The document is fine to deliver as it is — do "
                               "not rebuild or edit it for these.")
        return out

    out["layout_errors"] = errors[:8]
    persisted = sorted(set(_error_keys(envelope)) & set(previous_errors or []))
    if persisted:
        out["fix_note"] = (
            "These errors were ALSO present before your last change, so another edit will "
            "not fix them — they come from the renderer, not your content. Stop editing for "
            "them. The document is already delivered. Persisting: " + ", ".join(persisted[:5]))
    else:
        out["fix_note"] = (
            "The document is already delivered. If one of these errors changes what the "
            "reader sees, fix it with ONE build_document(action='edit') naming the block id "
            "— not by re-creating the document. If it persists after that edit, stop.")
    return out


async def _build_store_and_deliver(
    session_id: str, spec: DocumentSpec, slug: str, *, label: str, base_version: Optional[int],
) -> Dict[str, Any]:
    spec.assign_ids()
    try:
        prior = await docgen_store.get(session_id, slug)
    except docgen_store.UnknownDocument:
        prior = None

    async with _session_lock(session_id):
        from utils.docgen_runtime import ensure_docgen_ready

        sbx = await sandbox_for_this_session()
        runtime = await ensure_docgen_ready(sbx)
        envelope = await _run_build(sbx, runtime, spec, slug)

        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            return {
                "success": False,
                "slug": slug,
                "error": f"{error.get('type', 'BuildError')}: {error.get('message', '')}",
                "detail": error.get("traceback_tail"),
                "warnings": envelope.get("warnings") or [],
                "note": "The spec was rejected by the builder. Fix the block it names and "
                        "call build_document again; do not switch to writing Python.",
            }

        document = envelope.get("document") or {}
        delivery = await _deliver(sbx, document["path"], spec.filename)
        delivery["preview_key"] = (
            delivery["object_key"] if spec.format == "pdf"
            else await _deliver_preview(sbx, runtime, document["path"], delivery["object_key"]))
        entry = await docgen_store.save(
            session_id, slug, spec, label=label, base_version=base_version,
            link=delivery["url"], object_key=delivery["object_key"], file_sha=delivery["file_sha"],
            sandbox_id=getattr(sbx, "sandbox_id", None), errors=_error_keys(envelope),
        )

    logger.info(f"[docgen] {spec.format} {slug} v{entry['version']} built in "
                f"{envelope.get('wall_s', 0):.2f}s ({delivery['size_bytes']} bytes)")

    return {
        # url / filename / size_bytes are what the chat UI's download card reads.
        "success": True,
        "url": delivery["url"],
        "object_key": delivery["object_key"],
        # A PDF of the document for the chat's preview pane (None if it couldn't render).
        "preview_key": delivery["preview_key"],
        "filename": delivery["filename"],
        "size_bytes": delivery["size_bytes"],
        "slug": slug,
        "version": entry["version"],
        "format": spec.format,
        "build_s": envelope.get("wall_s"),
        "outline": spec.outline(),
        **_findings(envelope, (prior or {}).get("errors")),
        **({"replaced_version": prior["version"],
            "replaced_note": "A document with this name already existed, so this became its "
                             "next version. To change a delivered document, use "
                             "action='edit' — re-creating it rebuilds everything."}
           if prior and label == "created" else {}),
        "note": (
            "The document is delivered — the chat renders it as a download card, so do NOT "
            "paste the URL; just say briefly what the document contains. To change it, call "
            f"build_document(action='edit', slug='{slug}', base_version={entry['version']}, "
            "ops=[…]) with the block ids in `outline`. Rebuilding the whole spec to change one "
            "block wastes the turn."
        ),
    }


@tool(stop_after_tool_call=False)
async def build_document(
    action: str = "create",
    spec: Optional[Dict[str, Any]] = None,
    slug: str = "",
    ops: Optional[List[Dict[str, Any]]] = None,
    base_version: Optional[int] = None,
    label: str = "",
    ids: Optional[List[str]] = None,
    version: Optional[int] = None,
) -> str:
    """Build, edit and deliver a PDF, Word document, PowerPoint deck or Excel workbook.

    One call builds the file, checks its layout, uploads it and returns a download link.
    Use it whenever the user wants a file: reports, briefs, warning orders (WARNO),
    operations orders (OPORD), COA comparisons, decision matrices, slide decks, tables.
    The result stays editable in later turns. Every fact in a spec must come from
    search_knowledge_base, web search, or the user — never invent figures, names or
    doctrine; cite sources in the document (e.g. a "Sources" section or table column).

    Args:
        action: "create" a new document, "edit" an existing one, "show" blocks in full,
            "list" the documents in this conversation, "undo" the last edit, or "revert"
            to an earlier version.
        spec: For "create". `{format, filename, title, subtitle, footer, brand, content:[…]}`
            where `format` is pdf|docx|pptx|xlsx and `brand` is optional
            `{"primary":"#hex","secondary_1":"#hex"}`. `content` is a list of blocks —
            each `{"type": <block>, …its fields}`.
            PDF/DOCX blocks: cover (pdf only: kicker, style dark|minimal|editorial,
            meta {label: value}, wordmark), eyebrow (pdf), h1/h2/h3/body/caption {text},
            bullets {items}, steps {items}, kpi_row {pairs:[[value,label]]},
            columns {items:[[head,body]]}, timeline {items:[[label,head,body]]},
            fields {pairs:[[label,value]]}, quote {text, attribution},
            callout {text, tone info|good|warn|bad},
            table {headers, rows, align:[left|right|center|decimal]} (docx: widths),
            chart {kind bar|line|donut, categories, series (list, or list of lists),
            labels, title, x_title, y_title, value_format}, divider, page_break, spacer.
            PPTX: `content` is a list of slides — `{"type":"cover","title","subtitle",
            "kicker","style","meta":[[label,value]]}`, `{"type":"divider","title","number"}`,
            or `{"title":"…","blocks":[…],"notes":"…"}` with slide blocks section, body,
            caption, bullets, kpi_row, columns, card, callout, timeline, steps, quote,
            table, chart {kind bar|column|line|pie|donut, categories, series, x_title,
            y_title} (no chart title on slides). Too much on one slide fails — split it.
            XLSX: summary {name, title, kpis:[[value,label]], notes}, sheet {name, headers,
            rows, formats {header: currency|currency_cents|percent|integer|decimal|date|
            text}}, data_bars {sheet, column}, chart {sheet, kind, categories:"A",
            values:"C" or ["C","D"], title}. Numbers are JSON numbers, percentages are
            fractions, and a sheet must come before a chart that names it.
            Example: {"format":"pdf","filename":"coa-comparison.pdf","title":"COA Comparison",
            "content":[{"type":"h1","text":"Recommendation"},{"type":"callout","text":
            "COA 2 is recommended: lowest risk with equal speed.","tone":"good"},
            {"type":"table","headers":["Criterion","Weight","COA 1","COA 2"],"rows":
            [["Speed","3","2","2"],["Risk","2","1","3"]],"align":["left","right","right",
            "right"]},{"type":"h2","text":"Sources"},{"type":"bullets","items":
            ["<source document name> (as returned by search)","<web page title + url>"]}]}
        slug: Which document to act on — returned by "create", shown by "list".
        ops: For "edit". A list applied in order, each naming a block id from `outline`:
            `{"op":"update","id":"b7","set":{"text":"…"}}`,
            `{"op":"replace","id":"b7","block":{…}}`,
            `{"op":"insert","after":"b7","blocks":[{…}]}` (`after` may be "start"/"end"),
            `{"op":"delete","ids":["b7"]}`, `{"op":"move","id":"b7","after":"b2"}`,
            `{"op":"set","path":"title","value":"…"}`.
        base_version: For "edit" — the `version` from the last result for this document.
        label: A short note for this version, so "before the chart change" can be found.
        ids: For "show" — the block ids to expand; omit for the whole spec.
        version: For "revert" — which version to go back to.
    """
    # Returned as JSON text: agno would str() a dict (Python repr), which the chat UI
    # cannot parse to show the download card.
    result = await _build_document(action, spec, slug, ops, base_version, label, ids, version)
    return json.dumps(result, default=str)


async def _build_document(
    action: str, spec: Optional[Dict[str, Any]], slug: str,
    ops: Optional[List[Dict[str, Any]]], base_version: Optional[int], label: str,
    ids: Optional[List[str]], version: Optional[int],
) -> Dict[str, Any]:
    from utils.e2b_sandbox import (
        SandboxOwnershipError, SandboxUnavailableError, claim_session, is_configured,
    )

    if not is_configured():
        return _bad("document building is not available on this server", retry=False)
    ctx = get_session_context()
    action = (action or "create").strip().lower()

    try:
        # Stored documents belong to the session's owner; check before any read.
        session_id = await claim_session(ctx["session_id"], org_id=ctx["org_id"], user_id=ctx["user_id"])

        if action == "list":
            documents = await docgen_store.list_documents(session_id)
            return {"success": True, "documents": documents,
                    "note": "No documents yet — use action='create'." if not documents else
                            "Edit one with action='edit' and its slug."}

        if action == "create":
            if not isinstance(spec, dict) or not spec:
                return _bad("create needs a spec: {format, filename, content:[…]}")
            parsed = DocumentSpec(**spec)
            return await _build_store_and_deliver(
                session_id, parsed, _slugify(parsed.filename),
                label=label or "created", base_version=None)

        slug, resolved_note = await _resolve_slug(session_id, slug)
        if not slug:
            return _bad(f"{action} needs the document's slug, and this conversation has "
                        f"{resolved_note}; action='list' shows them")

        if action == "show":
            stored, entry = await docgen_store.load_spec(session_id, slug)
            if ids:
                blocks = [b.model_dump(exclude_none=True) for b in stored._every_block()
                          if getattr(b, "id", None) in set(ids)]
                missing = sorted(set(ids) - {b.get("id") for b in blocks})
                return {"success": True, "slug": slug, "version": entry["version"],
                        "blocks": blocks, **({"not_found": missing} if missing else {})}
            return {"success": True, "slug": slug, "version": entry["version"],
                    "spec": stored.payload(), "outline": stored.outline()}

        if action == "edit":
            stored, entry = await docgen_store.load_spec(session_id, slug)
            if entry.get("stale"):
                return _bad(
                    f"{slug} was changed outside build_document (by "
                    f"{entry.get('stale_by', 'a script')}), so the stored spec no longer "
                    "matches the file. Editing would discard that change — create a new "
                    "document instead.")
            edited, notes = doc_ops.apply(stored, ops or [])
            result = await _build_store_and_deliver(
                session_id, edited, slug, label=label or "; ".join(notes)[:80],
                base_version=base_version if base_version is not None else entry["version"])
            if result.get("success"):
                result["applied"] = notes
                if resolved_note:
                    result["resolved"] = resolved_note
            return result

        if action in ("undo", "revert"):
            restored, from_version = await docgen_store.restore(
                session_id, slug, None if action == "undo" else version)
            result = await _build_store_and_deliver(
                session_id, restored, slug, label=f"{action} to v{from_version}", base_version=None)
            if result.get("success"):
                result["restored_from_version"] = from_version
            return result

        return _bad(f"unknown action {action!r}; use create, edit, show, list, undo or revert")

    except SandboxOwnershipError as exc:
        return _bad(str(exc), retry=False)
    except SandboxUnavailableError as exc:
        return _bad(str(exc), retry=False)
    except docgen_store.StoreUnavailable as exc:
        logger.error(f"[docgen] document store unavailable during {action}: {exc}")
        return _bad(
            "the document store could not be reached just now. The document is NOT lost — do "
            "not re-create it. Try the same call once more.", retry=False)
    except (docgen_store.VersionConflict, docgen_store.UnknownDocument) as exc:
        return _bad(str(exc))
    except doc_ops.OpError as exc:
        return _bad(f"that edit cannot be applied: {exc}")
    except _TemplateMissingLibraries:
        logger.error("[docgen] the E2B template lacks docgen's libraries; set E2B_TEMPLATE_ID "
                     "to a template built from backend/e2b.Dockerfile")
        return _bad("the document sandbox is missing its document libraries, so no document "
                    "can be built right now. Tell the user; retrying will not help.", retry=False)
    except ValueError as exc:
        # Pydantic validation and the store's own complaints: the model can fix these.
        return _bad(f"the spec is not valid: {str(exc)[:600]}")
    except Exception as exc:  # noqa: BLE001 - a failure here is a result, not a crash
        from utils.e2b_sandbox import evict_handle

        evict_handle(ctx.get("session_id"))
        logger.error(f"[docgen] {action} failed for {slug or 'new'}: {exc}", exc_info=True)
        return _bad(
            f"the sandbox failed while building ({type(exc).__name__}: {str(exc)[:200]}). "
            "This is infrastructure, not your spec — retry the same call once; do not "
            "re-create it from scratch.", retry=False)


async def _resolve_slug(session_id: str, slug: str) -> tuple[str, str]:
    """The document a follow-up means when it doesn't name it exactly."""
    documents = await docgen_store.list_documents(session_id)
    slugs = {d["slug"] for d in documents}
    wanted = (slug or "").strip()
    if wanted in slugs:
        return wanted, ""
    if wanted:
        stem = _slugify(wanted)
        for d in documents:
            if stem in (d["slug"], _slugify(d.get("filename") or "")):
                return d["slug"], f"'{wanted}' resolved to '{d['slug']}'"
    if len(documents) == 1:
        only = documents[0]["slug"]
        return only, (f"'{wanted}' is not a document here; used '{only}', the only one"
                      if wanted else f"used '{only}', the only document in this conversation")
    if not documents:
        return ("" if not wanted else wanted), "no documents yet"
    return ("" if not wanted else wanted), f"{len(documents)} documents"


def _bad(message: str, *, retry: bool = True) -> Dict[str, Any]:
    return {
        "success": False,
        "error": message,
        "note": ("Fix the call and try again — do not switch to writing Python to build "
                 "the document." if retry else
                 "Do not retry this more than once. If it fails again, tell the user what "
                 "the document would have contained, inline."),
    }
