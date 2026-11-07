"""Register Inter once, and say so out loud when it is not there.

`register_inter()` in the pdf skill fell back to DejaVu silently — the skill even warned that
it does, and nothing checked. A document then rendered in the wrong face with no signal
anywhere. Registration now reports what it actually got, and the verifier checks the rendered
file independently, so a fallback is visible from both ends.
"""

import logging
import threading
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

INTER_DIR = Path("/usr/share/fonts/truetype/inter")
FACES = {
    "Inter": "Inter-Regular.ttf",
    "Inter-Bold": "Inter-Bold.ttf",
    "Inter-Italic": "Inter-Italic.ttf",
    "Inter-BoldItalic": "Inter-BoldItalic.ttf",
}
FALLBACK = ("Helvetica", "Helvetica-Bold")

_lock = threading.Lock()
_registered: Optional[Tuple[str, str]] = None


def available() -> bool:
    return all((INTER_DIR / f).exists() for f in FACES.values())


def register_pdf() -> Tuple[str, str]:
    """Returns the (regular, bold) names reportlab will actually draw with."""
    global _registered
    with _lock:
        if _registered is not None:
            return _registered
        if not available():
            missing = [f for f in FACES.values() if not (INTER_DIR / f).exists()]
            logger.warning(
                "docgen: Inter is not installed (%s missing from %s); falling back to %s. "
                "The rendered document will not match the design system.",
                missing, INTER_DIR, FALLBACK[0],
            )
            _registered = FALLBACK
            return _registered

        from reportlab.lib.fonts import addMapping
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for name, filename in FACES.items():
            pdfmetrics.registerFont(TTFont(name, str(INTER_DIR / filename)))
        addMapping("Inter", 0, 0, "Inter")
        addMapping("Inter", 1, 0, "Inter-Bold")
        addMapping("Inter", 0, 1, "Inter-Italic")
        addMapping("Inter", 1, 1, "Inter-BoldItalic")
        _registered = ("Inter", "Inter-Bold")
        return _registered
