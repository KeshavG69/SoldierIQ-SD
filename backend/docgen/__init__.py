"""Design tokens and helpers shared by every generated document.

Generated code imports from here instead of restating margins, type scales and colors, which
is how two documents of the same type end up identical. `verify()` reads the same tokens back
off a finished file, so the check and the builder cannot drift.
"""

from docgen import tokens
from docgen.palette import DEFAULT, Palette, active, clear_brand, resolve_palette, use_brand
from docgen.tokens import DOCX, PDF, PPTX, XLSX, Format, Type, for_path

__all__ = [
    "tokens", "Palette", "DEFAULT", "resolve_palette", "use_brand", "clear_brand", "active",
    "PPTX", "DOCX", "PDF", "XLSX", "Format", "Type", "for_path", "verify",
]


def verify(path, fmt=None, palette=None):
    """Lazy so importing tokens does not pull pdfplumber/python-pptx in."""
    from docgen.checks import run as _run

    return _run(path, fmt=fmt, palette=palette)
