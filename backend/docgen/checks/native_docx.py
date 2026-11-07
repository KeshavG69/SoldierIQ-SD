"""Structural checks on a Word file.

Word computes layout at render time, so a `.docx` carries no glyph coordinates — text overflow
and page breaks are the rendered pass's job. What the file itself can answer is whether the
type came off the scale, whether headings are ordered and kept with their text, and whether a
table is wider than the measure it has to fit.
"""

import re
from pathlib import Path

from docx import Document
from docx.shared import Emu

from docx.oxml.ns import qn

from docgen import tokens as T
from docgen.checks import ERROR, WARNING, Issue, Report

_PLACEHOLDER = re.compile(
    r"(\[[A-Z][A-Z0-9 _-]{1,30}\]|\{\{[^}]+\}\}|\bTBD\b|\bTKTK\b|\bXXX+\b|\blorem\b|\bipsum\b)",
    re.I,
)
_HEADING = re.compile(r"^Heading (\d)$")
_MAX_BLANK_RUN = 2


def _effective(paragraph, attr) -> bool:
    """Direct formatting first, then the style it inherits from. Reading only the direct
    value calls a correctly-styled heading an orphan risk."""
    direct = getattr(paragraph.paragraph_format, attr, None)
    if direct is not None:
        return bool(direct)
    style = getattr(paragraph, "style", None)
    while style is not None:
        value = getattr(style.paragraph_format, attr, None)
        if value is not None:
            return bool(value)
        style = getattr(style, "base_style", None)
    return False


def _style_name(p) -> str:
    try:
        return p.style.name or ""
    except AttributeError:
        return ""


_TABLE = object()


def _body_flow(doc):
    """Paragraphs and tables in document order.

    `doc.paragraphs` silently drops tables, which makes any check that looks at what
    precedes what read a table-heavy document wrongly."""
    from docx.text.paragraph import Paragraph

    for child in doc.element.body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield _TABLE


def _is_rule(paragraph) -> bool:
    pr = paragraph._p.find(qn("w:pPr"))
    return pr is not None and pr.find(qn("w:pBdr")) is not None


def check(path: Path, fmt: T.Format, palette, report: Report) -> None:
    doc = Document(str(path))
    allowed = set(fmt.sizes) | {fmt.table.header_size, fmt.table.cell_size}
    content_emu = int(fmt.content_w_in * T.EMU_PER_INCH)

    for i, section in enumerate(doc.sections, start=1):
        for edge in ("left", "right", "top", "bottom"):
            actual = getattr(section, f"{edge}_margin", None)
            want = Emu(int(fmt.margin_in[edge] * T.EMU_PER_INCH))
            if actual is None or abs(int(actual) - int(want)) > T.EMU_PER_INCH // 32:
                report.add(Issue(
                    "margin.wrong", f"section {i}",
                    f"{edge} margin is "
                    f"{(int(actual) / T.EMU_PER_INCH):.2f}in, expected {fmt.margin_in[edge]}in"
                    if actual is not None else f"{edge} margin is unset",
                    "set the section margins from docgen.tokens.DOCX.margin_in"))

    blanks = 0
    last_level = 0
    seen_body = False
    for p in _body_flow(doc):
        if p is _TABLE:
            # A table between two spacers is content, and `doc.paragraphs` cannot see it —
            # so a document with one blank line after each of four tables read as a run of
            # four consecutive blanks and was reported for spacing it does not have.
            blanks = 0
            seen_body = True
            continue

        text = p.text
        style = _style_name(p)

        if not text.strip():
            if _is_rule(p):
                # A paragraph carrying a bottom border is a horizontal rule. It has no text
                # by definition; it is still something on the page.
                blanks = 0
                continue
            blanks += 1
            if blanks == _MAX_BLANK_RUN + 1:
                report.add(Issue(
                    "text.blank_run", f"after {style or 'body'}",
                    f"{_MAX_BLANK_RUN + 1}+ empty paragraphs in a row",
                    "use paragraph spacing from the tokens instead of blank lines", WARNING))
            continue
        blanks = 0

        hit = _PLACEHOLDER.search(text)
        if hit:
            report.add(Issue("text.placeholder", text.strip()[:40],
                             f"unfilled placeholder {hit.group(0)!r}",
                             "replace it with the real value or drop the line"))

        m = _HEADING.match(style)
        if m:
            level = int(m.group(1))
            if last_level and level > last_level + 1:
                report.add(Issue(
                    "heading.skipped_level", text.strip()[:40],
                    f"Heading {level} follows Heading {last_level}",
                    "headings must descend one level at a time or the TOC reads wrong",
                    WARNING))
            last_level = level
            if not _effective(p, "keep_with_next"):
                report.add(Issue(
                    "heading.orphan_risk", text.strip()[:40],
                    "the heading is not kept with the text under it",
                    "set keep_with_next so a heading cannot land alone at a page bottom",
                    WARNING))
        elif style in ("Normal", "Body Text", "List Bullet", "List Number"):
            seen_body = True

        for run in p.runs:
            if run.font.size is not None:
                pt = round(run.font.size.pt, 2)
                if not any(abs(pt - a) <= 0.01 for a in allowed):
                    report.add(Issue(
                        "font.off_scale", text.strip()[:40] or style,
                        f"{pt}pt is not in the docx scale {sorted(allowed)}",
                        "take the size from docgen.tokens.DOCX.scale"))
            if run.font.name and fmt.font.lower() not in run.font.name.lower():
                report.add(Issue("font.family", text.strip()[:40] or style,
                                 f"{run.font.name!r} instead of {fmt.font}",
                                 f"every run must be {fmt.font}"))

    for n, table in enumerate(doc.tables, start=1):
        widths = [c.width for c in table.columns if c.width is not None]
        if len(widths) != len(table.columns):
            report.add(Issue("table.no_widths", f"table {n}",
                             "not every column has an explicit width",
                             "set columnWidths and a width on each cell, in DXA"))
            continue
        total = sum(int(w) for w in widths)
        if total > content_emu + T.EMU_PER_INCH // 32:
            report.add(Issue(
                "table.too_wide", f"table {n}",
                f"columns total {total / T.EMU_PER_INCH:.2f}in against a "
                f"{fmt.content_w_in:.2f}in measure",
                "narrow the columns — an over-wide table silently overflows the margin"))
        narrow = [i for i, w in enumerate(widths, start=1)
                  if int(w) / T.EMU_PER_INCH < fmt.table.min_col_in]
        if narrow:
            report.add(Issue(
                "table.column_too_narrow", f"table {n}",
                f"column(s) {narrow} are under {fmt.table.min_col_in}in",
                "a header that wraps to two lines is the clearest tell of a generated "
                "document — widen it"))

    # A figure is content. `Doc.chart` places a chart as an inline picture — python-docx
    # has no chart API — so a document whose substance is a chart and its caption carries
    # no body paragraph and no table, and was being called headings-only.
    if not seen_body and not doc.tables and not doc.inline_shapes:
        report.add(Issue("doc.empty", path.name, "no body text, tables or figures",
                         "the document is headings only"))
