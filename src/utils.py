"""Shared helpers: Rich console, filesystem utilities, and slug handling."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from rich.console import Console
from slugify import slugify as _slugify

console = Console()

# Some site firewalls block User-Agents containing a "python-requests" token,
# so we identify with a plain bot string plus a contact URL.
USER_AGENT = "podcast-to-wordpress-seo/1.0 (+https://esglesialagarriga.cat)"

# Audio container extensions we are willing to preserve from an enclosure URL.
_AUDIO_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".m4b",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".flac",
    ".mp4",
    ".webm",
}
DEFAULT_AUDIO_EXTENSION = ".mp3"


def ensure_dir(path: Path | str) -> Path:
    """Create ``path`` (and parents) if needed and return it as a ``Path``."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def slugify(text: str) -> str:
    """Return a filename/URL-safe slug for ``text`` (ASCII, hyphenated)."""
    return _slugify(text or "", lowercase=True)


def _audio_extension(audio_url: str) -> str:
    """Return a safe audio extension parsed from ``audio_url``.

    Falls back to :data:`DEFAULT_AUDIO_EXTENSION` when no recognised audio
    extension can be detected.
    """
    path = urlsplit(audio_url or "").path
    suffix = Path(unquote(path)).suffix.lower()
    return suffix if suffix in _AUDIO_EXTENSIONS else DEFAULT_AUDIO_EXTENSION


def build_audio_filename(title: str, audio_url: str) -> str:
    """Build a safe audio filename from an episode ``title`` and enclosure URL.

    The stem is a slug of the title (falling back to ``episode`` when the
    title slugifies to an empty string) and the extension is preserved from
    the enclosure URL when recognised, defaulting to ``.mp3``.
    """
    stem = slugify(title) or "episode"
    return f"{stem}{_audio_extension(audio_url)}"


def extract_slug_from_url(url: str) -> str:
    """Extract the trailing path slug from a permalink ``url``.

    ``https://site/esdeveniment/my-post/`` -> ``my-post``. Returns an empty
    string when no slug can be derived.
    """
    path = urlsplit(url or "").path
    segments = [segment for segment in path.split("/") if segment]
    return unquote(segments[-1]) if segments else ""


def resolve_language(
    cli_language: str | None,
    feed_language: str | None,
    config_language: str | None,
) -> str:
    """Resolve the transcription language by priority.

    Priority order: CLI override, then the RSS feed ``<language>``, then the
    configured ``seo.language``. Only the primary subtag is kept
    (``ca-ES`` -> ``ca``). Defaults to ``en`` when nothing is provided.
    """
    for candidate in (cli_language, feed_language, config_language):
        if candidate and candidate.strip():
            return candidate.strip().split("-")[0].lower()
    return "en"


def resolve_model(cli_model: str | None, config_model: str | None) -> str:
    """Resolve the Whisper model by priority: CLI override, then config."""
    for candidate in (cli_model, config_model):
        if candidate and candidate.strip():
            return candidate.strip()
    raise ValueError("No Whisper model configured (set whisper.model or pass --model).")
