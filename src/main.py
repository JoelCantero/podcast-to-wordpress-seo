"""Command-line entry point: RSS episode -> transcript -> SEO -> WordPress.

Run with ``python src/main.py`` (optionally with the flags below).
"""

from __future__ import annotations

import argparse

from rich.prompt import Confirm

from audio_downloader import DownloadError, download_audio
from config import AppConfig, ConfigError, load_config, load_credentials
from episode_selector import SelectionCancelled, select_episode
from feed_reader import FeedError, PodcastEpisode, read_feed
from seo_generator import SeoContent, generate_seo_content
from transcriber import TranscriptionError, transcribe
from utils import console, extract_slug_from_url, resolve_language, resolve_model
from wordpress_client import WordPressClient, WordPressError
from wordpress_formatter import apply_update
import agent_content
from agent_content import AgentPost


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="podcast-to-wordpress-seo",
        description=(
            "Read a podcast RSS feed, transcribe an episode locally with MLX "
            "Whisper, generate SEO content, and update the linked WordPress post."
        ),
    )
    parser.add_argument("--feed", help="Override the configured podcast RSS feed URL.")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the YAML config file."
    )
    parser.add_argument(
        "--env", default=".env", help="Path to the .env file with WordPress secrets."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing audio/transcript/output files.",
    )
    parser.add_argument(
        "--limit", type=int, help="Limit the number of displayed episodes."
    )
    parser.add_argument("--model", help="Override the Whisper MLX model.")
    parser.add_argument("--language", help="Override the detected feed language.")
    parser.add_argument(
        "--update-mode",
        choices=["append", "replace", "section"],
        help="Override wordpress.update_mode for this run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate all files but do not update WordPress.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts before updating WordPress.",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help=(
            "Publish the deterministic draft instead of waiting for "
            "agent-authored content."
        ),
    )
    return parser


def _print_update_plan(
    config: AppConfig,
    *,
    title: str,
    url: str,
    source: str,
    excerpt: str | None,
    dry_run: bool,
) -> None:
    """Display what is about to happen before touching WordPress."""
    console.print()
    console.print(f"[bold]WordPress post title:[/bold] {title or '(untitled)'}")
    console.print(f"[bold]WordPress post URL:[/bold] {url or '—'}")
    console.print(f"[bold]Update mode:[/bold] {config.wordpress.update_mode}")
    console.print(f"[bold]Content source:[/bold] {source}")
    console.print(f"[bold]Excerpt:[/bold] {excerpt or '—'}")
    console.print(f"[bold]Dry run:[/bold] {'yes' if dry_run else 'no'}")


def _update_wordpress(
    args: argparse.Namespace,
    config: AppConfig,
    episode: PodcastEpisode,
    seo: SeoContent,
    agent_post: AgentPost | None,
    handoff_path,
) -> None:
    """Resolve and update the WordPress post referenced by the episode GUID."""
    console.print()
    console.rule("Resolving WordPress post from GUID")

    permalink = episode.permalink_url
    if not permalink:
        if episode.guid and not episode.guid_is_permalink:
            console.print(
                "[yellow]Episode GUID is not marked isPermaLink=\"true\"; cannot "
                "resolve the WordPress post. Skipping update.[/yellow]"
            )
        else:
            console.print(
                "[yellow]Episode has no GUID permalink; skipping WordPress update.[/yellow]"
            )
        return

    slug = extract_slug_from_url(permalink)
    if not slug:
        console.print(
            f"[yellow]Could not derive a slug from GUID '{permalink}'; skipping "
            f"WordPress update.[/yellow]"
        )
        return

    # Decide where the published body and excerpt come from.
    if agent_post and agent_post.body:
        body = agent_post.body
        excerpt = agent_post.excerpt or seo.excerpt
        source = "agent"
    elif args.deterministic:
        body = seo.wordpress_html
        excerpt = seo.excerpt
        source = "deterministic"
    else:
        console.print(
            f"[yellow]No agent-authored content yet. Write the final title, "
            f"excerpt and Gutenberg body in:[/yellow]\n  {handoff_path}\n"
            f"[yellow]then re-run to publish. Use --deterministic to publish the "
            f"draft instead.[/yellow]"
        )
        return

    console.print(f"GUID permalink: {permalink}")

    try:
        credentials = load_credentials(args.env)
    except ConfigError as exc:
        if args.dry_run:
            console.print(f"[yellow]{exc}[/yellow]")
            _print_update_plan(
                config,
                title="(not resolved — dry run without credentials)",
                url=permalink,
                source=source,
                excerpt=excerpt,
                dry_run=True,
            )
            return
        raise

    client = WordPressClient(config.wordpress.base_url, credentials)
    post = client.find_post_by_slug(slug, config.wordpress.post_type)
    console.print(f"[green]Post found:[/green] {post.title or '(untitled)'}")

    new_content = apply_update(post.content, body, config.wordpress.update_mode)
    _print_update_plan(
        config,
        title=post.title,
        url=post.link or permalink,
        source=source,
        excerpt=excerpt,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        console.print("[yellow]Dry run: WordPress was not modified.[/yellow]")
        return

    if config.wordpress.confirm_before_update and not args.yes:
        if not Confirm.ask("Update this WordPress post?", default=False):
            console.print("[yellow]Update cancelled by the user.[/yellow]")
            return

    updated = client.update_post(post, new_content, excerpt=excerpt)
    console.print(
        f"[bold green]WordPress post updated successfully.[/bold green] "
        f"(id {updated.id})"
    )


def run(args: argparse.Namespace) -> int:
    """Execute the full workflow. Returns a process exit code."""
    config = load_config(args.config)
    feed_url = args.feed or config.podcast_feed_url

    if args.update_mode:
        config.wordpress.update_mode = args.update_mode

    console.rule("Podcast to WordPress SEO")
    console.print("Reading podcast feed...")
    feed = read_feed(feed_url)
    console.print(f"[bold green]Podcast found:[/bold green] {feed.title}")
    if feed.language:
        console.print(f"Language: {feed.language}")

    episode = select_episode(feed, limit=args.limit)
    console.print(f"\n[bold]Selected:[/bold] {episode.title}")

    language = resolve_language(args.language, feed.language, config.seo.language)
    model = resolve_model(args.model, config.whisper.model)

    console.print()
    console.rule("Downloading audio")
    audio_path = download_audio(
        episode, config.output.audio_dir, force=args.force
    )

    console.print()
    console.rule("Transcribing with mlx_whisper")
    transcript_path = transcribe(
        audio_path,
        config.output.transcripts_dir,
        conda_env=config.whisper.conda_env,
        model=model,
        language=language,
        output_format=config.whisper.output_format,
        force=args.force,
    )

    console.print()
    console.rule("Generating SEO content")
    seo = generate_seo_content(
        feed,
        episode,
        transcript_path,
        config,
        language=language,
        force=args.force,
    )

    # Agent-in-the-loop handoff: the final title/excerpt/body are authored by an
    # agent (or human) in this file, not by the deterministic generator.
    handoff_path = agent_content.post_path(config.output.posts_dir, seo.slug)
    agent_post = agent_content.load_agent_post(handoff_path)
    if agent_post is None and not handoff_path.exists():
        agent_content.write_template(
            handoff_path, title=episode.title, reference_path=seo.markdown_path
        )
    console.print(f"[bold]Agent content file:[/bold] {handoff_path}")

    _update_wordpress(args, config, episode, seo, agent_post, handoff_path)

    console.print()
    console.rule("Done")
    console.print(f"[bold]Audio:[/bold] {audio_path}")
    console.print(f"[bold]Transcript:[/bold] {transcript_path}")
    console.print(f"[bold]SEO draft:[/bold] {seo.markdown_path}")
    console.print(f"[bold]Agent content:[/bold] {handoff_path}")
    return 0


def main() -> int:
    """Parse arguments, run the workflow, and translate errors to exit codes."""
    args = build_parser().parse_args()
    try:
        return run(args)
    except SelectionCancelled as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return 130
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    except (
        ConfigError,
        FeedError,
        DownloadError,
        TranscriptionError,
        WordPressError,
    ) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
