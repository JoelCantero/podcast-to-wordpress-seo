"""Download podcast episode audio to the local output directory."""

from __future__ import annotations

from pathlib import Path

import requests
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from feed_reader import PodcastEpisode
from utils import USER_AGENT, build_audio_filename, console, ensure_dir


class DownloadError(Exception):
    """Raised when the episode audio cannot be downloaded."""


def download_audio(
    episode: PodcastEpisode,
    audio_dir: Path | str,
    *,
    force: bool = False,
    timeout: int = 60,
) -> Path:
    """Download the episode enclosure audio into ``audio_dir``.

    The filename is derived from a slugified episode title, preserving the
    original audio extension when possible (defaulting to ``.mp3``). Existing
    files are reused unless ``force`` is ``True``.
    """
    if not episode.audio_url:
        raise DownloadError(f"Episode '{episode.title}' has no audio URL to download.")

    audio_dir = ensure_dir(audio_dir)
    filename = build_audio_filename(episode.title, episode.audio_url)
    destination = audio_dir / filename

    if destination.exists() and not force:
        console.print(f"[green]Audio already downloaded:[/green] {destination}")
        return destination

    console.print(f"Downloading audio from {episode.audio_url} ...")
    partial = destination.with_name(destination.name + ".part")

    try:
        with requests.get(
            episode.audio_url,
            stream=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0)) or None

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
            )
            with progress:
                task = progress.add_task("Downloading", total=total)
                with open(partial, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            handle.write(chunk)
                            progress.update(task, advance=len(chunk))
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"Failed to download audio: {exc}") from exc

    partial.replace(destination)
    console.print(f"[green]Audio saved to:[/green] {destination}")
    return destination
