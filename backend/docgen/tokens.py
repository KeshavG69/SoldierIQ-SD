"""The design system, as values rather than prose.

Every number here was previously a markdown code block the model retyped into each generated
script, and the two files holding them disagreed: the pptx type scale was `title 24 / heading
14 / body 14 / caption 14 / footer 14` in one reference and `36-44 / 20-24 / 14-16 / 10-12 /
7` in another; margins were 0.4in in the constants and 0.5in in the QA prompt that judged
them. Measured result in production: 56% of PDF `fontSize=` values off any sanctioned scale
and eight different page margins in use.

Deliberately free of pptx/docx/reportlab imports — the verifier reads the scale to check a
finished file, and should not pay for a rendering library to do it.
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple

EMU_PER_INCH = 914400


@dataclass(frozen=True)
class Type:
    """A named size in points. `leading` is a multiple of size, not an absolute."""

    size: float
    leading: float = 1.25
    bold: bool = False
    space_before: float = 0.0
    space_after: float = 0.0
    tracking: float = 0.0

    @property
    def line_pt(self) -> float:
        return round(self.size * self.leading, 2)


@dataclass(frozen=True)
class Table:
    header_size: float
    cell_size: float
    row_pad_v: float
    row_pad_h: float
    band_rows: bool = True
    rule_pt: float = 0.5
    header_bold: bool = True
    min_col_in: float = 0.55


@dataclass(frozen=True)
class Format:
    name: str
    page_w_in: float
    page_h_in: float
    margin_in: Dict[str, float]
    font: str
    font_bold: str
    scale: Dict[str, Type]
    table: Table
    pad_pt: Dict[str, float]
    gap_in: Dict[str, float]
    grid_cols: int = 12
    gutter_in: float = 0.20
    min_ink_ratio: float = 0.0

    @property
    def content_w_in(self) -> float:
        return self.page_w_in - self.margin_in["left"] - self.margin_in["right"]

    @property
    def content_h_in(self) -> float:
        return self.page_h_in - self.margin_in["top"] - self.margin_in["bottom"]

    @property
    def sizes(self) -> Tuple[float, ...]:
        return tuple(sorted({t.size for t in self.scale.values()}))

    def col_w_in(self, span: int = 1) -> float:
        unit = (self.content_w_in - self.gutter_in * (self.grid_cols - 1)) / self.grid_cols
        return unit * span + self.gutter_in * (span - 1)


# ── PPTX ──────────────────────────────────────────────────────────────────────
# 16:9. Margin is 0.5in on all four sides: `design.md` required it and the QA prompt flagged
# anything under it, while the constants shipped 0.4in — so the helpers failed the skill's
# own check. There was no MARGIN_B at all; the bottom was implied by the footer bar.
#
# The scale is measured off Lenovo_CAS_2H2026_US_Strategy.pptx, the deck this system is meant
# to match. Its 391 runs are all Inter at 10pt (146 runs), 9pt (115), 11pt (37), 28pt (26),
# 8pt (16), 13pt (15), 22pt (15), 12pt (12), 14pt (6) — body in the 9-11 band, headings at 22
# and 28. Shipping body at 14 and titles at 36 meant a slide held a third of the reference's
# content (7 shapes and 71 words against a median 37 and 253), which is the whole of "the
# deck looks thin": nothing was broken, the type was simply too big for anything to fit.
PPTX = Format(
    name="pptx",
    page_w_in=13.333,
    page_h_in=7.5,
    margin_in={"left": 0.5, "right": 0.5, "top": 0.5, "bottom": 0.5},
    font="Inter",
    font_bold="Inter",
    scale={
        # The cover, and only the cover. The reference deck has exactly one 40pt run in 391.
        "display": Type(40, 1.05, bold=True, space_after=12),
        "title": Type(28, 1.1, bold=True, space_after=10),
        "section": Type(22, 1.15, bold=True, space_before=8, space_after=6),
        "subhead": Type(16, 1.2, bold=True, space_after=4),
        "body": Type(11, 1.35, space_after=6),
        "bullet": Type(11, 1.35, space_after=4),
        "caption": Type(10, 1.25, space_after=2),
        "footer": Type(9, 1.1, tracking=0.2),
        "badge": Type(9, 1.0, bold=True, tracking=0.2),
        "kpi_value": Type(28, 1.0, bold=True),
        "kpi_label": Type(9, 1.2, tracking=0.2),
    },
    table=Table(header_size=10, cell_size=10, row_pad_v=4, row_pad_h=8, min_col_in=0.8),
    # One rule keyed on box height, replacing "CARD_PADDING = Pt(2), use on every colored-fill
    # shape" sitting 240 lines above "bump it to Pt(10) for any card >= 0.6in" — i.e. for
    # everything except the badge pills.
    pad_pt={"card": 10, "pill": 3, "band": 12},
    gap_in={"block": 0.22, "section": 0.34, "footer_h": 0.30, "pad_switch": 0.6},
    # 0.16 was carried over from page formats and is wrong by about three times for a 16:9
    # slide, where whitespace is the design rather than a defect. On a well-composed deck it
    # failed 8 of 17 slides — every text-led one — and the model, told only "sparse", rewrote
    # the content denser, failed again and spent the run. Measured at the old 14pt body:
    #
    #   title only (genuinely empty)  2.0%      cover                      7.0%
    #   title + one bullet            2.6%      title + 4 bullets + caption 8.0%
    #   title + three short bullets   2.2%      title + a full paragraph   11.3%
    #   title + six bullets           6.4%      title + a 5-column table   25.3%
    #
    # Ink cannot separate "three short bullets" from "nothing at all", so the empty slide is
    # caught structurally instead (`slide.title_only`) and this floor only has to sit under
    # the lightest legitimate slide.
    #
    # Glyph area goes with the square of the size, so dropping body 14 -> 11 and title 36 ->
    # 28 takes every number above to about 0.62 of what it was. The floor is scaled by the
    # same factor rather than re-measured — soffice is not installed on a dev Mac, so the
    # table cannot be regenerated here — which keeps the check behaving exactly as it did
    # against the new scale. Re-measure on the pod before tightening it.
    min_ink_ratio=0.025,
)

# ── DOCX ──────────────────────────────────────────────────────────────────────
# H3 exists because the TOC is configured to collect heading levels 1-3 and the styles block
# only ever defined two.
#
# Heading 16pt and sub-heading 13pt: the brief caps a heading at 22px and a sub-heading at
# 16-18px, which is 16.5pt and 12-13.5pt, and is also what Word itself ships (H1 16, H2 13).
# 22pt is the document title — the cap, used once per file.
DOCX = Format(
    name="docx",
    page_w_in=8.5,
    page_h_in=11.0,
    margin_in={"left": 1.0, "right": 1.0, "top": 1.0, "bottom": 1.0},
    font="Inter",
    font_bold="Inter",
    scale={
        "title": Type(22, 1.15, bold=True, space_after=14),
        "h1": Type(16, 1.25, bold=True, space_before=14, space_after=6),
        "h2": Type(13, 1.3, bold=True, space_before=10, space_after=4),
        "h3": Type(11.5, 1.3, bold=True, space_before=8, space_after=3),
        "body": Type(11, 1.3, space_after=8),
        "bullet": Type(11, 1.3, space_after=4),
        "cell": Type(10, 1.15),
        "caption": Type(9, 1.2, space_after=6),
        "footnote": Type(8.5, 1.2),
        "header_footer": Type(8.5, 1.1),
    },
    table=Table(header_size=10, cell_size=10, row_pad_v=4, row_pad_h=6, min_col_in=0.7),
    pad_pt={"card": 8, "pill": 3, "band": 10},
    gap_in={"block": 0.14, "section": 0.24},
    min_ink_ratio=0.14,
)

# ── PDF ───────────────────────────────────────────────────────────────────────
# Top margin is deeper than the sides to leave room for the running header. The page number
# now sits on the body measure; it was drawn at 0.5in against a 0.75in margin.
#
# Same heading cap as DOCX — h1 16, h2 13 — so a report and a Word doc of the same content
# set identically. Only the cover is display type, and it comes down from 32 to 26.
PDF = Format(
    name="pdf",
    page_w_in=8.5,
    page_h_in=11.0,
    margin_in={"left": 0.75, "right": 0.75, "top": 0.85, "bottom": 0.75},
    font="Inter",
    font_bold="Inter-Bold",
    scale={
        "cover": Type(26, 1.15, bold=True, space_after=12),
        "h1": Type(16, 1.3, bold=True, space_before=16, space_after=6),
        "h2": Type(13, 1.35, bold=True, space_before=12, space_after=4),
        "h3": Type(11.5, 1.35, bold=True, space_before=9, space_after=3),
        "body": Type(10.5, 1.45, space_after=6),
        "bullet": Type(10.5, 1.45, space_after=3),
        "cell": Type(9.5, 1.3),
        "caption": Type(8.5, 1.35, space_after=4),
        "footer": Type(8, 1.2, tracking=0.2),
        "badge": Type(8.5, 1.0, bold=True, tracking=0.2),
        "kpi_value": Type(20, 1.05, bold=True),
        "kpi_label": Type(8.5, 1.2, tracking=0.2),
    },
    table=Table(header_size=9.5, cell_size=9.5, row_pad_v=5, row_pad_h=7, min_col_in=0.65),
    pad_pt={"card": 8, "pill": 3, "band": 12},
    gap_in={"block": 0.16, "section": 0.28},
    min_ink_ratio=0.12,
)

# ── XLSX ──────────────────────────────────────────────────────────────────────
# Calibri, not Inter: a workbook is rendered by the reader's Excel, where Inter is not
# installed. This is the one format whose font belongs to the reader.
XLSX = Format(
    name="xlsx",
    page_w_in=11.0,
    page_h_in=8.5,
    margin_in={"left": 0.5, "right": 0.5, "top": 0.6, "bottom": 0.6},
    font="Calibri",
    font_bold="Calibri",
    scale={
        "title": Type(14, 1.2, bold=True),
        "header": Type(11, 1.2, bold=True),
        "body": Type(11, 1.2),
        "note": Type(9, 1.2),
    },
    table=Table(header_size=11, cell_size=11, row_pad_v=0, row_pad_h=0, min_col_in=0.0),
    pad_pt={"card": 0, "pill": 0, "band": 0},
    gap_in={"block": 0.0, "section": 0.0},
)

NUMBER_FORMATS = {
    "currency": '#,##0;(#,##0);"-"',
    "currency_cents": '#,##0.00;(#,##0.00);"-"',
    "percent": '0.0%;(0.0%);"-"',
    "integer": '#,##0;(#,##0);"-"',
    "decimal": "#,##0.00",
    "multiple": '0.0"x"',
    "date": "yyyy-mm-dd",
    "month": "mmm yyyy",
    "text": "@",
}

# Column width in Excel character units, not inches.
XLSX_COL_MIN = 10
XLSX_COL_MAX = 45
XLSX_COL_PAD = 2
XLSX_ROW_H = 18
XLSX_HEADER_ROW_H = 22

BY_NAME: Dict[str, Format] = {f.name: f for f in (PPTX, DOCX, PDF, XLSX)}

# Anything wider than this reads as a lost row of content rather than a deliberate break.
MAX_TRAILING_GAP_IN = 2.0


def for_path(path) -> Format:
    ext = str(path).rsplit(".", 1)[-1].lower()
    try:
        return BY_NAME[ext]
    except KeyError:
        raise ValueError(f"no design tokens for .{ext}") from None
