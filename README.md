# podcast-to-wordpress-seo

A local, privacy-friendly Python CLI that turns a podcast RSS episode into an
SEO-optimized WordPress post.

The workflow is fully local: it reads a podcast RSS feed, lets you pick an
episode, downloads the audio, transcribes it **on your own machine** with
[MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
(Apple Silicon), generates SEO content, and updates the original WordPress post
referenced by the RSS `<guid isPermaLink="true">…</guid>`.

No audio is ever uploaded to a cloud transcription service, and no external AI
API is called in this version.

## What it does

```
RSS feed ──▶ pick episode ──▶ download audio ──▶ MLX Whisper transcript
        ──▶ SEO draft (Markdown) ──▶ update the linked WordPress post
```

1. Reads the podcast RSS feed from `config.yaml` (or `--feed`).
2. Lists episodes and lets you choose one.
3. Downloads the selected episode audio into `output/audio/`.
4. Detects the language from the feed `<language>` (e.g. `ca`).
5. Transcribes locally with `mlx_whisper` via `conda run` into `output/transcripts/`.
6. Generates an SEO draft (title, slug, meta description, excerpt, summary,
   article, key points, reflection questions, categories, tags, CTA, and the
   full LLM-ready prompt) into `output/posts/`.
7. Resolves the WordPress post from the RSS GUID permalink and updates it via
   the REST API using an Application Password.

## The GitHub Copilot custom agent

This repository ships a custom agent profile at
[`.github/agents/podcast-to-wordpress-seo.agent.md`](.github/agents/podcast-to-wordpress-seo.agent.md).

Select **podcast-to-wordpress-seo** in the VS Code Copilot agent picker to get an
assistant specialized in this codebase. It knows the flat-module layout, the
verified gotchas (RSS `isPermaLink` parsing, WordPress custom post type REST
base resolution, `conda run` transcription), the security rules (never hardcode
or print credentials, never upload audio, confirm before updating WordPress),
and the coding standards used here. Use it to add features, fix bugs, or keep
the docs and configuration in sync.

## Requirements

- macOS on Apple Silicon (for MLX Whisper).
- Python 3.11+.
- [Miniconda / Anaconda](https://docs.conda.io/) for the Whisper environment.
- A WordPress site with the REST API enabled and an Application Password.

## 1. Create the MLX Whisper environment

MLX Whisper runs in its own conda environment. The CLI invokes it with
`conda run` (it never calls `conda activate`).

```bash
conda create -n whisper311 python=3.11
conda activate whisper311
pip install mlx-whisper
```

The environment name must match `whisper.conda_env` in `config.yaml`
(`whisper311` by default).

## 2. Set up the project environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
cp .env.example .env
```

To run the test suite you also need `pytest`:

```bash
pip install pytest
python -m pytest -q
```

## 3. Configure `config.yaml`

```yaml
podcast_feed_url: "https://esglesialagarriga.cat/podcast.xml"

whisper:
  conda_env: "whisper311"
  model: "mlx-community/whisper-large-v3-mlx"
  output_format: "txt"

output:
  audio_dir: "output/audio"
  transcripts_dir: "output/transcripts"
  posts_dir: "output/posts"

seo:
  site_name: "Església la Garriga"
  default_author: "Església la Garriga"
  tone: "warm, clear, pastoral, biblical, natural, and welcoming"
  language: "ca"

wordpress:
  base_url: "https://esglesialagarriga.cat"
  post_type: "esdeveniment"
  update_mode: "append"   # append | replace | section
  confirm_before_update: true
```

### Update modes

- `append` — add the generated block after the existing post content.
- `replace` — replace the whole post content.
- `section` — insert or replace a block delimited by
  `<!-- podcast-seo:start -->` / `<!-- podcast-seo:end -->`. This is the
  safest, repeatable option: re-running only updates the content between the
  markers.

## 4. Configure `.env` (WordPress credentials)

```dotenv
WORDPRESS_USERNAME=your-wp-username
WORDPRESS_APPLICATION_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

`.env` is git-ignored. Never commit real credentials.

### How WordPress Application Passwords work

Application Passwords let an app authenticate as your user without your main
password:

1. In WordPress, go to **Users → Profile → Application Passwords**.
2. Enter a name (e.g. `podcast-seo`) and click **Add New Application Password**.
3. Copy the generated password (shown once) into
   `WORDPRESS_APPLICATION_PASSWORD`.
4. Use your normal login as `WORDPRESS_USERNAME`.

Authentication uses HTTP Basic Auth over HTTPS
(`requests.auth.HTTPBasicAuth`). The application password is never logged or
printed. Your account needs permission to edit the target post type.

## Running the CLI

Interactive run (uses `config.yaml`):

```bash
python src/main.py
```

Preview everything without touching WordPress:

```bash
python src/main.py --feed https://esglesialagarriga.cat/podcast.xml --dry-run
```

Run and update WordPress:

```bash
python src/main.py --feed https://esglesialagarriga.cat/podcast.xml
```

### CLI options

| Flag | Description |
|------|-------------|
| `--feed URL` | Override the configured podcast RSS feed URL. |
| `--config PATH` | Path to the YAML config (default `config.yaml`). |
| `--env PATH` | Path to the `.env` file (default `.env`). |
| `--force` | Overwrite existing audio/transcript/output files. |
| `--limit N` | Limit the number of displayed episodes. |
| `--model NAME` | Override the Whisper MLX model. |
| `--language CODE` | Override the detected feed language. |
| `--dry-run` | Generate all files but do not update WordPress. |
| `--yes` | Skip the confirmation prompt before updating WordPress. |

### Language and model resolution

- **Language** priority: `--language` → RSS feed `<language>` → `seo.language`.
- **Model** priority: `--model` → `whisper.model`.

## Output

```
output/
├── audio/nomes-cal-fe-per-ser-salvats.mp3
├── transcripts/nomes-cal-fe-per-ser-salvats.txt
└── posts/nomes-cal-fe-per-ser-salvats-seo.md
```

The `…-seo.md` draft contains the SEO title, slug, meta description, excerpt,
summary, WordPress article HTML, key points, reflection questions, suggested
categories/tags, the call to action, the source metadata, the transcript
reference, and the full LLM prompt used.

## Troubleshooting

- **`conda: command not found`** — Install Miniconda/Anaconda and make sure
  `conda` is on your PATH.
- **`mlx_whisper` fails / not found** — Install it in the environment:
  `conda run -n whisper311 pip install mlx-whisper`.
- **Feed cannot be fetched/parsed** — Check the URL and your network; the feed
  must be valid RSS with at least one episode.
- **Episode has no audio** — Episodes without an enclosure are listed but can't
  be processed.
- **WordPress 401** — Wrong username or application password.
- **WordPress 403** — The user lacks rights to edit that post type.
- **WordPress post not found** — The GUID slug doesn't match any post under the
  configured post type or `posts`. The client resolves the real REST base via
  `/wp-json/wp/v2/types/<post_type>` (custom post types are often served under a
  different base) before falling back.
- **Multiple posts for a slug** — Resolve the ambiguity in WordPress; the client
  refuses to guess.
- **`isPermaLink` not detected** — The RSS `<guid>` must be a URL and either
  omit `isPermaLink` or set `isPermaLink="true"` for the WordPress update to run.

## Security

- WordPress credentials come only from environment variables / `.env`, never
  hardcoded.
- The application password is never logged or printed.
- `.env` and local `config.yaml` are git-ignored.
- Audio is transcribed locally and never uploaded anywhere.
- No external AI API is called in this version.

## Project layout

```
.
├── .github/agents/podcast-to-wordpress-seo.agent.md
├── src/
│   ├── main.py               # CLI orchestration
│   ├── config.py             # config + credentials loading
│   ├── feed_reader.py        # RSS parsing (+ isPermaLink handling)
│   ├── episode_selector.py   # interactive selection
│   ├── audio_downloader.py   # enclosure download
│   ├── transcriber.py        # MLX Whisper via conda run
│   ├── seo_generator.py      # deterministic SEO draft + LLM prompt
│   ├── wordpress_client.py   # REST resolve + update
│   ├── wordpress_formatter.py# append/replace/section merge
│   └── utils.py              # console, slug, filename, resolution helpers
├── prompts/seo_post_prompt.md
├── tests/test_slugify.py
├── output/{audio,transcripts,posts}/
├── config.yaml.example
├── .env.example
└── requirements.txt
```

## Future improvements

- OpenAI/LLM integration to generate the final SEO text automatically.
- Batch processing of all podcast episodes.
- Automatic biblical reference and speaker extraction.
- Automatic categories and tags.
- Featured image generation or selection.
- Direct support for custom WordPress fields.
- SRT/VTT subtitle generation.
- Scheduling or GitHub Actions integration.
