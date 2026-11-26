"""Small shared utilities.

Why: Avoid duplication for frontmatter, config loading, path handling.
What: Load/save yaml frontmatter, config, image url rewriting, post id writeback.
"""

from pathlib import Path
import html
import re
from urllib.parse import quote
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


_SERIES_TEXT = {
    "nl": 'Dit artikel hoort bij de serie <a href="{url}">{label}</a>: {blurb}. '
          "Via die link vind je alle delen van de serie, ook de nieuwe.",
    "en": 'This article is part of the series <a href="{url}">{label}</a>: {blurb}. '
          "That link takes you to every part of the series, including new ones.",
}
_SERIES_FOOTER_RE = re.compile(
    r'<div class="hexnut-series"[^>]*data-series="([^"]*)"[^>]*>.*?</div>\s*', re.S)


def series_info(config: dict, key: str, lang: str) -> dict:
    """Label and blurb of one series in one language.

    Why: a series is defined once in config; posts only name its key.
    What: returns {'label': ..., 'blurb': ...} from config['series'][key][lang].
    Pre: key exists in config['series'] and has an entry for lang with a label.
    Post: label is non-empty; it is used verbatim as the public Blogger label.
    """
    series = (config.get("series") or {}).get(key)
    assert series, f"unknown series {key!r}: add it under 'series:' in config/default.yaml"
    info = series.get(lang)
    assert info and info.get("label"), f"series {key!r} has no label for lang {lang!r}"
    return {"label": info["label"], "blurb": info.get("blurb", "")}


def series_label_url(config: dict, label: str) -> str:
    """Public Blogger label page, which always lists every post of the series.

    Pre: config['blog']['public_url'] is set (e.g. https://www.hexnut.net).
    """
    base = (config.get("blog") or {}).get("public_url", "").rstrip("/")
    assert base, "set blog.public_url in config/default.yaml"
    return f"{base}/search/label/{quote(label)}"


def series_footer_html(config: dict, key: str, lang: str) -> str:
    """Footer linking a post to its series page.

    Why: new parts must become findable from old posts without editing them;
         a link to the label page does that, because Blogger keeps that page current.
    What: <div class="hexnut-series" data-series="label">…</div>; fetch strips it again.
    Pre: series_info(config, key, lang) is valid and lang has a footer text.
    Post: contains exactly one link, to series_label_url().
    """
    assert lang in _SERIES_TEXT, f"no series footer text for lang {lang!r}"
    info = series_info(config, key, lang)
    text = _SERIES_TEXT[lang].format(
        url=html.escape(series_label_url(config, info["label"]), quote=True),
        label=html.escape(info["label"]),
        blurb=html.escape(info["blurb"]),
    )
    return (f'<div class="hexnut-series" data-series="{html.escape(info["label"], quote=True)}">'
            f"<p><em>{text}</em></p></div>")


def strip_series_footer(post_html: str) -> tuple[str, str | None]:
    """Remove the series footer from fetched HTML.

    Post: (html without footer, series label or None). Keeps the Markdown free of
          generated text, so a republish does not add a second footer.
    """
    m = _SERIES_FOOTER_RE.search(post_html or "")
    if not m:
        return post_html or "", None
    return _SERIES_FOOTER_RE.sub("", post_html, count=1).rstrip(), html.unescape(m.group(1))


def series_key_for_label(config: dict, label: str) -> str | None:
    """Reverse lookup used by fetch: which configured series has this label?"""
    for key, langs in (config.get("series") or {}).items():
        for info in (langs or {}).values():
            if info and info.get("label") == label:
                return key
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
