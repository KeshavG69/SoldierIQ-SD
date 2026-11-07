"""Structural checks a deck can answer about itself, before anything is rendered.

The checker this replaces exempted every shape whose name contained "rectangle":

    elif "footer" not in shape.name.lower() and "rectangle" not in shape.name.lower() ...

python-pptx auto-names autoshapes "Rectangle 3" / "Rounded Rectangle 5", so every card, KPI
tile, CTA and badge the skill tells you to build was skipped by the one check meant to catch
content running into the footer.
"""

import re
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from docgen import tokens as T
from docgen.deck import FOOTER_NAME
from docgen.checks import ERROR, WARNING, Issue, Report

# Fraction of the content height that may sit empty below a slide's last shape before the
# slide counts as underfilled. `Deck.save` uses the same number for its `thin` log, so the
# builder and the verifier report one figure rather than two.
#
# Calibrated to the reference deck's 253 words a content slide. Measured at 11pt body on the
# 6.5in content height, with bullets flowed into the two columns the measure requires:
#
#   174 words -> 62% empty      348 words -> 40% empty
#   232 words -> 54% empty      406 words -> 33% empty
#   290 words -> 47% empty      464 words -> 26% empty
#
# 0.50 asks for roughly 270 words — the reference's density with a little headroom. It stays
# a WARNING at any value: `min_ink_ratio` at 0.16 failed 8 of 17 good slides and sent the
# model into a rewrite loop that spent the run, and nothing here may ever do that again.
_UNDERFILL_IN = 0.50

# Strings that mean a template slot was never filled. Matched as whole tokens so a legitimate
# "TBDx" or a bracketed citation does not trip it.
_PLACEHOLDER = re.compile(
    r"(\[[A-Z][A-Z0-9 _-]{1,30}\]|\{\{[^}]+\}\}|\bTBD\b|\bTKTK\b|\bXXX+\b|\blorem\b|\bipsum\b)",
    re.I,
)


def _runs(shape):
    if not shape.has_text_frame:
        return
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            yield para, run


def _at_title_size(shape, top, fmt: T.Format) -> bool:
    if top is None:
        return False
    if top > Emu(int((fmt.margin_in["top"] + 1.6) * T.EMU_PER_INCH)):
        return False
    size = fmt.scale["title"].size
    return any(run.font.size is not None and abs(run.font.size.pt - size) <= 0.01
               for _, run in _runs(shape))


def _shape_key(shape):
    """python-pptx builds a fresh proxy on every access, so shapes cannot be compared with
    `is` across two walks of the same slide. The id in the XML is stable."""
    try:
        return shape.shape_id
    except Exception:  # noqa: BLE001 - a shape without an id is simply not the title
        return None


def _title_key(slide, fmt: T.Format):
    """The topmost run set at the title size in the top band — and only that one.

    Matching on size alone made every role that happens to share the title's size a title.
    A KPI row sits in the top band and its value type is the same size as a slide title, so
    a slide built from `kpi_row` alone counted zero bodies and reported `slide.title_only`.
    A slide has one title; the rest of the band is content."""
    best, best_top = None, None
    for shape in _shapes(slide):
        top = getattr(shape, "top", None)
        if not shape.has_text_frame or not shape.text_frame.text.strip():
            continue
        if not _at_title_size(shape, top, fmt):
            continue
        if best_top is None or top < best_top:
            best, best_top = _shape_key(shape), top
    return best


# Shapes the design system draws as furniture rather than content: the footer, and any
# deliberately full-bleed band or rail. A band is outside the margins BY DESIGN — that is what
# full-bleed means — so the margin checks cannot be applied to it without rejecting the exact
# treatment the reference deck uses on every slide.
DECOR_PREFIX = "docgen-"


def _is_decor(name) -> bool:
    return str(name or "").startswith(DECOR_PREFIX)


def _shapes(slide):
    for shape in slide.shapes:
        yield shape
        if shape.shape_type == 6:  # GROUP
            try:
                yield from shape.shapes
            except AttributeError:
                pass


def check(path: Path, fmt: T.Format, palette, report: Report) -> None:
    prs = Presentation(str(path))
    slide_w, slide_h = prs.slide_width, prs.slide_height
    m = fmt.margin_in
    left_lim = Emu(int(m["left"] * T.EMU_PER_INCH))
    right_lim = slide_w - Emu(int(m["right"] * T.EMU_PER_INCH))
    # Two lines, not one. The bottom margin is hard — nothing may cross it. The footer band
    # above it is reserved, so body content landing there collides with the footer but has
    # not left the slide.
    page_bottom = slide_h - Emu(int(m["bottom"] * T.EMU_PER_INCH))
    content_bottom = slide_h - Emu(int((m["bottom"] + fmt.gap_in["footer_h"]) * T.EMU_PER_INCH))
    allowed = set(fmt.sizes) | {fmt.table.header_size, fmt.table.cell_size}

    if not prs.slides:
        report.add(Issue("doc.empty", path.name, "the deck has no slides",
                         "the build saved before adding anything"))
        return

    total = len(prs.slides)
    for i, slide in enumerate(prs.slides, start=1):
        where = f"slide {i}"
        has_text = False
        # An ink ratio cannot tell "title and three short bullets" (2.2% of the slide) from
        # "title and nothing else" (2.0%) — the two are indistinguishable by area, which is
        # why the rendered floor was failing good slides while the real defect walked past
        # it. Counting the slide's own content shapes answers it exactly and needs no render.
        bodies = 0
        title_key = _title_key(slide, fmt)
        lowest = 0.0

        for shape in _shapes(slide):
            name = shape.name or "shape"
            try:
                left, top, width, height = shape.left, shape.top, shape.width, shape.height
            except (AttributeError, TypeError):
                left = top = width = height = None

            decor = _is_decor(name)
            if None not in (left, top, width, height) and not decor:
                if top + height > page_bottom:
                    over = (top + height - page_bottom) / T.EMU_PER_INCH
                    report.add(Issue(
                        "shape.below_content", f"{where} '{name}'",
                        f"bottom edge is {over:.2f}in past the bottom margin",
                        f"keep top+height under "
                        f"{page_bottom / T.EMU_PER_INCH:.2f}in — split the content across two "
                        f"slides rather than overflowing"))
                elif top + height > content_bottom:
                    report.add(Issue(
                        "shape.in_footer_band", f"{where} '{name}'",
                        "the shape reaches into the footer strip",
                        f"stop content at {content_bottom / T.EMU_PER_INCH:.2f}in so it "
                        f"cannot collide with the footer", WARNING))
                if left < left_lim or left + width > right_lim:
                    report.add(Issue(
                        "shape.outside_margin", f"{where} '{name}'",
                        f"spans {left / T.EMU_PER_INCH:.2f}in to "
                        f"{(left + width) / T.EMU_PER_INCH:.2f}in",
                        f"stay between {m['left']}in and "
                        f"{(slide_w / T.EMU_PER_INCH) - m['right']:.2f}in"))

            # Furniture does not count toward how full the slide is: a full-bleed band runs
            # to the edge on every slide and would make an empty one look finished.
            if not decor and top is not None and height is not None:
                lowest = max(lowest, (top + height) / T.EMU_PER_INCH)

            if not shape.has_text_frame and not decor:
                bodies += 1

            if shape.has_text_frame:
                text = shape.text_frame.text
                if text.strip():
                    has_text = True
                    if not decor and _shape_key(shape) != title_key:
                        bodies += 1
                    hit = _PLACEHOLDER.search(text)
                    if hit:
                        report.add(Issue(
                            "text.placeholder", f"{where} '{name}'",
                            f"unfilled placeholder {hit.group(0)!r}",
                            "replace it with the real value or drop the element"))
                elif shape.is_placeholder:
                    report.add(Issue(
                        "text.empty_placeholder", f"{where} '{name}'",
                        "an empty placeholder box",
                        "fill it or delete it — it renders as a visible gap", WARNING))

                for _, run in _runs(shape):
                    size = run.font.size
                    if size is not None:
                        pt = round(size.pt, 2)
                        if not any(abs(pt - a) <= 0.01 for a in allowed):
                            report.add(Issue(
                                "font.off_scale", f"{where} '{name}'",
                                f"{pt}pt is not in the pptx scale {sorted(allowed)}",
                                "take the size from docgen.tokens.PPTX.scale"))
                    face = run.font.name
                    if face and fmt.font.lower() not in face.lower():
                        report.add(Issue(
                            "font.family", f"{where} '{name}'",
                            f"{face!r} instead of {fmt.font}",
                            f"every run must be {fmt.font}"))

        if not has_text:
            report.add(Issue("slide.no_text", where, "the slide carries no text at all",
                             "a slide with only shapes reads as a mistake"))
        elif bodies == 0 and not (i == 1 or i == total):
            # The cover and a closing slide are allowed to be a title alone. Anywhere in the
            # middle of a deck it is a slide the build forgot to fill.
            report.add(Issue(
                "slide.title_only", where,
                "nothing on it but the title",
                "put the content under the title, or drop the slide and fold its point into "
                "the neighbouring one"))

        # `Deck.save` already computes this and writes it to the log, where nothing that
        # could act on it ever reads it. Measured on the reference deck this design system
        # exists to match, all 16 slides finish flush against the content bottom; a
        # generated deck of the same material left 2.87in — 43% of the height — empty.
        #
        # A WARNING, never an error: it is a thin slide, not a broken one, and an earlier
        # blocking version of this idea (min_ink_ratio at 0.16) failed 8 of 17 good slides
        # and sent the model into a rewrite loop. This reaches the model without ever
        # standing between a finished deck and the user.
        if has_text and lowest > 0:
            unused = content_bottom / T.EMU_PER_INCH - lowest
            if unused > fmt.content_h_in * _UNDERFILL_IN:
                report.add(Issue(
                    "slide.underfilled", where,
                    f"{unused:.1f}in of {fmt.content_h_in:.1f}in is empty below the content "
                    f"({unused / fmt.content_h_in:.0%})",
                    "a content slide carries about 250 words across three or four blocks — "
                    "add the evidence behind each claim, a second example, the number, or "
                    "fold this slide into the next one",
                    WARNING))
