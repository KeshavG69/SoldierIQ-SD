"""Build a workbook with the presentation the xlsx skill never specified.

No column widths, no freeze panes, no header styling, no date formats, no conditional
formatting, no autofilter, no print setup — none of it was in the skill, so every workbook
invented its own or went without.

Calibri rather than Inter on purpose: a workbook renders in the reader's Excel, where Inter is
not installed. It is the one format whose font belongs to the reader.
"""

from pathlib import Path
from statistics import quantiles
from typing import Dict, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter

from docgen import tokens as T
from docgen.palette import DEFAULT, Palette, active


def _argb(hex_color: str) -> str:
    return "FF" + hex_color.lstrip("#").upper()


class Book:
    def __init__(self, path, palette: Optional[Palette] = None):
        self.path = Path(path)
        self.fmt = T.XLSX
        self.p = palette or active()
        self.wb = Workbook()
        self.wb.remove(self.wb.active)

    def sheet(self, name: str, headers: Sequence[str], rows: Sequence[Sequence],
              formats: Optional[Dict[str, str]] = None, freeze: bool = True):
        headers = [str(h) for h in headers]
        rows = [list(r) for r in rows]
        ws = self.wb.create_sheet(title=str(name)[:31])
        ws.append(headers)
        for row in rows:
            ws.append(row)

        head_font = Font(name=self.fmt.font, size=self.fmt.scale["header"].size, bold=True,
                         color=_argb(self.p.on(self.p.primary)))
        head_fill = PatternFill("solid", fgColor=_argb(self.p.primary))
        body_font = Font(name=self.fmt.font, size=self.fmt.scale["body"].size)
        band = PatternFill("solid", fgColor=_argb(self.p.surface_alt))
        thin = Side(style="thin", color=_argb(self.p.rule))
        border = Border(bottom=thin)

        for cell in ws[1]:
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = border
        ws.row_dimensions[1].height = T.XLSX_HEADER_ROW_H

        fmt_by_col = self._number_formats(headers, rows, formats or {})
        for r in range(2, ws.max_row + 1):
            ws.row_dimensions[r].height = T.XLSX_ROW_H
            for c in range(1, len(headers) + 1):
                cell = ws.cell(row=r, column=c)
                cell.font = body_font
                nf = fmt_by_col.get(c)
                if nf:
                    cell.number_format = nf
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.alignment = Alignment(vertical="center", wrap_text=False)
                if r % 2 == 1:
                    cell.fill = band

        self._widths(ws, headers, rows)
        if freeze:
            ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
        self._print(ws, len(headers))
        return ws

    def summary(self, name: str, title: str, kpis: Sequence[Sequence[str]],
                notes: Optional[Sequence[str]] = None):
        """A front sheet: the headline numbers as count cards, then what they mean.

        A workbook opened on a wall of rows makes the reader find the story. Every other
        format in this system can state a number as a number; this one could not, so the
        headline ended up in a cell comment or nowhere."""
        ws = self.wb.create_sheet(title=str(name)[:31], index=0)
        ws.sheet_view.showGridLines = False

        ws["B2"] = str(title)
        ws["B2"].font = Font(name=self.fmt.font, size=self.fmt.scale["title"].size,
                             bold=True, color=_argb(self.p.primary))
        ws.row_dimensions[2].height = T.XLSX_HEADER_ROW_H * 1.4

        pairs = [k for k in (kpis or []) if k]
        fill = PatternFill("solid", fgColor=_argb(self.p.surface_alt))
        span = 2  # each card is two columns wide, with one blank between
        col = 2
        for value, label in pairs:
            letter = get_column_letter(col)
            end = get_column_letter(col + span - 1)
            ws.merge_cells(f"{letter}4:{end}4")
            ws.merge_cells(f"{letter}5:{end}5")

            top = ws[f"{letter}4"]
            top.value = str(value)
            top.font = Font(name=self.fmt.font, size=self.fmt.scale["title"].size,
                            bold=True, color=_argb(self.p.primary))
            top.alignment = Alignment(horizontal="left", vertical="center")

            bottom = ws[f"{letter}5"]
            bottom.value = str(label)
            bottom.font = Font(name=self.fmt.font, size=self.fmt.scale["note"].size,
                               color=_argb(self.p.muted))
            bottom.alignment = Alignment(horizontal="left", vertical="top")

            for r in (4, 5):
                for c in range(col, col + span):
                    ws.cell(row=r, column=c).fill = fill
            col += span + 1

        ws.row_dimensions[4].height = T.XLSX_HEADER_ROW_H * 1.5
        ws.row_dimensions[5].height = T.XLSX_ROW_H * 1.2

        row = 7
        for note in (notes or []):
            ws.cell(row=row, column=2, value=str(note)).font = Font(
                name=self.fmt.font, size=self.fmt.scale["body"].size)
            row += 1

        ws.column_dimensions["A"].width = 2
        for c in range(2, col + 1):
            ws.column_dimensions[get_column_letter(c)].width = 18
        return ws

    def data_bars(self, ws, column: str, *, tone: str = "info"):
        """In-cell bars down a numeric column, so magnitude reads without a chart.

        The one piece of conditional formatting worth having by default: it costs no space,
        survives sorting and filtering, and answers "which of these is big" at a glance."""
        from openpyxl.formatting.rule import DataBarRule

        color = {"good": self.p.good, "warn": self.p.warn,
                 "bad": self.p.bad}.get(tone, self.p.primary)
        if ws.max_row < 2:
            return ws
        ref = f"{column}2:{column}{ws.max_row}"
        ws.conditional_formatting.add(ref, DataBarRule(
            start_type="min", end_type="max",
            color=_argb(color).lstrip("FF"), showValue=True))
        return ws

    def chart(self, ws, *, kind: str = "bar", categories: str, values,
              x_title: str = "", y_title: str = "", title: str = "",
              anchor: Optional[str] = None, height_in: float = 3.0,
              width_in: float = 6.0):
        """A native Excel chart over a sheet's own columns, so it stays live on the data.

        `categories` and `values` are column letters ("A", or "C" / ["C", "D"]) in `ws`.
        `x_title` and `y_title` are what the axes denote: a reader can see a bar is 412
        tall, and nothing else on the sheet says 412 of what.
        """
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference

        kinds = {"bar": BarChart, "column": BarChart, "line": LineChart,
                 "pie": PieChart, "donut": PieChart}
        if kind not in kinds:
            raise ValueError(f"unknown chart kind {kind!r}; use {sorted(kinds)}")
        if ws.max_row < 2:
            raise ValueError("a chart needs at least one row of data")

        chart = kinds[kind]()
        if kind in ("bar", "column"):
            chart.type = "col"
        chart.style = 2
        if title:
            chart.title = str(title)
        chart.height = height_in * 2.54
        chart.width = width_in * 2.54

        cols = [values] if isinstance(values, str) else list(values)
        for letter in cols:
            index = column_index_from_string(letter)
            chart.add_data(
                Reference(ws, min_col=index, min_row=1, max_row=ws.max_row),
                titles_from_data=True,
            )
        cat_index = column_index_from_string(categories)
        chart.set_categories(
            Reference(ws, min_col=cat_index, min_row=2, max_row=ws.max_row))

        # Colours from the palette, as every other chart docgen draws. `chart.style = 2` alone
        # left Excel's own blue and orange in place, so a workbook built for a brand ignored
        # the brand_palette the request carried. Explicit fills win over the style.
        if kind in ("pie", "donut"):
            from openpyxl.chart.series import DataPoint

            for series in chart.series:
                for point in range(ws.max_row - 1):
                    dp = DataPoint(idx=point)
                    dp.graphicalProperties.solidFill = self.p.series(point).lstrip("#")
                    series.dPt.append(dp)
        else:
            for i, series in enumerate(chart.series):
                colour = self.p.series(i).lstrip("#")
                series.graphicalProperties.line.solidFill = colour
                if kind != "line":
                    series.graphicalProperties.solidFill = colour

        if kind not in ("pie", "donut"):
            # openpyxl writes no axis element at all unless `delete` is set False, and a
            # missing element is what Excel reads as "hide this axis" — so a title set on
            # an axis that was never written simply does not appear.
            chart.x_axis.delete = False
            chart.y_axis.delete = False
            if x_title:
                chart.x_axis.title = str(x_title)
            if y_title:
                chart.y_axis.title = str(y_title)

        ws.add_chart(chart, anchor or f"{get_column_letter(ws.max_column + 2)}2")
        return chart

    def _number_formats(self, headers, rows, override) -> Dict[int, str]:
        out = {}
        for i, header in enumerate(headers, start=1):
            key = override.get(header)
            if key:
                out[i] = T.NUMBER_FORMATS.get(key, key)
                continue
            values = [r[i - 1] for r in rows if i - 1 < len(r) and r[i - 1] is not None]
            if not values:
                continue
            if all(hasattr(v, "year") for v in values):
                out[i] = T.NUMBER_FORMATS["date"]
            elif all(isinstance(v, bool) is False and isinstance(v, (int, float))
                     for v in values):
                low = header.lower()
                if "%" in header or "rate" in low or "share" in low or "margin" in low:
                    out[i] = T.NUMBER_FORMATS["percent"]
                elif any(w in low for w in ("spend", "amount", "cost", "revenue", "value",
                                            "price", "$")):
                    out[i] = T.NUMBER_FORMATS["currency"]
                elif all(float(v).is_integer() for v in values):
                    out[i] = T.NUMBER_FORMATS["integer"]
                else:
                    out[i] = T.NUMBER_FORMATS["decimal"]
        return out

    def _widths(self, ws, headers, rows) -> None:
        """Sized to the content, clamped. A too-narrow number column renders ####; one sized
        to its longest outlier pushes everything else off the screen."""
        for i, header in enumerate(headers, start=1):
            lengths = [len(str(r[i - 1])) for r in rows
                       if i - 1 < len(r) and r[i - 1] is not None]
            if len(lengths) >= 8:
                typical = quantiles(lengths, n=20)[18]  # p95
            else:
                typical = max(lengths, default=0)
            width = max(len(header), typical) + T.XLSX_COL_PAD
            ws.column_dimensions[get_column_letter(i)].width = max(
                T.XLSX_COL_MIN, min(T.XLSX_COL_MAX, width))

    def _print(self, ws, columns: int) -> None:
        ws.page_setup.orientation = "landscape" if columns > 6 else "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "1:1"
        for edge, value in self.fmt.margin_in.items():
            setattr(ws.page_margins, edge, value)

    def save(self) -> Path:
        if not self.wb.sheetnames:
            raise ValueError("the workbook has no sheets")
        self.wb.save(str(self.path))
        return self.path
