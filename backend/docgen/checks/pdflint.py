"""Glyph-level checks on a rendered page.

A `.docx` carries no glyph coordinates — Word decides the layout at render time — so the only
way to see text overflowing its box, a heading stranded alone, or a page that is four-fifths
empty is to render and measure. pdfplumber does that in roughly 15-20ms per page with no
vision model, which is what makes it usable as a gate.
"""

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

from docgen import tokens as T
from docgen.fonts import available as _inter_installed
from docgen.checks import ERROR, WARNING, Issue, Report

# A glyph pair has to overlap by more than a hairline to count; renderers routinely emit
# kerned pairs whose boxes touch. The allowance scales with the type because a kern is
# specified in em, not points: Inter's `Te`, `Wo` and `7.` pairs run about 0.05em, which is
# 0.55pt under 11pt body and 1.8pt under a 36pt title. A fixed point threshold therefore
# passes every body line and fails every heading, and the only way past it is to reword the
# heading — one run spent 23 of its 30 tool calls bisecting titles against this and then
# deleted the flagged figures ($67.9B, Q1 FY26/27) from the deck to get the upload through.
_H_OVERLAP_PT = 1.5
_H_OVERLAP_EM = 0.28
_V_OVERLAP_PT = 1.5
_V_OVERLAP_EM = 0.28
_SIZE_TOL_PT = 0.6
_MARGIN_TOL_PT = 3.0
_GRID = 120
# A running header, a rule, and a page number — anything more is content that escaped.
_FURNITURE_ROWS = 2
# Below this a "page" is furniture only — a page number and a rule.
_BLANK_INK = 0.004


def _fill_is_visible(obj) -> bool:
    c = obj.get("non_stroking_color")
    if c is None:
        return bool(obj.get("stroking_color"))
    if isinstance(c, (int, float)):
        c = [c]
    try:
        vals = [float(v) for v in c]
    except (TypeError, ValueError):
        return True
    if len(vals) == 1:
        return vals[0] < 0.97
    if len(vals) == 3:
        return sum(vals) / 3 < 0.97
    if len(vals) == 4:  # CMYK
        return sum(vals) > 0.04
    return True


def _ink_boxes(page) -> List[Tuple[float, float, float, float]]:
    boxes = [(c["x0"], c["top"], c["x1"], c["bottom"]) for c in page.chars]
    page_area = float(page.width) * float(page.height)
    for kind in ("rects", "curves", "images"):
        for o in getattr(page, kind, []) or []:
            if kind != "images" and not _fill_is_visible(o):
                continue
            x0, top, x1, bottom = o["x0"], o["top"], o["x1"], o["bottom"]
            area = max(0.0, x1 - x0) * max(0.0, bottom - top)
            # A full-bleed white or tinted background is not content; counting it would make
            # every empty page look full.
            if area > 0.92 * page_area:
                continue
            boxes.append((x0, top, x1, bottom))
    return boxes


def ink_ratio(page, boxes=None) -> float:
    """Covered fraction of the page, on a coarse grid — exact union is not worth the cost."""
    boxes = _ink_boxes(page) if boxes is None else boxes
    if not boxes:
        return 0.0
    w, h = float(page.width), float(page.height)
    if w <= 0 or h <= 0:
        return 0.0
    cw, ch = w / _GRID, h / _GRID
    cells = set()
    for x0, top, x1, bottom in boxes:
        cx0 = max(0, min(_GRID - 1, int(x0 / cw)))
        cx1 = max(0, min(_GRID - 1, int((x1 - 1e-9) / cw)))
        cy0 = max(0, min(_GRID - 1, int(top / ch)))
        cy1 = max(0, min(_GRID - 1, int((bottom - 1e-9) / ch)))
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                cells.add((cx, cy))
    return len(cells) / (_GRID * _GRID)


def _upright(chars) -> List[dict]:
    """Rotated text — an axis title running up the y axis — is legitimate, but its geometry
    is expressed in a rotated frame: pdfplumber derives `size` from a matrix component that
    is not the point size, and every glyph in a vertical run shares an x range while
    stacking in y. Read as if upright, a correct y-axis label reports as four off-scale
    sizes and a pile of overlapping lines. It still counts as ink; it just cannot be
    measured with the rules written for a baseline."""
    # pdfminer's `upright` alone is not enough: it tests `a*d > 0 and b*c <= 0`, which is
    # False only once rotation reaches 90 degrees. A bar chart angles category names at 35
    # degrees when they are too long to sit flat, and those glyphs pass as upright — each one
    # has its own `top`, reads as its own "line", and collides with its neighbour. One clean
    # chart reported 33 `text.overlap` errors, and a model told a document has overlapping
    # text will keep trying to fix what it cannot, which is how one PDF request became four
    # rebuilds. Any rotation or skew in the text matrix excludes the glyph.
    out = []
    for c in chars:
        if not c.get("upright", True):
            continue
        matrix = c.get("matrix")
        if matrix and (abs(float(matrix[1])) > 1e-3 or abs(float(matrix[2])) > 1e-3):
            continue
        out.append(c)
    return out


def _lines(page, tol=2.0) -> Dict[float, list]:
    rows = defaultdict(list)
    for c in _upright(page.chars):
        key = round(c["top"] / tol) * tol
        rows[key].append(c)
    return rows


def _slack(chars, em: float, floor: float) -> float:
    """How much box overlap the largest glyph in `chars` is allowed before it is a collision."""
    size = max((float(c.get("size") or 0.0) for c in chars), default=0.0)
    return max(floor, em * size)


def _overlaps(page) -> List[str]:
    out = []
    rows = _lines(page)
    for key in sorted(rows):
        chars = sorted(rows[key], key=lambda c: c["x0"])
        for a, b in zip(chars, chars[1:]):
            if a["x1"] - b["x0"] > _slack((a, b), _H_OVERLAP_EM, _H_OVERLAP_PT):
                out.append(f"'{a.get('text', '')}{b.get('text', '')}' near x={b['x0']:.0f}")
                break
    keys = sorted(rows)
    for top, nxt in zip(keys, keys[1:]):
        upper, lower = rows[top], rows[nxt]
        vslack = _slack(upper + lower, _V_OVERLAP_EM, _V_OVERLAP_PT)
        if max(c["bottom"] for c in upper) - nxt <= vslack:
            continue
        # Vertical proximity alone is not a collision. A chart's axis labels sit at tick
        # positions rather than on a baseline grid, and — the case that failed correct output —
        # cards laid side by side put each column's text at its own baseline, so two adjacent
        # rows a couple of points apart belong to DIFFERENT columns and never touch. Comparing
        # the rows' full bounding widths (each spanning the whole measure across every card)
        # called those overlaps; a 4-card row failed the gate. Test glyph against glyph: a real
        # collision needs one glyph from each row to share horizontal space AND intrude in y.
        hslack = _slack(upper + lower, _H_OVERLAP_EM, _H_OVERLAP_PT)
        if any(min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) > hslack
               and a["bottom"] - b["top"] > vslack
               for a in upper for b in lower):
            out.append(f"line at y={top:.0f} runs into the line at y={nxt:.0f}")
    return out


def _rows(chars, tol: float = 4.0) -> set:
    return {round(float(c["top"]) / tol) for c in chars}


def _content_box(page, fmt: T.Format):
    w, h = float(page.width), float(page.height)
    m = fmt.margin_in
    return (m["left"] * 72, m["top"] * 72, w - m["right"] * 72, h - m["bottom"] * 72)


def _is_cover(page) -> bool:
    """A page laid on a full-bleed non-white ground is a designed cover, not a content page.

    The report cover (and a deck's cover slide) bleeds a dark rectangle to every edge, floats
    a motif of circles off the corner, and sets a display-size title — all of which read as a
    margin breach, off-scale type and sparse content to rules written for a body page. A deck's
    first slide already gets this exemption by index; a report's cover is detected by its ground
    so the check needs nothing passed to it.
    """
    page_area = float(page.width) * float(page.height)
    if page_area <= 0:
        return False
    for kind in ("rects", "curves", "images"):
        for o in getattr(page, kind, []) or []:
            area = max(0.0, o["x1"] - o["x0"]) * max(0.0, o["bottom"] - o["top"])
            if area > 0.92 * page_area and (kind == "images" or _fill_is_visible(o)):
                return True
    return False


def check(pdf_path, fmt: T.Format, report: Report, origin: Optional[str] = None) -> None:
    slides = fmt.name == "pptx"
    unit = "slide" if slides else "page"
    allowed = set(fmt.sizes) | {fmt.table.header_size, fmt.table.cell_size}
    body = fmt.scale["body"].size
    seen_sizes: set = set()
    fonts: set = set()

    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = pdf.pages
        total = len(pages)
        if total == 0:
            report.add(Issue("doc.empty", origin or Path(pdf_path).name,
                             "no pages at all", "the build produced nothing"))
            return

        for idx, page in enumerate(pages, start=1):
            where = f"{unit} {idx}"
            is_cover = _is_cover(page)
            boxes = _ink_boxes(page)
            ratio = ink_ratio(page, boxes)

            if not page.chars and ratio <= _BLANK_INK:
                report.add(Issue("page.blank", where, "no text and no graphics on it",
                                 f"remove the empty {unit} or put its content back"))
                continue

            # The last page of a multi-page flow is partial by nature — every document
            # ends mid-page, and holding it to the fill floor would fail correct output. A
            # one-page document gets no such exemption: there, the page is the document.
            # A deck's first slide is its cover, which is sparse on purpose.
            exempt = (total > 1 and idx == total) or (slides and idx == 1) or is_cover
            if ratio < fmt.min_ink_ratio and not exempt:
                report.add(Issue(
                    "page.sparse", where,
                    f"only {ratio:.0%} of the {unit} carries content "
                    f"(floor is {fmt.min_ink_ratio:.0%})",
                    f"merge it with the neighbouring {unit} or add the detail it is missing",
                    # Density is a judgement about CONTENT, not a layout fault, and it
                    # was blocking delivery of correct documents: a research section with
                    # three findings genuinely has less ink than a dense table, and the
                    # model cannot fix that by rewriting the layout — it rewrote the
                    # document instead, or gave up. On a slide this was always a warning
                    # (whitespace is often the design); it is now a warning everywhere, and
                    # a page carrying nothing at all is still caught by `page.blank`.
                    WARNING))

            x0, top, x1, bottom = _content_box(page, fmt)
            if idx < total and not is_cover:
                lowest = max((b[3] for b in boxes), default=top)
                gap_in = (bottom - lowest) / 72
                if gap_in > T.MAX_TRAILING_GAP_IN:
                    report.add(Issue(
                        "page.trailing_gap", where,
                        f"{gap_in:.1f}in of empty space below the last content, "
                        f"then a break",
                        "pull the next section up, or let the content flow instead of "
                        "forcing the break", WARNING))

            # Full-bleed ink is a design decision, not an overflow: something spanning the
            # whole sheet was placed there deliberately, while content that escapes starts
            # inside the measure and pokes out. Judged by span rather than by position, since
            # a rendered page carries no shape names.
            # Full-bleed is two-dimensional, and testing only the width missed half of it.
            # `Slide.rail()` draws a 6pt accent strip down the left edge at x=0, full page
            # height — full-bleed vertically, and 6pt wide, so the width test never exempted
            # it. It breached the 0.5in left margin by the whole margin: 39.1pt, well past
            # one body line, so it landed as an ERROR and the gate blocked the upload.
            #
            # `native_pptx` exempts the same shape by its `docgen-` name, so the two passes
            # disagreed about a deck the builder had drawn correctly — and the model cannot
            # fix what it did not draw. Production session 6aaa716c: 24 tool calls, 11 of
            # them spent reading docgen's own source to find the rule, then the run died.
            full_bleed_w = 0.98 * float(page.width)
            full_bleed_h = 0.98 * float(page.height)
            over_h = [b for b in boxes
                      if (b[2] - b[0]) < full_bleed_w
                      and (b[3] - b[1]) < full_bleed_h
                      and (b[0] < x0 - _MARGIN_TOL_PT or b[2] > x1 + _MARGIN_TOL_PT)]
            if over_h and not is_cover:
                worst = max(max(x0 - b[0], b[2] - x1) for b in over_h)
                # Severity by magnitude, because this is measured on a LibreOffice re-render
                # and a hairline is the renderer rather than the layout. A deck whose shapes
                # sit at exactly 0.500in and 12.833in — the content box to three decimals —
                # still reported "2 objects cross the side margin by up to 3pt": a 1.5pt
                # shape border contributes 0.75pt of ink outside its own box by definition,
                # and glyphs on a full-measure text box render a point or two past it when
                # the renderer's metrics differ from the font the layout was measured in.
                #
                # As a flat ERROR that blocked the upload, it cost one production run 23
                # identical rebuilds of a correct deck before the user cancelled it. Content
                # genuinely off the page is a different quantity: a word is tens of points.
                # One line of body text is the line between the two.
                line = fmt.scale["body"].line_pt
                report.add(Issue(
                    "margin.breach", where,
                    f"{len(over_h)} object(s) cross the side margin by up to {worst:.1f}pt",
                    f"keep every box inside the {fmt.content_w_in:.2f}in content width",
                    ERROR if worst > line else WARNING))

            # The top and bottom margins are where a running header and a page number
            # legitimately live, so a breach is measured in text rows rather than glyphs, and
            # the two bands are counted separately — one row in each is furniture, several in
            # one is content that escaped. The top needs the extra ascent tolerance because a
            # glyph box rises above its baseline by roughly the font size, so a heading set
            # exactly on the top margin reports a box above it.
            upright = _upright(page.chars)
            ascent = max((float(c["size"]) for c in upright), default=0.0)
            above = _rows(c for c in upright if c["top"] < top - ascent - _MARGIN_TOL_PT)
            below = _rows(c for c in upright if c["bottom"] > bottom + _MARGIN_TOL_PT)
            for band, rows in (("above the top", above), ("below the bottom", below)):
                if len(rows) > _FURNITURE_ROWS and not is_cover:
                    report.add(Issue(
                        "margin.breach_v", where,
                        f"{len(rows)} lines of text sit {band} margin",
                        "only a running header and a page number belong outside the content "
                        "box — the content is overflowing", WARNING))

            if not is_cover:
                for note in _overlaps(page):
                    report.add(Issue("text.overlap", where, note,
                                     "the text is wider than its box — widen the column or "
                                     "shorten the string"))

            for c in _upright(page.chars):
                # A cover's display title and wordmark are deliberately off the body scale;
                # counting their sizes would fail `font.off_scale` on every branded document.
                if not is_cover:
                    seen_sizes.add(round(float(c["size"]), 2))
                fonts.add(str(c.get("fontname", "")))
            for c in page.chars:
                if not c.get("upright", True):
                    fonts.add(str(c.get("fontname", "")))

    off = [s for s in sorted(seen_sizes)
           if not any(abs(s - a) <= _SIZE_TOL_PT for a in allowed)]
    if off:
        report.add(Issue(
            "font.off_scale", origin or Path(pdf_path).name,
            f"sizes {off} are not in the {fmt.name} scale {sorted(allowed)}",
            "take every size from docgen.tokens — do not pass a literal point size"))

    family = fmt.font.split("-")[0].lower()
    wrong = sorted({f for f in fonts if family not in f.lower()})
    if wrong:
        # A render can only draw faces this machine has. Where Inter is installed, a
        # substitute in the output means the document asked for another face — a real
        # defect. Where it is not, every document substitutes, whatever it asked for, and no
        # script can change that: the native pass has already checked what the file
        # requests. As an ERROR here it blocked every deck built on a host without Inter, and
        # the "register Inter" fix sent the model to download fonts from GitHub and write
        # them into /usr/share/fonts — minutes of PermissionErrors and 404s, never a deck.
        on_host = _inter_installed()
        report.add(Issue(
            "font.family", origin or Path(pdf_path).name,
            f"{wrong[:4]} rendered instead of {fmt.font}",
            f"register {fmt.font} before building; a missing face falls back silently"
            if on_host else
            f"{fmt.font} is not installed on this machine, so the renderer substituted it. "
            f"That is the host, not the document — nothing in the script fixes it. Do not "
            f"download or install fonts; upload the file",
            ERROR if on_host else WARNING))

    if len(seen_sizes) < 2:
        report.add(Issue(
            "type.flat", origin or Path(pdf_path).name,
            f"every character is the same size ({sorted(seen_sizes)})",
            "headings and body must differ — use the named roles in docgen.tokens"))
    elif seen_sizes and max(seen_sizes) / body < 1.4:
        report.add(Issue(
            "type.weak_hierarchy", origin or Path(pdf_path).name,
            f"largest size {max(seen_sizes)} is only {max(seen_sizes) / body:.2f}x body",
            "use the title/h1 role so headings are visibly larger", WARNING))
