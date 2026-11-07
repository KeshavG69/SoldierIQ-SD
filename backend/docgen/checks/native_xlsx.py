"""Structural checks on a workbook.

The xlsx skill specified none of this: no column widths, no freeze panes, no header styling,
no date formats, no autofilter, no print setup. A workbook has no page geometry until someone
prints it, so this is the whole check — there is no rendered pass.
"""

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from docgen import tokens as T
from docgen.checks import ERROR, WARNING, Issue, Report

_DEFAULT_WIDTH = 8.43
_SAMPLE_ROWS = 200
# Beyond about a screenful the header scrolls out of sight and the columns lose meaning.
_SCROLLS_AFTER_ROWS = 15


def _is_dateish(value) -> bool:
    return hasattr(value, "year") and hasattr(value, "month")


def check(path: Path, fmt: T.Format, palette, report: Report) -> None:
    wb = load_workbook(str(path))

    for ws in wb.worksheets:
        where = ws.title
        # A sheet with gridlines deliberately switched off is a dashboard, not a table:
        # `Book.summary` lays out count cards and prose there, and it has no header row by
        # design. Every check below is about tabular data and none of them apply to it.
        # `is False`, not falsy: openpyxl leaves this None on a sheet nobody has touched,
        # and `not None` would exempt every ordinary workbook from every check below.
        if ws.sheet_view.showGridLines is False:
            continue
        if ws.max_row <= 1 and ws.max_column <= 1 and ws["A1"].value in (None, ""):
            report.add(Issue("sheet.empty", where, "the sheet has no data",
                             "remove the empty sheet or populate it"))
            continue

        header = [c for c in next(ws.iter_rows(min_row=1, max_row=1), ())]
        labelled = [c for c in header if c.value not in (None, "")]
        if not labelled:
            report.add(Issue("sheet.no_header", where, "row 1 carries no column labels",
                             "write a header row — every other check depends on it"))
            continue

        if not any(c.font and c.font.bold for c in labelled):
            report.add(Issue("header.unstyled", where, "the header row is not bold",
                             "use docgen.xlsx.Book so the header is styled once"))
        if not any(c.fill and c.fill.fgColor and c.fill.fgColor.rgb
                   not in (None, "00000000") for c in labelled):
            report.add(Issue("header.no_fill", where, "the header row has no fill",
                             "fill it with the palette primary and set readable text",
                             WARNING))

        if not ws.freeze_panes:
            # On a sheet short enough to see at once this is an improvement, not a defect,
            # and blocking delivery over it would reject correct work. Replaying production
            # workbooks put 21% in this bucket, most of them small summary sheets.
            scrolls = ws.max_row > _SCROLLS_AFTER_ROWS
            report.add(Issue(
                "sheet.no_freeze", where,
                f"no frozen header over {ws.max_row} rows" if scrolls else "no frozen header",
                "freeze below the header row so it stays visible when scrolling",
                ERROR if scrolls else WARNING))
        if not ws.auto_filter.ref:
            report.add(Issue("sheet.no_filter", where, "no autofilter on the table",
                             "set auto_filter over the used range", WARNING))

        default_cols = []
        for c in labelled:
            letter = get_column_letter(c.column)
            dim = ws.column_dimensions.get(letter)
            if dim is None or dim.width is None or abs(dim.width - _DEFAULT_WIDTH) < 0.01:
                default_cols.append(letter)
        if default_cols:
            report.add(Issue(
                "column.default_width", where,
                f"column(s) {default_cols[:8]} are at the default width",
                "size columns to their content — a too-narrow number column renders ####"))

        unformatted = set()
        for row in ws.iter_rows(min_row=2, max_row=min(ws.max_row, _SAMPLE_ROWS)):
            for cell in row:
                if _is_dateish(cell.value) and "y" not in str(cell.number_format).lower():
                    unformatted.add(get_column_letter(cell.column))
        if unformatted:
            report.add(Issue(
                "cell.unformatted_date", where,
                f"date values in column(s) {sorted(unformatted)[:8]} have no date format",
                f"apply {T.NUMBER_FORMATS['date']!r}"))

        if ws.max_column > 6 and ws.page_setup.orientation != "landscape":
            report.add(Issue(
                "print.orientation", where,
                f"{ws.max_column} columns in portrait",
                "set landscape and fit-to-width, or the printed sheet splits", WARNING))
