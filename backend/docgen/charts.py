"""Charts drawn from the palette, so a figure matches the document it sits in.

The pdf skill said to route anything needing "more than 5 lines of reportlab" through
`image_gen_tool` — an image-model call, an S3 upload and a 30s download per graphic, for
output that carries no real numbers. That bar is right for illustration and wrong for a bar
chart, and it was the only option offered.
"""

import math
from typing import List, NamedTuple, Optional, Sequence, Tuple

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Group, Rect, String
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib import colors
from reportlab.lib.units import inch

from docgen import fonts
from docgen import tokens as T
from docgen.palette import DEFAULT, Palette, active


def _hex(value: str):
    return colors.HexColor(value)


def series_colors(p: Palette, n: int):
    """Ordered so a single-series chart is the brand primary and later series stay distinct.

    The old list was `[primary, accent, emphasis, info, muted]`, which contained duplicates in
    both directions: `DEFAULT.accent` and `DEFAULT.info` are both `#31708E`, so series 1 and 3
    drew in one colour, and `from_brand` set `emphasis = accent`, so a brand chart drew series
    1 and 2 identically. `Palette.sequence` is deduplicated by construction.
    """
    return [_hex(p.series(i)) for i in range(max(1, n))]


def _frame(width_in: float, height_in: float):
    return Drawing(width_in * inch, height_in * inch)


def _face() -> str:
    """The name reportlab will actually resolve. `fmt.font` is the name we want; when Inter
    is not installed it was never registered, and asking for it raises KeyError deep inside
    the renderer instead of falling back."""
    return fonts.register_pdf()[0]


def _style_axes(chart, p: Palette, fmt: T.Format, value_format=None):
    t = fmt.scale["caption"]
    for axis in (chart.categoryAxis, chart.valueAxis):
        axis.labels.fontName = _face()
        axis.labels.fontSize = t.size
        axis.labels.fillColor = _hex(p.muted)
        axis.strokeColor = _hex(p.rule)
    # A bar's length IS its value, so a bar chart must start at zero. reportlab picks a
    # "nice" minimum otherwise — a report's value axis started at 2.0, which made a $2.0M
    # category draw as no bar at all and every other bar look proportionally larger than it
    # was. Line charts keep the fitted range: there, position carries the value, not length.
    if isinstance(chart, VerticalBarChart):
        values = [v for row in (chart.data or []) for v in row if v is not None]
        if values and min(values) >= 0:
            chart.valueAxis.valueMin = 0
    chart.valueAxis.gridStrokeColor = _hex(p.rule)
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.valueAxis.visibleGrid = True
    chart.categoryAxis.visibleGrid = False
    if value_format:
        chart.valueAxis.labelTextFormat = value_format


# Legend geometry, in points. Measured against the real text rather than laid out on a fixed
# pitch: the previous legend put every entry 72pt after the last whatever its length, so any
# label wider than ~60pt ran into its neighbour — "Expired" printed over "ACH" in a shipped
# contract report, and the model spent four rebuilds failing to fix it from the spec, because
# nothing in the spec could.
_SWATCH, _SWATCH_GAP, _ITEM_GAP, _ROW_PITCH = 7.0, 4.0, 12.0, 1.7


def _text_w(text: str, size: float) -> float:
    return stringWidth(text, _face(), size)


def _fit(text: str, size: float, max_w: float) -> str:
    """`text`, shortened with an ellipsis until it fits `max_w`. Never wider, never empty."""
    text = str(text)
    if _text_w(text, size) <= max_w:
        return text
    while len(text) > 1 and _text_w(text + "…", size) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _legend_rows(names, size: float, max_w: float) -> List[List[Tuple[str, float]]]:
    """Entries packed left to right and wrapped, as (label, x) per row."""
    rows: List[List[Tuple[str, float]]] = [[]]
    x = 0.0
    for name in names:
        label = _fit(name, size, max(12.0, max_w - _SWATCH - _SWATCH_GAP))
        width = _SWATCH + _SWATCH_GAP + _text_w(label, size)
        if rows[-1] and x + width > max_w:
            rows.append([])
            x = 0.0
        rows[-1].append((label, x))
        x += width + _ITEM_GAP
    return rows


def _legend_height(names, fmt: T.Format, width_pt: float) -> float:
    size = fmt.scale["caption"].size
    return len(_legend_rows(names, size, width_pt)) * size * _ROW_PITCH + 4


def _legend(drawing, p: Palette, fmt: T.Format, names, swatches, *, width_pt: float,
            height_pt: float, x0: float = 0.0) -> None:
    """Draw a wrapped legend filling [0, height_pt] from the top row down."""
    size = fmt.scale["caption"].size
    pitch = size * _ROW_PITCH
    colour = iter(swatches)
    for r, row in enumerate(_legend_rows(names, size, width_pt)):
        baseline = height_pt - (r + 1) * pitch + (pitch - size) / 2 + 1
        for label, x in row:
            fill = next(colour)
            drawing.add(Rect(x0 + x, baseline, _SWATCH, _SWATCH, fillColor=fill,
                             strokeColor=None))
            drawing.add(String(x0 + x + _SWATCH + _SWATCH_GAP, baseline, label,
                               fontName=_face(), fontSize=size, fillColor=_hex(p.muted)))


# Height reserved below the plot for the category tick labels, the legend, and the x-axis
# title; width reserved at the left for the value tick labels and the rotated y-axis title.
_TICKS_H, _LEGEND_H, _AXIS_TITLE_H = 20, 24, 14
_TICKS_W, _AXIS_TITLE_W = 42, 16


def _axis_titles(d, p: Palette, fmt: T.Format, *, x_title: str, y_title: str,
                 left: float, bottom: float, plot_w: float, plot_h: float,
                 legend_h: float) -> None:
    """What the axes denote. A reader can see that a bar is 412 units tall; without this
    there is nothing on the figure that says 412 of what."""
    t = fmt.scale["caption"]
    if x_title:
        d.add(String(left + plot_w / 2.0, legend_h + 4, str(x_title),
                     fontName=_face(), fontSize=t.size, fillColor=_hex(p.text),
                     textAnchor="middle"))
    if y_title:
        label = String(0, 0, str(y_title), fontName=_face(), fontSize=t.size,
                       fillColor=_hex(p.text), textAnchor="middle")
        g = Group(label)
        g.rotate(90)
        g.translate(bottom + plot_h / 2.0, -(10))
        d.add(g)


class _Box(NamedTuple):
    left: float
    bottom: float
    width: float
    height: float
    legend_h: float
    cat_names: List[str]
    cat_angle: float


# Past this share of the figure height the category labels would be eating the chart.
_MAX_TICK_SHARE = 0.34


def _plot_box(width_in: float, height_in: float, *, labels, title: str,
              x_title: str, y_title: str, fmt: Optional[T.Format] = None,
              categories: Sequence = ()) -> _Box:
    """The plot area, shrunk to make room for everything around it — measured, not assumed.

    Two things used to be fixed and are now fitted: the legend (one row reserved, however
    many entries) and the category labels (one line reserved, however long). A category name
    wider than its slot now angles; one wider than the angled room is shortened with an
    ellipsis. Neither can overlap its neighbour.
    """
    fmt = fmt or T.PDF
    size = fmt.scale["caption"].size
    left = _TICKS_W + (_AXIS_TITLE_W if y_title else 0)
    width = width_in * inch - left - 14
    legend_h = _legend_height(labels, fmt, width_in * inch) if labels else 0

    names = [str(c) for c in categories]
    angle, ticks_h = 0.0, float(_TICKS_H)
    if names:
        slot = width / len(names)
        widest = max(_text_w(n, size) for n in names)
        if widest > slot * 0.92:
            angle = 35.0
            sin = math.sin(math.radians(angle))
            room = max(size * 2, height_in * inch * _MAX_TICK_SHARE - size - 6)
            names = [_fit(n, size, room / sin) for n in names]
            widest = max(_text_w(n, size) for n in names)
            ticks_h = min(widest * sin + size + 8, height_in * inch * _MAX_TICK_SHARE)

    bottom = ticks_h + legend_h + (_AXIS_TITLE_H if x_title else 0)
    height = height_in * inch - bottom - (22 if title else 10)
    return _Box(left, bottom, width, height, legend_h, names, angle)


def _apply_categories(chart, box: _Box) -> None:
    chart.categoryAxis.categoryNames = box.cat_names
    if box.cat_angle:
        chart.categoryAxis.labels.angle = box.cat_angle
        chart.categoryAxis.labels.boxAnchor = "ne"
        chart.categoryAxis.labels.dx = 2
        chart.categoryAxis.labels.dy = -2


def check_series(categories, series) -> list[list]:
    """The rows a chart will draw, or a ValueError naming what is wrong with them.

    reportlab and python-pptx both accept a chart with no numbers: they draw the axes over
    nothing, and the reader gets an empty frame where the evidence should be. A series that
    does not line up with the categories is the same defect one step later — the bars stop
    meaning what the labels say. Both are caught here, where the caller still has the data
    in hand, rather than surviving into a document nobody checks again.
    """
    cats = list(categories or [])
    rows = ([list(series)] if series and not isinstance(series[0], (list, tuple))
            else [list(s) for s in (series or [])])
    if not rows or not any(len(r) for r in rows):
        raise ValueError("chart needs at least one series of numbers; got none")
    if not cats:
        raise ValueError("chart needs categories to label its values; got none")
    for row in rows:
        if len(row) != len(cats):
            raise ValueError(
                f"chart series has {len(row)} values but there are {len(cats)} "
                "categories; they must match")
    return rows


def bar(categories: Sequence[str], series, *, labels: Optional[Sequence[str]] = None,
        width_in: float = 6.5, height_in: float = 2.6, palette: Optional[Palette] = None,
        fmt: Optional[T.Format] = None, value_format: str = "%d", title: str = "",
        x_title: str = "", y_title: str = ""):
    """`series` is one sequence of numbers, or several for a grouped chart."""
    p = palette or active()
    fmt = fmt or T.PDF
    rows = [list(series)] if series and not isinstance(series[0], (list, tuple)) else \
        [list(s) for s in series]

    d = _frame(width_in, height_in)
    chart = VerticalBarChart()
    box = _plot_box(width_in, height_in, labels=labels, title=title, x_title=x_title,
                    y_title=y_title, fmt=fmt, categories=categories)
    left, bottom, plot_w, plot_h, legend_h = box.left, box.bottom, box.width, box.height, \
        box.legend_h
    chart.x, chart.y, chart.width, chart.height = left, bottom, plot_w, plot_h
    chart.data = rows
    chart.barSpacing = 1.5
    chart.groupSpacing = 8
    chart.barWidth = 8
    swatches = series_colors(p, len(rows))
    for i, colour in enumerate(swatches):
        chart.bars[i].fillColor = colour
        chart.bars[i].strokeColor = None
    _style_axes(chart, p, fmt, value_format)
    _apply_categories(chart, box)
    d.add(chart)
    if title:
        d.add(String(0, height_in * inch - 12, title, fontName=_face(),
                     fontSize=fmt.scale["h3"].size, fillColor=_hex(p.text)))
    if labels:
        _legend(d, p, fmt, [str(l) for l in labels], swatches,
                width_pt=width_in * inch, height_pt=legend_h)
    _axis_titles(d, p, fmt, x_title=x_title, y_title=y_title, left=left, bottom=bottom,
                 plot_w=plot_w, plot_h=plot_h, legend_h=legend_h)
    return d


def line(categories: Sequence[str], series, *, labels: Optional[Sequence[str]] = None,
         width_in: float = 6.5, height_in: float = 2.6, palette: Optional[Palette] = None,
         fmt: Optional[T.Format] = None, value_format: str = "%d", title: str = "",
         x_title: str = "", y_title: str = ""):
    p = palette or active()
    fmt = fmt or T.PDF
    rows = [list(series)] if series and not isinstance(series[0], (list, tuple)) else \
        [list(s) for s in series]

    d = _frame(width_in, height_in)
    chart = HorizontalLineChart()
    box = _plot_box(width_in, height_in, labels=labels, title=title, x_title=x_title,
                    y_title=y_title, fmt=fmt, categories=categories)
    left, bottom, plot_w, plot_h, legend_h = box.left, box.bottom, box.width, box.height, \
        box.legend_h
    chart.x, chart.y, chart.width, chart.height = left, bottom, plot_w, plot_h
    chart.data = rows
    swatches = series_colors(p, len(rows))
    for i, colour in enumerate(swatches):
        chart.lines[i].strokeColor = colour
        chart.lines[i].strokeWidth = 1.6
    _style_axes(chart, p, fmt, value_format)
    _apply_categories(chart, box)
    d.add(chart)
    if title:
        d.add(String(0, height_in * inch - 12, title, fontName=_face(),
                     fontSize=fmt.scale["h3"].size, fillColor=_hex(p.text)))
    if labels:
        _legend(d, p, fmt, [str(l) for l in labels], swatches,
                width_pt=width_in * inch, height_pt=legend_h)
    _axis_titles(d, p, fmt, x_title=x_title, y_title=y_title, left=left, bottom=bottom,
                 plot_w=plot_w, plot_h=plot_h, legend_h=legend_h)
    return d


# Slices smaller than this are folded into "Other" only when the legend has no room for them;
# a legible legend beats a complete one that overprints itself.
_OTHER = "Other"


def _share(value: float, total: float) -> str:
    pct = 100.0 * value / total if total else 0.0
    if 0 < pct < 1:
        return "<1%"
    return f"{pct:.0f}%"


def donut(labels: Sequence[str], values: Sequence[float], *, width_in: float = 4.0,
          height_in: float = 2.6, palette: Optional[Palette] = None,
          fmt: Optional[T.Format] = None, title: str = ""):
    """A donut with a legend column beside it, each entry carrying its share.

    Labels are never drawn on or around the ring, and the legend is laid out by measuring
    its text: the previous version laid entries in one row at a fixed 72pt pitch under the
    ring, so neighbouring labels printed over each other whenever one ran long. When more
    slices exist than the column can hold, the smallest are folded into "Other" rather than
    overprinted.
    """
    p = palette or active()
    fmt = fmt or T.PDF
    size = fmt.scale["caption"].size
    d = _frame(width_in, height_in)

    pairs = [(str(l), float(v or 0)) for l, v in zip(labels, values)]
    total = sum(v for _, v in pairs)

    top = height_in * inch - (22 if title else 6)
    diameter = max(24.0, min(top - 6, width_in * inch * 0.42))
    pitch = size * 1.8
    legend_x = 6 + diameter + 18
    legend_w = width_in * inch - legend_x - 4
    rows_per_col = max(1, int((top - 4) // pitch))
    columns = 2 if (len(pairs) > rows_per_col and legend_w >= 2 * 110) else 1
    # A slice is identified only by its colour, so two slices sharing one make the chart
    # unreadable: the reader cannot tell which wedge is ACH and which is BACS. The palette
    # cycles after `len(sequence)` colours (6 for the house palette, 10 for most brands), so
    # capacity is bounded by distinct colours as well as by legend rows.
    capacity = min(rows_per_col * columns, len(p.sequence))

    if len(pairs) > capacity:
        # The data may already have its own "Other" bucket; fold the remainder into it rather
        # than printing "Other methods" and "Other" side by side, which reads as two things.
        own_other = next((kv for kv in pairs if kv[0].strip().lower().startswith("other")), None)
        ranked = sorted((kv for kv in pairs if kv is not own_other),
                        key=lambda kv: kv[1], reverse=True)
        kept = ranked[:capacity - 1]
        folded = sum(v for _, v in ranked[capacity - 1:]) + (own_other[1] if own_other else 0)
        keep = {id(kv) for kv in kept}
        pairs = [kv for kv in pairs if id(kv) in keep] + \
            [((own_other[0] if own_other else _OTHER), folded)]

    pie = Pie()
    pie.x = 6
    pie.y = (top - diameter) / 2
    pie.width = pie.height = diameter
    pie.data = [v for _, v in pairs] or [1]
    pie.labels = None
    pie.innerRadiusFraction = 0.55
    pie.slices.strokeColor = _hex(p.surface)
    pie.slices.strokeWidth = 1.2
    swatches = series_colors(p, len(pairs))
    for i, colour in enumerate(swatches[:len(pairs)]):
        pie.slices[i].fillColor = colour
    d.add(pie)

    if title:
        d.add(String(0, height_in * inch - 12, title, fontName=_face(),
                     fontSize=fmt.scale["h3"].size, fillColor=_hex(p.text)))

    # Capped, so a single short column does not stretch its percentages to the far edge of
    # the page, a hand's width away from the label they belong to.
    col_w = min(legend_w / columns, 190.0)
    block_h = min(len(pairs), rows_per_col) * pitch
    y_top = (top + block_h) / 2
    for i, ((label, value), colour) in enumerate(zip(pairs, swatches)):
        col, row = divmod(i, rows_per_col)
        x = legend_x + col * col_w
        baseline = y_top - (row + 1) * pitch + (pitch - size) / 2 + 1
        share = _share(value, total)
        share_w = _text_w(share, size)
        text_room = col_w - _SWATCH - _SWATCH_GAP - share_w - 10
        d.add(Rect(x, baseline, _SWATCH, _SWATCH, fillColor=colour, strokeColor=None))
        d.add(String(x + _SWATCH + _SWATCH_GAP, baseline, _fit(label, size, text_room),
                     fontName=_face(), fontSize=size, fillColor=_hex(p.text)))
        d.add(String(x + col_w - 6, baseline, share, fontName=_face(), fontSize=size,
                     fillColor=_hex(p.muted), textAnchor="end"))
    return d


def to_png(drawing, path, *, dpi: int = 200) -> "Path":
    """A chart as a raster, for a format with no native chart of its own (docx).

    reportlab's own raster backend needs `rlPyCairo`, which is not in the image, so the
    route is its always-available PDF renderer plus poppler — which the image installs and
    `docgen.checks` already shells out to. The drawing is the same object the PDF report
    embeds as vectors, so a chart looks identical across formats, axis titles included.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    from reportlab.graphics import renderPDF

    path = Path(path)
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "chart.pdf"
        renderPDF.drawToFile(drawing, str(pdf))
        stem = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-singlefile", str(pdf), str(stem)],
            check=True, capture_output=True,
        )
        out = stem.with_suffix(".png")
        if not out.exists():
            raise RuntimeError("pdftoppm produced no image for the chart")
        path.write_bytes(out.read_bytes())
    return path
