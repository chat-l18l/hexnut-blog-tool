"""Small shared utilities.

Why: Avoid duplication for frontmatter, config loading, path handling.
What: Load/save yaml frontmatter, config, image url rewriting, post id writeback.
"""

from pathlib import Path
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

def build_labels(article: dict, lang: str) -> list[str]:
    # Prefer explicit "labels" (from fetch or user) else fall back to tags/keywords
    if "labels" in article and article["labels"]:
        base = list(article["labels"])
    else:
        tags = article.get("tags", []) or []
        keywords = article.get("keywords", []) or []
        base = list(tags)
        if keywords:
            base.extend([f"kw:{k}" for k in keywords])
    labels = base + [f"lang:{lang}"]
    slug = article.get("slug")
    if slug and not any(l.startswith("slug:") for l in labels):
        labels.append(f"slug:{slug}")
    # dedup while preserving order
    seen = set()
    out = []
    for l in labels:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out
