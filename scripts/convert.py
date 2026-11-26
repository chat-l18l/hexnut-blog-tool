"""Convert Markdown articles to Blogger-ready HTML.

Why: All transformation (Mermaid, images, references, cross-refs, bilingual links) happens here deterministically.
What: Reads .md, renders diagrams, rewrites asset paths, appends References, produces HTML.
Pre:  Valid frontmatter, mmdc available in PATH, assets exist.
Post: Article dict extended with 'html', 'labels', 'rendered' info. No side effects unless dry_run=False.
"""

import subprocess
import tempfile
import re
from pathlib import Path
from typing import Optional
import markdown
from jinja2 import Environment, FileSystemLoader
import markdownify
from . import utils
from .index import build_index

PUPPETEER_CONFIG_PATH = Path("config/puppeteer.json")

def find_mermaid_blocks(text: str):
    """Return list of (full_match, diagram_code)."""
    pattern = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)
    return [(m.group(0), m.group(1).strip()) for m in pattern.finditer(text)]

def render_mermaid_to_svg(diagram: str, out_path: Path) -> Path:
    """Render one Mermaid diagram to SVG with the local Mermaid CLI.

    Why: Blogger does not execute Mermaid JavaScript, so every diagram must be
    converted to an image before publishing.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as tmp:
        tmp.write(diagram)
        tmp_path = Path(tmp.name)
    try:
        # Prefer the project-local CLI for reproducible builds, then PATH mmdc.
        local_mmdc = Path("node_modules/.bin/mmdc")
        candidates = []
        if local_mmdc.exists():
            candidates.append([str(local_mmdc)])
        candidates.append(["mmdc"])

        errors = []
        for base_cmd in candidates:
            cmd = base_cmd + ["-i", str(tmp_path), "-o", str(out_path), "--quiet"]
            if PUPPETEER_CONFIG_PATH.exists():
                cmd.extend(["-p", str(PUPPETEER_CONFIG_PATH)])
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
                return out_path
            except FileNotFoundError:
                errors.append(f"Command not found: {base_cmd[0]}")
            except subprocess.TimeoutExpired:
                errors.append(f"Timed out: {' '.join(cmd)}")
            except subprocess.CalledProcessError as error:
                errors.append(error.stderr.strip() or f"Command failed: {' '.join(cmd)}")
        raise RuntimeError("Mermaid rendering failed:\n" + "\n".join(errors))
    finally:
        tmp_path.unlink(missing_ok=True)

def rewrite_images(md_content: str, config: dict, article_dir: Path) -> str:
    """Rewrite local image paths to GitHub raw URLs."""
    def replacer(match):
        alt = match.group(1)
        src = match.group(2)
        if src.startswith(("http", "data:")):
            return match.group(0)
        # resolve relative to article or assets
        rel = src
        if not rel.startswith("assets/"):
            # assume relative like ../assets or just filename -> put under assets/images
            rel = f"assets/images/{Path(src).name}"
        full = utils.github_raw_image_url(config, rel)
        return f"![{alt}]({full})"
    return re.sub(r"!\[(.*?)\]\((.*?)\)", replacer, md_content)

def append_references(md_content: str, refs: list) -> str:
    if not refs:
        return md_content
    section = "\n\n## References / Bronnen\n\n"
    for i, ref in enumerate(refs, 1):
        section += f"{i}. [{ref.get('title', ref.get('url'))}]({ref.get('url')})"
        if ref.get("note"):
            section += f" — {ref['note']}"
        section += "\n"
    return md_content + section

def md_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=["extra", "codehilite", "toc"])

def process_article(md_path: Path, config: dict, dry_run: bool = False) -> dict:
    """Main entry for one article. Returns enriched article dict."""
    article = utils.load_article(md_path)
    lang = article.get("lang", "en")

    # 1. Rewrite images
    md = rewrite_images(article["content"], config, md_path.parent)

    # 2. Render mermaid blocks
    blocks = find_mermaid_blocks(md)
    rendered_diagrams = []
    for diagram_number, (full_block, code) in enumerate(blocks, 1):
        # Generated SVGs must be in tracked assets, not ignored rendered/.
        # Otherwise the raw GitHub URL embedded in Blogger would be broken.
        slug = article.get("slug", md_path.stem)
        out_path = Path("assets") / "diagrams" / lang / f"{slug}-diag-{diagram_number}.svg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path = render_mermaid_to_svg(code, out_path)
        # For Blogger we use GitHub raw of the tracked SVG asset.
        svg_raw = utils.github_raw_image_url(config, str(svg_path))
        img_tag = f'<img src="{svg_raw}" alt="diagram" style="max-width:100%;">'
        md = md.replace(full_block, img_tag)
        rendered_diagrams.append(str(svg_path))

    # 3. Append references
    refs = article.get("references", [])
    md = append_references(md, refs)

    # 4. Convert to HTML
    html_body = md_to_html(md)

    # 5. Wrap in template for preview
    env = Environment(loader=FileSystemLoader("templates"))
    tmpl = env.get_template("post.html.j2")
    full_html = tmpl.render(title=article.get("title", ""), content=html_body)

    article["html"] = utils.meta_comment(article, lang) + "\n" + html_body   # the part we send to Blogger
    article["full_preview_html"] = full_html
    article["labels"] = utils.build_labels(article, lang)
    article["rendered_diagrams"] = rendered_diagrams

    # Write preview if not dry
    if not dry_run:
        preview_path = Path("rendered") / (md_path.stem + ".preview.html")
        preview_path.parent.mkdir(exist_ok=True)
        preview_path.write_text(full_html, encoding="utf-8")

    return article

def build_all(dry_run: bool = False):
    """Process all articles."""
    config = utils.load_config()
    index = build_index(config)  # for future cross-ref use
    content_dir = Path(config.get("paths", {}).get("content_dir", "content"))

    articles = []
    for md in content_dir.rglob("*.md"):
        print(f"Processing: {md}")
        art = process_article(md, config, dry_run=dry_run)
        articles.append(art)

    print(f"Built {len(articles)} articles.")
    if not dry_run:
        print("Previews written to rendered/")

    # TODO: use index for cross-ref replacement in a second pass
    return articles


# --- Reverse conversion (Blogger post -> local Markdown) ---

def html_to_md(html: str) -> str:
    """Convert Blogger HTML content to clean Markdown.
    Why: Enable offline editing of fetched posts.
    Uses markdownify for structure preservation (headings, lists, links, images, code).
    """
    if not html:
        return ""
    # markdownify converts HTML to MD; strip some noise
    md = markdownify.markdownify(html, heading_style="ATX", bullets="*")
    # Normalize some common Blogger artifacts
    md = re.sub(r'\n{3,}', '\n\n', md).strip()
    return md


def post_to_article(post: dict) -> dict:
    """Convert a raw Blogger post dict into a dict ready for local MD + frontmatter.
    Includes blogger_* fields for ID preservation and editable metadata.
    """
    content_html = post.get("content", "") or ""
    marker = utils.parse_meta_comment(content_html)
    md_body = html_to_md(utils.strip_meta_comment(content_html))

    meta = {
        "title": post.get("title", "Untitled"),
        "blogger_post_id": post.get("id"),
        "blogger_url": post.get("url", ""),
        "labels": post.get("labels", []) or [],
    }

    if post.get("published"):
        meta["blogger_published"] = post["published"]
        meta["published"] = post["published"]  # editable

    if post.get("status"):
        meta["blogger_status"] = post["status"]

    # Keep original content reference if needed
    meta["_original_html"] = content_html  # not written to frontmatter by default

    # Derive slug if not present (simple)
    if "slug" not in meta:
        slug = (post.get("title") or post.get("id", "")).lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
        meta["slug"] = slug or post.get("id", "post")

    # lang/slug from the invisible marker, else legacy lang: labels
    if marker.get("slug"):
        meta["slug"] = marker["slug"]
    lang = utils.lang_from_post(post)
    if lang:
        meta["lang"] = lang
    meta.setdefault("lang", "en")
    # internal labels are not public tags; never carry them back into frontmatter
    meta["labels"] = [l for l in meta["labels"] if not l.startswith(utils.INTERNAL_LABEL_PREFIXES)]

    # title_nl if the post is Dutch (leave for user)
    if meta["lang"] == "nl":
        meta.setdefault("title_nl", meta["title"])

    article = meta.copy()
    article["content"] = md_body
    # source_path will be set by caller
    return article


def build_article_from_post(post: dict, target_path: Path, config: dict) -> dict:
    """High level: take fetched post, write it as local MD file with rich meta.
    Returns the article dict.
    """
    article = post_to_article(post)
    # Write using utils (preserves other frontmatter if file existed)
    content = article.pop("content")
    # merge any existing on disk
    if target_path.exists():
        existing = utils.load_article(target_path)
        # keep user content? no, we are overwriting with fetched, but preserve non-blogger keys if wanted
        for k in list(existing.keys()):
            if not k.startswith("blogger_") and k not in ("content", "source_path"):
                article.setdefault(k, existing[k])
    utils.save_article(target_path, article, content)
    # Now write the blogger meta cleanly (adds id etc.)
    utils.write_blogger_meta(str(target_path), post)
    return {**article, "content": content, "source_path": str(target_path)}
