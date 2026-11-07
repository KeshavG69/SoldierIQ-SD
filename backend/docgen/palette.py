"""One palette for every generated document, derived from the request's brand colors.

Production generated documents in `#10b981`, `#dc2626`, `#7c3aed`, `#f59e0b` and `#0ea5e9` —
Tailwind defaults that appear in no brand palette — because the rule naming the accent lived
in a reference file the loader could not serve. Colors live here now so generated code takes
them rather than inventing them.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

# Semantic meaning is never brand-derived: a brand whose primary is red must not turn every
# status chip into a failure.
GOOD = "#1E7F4F"
WARN = "#B8860B"
BAD = "#C0392B"
INFO = "#31708E"

SEVERITY = {
    "critical": BAD,
    "high": "#D97706",
    "medium": WARN,
    "low": "#5A7D9A",
    "none": "#5A5F6B",
}


# The decorative sequence. Blocks used to take `p.accent` whatever they were — a row of four
# cards came out as four identical boxes, and a nine-slide deck measured ten shape fills all
# on `#F5F7FA`. These are what a block reaches for when it carries no semantic meaning.
#
# Ordered so NEIGHBOURS are far apart, not so the list reads prettily: adjacent cards are the
# ones a reader compares. Every adjacent pair is >=116 apart under `_distance` except the
# wrap from violet back to indigo (61), which only occurs past six blocks in one row.
#
# Kept clear of the semantic trio — the nearest decorative colour is 84 from GOOD, 110 from
# BAD, 125 from WARN — so a plain block is never mistaken for a status.
SEQUENCE = (
    "#2D4A8A",  # indigo
    "#8A5A2B",  # bronze
    "#31708E",  # teal
    "#6D2E46",  # berry
    "#4A6741",  # moss
    "#53497D",  # violet
)

# Below this two colours read as "the same colour" on a slide. 55 keeps indigo and violet
# (61) as separate entries while collapsing a brand accent onto a house colour it duplicates.
MIN_SEPARATION = 55.0


def _clean(value: str) -> str:
    v = str(value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    int(v, 16)
    if len(v) != 6:
        raise ValueError(f"not a 6-digit hex color: {value!r}")
    return "#" + v.upper()


def _rgb(hex_color: str):
    v = hex_color.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _mix(hex_color: str, toward: str, amount: float) -> str:
    a, b = _rgb(hex_color), _rgb(toward)
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b))


def _luminance(hex_color: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (v / 255 for v in _rgb(hex_color))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _distance(a: str, b: str) -> float:
    """Weighted RGB distance — enough to answer "do these two cards look the same?".

    The job here is deduplication, not colour science: a brand whose accent already matches a
    house colour must not appear twice in one row.
    """
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    rm = (r1 + r2) / 2
    return ((2 + rm / 256) * (r1 - r2) ** 2
            + 4 * (g1 - g2) ** 2
            + (2 + (255 - rm) / 256) * (b1 - b2) ** 2) ** 0.5


def _distinct(candidates, minimum: float = MIN_SEPARATION):
    """Drop any colour that is too close to one already kept, preserving order."""
    out = []
    for c in candidates:
        if all(_distance(c, kept) >= minimum for kept in out):
            out.append(c)
    return out


def _readable(hex_color: str, minimum: float = 3.0) -> str:
    """The colour, darkened just enough to hold `minimum` contrast against white.

    A decorative colour is drawn as a card edge, a heading and a KPI value, all on a light
    fill. A brand is free to send a pale yellow; used as-is it would be an invisible heading.
    Darkening keeps the hue — it is still the brand's colour — and 3:1 is the WCAG floor for
    the large bold text these colours carry.
    """
    colour = hex_color
    for _ in range(16):
        if _contrast(colour, "#FFFFFF") >= minimum:
            return colour
        colour = _mix(colour, "#000000", 0.12)
    return colour


@dataclass(frozen=True)
class Palette:
    # PriceIQ: deep navy for dark surfaces (cover, table headers, section bands) and the
    # app's primary blue (#2563EB) for every accent — eyebrows, rules, KPI figures, chart
    # highlights. A spec's `brand` overrides these per document.
    primary: str = "#0F1E3D"
    accent: str = "#2563EB"
    emphasis: str = "#1E3A8A"
    text: str = "#0F172A"
    muted: str = "#5A5F6B"
    rule: str = "#E2E8F0"
    surface: str = "#FFFFFF"
    surface_alt: str = "#F1F5F9"
    band: str = "#E8EEF9"

    good: str = GOOD
    warn: str = WARN
    bad: str = BAD
    info: str = INFO

    # Set by `from_brand`. A brand palette draws every decorative colour from the brand;
    # the house palette uses the house sequence.
    brand: bool = False

    @property
    def sequence(self) -> tuple:
        """Decorative colours for this palette, deduplicated, in the order blocks take them.

        With a brand palette, every entry comes from the brand. Without one, the house
        palette's three lead and the house ramp follows.
        """
        if not self.brand:
            return tuple(_distinct([self.primary, self.accent, self.emphasis, *SEQUENCE]))
        # Every colour from the payload's brand_palette, never from the house ramp: the
        # brand's own three first, then darker and lighter steps of each. A deck sent with a
        # green-and-gold brand used to turn indigo and bronze from its fourth block on.
        # `_distinct` drops steps too close to one already kept, so a one-colour brand
        # yields fewer entries rather than near-duplicates — neighbouring blocks still differ.
        #
        # The brand's own hexes are used exactly — a card edge, a fill tint and a chart bar
        # show the colour that was sent. Only the steps generated here must be legible on
        # white to be kept; text drawn in any of these colours goes through `ink()`.
        base = [self.primary, self.accent, self.emphasis]
        steps = ([_mix(c, "#000000", 0.35) for c in base]
                 + [_mix(c, "#FFFFFF", 0.30) for c in base]
                 + [_mix(c, "#000000", 0.60) for c in base])
        legible = [c for c in steps if _contrast(c, "#FFFFFF") >= 3.0]
        return tuple(_distinct(base + legible))

    def series(self, index: int) -> str:
        """The index-th decorative colour, cycling."""
        seq = self.sequence
        return seq[int(index) % len(seq)]

    def ink(self, hex_color: str) -> str:
        """A decorative colour, safe to set text in: the same hue, darkened only if it would
        not read on a light fill. A no-op for every house colour and for most brands; it
        exists for the brand that sends a pale gold or yellow."""
        return _readable(_clean(hex_color))

    def tint(self, hex_color: str, amount: float = 0.86) -> str:
        """A colour as a block fill: enough hue to tell two cards apart, light enough that
        `text` still reads on it. Replaces the flat `surface_alt` every block used to take.

        0.86 is chosen against the block's other two colour carriers, not on its own: the edge
        rule and the heading already sit at full strength, so the fill supports them rather
        than competing. It lands 48 from the old flat `#F5F7FA` under `_distance` — plainly a
        different colour — while `text` still reads at 13:1, far past the 4.5:1 floor. Legibility
        is not what caps this; 0.80 still clears 12:1. Content surfaces stay light on purpose,
        which is `design.md`'s rule and the reason this is a tint and not the colour itself.
        """
        return _mix(_clean(hex_color), "#FFFFFF", amount)

    def severity(self, level: str) -> str:
        return SEVERITY.get(str(level or "").strip().lower(), SEVERITY["none"])

    def on(self, fill: str) -> str:
        """Readable text for any filled surface. Restated as prose in four places before this.

        Picks whichever of the two text tokens actually wins on contrast rather than guessing
        from a brightness threshold. The skills used `R+G+B < ~450`, which puts white text on
        `#B8860B` and on `#00FF00` — both well under 3:1.
        """
        f = _clean(fill)
        return max((self.surface, self.text), key=lambda c: _contrast(c, f))

    @classmethod
    def from_brand(
        cls,
        primary: Optional[str] = None,
        secondary_1: Optional[str] = None,
        secondary_2: Optional[str] = None,
    ) -> "Palette":
        if not primary:
            return cls()
        p = _clean(primary)
        a = _clean(secondary_1) if secondary_1 else _mix(p, "#FFFFFF", 0.35)
        # Not `a`. Defaulting emphasis to the accent put the same hex at index 1 and 2 of the
        # sequence, so two chart series drew in one colour and a three-card row showed two
        # identical cards. A darker shade of the brand stays on-brand and stays distinct.
        e = _clean(secondary_2) if secondary_2 else _mix(p, "#000000", 0.35)
        return cls(
            primary=p,
            accent=a,
            emphasis=e,
            band=_mix(p, "#FFFFFF", 0.92),
            surface_alt=_mix(p, "#FFFFFF", 0.96),
            brand=True,
        )

    def replace(self, **kw) -> "Palette":
        return replace(self, **{k: (v if k == "brand" else _clean(v)) for k, v in kw.items()})


DEFAULT = Palette()

# The request's brand colours, for the duration of one agent run.
#
# `brand_palette` arrives on the /query payload and reached the model as a paragraph of
# prompt telling it to call `resolve_palette(brand)` and pass the result to the builder. A
# document therefore came out on-brand only when the model remembered two steps, and the
# measured result was that it did not: every deck rendered in the house navy whatever brand
# was sent. Prompt text cannot be the transport for something the builder can simply read.
#
# A ContextVar for the same reason `python_repl_tool.set_session_id` is one: the orchestrator
# sets it per run, `asyncio.to_thread` carries the context into the worker that executes the
# generated script, and nothing leaks into the next run.
_active: ContextVar[Optional[Palette]] = ContextVar("docgen_brand_palette", default=None)


def use_brand(brand: Optional[Mapping[str, str]]) -> Palette:
    """Make `brand` the palette every builder in this run defaults to.

    Never raises: a malformed palette on the request must not take down generation, so a bad
    value falls back to the house palette exactly as `resolve_palette` does.
    """
    palette = resolve_palette(brand, _fallback_to_active=False)
    _active.set(palette)
    if palette is not DEFAULT:
        logger.info("docgen: brand palette active (primary=%s)", palette.primary)
    return palette


def clear_brand() -> None:
    _active.set(None)


def active() -> Palette:
    """The palette a builder takes when it is not given one explicitly."""
    return _active.get() or DEFAULT


def resolve_palette(brand: Optional[Mapping[str, str]] = None,
                    *, _fallback_to_active: bool = True) -> Palette:
    """`resolve_palette(None)` returns the run's brand palette, not the house default.

    That is what makes `Deck(...)` on its own come out on-brand: the skills already tell the
    model to call this with whatever it has, and passing nothing is the common case.
    """
    if not brand:
        return active() if _fallback_to_active else DEFAULT
    try:
        return Palette.from_brand(
            brand.get("primary"), brand.get("secondary_1"), brand.get("secondary_2")
        )
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning("docgen: ignoring malformed brand palette %r (%s)", brand, exc)
        return active() if _fallback_to_active else DEFAULT
