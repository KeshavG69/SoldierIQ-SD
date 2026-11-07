"""Build a report PDF from content, never from style.

None of these methods takes a font size, a color or a margin. That is the point: production
PDFs used eight different page margins and put 56% of their font sizes outside any sanctioned
scale, because the scale lived in a reference file the loader could not serve and every script
retyped its own numbers.

    from docgen.pdf import Report

    r = Report("q1.pdf", title="Q1 Review", subtitle="Procurement")
    r.cover()
    r.h1("Spend by category")
    r.body("Consulting is 38% of addressable spend.")
    r.table(["Category", "Spend", "Share"], rows)
    r.save()
"""

from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from docgen import fonts
from docgen import measure
from docgen import tokens as T
from docgen.palette import DEFAULT, Palette, active

# Above this a table repeats its header and is allowed to split; below it, it stays whole.
_SPLIT_ROWS = 15

# The cover styles the agent chooses between (see `Report.cover`).
_COVER_STYLES = ("dark", "minimal", "editorial", "custom")
# A light cover ground that is still visibly non-white, so the linter's `_is_cover` detects a
# light-styled cover the same way it detects a dark one (a pure-white fill reads as invisible).
_COVER_LIGHT = "#F1F5FB"  # light cover ground, a tint of the PriceIQ navy


def _hex(value: str):
    return colors.HexColor(value)


def _clean_hex(value, fallback: str = "#150F26") -> str:
    """Normalise a caller-supplied colour to #RRGGBB, falling back on anything unparseable —
    a bad colour on a custom cover must not take down the build."""
    try:
        v = str(value).strip().lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        if len(v) != 6:
            return fallback
        int(v, 16)
        return "#" + v.upper()
    except (TypeError, ValueError):
        return fallback


def esc(text) -> str:
    """Escape user text for reportlab's mini-markup parser.

    A Paragraph reads its string as XML-ish markup, so an unescaped "&" in content — "R&D",
    "S&OP", "AT&T" — is taken as an entity and silently mangled (this is where the reference
    report's "Demand Planning & S&OP;" stray semicolon came from). Applied to every piece of
    model-supplied text; the builder's own <b>/<i>/&nbsp; tags are added around the result.
    """
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Report:
    def __init__(self, path, title: str = "", subtitle: str = "", author: str = "SoldierIQ",
                 palette: Optional[Palette] = None, footer: str = ""):
        self.path = Path(path)
        self.title = title
        self.subtitle = subtitle
        self.footer_text = footer or title
        self.p = palette or active()
        # How many neutral blocks this report has drawn — see `_next_accent`.
        self._decor = 0
        self.fmt = T.PDF
        self.regular, self.bold = fonts.register_pdf()
        self.story: List = []

        m = self.fmt.margin_in
        self.doc = SimpleDocTemplate(
            str(self.path),
            pagesize=(self.fmt.page_w_in * inch, self.fmt.page_h_in * inch),
            leftMargin=m["left"] * inch, rightMargin=m["right"] * inch,
            topMargin=m["top"] * inch, bottomMargin=m["bottom"] * inch,
            title=title or self.path.stem, author=author, subject=subtitle,
        )
        self._styles = {name: self._style(name) for name in self.fmt.scale}
        # Cover state — set by cover(), consumed by _draw_cover on the first page.
        self._has_cover = False
        self._cover_meta: dict = {}
        self._cover_kicker = ""
        self._cover_style = "dark"
        self._cover_wordmark = ""
        self._cover_motif_kind = "circles"
        self._cover_bg = None
        self._cover_shapes: list = []
        self._cover_ink: dict = {}

    # ── styles ────────────────────────────────────────────────────────────────
    def _style(self, role: str) -> ParagraphStyle:
        t = self.fmt.scale[role]
        return ParagraphStyle(
            f"docgen-{role}",
            fontName=self.bold if t.bold else self.regular,
            fontSize=t.size,
            leading=t.line_pt,
            spaceBefore=t.space_before,
            spaceAfter=t.space_after,
            textColor=_hex(self.p.text),
            alignment=TA_LEFT,
            # Default (word-boundary) wrapping, NOT "CJK": CJK wraps between any two glyphs, so
            # a bold heading in a narrow card came out "Manual Reconcili / ation". Latin wrapping
            # breaks on spaces and only splits a word that is itself wider than the column.
            splitLongWords=True,
        )

    def _para(self, text: str, role: str, color: Optional[str] = None,
              raw: bool = False, **overrides) -> Paragraph:
        style = self._styles[role]
        if color:
            style = ParagraphStyle(f"{style.name}-{color}", parent=style, textColor=_hex(color))
        if overrides:
            # Must be set before the Paragraph exists: font size is baked into its
            # fragments at construction, so restyling afterwards only moves alignment.
            key = "-".join(f"{k}{v}" for k, v in sorted(overrides.items()))
            style = ParagraphStyle(f"{style.name}-{key}", parent=style, **overrides)
        # Model text is escaped by default; `raw=True` is for the few call sites that build
        # their own <b>/<i>/&nbsp; markup and escape the user parts themselves.
        return Paragraph(str(text) if raw else esc(text), style)

    # ── content ───────────────────────────────────────────────────────────────
    def cover(self, meta: Optional[dict] = None, kicker: str = "",
              style: str = "dark", wordmark: str = "",
              motif: str = "circles", background=None, shapes=None,
              ink: Optional[dict] = None) -> "Report":
        """A cover page, drawn on the canvas by `_draw_cover`. Page 1 holds nothing else.

        `style` is the agent's call, chosen for the document — not one look for everything:

        - **dark** — full-bleed near-black ground, motif, title reversed out. Bold and premium;
          for playbooks, strategy, launches, marketing, and anything meant to impress.
        - **minimal** — light ground, dark title, a coral rule, no motif. Restrained and formal;
          for financial, legal, research, and internal reports where quiet reads as credible.
        - **editorial** — light ground with a strong colour band carrying the title. For briefs,
          newsletters, announcements — a magazine-cover feel.
        - **custom** — you compose the whole aesthetic: `background`, `shapes`, and `ink` below.

        `wordmark` is the producer mark shown top-left; empty (the default) shows none. Use
        the client company's or the prime contractor's name when the user asks. Keep it `""` (a document *about* another company should carry no wordmark rather
        than that company's name, which would read as their own publication).

        `motif` is the `dark`-style background design (ignored by the light styles): circles
        (the default cluster), rings, dots, arcs, glow, or none for a plain ground.

        For **style="custom"**, the aesthetic is entirely yours — a different look per document:

        - `background`: a hex colour for a solid ground, or `{"type": "gradient", "from": "#0B1E3F",
          "to": "#123", "angle": 135}` for a gradient (angle in degrees). Use a non-white ground.
        - `shapes`: a list drawn behind the text, coordinates as fractions of the page with the
          origin TOP-LEFT (x right, y down). Each is one of:
            `{"shape": "circle", "cx": 0.85, "cy": 0.2, "r": 0.25, "color": "#F0A", "alpha": 0.5}`
            `{"shape": "ring",   "cx": .., "cy": .., "r": .., "color": .., "alpha": .., "width": 2}`
            `{"shape": "rect",   "x": 0, "y": 0.4, "w": 1, "h": 0.18, "color": .., "alpha": 1}`
            `{"shape": "line",   "x1": .., "y1": .., "x2": .., "y2": .., "color": .., "width": 2}`
          `r`/`w`/`x` are fractions of page WIDTH; `cy`/`y`/`h` fractions of page HEIGHT.
        - `ink`: text colours, so the type reads on your ground. Any of `wordmark`, `eyebrow`,
          `title`, `rule`, `subtitle`, `meta_label`, `meta_value`, `footer`. Omitted keys default
          to white-on-dark or ink-on-light by the background's brightness.

        The old cover was a flat band the width of the text measure with the first section
        flowing in under it — cover, metadata and body all crammed onto page 1. This reserves
        page 1 for the cover alone (the trailing PageBreak).
        """
        self._has_cover = True
        self._cover_meta = dict(meta or {})
        self._cover_kicker = (kicker or "Playbook").upper()
        self._cover_wordmark = "" if wordmark is None else str(wordmark)
        self._cover_motif_kind = str(motif or "circles").strip().lower()
        self._cover_bg = background
        self._cover_shapes = list(shapes or [])
        self._cover_ink = dict(ink or {})
        self._cover_style = str(style or "dark").strip().lower()
        if self._cover_style not in _COVER_STYLES:
            self._cover_style = "dark"
        # Page 1 holds nothing but the canvas-drawn cover; the break sends content to page 2.
        self.story += [Spacer(1, 1), PageBreak()]
        return self

    def eyebrow(self, text: str) -> "Report":
        """A coral, tracked, small-caps kicker above a heading — the reference's section label.

        Text-only reports opened every section with a bare `h1`; the eyebrow is the one piece
        of the deck's vocabulary that reads as 'this is a section', not just 'this is bold'.
        """
        cap = self.fmt.scale["caption"]
        style = ParagraphStyle(
            "docgen-eyebrow", parent=self._styles["caption"],
            fontName=self.bold, fontSize=cap.size, leading=cap.line_pt,
            spaceBefore=8, spaceAfter=1,
            textColor=_hex(self.p.ink(self.p.accent)),
        )
        para = Paragraph(str(text).upper(), style)
        # An eyebrow labels what follows; it must never end a page on its own.
        para.keepWithNext = True
        self.story.append(para)
        return self

    def h1(self, text: str) -> "Report":
        return self._heading(text, "h1")

    def h2(self, text: str) -> "Report":
        return self._heading(text, "h2")

    def h3(self, text: str) -> "Report":
        return self._heading(text, "h3")

    def _heading(self, text: str, role: str) -> "Report":
        # Bound to whatever comes next so a heading cannot strand at a page bottom.
        # keepWithNext, not KeepTogether([heading]): the old wrapper held the heading
        # together with a 1pt spacer only, so "YEAR-BY-YEAR COST TABLE" still ended a
        # page with its table on the next one. The doc template groups a keepWithNext
        # flowable with the one after it (and chains eyebrow -> heading -> block).
        para = self._para(text, role)
        para.keepWithNext = True
        self.story.append(para)
        return self

    def body(self, text: str) -> "Report":
        self.story.append(self._para(text, "body"))
        return self

    def caption(self, text: str) -> "Report":
        self.story.append(self._para(text, "caption", self.p.muted))
        return self

    def bullets(self, items: Iterable[str]) -> "Report":
        for item in items:
            self.story.append(self._para(f"•&nbsp;&nbsp;{esc(item)}", "bullet", raw=True))
        return self

    def question(self, number, text: str, marks=None) -> "Report":
        """A numbered question, with the number hanging beside the text.

        Without this the only thing to reach for was `body()`, so a whole exam paper came
        out as flat paragraphs — `r.body("<b>1.</b> Which of the following pairs is
        correctly matched? (a) ... (b) ...")`, with the number inline and the wrapped lines
        running back under it. The number sits in its own column so every line of the
        question aligns, and the marks sit against the right margin where a candidate
        looks for them."""
        num = esc(number)
        label = f"<b>{num}.</b>" if not str(number).rstrip().endswith((".", ")")) else f"<b>{num}</b>"
        num_w = max(0.3, measure.natural_width_in(f"{number}.", self.fmt.scale["body"].size, True) + 0.08)
        marks_w = 0.0
        if marks is not None:
            marks_w = max(0.45, measure.natural_width_in(str(marks), self.fmt.scale["caption"].size) + 0.12)

        total = self.fmt.content_w_in
        widths = [num_w, total - num_w - marks_w] + ([marks_w] if marks_w else [])
        row = [self._para(label, "body", raw=True), self._para(text, "body")]
        if marks_w:
            # A table cell's ALIGN places the flowable, not the text inside it; a Paragraph
            # fills its cell and keeps its own alignment, so the marks have to carry theirs.
            style = ParagraphStyle(
                "docgen-marks", parent=self._styles["caption"],
                alignment=TA_RIGHT, textColor=_hex(self.p.muted),
            )
            row.append(Paragraph(str(marks), style))

        t = Table([row], colWidths=[w * inch for w in widths])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (1, 0), (1, 0), 4),
        ]
        if marks_w:
            style.append(("ALIGN", (2, 0), (2, 0), "RIGHT"))
        t.setStyle(TableStyle(style))
        # A question and its number are one thing; splitting them across a page break is
        # the single worst thing that can happen to an exam paper.
        self.story.append(KeepTogether(t))
        return self

    def options(self, items: Iterable[str], columns: int = 2) -> "Report":
        """The answer choices as a grid, indented under the question.

        Run together inside the question paragraph — which is what `body()` did — (a) to
        (d) are unreadable as a set."""
        items = [str(i) for i in items]
        if not items:
            return self
        columns = max(1, min(int(columns), len(items)))
        rows = [items[i:i + columns] for i in range(0, len(items), columns)]
        rows = [r + [""] * (columns - len(r)) for r in rows]

        indent = 0.34
        width = (self.fmt.content_w_in - indent) / columns
        t = Table([[self._para(c, "body") if c else "" for c in r] for r in rows],
                  colWidths=[width * inch] * columns)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        wrap = Table([["", t]], colWidths=[indent * inch, (self.fmt.content_w_in - indent) * inch])
        wrap.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        self.story.append(KeepTogether(wrap))
        return self

    def kpi_row(self, pairs: Sequence[Sequence[str]]) -> "Report":
        pairs = list(pairs)
        if not pairs:
            return self
        # A colour per card — tint, top rule and figure — matching the deck's KPI tiles.
        # This was one grey band with every figure in the primary.
        accents = [self._next_accent("info") for _ in pairs]
        width = self.fmt.content_w_in * inch / len(pairs)
        pad = self.fmt.pad_pt["card"]
        # A figure must read as one figure: "$1,281,572" / ".80" across two lines is the
        # tell of a generated document. Shrink every value in the row to one common size
        # at which the longest fits its tile on a single line (never below 45%).
        base = self._styles["kpi_value"]
        inner = width - 2 * pad - 2
        longest = max(pdfmetrics.stringWidth(str(v), base.fontName, base.fontSize)
                      for v, _ in pairs)
        size = base.fontSize * max(0.45, min(1.0, inner / longest)) if longest else base.fontSize
        size = self._snap(size)
        fit = ({"fontSize": size, "leading": base.leading * size / base.fontSize}
               if size < base.fontSize else {})
        values = [self._para(str(v), "kpi_value", self.p.ink(a), **fit)
                  for (v, _), a in zip(pairs, accents)]
        cells = [values,
                 [self._para(str(l), "kpi_label", self.p.muted) for _, l in pairs]]
        t = Table(cells, colWidths=[width] * len(pairs))
        per_card = []
        for col, a in enumerate(accents):
            per_card += [("BACKGROUND", (col, 0), (col, -1), _hex(self.p.tint(a))),
                         ("LINEABOVE", (col, 0), (col, 0), 3, _hex(a))]
        t.setStyle(TableStyle(per_card + [
            ("LEFTPADDING", (0, 0), (-1, -1), pad),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        self.story += [t, self._gap("block")]
        return self

    def callout(self, text: str, tone: str = "info") -> "Report":
        fill = self._next_accent(tone)
        t = Table([[self._para(text, "body", self.p.text)]],
                  colWidths=[self.fmt.content_w_in * inch])
        pad = self.fmt.pad_pt["card"]
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _hex(self.p.tint(fill))),
            ("LINEBEFORE", (0, 0), (0, -1), 3, _hex(fill)),
            ("LEFTPADDING", (0, 0), (-1, -1), pad + 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ]))
        self.story += [t, self._gap("block")]
        return self

    # ── composed blocks ───────────────────────────────────────────────────────
    def _card_cell(self, head: str, body: str, width: float, accent: str) -> Table:
        pad = self.fmt.pad_pt["card"]
        flow = [self._para(head, "h3" if body else "body",
                           self.p.ink(accent) if body else self.p.text)]
        if body:
            flow.append(self._para(body, "body"))
        cell = Table([[flow]], colWidths=[width])
        cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _hex(self.p.tint(accent))),
            ("LINEBEFORE", (0, 0), (0, -1), 3, _hex(accent)),
            ("LEFTPADDING", (0, 0), (-1, -1), pad + 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return cell

    def columns(self, items: Sequence, *, tone: str = "info") -> "Report":
        """Titled cards side by side, on the format's own gutter.

        Every other block in this class runs the full measure, so a report could only ever
        stack. Three blocks across the page is how a reference deck reaches 38 shapes on a
        slide where a stacked one reaches 10 — and the same is true of a page."""
        items = [i for i in items if i]
        if not items:
            return self
        pairs = [(i, "") if isinstance(i, str) else (i[0], i[1] if len(i) > 1 else "")
                 for i in items]
        gutter = self.fmt.gutter_in * inch
        total = self.fmt.content_w_in * inch
        width = (total - gutter * (len(pairs) - 1)) / len(pairs)

        row, widths = [], []
        for index, (head, body) in enumerate(pairs):
            if index:
                row.append("")
                widths.append(gutter)
            row.append(self._card_cell(str(head), str(body), width,
                                       self._next_accent(tone)))
            widths.append(width)

        outer = Table([row], colWidths=widths)
        outer.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        self.story += [KeepTogether(outer), self._gap("block")]
        return self

    def quote(self, text: str, attribution: str = "") -> "Report":
        """A pull quote — the one place a document is allowed to slow down and land a line."""
        flow = [self._para(f"<i>{esc(text)}</i>", "h3", self.p.text, raw=True)]
        if attribution:
            flow.append(self._para(f"— {esc(attribution)}", "caption", self.p.muted, raw=True))
        pad = self.fmt.pad_pt["card"]
        t = Table([[flow]], colWidths=[self.fmt.content_w_in * inch])
        t.setStyle(TableStyle([
            ("LINEBEFORE", (0, 0), (0, -1), 3, _hex(self.p.accent)),
            ("LEFTPADDING", (0, 0), (-1, -1), pad + 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ]))
        self.story += [KeepTogether(t), self._gap("block")]
        return self

    def timeline(self, items: Sequence) -> "Report":
        """Phased milestones: a marker column against the content, ruled down the side.

        A roadmap rendered as bullets loses the one thing that makes it a roadmap — that the
        phases are ordered and the reader can see where one ends."""
        items = [i for i in items if i]
        if not items:
            return self
        rows = []
        for item in items:
            if isinstance(item, str):
                label, head, body = "", item, ""
            else:
                item = list(item)
                label = str(item[0]) if item else ""
                head = str(item[1]) if len(item) > 1 else ""
                body = str(item[2]) if len(item) > 2 else ""
            rows.append((label, head, body))

        marker_w = max(
            measure.natural_width_in(label, self.fmt.scale["caption"].size, True)
            for label, _, _ in rows
        ) + 0.24
        marker_w = min(max(marker_w, 0.8), 2.0)
        body_w = self.fmt.content_w_in - marker_w - 0.18

        data, style = [], [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 10),
            ("LEFTPADDING", (1, 0), (1, -1), 12),
            ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LINEBEFORE", (1, 0), (1, -1), 2, _hex(self.p.rule)),
        ]
        for index, (label, head, body) in enumerate(rows):
            # Each phase its own colour, as in the deck: one accent down every phase hid where
            # one ended and the next began.
            accent = self._next_accent("info")
            flow = [self._para(f"<b>{esc(head)}</b>", "body", raw=True)] if head else []
            if body:
                flow.append(self._para(body, "body"))
            data.append([self._para(f"<b>{esc(label)}</b>", "caption", self.p.ink(accent), raw=True), flow])
            style.append(("LINEBEFORE", (1, index), (1, index), 2, _hex(accent)))
            style.append(("BACKGROUND", (1, index), (1, index), _hex(self.p.tint(accent))))

        t = Table(data, colWidths=[marker_w * inch, (body_w + 0.18) * inch])
        t.setStyle(TableStyle(style))
        self.story += [t, self._gap("block")]
        return self

    def steps(self, items: Sequence[str]) -> "Report":
        """A numbered process, with the number in its own marker so the text aligns."""
        items = [str(i) for i in items if i]
        if not items:
            return self
        marker = 0.34
        data, style = [], [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        for index, text in enumerate(items, start=1):
            # The number takes the step's own colour, matching the deck's steps.
            data.append([self._para(f"<b>{index}</b>", "body",
                                    self.p.ink(self._next_accent("info")), raw=True),
                         self._para(text, "body")])
        t = Table(data, colWidths=[marker * inch,
                                   (self.fmt.content_w_in - marker) * inch])
        t.setStyle(TableStyle(style))
        self.story += [KeepTogether(t), self._gap("block")]
        return self

    def fields(self, pairs: Sequence[Sequence[str]], columns: int = 2) -> "Report":
        """Label/value metadata — the block every report opens with and none of them had."""
        pairs = [p for p in pairs if p]
        if not pairs:
            return self
        columns = max(1, min(int(columns), len(pairs)))
        cells = []
        for label, value in pairs:
            cells.append([self._para(str(label).upper(), "caption", self.p.muted),
                          self._para(f"<b>{esc(value)}</b>", "body", raw=True)])
        rows = [cells[i:i + columns] for i in range(0, len(cells), columns)]
        rows = [r + [[]] * (columns - len(r)) for r in rows]

        width = self.fmt.content_w_in / columns
        t = Table(rows, colWidths=[width * inch] * columns)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        self.story += [KeepTogether(t), self._gap("block")]
        return self

    def divider(self) -> "Report":
        t = Table([[""]], colWidths=[self.fmt.content_w_in * inch], rowHeights=[1])
        t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.75, _hex(self.p.rule))]))
        self.story += [self._gap("block"), t, self._gap("block")]
        return self

    def _tone(self, tone: str) -> str:
        return {"good": self.p.good, "warn": self.p.warn,
                "bad": self.p.bad}.get(tone, self.p.accent)

    def _next_accent(self, tone: str) -> str:
        """The colour for one block: its status if it has one, else the next decorative hue.

        An explicit tone still wins outright, so a status keeps one colour throughout; only
        the neutral default advances. Shared with `Slide._next_accent` so a deck and the
        report that accompanies it colour the same content the same way.
        """
        semantic = {"good": self.p.good, "warn": self.p.warn, "bad": self.p.bad}.get(tone)
        if semantic:
            return semantic
        colour = self.p.series(self._decor)
        self._decor += 1
        return colour

    def table(self, headers: Sequence[str], rows: Sequence[Sequence],
              align: Optional[Sequence[str]] = None) -> "Report":
        headers = [str(h) for h in headers]
        body = [[str(c) if c is not None else "" for c in r] for r in rows]
        # Shrink the table's type a step at a time until every figure fits on one line;
        # at the last step the floors are scaled to the page as a last resort.
        for scale in (1.0, 0.92, 0.85, 0.78):
            widths, fits = self._widths(headers, body, scale)
            if fits:
                break
        if not fits:
            squeeze = self.fmt.content_w_in * inch / sum(widths)
            widths = [w * squeeze for w in widths]
        # Case-folded and checked here, not handed to reportlab as given: a lowercase
        # "left" is what anyone writing a spec types, and reportlab's own complaint
        # ("Invalid justification 'left'") arrives from inside save(), after the document
        # is otherwise built, naming neither the table nor the column.
        if align:
            align = [str(a).strip().upper() for a in align]
            unknown = sorted(set(align) - {"LEFT", "RIGHT", "CENTER", "CENTRE", "DECIMAL"})
            if unknown:
                raise ValueError(
                    f"unknown table alignment {unknown}; use left, right, center or decimal")
            if len(align) != len(headers):
                raise ValueError(
                    f"align has {len(align)} entries for {len(headers)} columns")
        else:
            align = self._align(body, len(headers))

        # Cells are Paragraphs, which ignore the table's ALIGN; each column's paragraphs
        # carry the alignment themselves (DECIMAL reads as right-aligned text).
        _ta = {"RIGHT": TA_RIGHT, "DECIMAL": TA_RIGHT, "CENTER": TA_CENTER, "CENTRE": TA_CENTER}

        cell_style = self._styles["cell"]

        def _cell(text, i, header=False):
            over = {}
            a = _ta.get(align[i]) if i < len(align) else None
            if a is not None:
                over["alignment"] = a
            if scale < 1.0:
                size = self._snap(cell_style.fontSize * scale)
                over.update(fontSize=size,
                            leading=cell_style.leading * size / cell_style.fontSize)
            if header:
                return self._para(f"<b>{esc(text)}</b>", "cell", self.p.on(self.p.primary),
                                  raw=True, **over)
            return self._para(text, "cell", **over)

        data = [[_cell(h, i, header=True) for i, h in enumerate(headers)]]
        data += [[_cell(c, i) for i, c in enumerate(r)] for r in body]

        t = Table(data, colWidths=widths, repeatRows=1,
                  splitByRow=len(body) > _SPLIT_ROWS)
        tk = self.fmt.table
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), _hex(self.p.primary)),
            ("GRID", (0, 0), (-1, -1), tk.rule_pt, _hex(self.p.rule)),
            ("TOPPADDING", (0, 0), (-1, -1), tk.row_pad_v),
            ("BOTTOMPADDING", (0, 0), (-1, -1), tk.row_pad_v),
            ("LEFTPADDING", (0, 0), (-1, -1), tk.row_pad_h),
            ("RIGHTPADDING", (0, 0), (-1, -1), tk.row_pad_h),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if tk.band_rows:
            style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1),
                          [_hex(self.p.surface), _hex(self.p.surface_alt)]))
        for i, a in enumerate(align):
            if a != "LEFT":
                style.append(("ALIGN", (i, 0), (i, -1), a))
        t.setStyle(TableStyle(style))

        self.story.append(t if len(body) > _SPLIT_ROWS else KeepTogether(t))
        self.story.append(self._gap("block"))
        return self

    def _align(self, rows, n) -> List[str]:
        out = []
        for i in range(n):
            vals = [r[i] for r in rows if i < len(r) and str(r[i]).strip()]
            numeric = sum(1 for v in vals
                          if str(v).replace(",", "").replace("$", "").replace("%", "")
                          .replace("(", "").replace(")", "").replace(".", "").replace("-", "")
                          .isdigit())
            out.append("RIGHT" if vals and numeric >= 0.8 * len(vals) else "LEFT")
        return out

    def _widths(self, headers: Sequence[str], rows: Sequence[Sequence[str]],
                scale: float = 1.0) -> tuple:
        """Measured, not guessed. The skill asked the model to 'mentally check' whether a
        header fits, and a header wrapping to two lines is the clearest tell of a generated
        document.

        Returns (widths, fits). `fits` is False when even the floors — every figure and
        short label on one line — exceed the page at this font `scale`; the caller then
        retries smaller rather than wrapping numbers."""
        tk = self.fmt.table
        pad = 2 * tk.row_pad_h
        head_size, cell_size = tk.header_size * scale, tk.cell_size * scale
        numeric = [a != "LEFT" for a in self._align(rows, len(headers))]
        want, floors = [], []
        for i, h in enumerate(headers):
            head_w = pdfmetrics.stringWidth(h, self.bold, head_size) + pad
            cell_w = max(
                (pdfmetrics.stringWidth(str(r[i]), self.regular, cell_size)
                 for r in rows if i < len(r)),
                default=0.0,
            ) + pad
            # A header must never wrap; a long cell may, so it is capped.
            want.append(max(head_w, min(cell_w, 2.6 * inch), tk.min_col_in * inch))
            # A figure is never squeezed below its own width (a wrapped "$3,052." / "80"
            # is unreadable), nor a short label ("Year" / "1"); long prose absorbs the cut.
            floors.append(max(head_w, cell_w if numeric[i] else min(cell_w, 1.1 * inch)))

        avail = self.fmt.content_w_in * inch
        total = sum(want)
        if total <= avail:
            extra = (avail - total) / len(want)
            return [w + extra for w in want], True
        if sum(floors) > avail:
            return floors, False

        # Over budget: take the excess from columns with slack above their floor, and
        # never past it (a proportional cut larger than a column's slack is what once
        # squeezed "Year" to "Ye" / "ar").
        out = list(want)
        for _ in range(40):
            over = sum(out) - avail
            if over <= 0.5:
                break
            slack = [max(0.0, out[i] - floors[i]) for i in range(len(out))]
            pool = sum(slack)
            if pool <= 0.5:
                break
            for i in range(len(out)):
                out[i] -= min(slack[i], over * (slack[i] / pool))
        return out, True

    def chart(self, kind: str, categories, series, *, labels=None, title: str = "",
              height_in: float = 2.6, value_format: str = "%d",
              x_title: str = "", y_title: str = "") -> "Report":
        """A real chart from real numbers, in the document's own palette.

        `kind` is "bar", "line" or "donut". `x_title` and `y_title` say what the axes
        denote — a reader can see a bar is 412 tall, but not 412 of what. Reach for
        `image_gen_tool` only for genuine illustration — it costs an image-model call, an
        upload and a download, and it cannot plot a number.
        """
        from docgen.charts import check_series
        check_series(categories, series)
        from docgen import charts

        draw = {"bar": charts.bar, "line": charts.line, "donut": charts.donut}.get(kind)
        if draw is None:
            raise ValueError(f"unknown chart kind {kind!r}; use bar, line or donut")
        kw = dict(width_in=self.fmt.content_w_in, height_in=height_in,
                  palette=self.p, fmt=self.fmt, title=title)
        if kind == "donut":
            # A donut has no axes; its slice labels carry the categories.
            drawing = draw(categories, series, **{k: v for k, v in kw.items()})
        else:
            drawing = draw(categories, series, labels=labels, value_format=value_format,
                           x_title=x_title, y_title=y_title, **kw)
        self.story += [drawing, self._gap("block")]
        return self

    def page_break(self) -> "Report":
        self.story.append(PageBreak())
        return self

    def _gap(self, which: str) -> Spacer:
        return Spacer(1, self.fmt.gap_in[which] * inch)

    def spacer(self, which: str = "block") -> "Report":
        self.story.append(self._gap(which))
        return self

    # ── cover ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _wrap(text: str, font: str, size: float, max_w: float) -> List[str]:
        """Greedy word-wrap to a pixel width, for canvas text the platypus frame never sees."""
        lines, cur = [], ""
        for word in str(text).split():
            trial = f"{cur} {word}".strip()
            if not cur or pdfmetrics.stringWidth(trial, font, size) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    @staticmethod
    def _tracked(canvas, x, y, text, font, size, char_space, color) -> None:
        """Letter-spaced canvas text. Tracking lives on a text object, not the canvas.

        Wrapped in save/restore: `drawText` leaves the canvas's charSpace set, so without this
        every later `drawString` inherited the tracking — which pushed a full-width cover
        subtitle off the page.
        """
        canvas.saveState()
        to = canvas.beginText(x, y)
        to.setFont(font, size)
        to.setFillColor(_hex(color) if isinstance(color, str) else color)
        to.setCharSpace(char_space)
        to.textLine(str(text))
        canvas.drawText(to)
        canvas.restoreState()

    def _cover_motif(self, canvas, W: float, H: float) -> None:
        """The cover background design — a selectable, on-brand treatment (see `Report.cover`
        `motif`): circles, rings, dots, arcs, glow or none. All bleed off the top-right corner
        and sit behind the title. Coordinates are top-referenced (origin bottom-left)."""
        kind = self._cover_motif_kind
        if kind == "none":
            return
        berry, indigo, accent = "#5A2A38", self.p.emphasis, self.p.accent

        def disc(fx, fy, r_in, col, alpha):
            canvas.setFillColor(_hex(col))
            canvas.setFillAlpha(alpha)
            canvas.circle(W * fx, H * fy, r_in * inch, stroke=0, fill=1)

        if kind == "rings":
            canvas.setFillAlpha(1)
            for r_in, a in ((2.0, 0.55), (1.5, 0.46), (1.0, 0.38), (0.55, 0.30)):
                canvas.setStrokeColor(_hex(indigo))
                canvas.setStrokeAlpha(a)
                canvas.setLineWidth(2.0)
                canvas.circle(W * 1.02, H * 0.92, r_in * inch, stroke=1, fill=0)
            canvas.setStrokeAlpha(1)
        elif kind == "dots":
            for gx in range(6):
                for gy in range(5):
                    disc(0.62 + gx * 0.055, 0.94 - gy * 0.05, 0.045, indigo, 0.45)
        elif kind == "arcs":
            disc(1.06, 1.00, 2.3, indigo, 0.50)
            disc(1.14, 0.40, 1.7, berry, 0.46)
        elif kind == "glow":
            disc(1.02, 0.96, 2.0, indigo, 0.38)
            disc(0.98, 0.10, 1.7, berry, 0.32)
            disc(1.10, 0.52, 1.1, accent, 0.24)
        else:  # circles
            for fx, fy, r_in, col, alpha in (
                (0.86, 0.87, 1.55, indigo, 0.55),
                (1.00, 0.66, 1.15, berry, 0.55),
                (0.80, 0.53, 0.95, indigo, 0.42),
                (0.92, 0.31, 0.85, berry, 0.50),
            ):
                disc(fx, fy, r_in, col, alpha)
        canvas.setFillAlpha(1)

    def _draw_cover(self, canvas, doc) -> None:
        canvas.saveState()
        if self._cover_style == "custom":
            self._cover_custom(canvas)
        elif self._cover_style == "minimal":
            self._cover_minimal(canvas)
        elif self._cover_style == "editorial":
            self._cover_editorial(canvas)
        else:
            self._cover_dark(canvas)
        canvas.restoreState()

    @staticmethod
    def _is_dark(hex_color: str) -> bool:
        v = str(hex_color).lstrip("#")
        if len(v) != 6:
            return True
        r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 128

    def _cover_custom(self, canvas) -> None:
        W = self.fmt.page_w_in * inch
        H = self.fmt.page_h_in * inch

        # 1) Background — solid hex, or {"type":"gradient","from":..,"to":..,"angle":deg}.
        bg = self._cover_bg
        base = self.p.primary
        if isinstance(bg, dict) and str(bg.get("type", "")).lower() == "gradient":
            frm, to = _clean_hex(bg.get("from", self.p.primary)), _clean_hex(bg.get("to", self.p.emphasis))
            base = frm
            # A solid full-bleed rect under the gradient: the shading pattern itself is not a
            # rect pdfplumber reports, so without this the linter would not see a cover ground
            # and would fail the display-size title as off-scale.
            canvas.setFillColor(_hex(frm))
            canvas.rect(0, 0, W, H, stroke=0, fill=1)
            import math
            a = math.radians(float(bg.get("angle", 135)))
            dx, dy = math.cos(a), math.sin(a)
            x0, x1 = (0, W) if dx >= 0 else (W, 0)
            y0, y1 = (0, H) if dy >= 0 else (H, 0)
            canvas.linearGradient(x0, y0, x1, y1, [_hex(frm), _hex(to)], extend=True)
        else:
            base = _clean_hex(bg) if bg else self.p.primary
            canvas.setFillColor(_hex(base))
            canvas.rect(0, 0, W, H, stroke=0, fill=1)

        # 2) Decorative shapes, coordinates as page fractions with a top-left origin.
        self._draw_custom_shapes(canvas, W, H)

        # 3) Text — defaults by ground brightness, overridable per element via `ink`.
        dark = self._is_dark(base)
        d = (dict(wordmark="#FFFFFF", eyebrow=self.p.accent, title="#FFFFFF", rule=self.p.accent,
                  subtitle="#C9C2DA", meta_label=self.p.accent, meta_value="#D8D3E4", footer="#8A83A0")
             if dark else
             dict(wordmark=self.p.primary, eyebrow=self.p.ink(self.p.accent), title=self.p.text,
                  rule=self.p.accent, subtitle=self.p.muted, meta_label=self.p.ink(self.p.accent),
                  meta_value=self.p.text, footer=self.p.muted))
        for k, v in self._cover_ink.items():
            if k in d and v:
                d[k] = _clean_hex(v)
        self._cover_column(
            canvas, wordmark_c=d["wordmark"], eyebrow_c=d["eyebrow"], title_c=d["title"],
            rule_c=d["rule"], sub_c=d["subtitle"], label_c=d["meta_label"],
            value_c=d["meta_value"], footer_c=d["footer"])

    def _draw_custom_shapes(self, canvas, W: float, H: float) -> None:
        for sp in self._cover_shapes:
            if not isinstance(sp, dict):
                continue
            kind = str(sp.get("shape", "circle")).lower()
            color = _clean_hex(sp.get("color", self.p.emphasis))
            alpha = float(sp.get("alpha", 1.0))
            canvas.setFillColor(_hex(color))
            canvas.setStrokeColor(_hex(color))
            canvas.setFillAlpha(alpha)
            canvas.setStrokeAlpha(alpha)
            if kind in ("circle", "ring"):
                cx, cy = float(sp.get("cx", 0.5)) * W, (1 - float(sp.get("cy", 0.5))) * H
                r = float(sp.get("r", 0.15)) * W
                if kind == "ring":
                    canvas.setLineWidth(float(sp.get("width", 2.0)))
                    canvas.circle(cx, cy, r, stroke=1, fill=0)
                else:
                    canvas.circle(cx, cy, r, stroke=0, fill=1)
            elif kind == "rect":
                x = float(sp.get("x", 0.0)) * W
                hh = float(sp.get("h", 0.1)) * H
                y = (1 - float(sp.get("y", 0.0))) * H - hh
                canvas.rect(x, y, float(sp.get("w", 0.2)) * W, hh, stroke=0, fill=1)
            elif kind == "line":
                canvas.setLineWidth(float(sp.get("width", 2.0)))
                canvas.line(float(sp.get("x1", 0)) * W, (1 - float(sp.get("y1", 0))) * H,
                            float(sp.get("x2", 1)) * W, (1 - float(sp.get("y2", 0))) * H)
        canvas.setFillAlpha(1)
        canvas.setStrokeAlpha(1)

    def _cover_meta_and_footer(self, canvas, mL, *, label_c, value_c, footer_c) -> None:
        my = 1.55 * inch
        for label, value in reversed(list(self._cover_meta.items())):
            self._tracked(canvas, mL, my, str(label).upper(), self.bold, 8.5, 1.1, label_c)
            canvas.setFillColor(_hex(value_c))
            canvas.setFont(self.regular, 10)
            canvas.drawString(mL + 1.5 * inch, my, str(value))
            my += 0.28 * inch
        self._tracked(canvas, mL, 0.6 * inch, self.footer_text[:90], self.regular, 9, 1.4, footer_c)

    def _cover_column(self, canvas, *, wordmark_c, eyebrow_c, title_c, rule_c, sub_c,
                      label_c, value_c, footer_c) -> None:
        """The shared left-column cover layout — wordmark, eyebrow, title, rule, subtitle,
        metadata — painted in whatever colours the style hands it. Ground and motif are the
        caller's job."""
        W = self.fmt.page_w_in * inch
        H = self.fmt.page_h_in * inch
        mL = self.fmt.margin_in["left"] * inch
        max_w = W * 0.60 - mL

        if self._cover_wordmark:
            canvas.setFillColor(_hex(wordmark_c))
            canvas.setFont(self.bold, 21)
            canvas.drawString(mL, H - 0.95 * inch, self._cover_wordmark)

        self._tracked(canvas, mL, H * 0.635, self._cover_kicker, self.bold, 11, 2.6, eyebrow_c)

        title_size = 40
        y = H * 0.635 - 0.42 * inch
        canvas.setFillColor(_hex(title_c))
        canvas.setFont(self.bold, title_size)
        for line in self._wrap(self.title, self.bold, title_size, max_w):
            y -= title_size * 1.06
            canvas.drawString(mL, y, line)

        y -= 0.30 * inch
        canvas.setFillColor(_hex(rule_c))
        canvas.rect(mL, y, 1.45 * inch, 3, stroke=0, fill=1)

        if self.subtitle:
            sub_size = 13
            y -= 0.34 * inch
            canvas.setFillColor(_hex(sub_c))
            canvas.setFont(self.regular, sub_size)
            for line in self._wrap(self.subtitle, self.regular, sub_size, max_w):
                y -= sub_size * 1.4
                canvas.drawString(mL, y, line)

        self._cover_meta_and_footer(canvas, mL, label_c=label_c, value_c=value_c, footer_c=footer_c)

    def _cover_dark(self, canvas) -> None:
        W, H = self.fmt.page_w_in * inch, self.fmt.page_h_in * inch
        p = self.p
        canvas.setFillColor(_hex(p.primary))
        canvas.rect(0, 0, W, H, stroke=0, fill=1)
        self._cover_motif(canvas, W, H)
        self._cover_column(
            canvas, wordmark_c="#FFFFFF", eyebrow_c=p.accent, title_c="#FFFFFF",
            rule_c=p.accent, sub_c="#C9C2DA", label_c=p.accent, value_c="#D8D3E4",
            footer_c="#8A83A0")

    def _cover_minimal(self, canvas) -> None:
        W, H = self.fmt.page_w_in * inch, self.fmt.page_h_in * inch
        p = self.p
        canvas.setFillColor(_hex(_COVER_LIGHT))
        canvas.rect(0, 0, W, H, stroke=0, fill=1)
        self._cover_column(
            canvas, wordmark_c=p.primary, eyebrow_c=p.ink(p.accent), title_c=p.text,
            rule_c=p.accent, sub_c=p.muted, label_c=p.ink(p.accent), value_c=p.text,
            footer_c=p.muted)

    def _cover_editorial(self, canvas) -> None:
        W = self.fmt.page_w_in * inch
        H = self.fmt.page_h_in * inch
        mL = self.fmt.margin_in["left"] * inch
        p = self.p
        max_w = W - 2 * mL

        canvas.setFillColor(_hex(_COVER_LIGHT))
        canvas.rect(0, 0, W, H, stroke=0, fill=1)

        if self._cover_wordmark:
            canvas.setFillColor(_hex(p.primary))
            canvas.setFont(self.bold, 21)
            canvas.drawString(mL, H - 0.95 * inch, self._cover_wordmark)

        # A full-width colour band sized to hold the eyebrow and the wrapped title.
        title_size = 38
        lines = self._wrap(self.title, self.bold, title_size, max_w)
        band_h = 0.5 * inch + len(lines) * title_size * 1.06 + 0.3 * inch
        band_top = H * 0.60 - band_h + 0.3 * inch
        canvas.setFillColor(_hex(p.primary))
        canvas.rect(0, band_top, W, band_h, stroke=0, fill=1)

        self._tracked(canvas, mL, band_top + band_h - 0.42 * inch,
                      self._cover_kicker, self.bold, 11, 2.6, p.accent)
        y = band_top + band_h - 0.42 * inch - 0.32 * inch
        canvas.setFillColor(colors.white)
        canvas.setFont(self.bold, title_size)
        for line in lines:
            y -= title_size * 1.06
            canvas.drawString(mL, y, line)

        if self.subtitle:
            sub_size = 13
            y = band_top - 0.36 * inch
            canvas.setFillColor(_hex(p.muted))
            canvas.setFont(self.regular, sub_size)
            for line in self._wrap(self.subtitle, self.regular, sub_size, max_w):
                canvas.drawString(mL, y, line)
                y -= sub_size * 1.4

        self._cover_meta_and_footer(canvas, mL, label_c=p.ink(p.accent),
                                    value_c=p.text, footer_c=p.muted)

    # ── furniture ─────────────────────────────────────────────────────────────
    def _furniture(self, canvas, doc):
        canvas.saveState()
        t = self.fmt.scale["footer"]
        m = self.fmt.margin_in
        canvas.setFont(self.regular, t.size)
        canvas.setFillColor(_hex(self.p.muted))
        y = (m["bottom"] * inch) / 2
        canvas.drawString(m["left"] * inch, y, self.footer_text[:90])
        canvas.drawRightString(
            (self.fmt.page_w_in - m["right"]) * inch, y, f"Page {doc.page}")
        if doc.page > 1 and self.title:
            top = (self.fmt.page_h_in - m["top"] / 2) * inch
            canvas.drawString(m["left"] * inch, top, self.title[:90])
            canvas.setStrokeColor(_hex(self.p.rule))
            canvas.setLineWidth(0.5)
            canvas.line(m["left"] * inch, top - 4,
                        (self.fmt.page_w_in - m["right"]) * inch, top - 4)
        canvas.restoreState()

    def _snap(self, size: float) -> float:
        """The largest size on this format's type scale that is no bigger than `size`, so a
        shrunk figure stays on the scale the layout check enforces (font.off_scale)."""
        steps = sorted(set(self.fmt.sizes) | {self.fmt.table.cell_size})
        fitting = [s for s in steps if s <= size + 0.01]
        return fitting[-1] if fitting else steps[0]

    @staticmethod
    def _bind_headings(story: list) -> list:
        """Glue each run of keepWithNext flowables (eyebrow, headings) to the block after.

        reportlab's own keepWithNext stops at a container: a short table is wrapped in
        KeepTogether so it never splits, and the template will not merge a heading into
        that, so "YEAR-BY-YEAR COST TABLE" still ended a page alone. Doing it here, with
        the container's contents unwrapped into one KeepTogether, binds them for real.
        """
        out, i = [], 0
        while i < len(story):
            if not getattr(story[i], "keepWithNext", False):
                out.append(story[i])
                i += 1
                continue
            run = []
            while i < len(story) and getattr(story[i], "keepWithNext", False):
                run.append(story[i])
                i += 1
            if i == len(story):
                out.extend(run)
                break
            nxt = story[i]
            i += 1
            inner = list(nxt._content) if isinstance(nxt, KeepTogether) else [nxt]
            for f in run:  # bound now; don't let the template regroup them inside
                f.keepWithNext = False
            out.append(KeepTogether(run + inner))
        return out

    def save(self) -> Path:
        if not self.story:
            raise ValueError("nothing was added to the report")
        first = self._draw_cover if self._has_cover else self._furniture
        self.doc.build(self._bind_headings(self.story), onFirstPage=first,
                       onLaterPages=self._furniture)
        return self.path
