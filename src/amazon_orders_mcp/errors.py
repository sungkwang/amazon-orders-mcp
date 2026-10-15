"""Errors the server reports to the caller, with enough context to act on them."""

from typing import Optional


class ParseStructureError(RuntimeError):
    """An Amazon page did not have the structure the parser expects.

    Raised instead of returning empty data, so a changed layout is visible.
    `url` and `snippet` say which page and what it contained (keep both
    free of personal details when logged).
    """

    def __init__(self, message: str, url: Optional[str] = None, snippet: Optional[str] = None):
        super().__init__(message)
        self.url = url
        self.snippet = snippet


def snippet_of(text: str, limit: int = 300) -> str:
    """A short, single-line excerpt of page text for error reports."""
    flat = " ".join(text.split())
    return flat[:limit]
