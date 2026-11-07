"""Build a deck from content, and refuse to place anything that will not fit.

Two defects this replaces. The type scale gave heading, body, caption and footer the same
Pt(14), so nothing had hierarchy; and the alignment checker skipped any shape named
"rectangle", which is every card python-pptx auto-names, so overflow was never caught.

The slide cursor is the other half. The skill told the model to build four slides, save,
reload and continue — which cost a model turn per batch and accounted for most of the repeat
builds measured in production. A deck is one object here, built in one call.

    from docgen.deck import Deck

    d = Deck("q1.pptx", footer="PriceIQ · Q1 2026")
    s = d.slide("Where the money goes")
    s.kpi_row([("$24.5M", "Addressable"), ("38%", "Consulting")])
    s.bullets(["Consulting is the least contracted category."])
    d.save()
"""

from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from docgen import measure
from docgen import tokens as T
from docgen.palette import DEFAULT, Palette, active


# The checker recognises deck furniture by this exact name. The previous checker matched
# the substring "rectangle", which is what python-pptx calls every card and tile.
FOOTER_NAME = "docgen-footer"
# Everything the design system draws as furniture carries this prefix, so the
# margin and fill checks can tell a deliberate full-bleed band from content that
# overflowed. `docgen.checks.native_pptx` reads the same constant.
DECOR_PREFIX = "docgen-"

# A light cover ground that is still visibly non-white, so a light-styled cover renders a
# full-bleed fill the linter's `_is_cover` can detect (a pure-white ground reads as invisible).
_COVER_LIGHT = "#F1F5FB"  # light cover ground, a tint of the PriceIQ navy


class LayoutError(ValueError):
    """Raised rather than letting content run off the slide."""


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(_clean_hex(hex_color).lstrip("#").upper())


def _clean_hex(value, fallback: str = "#150F26") -> str:
    """Normalise a caller colour to #RRGGBB, falling back on anything unparseable."""
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


def _is_dark_hex(hex_color: str) -> bool:
    v = _clean_hex(hex_color).lstrip("#")
    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


class Slide:
    def __init__(self, deck: "Deck", raw, title: Optional[str]):
        self.deck = deck
        self.raw = raw
        self.fmt = deck.fmt
        self.p = deck.p
        self.y = self.fmt.margin_in["top"]
        self.left = self.fmt.margin_in["left"]
        self.width = self.fmt.content_w_in
        # Muted grey is right on white and invisible on a full-bleed cover; the archetype
        # that paints the ground says what the furniture on it should be.
        self.footer_color = self.p.muted
        # How many neutral blocks this slide has drawn. A block with no semantic tone takes
        # the next colour from the palette sequence rather than the one accent every block
        # used to share, which is what made a row of four cards four identical boxes.
        #
        # Not `_decor`: that is the band/rule drawing method on this class, and an int
        # attribute of the same name shadows it on the instance — every `self._decor(...)`
        # call would raise "'int' object is not callable".
        self._accent_index = 0
        if title:
            self.title(title)

    @property
    def _bottom(self) -> float:
        return (self.fmt.page_h_in - self.fmt.margin_in["bottom"]
                - self.fmt.gap_in["footer_h"])

    def _room(self, height: float, what: str) -> None:
        if self.y + height > self._bottom + 1e-6:
            raise LayoutError(
                f"{what} needs {height:.2f}in and only "
                f"{max(0.0, self._bottom - self.y):.2f}in is left on this slide — "
                f"start a new slide with deck.slide() instead of overflowing"
            )

    def _lines_for(self, text: str, role: str, width: float) -> int:
        t = self.fmt.scale[role]
        return measure.lines(text, t.size, width, t.bold)

    def _height_for(self, text: str, role: str, width: float) -> float:
        t = self.fmt.scale[role]
        return (t.line_pt * self._lines_for(text, role, width) + t.space_after) / 72

    def _textbox(self, text: str, role: str, *, left=None, width=None, height=None,
                 color=None, align=PP_ALIGN.LEFT, advance=True):
        t = self.fmt.scale[role]
        left = self.left if left is None else left
        width = self.width if width is None else width
        height = self._height_for(text, role, width) if height is None else height
        if advance:
            self._room(height, f"{role} text")
        box = self.raw.shapes.add_textbox(
            Inches(left), Inches(self.y), Inches(width), Inches(height))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = str(text)
        para = tf.paragraphs[0]
        para.alignment = align
        run = para.runs[0]
        run.font.size = Pt(t.size)
        run.font.bold = t.bold
        run.font.name = self.fmt.font
        run.font.color.rgb = _rgb(color or self.p.text)
        if advance:
            self.y += height
        return box

    # ── decoration ────────────────────────────────────────────────────────────
    def _decor(self, left, top, width, height, color, *, kind="band"):
        """A shape the design system owns: named so the checks know it is furniture.

        Full-bleed is outside the margins by definition — that is what full-bleed means — so
        the margin checks have to be able to tell a deliberate band from content that escaped.
        They key on the `docgen-` prefix."""
        shape = self.raw.shapes.add_shape(
            1, Inches(left), Inches(top), Inches(width), Inches(height))
        shape.name = f"{DECOR_PREFIX}{kind}"
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(color)
        shape.line.fill.background()
        shape.shadow.inherit = False
        return shape

    def band(self, height_in: float, color: Optional[str] = None, *, top: float = 0.0) -> "Slide":
        """A full-bleed horizontal band, edge to edge. Drawn behind whatever follows."""
        self._decor(0.0, top, self.fmt.page_w_in, height_in, color or self.p.band)
        return self

    def rail(self, color: Optional[str] = None, *, width_pt: float = 6.0) -> "Slide":
        """A full-height accent rail down the left edge — the cheapest way to stop a deck of
        white slides reading as a stack of blank pages."""
        self._decor(0.0, 0.0, width_pt / 72, self.fmt.page_h_in,
                    color or self.p.primary, kind="rail")
        return self

    @staticmethod
    def _alpha(element, alpha_pct: float):
        from pptx.oxml.ns import qn
        if element is None:
            return
        # Search descendants, so both a solidFill and a line's nested srgbClr are reached.
        srgb = element.find(".//" + qn("a:srgbClr"))
        if srgb is None and element.tag == qn("a:srgbClr"):
            srgb = element
        if srgb is not None:
            srgb.append(srgb.makeelement(qn("a:alpha"), {"val": str(int(alpha_pct * 1000))}))

    def _oval(self, cx: float, cy: float, r: float, color: str, alpha_pct: float,
              *, fill: bool = True, line_pt: float = 0.0):
        """A translucent circle centred on (cx, cy), radius r inches — filled, or an outline
        ring when `fill=False` and `line_pt` is set. Named as furniture so the margin checks
        let it bleed off the edge."""
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.oxml.ns import qn

        shape = self.raw.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(cx - r), Inches(cy - r), Inches(2 * r), Inches(2 * r))
        shape.name = f"{DECOR_PREFIX}motif"
        shape.shadow.inherit = False
        if fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = _rgb(color)
            self._alpha(shape._element.spPr.find(qn("a:solidFill")), alpha_pct)
        else:
            shape.fill.background()
        if line_pt:
            shape.line.color.rgb = _rgb(color)
            shape.line.width = Pt(line_pt)
            self._alpha(shape._element.spPr.find(qn("a:ln")), alpha_pct)
        else:
            shape.line.fill.background()
        return shape

    def cover_motif(self, kind: str = "circles") -> "Slide":
        """The cover background design — a selectable, on-brand treatment, not one fixed look.

        `kind`: circles (overlapping translucent discs), rings (concentric outlines), dots (a
        dot grid), arcs (two big soft discs bleeding off the corner), glow (a quiet corner
        wash), or none. All bleed off the top-right and sit behind the title.
        """
        kind = str(kind or "circles").strip().lower()
        if kind == "none":
            return self
        w, h = self.fmt.page_w_in, self.fmt.page_h_in
        berry, indigo, accent = "#5A2A38", self.p.emphasis, self.p.accent

        if kind == "rings":
            for r, a in ((2.7, 55), (2.0, 46), (1.35, 38), (0.75, 30)):
                self._oval(w * 1.02, h * 0.08, r, indigo, a, fill=False, line_pt=2.5)
        elif kind == "dots":
            for gx in range(7):
                for gy in range(5):
                    self._oval(w * 0.60 + gx * 0.42, h * 0.10 + gy * 0.42, 0.06, indigo, 45)
        elif kind == "arcs":
            self._oval(w * 1.06, h * 0.00, 3.0, indigo, 50)
            self._oval(w * 1.14, h * 0.66, 2.3, berry, 46)
        elif kind == "glow":
            self._oval(w * 1.02, h * 0.04, 2.6, indigo, 38)
            self._oval(w * 0.98, h * 0.92, 2.2, berry, 32)
            self._oval(w * 1.10, h * 0.48, 1.4, accent, 24)
        else:  # circles
            for cx, cy, r, col, alpha in (
                (w * 0.92, h * 0.06, 2.1, indigo, 55),
                (w * 1.00, h * 0.50, 1.5, berry, 55),
                (w * 0.80, h * 0.30, 1.15, indigo, 42),
                (w * 0.94, h * 0.82, 1.05, berry, 50),
            ):
                self._oval(cx, cy, r, col, alpha)
        return self

    # ── content ───────────────────────────────────────────────────────────────
    def title(self, text: str) -> "Slide":
        self._textbox(text, "title")
        # A short accent rule under the title, the width of the type rather than the measure:
        # it reads as a deliberate mark instead of a divider.
        rule_w = min(self.width, max(1.1, measure.natural_width_in(
            text, self.fmt.scale["title"].size, True) * 0.22))
        self._decor(self.left, self.y + 0.04, rule_w, 3.5 / 72, self.p.primary, kind="rule")
        self.y += self.fmt.gap_in["block"]
        return self

    def section(self, text: str) -> "Slide":
        self._textbox(text, "section")
        return self

    def body(self, text: str) -> "Slide":
        self._textbox(text, "body")
        return self

    def caption(self, text: str) -> "Slide":
        self._textbox(text, "caption", color=self.p.muted)
        return self

    def bullets(self, items: Iterable[str], columns: Optional[int] = None) -> "Slide":
        """Bullets, flowed into columns when the measure is too wide to read.

        A 13.3in slide at 11pt body runs to 177 characters a line. The typographic optimum
        is 45-90 and the eye loses the return sweep past about 100, so a full-measure bullet
        on a slide is close to twice the readable ceiling. Two columns bring it to 89 — and
        the same slide then carries twice the words in the same height, which is most of the
        gap between a generated deck at 116 words a slide and the reference deck at 253.

        Pass `columns=1` for something that genuinely has to run the full width."""
        items = [str(i) for i in items if str(i).strip()]
        if not items:
            return self
        if columns is None:
            columns = measure.columns_for(self.width, self.fmt.scale["bullet"].size)
        columns = max(1, min(int(columns), len(items)))
        if columns == 1:
            for item in items:
                self._textbox(f"•  {item}", "bullet")
            return self

        gutter = self.fmt.gutter_in
        width = (self.width - gutter * (columns - 1)) / columns
        heights = [self._height_for(f"•  {i}", "bullet", width) for i in items]

        # Fill each column to its share of the total rather than dealing round-robin, so the
        # columns finish level and the slide does not end on a ragged step.
        target = sum(heights) / columns
        buckets: List[List[int]] = [[] for _ in range(columns)]
        col, run = 0, 0.0
        for index, h in enumerate(heights):
            if col < columns - 1 and run > 0 and run + h / 2 > target:
                col, run = col + 1, 0.0
            buckets[col].append(index)
            run += h

        tallest = max(sum(heights[i] for i in b) for b in buckets) if any(buckets) else 0.0
        self._room(tallest, "bullets")

        start = self.y
        for c, bucket in enumerate(buckets):
            self.y = start
            left = self.left + c * (width + gutter)
            for i in bucket:
                self._textbox(f"•  {items[i]}", "bullet", left=left, width=width)
        self.y = start + tallest
        return self

    def kpi_row(self, pairs: Sequence[Sequence[str]]) -> "Slide":
        pairs = list(pairs)
        if not pairs:
            return self
        gutter = self.fmt.gutter_in
        tile_w = (self.width - gutter * (len(pairs) - 1)) / len(pairs)
        vt, lt = self.fmt.scale["kpi_value"], self.fmt.scale["kpi_label"]
        pad = self.fmt.pad_pt["card"] / 72
        # The tile used to be exactly two lines tall whatever the label said. At five tiles
        # a 2.31in column wraps "Change failure rate across all services" onto a second line
        # and it rendered outside the tile — invisible in the file's own geometry, so it
        # surfaced only as unexplained overlap in the rendered pass.
        inner = tile_w - 2 * pad
        # One common value size at which the longest figure fits its tile on one line
        # (never below 45%): a wrapped "$1,281,572." / "80" also overflowed the tile rule.
        # 12% headroom: a deck is re-rendered with the viewer's fonts, and a substitute
        # for Inter (PowerPoint without it, LibreOffice elsewhere) runs wider.
        longest = max(measure.width_pt(str(v), vt.size, True) for v, _ in pairs)
        value_size = vt.size * max(0.45, min(1.0, 0.88 * inner * 72 / longest)) if longest else vt.size
        # Snap down onto the type scale the layout check enforces (font.off_scale).
        value_size = max([z for z in self.fmt.sizes if z <= value_size + 0.01] or [min(self.fmt.sizes)])
        value_line = vt.line_pt * value_size / vt.size
        rows = max(measure.lines(v, value_size, inner, True) * value_line
                   + measure.lines(l, lt.size, inner) * lt.line_pt
                   for v, l in pairs)
        height = rows / 72 + 2 * pad
        self._room(height, "KPI row")

        for i, (value, label) in enumerate(pairs):
            # Each tile its own colour — fill, top rule and figure — rather than a grey tile
            # with only a 3pt rule to tell it from its neighbour.
            accent = self._next_accent("info")
            x = self.left + i * (tile_w + gutter)
            tile = self.raw.shapes.add_shape(
                1, Inches(x), Inches(self.y), Inches(tile_w), Inches(height))
            tile.fill.solid()
            tile.fill.fore_color.rgb = _rgb(self.p.tint(accent))
            tile.line.fill.background()
            tile.shadow.inherit = False
            # A rule across the top of each tile. Without it a row of tiles reads as one flat
            # grey strip with numbers on it rather than as separate cards, which is most of
            # why a generated deck looks plainer than a made one.
            self._decor(x, self.y, tile_w, 3.0 / 72, accent, kind="tilerule")
            tf = tile.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = Pt(self.fmt.pad_pt["card"])
            tf.margin_top = tf.margin_bottom = Pt(self.fmt.pad_pt["card"] / 2)
            tf.text = str(value)
            r = tf.paragraphs[0].runs[0]
            r.font.size, r.font.bold, r.font.name = Pt(value_size), True, self.fmt.font
            r.font.color.rgb = _rgb(self.p.ink(accent))
            para = tf.add_paragraph()
            run = para.add_run()
            run.text = str(label)
            run.font.size, run.font.name = Pt(lt.size), self.fmt.font
            run.font.color.rgb = _rgb(self.p.muted)
        self.y += height + self.fmt.gap_in["block"]
        return self

    def card(self, text: str, *, tone: str = "info", width: Optional[float] = None) -> "Slide":
        accent = self._next_accent(tone)
        width = width or self.width
        pad = self.fmt.pad_pt["card"] / 72
        height = self._height_for(text, "body", width - 2 * pad) + 2 * pad
        self._room(height, "card")
        shape = self.raw.shapes.add_shape(
            5, Inches(self.left), Inches(self.y), Inches(width), Inches(height))
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(self.p.tint(accent))
        shape.line.color.rgb = _rgb(accent)
        shape.line.width = Pt(1.5)
        shape.shadow.inherit = False
        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Pt(self.fmt.pad_pt["card"])
        tf.margin_top = tf.margin_bottom = Pt(self.fmt.pad_pt["card"])
        tf.text = str(text)
        run = tf.paragraphs[0].runs[0]
        t = self.fmt.scale["body"]
        run.font.size, run.font.name = Pt(t.size), self.fmt.font
        run.font.color.rgb = _rgb(self.p.text)
        self.y += height + self.fmt.gap_in["block"]
        return self

    def columns(self, items: Sequence, *, tone: str = "info", fill: bool = False) -> "Slide":
        """A row of cards side by side, on the format's own grid.

        `card()` always draws at `self.left` and advances `y`, so a slide could only ever
        stack — and a deck built that way lands around 10 shapes and 120 words per slide
        against the 38 and 252 of the reference deck this system exists to match. Columns
        are how the reference gets there: three or four small composed blocks across the
        measure rather than one wide one.

        Each item is either a string, or a `(heading, body)` pair — the heading sets in the
        subhead role so the card reads as a titled block rather than a paragraph in a box.

        `fill=True` stretches the row down to the content bottom. A row of cards otherwise
        hugs its text and leaves the lower half of the slide empty — the single biggest reason
        a generated deck reads as thinner than the reference, whose paired cards run tall. Use
        it when the cards are the slide's main content and carry a real paragraph each.
        """
        items = [i for i in items if i]
        if not items:
            return self
        pairs = [(i, "") if isinstance(i, str) else (i[0], i[1] if len(i) > 1 else "")
                 for i in items]

        gutter = self.fmt.gutter_in
        width = (self.width - gutter * (len(pairs) - 1)) / len(pairs)
        pad = self.fmt.pad_pt["card"] / 72
        inner = width - 2 * pad

        height = 0.0
        for head, body in pairs:
            need = self._height_for(str(head), "subhead" if body else "body", inner)
            if body:
                need += self._height_for(str(body), "body", inner)
            height = max(height, need)
        height += 2 * pad
        self._room(height, "columns")
        if fill:
            height = max(height, self._bottom - self.y)

        for index, (head, body) in enumerate(pairs):
            # Inside the loop on purpose. This was resolved once above and painted onto every
            # card, so a four-card row drew four identical boxes — the measured symptom was a
            # nine-slide deck whose ten shape fills were all #F5F7FA.
            accent = self._next_accent(tone)
            left = self.left + index * (width + gutter)
            shape = self.raw.shapes.add_shape(
                5, Inches(left), Inches(self.y), Inches(width), Inches(height))
            shape.fill.solid()
            shape.fill.fore_color.rgb = _rgb(self.p.tint(accent))
            shape.line.color.rgb = _rgb(accent)
            shape.line.width = Pt(1.5)
            shape.shadow.inherit = False

            tf = shape.text_frame
            tf.word_wrap = True
            # Top-anchored, so a filled (tall) card keeps its heading and body at the top edge
            # instead of floating them in the vertical middle of an empty box.
            tf.vertical_anchor = MSO_ANCHOR.TOP
            tf.margin_left = tf.margin_right = Pt(self.fmt.pad_pt["card"])
            tf.margin_top = tf.margin_bottom = Pt(self.fmt.pad_pt["card"])

            head_role = "subhead" if body else "body"
            tf.text = str(head)
            run = tf.paragraphs[0].runs[0]
            ht = self.fmt.scale[head_role]
            run.font.size, run.font.name = Pt(ht.size), self.fmt.font
            run.font.bold = ht.bold
            # The heading carries the card's own colour, so the block reads as coloured
            # rather than as a grey box with a coloured edge.
            run.font.color.rgb = _rgb(self.p.ink(accent) if body else self.p.text)

            if body:
                para = tf.add_paragraph()
                para.text = str(body)
                bt = self.fmt.scale["body"]
                for r in para.runs:
                    r.font.size, r.font.name = Pt(bt.size), self.fmt.font
                    r.font.color.rgb = _rgb(self.p.text)

        self.y += height + self.fmt.gap_in["block"]
        return self

    def _tone(self, tone: str) -> str:
        return {"good": self.p.good, "warn": self.p.warn,
                "bad": self.p.bad}.get(tone, self.p.accent)

    def _next_accent(self, tone: str) -> str:
        """The colour for one block: its status if it has one, else the next decorative hue.

        An explicit tone still wins outright — "good" is green on every slide of every deck,
        because a status that shifted colour by position would be unreadable. Only the
        neutral default advances, so meaning stays fixed and decoration stays varied.
        """
        semantic = {"good": self.p.good, "warn": self.p.warn, "bad": self.p.bad}.get(tone)
        if semantic:
            return semantic
        colour = self.deck.series_color(self._accent_index)
        self._accent_index += 1
        return colour

    def callout(self, text: str, tone: str = "info") -> "Slide":
        """The same block as `Report.callout` and `Doc.callout`, under the same name — a
        deck and its accompanying report should not need two different calls for one idea."""
        return self.card(text, tone=tone)

    def timeline(self, items: Sequence, *, tone: str = "info") -> "Slide":
        """Phases left to right, each under a filled label chip, on one connecting rule.

        A roadmap written as bullets stops being a roadmap: the reader can no longer see
        that the phases are ordered, or where one ends and the next starts."""
        rows = []
        for item in items or []:
            if not item:
                continue
            if isinstance(item, str):
                rows.append(("", item, ""))
            else:
                item = list(item)
                rows.append((str(item[0]) if item else "",
                             str(item[1]) if len(item) > 1 else "",
                             str(item[2]) if len(item) > 2 else ""))
        if not rows:
            return self

        gutter = self.fmt.gutter_in
        width = (self.width - gutter * (len(rows) - 1)) / len(rows)
        pad = self.fmt.pad_pt["card"] / 72
        chip_h = (self.fmt.scale["caption"].line_pt + 2 * self.fmt.pad_pt["pill"]) / 72

        body_h = 0.0
        for _, head, body in rows:
            need = self._height_for(head, "subhead", width - 2 * pad) if head else 0.0
            if body:
                need += self._height_for(body, "body", width - 2 * pad)
            body_h = max(body_h, need)
        total = chip_h + body_h + 2 * pad + 0.10
        self._room(total, "timeline")

        rule_y = self.y + chip_h / 2
        rule = self.raw.shapes.add_shape(
            1, Inches(self.left), Inches(rule_y), Inches(self.width), Pt(1.25))
        rule.fill.solid()
        rule.fill.fore_color.rgb = _rgb(self.p.rule)
        rule.line.fill.background()
        rule.shadow.inherit = False

        for index, (label, head, body) in enumerate(rows):
            # Phases are ordered, so they read best as a progression of colours rather than
            # one colour repeated — the chip is the only place a reader can see the boundary.
            accent = self._next_accent(tone)
            left = self.left + index * (width + gutter)

            chip_w = min(width, max(0.9, measure.natural_width_in(
                label or " ", self.fmt.scale["caption"].size, True) + 0.40))
            chip = self.raw.shapes.add_shape(
                5, Inches(left), Inches(self.y), Inches(chip_w), Inches(chip_h))
            chip.fill.solid()
            chip.fill.fore_color.rgb = _rgb(accent)
            chip.line.fill.background()
            chip.shadow.inherit = False
            ctf = chip.text_frame
            ctf.word_wrap = False
            ctf.margin_left = ctf.margin_right = Pt(self.fmt.pad_pt["pill"])
            ctf.margin_top = ctf.margin_bottom = Pt(0)
            ctf.text = label
            crun = ctf.paragraphs[0].runs[0]
            crun.font.size = Pt(self.fmt.scale["caption"].size)
            crun.font.name, crun.font.bold = self.fmt.font, True
            crun.font.color.rgb = _rgb(self.p.on(accent))

            card = self.raw.shapes.add_shape(
                5, Inches(left), Inches(self.y + chip_h + 0.10),
                Inches(width), Inches(body_h + 2 * pad))
            card.fill.solid()
            card.fill.fore_color.rgb = _rgb(self.p.tint(accent))
            card.line.fill.background()
            card.shadow.inherit = False
            tf = card.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = Pt(self.fmt.pad_pt["card"])
            tf.margin_top = tf.margin_bottom = Pt(self.fmt.pad_pt["card"])
            tf.text = head
            hrun = tf.paragraphs[0].runs[0]
            ht = self.fmt.scale["subhead"]
            hrun.font.size, hrun.font.name = Pt(ht.size), self.fmt.font
            hrun.font.bold = True
            hrun.font.color.rgb = _rgb(self.p.ink(accent))
            if body:
                para = tf.add_paragraph()
                para.text = body
                bt = self.fmt.scale["body"]
                for r in para.runs:
                    r.font.size, r.font.name = Pt(bt.size), self.fmt.font
                    r.font.color.rgb = _rgb(self.p.text)

        self.y += total + self.fmt.gap_in["block"]
        return self

    def steps(self, items: Sequence[str], *, tone: str = "info") -> "Slide":
        """A numbered process across the slide — the same idea as `timeline`, numbered."""
        items = [str(i) for i in items if i]
        if not items:
            return self
        return self.timeline([(str(n), text, "") for n, text in enumerate(items, start=1)],
                             tone=tone)

    def quote(self, text: str, attribution: str = "") -> "Slide":
        """A pull quote, set large against the accent rule."""
        pad = self.fmt.pad_pt["card"] / 72
        height = self._height_for(text, "subhead", self.width - 2 * pad) + 2 * pad
        if attribution:
            height += self._height_for(attribution, "caption", self.width - 2 * pad)
        self._room(height, "quote")

        shape = self.raw.shapes.add_shape(
            5, Inches(self.left), Inches(self.y), Inches(self.width), Inches(height))
        shape.fill.background()
        shape.line.fill.background()
        shape.shadow.inherit = False

        bar = self.raw.shapes.add_shape(
            1, Inches(self.left), Inches(self.y), Pt(3), Inches(height))
        bar.fill.solid()
        bar.fill.fore_color.rgb = _rgb(self.p.accent)
        bar.line.fill.background()
        bar.shadow.inherit = False

        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Pt(self.fmt.pad_pt["card"] + 6)
        tf.margin_right = tf.margin_top = tf.margin_bottom = Pt(self.fmt.pad_pt["card"])
        tf.text = str(text)
        run = tf.paragraphs[0].runs[0]
        qt = self.fmt.scale["subhead"]
        run.font.size, run.font.name = Pt(qt.size), self.fmt.font
        run.font.italic = True
        run.font.color.rgb = _rgb(self.p.text)
        if attribution:
            para = tf.add_paragraph()
            para.text = f"\u2014 {attribution}"
            for r in para.runs:
                r.font.size = Pt(self.fmt.scale["caption"].size)
                r.font.name = self.fmt.font
                r.font.color.rgb = _rgb(self.p.muted)

        self.y += height + self.fmt.gap_in["block"]
        return self

    def table(self, headers: Sequence[str], rows: Sequence[Sequence]) -> "Slide":
        headers = [str(h) for h in headers]
        rows = [[("" if c is None else str(c)) for c in r] for r in rows]
        tk = self.fmt.table
        widths = self._widths(headers, rows)
        # Every row used to be one line tall. `_widths` scales the columns to fill the
        # measure exactly, so a wide comparison table is squeezed — five columns of prose
        # came out at 52% of their natural width — and then every cell wrapped onto a second
        # line that rendered past the declared table height.
        inner = [w - 2 * tk.row_pad_h / 72 for w in widths]
        heights = [
            max((measure.lines(cell, size, inner[c], bold)
                 for c, cell in enumerate(row) if c < len(inner)), default=1)
            * self.fmt.scale["body"].line_pt + 2 * tk.row_pad_v
            for row, size, bold in
            [(headers, tk.header_size, True)] + [(r, tk.cell_size, False) for r in rows]
        ]
        height = sum(heights) / 72
        self._room(height, f"a {len(rows)}-row table")

        shape = self.raw.shapes.add_table(
            len(rows) + 1, len(headers), Inches(self.left), Inches(self.y),
            Inches(self.width), Inches(height))
        table = shape.table
        for c, width in enumerate(widths):
            table.columns[c].width = Emu(int(width * T.EMU_PER_INCH))
        for r, h in enumerate(heights):
            table.rows[r].height = Emu(int(h / 72 * T.EMU_PER_INCH))

        head_fg = self.p.on(self.p.primary)
        for c, text in enumerate(headers):
            self._cell(table.cell(0, c), text, tk.header_size, bold=True,
                       fill=self.p.primary, color=head_fg)
        for r, row in enumerate(rows, start=1):
            band = self.p.surface_alt if (tk.band_rows and r % 2 == 0) else self.p.surface
            for c in range(len(headers)):
                self._cell(table.cell(r, c), row[c] if c < len(row) else "",
                           tk.cell_size, fill=band, color=self.p.text)
        self.y += height + self.fmt.gap_in["block"]
        return self

    def _cell(self, cell, text, size, *, bold=False, fill=None, color=None):
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(fill or self.p.surface)
        cell.margin_left = cell.margin_right = Pt(self.fmt.table.row_pad_h)
        cell.margin_top = cell.margin_bottom = Pt(self.fmt.table.row_pad_v)
        tf = cell.text_frame
        tf.word_wrap = True
        tf.text = str(text)
        run = tf.paragraphs[0].runs[0] if tf.paragraphs[0].runs else tf.paragraphs[0].add_run()
        run.text = str(text)
        run.font.size, run.font.bold, run.font.name = Pt(size), bold, self.fmt.font
        run.font.color.rgb = _rgb(color or self.p.text)

    def _widths(self, headers, rows) -> List[float]:
        """Real glyph widths, not a character count — a column of "5%" and a column of
        "Failed deployment recovery time" are not proportional to their lengths."""
        tk = self.fmt.table
        pad = 2 * tk.row_pad_h / 72
        want = []
        for i, h in enumerate(headers):
            widest = max(
                [measure.natural_width_in(h, tk.header_size, True)]
                + [measure.natural_width_in(r[i], tk.cell_size) for r in rows if i < len(r)]
            )
            want.append(max(tk.min_col_in, widest + pad))
        scale = self.width / sum(want)
        return [w * scale for w in want]

    def chart(self, kind: str, categories: Sequence[str], series, *,
              labels: Optional[Sequence[str]] = None, x_title: str = "", y_title: str = "",
              height_in: float = 3.2) -> "Slide":
        """A native PowerPoint chart — editable in the deck, not a picture of one.

        `x_title` and `y_title` are what the axes denote. A reader can see a bar is 412
        tall; nothing else on the slide says 412 of what, and a chart that does not say is
        a chart the reader has to guess at.
        """
        from docgen.charts import check_series
        check_series(categories, series)
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION

        kinds = {
            "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
            "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
            "line": XL_CHART_TYPE.LINE_MARKERS,
            "pie": XL_CHART_TYPE.DOUGHNUT,
            "donut": XL_CHART_TYPE.DOUGHNUT,
        }
        if kind not in kinds:
            raise LayoutError(f"unknown chart kind {kind!r}; use {sorted(kinds)}")

        rows = [list(series)] if series and not isinstance(series[0], (list, tuple)) \
            else [list(s) for s in series]
        names = list(labels) if labels else [f"Series {i + 1}" for i in range(len(rows))]

        self._room(height_in, f"a {kind} chart")
        data = CategoryChartData()
        data.categories = [str(c) for c in categories]
        for name, row in zip(names, rows):
            data.add_series(str(name), tuple(row))

        frame = self.raw.shapes.add_chart(
            kinds[kind], Inches(self.left), Inches(self.y),
            Inches(self.width), Inches(height_in), data)
        chart = frame.chart
        # Off explicitly. Left unset, a single-series chart gets an automatic title from its
        # series name, which the renderer sets at its own default size — `chart.font` does
        # not reach it. It rendered as "Series 1" at 11.99pt, a size off the scale, so the
        # gate failed a deck `Deck` had drawn: session 6aaa716c hit `font.off_scale` on every
        # rebuild with no size anywhere in the model's code to change. The slide title
        # already names the chart; the axis titles below say what it measures.
        chart.has_title = False
        chart.font.name = self.fmt.font
        chart.font.size = Pt(self.fmt.scale["caption"].size)
        chart.font.color.rgb = _rgb(self.p.text)

        for i, plot_series in enumerate(chart.series):
            fill = plot_series.format.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(self.deck.series_color(i))

        chart.has_legend = len(rows) > 1 or kind in ("pie", "donut")
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False

        if kind not in ("pie", "donut"):
            # Anchor the value axis at zero (PowerPoint's auto-scale started a 225k-253k
            # series at 210k, turning a 3% escalation into a 4x-looking climb) and show
            # thousands separators instead of "250000".
            values = [v for row in rows for v in row if isinstance(v, (int, float))]
            if values and min(values) >= 0:
                chart.value_axis.minimum_scale = 0
            chart.value_axis.tick_labels.number_format = "#,##0"
            chart.value_axis.tick_labels.number_format_is_linked = False
            for axis, text in ((chart.category_axis, x_title), (chart.value_axis, y_title)):
                if not text:
                    continue
                axis.has_title = True
                axis.axis_title.text_frame.text = str(text)
                run = axis.axis_title.text_frame.paragraphs[0].runs[0]
                run.font.size = Pt(self.fmt.scale["caption"].size)
                run.font.name = self.fmt.font
                run.font.color.rgb = _rgb(self.p.muted)

        self.y += height_in + self.fmt.gap_in["block"]
        return self

    def notes(self, text: str) -> "Slide":
        self.raw.notes_slide.notes_text_frame.text = str(text)
        return self

    @property
    def remaining_in(self) -> float:
        return max(0.0, self._bottom - self.y)


class Deck:
    def __init__(self, path, footer: str = "", palette: Optional[Palette] = None):
        self.path = Path(path)
        self.fmt = T.PPTX
        self.p = palette or active()
        self.footer_text = footer
        self.prs = Presentation()
        self.prs.slide_width = Inches(self.fmt.page_w_in)
        self.prs.slide_height = Inches(self.fmt.page_h_in)
        self._blank = self.prs.slide_layouts[6]
        self.slides: List[Slide] = []

    def series_color(self, index: int) -> str:
        """Same ordering the PDF charts use, so one report's figures match another's."""
        return self.p.series(index)

    def slide(self, title: Optional[str] = None) -> Slide:
        s = Slide(self, self.prs.slides.add_slide(self._blank), title)
        self.slides.append(s)
        return s

    def _bare(self) -> Slide:
        s = Slide(self, self.prs.slides.add_slide(self._blank), None)
        self.slides.append(s)
        return s

    def cover(self, title: str, subtitle: str = "",
              meta: Optional[Sequence[Sequence[str]]] = None, kicker: str = "",
              style: str = "dark", wordmark: str = "",
              motif: str = "circles", background=None, shapes=None,
              ink: Optional[dict] = None) -> Slide:
        """The title slide — the agent picks `style` for the deck, not one look for all:

        - **dark** — full-bleed near-black, motif circles, title reversed out. Bold; for
          playbooks, launches, pitches, marketing.
        - **minimal** — light ground, dark title, no motif. Restrained; for reviews, internal
          and data-led decks.
        - **editorial** — light ground with a strong colour band carrying the title. For
          briefs and announcements.
        - **custom** — you compose the whole aesthetic: `background`, `shapes`, and `ink`.

        `wordmark` is the producer mark top-left; empty (the default) shows none. Pass `""` to
        hide it: a deck *about* another company should carry no wordmark rather than that
        company's name, which would read as their own publication.

        `motif` is the `dark`-style background design (ignored by the light styles): circles
        (the default cluster), rings, dots, arcs, glow, or none for a plain ground.

        For **style="custom"** the whole aesthetic is yours — a different look per deck:
        - `background`: a hex colour, or `{"type": "gradient", "from": .., "to": .., "angle": deg}`.
        - `shapes`: drawn behind the text, coordinates as page fractions (origin top-left):
          `{"shape": "circle"|"ring"|"rect"|"line", ...}` with `cx/cy/r` or `x/y/w/h` or
          `x1/y1/x2/y2`, plus `color`, `alpha` (0-1), and `width` for ring/line.
        - `ink`: text colours — `wordmark`, `eyebrow`, `title`, `rule`, `subtitle`, `meta_label`,
          `meta_value`, `footer` — defaulting to white-on-dark or ink-on-light by brightness.

        A deck whose first slide is the same white page as its twelfth has no opening; the
        reference deck spends its largest type here and nowhere else."""
        style = str(style or "dark").strip().lower()
        if style not in ("dark", "minimal", "editorial", "custom"):
            style = "dark"
        wordmark = "" if wordmark is None else str(wordmark)
        s = self._bare()
        if style == "custom":
            return self._cover_custom(s, title, subtitle, meta, kicker, wordmark,
                                      background, shapes or [], ink or {})
        if style == "editorial":
            return self._cover_editorial(s, title, subtitle, meta, kicker, wordmark)

        if style == "minimal":
            s.band(self.fmt.page_h_in, _COVER_LIGHT)
            wordmark_c = self.p.primary
            eyebrow_c = self.p.ink(self.p.accent)
            title_c = self.p.text
            sub_c = self.p.text
            s.footer_color = self.p.muted
        else:
            s.band(self.fmt.page_h_in, self.p.primary)
            s.cover_motif(motif)
            on = self.p.on(self.p.primary)
            wordmark_c = title_c = sub_c = on
            eyebrow_c = self.p.accent
            s.footer_color = on

        s.y = self.fmt.margin_in["top"]
        if wordmark:
            s._textbox(wordmark, "section", color=wordmark_c)

        s.y = self.fmt.page_h_in * 0.34
        if kicker:
            s._textbox(kicker.upper(), "badge", color=eyebrow_c)
            s.y += 0.04
        s._textbox(title, "display", color=title_c)
        s._decor(s.left, s.y + 0.12, 1.8, 4.5 / 72, self.p.accent, kind="rule")
        s.y += 0.40
        if subtitle:
            s._textbox(subtitle, "subhead", color=sub_c)

        self._cover_meta(s, meta, label_c=eyebrow_c, value_c=sub_c)
        # Nothing else belongs on a cover; hold it full so the fill check reads it as done.
        s.y = self._fmt_bottom()
        return s

    def _cover_editorial(self, s: Slide, title: str, subtitle: str,
                         meta, kicker: str, wordmark: str = "") -> Slide:
        s.band(self.fmt.page_h_in, _COVER_LIGHT)
        band_h = 2.1
        band_top = self.fmt.page_h_in * 0.40
        s.band(band_h, self.p.primary, top=band_top)
        s.footer_color = self.p.muted
        on = self.p.on(self.p.primary)

        s.y = self.fmt.margin_in["top"]
        if wordmark:
            s._textbox(wordmark, "section", color=self.p.primary)

        s.y = band_top + 0.26
        if kicker:
            s._textbox(kicker.upper(), "badge", color=self.p.accent)
            s.y += 0.04
        s._textbox(title, "display", color=on)

        s.y = band_top + band_h + 0.20
        if subtitle:
            s._textbox(subtitle, "subhead", color=self.p.text)

        self._cover_meta(s, meta, label_c=self.p.ink(self.p.accent), value_c=self.p.text)
        s.y = self._fmt_bottom()
        return s

    def _cover_meta(self, s: Slide, meta, *, label_c: str, value_c: str) -> None:
        if not meta:
            return
        pairs = [m for m in meta if m]
        gutter = self.fmt.gutter_in
        width = (s.width - gutter * (len(pairs) - 1)) / len(pairs)
        top = self.fmt.page_h_in - self.fmt.margin_in["bottom"] - 1.05
        label_h = self.fmt.scale["footer"].line_pt / 72
        for index, (label, value) in enumerate(pairs):
            left = s.left + index * (width + gutter)
            s.y = top
            s._textbox(str(label).upper(), "footer", left=left, width=width,
                       color=label_c, advance=False)
            s.y = top + label_h + 0.06
            s._textbox(str(value), "subhead", left=left, width=width,
                       color=value_c, advance=False)
        s._decor(s.left, top - 0.16, s.width, 1.0 / 72, self.p.accent, kind="rule")

    # ── custom cover ────────────────────────────────────────────────────────────
    def _cover_custom(self, s: Slide, title: str, subtitle: str, meta, kicker: str,
                      wordmark: str, background, shapes, ink: dict) -> Slide:
        w, h = self.fmt.page_w_in, self.fmt.page_h_in

        # 1) Background — solid hex, or {"type":"gradient","from":..,"to":..,"angle":deg}.
        if isinstance(background, dict) and str(background.get("type", "")).lower() == "gradient":
            base = _clean_hex(background.get("from", self.p.primary))
            self._gradient_band(s, base, _clean_hex(background.get("to", self.p.emphasis)),
                                float(background.get("angle", 135)))
        else:
            base = _clean_hex(background) if background else self.p.primary
            s.band(h, base)

        # 2) Decorative shapes, page fractions with a top-left origin.
        for sp in shapes:
            self._custom_shape(s, sp, w, h)

        # 3) Text colours — defaults by ground brightness, per-element overrides via `ink`.
        dark = _is_dark_hex(base)
        d = (dict(wordmark="#FFFFFF", eyebrow=self.p.accent, title="#FFFFFF", rule=self.p.accent,
                  subtitle="#C9C2DA", meta_label=self.p.accent, meta_value="#D8D3E4", footer="#FFFFFF")
             if dark else
             dict(wordmark=self.p.primary, eyebrow=self.p.ink(self.p.accent), title=self.p.text,
                  rule=self.p.accent, subtitle=self.p.text, meta_label=self.p.ink(self.p.accent),
                  meta_value=self.p.text, footer=self.p.muted))
        for k, v in (ink or {}).items():
            if k in d and v:
                d[k] = _clean_hex(v)
        s.footer_color = d["footer"]

        s.y = self.fmt.margin_in["top"]
        if wordmark:
            s._textbox(wordmark, "section", color=d["wordmark"])
        s.y = self.fmt.page_h_in * 0.34
        if kicker:
            s._textbox(kicker.upper(), "badge", color=d["eyebrow"])
            s.y += 0.04
        s._textbox(title, "display", color=d["title"])
        s._decor(s.left, s.y + 0.12, 1.8, 4.5 / 72, d["rule"], kind="rule")
        s.y += 0.40
        if subtitle:
            s._textbox(subtitle, "subhead", color=d["subtitle"])
        self._cover_meta(s, meta, label_c=d["meta_label"], value_c=d["meta_value"])
        s.y = self._fmt_bottom()
        return s

    def _gradient_band(self, s: Slide, frm: str, to: str, angle: float):
        from pptx.enum.shapes import MSO_SHAPE

        shape = s.raw.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0),
            Inches(self.fmt.page_w_in), Inches(self.fmt.page_h_in))
        shape.name = f"{DECOR_PREFIX}band"
        shape.line.fill.background()
        shape.shadow.inherit = False
        shape.fill.gradient()
        stops = shape.fill.gradient_stops
        stops[0].position, stops[0].color.rgb = 0.0, _rgb(frm)
        stops[1].position, stops[1].color.rgb = 1.0, _rgb(to)
        try:
            shape.fill.gradient_angle = float(angle)
        except (ValueError, TypeError, NotImplementedError):
            pass
        return shape

    def _custom_shape(self, s: Slide, sp, w: float, h: float) -> None:
        if not isinstance(sp, dict):
            return
        kind = str(sp.get("shape", "circle")).lower()
        color = _clean_hex(sp.get("color", self.p.emphasis))
        alpha = float(sp.get("alpha", 1.0)) * 100
        if kind in ("circle", "ring"):
            cx, cy = float(sp.get("cx", 0.5)) * w, float(sp.get("cy", 0.5)) * h
            r = float(sp.get("r", 0.15)) * w
            if kind == "ring":
                s._oval(cx, cy, r, color, alpha, fill=False, line_pt=float(sp.get("width", 2.0)))
            else:
                s._oval(cx, cy, r, color, alpha)
        elif kind == "rect":
            self._filled_rect(s, float(sp.get("x", 0.0)) * w, float(sp.get("y", 0.0)) * h,
                              float(sp.get("w", 0.2)) * w, float(sp.get("h", 0.1)) * h, color, alpha)
        elif kind == "line":
            self._custom_line(s, float(sp.get("x1", 0)) * w, float(sp.get("y1", 0)) * h,
                              float(sp.get("x2", 1)) * w, float(sp.get("y2", 0)) * h,
                              color, float(sp.get("width", 2.0)), alpha)

    def _filled_rect(self, s: Slide, x, y, ww, hh, color, alpha_pct):
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.oxml.ns import qn

        shape = s.raw.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
            Inches(max(ww, 0.01)), Inches(max(hh, 0.01)))
        shape.name = f"{DECOR_PREFIX}motif"
        shape.line.fill.background()
        shape.shadow.inherit = False
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(color)
        Slide._alpha(shape._element.spPr.find(qn("a:solidFill")), alpha_pct)
        return shape

    def _custom_line(self, s: Slide, x1, y1, x2, y2, color, width, alpha_pct):
        from pptx.enum.shapes import MSO_CONNECTOR
        from pptx.oxml.ns import qn

        conn = s.raw.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        conn.name = f"{DECOR_PREFIX}motif"
        conn.line.color.rgb = _rgb(color)
        conn.line.width = Pt(width)
        conn.shadow.inherit = False
        Slide._alpha(conn._element.spPr.find(qn("a:ln")), alpha_pct)
        return conn

    def divider(self, title: str, subtitle: str = "", number: Optional[int] = None) -> Slide:
        """A section divider: a tinted full-bleed page carrying one idea.

        This is what turns thirteen slides into three acts. Without it every slide has the
        same weight and the reader has no map."""
        s = self._bare()
        s.band(self.fmt.page_h_in, self.p.band)
        s.rail(self.p.primary, width_pt=10)

        s.y = self.fmt.page_h_in * 0.38
        if number is not None:
            s._textbox(f"{int(number):02d}", "title", color=self.p.accent)
            s.y += 0.06
        s._textbox(title, "title", color=self.p.primary)
        s._decor(s.left, s.y + 0.08, 1.6, 4.0 / 72, self.p.accent, kind="rule")
        s.y += 0.32
        if subtitle:
            s._textbox(subtitle, "subhead", color=self.p.text)
        s.y = self._fmt_bottom()
        return s

    def _fmt_bottom(self) -> float:
        return (self.fmt.page_h_in - self.fmt.margin_in["bottom"]
                - self.fmt.gap_in["footer_h"])

    def _footer(self, slide: Slide, index: int, total: int) -> None:
        if not self.footer_text:
            return
        t = self.fmt.scale["footer"]
        y = self.fmt.page_h_in - self.fmt.margin_in["bottom"] - self.fmt.gap_in["footer_h"]
        box = slide.raw.shapes.add_textbox(
            Inches(self.fmt.margin_in["left"]), Inches(y),
            Inches(self.fmt.content_w_in), Inches(self.fmt.gap_in["footer_h"]))
        box.name = FOOTER_NAME
        tf = box.text_frame
        tf.text = f"{self.footer_text}    ·    {index} / {total}"
        run = tf.paragraphs[0].runs[0]
        run.font.size, run.font.name = Pt(t.size), self.fmt.font
        run.font.color.rgb = _rgb(slide.footer_color)

    def save(self) -> Path:
        if not self.slides:
            raise LayoutError("the deck has no slides")
        thin = [i for i, s in enumerate(self.slides, start=1)
                if s.remaining_in > self.fmt.content_h_in * 0.50]
        for i, s in enumerate(self.slides, start=1):
            self._footer(s, i, len(self.slides))
        self.prs.save(str(self.path))
        if thin:
            # Not fatal — the verifier decides — but the builder knows first.
            import logging

            logging.getLogger(__name__).info(
                "docgen: slide(s) %s are less than half full", thin)
        return self.path
