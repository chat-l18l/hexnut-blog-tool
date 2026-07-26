"""LLM assistance layer (Grok / xAI first).

Why: Offload writing, translation, reference suggestions and style to LLM while keeping human in control.
What: Simple wrapper around OpenAI-compatible client for xAI.
Pre:  XAI_API_KEY in env, article file exists.
Post: Updated .md file written (user must review and commit).
"""

import os
from pathlib import Path
import frontmatter
from openai import OpenAI
from . import utils

PROTECTED_BLOGGER_FIELDS = (
    "blogger_post_id",
    "blogger_url",
    "blogger_published",
    "blogger_status",
    "blogger_location",
)

def get_client() -> OpenAI:
    # xAI uses OpenAI compatible endpoint
    api_key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY (or GROK_API_KEY) not set in environment")
    base_url = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
    return OpenAI(api_key=api_key, base_url=base_url)

SYSTEM_PROMPT = """You are a helpful technical writing assistant for embedded/robotics/DSP projects.
Keep language clear, simple and precise. Avoid hype.
Always produce valid Markdown with YAML frontmatter.
When asked to translate, keep technical terms accurate.
Suggest 2-4 good references when the article mentions concepts, datasheets or libraries.
Output ONLY the full updated Markdown file.
"""


def preserve_blogger_identity(original: dict, candidate: dict) -> dict:
    """Keep the remote identity when an LLM rewrites frontmatter.

    Why: A fetched post must always retain its Blogger ID, otherwise publish can
    insert a duplicate instead of updating the original statistics-bearing post.
    """
    for key in PROTECTED_BLOGGER_FIELDS:
        if key in original:
            candidate[key] = original[key]
    return candidate

def prepare_article(path: Path, lang: str | None = None):
    """Call LLM to refine or translate the article."""
    article = utils.load_article(path)
    original_post = frontmatter.load(path)
    original = frontmatter.dumps(original_post)
    current_lang = article.get("lang", "en")

    target_lang = lang or current_lang
    prompt = f"""Improve and complete this technical article.
Current language: {current_lang}
Target language: {target_lang}

Requirements:
- Keep or improve the existing frontmatter (add missing title_{target_lang} if needed)
- Add or improve Mermaid diagrams where they help understanding
- Make sure there is a references list (use the references frontmatter field if present)
- Suggest cross references using [[slug]] syntax if relevant
- Output the complete updated article

Here is the current article:

{original}
"""

    client = get_client()
    model = os.getenv("LLM_MODEL", "grok-beta")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    new_md = resp.choices[0].message.content.strip()

    # Basic safety: only write if it looks like markdown with frontmatter.
    # Reapply immutable Blogger identity even if the model omitted it.
    if new_md.startswith("---") and "slug:" in new_md:
        candidate_post = frontmatter.loads(new_md)
        metadata = preserve_blogger_identity(dict(original_post.metadata), dict(candidate_post.metadata))
        utils.save_article(path, metadata, candidate_post.content)
        print(f"LLM updated article written to {path}")
        print("Please review the changes before committing.")
    else:
        print("LLM response did not look like a valid article. Not written.")
        print("Response preview (first 800 chars):")
        print(new_md[:800])
