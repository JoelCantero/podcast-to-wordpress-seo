"""Unit tests for slugging, filename, language, and section-update helpers.

Run with ``python -m pytest -q`` from the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the flat modules under ``src/`` importable without a package install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils import (  # noqa: E402
    build_audio_filename,
    extract_slug_from_url,
    resolve_language,
    resolve_model,
    slugify,
)
from wordpress_formatter import (  # noqa: E402
    SECTION_END,
    SECTION_START,
    apply_update,
    wrap_section,
)
from seo_generator import _extract_key_points  # noqa: E402
from agent_content import (  # noqa: E402
    AGENT_TODO_MARKER,
    load_agent_post,
    post_path,
    write_template,
)


# -- slugify -------------------------------------------------------------

def test_slugify_transliterates_catalan_accents():
    assert slugify("Només cal fe per ser salvats?") == "nomes-cal-fe-per-ser-salvats"


def test_slugify_collapses_punctuation_and_spaces():
    assert slugify("  Hola,  Món!! ") == "hola-mon"


def test_slugify_empty_string():
    assert slugify("") == ""


# -- GUID URL slug extraction -------------------------------------------

def test_extract_slug_with_trailing_slash():
    url = "https://esglesialagarriga.cat/esdeveniment/nomes-cal-fe-per-ser-salvats/"
    assert extract_slug_from_url(url) == "nomes-cal-fe-per-ser-salvats"


def test_extract_slug_without_trailing_slash():
    url = "https://esglesialagarriga.cat/esdeveniment/nomes-cal-fe-per-ser-salvats"
    assert extract_slug_from_url(url) == "nomes-cal-fe-per-ser-salvats"


def test_extract_slug_ignores_query_and_fragment():
    url = "https://site.tld/blog/my-post/?utm=1#top"
    assert extract_slug_from_url(url) == "my-post"


def test_extract_slug_empty_url():
    assert extract_slug_from_url("") == ""


# -- audio filename generation ------------------------------------------

def test_build_audio_filename_preserves_known_extension():
    name = build_audio_filename("Només cal fe per ser salvats?", "https://x/a.mp3")
    assert name == "nomes-cal-fe-per-ser-salvats.mp3"


def test_build_audio_filename_preserves_m4a():
    assert build_audio_filename("Hello World", "https://cdn.tld/ep.m4a") == "hello-world.m4a"


def test_build_audio_filename_defaults_to_mp3():
    assert build_audio_filename("Hello", "https://cdn.tld/stream?id=1") == "hello.mp3"


def test_build_audio_filename_empty_title_falls_back():
    assert build_audio_filename("", "https://cdn.tld/a.mp3") == "episode.mp3"


# -- language / model fallback priority ---------------------------------

def test_language_prefers_cli_override():
    assert resolve_language("en", "ca", "fr") == "en"


def test_language_falls_back_to_feed_and_strips_region():
    assert resolve_language(None, "ca-ES", "en") == "ca"


def test_language_falls_back_to_config():
    assert resolve_language(None, "", "ca") == "ca"


def test_language_default_when_all_missing():
    assert resolve_language(None, None, None) == "en"


def test_model_prefers_cli_then_config():
    assert resolve_model("cli-model", "config-model") == "cli-model"
    assert resolve_model(None, "config-model") == "config-model"


# -- section replacement between markers --------------------------------

def test_section_inserts_when_markers_absent():
    result = apply_update("<p>Existing</p>", "<p>New</p>", "section")
    assert SECTION_START in result and SECTION_END in result
    assert "<p>Existing</p>" in result
    assert "<p>New</p>" in result


def test_section_replaces_only_between_markers():
    first = apply_update("<p>Intro</p>", "<p>One</p>", "section")
    second = apply_update(first, "<p>Two</p>", "section")
    assert second.count(SECTION_START) == 1
    assert second.count(SECTION_END) == 1
    assert "<p>Intro</p>" in second
    assert "<p>Two</p>" in second
    assert "<p>One</p>" not in second


def test_section_on_empty_content():
    assert apply_update("", "<p>New</p>", "section") == wrap_section("<p>New</p>")


def test_append_mode_keeps_existing():
    assert apply_update("<p>A</p>", "<p>B</p>", "append") == "<p>A</p>\n\n<p>B</p>"


def test_append_mode_on_empty_content():
    assert apply_update("", "<p>B</p>", "append") == "<p>B</p>"


def test_replace_mode_discards_existing():
    assert apply_update("<p>A</p>", "<p>B</p>", "replace") == "<p>B</p>"


# -- key points extraction -----------------------------------------------

_SHORT = ["Sí.", "No.", "Bé."]
_INTRO_HEAVY = [
    "Introducció curta.",  # < 45 chars → filtered
    "Però una pregunta sobre el tema inicial.",  # < 45 chars → borderline
    "Aquí comença el missatge sobre la salvació per gràcia i la fe en Crist.",
    "Pau explica que els Gàlates han rebut l'Esperit per l'escolta de la fe.",
    "L'exemple d'Abram estableix el patró de tota la Bíblia sobre la justificació.",
    "La llei no pot salvar ningú perquè ningú la compleix del tot i perfectament.",
    "Jesús va morir la mort que ens tocava a nosaltres per pagar el nostre deute.",
    "Per la fe es produeix el gran intercanvi: la seva justícia passa a compte meu.",
    "L'Esperit de Déu dóna la certesa que som fills de Déu i mai estarem sols.",
]


def test_extract_key_points_samples_across_full_list():
    points = _extract_key_points(_INTRO_HEAVY, count=4)
    assert len(points) == 4
    # First and last items should come from different parts of the list.
    assert points[0] != points[-1]


def test_extract_key_points_filters_short_sentences():
    points = _extract_key_points(_SHORT + _INTRO_HEAVY, count=4)
    # None of the returned points should be one of the short stubs.
    for point in points:
        assert point not in _SHORT


def test_extract_key_points_returns_all_when_fewer_than_count():
    few = [s for s in _INTRO_HEAVY if len(s) >= 45]
    points = _extract_key_points(few[:3], count=7)
    assert len(points) == 3


def test_extract_key_points_fallback_on_all_short():
    all_short = ["Sí.", "No.", "Bé.", "Déu.", "Fe."]
    points = _extract_key_points(all_short, count=3)
    assert len(points) <= 3


# -- agent-authored content handoff --------------------------------------

def test_post_path_uses_slug(tmp_path):
    assert post_path(tmp_path, "my-slug").name == "my-slug.wordpress.md"


def test_load_agent_post_missing_file_returns_none(tmp_path):
    assert load_agent_post(tmp_path / "absent.wordpress.md") is None


def test_load_agent_post_template_not_ready_returns_none(tmp_path):
    path = post_path(tmp_path, "ep")
    write_template(path, title="Episodi", reference_path="output/posts/ep-seo.md")
    # Freshly written template still holds the TODO marker → not ready.
    assert AGENT_TODO_MARKER in path.read_text(encoding="utf-8")
    assert load_agent_post(path) is None


def test_load_agent_post_parses_front_matter_and_body(tmp_path):
    path = post_path(tmp_path, "ep")
    path.write_text(
        '---\n'
        'title: "El gran intercanvi"\n'
        'excerpt: "Un resum breu del missatge."\n'
        '---\n'
        '<!-- wp:paragraph -->\n<p>Cos del post.</p>\n<!-- /wp:paragraph -->\n',
        encoding="utf-8",
    )
    post = load_agent_post(path)
    assert post is not None
    assert post.title == "El gran intercanvi"
    assert post.excerpt == "Un resum breu del missatge."
    assert "wp:paragraph" in post.body


def test_load_agent_post_empty_body_returns_none(tmp_path):
    path = post_path(tmp_path, "ep")
    path.write_text('---\ntitle: "X"\nexcerpt: "Y"\n---\n\n', encoding="utf-8")
    assert load_agent_post(path) is None
