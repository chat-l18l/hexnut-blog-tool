"""Article index, cross-reference resolution, and validation.

Why: Enable reliable links between articles and bilingual pairing.
What: Scans content tree, builds simple index by slug+lang, provides check + (future) link rewriting.
"""

from pathlib import Path
from collections import defaultdict
from . import utils

def build_index(config: dict) -> dict:
    """Return {slug: {'en': path, 'nl': path}} like structure."""
    content_dir = Path(config.get("paths", {}).get("content_dir", "content"))
    index = defaultdict(dict)
    for md in content_dir.rglob("*.md"):
        art = utils.load_article(md)
        slug = art.get("slug")
        lang = art.get("lang", "en")
        if slug:
            index[slug][lang] = str(md)
    return dict(index)

def run_checks():
    config = utils.load_config()
    idx = build_index(config)
    errors = []

    for slug, langs in idx.items():
        if "en" not in langs or "nl" not in langs:
            errors.append(f"Missing language for slug '{slug}': has {list(langs.keys())}")

    # Check frontmatter basics
    content_dir = Path(config.get("paths", {}).get("content_dir", "content"))
    for md in content_dir.rglob("*.md"):
        art = utils.load_article(md)
        for key in ("title", "slug", "lang"):
            if key not in art:
                errors.append(f"{md}: missing required frontmatter key '{key}'")

    if errors:
        print("CHECK FAILED:")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)
    else:
        print("All checks passed. Articles look good.")
        print(f"Found {len(idx)} unique slugs.")
