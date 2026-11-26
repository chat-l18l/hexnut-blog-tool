"""Small shared utilities.

Why: Avoid duplication for frontmatter, config loading, path handling.
What: Load/save yaml frontmatter, config, image url rewriting, post id writeback.
"""

from pathlib import Path
import re
import yaml
import frontmatter
from typing import Any

def load_config(path: Path | None = None) -> dict:
    if path is None:
        path = Path("config/default.yaml")
    with open(path) as f:
        return yaml.safe_load(f)

def load_article(path: Path) -> dict:
    """Load MD + frontmatter. Returns dict with all keys + raw content + source_path."""
    post = frontmatter.load(path)
    data = dict(post.metadata)
    data["content"] = post.content
    data["source_path"] = str(path)
    return data

def save_article(path: Path, data: dict, content: str):
    """Write back article (used by LLM prepare and by id writeback)."""
    post = frontmatter.Post(content, **{k: v for k, v in data.items() if k not in ("content", "source_path")})
    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

def write_post_id_back(source_path: str, post_id: str, url: str):
    """Update the source MD frontmatter with blogger_post_id and blogger_url."""
    path = Path(source_path)
    article = load_article(path)
    article["blogger_post_id"] = post_id
    article["blogger_url"] = url
    # keep original content
    content = article.pop("content")
    save_article(path, article, content)
    print(f"Wrote back post_id={post_id} to {source_path}")


def write_blogger_meta(source_path: str, post: dict):
    """Write rich blogger metadata from a fetched post into frontmatter.
    Preserves existing user fields. Stores id for updates.
    """
    path = Path(source_path)
    article = load_article(path)
    # Core identity for updates (never lose the ID)
    article["blogger_post_id"] = post.get("id")
    article["blogger_url"] = post.get("url", "")
    # Editable / useful fields (user can edit these in frontmatter)
    if "title" in post:
        article.setdefault("title", post["title"])  # don't overwrite if user has custom
    if post.get("labels"):
        # keep as list for consistency
        article["labels"] = post["labels"]
    if post.get("published"):
        article["blogger_published"] = post["published"]
        article.setdefault("published", post["published"])
    if post.get("status"):
        article["blogger_status"] = post["status"]
    # Store other potentially editable fields
    for key in ("location",):
        if key in post:
            article[f"blogger_{key}"] = post[key]
    content = article.pop("content", "")
    save_article(path, article, content)
    print(f"Updated blogger meta (id={post.get('id')}) in {source_path}")

def github_raw_image_url(config: dict, rel_path: str) -> str:
    """Turn assets/images/foo.png into full raw github url."""
    gh = config.get("github", {})
    user = gh.get("user", "yourusername")
    repo = gh.get("repo", "hexnut-blog-tool")
    # assume path is relative like assets/images/...
    return f"https://raw.githubusercontent.com/{user}/{repo}/main/{rel_path}"

# Blogger shows every label on the post and in the label widget; there is no
# hidden-label syntax. These prefixes were used by older versions of this tool
# and are never sent as labels any more.
INTERNAL_LABEL_PREFIXES = ("kw:", "lang:", "slug:")
_META_COMMENT_RE = re.compile(r"<!--\s*hexnut\s+(.*?)-->", re.S)


def meta_comment(article: dict, lang: str) -> str:
    """Invisible HTML marker carrying lang and slug inside the post body.

    Why: fetch must recover lang/slug, but public labels are the wrong place.
    What: returns e.g. '<!-- hexnut lang=nl slug=my-post -->'.
    Pre: lang is a non-empty token; slug (if present) has no whitespace or '--'.
    Post: parse_meta_comment(result) == {'lang': lang, 'slug': slug}.
    """
    assert lang and lang.isalnum(), f"invalid lang: {lang!r}"
    parts = [f"lang={lang}"]
    slug = article.get("slug")
    if slug:
        assert not re.search(r"\s|--", slug), f"slug cannot live in an HTML comment: {slug!r}"
        parts.append(f"slug={slug}")
    return f"<!-- hexnut {' '.join(parts)} -->"


def parse_meta_comment(html: str) -> dict:
    """Read the hexnut marker from post HTML.

    Why/What: counterpart of meta_comment; returns {'lang': .., 'slug': ..}.
    Pre: html is a string (None is treated as empty for fetched posts without content).
    Post: {} when no marker is present.
    """
    m = _META_COMMENT_RE.search(html or "")
    if not m:
        return {}
    return dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv)


def strip_meta_comment(html: str) -> str:
    """Remove the first hexnut marker so it does not end up in the local Markdown."""
    return _META_COMMENT_RE.sub("", html or "", count=1).lstrip()


def lang_from_post(post: dict) -> str | None:
    """Language of a fetched Blogger post.

    Why: decide content/<lang>/ on fetch without relying on public labels.
    What: marker first, then legacy 'lang:' labels for posts published before the marker.
    Pre: post is a Blogger post dict.
    Post: 'en', 'nl', ... or None when unknown (caller chooses the default).
    """
    assert isinstance(post, dict), "post must be a dict"
    lang = parse_meta_comment(post.get("content", "")).get("lang")
    if lang:
        return lang
    for lab in post.get("labels", []) or []:
        if lab.startswith("lang:"):
            return lab.split(":", 1)[1]
    return None


def build_labels(article: dict, lang: str) -> list[str]:
    """Public Blogger labels for an article.

    Why: labels are visible to readers, so only human topic tags belong there.
    What: explicit 'labels' (from fetch/user) if present, else 'tags'; internal
          kw:/lang:/slug: entries are dropped; order kept, duplicates removed.
          lang/slug travel via meta_comment, keywords stay in the frontmatter.
    Pre: article is a dict; lang is non-empty (kept for a stable call signature).
    Post: no returned label starts with INTERNAL_LABEL_PREFIXES.
    """
    assert isinstance(article, dict), "article must be a dict"
    assert lang, "lang is required"
    if "labels" in article and article["labels"]:
        base = list(article["labels"])
    else:
        base = list(article.get("tags", []) or [])
    out: list[str] = []
    seen: set[str] = set()
    for label in base:
        if label.startswith(INTERNAL_LABEL_PREFIXES) or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out
