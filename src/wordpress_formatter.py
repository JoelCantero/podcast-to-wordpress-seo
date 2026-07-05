"""Merge generated SEO content into existing WordPress post content.

Three update modes are supported:

- ``replace``: replace the whole post content with the generated block.
- ``append``: append the generated block after the existing content.
- ``section`` (recommended default): insert or replace a block delimited by
  HTML comment markers so the operation is safe and repeatable.
"""

from __future__ import annotations

import re

SECTION_START = "<!-- podcast-seo:start -->"
SECTION_END = "<!-- podcast-seo:end -->"

_SECTION_RE = re.compile(
    re.escape(SECTION_START) + r".*?" + re.escape(SECTION_END),
    re.DOTALL,
)


def wrap_section(block: str) -> str:
    """Wrap ``block`` between the podcast-seo section markers."""
    return f"{SECTION_START}\n{block}\n{SECTION_END}"


def replace_section(existing: str, block: str) -> str:
    """Insert or replace the marked section within ``existing`` content.

    If the markers already exist, only the content between them is replaced.
    Otherwise the wrapped block is appended to the end of the content.
    """
    existing = existing or ""
    wrapped = wrap_section(block)
    if _SECTION_RE.search(existing):
        return _SECTION_RE.sub(lambda _match: wrapped, existing, count=1)
    if existing.strip():
        return f"{existing.rstrip()}\n\n{wrapped}"
    return wrapped


def apply_update(existing: str, block: str, mode: str) -> str:
    """Return the new post content for ``mode``.

    ``existing`` may be empty (some custom post types have no editor support);
    every mode handles that gracefully.
    """
    existing = existing or ""
    if mode == "replace":
        return block
    if mode == "append":
        if existing.strip():
            return f"{existing.rstrip()}\n\n{block}"
        return block
    # Default and recommended: idempotent marked section.
    return replace_section(existing, block)
