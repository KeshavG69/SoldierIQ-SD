"""
Text matching helpers for grounding checks
Used to verify that LLM-quoted evidence actually appears in source documents
"""

import re

# Quotes shorter than this must match exactly; longer ones are matched by word shingles
SHINGLE_SIZE = 3
SHINGLE_MATCH_THRESHOLD = 0.7


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace for fuzzy quote matching"""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def quote_in_text(quote: str, normalized_text: str) -> bool:
    """Check that a quote appears (near-)verbatim in already-normalized source text"""
    normalized_quote = normalize_text(quote)
    if not normalized_quote:
        return False
    if normalized_quote in normalized_text:
        return True

    words = normalized_quote.split()
    if len(words) < SHINGLE_SIZE:
        return False
    shingles = [" ".join(words[i:i + SHINGLE_SIZE]) for i in range(len(words) - SHINGLE_SIZE + 1)]
    found = sum(1 for s in shingles if s in normalized_text)
    return found / len(shingles) >= SHINGLE_MATCH_THRESHOLD
