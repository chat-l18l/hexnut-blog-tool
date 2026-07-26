"""CLI entrypoint for hexnut-blog-tool.

Why: Provide a simple, discoverable command line interface.
What: Thin wrapper that dispatches to the real modules.
Pre:  Virtualenv with requirements installed + valid .env + config.
Post: Commands run or show helpful errors.
"""

import typer
from pathlib import Path
from typing import Optional

app = typer.Typer(help="hexnut-blog-tool: git MD -> hexnut.net (Blogger) with AI assist")

@app.command()
def auth():
    """Run OAuth flow for Blogger API (one-time)."""
    from . import auth as auth_mod
    auth_mod.run_auth()

@app.command()
def prepare(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to a .md file to prepare with LLM"),
    lang: Optional[str] = typer.Option(None, help="Force lang (en|nl)")
):
    """Use LLM (Grok) to help write/refine/translate an article."""
    from . import llm
    llm.prepare_article(path, lang=lang)

@app.command()
def build(
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write files, only show what would happen")
):
    """Parse content, render Mermaid, rewrite images, build cross-refs, produce HTML previews."""
    from . import convert
    convert.build_all(dry_run=dry_run)

@app.command()
def publish(
    lang: Optional[str] = typer.Option(None, "--lang", help="en or nl (inferred from frontmatter if omitted when using --path)"),
    draft: bool = typer.Option(True, "--draft/--publish", help="Publish as draft"),
    path: Optional[Path] = typer.Option(None, help="Publish only this specific article (optional)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be sent without calling API")
):
    """Publish (or update) the article(s) for the given language to Blogger.
    When using --path on a previously fetched article, the stored blogger_post_id is used
    to update in place (preserving statistics).
    """
    from . import blogger
    blogger.publish(lang=lang, draft=draft, path=path, dry_run=dry_run)

@app.command()
def check():
    """Validate cross-references, images, frontmatter, bilingual pairing."""
    from . import index
    index.run_checks()

@app.command()
def sync(
    lang: Optional[str] = typer.Option(None, help="Limit to one language")
):
    """Build + publish changed articles (simple git-aware or timestamp for v1)."""
    typer.echo("sync not fully implemented in v1 - run build + publish manually")
    # Future: use git diff on content/


# --- Bidirectional commands (list / fetch for offline edit + ID-preserving update) ---

@app.command("list")
def list_posts(
    max_results: int = typer.Option(20, "--max", help="Max posts to return"),
    status: Optional[str] = typer.Option(None, help="draft | live | scheduled"),
    labels: Optional[str] = typer.Option(None, help="Comma separated labels filter"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON instead of table"),
    order_by: str = typer.Option("PUBLISHED", "--order-by", help="PUBLISHED | UPDATED"),
    view: Optional[str] = typer.Option(None, "--view", help="ADMIN (to get status etc, may 404)"),
):
    """List existing posts on the blog (use for discovery before fetch)."""
    from . import blogger
    blogger.list_posts_cli(max_results=max_results, status=status, labels=labels,
                           json_output=json_output, order_by=order_by, view=view)


@app.command()
def fetch(
    post_id: str = typer.Argument(..., help="Blogger post ID to fetch"),
    lang: Optional[str] = typer.Option(None, "--lang", help="en or nl (auto from labels if omitted)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Explicit output .md path (overrides auto placement)"),
    view: Optional[str] = typer.Option(None, "--view", help="ADMIN (to get status/drafts) or omit for default"),
):
    """Download a post from Blogger as local Markdown + rich frontmatter.
    After fetch you can: prepare (LLM), edit, build, then publish (same ID preserved).
    Use --view ADMIN if fetching drafts or to get full admin fields (may 404 otherwise).
    """
    from . import blogger
    blogger.fetch_post(post_id, lang=lang, output=output, view=view)


@app.command()
def menu(
    max_results: int = typer.Option(50, "--max", help="Max posts shown in the menu"),
):
    """Interactive terminal menu: list, fetch, edit and update a post.

    The menu keeps fetched post IDs in frontmatter and asks confirmation before
    sending an update to Blogger.
    """
    from . import blogger
    blogger.menu(max_results=max_results)


if __name__ == "__main__":
    app()
