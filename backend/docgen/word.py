"""Build a Word document from content.

Standardised on python-docx. Production split Word generation across two libraries — 21
scripts used python-docx and 33 shelled out to docx-js — and a Python token module cannot
serve a Node generator, so a split runtime means two design systems or none.

Styles are registered once from the tokens, which is also where pagination lives: headings
are kept with their text and table rows do not split, neither of which the skill specified
despite claiming to.
"""

from pathlib import Path
from typing import Iterable, Optional, Sequence

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from docgen import tokens as T
from docgen.palette import DEFAULT, Palette, active

_ROLE_STYLE = {
    "title": "Title",
    "h1": "Heading 1",
    "h2": "Heading 2",
    "h3": "Heading 3",
    "body": "Normal",
    "bullet": "List Bullet",
    "caption": "Caption",
}


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#").upper())


class Doc:
    def __init__(self, path, title: str = "", subtitle: str = "",
                 palette: Optional[Palette] = None, author: str = "SoldierIQ"):
        self.path = Path(path)
        self.fmt = T.DOCX
        self.p = palette or active()
        # How many neutral blocks this document has drawn — see `_next_accent`.
        self._decor = 0
        self.doc = Document()
        self.doc.core_properties.title = title or self.path.stem
        self.doc.core_properties.author = author
        self.doc.core_properties.subject = subtitle
        self._page()
        self._styles()
        if title:
            self.title(title, subtitle)

    def _page(self) -> None:
        for section in self.doc.sections:
            section.page_width = Inches(self.fmt.page_w_in)
            section.page_height = Inches(self.fmt.page_h_in)
            for edge, value in self.fmt.margin_in.items():
                setattr(section, f"{edge}_margin", Inches(value))

    def _styles(self) -> None:
        for role, name in _ROLE_STYLE.items():
            t = self.fmt.scale[role]
            try:
                style = self.doc.styles[name]
            except KeyError:
                continue
            style.font.name = self.fmt.font
            style.font.size = Pt(t.size)
            style.font.bold = t.bold or None
            style.font.color.rgb = _rgb(self.p.primary if role.startswith("h") else self.p.text)
            style.font.italic = False
            rpr = style.element.get_or_add_rPr()
            rfonts = rpr.get_or_add_rFonts()
            for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                rfonts.set(qn(f"w:{attr}"), self.fmt.font)
            pf = style.paragraph_format
            pf.space_before = Pt(t.space_before)
            pf.space_after = Pt(t.space_after)
            pf.line_spacing = t.leading
            pf.widow_control = True
            if role in ("title", "h1", "h2", "h3"):
                pf.keep_with_next = True
                pf.keep_together = True

    # ── content ───────────────────────────────────────────────────────────────
    def _p(self, text: str, role: str, color: Optional[str] = None):
        para = self.doc.add_paragraph(str(text), style=_ROLE_STYLE[role])
        for run in para.runs:
            run.font.name = self.fmt.font
            run.font.size = Pt(self.fmt.scale[role].size)
            if color:
                run.font.color.rgb = _rgb(color)
        return para

    def title(self, text: str, subtitle: str = "") -> "Doc":
        self._p(text, "title", self.p.primary)
        if subtitle:
            self._p(subtitle, "caption", self.p.muted)
        return self

    def h1(self, text: str) -> "Doc":
        return self._h(text, "h1")

    def h2(self, text: str) -> "Doc":
        return self._h(text, "h2")

    def h3(self, text: str) -> "Doc":
        return self._h(text, "h3")

    def _h(self, text: str, role: str) -> "Doc":
        self._p(text, role, self.p.primary)
        return self

    def body(self, text: str) -> "Doc":
        self._p(text, "body")
        return self

    def caption(self, text: str) -> "Doc":
        self._p(text, "caption", self.p.muted)
        return self

    def bullets(self, items: Iterable[str]) -> "Doc":
        for item in items:
            self._p(item, "bullet")
        return self

    def question(self, number, text: str, marks=None) -> "Doc":
        """A numbered question, with the number hanging beside the text.

        Word does this natively: a left indent with a matching negative first-line indent
        puts the number in the gutter and aligns every wrapped line under the question. The
        marks go on a right tab at the measure. Same signature as `Report.question`, so a
        paper reads identically whether it was asked for as .pdf or .docx."""
        gutter = 0.34
        label = str(number)
        if not label.rstrip().endswith((".", ")")):
            label += "."

        para = self.doc.add_paragraph(style=_ROLE_STYLE["body"])
        fmt = para.paragraph_format
        fmt.left_indent = Inches(gutter)
        fmt.first_line_indent = Inches(-gutter)
        fmt.keep_together = True

        run = para.add_run(f"{label}\t")
        run.bold = True
        para.add_run(str(text))

        if marks is not None:
            tabs = fmt.tab_stops
            tabs.add_tab_stop(Inches(gutter))
            tabs.add_tab_stop(Inches(self.fmt.content_w_in - gutter), WD_TAB_ALIGNMENT.RIGHT)
            marks_run = para.add_run(f"\t{marks}")
            marks_run.font.color.rgb = _rgb(self.p.muted)
            marks_run.font.size = Pt(self.fmt.scale["caption"].size)
        else:
            fmt.tab_stops.add_tab_stop(Inches(gutter))

        for r in para.runs:
            r.font.name = self.fmt.font
            if r.font.size is None:
                r.font.size = Pt(self.fmt.scale["body"].size)
        return self

    def options(self, items: Iterable[str], columns: int = 2) -> "Doc":
        """The answer choices as a grid, indented under the question.

        Run together inside the question paragraph — which is what `body()` did — (a) to
        (d) are unreadable as a set."""
        items = [str(i) for i in items]
        if not items:
            return self
        columns = max(1, min(int(columns), len(items)))
        rows = [items[i:i + columns] for i in range(0, len(items), columns)]

        table = self.doc.add_table(rows=len(rows), cols=columns)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        width = (self.fmt.content_w_in - 0.34) / columns
        for r, row in enumerate(rows):
            for c in range(columns):
                cell = table.cell(r, c)
                cell.width = Inches(width)
                para = cell.paragraphs[0]
                para.text = row[c] if c < len(row) else ""
                for run in para.runs:
                    run.font.name = self.fmt.font
                    run.font.size = Pt(self.fmt.scale["body"].size)
        table.left_indent = Inches(0.34) if hasattr(table, "left_indent") else None
        self._indent_table(table, 0.34)
        return self

    def _indent_table(self, table, inches: float) -> None:
        """python-docx exposes no table indent; it is a `w:tblInd` on the properties."""
        from docx.oxml import OxmlElement

        ind = OxmlElement("w:tblInd")
        ind.set(qn("w:w"), str(int(inches * 1440)))
        ind.set(qn("w:type"), "dxa")
        table._tbl.tblPr.append(ind)

    def chart(self, kind: str, categories: Sequence[str], series, *,
              labels: Optional[Sequence[str]] = None, title: str = "",
              x_title: str = "", y_title: str = "", height_in: float = 2.6,
              value_format: str = "%d") -> "Doc":
        """The same chart the PDF report draws, placed as a picture.

        python-docx has no chart API, so this is the one format that cannot carry a live
        chart. It is still drawn by `docgen.charts` from the document's own palette and
        tokens, so a figure matches its siblings in the other formats — axis titles
        included. `x_title` and `y_title` are what the axes denote; a reader can see a bar
        is 412 tall but not 412 of what.
        """
        import tempfile

        from docgen.charts import check_series
        check_series(categories, series)
        from docgen import charts

        draw = {"bar": charts.bar, "line": charts.line, "donut": charts.donut}.get(kind)
        if draw is None:
            raise ValueError(f"unknown chart kind {kind!r}; use bar, line or donut")
        width_in = self.fmt.content_w_in
        kw = dict(width_in=width_in, height_in=height_in, palette=self.p, fmt=self.fmt,
                  title=title)
        if kind == "donut":
            drawing = draw(categories, series, **kw)
        else:
            drawing = draw(categories, series, labels=labels, value_format=value_format,
                           x_title=x_title, y_title=y_title, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            png = charts.to_png(drawing, Path(tmp) / "chart.png")
            self.doc.add_picture(str(png), width=Inches(width_in))
        self.doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        return self

    # ── composed blocks ───────────────────────────────────────────────────────
    def _gap(self) -> None:
        """One empty paragraph between blocks, never two.

        Each block used to append its own spacer unconditionally, so two blocks in a row
        left a run of blanks and the verifier reported `text.blank_run` on a document that
        was actually fine."""
        paras = self.doc.paragraphs
        if paras and not paras[-1].text.strip() and not paras[-1].runs:
            return
        self.doc.add_paragraph()

    def _tone(self, tone: str) -> str:
        return {"good": self.p.good, "warn": self.p.warn,
                "bad": self.p.bad}.get(tone, self.p.accent)

    def _next_accent(self, tone: str) -> str:
        """The colour for one block: its status if it has one, else the next decorative hue.

        An explicit tone still wins outright, so a status keeps one colour throughout; only
        the neutral default advances. Shared with `Slide._next_accent` so a deck and the
        report that accompanies it colour the same content the same way.
        """
        semantic = {"good": self.p.good, "warn": self.p.warn, "bad": self.p.bad}.get(tone)
        if semantic:
            return semantic
        colour = self.p.series(self._decor)
        self._decor += 1
        return colour

    def _plain_table(self, rows: int, cols: int):
        """A table used as a layout grid rather than as data — no borders, no banding."""
        table = self.doc.add_table(rows=rows, cols=cols)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.autofit = False
        self._no_borders(table)
        return table

    def _no_borders(self, table) -> None:
        from docx.oxml import OxmlElement

        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "none")
            el.set(qn("w:sz"), "0")
            borders.append(el)
        table._tbl.tblPr.append(borders)

    def _fill(self, cell, color: str) -> None:
        shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), color.lstrip("#"))
        cell._tc.get_or_add_tcPr().append(shd)

    def _accent_edge(self, cell, color: str, width_eighths: int = 24) -> None:
        """A coloured rule down the left edge — the accent bar every card in this system has."""
        from docx.oxml import OxmlElement

        borders = OxmlElement("w:tcBorders")
        left = OxmlElement("w:left")
        left.set(qn("w:val"), "single")
        left.set(qn("w:sz"), str(width_eighths))
        left.set(qn("w:color"), color.lstrip("#"))
        borders.append(left)
        cell._tc.get_or_add_tcPr().append(borders)

    def _block_text(self, cell, head: str, body: str = "", *,
                    head_role: str = "h3", head_color=None) -> None:
        cell.text = ""
        para = cell.paragraphs[0]
        para.style = self.doc.styles[_ROLE_STYLE[head_role]]
        run = para.add_run(str(head))
        run.font.name = self.fmt.font
        run.font.size = Pt(self.fmt.scale[head_role].size)
        run.font.bold = True
        run.font.color.rgb = _rgb(head_color or self.p.primary)
        if body:
            second = cell.add_paragraph()
            second.style = self.doc.styles[_ROLE_STYLE["body"]]
            brun = second.add_run(str(body))
            brun.font.name = self.fmt.font
            brun.font.size = Pt(self.fmt.scale["body"].size)
            brun.font.color.rgb = _rgb(self.p.text)

    def kpi_row(self, pairs: Sequence[Sequence[str]]) -> "Doc":
        """Count cards. A Word report had no way to state a number as a number — every
        headline figure ended up inside a sentence, where nobody scanning the page finds it."""
        pairs = [p for p in pairs if p]
        if not pairs:
            return self
        table = self._plain_table(2, len(pairs))
        width = self.fmt.content_w_in / len(pairs)
        for index, (value, label) in enumerate(pairs):
            # A colour per card, the way the deck's tiles take one — the two used to share
            # a grey tile and a primary figure, so a report's KPIs were one colour.
            accent = self._next_accent("info")
            top, bottom = table.cell(0, index), table.cell(1, index)
            for cell in (top, bottom):
                cell.width = Inches(width)
                self._fill(cell, self.p.tint(accent))
            # No edge rule here: Word sets the figure flush against a left border, and at
            # title size that crowds it. The fill and the figure carry the colour.
            top.text = ""
            run = top.paragraphs[0].add_run(str(value))
            run.font.name, run.font.bold = self.fmt.font, True
            run.font.size = Pt(self.fmt.scale["title"].size)
            run.font.color.rgb = _rgb(self.p.ink(accent))
            bottom.text = ""
            lrun = bottom.paragraphs[0].add_run(str(label))
            lrun.font.name = self.fmt.font
            lrun.font.size = Pt(self.fmt.scale["caption"].size)
            lrun.font.color.rgb = _rgb(self.p.muted)
        for index in range(len(pairs)):
            table.columns[index].width = Inches(width)
        self._gap()
        return self

    def columns(self, items: Sequence, *, tone: str = "info") -> "Doc":
        """Titled cards side by side, so a page can carry three points across rather than
        three points down."""
        items = [i for i in items if i]
        if not items:
            return self
        pairs = [(i, "") if isinstance(i, str) else (i[0], i[1] if len(i) > 1 else "")
                 for i in items]
        table = self._plain_table(1, len(pairs))
        width = self.fmt.content_w_in / len(pairs)
        for index, (head, body) in enumerate(pairs):
            # Inside the loop: resolved once above, it painted every card in the row the
            # same colour, so a three-card row was three identical boxes.
            accent = self._next_accent(tone)
            cell = table.cell(0, index)
            cell.width = Inches(width)
            self._fill(cell, self.p.tint(accent))
            self._accent_edge(cell, accent)
            self._block_text(cell, str(head), str(body),
                             head_role="h3" if body else "body",
                             head_color=self.p.ink(accent) if body else self.p.text)
        for index in range(len(pairs)):
            table.columns[index].width = Inches(width)
        self._gap()
        return self

    def callout(self, text: str, tone: str = "info") -> "Doc":
        table = self._plain_table(1, 1)
        cell = table.cell(0, 0)
        cell.width = Inches(self.fmt.content_w_in)
        accent = self._next_accent(tone)
        self._fill(cell, self.p.tint(accent))
        self._accent_edge(cell, accent)
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(text))
        run.font.name = self.fmt.font
        run.font.size = Pt(self.fmt.scale["body"].size)
        run.font.color.rgb = _rgb(self.p.text)
        table.columns[0].width = Inches(self.fmt.content_w_in)
        self._gap()
        return self

    def quote(self, text: str, attribution: str = "") -> "Doc":
        table = self._plain_table(1, 1)
        cell = table.cell(0, 0)
        cell.width = Inches(self.fmt.content_w_in)
        self._accent_edge(cell, self.p.accent)
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(text))
        run.font.name, run.font.italic = self.fmt.font, True
        run.font.size = Pt(self.fmt.scale["h3"].size)
        run.font.color.rgb = _rgb(self.p.text)
        if attribution:
            para = cell.add_paragraph()
            arun = para.add_run(f"— {attribution}")
            arun.font.name = self.fmt.font
            arun.font.size = Pt(self.fmt.scale["caption"].size)
            arun.font.color.rgb = _rgb(self.p.muted)
        table.columns[0].width = Inches(self.fmt.content_w_in)
        self._gap()
        return self

    def timeline(self, items: Sequence) -> "Doc":
        """Phased milestones, the marker in its own column against a ruled content edge."""
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

        marker = 1.1
        table = self._plain_table(len(rows), 2)
        for index, (label, head, body) in enumerate(rows):
            # Each phase its own colour — label, edge and fill — as the deck's timeline does.
            # One accent down every phase hid where one phase ended and the next began.
            accent = self._next_accent("info")
            left, right = table.cell(index, 0), table.cell(index, 1)
            left.width, right.width = Inches(marker), Inches(self.fmt.content_w_in - marker)
            left.text = ""
            run = left.paragraphs[0].add_run(label)
            run.font.name, run.font.bold = self.fmt.font, True
            run.font.size = Pt(self.fmt.scale["caption"].size)
            run.font.color.rgb = _rgb(self.p.ink(accent))
            self._fill(right, self.p.tint(accent))
            self._accent_edge(right, accent, width_eighths=16)
            self._block_text(right, head, body, head_role="body", head_color=self.p.text)
        table.columns[0].width = Inches(marker)
        table.columns[1].width = Inches(self.fmt.content_w_in - marker)
        self._gap()
        return self

    def steps(self, items: Sequence[str]) -> "Doc":
        """A numbered process. Word's own list numbering restarts unpredictably across
        sections, so the number is placed rather than generated."""
        items = [str(i) for i in items if i]
        if not items:
            return self
        gutter = 0.34
        for index, text in enumerate(items, start=1):
            para = self.doc.add_paragraph(style=_ROLE_STYLE["body"])
            fmt = para.paragraph_format
            fmt.left_indent = Inches(gutter)
            fmt.first_line_indent = Inches(-gutter)
            fmt.tab_stops.add_tab_stop(Inches(gutter))
            fmt.keep_together = True
            run = para.add_run(f"{index}.\t")
            run.bold = True
            # The number takes the step's own colour, matching the deck's steps.
            run.font.color.rgb = _rgb(self.p.ink(self._next_accent("info")))
            para.add_run(text)
            for r in para.runs:
                r.font.name = self.fmt.font
                if r.font.size is None:
                    r.font.size = Pt(self.fmt.scale["body"].size)
        return self

    def fields(self, pairs: Sequence[Sequence[str]], columns: int = 2) -> "Doc":
        """Label/value metadata — the block a report opens with."""
        pairs = [p for p in pairs if p]
        if not pairs:
            return self
        columns = max(1, min(int(columns), len(pairs)))
        rows = (len(pairs) + columns - 1) // columns
        table = self._plain_table(rows * 2, columns)
        width = self.fmt.content_w_in / columns
        for index, (label, value) in enumerate(pairs):
            r, c = divmod(index, columns)
            lab, val = table.cell(r * 2, c), table.cell(r * 2 + 1, c)
            lab.width = val.width = Inches(width)
            lab.text = ""
            lrun = lab.paragraphs[0].add_run(str(label).upper())
            lrun.font.name = self.fmt.font
            lrun.font.size = Pt(self.fmt.scale["caption"].size)
            lrun.font.color.rgb = _rgb(self.p.muted)
            val.text = ""
            vrun = val.paragraphs[0].add_run(str(value))
            vrun.font.name, vrun.font.bold = self.fmt.font, True
            vrun.font.size = Pt(self.fmt.scale["body"].size)
            vrun.font.color.rgb = _rgb(self.p.text)
        for c in range(columns):
            table.columns[c].width = Inches(width)
        self._gap()
        return self

    def divider(self) -> "Doc":
        from docx.oxml import OxmlElement

        para = self.doc.add_paragraph()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:color"), self.p.rule.lstrip("#"))
        borders.append(bottom)
        para._p.get_or_add_pPr().append(borders)
        return self

    def table(self, headers: Sequence[str], rows: Sequence[Sequence],
              widths: Optional[Sequence[float]] = None) -> "Doc":
        headers = [str(h) for h in headers]
        rows = [[("" if c is None else str(c)) for c in r] for r in rows]
        widths = list(widths) if widths else self._widths(headers, rows)

        table = self.doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.autofit = False
        tk = self.fmt.table

        for c, (cell, text) in enumerate(zip(table.rows[0].cells, headers)):
            self._cell(cell, text, bold=True, fill=self.p.primary,
                       color=self.p.on(self.p.primary), width=widths[c])
        self._repeat_header(table.rows[0])

        for i, row in enumerate(rows):
            cells = table.add_row().cells
            band = self.p.surface_alt if (tk.band_rows and i % 2 == 0) else None
            for c, cell in enumerate(cells):
                self._cell(cell, row[c] if c < len(row) else "", fill=band,
                           width=widths[c])
            self._no_split(table.rows[-1])

        # python-docx needs the width on the column objects too or Word recomputes them.
        for c, w in enumerate(widths):
            table.columns[c].width = Inches(w)
        self._gap()
        return self

    def _cell(self, cell, text, *, bold=False, fill=None, color=None, width=None):
        tk = self.fmt.table
        if width:
            cell.width = Inches(width)
        cell.text = ""
        para = cell.paragraphs[0]
        para.paragraph_format.space_before = Pt(tk.row_pad_v)
        para.paragraph_format.space_after = Pt(tk.row_pad_v)
        run = para.add_run(str(text))
        run.font.name = self.fmt.font
        run.font.size = Pt(tk.header_size if bold else tk.cell_size)
        run.font.bold = bold
        run.font.color.rgb = _rgb(color or self.p.text)
        if fill:
            shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), fill.lstrip("#").upper())
            cell._tc.get_or_add_tcPr().append(shd)

    def _repeat_header(self, row) -> None:
        pr = row._tr.get_or_add_trPr()
        pr.append(pr.makeelement(qn("w:tblHeader"), {}))

    def _no_split(self, row) -> None:
        pr = row._tr.get_or_add_trPr()
        pr.append(pr.makeelement(qn("w:cantSplit"), {}))

    def _widths(self, headers, rows):
        want = []
        for i, h in enumerate(headers):
            longest = max([len(h)] + [len(r[i]) for r in rows if i < len(r)])
            want.append(max(self.fmt.table.min_col_in,
                            min(longest * 0.085 + 0.2, 3.0)))
        scale = self.fmt.content_w_in / sum(want)
        return [w * scale for w in want]

    def page_break(self) -> "Doc":
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        return self

    def save(self) -> Path:
        if not self.doc.paragraphs and not self.doc.tables:
            raise ValueError("nothing was added to the document")
        self.doc.save(str(self.path))
        return self.path
