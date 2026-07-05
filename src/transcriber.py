"""Local transcription with MLX Whisper, invoked through ``conda run``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from utils import console, ensure_dir


class TranscriptionError(Exception):
    """Raised when transcription cannot be performed or fails."""


def conda_available() -> bool:
    """Return whether a ``conda`` executable is on the PATH."""
    return shutil.which("conda") is not None


def _find_transcript(
    directory: Path, stem: str, output_format: str
) -> Optional[Path]:
    """Locate the transcript mlx_whisper produced for ``stem``."""
    exact = directory / f"{stem}.{output_format}"
    if exact.is_file():
        return exact
    matches = sorted(directory.glob(f"{stem}.*"))
    return matches[0] if matches else None


def transcribe(
    audio_path: Path | str,
    transcripts_dir: Path | str,
    *,
    conda_env: str,
    model: str,
    language: str,
    output_format: str = "txt",
    force: bool = False,
) -> Path:
    """Transcribe ``audio_path`` locally with MLX Whisper.

    Runs ``conda run -n <env> mlx_whisper <audio> --language <lang>
    --model <model> -f <format> -o <transcripts_dir>`` as a safe argument list
    (never ``shell=True``). Existing transcripts are reused unless ``force`` is
    ``True``. Returns the path to the transcript file.
    """
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    transcripts_dir = ensure_dir(transcripts_dir)
    transcript_path = transcripts_dir / f"{audio_path.stem}.{output_format}"

    if transcript_path.exists() and not force:
        console.print(f"[green]Transcript already exists:[/green] {transcript_path}")
        return transcript_path

    if not conda_available():
        raise TranscriptionError(
            "The 'conda' executable was not found on PATH. Install Miniconda or "
            "Anaconda and create the whisper environment (see the README)."
        )

    command = [
        "conda",
        "run",
        "-n",
        conda_env,
        "mlx_whisper",
        str(audio_path),
        "--language",
        language,
        "--model",
        model,
        "-f",
        output_format,
        "-o",
        str(transcripts_dir),
    ]

    console.print("[dim]$ " + " ".join(command) + "[/dim]")

    try:
        # No shell=True; output streams straight to the terminal.
        completed = subprocess.run(command, check=False, text=True)
    except FileNotFoundError as exc:
        raise TranscriptionError(
            f"Could not execute conda/mlx_whisper: {exc}. Is mlx-whisper "
            f"installed in the '{conda_env}' environment?"
        ) from exc

    if completed.returncode != 0:
        raise TranscriptionError(
            f"mlx_whisper failed with exit code {completed.returncode}. Verify the "
            f"'{conda_env}' environment has mlx-whisper installed "
            f"(conda run -n {conda_env} pip install mlx-whisper)."
        )

    if not transcript_path.is_file():
        located = _find_transcript(transcripts_dir, audio_path.stem, output_format)
        if located is None:
            raise TranscriptionError(
                "Transcription finished but no transcript file was found in "
                f"{transcripts_dir}."
            )
        transcript_path = located

    console.print(f"[green]Transcript saved to:[/green] {transcript_path}")
    return transcript_path
