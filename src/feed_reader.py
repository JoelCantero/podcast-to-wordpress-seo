"""Fetch and parse a podcast RSS feed into typed dataclasses.

feedparser's ``entry.guidislink`` is unreliable for detecting
``isPermaLink`` (it reports whether the guid is used as the link, and is
False whenever a separate ``<link>`` exists). We therefore read the raw
``<guid isPermaLink="...">`` attribute from the fetched XML. Per RSS 2.0 the
attribute defaults to ``true`` when absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import feedparser
import requests

from utils import USER_AGENT

_GUID_RE = re.compile(r"<guid\b([^>]*)>(.*?)</guid>", re.IGNORECASE | re.DOTALL)
_ISPERMALINK_RE = re.compile(r"""ispermalink\s*=\s*["']?\s*(true|false)""", re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)

_AUDIO_SUFFIXES = (
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
)


class FeedError(Exception):
    """Raised when the podcast feed cannot be fetched or parsed."""


@dataclass
class PodcastEpisode:
    """A single podcast episode extracted from the RSS feed."""

    title: str
    link: str
    guid: str
    guid_is_permalink: bool
    pub_date: str
    description: str
    audio_url: str
    audio_type: Optional[str]
    audio_length: Optional[int]
    author: Optional[str]
    duration: Optional[str]
    episode_number: Optional[int]
    season_number: Optional[int]

    @property
    def has_audio(self) -> bool:
        """Whether the episode has a downloadable audio enclosure."""
        return bool(self.audio_url)

    @property
    def permalink_url(self) -> Optional[str]:
        """The canonical WordPress URL from the guid, when it is a permalink."""
        if self.guid_is_permalink and self.guid.startswith("http"):
            return self.guid
        return None


@dataclass
class PodcastFeed:
    """Channel-level metadata plus the list of episodes."""

    title: str
    description: str
    link: str
    language: str
    episodes: list[PodcastEpisode]
    image: Optional[str] = None
    author: Optional[str] = None
    owner: Optional[str] = None


def _clean_guid(value: str) -> str:
    """Strip whitespace and CDATA wrappers from a raw guid value."""
    value = value.strip()
    match = _CDATA_RE.search(value)
    return match.group(1).strip() if match else value


def _guid_permalink_map(xml_text: str) -> dict[str, bool]:
    """Map each raw guid value to its ``isPermaLink`` boolean.

    RSS 2.0 default: ``isPermaLink`` is ``true`` when the attribute is absent.
    """
    mapping: dict[str, bool] = {}
    for attrs, raw_value in _GUID_RE.findall(xml_text):
        guid_value = _clean_guid(raw_value)
        if not guid_value:
            continue
        match = _ISPERMALINK_RE.search(attrs)
        mapping[guid_value] = True if match is None else match.group(1).lower() == "true"
    return mapping


def _as_int(value: object) -> Optional[int]:
    """Best-effort integer parse; returns ``None`` on failure."""
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.lstrip("-").isdigit() else None


def _looks_like_audio(href: str) -> bool:
    """Heuristically decide whether ``href`` points at an audio file."""
    path = href.split("?", 1)[0].lower()
    return path.endswith(_AUDIO_SUFFIXES)


def _extract_audio(entry) -> tuple[str, Optional[str], Optional[int]]:
    """Return ``(url, mime_type, length)`` for the episode's audio enclosure."""
    candidates: list[dict] = list(entry.get("enclosures", []) or [])
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure":
            candidates.append(link)

    # Prefer enclosures that clearly look like audio.
    for enclosure in candidates:
        href = enclosure.get("href") or enclosure.get("url")
        mime = enclosure.get("type")
        if href and ((mime and mime.startswith("audio")) or _looks_like_audio(href)):
            return href, mime, _as_int(enclosure.get("length"))

    # Fall back to the first enclosure with a usable URL.
    for enclosure in candidates:
        href = enclosure.get("href") or enclosure.get("url")
        if href:
            return href, enclosure.get("type"), _as_int(enclosure.get("length"))

    return "", None, None


def _build_episode(entry, permalink_map: dict[str, bool]) -> PodcastEpisode:
    """Construct a :class:`PodcastEpisode` from a feedparser entry."""
    guid = (entry.get("id") or entry.get("guid") or "").strip()
    audio_url, audio_type, audio_length = _extract_audio(entry)
    return PodcastEpisode(
        title=(entry.get("title") or "").strip() or "(untitled episode)",
        link=(entry.get("link") or "").strip(),
        guid=guid,
        guid_is_permalink=permalink_map.get(guid, False),
        pub_date=(entry.get("published") or entry.get("updated") or "").strip(),
        description=(entry.get("summary") or entry.get("description") or "").strip(),
        audio_url=audio_url,
        audio_type=audio_type,
        audio_length=audio_length,
        author=(entry.get("author") or entry.get("itunes_author") or None),
        duration=(entry.get("itunes_duration") or None),
        episode_number=_as_int(entry.get("itunes_episode")),
        season_number=_as_int(entry.get("itunes_season")),
    )


def read_feed(url: str, *, timeout: int = 30) -> PodcastFeed:
    """Fetch and parse the podcast RSS ``url`` into a :class:`PodcastFeed`."""
    if not url or not str(url).strip():
        raise FeedError("No podcast feed URL provided.")

    try:
        response = requests.get(
            url, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FeedError(f"Could not fetch feed '{url}': {exc}") from exc

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise FeedError(
            f"Feed '{url}' could not be parsed: {parsed.get('bozo_exception', 'unknown error')}"
        )

    permalink_map = _guid_permalink_map(response.text)
    channel = parsed.feed

    image = None
    if isinstance(channel.get("image"), dict):
        image = channel["image"].get("href") or channel["image"].get("url")
    image = image or channel.get("itunes_image") or None

    owner = None
    if isinstance(channel.get("publisher_detail"), dict):
        owner = channel["publisher_detail"].get("email")

    episodes = [_build_episode(entry, permalink_map) for entry in parsed.entries]
    if not episodes:
        raise FeedError(f"Feed '{url}' contains no episodes.")

    return PodcastFeed(
        title=(channel.get("title") or "").strip() or "(untitled podcast)",
        description=(channel.get("subtitle") or channel.get("description") or "").strip(),
        link=(channel.get("link") or "").strip(),
        language=(channel.get("language") or "").strip(),
        episodes=episodes,
        image=image,
        author=(channel.get("author") or channel.get("itunes_author") or None),
        owner=owner,
    )
