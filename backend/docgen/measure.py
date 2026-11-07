"""How wide a string actually is, so a builder can reserve the room it will really need.

`Slide._height_for` used to divide the character count by an assumed average glyph width of
half the point size. At full content width that estimate is close — measured against real
metrics it was right on 8 of 8 realistic strings. It falls apart everywhere the box is
narrow, which is where decks put text: a KPI tile reserved one line for its label whatever
the label said, and a five-column table reserved one line per row and then squeezed the
columns to 52% of their natural width, so every cell wrapped and the table rendered 1.09in
past the height the builder had declared. Neither shows up in the file's own structure — the
declared geometry is fine — so it surfaced only in the rendered pass, as "text overflow" with
no locator, and the model was left rewriting strings and guessing.

reportlab's metrics are the same ones the verifier's renderer resolves, and Inter is
registered from the same place, so the builder and the checker measure the same glyphs.
"""

from functools import lru_cache
from typing import List

from docgen import fonts


@lru_cache(maxsize=4)
def _faces() -> tuple:
    return fonts.register_pdf()


def face(bold: bool = False) -> str:
    regular, strong = _faces()
    return strong if bold else regular


def width_pt(text: str, size: float, bold: bool = False) -> float:
    from reportlab.pdfbase import pdfmetrics

    return pdfmetrics.stringWidth(str(text), face(bold), size)


def wrap(text: str, size: float, width_in: float, bold: bool = False) -> List[str]:
    """Greedy word wrap, the way a text frame breaks it.

    A word longer than the line is left on its own line rather than split: the renderer will
    overflow it horizontally, which the margin check catches. Pretending it wrapped would
    hide that.
    """
    limit = max(1.0, width_in * 72)
    out: List[str] = []
    line = ""
    for word in str(text).split():
        trial = f"{line} {word}".strip()
        if line and width_pt(trial, size, bold) > limit:
            out.append(line)
            line = word
        else:
            line = trial
    if line:
        out.append(line)
    return out or [""]


def lines(text: str, size: float, width_in: float, bold: bool = False) -> int:
    return len(wrap(text, size, width_in, bold))


# Typographic optimum is 45-90 characters a line; past about 100 the eye loses the return
# sweep and re-reads the line it just finished. A 13.3in slide at 11pt runs to 177.
MAX_LINE_CHARS = 90
_SAMPLE = "the quick brown fox jumps over the lazy dog and keeps on running "


def chars_per_line(width_in: float, size: float, bold: bool = False) -> float:
    """How many characters of ordinary prose fit on one line of this measure."""
    if width_in <= 0 or size <= 0:
        return 0.0
    avg = width_pt(_SAMPLE, size, bold) / len(_SAMPLE)
    return (width_in * 72) / avg if avg else 0.0


def columns_for(width_in: float, size: float, *, maximum: int = 3) -> int:
    """The fewest columns that bring this measure back under the ceiling."""
    for n in range(1, maximum + 1):
        # `width_in` already excludes the outer margins; each split adds a gutter.
        per = (width_in - 0.20 * (n - 1)) / n
        if chars_per_line(per, size) <= MAX_LINE_CHARS:
            return n
    return maximum


def natural_width_in(text: str, size: float, bold: bool = False) -> float:
    return width_pt(text, size, bold) / 72.0
