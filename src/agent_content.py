"""Agent-authored WordPress content handoff.

The deterministic SEO generator only produces a scaffold and an LLM-ready
prompt; it is not meant to write the final published prose. To keep a human or
an AI agent in the loop, the publish step reads the final title, excerpt, and
Gutenberg body from a handoff file:

    output/posts/<slug>.wordpress.md

The file uses YAML front matter for ``title`` and ``excerpt`` followed by the
WordPress body (Gutenberg blocks). While the file still contains the TODO
marker it is considered incomplete and is ignored by the publish step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# While this marker is present the handoff file is treated as not yet authored.
AGENT_TODO_MARKER = "<!-- podcast-seo:todo -->"


@dataclass
class AgentPost:
    """Final, agent-authored content for a WordPress post."""

    title: str | None
    excerpt: str | None
    body: str


def post_path(posts_dir: Path | str, slug: str) -> Path:
    """Return the handoff file path for ``slug`` under ``posts_dir``."""
    return Path(posts_dir) / f"{slug}.wordpress.md"


def _split_front_matter(text: str) -> tuple[dict, str]:
    """Split ``text`` into (front_matter_dict, body)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            if isinstance(meta, dict):
                return meta, parts[2]
    return {}, text


def load_agent_post(path: Path | str) -> AgentPost | None:
    """Load an agent-authored post, or ``None`` when missing or incomplete.

    Returns ``None`` when the file does not exist, still contains the TODO
    marker, or has an empty body — so callers can tell "not ready yet" from
    "ready to publish".
    """
    path = Path(path)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if AGENT_TODO_MARKER in text:
        return None
    front, body = _split_front_matter(text)
    body = body.strip()
    if not body:
        return None
    return AgentPost(
        title=(str(front["title"]).strip() if front.get("title") else None),
        excerpt=(str(front["excerpt"]).strip() if front.get("excerpt") else None),
        body=body,
    )


def write_template(
    path: Path | str,
    *,
    title: str,
    reference_path: Path | str,
) -> Path:
    """Write a fill-in handoff template for the agent to complete."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    template = f"""---
title: "{title}"
excerpt: ""
---
{AGENT_TODO_MARKER}
<!--
  AGENT / HUMAN: escriu el contingut final d'aquest post.
    1. Front matter (a dalt): títol SEO i un extracte breu de 2-3 frases.
    2. Cos (aquí sota): el post en blocs Gutenberg, per exemple:
         <!-- wp:heading --><h2>Títol</h2><!-- /wp:heading -->
         <!-- wp:paragraph --><p>Text...</p><!-- /wp:paragraph -->
  Referència (esborrany + prompt complet): {reference_path}
  Quan acabis, ESBORRA la línia {AGENT_TODO_MARKER} i torna a executar per publicar.
-->
"""
    path.write_text(template, encoding="utf-8")
    return path
