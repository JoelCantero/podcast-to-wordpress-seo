"""Resolve and update WordPress posts through the REST API.

The custom post type used by the site (e.g. ``esdeveniment``) may be served
under a different REST base (e.g. ``cultes``). We therefore resolve the real
``rest_base`` generically via ``/wp-json/wp/v2/types/<post_type>`` and fall
back to the configured type and finally to standard ``posts``.

Authentication uses WordPress Application Passwords via HTTP Basic Auth. The
application password is never logged or printed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from config import WordPressCredentials
from utils import USER_AGENT


class WordPressError(Exception):
    """Raised for any WordPress REST API failure."""


@dataclass
class WordPressPost:
    """A resolved WordPress post targeted for update."""

    id: int
    rest_base: str
    link: str
    title: str
    content: str
    rendered_content: str = ""


class WordPressClient:
    """Thin WordPress REST client for resolving and updating a single post."""

    def __init__(
        self,
        base_url: str,
        credentials: WordPressCredentials,
        *,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(
            credentials.username, credentials.application_password
        )
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "application/json"}
        )

    # -- low-level helpers -------------------------------------------------

    def _api(self, path: str) -> str:
        return f"{self.base_url}/wp-json/wp/v2/{path.lstrip('/')}"

    def _get(self, url: str, params: dict) -> requests.Response:
        try:
            return self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise WordPressError(f"Could not reach WordPress: {exc}") from exc

    def _post(self, url: str, payload: dict) -> requests.Response:
        try:
            return self.session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise WordPressError(f"Could not reach WordPress: {exc}") from exc

    def _check(self, response: requests.Response, *, context: str) -> None:
        """Raise a helpful :class:`WordPressError` for known failure codes."""
        if response.status_code == 401:
            raise WordPressError(
                "WordPress authentication failed (401). Check WORDPRESS_USERNAME "
                "and the application password."
            )
        if response.status_code == 403:
            raise WordPressError(
                f"WordPress denied permission (403) while {context}. The user may "
                f"lack rights to edit this post type."
            )
        if response.status_code == 404:
            raise WordPressError(f"WordPress resource not found (404) while {context}.")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise WordPressError(f"WordPress REST error while {context}: {exc}") from exc

    @staticmethod
    def _to_post(item: dict, rest_base: str) -> WordPressPost:
        content = item.get("content") or {}
        raw = content.get("raw")
        title = (item.get("title") or {}).get("rendered", "")
        return WordPressPost(
            id=int(item["id"]),
            rest_base=rest_base,
            link=item.get("link", ""),
            title=title,
            content=raw if raw is not None else "",
            rendered_content=content.get("rendered", ""),
        )

    # -- public API --------------------------------------------------------

    def resolve_rest_base(self, post_type: str) -> str:
        """Resolve the REST base for ``post_type`` (falls back to the type name)."""
        response = self._get(self._api(f"types/{post_type}"), params={})
        if response.status_code == 200:
            data = response.json()
            return data.get("rest_base") or data.get("slug") or post_type
        return post_type

    def _query_slug(self, rest_base: str, slug: str) -> Optional[list]:
        """Query one REST base for ``slug``.

        Returns the list of matching posts, or ``None`` when the REST base does
        not exist (so the caller can try the next candidate).
        """
        url = self._api(rest_base)
        response = self._get(
            url, params={"slug": slug, "context": "edit", "per_page": 5}
        )
        # Without edit rights the edit context may be rejected; retry as a
        # read-only lookup so we can still locate the post.
        if response.status_code in (400, 403):
            response = self._get(url, params={"slug": slug, "per_page": 5})
        if response.status_code == 404:
            return None
        self._check(response, context=f"searching '{rest_base}' for slug '{slug}'")
        data = response.json()
        return data if isinstance(data, list) else []

    def find_post_by_slug(self, slug: str, post_type: str) -> WordPressPost:
        """Find the single post matching ``slug`` for ``post_type``.

        Tries the resolved REST base, then the configured post type, then the
        standard ``posts`` endpoint. Raises :class:`WordPressError` when no post
        or more than one post is found.
        """
        if not slug:
            raise WordPressError("Cannot resolve a WordPress post without a slug.")

        resolved = self.resolve_rest_base(post_type)
        candidates: list[str] = []
        for base in (resolved, post_type, "posts"):
            if base and base not in candidates:
                candidates.append(base)

        for rest_base in candidates:
            posts = self._query_slug(rest_base, slug)
            if posts is None:
                continue
            if len(posts) == 1:
                return self._to_post(posts[0], rest_base)
            if len(posts) > 1:
                raise WordPressError(
                    f"Multiple posts ({len(posts)}) match slug '{slug}' under "
                    f"'{rest_base}'. Resolve the ambiguity manually."
                )

        raise WordPressError(
            f"No WordPress post found for slug '{slug}' "
            f"(tried: {', '.join(candidates)})."
        )

    def update_post(
        self,
        post: WordPressPost,
        content: str,
        *,
        excerpt: str | None = None,
    ) -> WordPressPost:
        """Update ``post`` content (and optionally its excerpt) via the REST API.

        Returns the fresh post. When ``excerpt`` is ``None`` or empty the
        excerpt field is left untouched.
        """
        payload: dict = {"content": content}
        if excerpt:
            payload["excerpt"] = excerpt
        url = self._api(f"{post.rest_base}/{post.id}")
        response = self._post(url, payload)
        self._check(response, context=f"updating post {post.id}")
        return self._to_post(response.json(), post.rest_base)
