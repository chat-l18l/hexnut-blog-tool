"""Blogger API thin wrapper.

Why: Centralize all direct calls to Blogger v3 so the rest of the code stays clean.
What: insert, patch, get blog, publish helpers. Use postId from frontmatter for updates.
Pre:  Valid credentials from auth.py, valid HTML content, correct blog.
Post: Post created/updated on Blogger. Returns post dict with id + url.
"""

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pathlib import Path
import yaml
import re
import json
import os
import shlex
import subprocess
import typer
from .auth import get_credentials
from . import utils

BLOGGER_SERVICE = None

def get_service():
    global BLOGGER_SERVICE
    if BLOGGER_SERVICE is None:
        creds = get_credentials()
        BLOGGER_SERVICE = build("blogger", "v3", credentials=creds)
    return BLOGGER_SERVICE

def get_blog_id(config: dict) -> str:
    """Resolve blogId. Prefer explicit, else getByUrl."""
    if "blog_id" in config.get("blog", {}):
        return str(config["blog"]["blog_id"])

    blog_url = config["blog"]["url"]
    service = get_service()
    try:
        blog = service.blogs().getByUrl(url=blog_url).execute()
        return blog["id"]
    except HttpError as e:
        raise RuntimeError(f"Could not resolve blog id for {blog_url}: {e}") from e

def insert_post(blog_id: str, title: str, content: str, labels: list[str]) -> dict:
    """Create new post. Returns the created post resource."""
    service = get_service()
    body = {
        "kind": "blogger#post",
        "title": title,
        "content": content,
        "labels": labels,
    }
    post = service.posts().insert(blogId=blog_id, body=body, isDraft=True).execute()
    return post

def patch_post(blog_id: str, post_id: str, body: dict) -> dict:
    """Partial update. Body should contain the fields to change.
    Always include 'id' for safety.
    """
    service = get_service()
    if "id" not in body:
        body["id"] = post_id
    post = service.posts().patch(blogId=blog_id, postId=post_id, body=body).execute()
    return post


def update_post(blog_id: str, post_id: str, body: dict) -> dict:
    """Full update (PUT). Use when you want to replace more fields."""
    service = get_service()
    if "id" not in body:
        body["id"] = post_id
    post = service.posts().update(blogId=blog_id, postId=post_id, body=body).execute()
    return post

def publish_post(blog_id: str, post_id: str) -> dict:
    """Publish a draft."""
    service = get_service()
    return service.posts().publish(blogId=blog_id, postId=post_id).execute()

def get_post(blog_id: str, post_id: str, view: str | None = None) -> dict:
    """Fetch full post. Use view='ADMIN' to get status etc. (may 404 if no admin access)."""
    service = get_service()
    params = {"blogId": blog_id, "postId": post_id}
    if view:
        params["view"] = view.upper()
    return service.posts().get(**params).execute()


def list_posts(blog_id: str, max_results: int = 20, status: str | None = None,
                 labels: str | None = None, order_by: str = "PUBLISHED",
                 fetch_bodies: bool = False, page_token: str | None = None,
                 view: str | None = None) -> dict:
    """List posts. Returns the raw list response (with items + nextPageToken)."""
    service = get_service()
    # Normalize to match API enum expectations (client validates case)
    order_by = (order_by or "PUBLISHED").upper()
    params = {
        "blogId": blog_id,
        "maxResults": max_results,
        "orderBy": order_by,
        "fetchBodies": fetch_bodies,
    }
    if view:
        params["view"] = view.upper()
    if status:
        params["status"] = status.upper()
    if labels:
        params["labels"] = labels
    if page_token:
        params["pageToken"] = page_token
    return service.posts().list(**params).execute()


def update_article_on_blogger(
    config: dict,
    article: dict,   # parsed frontmatter + html + meta
    draft: bool = True
) -> dict:
    """
    Why: Central decision for create vs update.
    What: If blogger_post_id present -> ALWAYS update that ID (preserve stats).
          Never insert for known posts. Supports many fields (title, content, labels,
          published, status, etc.).
    """
    blog_id = get_blog_id(config)
    title = article.get("title")
    content = article.get("html") or article.get("content", "")
    labels = article.get("labels", [])

    post_id = article.get("blogger_post_id")

    # Build rich body for patch/update
    body = {
        "title": title,
        "content": content,
        "labels": labels,
    }
    # Add other editable fields if present in frontmatter
    for field in ("published", "status", "location"):
        if field in article:
            body[field] = article[field]
        elif f"blogger_{field}" in article:
            body[field] = article[f"blogger_{field}"]

    if post_id:
        # Force update on existing ID - never create duplicate
        post = patch_post(blog_id, post_id, body)
    else:
        # Only for brand new content (no ID yet)
        post = insert_post(blog_id, title, content, labels)
        # write back
        utils.write_post_id_back(article["source_path"], post["id"], post.get("url", ""))

    if not draft and post.get("status") == "DRAFT":
        publish_post(blog_id, post["id"])

    return post


def find_article_for_lang(slug: str | None, lang: str, content_dir: Path) -> Path | None:
    """Find the matching .md file for a language."""
    lang_dir = content_dir / lang
    if slug:
        for md in lang_dir.rglob("*.md"):
            art = utils.load_article(md)
            if art.get("slug") == slug:
                return md
    # fallback: first md in the lang tree if no slug
    for md in lang_dir.rglob("*.md"):
        return md
    return None


def publish(lang: str, draft: bool = True, path: Path | None = None, dry_run: bool = False):
    """High level publish command implementation.
    If path given and has blogger_post_id, we force-update that ID.
    lang may be inferred from article frontmatter.
    """
    from . import convert

    config = utils.load_config()
    content_dir = Path(config.get("paths", {}).get("content_dir", "content"))

    if path:
        articles = [convert.process_article(path, config)]
        # infer lang from the article itself if not provided
        if not lang:
            lang = articles[0].get("lang", "en")
    else:
        if not lang:
            raise ValueError("lang is required when not using --path")
        # find one representative for the lang (or all later)
        target = find_article_for_lang(None, lang, content_dir)
        if not target:
            print(f"No article found for lang={lang}")
            return
        articles = [convert.process_article(target, config)]

    for art in articles:
        # title selection for lang
        if lang == "nl":
            title = art.get("title_nl") or art.get("title")
        else:
            title = art.get("title")

        art["title"] = title or "Untitled"
        art["html"] = art["html"]  # already processed

        if dry_run:
            print(f"[DRY] Would publish/update '{art['title']}' (lang={lang}) with {len(art.get('labels',[]))} labels")
            print(f"      HTML length: {len(art['html'])} chars")
            if art.get("blogger_post_id"):
                print(f"      Will UPDATE existing ID {art['blogger_post_id']}")
            continue

        action = "Updating (existing ID)" if art.get("blogger_post_id") else "Publishing"
        print(f"{action} '{art['title']}' (lang={lang}) ...")
        result = update_article_on_blogger(config, art, draft=draft)
        print(f"  -> post id: {result.get('id')}  url: {result.get('url')}")
        print(f"  status: {result.get('status')}")


# --- New bidirectional support ---

def list_posts_cli(max_results: int = 20, status: str | None = None,
                    labels: str | None = None, json_output: bool = False,
                    order_by: str = "PUBLISHED", view: str | None = None):
    """High-level list for CLI. Prints table or JSON.
    Use --view ADMIN to include status (may require owner access, can cause 404 on some setups).
    """
    config = utils.load_config()
    blog_id = get_blog_id(config)
    resp = list_posts(blog_id, max_results=max_results, status=status,
                      labels=labels, order_by=order_by, fetch_bodies=False, view=view)

    items = resp.get("items", []) or []
    if json_output:
        print(json.dumps({"items": items, "nextPageToken": resp.get("nextPageToken")}, indent=2))
        return

    print_post_table(items)


def print_post_table(items: list[dict], numbered: bool = False):
    """Print selectable posts without truncating their Blogger IDs."""
    if not items:
        print("No posts found.")
        return

    prefix = "#  " if numbered else ""
    print(f"{prefix}{'ID':<20} {'Title':<50} {'Published':<20} {'Status':<8} Labels")
    print("-" * 124)
    for number, post in enumerate(items, 1):
        # Never truncate post IDs: users copy this value into fetch/update and
        # Blogger requires the complete identifier.
        pid = str(post.get("id", ""))
        title = (post.get("title") or "")[:48]
        published = post.get("published", "")[:19]
        status = post.get("status", "")
        labels = ",".join(post.get("labels", [])[:3])
        number_prefix = f"{number:<2} " if numbered else ""
        print(f"{number_prefix}{pid:<20} {title:<50} {published:<20} {status:<8} {labels}")


def open_editor(path: Path):
    """Open a downloaded article in the user's terminal editor."""
    editor = os.environ.get("EDITOR", "nano")
    command = shlex.split(editor) + [str(path)]
    subprocess.run(command, check=True)


def menu(max_results: int = 50):
    """Run a small interactive terminal workflow for pull, edit and update.

    The menu deliberately requires an explicit confirmation before a remote
    update. Existing Blogger IDs are retained in the fetched frontmatter.
    """
    config = utils.load_config()
    blog_id = get_blog_id(config)
    response = list_posts(blog_id, max_results=max_results, fetch_bodies=False)
    items = response.get("items", []) or []

    if not items:
        print("No posts found.")
        return

    while True:
        print()
        print_post_table(items, numbered=True)
        choice = typer.prompt("Select number, r=refresh, q=quit", default="q").strip().lower()
        if choice == "q":
            return
        if choice == "r":
            response = list_posts(blog_id, max_results=max_results, fetch_bodies=False)
            items = response.get("items", []) or []
            continue
        if not choice.isdigit() or not 1 <= int(choice) <= len(items):
            print("Invalid selection.")
            continue

        selected = items[int(choice) - 1]
        post_id = str(selected["id"])
        print(f"Selected: {post_id} - {selected.get('title', '')}")
        action = typer.prompt("f=fetch, e=fetch+edit, u=fetch+edit+update, b=back", default="b").strip().lower()
        if action == "b":
            continue
        if action not in ("f", "e", "u"):
            print("Invalid action.")
            continue

        path = fetch_post(post_id, config=config)
        if action in ("e", "u"):
            open_editor(path)
        if action == "u":
            if typer.confirm("Update this existing Blogger post with the edited file?", default=False):
                # Existing post ID in the fetched frontmatter forces patch/update,
                # preserving the Blogger URL, comments and statistics.
                publish(lang="", path=path, draft=True)
            else:
                print("Remote update cancelled.")


def fetch_post(post_id: str, lang: str | None = None, output: Path | None = None,
                config: dict | None = None, view: str | None = None) -> Path:
    """Fetch a post from Blogger, convert to local MD, write to content tree.
    Returns the path written.
    """
    if config is None:
        config = utils.load_config()
    blog_id = get_blog_id(config)
    post = get_post(blog_id, post_id, view=view)

    # Determine target path
    content_dir = Path(config.get("paths", {}).get("content_dir", "content"))
    slug = post.get("id")
    # Try to use title for nicer filename, sanitize
    title_for_file = (post.get("title") or post.get("id", "post")).lower()
    title_for_file = re.sub(r'[^a-z0-9]+', '-', title_for_file).strip('-')[:60] or "post"

    if output:
        target = output
    else:
        use_lang = lang
        if not use_lang:
            # derive from labels
            for lab in post.get("labels", []):
                if lab.startswith("lang:"):
                    use_lang = lab.split(":", 1)[1]
                    break
        use_lang = use_lang or "en"
        sub = "projecten" if use_lang == "nl" else "projects"
        target_dir = content_dir / use_lang / sub
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{title_for_file}.md"

    from . import convert
    convert.build_article_from_post(post, target, config)
    print(f"Fetched post {post_id} -> {target}")
    return target
