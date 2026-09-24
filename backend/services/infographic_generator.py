"""
Infographic Generator Service
Generates infographic images using Map-Reduce content selection + image model render

Pipeline (runs as a background task):
    MAP     - per document: ranked digest of candidate insights (structured output)
    REDUCE  - pick headline + select/arrange the most important insights into a spec
    CHECK   - drop items whose numbers don't appear in the source documents
    COMPOSE - build a strict image prompt from the spec (code template, not LLM)
    RENDER  - image model via OpenRouter Images API, upload PNG to iDrive E2
"""

import asyncio
import io
import re
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from clients.postgres_client import get_postgres_client
from clients.idrivee2_client import get_idrivee2_client
from clients.ultimate_llm import get_llm
from models.infographic_models import (
    DocDigest,
    InfographicSpec,
    ASPECT_RATIOS,
    DETAIL_BUDGETS,
)
from utils.text_match import normalize_text
from utils.image_gen import generate_image, IMAGE_MODEL
from app.logger import logger


TEXT_MODEL = "google/gemini-3-flash-preview"
# A "processing" row older than this is treated as failed (e.g. server restarted mid-generation)
STALE_AFTER = timedelta(minutes=10)

# Art direction per style. Written as prose briefs (palette as name + hex, type described by
# character + a reference family, layout motifs, iconography, finish), per Google's Nano Banana
# prompting guides and published infographic skills: prose beats keyword lists for image models.
STYLE_FORMATS = {
    "auto": "clean information-design poster",
    "professional": "board-briefing one-pager",
    "tactical": "military operations briefing board",
    "editorial": "editorial magazine infographic",
    "instructional": "field-manual instruction plate",
    "sketch": "hand-drawn sketchnote page",
}

STYLE_PROMPTS = {
    "auto": (
        "A clean, contemporary information-design poster on a pure white (#FFFFFF) field with soft cool-gray panels (#EEF2F5). "
        "Deep ink (#16202A) for text, deep teal (#0E6E6E) for primary shapes, and a single warm amber accent (#F2A541) reserved for the single highlighted value. "
        "Typography is a neutral geometric grotesque in the spirit of Inter: heavy, tightly tracked title; semibold headings; regular body. "
        "Flat single-weight teal line icons and a crisp vector finish."
    ),
    "professional": (
        "A restrained corporate board-briefing one-pager on white (#FFFFFF) with pale slate bands (#EDF1F6). "
        "Navy (#13294B) headings, slate (#5B6B7F) secondary text, and a muted gold accent (#B8962E) only on the single highlighted value. "
        "A humanist sans in the spirit of Frutiger or Source Sans, semibold headings, tabular figures. "
        "Thin navy rules and small square-cornered panels without shadows, consistent 1.5-pt outline icons, a quiet, precise, print-ready finish."
    ),
    "tactical": (
        "A restrained military operations-briefing board on dark gunmetal charcoal (#1E2226), with olive-drab panels (#3F4A2A), "
        "sand-khaki secondary text (#CBBE94) and a signal-amber accent (#E3A72F) used only for the single highlighted value and critical warnings. "
        "Headings in a bold condensed industrial sans in the spirit of DIN Condensed with slight letter-spacing; body in a clean grotesque. "
        "Motifs: a faint coordinate grid, corner registration ticks, bracketed frames and sector-style dividers. "
        "Simple stencil-like symbols of uniform stroke and a matte, laminated field-briefing-card finish; no camouflage, weapons, neon glow or HUD effects."
    ),
    "editorial": (
        "A magazine feature spread on an asymmetric grid: paper white (#F7F6F2) ground, ink black (#141414) text, a cobalt accent (#2340B8) "
        "and sparing ochre (#D39B22). A very large high-contrast display serif headline in the spirit of Tiempos Headline; body and labels in a crisp grotesque. "
        "Bold color-block panels, oversized numerals, pull-quote scale contrast and thin column rules. "
        "Flat graphic illustration rather than kit icons, and a fine offset-print finish."
    ),
    "instructional": (
        "A field-manual instruction plate on off-white (#F4F3EE) with near-black ink (#161616) linework and text; "
        "safety orange (#F26A1B) marks only step numbers, warnings and the single highlighted value. "
        "A sturdy technical sans in the spirit of Helvetica Bold for headings and a condensed sans for captions. "
        "A ruled panel grid with boxed numbered steps, leader-line callouts and directional arrows. "
        "Clean technical line drawings with uniform 2-pt strokes and no shading, and a crisp printed-manual finish."
    ),
    "sketch": (
        "A hand-drawn sketchnote on lightly dotted cream paper (#FBF9F3): black fineliner (#222222) linework, two highlighter accents, "
        "lemon (#FFE45C) and aqua (#4CC3B5), and soft gray marker shadows (#D5D5D5). "
        "Bold hand-lettered block capitals for headings and neat, highly legible handwriting for body text. "
        "Wobbly boxes, banners, arrows, underline swooshes and a few sparse doodles in one consistent pen weight; "
        "it should look made by a skilled visual note-taker, clean and uncrowded."
    ),
}

# Designed treatment per section kind (instead of generic "cards")
SECTION_VISUALS = {
    "stats": "oversized bold numerals (3-4x the label size) on a shared baseline, each with a short thin rule and a small label beneath, separated by hairline vertical dividers rather than boxed cards",
    "list": "a left-aligned column of consistent line icons, each beside a bold label and a one-line muted description, with hairline separators",
    "steps": "large numerals in open circles joined by one continuous connector line with small arrowheads, evenly spaced, with a bold label and short description under each node",
    "comparison": "two mirrored columns with contrasting header chips, rows aligned across a shared center spine, both sides of equal visual weight",
    "timeline": "a single continuous spine with dot markers and tick marks, bold time values on the spine and event labels alternating sides",
}

# How the canvas is organised per orientation
ORIENTATION_COMPOSITION = {
    "portrait": "a full-width header band across the top ~15% of the canvas, then sections stacked vertically in reading order",
    "landscape": "a header band across the top, then sections arranged left to right in columns, reading left to right and top to bottom; columns may hold different numbers of items, so leave whitespace at the bottom of shorter columns rather than filling them",
    "square": "a compact header across the top, then sections arranged in a two-column grid; sections may differ in size, so leave whitespace rather than filling gaps",
}

DESIGN_RULES = """- Build on a strict 12-column grid with outer margins of 6-8% of the canvas on every side; align every element to shared column edges and baselines, and left-align text blocks.
- One dominant focal point: the title and the single highlighted value. Everything else is quieter and subordinate.
- Three levels of hierarchy only: title about 3x the section-heading size, headings about 1.5x body text. At most two type families and two weights each; tabular lining figures for numbers.
- Group with whitespace rather than boxes: related items sit close together, sections are separated by generous space and thin hairline rules. Be generous with whitespace.
- Restrained palette in roughly 60/30/10 proportions (neutral ground, primary ink, single accent); the accent appears only on the single highlighted value. Text contrast at least 4.5:1.
- One icon family throughout: same stroke weight, corner style, size and single color; each icon literally depicts its concept.
- Numbers are the heroes: large, flat, no 3D, gradients or shadows on data.
- A calm solid background and crisp flat vector rendering with consistent corner radii; no gradient washes, glow, glassmorphism, clip-art, stock 3D people, emoji or mascots, and no kit of identical rounded cards with drop shadows.
- The page should look meticulously composed by a senior information designer, with nothing overlapping or crowded."""


def _number_tokens(text: str) -> List[str]:
    """Normalized tokens that contain a digit, e.g. '65.5 Tons via M1070' -> ['65', '5', 'm1070']"""
    return [t for t in normalize_text(text or "").split() if any(c.isdigit() for c in t)]


def _numbers_grounded(text: str, padded_sources: List[str]) -> bool:
    """True if every number-bearing token in text appears as a whole token in at least one source document"""
    return all(any(f" {t} " in src for src in padded_sources) for t in _number_tokens(text))


class InfographicGeneratorService:
    """Service for generating infographics"""

    def __init__(self):
        """Initialize infographic generator service"""
        self.postgres_client = get_postgres_client()
        self.idrive = get_idrivee2_client()
        self.llm = get_llm(model=TEXT_MODEL, provider="openrouter")
        self.digest_llm = self.llm.with_structured_output(DocDigest)
        self.spec_llm = self.llm.with_structured_output(InfographicSpec)

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    async def create_pending(
        self,
        document_ids: List[str],
        options: Dict[str, Any],
        user_id: str,
        organization_id: str
    ) -> str:
        """Insert a 'processing' workflow row; the caller schedules run_generation()"""
        workflow_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.postgres_client.insert_workflow({
            "id": workflow_id,
            "type": "infographic",
            "document_ids": document_ids,
            "user_id": user_id,
            "organization_id": organization_id,
            "status": "processing",
            "data": {"title": None, "settings": options},
            "created_at": now,
            "updated_at": now,
        })
        logger.info(f"🖼️ Infographic {workflow_id} queued for {len(document_ids)} documents")
        return workflow_id

    async def run_generation(
        self,
        workflow_id: str,
        document_ids: List[str],
        options: Dict[str, Any],
        organization_id: str
    ) -> None:
        """Background task: run the full pipeline and record the result on the workflow row"""
        try:
            detail_level = options.get("detail_level", "standard")
            focus = options.get("focus")

            # MAP
            digests = await self._map_digest_documents(document_ids, focus)
            if not digests:
                raise Exception("No content could be extracted from the selected documents")

            # REDUCE
            spec = await self._reduce_create_spec(digests, detail_level, focus)

            # CHECK
            spec = self._drop_ungrounded_numbers(spec, digests)

            # COMPOSE + RENDER
            prompt = self._compose_prompt(spec, options)
            image_bytes, cost = await self._render(prompt, ASPECT_RATIOS.get(options.get("orientation"), "3:4"))

            image_key = f"infographics/{organization_id}/{workflow_id}.png"
            await self.idrive.upload_file(io.BytesIO(image_bytes), image_key, "image/png")

            sources = sorted({item["source"] for s in spec["sections"] for item in s["items"] if item.get("source")})
            await self.postgres_client.update_workflow(workflow_id, {
                "status": "completed",
                "data": {
                    "title": spec["title"],
                    "settings": options,
                    "spec": spec,
                    "prompt": prompt,
                    "image_key": image_key,
                    "image_model": IMAGE_MODEL,
                    "cost_usd": cost,
                    "sources": sources,
                },
                "updated_at": datetime.now(timezone.utc),
            })
            logger.info(f"✅ Infographic {workflow_id} completed (cost ${cost})")

        except Exception as e:
            logger.error(f"❌ Infographic {workflow_id} failed: {str(e)}")
            try:
                await self.postgres_client.update_workflow(workflow_id, {
                    "status": "failed",
                    "data": {"title": None, "settings": options, "error": str(e)},
                    "updated_at": datetime.now(timezone.utc),
                })
            except Exception as update_error:
                logger.error(f"❌ Failed to mark infographic {workflow_id} as failed: {str(update_error)}")

    # ------------------------------------------------------------------
    # MAP
    # ------------------------------------------------------------------

    async def _map_digest_documents(self, document_ids: List[str], focus: Optional[str]) -> List[Dict[str, Any]]:
        """MAP Phase: ranked digest of each document, in parallel"""
        semaphore = asyncio.Semaphore(5)
        focus_rule = (
            f"\n- The user wants the infographic to focus on: {focus}\n  Rank insights relevant to this focus highest; this overrides the other criteria."
            if focus else ""
        )

        async def digest_one(doc_id: str) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    document = await self.postgres_client.find_document_by_id(doc_id)
                    if not document:
                        logger.warning(f"⚠️ Document {doc_id} not found")
                        return None

                    filename = document.get("file_name", "Unknown")
                    raw_content = document.get("raw_content", "")
                    if not raw_content:
                        logger.warning(f"⚠️ Document {doc_id} has no content")
                        return None

                    prompt = f"""You are selecting content for an infographic that summarizes the document below.

Identify the document's single most important takeaway, then list up to 15 candidate insights, most important first.

Judge importance by:
- Centrality: what the document exists to say, not side details.
- Decision relevance: requirements, limits, risks, deadlines, recommendations.
- Visual potential: numbers, sequences, comparisons and timelines make the best infographic content.{focus_rule}

For each insight give the key number/date in "value" if there is one, and copy the supporting sentence EXACTLY, word for word, into "quote".

Document content:
{raw_content}"""

                    digest: DocDigest = await self.digest_llm.ainvoke(prompt)
                    logger.info(f"✅ Digested {filename}: {len(digest.insights)} insights")
                    return {
                        "filename": filename,
                        "digest": digest,
                        "normalized_content": normalize_text(raw_content),
                    }

                except Exception as e:
                    logger.error(f"❌ Failed to digest document {doc_id}: {str(e)}")
                    return None

        results = await asyncio.gather(*[digest_one(doc_id) for doc_id in document_ids])
        digests = [r for r in results if r]
        logger.info(f"📊 Digested {len(digests)}/{len(document_ids)} documents")
        return digests

    # ------------------------------------------------------------------
    # REDUCE
    # ------------------------------------------------------------------

    async def _reduce_create_spec(
        self,
        digests: List[Dict[str, Any]],
        detail_level: str,
        focus: Optional[str]
    ) -> Dict[str, Any]:
        """REDUCE Phase: choose the headline and the most important insights, arranged into sections"""
        budget = DETAIL_BUDGETS.get(detail_level, DETAIL_BUDGETS["standard"])

        blocks = []
        for d in digests:
            digest: DocDigest = d["digest"]
            lines = [f"Document: {d['filename']}", f"Main point: {digest.main_point}"]
            for ins in digest.insights:
                value = f" [value: {ins.value}]" if ins.value else ""
                lines.append(f"- ({ins.kind}, importance {ins.importance}){value} {ins.claim} | why: {ins.why}")
            blocks.append("\n".join(lines))
        candidates = "\n\n".join(blocks)
        focus_rule = f"\n- Focus: {focus}. Prioritise content relevant to this focus." if focus else ""

        prompt = f"""You are designing the content of a single infographic that summarizes these documents.

Below are ranked candidate insights extracted from each document.

STEPS:
1. Decide the ONE headline takeaway across all documents. It becomes the title and subtitle; everything else must support it.
2. Merge insights that appear in more than one document; being backed by several documents makes an insight more important.
3. Select only the most important insights within the budget: {budget['sections']} sections, {budget['items']} items in total, roughly {budget['words']} words of text overall.
4. Choose a mix of section kinds that fits the content (stats, list, steps, comparison, timeline) rather than repeating the same kind.
5. Cover every document unless the focus says otherwise; don't let one document crowd out the others.

RULES:
- Text must be short: labels 2-6 words, optional descriptions one short line. Less text is better.
- Copy numbers and dates EXACTLY as given in the candidates; never invent, round, convert or compute numbers.
- Set "source" on every item to the filename of the document it comes from.
- Use plain words; no markdown, emoji or hashtags.{focus_rule}

Candidate insights:
{candidates}"""

        spec: InfographicSpec = await self.spec_llm.ainvoke(prompt)
        logger.info(f"✅ Spec: '{spec.title}' with {len(spec.sections)} sections")
        return spec.model_dump()

    # ------------------------------------------------------------------
    # CHECK
    # ------------------------------------------------------------------

    def _drop_ungrounded_numbers(self, spec: Dict[str, Any], digests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Drop items (and the takeaway) containing numbers that don't appear in any source document"""
        padded_sources = [f" {d['normalized_content']} " for d in digests]
        dropped = 0

        sections = []
        for section in spec["sections"]:
            items = []
            for item in section["items"]:
                text = " ".join(filter(None, [item.get("label"), item.get("value"), item.get("description")]))
                if _numbers_grounded(text, padded_sources):
                    items.append(item)
                else:
                    dropped += 1
                    logger.warning(f"⚠️ Dropping infographic item with ungrounded number: {text[:100]}")
            if items:
                # A lone stat card / step / column invites the image model to pad the layout
                # with invented items, so single-item sections are drawn as a plain list
                kind = section["kind"] if len(items) > 1 else "list"
                sections.append({**section, "kind": kind, "items": items})

        if spec.get("takeaway") and not _numbers_grounded(spec["takeaway"], padded_sources):
            logger.warning(f"⚠️ Dropping takeaway with ungrounded number: {spec['takeaway'][:100]}")
            spec["takeaway"] = None

        if not sections:
            raise Exception("No infographic content could be verified against the source documents")

        logger.info(f"🔎 Number check: dropped {dropped} items")
        return {**spec, "sections": sections}

    # ------------------------------------------------------------------
    # COMPOSE + RENDER
    # ------------------------------------------------------------------

    def _compose_prompt(self, spec: Dict[str, Any], options: Dict[str, Any]) -> str:
        """
        Build the image prompt from the spec with a fixed template:
        format/purpose -> art direction -> composition -> content in reading order -> design rules -> text rules
        """
        orientation = options.get("orientation", "portrait")
        style_key = options.get("style", "auto")
        style = STYLE_PROMPTS.get(style_key, STYLE_PROMPTS["auto"])
        fmt = STYLE_FORMATS.get(style_key, STYLE_FORMATS["auto"])
        aspect = ASPECT_RATIOS.get(orientation, "3:4")
        composition = ORIENTATION_COMPOSITION.get(orientation, ORIENTATION_COMPOSITION["portrait"])

        # The first item with a value is the key figure that gets the accent color
        key_item = next((it for sec in spec["sections"] for it in sec["items"] if it.get("value")), None)

        layout = [f'1. Header: title "{spec["title"]}", with subtitle "{spec["subtitle"]}" beneath it.']
        for i, section in enumerate(spec["sections"], start=2):
            visual = SECTION_VISUALS.get(section["kind"], SECTION_VISUALS["list"])
            count = len(section["items"])
            layout.append(
                f'{i}. Section headed "{section["heading"]}", shown as {visual}, '
                f'with exactly {count} item{"s" if count != 1 else ""}:'
            )
            for n, item in enumerate(section["items"], start=1):
                parts = [f'"{item["label"]}"']
                if item.get("value"):
                    parts.insert(0, f'"{item["value"]}"')
                if section["kind"] == "steps":
                    parts.insert(0, f'step number "{n}"')
                if item.get("description"):
                    parts.append(f'"{item["description"]}"')
                accent = "; draw its value in the accent color" if item is key_item else ""
                layout.append(f"   - {' / '.join(parts)} (icon: {item['icon_hint']}{accent})")
        if spec.get("takeaway"):
            layout.append(f'{len(spec["sections"]) + 2}. Footer band: "{spec["takeaway"]}"')

        layout_text = "\n".join(layout)
        return f"""Generate a professional infographic image: a {orientation} {aspect} {fmt} that summarizes source documents for busy professional readers.
This brief is instructions for the designer. The ONLY text that may appear in the image is the quoted strings in the CONTENT section.

ART DIRECTION: {style}

COMPOSITION: {composition}. The title and the accent-colored value form the focal point.

CONTENT (in reading order, top to bottom, left to right):
{layout_text}

DESIGN RULES:
{DESIGN_RULES}

TEXT RULES (critical):
- Render every text string exactly as written between quotes, with exact spelling, numbers and capitalization. Never shorten, abbreviate or truncate a string. Do not render the quote marks themselves.
- Everything outside quotes (including this brief's opening sentence and section names like CONTENT or ART DIRECTION) (style, colors, hex codes, fonts, layout and icon descriptions) is an instruction, not text: never draw it.
- Do not add ANY other text: no extra captions, descriptions, labels, hashtags, logos, watermarks, URLs, dates or footers.
- Draw exactly the sections and items listed, each once. Never add, repeat or invent items, numbers, stat cards, steps or columns to fill space; leave whitespace or enlarge existing elements instead.
- Icons and illustrations contain no text, letters or numbers.
- All text must be large, sharp and legible. Language: English."""

    async def _render(self, prompt: str, aspect_ratio: str) -> tuple[bytes, Optional[float]]:
        """Render the image via the OpenRouter Images API, retrying once on failure"""
        return await generate_image(prompt, aspect_ratio, model=IMAGE_MODEL)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _effective_status(self, status: str, updated_at: Optional[datetime]) -> str:
        """Treat long-stuck 'processing' rows (e.g. after a server restart) as failed"""
        if status == "processing" and updated_at and datetime.now(timezone.utc) - updated_at > STALE_AFTER:
            return "failed"
        return status

    async def list_infographics(self, user_id: str, organization_id: str) -> List[Dict[str, Any]]:
        """List the user's infographics (summaries + thumbnail URLs, newest first)"""
        workflows = await self.postgres_client.find_workflow_summaries_by_user(
            "infographic", user_id, organization_id, exclude_data_keys=["spec", "prompt"]
        )
        results = []
        for w in workflows:
            data = w["data"]
            image_key = data.get("image_key")
            results.append({
                "workflow_id": w["id"],
                "status": self._effective_status(w.get("status"), w.get("updated_at")),
                "title": data.get("title"),
                "settings": data.get("settings", {}),
                "document_count": w.get("document_count") or 0,
                "image_url": await self.idrive.generate_presigned_url(image_key) if image_key else None,
                "created_at": w["created_at"].isoformat() if w.get("created_at") else None,
            })
        return results

    async def get_infographic(self, workflow_id: str, user_id: str, organization_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Fetch an infographic, only if it belongs to the requesting user and organization"""
        workflow = await self.postgres_client.find_workflow_by_id(workflow_id, "infographic")
        if not workflow or workflow.get("user_id") != user_id or workflow.get("organization_id") != organization_id:
            return None

        data = workflow["data"]
        status = self._effective_status(workflow.get("status"), workflow.get("updated_at"))
        image_key = data.get("image_key")
        title = data.get("title")
        filename = re.sub(r"[^\w\- ]", "", title or "infographic").strip().replace(" ", "_") or "infographic"

        return {
            "workflow_id": workflow["id"],
            "status": status,
            "title": title,
            "settings": data.get("settings", {}),
            "spec": data.get("spec"),
            "sources": data.get("sources", []),
            "document_ids": workflow.get("document_ids", []),
            "document_count": len(workflow.get("document_ids") or []),
            "error": data.get("error") or ("Generation timed out" if status == "failed" and workflow.get("status") == "processing" else None),
            "image_url": await self.idrive.generate_presigned_url(image_key) if image_key else None,
            "download_url": await self.idrive.generate_presigned_url(image_key, download_filename=f"{filename}.png") if image_key else None,
            "created_at": workflow["created_at"].isoformat() if workflow.get("created_at") else None,
        }


# Singleton instance
_infographic_generator_service = None


def get_infographic_generator_service() -> InfographicGeneratorService:
    """Get or create infographic generator service singleton"""
    global _infographic_generator_service
    if _infographic_generator_service is None:
        _infographic_generator_service = InfographicGeneratorService()
    return _infographic_generator_service
