"""Read a finished document back and refuse the ones that are visibly wrong.

Before this, every check lived as a markdown snippet the model could retype, skip, or ignore:
the pptx alignment checker exempted any shape whose name contained "rectangle", which is every
card, tile and badge python-pptx auto-names; the PDF linter sat in a reference file gated
behind "load before generating an image", so a text report never loaded it. Nothing measured
white space at all.

Two passes. The native pass reads the file's own structure and is cheap enough to always run.
The rendered pass converts to PDF once and measures glyph geometry, which is the only way to
see text that overflows its box or a page that is mostly empty.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgen import tokens as T
from docgen.palette import DEFAULT, Palette

logger = logging.getLogger(__name__)

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    code: str
    where: str
    detail: str
    fix: str
    level: str = ERROR

    def __str__(self) -> str:
        return f"[{self.code}] {self.where}: {self.detail} — {self.fix}"

    def as_dict(self) -> Dict[str, str]:
        return {"code": self.code, "where": self.where, "detail": self.detail,
                "fix": self.fix, "level": self.level}


@dataclass
class Report:
    path: str
    fmt: str
    issues: List[Issue] = field(default_factory=list)
    checked: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, *issues: Issue) -> None:
        self.issues.extend(i for i in issues if i is not None)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "format": self.fmt,
            "errors": [i.as_dict() for i in self.errors],
            "warnings": [i.as_dict() for i in self.warnings],
            "checked": self.checked,
            "skipped": self.skipped,
        }

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return f"{Path(self.path).name}: passed {len(self.checked)} checks"
        parts = [f"{Path(self.path).name}:"]
        for i in self.errors:
            parts.append(f"  FAIL {i}")
        for i in self.warnings:
            parts.append(f"  warn {i}")
        return "\n".join(parts)


def run(path, fmt: Optional[T.Format] = None, palette: Optional[Palette] = None) -> Report:
    src = Path(path)
    fmt = fmt or T.for_path(src)
    palette = palette or DEFAULT
    report = Report(path=str(src), fmt=fmt.name)

    if not src.exists():
        report.add(Issue("file.missing", str(src), "no such file",
                         "check the path returned by python_repl_tool as working_dir"))
        return report
    if src.stat().st_size == 0:
        report.add(Issue("file.empty", src.name, "the file is 0 bytes",
                         "the build wrote nothing — check for an exception before save()"))
        return report

    _native(src, fmt, palette, report)
    _rendered(src, fmt, report)
    return report


def _native(src: Path, fmt: T.Format, palette: Palette, report: Report) -> None:
    try:
        if fmt.name == "pptx":
            from docgen.checks.native_pptx import check
        elif fmt.name == "docx":
            from docgen.checks.native_docx import check
        elif fmt.name == "xlsx":
            from docgen.checks.native_xlsx import check
        else:
            return
    except ImportError as exc:
        report.skipped.append(f"native:{fmt.name} ({exc})")
        return
    try:
        check(src, fmt, palette, report)
    except Exception as exc:
        # A file the format's own library cannot open is not a layout problem, it is a
        # corrupt document — found by replaying production scripts: a workbook whose zip had
        # no [Content_Types].xml. Letting this escape means the gate swallows it and ships
        # the file, which is the one outcome nobody wants.
        report.add(Issue(
            "file.unreadable", src.name,
            f"{fmt.name} could not be opened: {type(exc).__name__}: {exc}"[:200],
            "the file is corrupt or truncated — rebuild it and check the save() completed"))
        return
    report.checked.append(f"native:{fmt.name}")


def _rendered(src: Path, fmt: T.Format, report: Report) -> None:
    if fmt.name == "xlsx":
        return  # a workbook has no page geometry until someone prints it
    try:
        from docgen.checks import pdflint
    except ImportError as exc:
        report.skipped.append(f"rendered ({exc})")
        return

    if fmt.name == "pdf":
        try:
            pdflint.check(src, fmt, report)
        except Exception as exc:
            report.add(Issue(
                "file.unreadable", src.name,
                f"the pdf could not be read: {type(exc).__name__}: {exc}"[:200],
                "the file is corrupt or truncated — rebuild it and check build() completed"))
            return
        report.checked.append("rendered:pdf")
        return

    from docgen import soffice

    if not soffice.available():
        report.skipped.append("rendered (soffice not installed)")
        return
    try:
        pdf = soffice.to_pdf(src)
    except Exception as exc:
        report.skipped.append(f"rendered (conversion failed: {exc})")
        return
    try:
        pdflint.check(pdf, fmt, report, origin=src.name)
    except Exception as exc:
        report.skipped.append(f"rendered ({type(exc).__name__}: {exc})")
        return
    report.checked.append(f"rendered:{fmt.name}")
