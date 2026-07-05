"""Configuration and credential loading for the podcast-to-WordPress CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when configuration or credentials are missing or invalid."""


@dataclass
class WhisperConfig:
    """MLX Whisper transcription settings."""

    conda_env: str
    model: str
    output_format: str = "txt"


@dataclass
class OutputConfig:
    """Local output directories for artefacts."""

    audio_dir: Path
    transcripts_dir: Path
    posts_dir: Path


@dataclass
class SeoConfig:
    """SEO generation settings."""

    site_name: str
    default_author: str
    tone: str
    language: str


@dataclass
class WordPressConfig:
    """WordPress REST API target settings."""

    base_url: str
    post_type: str
    update_mode: str = "section"
    confirm_before_update: bool = True


@dataclass
class AppConfig:
    """Top-level application configuration."""

    podcast_feed_url: str
    whisper: WhisperConfig
    output: OutputConfig
    seo: SeoConfig
    wordpress: WordPressConfig


@dataclass
class WordPressCredentials:
    """WordPress Application Password credentials (never logged)."""

    username: str
    application_password: str


ALLOWED_UPDATE_MODES = {"append", "replace", "section"}


def _require(mapping: dict, key: str, context: str) -> object:
    """Return ``mapping[key]`` or raise :class:`ConfigError` when missing."""
    if not isinstance(mapping, dict) or key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"Missing required config key '{context}{key}'.")
    return mapping[key]


def load_config(path: Path | str = "config.yaml") -> AppConfig:
    """Load and validate the YAML configuration into an :class:`AppConfig`."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(
            f"Config file not found: {config_path}. Copy config.yaml.example to "
            f"config.yaml and adjust it."
        )
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping in {config_path}.")

    whisper_raw = raw.get("whisper") or {}
    output_raw = raw.get("output") or {}
    seo_raw = raw.get("seo") or {}
    wp_raw = raw.get("wordpress") or {}

    update_mode = str(wp_raw.get("update_mode", "section")).lower()
    if update_mode not in ALLOWED_UPDATE_MODES:
        raise ConfigError(
            f"Invalid wordpress.update_mode '{update_mode}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_UPDATE_MODES))}."
        )

    try:
        return AppConfig(
            podcast_feed_url=str(_require(raw, "podcast_feed_url", "")),
            whisper=WhisperConfig(
                conda_env=str(_require(whisper_raw, "conda_env", "whisper.")),
                model=str(_require(whisper_raw, "model", "whisper.")),
                output_format=str(whisper_raw.get("output_format", "txt")),
            ),
            output=OutputConfig(
                audio_dir=Path(str(_require(output_raw, "audio_dir", "output."))),
                transcripts_dir=Path(
                    str(_require(output_raw, "transcripts_dir", "output."))
                ),
                posts_dir=Path(str(_require(output_raw, "posts_dir", "output."))),
            ),
            seo=SeoConfig(
                site_name=str(_require(seo_raw, "site_name", "seo.")),
                default_author=str(seo_raw.get("default_author", "")),
                tone=str(seo_raw.get("tone", "")),
                language=str(seo_raw.get("language", "")),
            ),
            wordpress=WordPressConfig(
                base_url=str(_require(wp_raw, "base_url", "wordpress.")).rstrip("/"),
                post_type=str(_require(wp_raw, "post_type", "wordpress.")),
                update_mode=update_mode,
                confirm_before_update=bool(wp_raw.get("confirm_before_update", True)),
            ),
        )
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config in {config_path}: {exc}") from exc


def load_credentials(env_file: Path | str = ".env") -> WordPressCredentials:
    """Load WordPress credentials from the environment or a local ``.env``.

    Raises :class:`ConfigError` when either value is missing. The application
    password is never logged or printed.
    """
    env_path = Path(env_file)
    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    username = os.getenv("WORDPRESS_USERNAME", "").strip()
    application_password = os.getenv("WORDPRESS_APPLICATION_PASSWORD", "").strip()
    if not username or not application_password:
        raise ConfigError(
            "Missing WordPress credentials. Set WORDPRESS_USERNAME and "
            "WORDPRESS_APPLICATION_PASSWORD in your environment or .env file "
            "(copy .env.example to .env)."
        )
    return WordPressCredentials(
        username=username, application_password=application_password
    )
