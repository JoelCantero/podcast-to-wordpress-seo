"""Interactive episode selection using Rich."""

from __future__ import annotations

from typing import Optional

from rich.prompt import Prompt
from rich.table import Table

from feed_reader import PodcastEpisode, PodcastFeed
from utils import console


class SelectionCancelled(Exception):
    """Raised when the user cancels episode selection."""


def _render_episodes(episodes: list[PodcastEpisode]) -> None:
    """Print a numbered table of episodes, flagging those without audio."""
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Episode")
    table.add_column("Date", style="dim")
    table.add_column("Status")

    for index, episode in enumerate(episodes, start=1):
        status = "[green]audio[/green]" if episode.has_audio else "[red]no audio[/red]"
        table.add_row(str(index), episode.title, episode.pub_date or "—", status)

    console.print(table)


def select_episode(
    feed: PodcastFeed,
    *,
    limit: Optional[int] = None,
) -> PodcastEpisode:
    """Display episodes and prompt the user to choose one.

    ``limit`` restricts how many episodes are displayed. Invalid numbers and
    episodes without audio are rejected; entering ``q`` raises
    :class:`SelectionCancelled`.
    """
    episodes = feed.episodes[:limit] if limit else feed.episodes

    console.print()
    console.print(f"[bold]Podcast:[/bold] {feed.title}")
    if feed.language:
        console.print(f"[bold]Language:[/bold] {feed.language}")
    console.print()
    console.print("[bold]Available episodes:[/bold]")
    _render_episodes(episodes)
    console.print()

    while True:
        answer = Prompt.ask(
            "Which episode do you want to process? ([cyan]q[/cyan] to cancel)"
        ).strip().lower()

        if answer in {"q", "quit", "exit"}:
            raise SelectionCancelled("Episode selection cancelled by the user.")

        if not answer.isdigit():
            console.print("[red]Please enter a valid episode number.[/red]")
            continue

        index = int(answer)
        if not 1 <= index <= len(episodes):
            console.print(
                f"[red]Choose a number between 1 and {len(episodes)}.[/red]"
            )
            continue

        episode = episodes[index - 1]
        if not episode.has_audio:
            console.print(
                "[red]That episode has no audio enclosure and cannot be processed.[/red]"
            )
            continue

        return episode
