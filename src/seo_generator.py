"""Generate SEO-optimized WordPress content from a transcript and metadata.

The first implementation is deterministic: it derives a WordPress-ready draft
from the transcript and episode metadata (without calling any external AI
service) and also renders the LLM-ready prompt so a human or a future model can
refine the final prose. It never invents facts that are absent from the
transcript or metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from config import AppConfig
from feed_reader import PodcastEpisode, PodcastFeed
from utils import console, ensure_dir, slugify

_PLACEHOLDER_RE = re.compile(r"{{\s*(\w+)\s*}}")

DEFAULT_PROMPT_PATH = Path("prompts/seo_post_prompt.md")

_EMBEDDED_PROMPT = (
    "You are an SEO writer specialized in evangelical Christian content for a "
    "Catalan church website.\n\nCreate a WordPress post draft from this podcast "
    "episode.\n\nPodcast: {{ podcast_title }}\nSite: {{ site_name }}\nEpisode "
    "title: {{ episode_title }}\nDate: {{ pub_date }}\nSpeaker: {{ author }}\n"
    "Language: {{ language }}\nDuration: {{ duration }}\nOriginal description: "
    "{{ description }}\nOriginal episode link: {{ link }}\nWordPress post URL "
    "from RSS guid: {{ guid }}\nAudio URL: {{ audio_url }}\n\nTranscript:\n"
    "{{ transcript }}\n"
)


# Localized static labels and phrases. Catalan is used when the feed language
# is ``ca``; every other language falls back to English.
_STRINGS: dict[str, dict[str, str]] = {
    "ca": {
        "summary_heading": "Resum",
        "keypoints_heading": "Idees principals",
        "questions_heading": "Preguntes per a la reflexió",
        "listen_heading": "Escolta el missatge complet",
        "listen_intro": "Pots escoltar el missatge complet a l'àudio del podcast:",
        "cta": (
            "T'animem a escoltar el missatge complet i a visitar Església la "
            "Garriga per continuar creixent en la fe."
        ),
        "auto_note": (
            "Aquest esborrany s'ha generat automàticament a partir de la "
            "transcripció de l'àudio i està pensat per ser revisat abans de "
            "publicar-lo."
        ),
        "questions": [
            "Què creus que Déu et vol dir a través d'aquest missatge?",
            "Com pots aplicar aquesta paraula a la teva vida aquesta setmana?",
            "Amb qui podries compartir el que has après avui?",
        ],
        "no_transcript": "No hi ha transcripció disponible per a aquest episodi.",
    },
    "en": {
        "summary_heading": "Summary",
        "keypoints_heading": "Key points",
        "questions_heading": "Reflection questions",
        "listen_heading": "Listen to the full message",
        "listen_intro": "You can listen to the full message in the podcast audio:",
        "cta": (
            "We encourage you to listen to the full message and to visit "
            "Església la Garriga to keep growing in faith."
        ),
        "auto_note": (
            "This draft was generated automatically from the audio transcript "
            "and is meant to be reviewed before publishing."
        ),
        "questions": [
            "What do you think God is saying to you through this message?",
            "How can you apply this word to your life this week?",
            "Who could you share what you learned today with?",
        ],
        "no_transcript": "No transcript is available for this episode.",
    },
}


@dataclass
class SeoContent:
    """The generated SEO artefacts for an episode."""

    slug: str
    seo_title: str
    meta_description: str
    excerpt: str
    summary: str
    key_points: list[str]
    reflection_questions: list[str]
    categories: list[str]
    tags: list[str]
    call_to_action: str
    wordpress_html: str
    markdown_path: Path
    prompt: str


def _labels(language: str) -> dict:
    return _STRINGS.get((language or "").lower(), _STRINGS["en"])


def _strip_html(text: str) -> str:
    """Return ``text`` with HTML tags removed and whitespace collapsed."""
    if not text:
        return ""
    cleaned = BeautifulSoup(text, "html.parser").get_text(" ")
    return " ".join(cleaned.split())


def _truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` characters on a word boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:.- ")
    return f"{cut}…"


def _sentences(text: str, *, min_length: int = 20) -> list[str]:
    """Split ``text`` into trimmed sentences longer than ``min_length``."""
    normalized = " ".join((text or "").split())
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [part.strip() for part in parts if len(part.strip()) >= min_length]


def render_prompt(template_text: str, context: dict[str, object]) -> str:
    """Fill ``{{ key }}`` placeholders in ``template_text`` from ``context``."""

    def _replace(match: re.Match[str]) -> str:
        return str(context.get(match.group(1), "") or "")

    return _PLACEHOLDER_RE.sub(_replace, template_text)


def _load_prompt_template(prompt_path: Path) -> str:
    """Load the prompt template from disk, falling back to the embedded copy."""
    try:
        return Path(prompt_path).read_text(encoding="utf-8")
    except OSError:
        console.print(
            f"[yellow]Prompt template not found at {prompt_path}; using the "
            f"built-in template.[/yellow]"
        )
        return _EMBEDDED_PROMPT


def _build_context(
    feed: PodcastFeed,
    episode: PodcastEpisode,
    transcript: str,
    config: AppConfig,
    language: str,
) -> dict[str, object]:
    return {
        "podcast_title": feed.title,
        "site_name": config.seo.site_name,
        "episode_title": episode.title,
        "pub_date": episode.pub_date,
        "author": episode.author or config.seo.default_author,
        "language": language,
        "duration": episode.duration or "",
        "description": _strip_html(episode.description),
        "link": episode.link,
        "guid": episode.guid,
        "audio_url": episode.audio_url,
        "transcript": transcript,
    }


def _extract_key_points(sentences: list[str], *, count: int = 7) -> list[str]:
    """Extract ``count`` key-point sentences distributed across the full text.

    Filters out very short sentences (typically interjections, rhetorical
    questions, or transitional phrases) and samples evenly so that the result
    represents the whole message rather than just its introduction.
    """
    # Keep only sentences long enough to express a complete thought.
    substantive = [s for s in sentences if len(s) >= 45]
    if not substantive:
        # Fallback: relax the length threshold.
        substantive = [s for s in sentences if len(s) >= 25]
    if not substantive:
        return sentences[:count]

    if len(substantive) <= count:
        return substantive

    # Even-interval sampling across the full list.
    step = len(substantive) / count
    return [substantive[int(i * step)] for i in range(count)]


def _suggested_tags(feed: PodcastFeed, episode: PodcastEpisode) -> list[str]:
    """Derive suggested tags from the episode/podcast metadata."""
    tags: list[str] = []
    if episode.author:
        tags.append(episode.author)
    if feed.title:
        tags.append(feed.title)
    for word in re.findall(r"\w{5,}", episode.title):
        candidate = word.lower()
        if candidate not in {t.lower() for t in tags}:
            tags.append(candidate)
        if len(tags) >= 8:
            break
    return tags[:8]


def _wp_heading(text: str, level: int = 2) -> str:
    """Return a Gutenberg heading block."""
    attrs = f' {{"level":{level}}}' if level != 2 else ""
    return f"<!-- wp:heading{attrs} -->\n<h{level}>{text}</h{level}>\n<!-- /wp:heading -->"


def _wp_paragraph(html: str) -> str:
    """Return a Gutenberg paragraph block."""
    return f"<!-- wp:paragraph -->\n<p>{html}</p>\n<!-- /wp:paragraph -->"


def _wp_list(items: list[str]) -> str:
    """Return a Gutenberg list block with nested list-item blocks."""
    parts = ['<!-- wp:list -->', '<ul class="wp-block-list">']
    for item in items:
        parts.append(f"<!-- wp:list-item -->\n<li>{item}</li>\n<!-- /wp:list-item -->")
    parts.append("</ul>\n<!-- /wp:list -->")
    return "\n".join(parts)


def _wordpress_html(
    labels: dict,
    summary: str,
    key_points: list[str],
    questions: list[str],
    episode: PodcastEpisode,
) -> str:
    """Compose the Gutenberg block markup inserted into the WordPress post."""
    blocks: list[str] = []
    if summary:
        blocks.append(_wp_heading(labels["summary_heading"]))
        blocks.append(_wp_paragraph(summary))
    if key_points:
        blocks.append(_wp_heading(labels["keypoints_heading"]))
        blocks.append(_wp_list(key_points))
    if questions:
        blocks.append(_wp_heading(labels["questions_heading"]))
        blocks.append(_wp_list(questions))
    if episode.audio_url:
        blocks.append(_wp_heading(labels["listen_heading"]))
        blocks.append(_wp_paragraph(labels["listen_intro"]))
        blocks.append(
            _wp_paragraph(f'<a href="{episode.audio_url}">{episode.audio_url}</a>')
        )
    blocks.append(_wp_paragraph(f"<em>{labels['cta']}</em>"))
    return "\n\n".join(blocks)


def _markdown_document(
    content: "SeoContent",
    feed: PodcastFeed,
    episode: PodcastEpisode,
    language: str,
    transcript_path: Path,
    prompt: str,
) -> str:
    """Render the full Markdown draft saved under ``output/posts/``."""
    metadata = [
        f"- Podcast: {feed.title}",
        f"- Episode: {episode.title}",
        f"- Date: {episode.pub_date or '—'}",
        f"- Speaker: {episode.author or '—'}",
        f"- Language: {language}",
        f"- Duration: {episode.duration or '—'}",
        f"- Episode link: {episode.link or '—'}",
        f"- WordPress GUID: {episode.guid or '—'}",
        f"- Audio URL: {episode.audio_url or '—'}",
    ]
    key_points_md = "\n".join(f"- {point}" for point in content.key_points) or "- —"
    questions_md = (
        "\n".join(f"- {question}" for question in content.reflection_questions) or "- —"
    )
    categories_md = ", ".join(content.categories) or "—"
    tags_md = ", ".join(content.tags) or "—"

    return f"""# {content.seo_title}

## Recommended slug

{content.slug}

## Meta description

{content.meta_description}

## Short WordPress excerpt

{content.excerpt}

## Summary

{content.summary}

## Main WordPress article

{content.wordpress_html}

## Key points

{key_points_md}

## Reflection questions

{questions_md}

## Suggested WordPress categories

{categories_md}

## Suggested WordPress tags

{tags_md}

## Final call to action

{content.call_to_action}

## Source episode metadata

{chr(10).join(metadata)}

## Transcript reference

{transcript_path}

## Full LLM prompt used

```
{prompt}
```
"""


def generate_seo_content(
    feed: PodcastFeed,
    episode: PodcastEpisode,
    transcript_path: Path | str,
    config: AppConfig,
    *,
    language: str,
    prompt_path: Path | str = DEFAULT_PROMPT_PATH,
    force: bool = False,
) -> SeoContent:
    """Generate SEO content for ``episode`` and write the Markdown draft.

    Returns a :class:`SeoContent` whose ``wordpress_html`` is the block to
    insert into WordPress and whose ``markdown_path`` points at the saved
    draft. The draft is reused unless ``force`` is ``True``.
    """
    transcript_path = Path(transcript_path)
    labels = _labels(language)
    slug = slugify(episode.title) or "episode"

    posts_dir = ensure_dir(config.output.posts_dir)
    markdown_path = posts_dir / f"{slug}-seo.md"

    transcript = ""
    if transcript_path.is_file():
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace").strip()

    prompt = render_prompt(
        _load_prompt_template(Path(prompt_path)),
        _build_context(feed, episode, transcript, config, language),
    )

    clean_description = _strip_html(episode.description)
    source_text = transcript or clean_description
    sentences = _sentences(source_text)

    # For summary/excerpt use the episode description when available (it is a
    # curated human-written text), falling back to sampled transcript sentences.
    if clean_description:
        summary = _truncate(clean_description, 700)
        excerpt = _truncate(clean_description, 220)
    else:
        core = _extract_key_points(sentences, count=4)
        summary = _truncate(" ".join(core), 700) if core else labels["no_transcript"]
        excerpt = _truncate(" ".join(core[:2]) or summary, 220)
    meta_description = _truncate(clean_description or summary, 158)
    key_points = _extract_key_points(sentences)
    questions = list(labels["questions"])

    seo_title = _truncate(episode.title, 60)
    categories = [config.seo.site_name, feed.title]
    tags = _suggested_tags(feed, episode)
    call_to_action = labels["cta"]

    wordpress_html = _wordpress_html(labels, summary, key_points, questions, episode)

    content = SeoContent(
        slug=slug,
        seo_title=seo_title,
        meta_description=meta_description,
        excerpt=excerpt,
        summary=summary,
        key_points=key_points,
        reflection_questions=questions,
        categories=categories,
        tags=tags,
        call_to_action=call_to_action,
        wordpress_html=wordpress_html,
        markdown_path=markdown_path,
        prompt=prompt,
    )

    if markdown_path.exists() and not force:
        console.print(f"[green]SEO draft already exists:[/green] {markdown_path}")
        return content

    document = _markdown_document(
        content, feed, episode, language, transcript_path, prompt
    )
    markdown_path.write_text(document, encoding="utf-8")
    console.print(f"[green]SEO draft saved to:[/green] {markdown_path}")
    return content
