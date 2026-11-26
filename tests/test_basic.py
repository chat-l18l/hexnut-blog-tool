"""Basic tests for convert and index."""

from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from scripts import blogger, convert, index, llm, utils

def test_load_article_and_labels(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("""---
title: "Test"
slug: "test"
lang: "en"
tags: ["a"]
---
body
""")
    art = utils.load_article(md)
    labels = utils.build_labels(art, "en")
    assert labels == ["a"]  # lang/slug/kw are never public labels

def test_build_index_and_checks(tmp_path, monkeypatch):
    # minimal fake content
    (tmp_path / "content/en").mkdir(parents=True)
    (tmp_path / "content/nl").mkdir(parents=True)
    en = tmp_path / "content/en/ex.md"
    nl = tmp_path / "content/nl/ex.md"
    en.write_text("---\ntitle: T\nslug: ex\nlang: en\n---\n")
    nl.write_text("---\ntitle: T\nslug: ex\nlang: nl\n---\n")

    cfg = {"paths": {"content_dir": str(tmp_path / "content")}}
    idx = index.build_index(cfg)
    assert "ex" in idx
    assert "en" in idx["ex"] and "nl" in idx["ex"]


def test_html_to_md_and_post_to_article():
    html = "<h1>Title</h1><p>Para with <b>bold</b></p>"
    md = convert.html_to_md(html)
    assert "# Title" in md
    assert "**bold**" in md

    post = {
        "id": "987654321",
        "title": "My Fetched Post",
        "content": html,
        "labels": ["lang:en", "tech"],
        "published": "2026-07-26T10:00:00Z",
        "status": "LIVE",
        "url": "https://hexnut.net/p/987"
    }
    art = convert.post_to_article(post)
    assert art["blogger_post_id"] == "987654321"
    assert art["lang"] == "en"
    assert "tech" in art["labels"]
    assert "blogger_published" in art
    assert "# Title" in art["content"]


def test_build_labels_prefers_labels_list(tmp_path):
    md = tmp_path / "fetched.md"
    md.write_text("""---
title: Fetched
slug: fetched
lang: en
labels: ["foo", "lang:en"]
blogger_post_id: "111"
---
body
""")
    art = utils.load_article(md)
    labs = utils.build_labels(art, "en")
    assert labs == ["foo"]  # legacy internal labels are dropped on republish


def test_keywords_do_not_become_labels(tmp_path):
    md = tmp_path / "k.md"
    md.write_text("---\ntitle: K\nslug: k\nlang: nl\ntags: [AI]\nkeywords: [Git]\n---\nbody\n")
    art = utils.load_article(md)
    assert utils.build_labels(art, "nl") == ["AI"]


def test_meta_comment_round_trip():
    from scripts import convert
    html = utils.meta_comment({"slug": "mijn-post"}, "nl") + "\n<p>Hallo</p>"
    post = {"id": "1", "title": "Mijn post", "content": html, "labels": ["AI"]}
    art = convert.post_to_article(post)
    assert art["lang"] == "nl"
    assert art["slug"] == "mijn-post"
    assert "hexnut" not in art["content"]
    assert utils.lang_from_post(post) == "nl"


def test_legacy_lang_label_still_detected():
    post = {"content": "<p>x</p>", "labels": ["AI", "lang:nl", "kw:Git"]}
    assert utils.lang_from_post(post) == "nl"
    from scripts import convert
    assert convert.post_to_article({"id": "2", "title": "Oud", **post})["labels"] == ["AI"]


def test_list_posts_passes_filters_as_request_parameters():
    service = MagicMock()
    request = MagicMock()
    request.execute.return_value = {"items": []}
    service.posts.return_value.list.return_value = request

    with patch("scripts.blogger.get_service", return_value=service):
        blogger.list_posts(
            "blog-id",
            max_results=500,
            status="draft",
            labels="robotics",
            order_by="updated",
            page_token="next",
            view="admin",
        )

    assert service.posts.return_value.list.call_args.kwargs == {
        "blogId": "blog-id",
        "maxResults": 500,
        "orderBy": "UPDATED",
        "fetchBodies": False,
        "view": "ADMIN",
        "status": "DRAFT",
        "labels": "robotics",
        "pageToken": "next",
    }


def test_post_table_keeps_full_blogger_id(capsys):
    post_id = "8145016656587851603"
    blogger.print_post_table([{"id": post_id, "title": "CP70"}])
    assert post_id in capsys.readouterr().out


def test_llm_preserves_fetched_blogger_identity():
    original = {
        "blogger_post_id": "8145016656587851603",
        "blogger_url": "https://www.hexnut.net/2025/08/cp70.html",
        "blogger_published": "2025-08-15T09:10:00Z",
        "title": "Original title",
    }
    candidate = {"slug": "new-title", "title": "Improved title"}

    merged = llm.preserve_blogger_identity(original, candidate)

    assert merged["blogger_post_id"] == "8145016656587851603"
    assert merged["blogger_url"] == original["blogger_url"]
    assert merged["title"] == "Improved title"


def test_new_post_publishes_when_insert_response_has_no_status(monkeypatch):
    article = {
        "title": "New post",
        "content": "Body",
        "labels": ["lang:nl"],
        "source_path": "content/nl/projects/new-post.md",
    }
    publish = MagicMock(return_value={"id": "123", "status": "LIVE"})

    monkeypatch.setattr(blogger, "get_blog_id", lambda config: "blog")
    monkeypatch.setattr(blogger, "insert_post", lambda *args: {"id": "123", "url": "https://example.test"})
    monkeypatch.setattr(blogger, "publish_post", publish)
    monkeypatch.setattr(blogger.utils, "write_post_id_back", lambda *args: None)

    result = blogger.update_article_on_blogger({}, article, draft=False)

    publish.assert_called_once_with("blog", "123")
    assert result["status"] == "LIVE"


def test_mermaid_blocks_are_detected():
    blocks = convert.find_mermaid_blocks("""# Diagram

```mermaid
flowchart LR
    A --> B
```
""")

    assert len(blocks) == 1
    assert blocks[0][1] == "flowchart LR\n    A --> B"


def test_mermaid_renderer_uses_puppeteer_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "puppeteer.json").write_text('{"args": ["--no-sandbox"]}')
    (tmp_path / "node_modules/.bin").mkdir(parents=True)
    (tmp_path / "node_modules/.bin/mmdc").write_text("")
    output = tmp_path / "diagram.svg"

    with patch("scripts.convert.subprocess.run") as run:
        convert.render_mermaid_to_svg("graph TD\n    A --> B", output)

    command = run.call_args.args[0]
    assert "-p" in command
    assert "config/puppeteer.json" in command
    assert command[command.index("-o") + 1] == str(output)


SERIES_CONFIG = {
    "blog": {"public_url": "https://www.hexnut.net/"},
    "series": {"ai-agents": {
        "nl": {"label": "Bouwen met AI-agents", "blurb": "projecten die ik samen met AI-agents bouw"},
        "en": {"label": "Building with AI agents", "blurb": "projects I build together with AI agents"},
    }},
}


def test_series_footer_links_to_label_page():
    footer = utils.series_footer_html(SERIES_CONFIG, "ai-agents", "nl")
    assert 'data-series="Bouwen met AI-agents"' in footer
    assert 'href="https://www.hexnut.net/search/label/Bouwen%20met%20AI-agents"' in footer
    assert footer.count("<a ") == 1


def test_series_footer_matches_live_posts():
    # Exact markup that is live on hexnut.net; keeps tool output and live posts identical.
    expected = ('<div class="hexnut-series" data-series="Building with AI agents"><p><em>This article is part of '
                'the series <a href="https://www.hexnut.net/search/label/Building%20with%20AI%20agents">Building '
                'with AI agents</a>: projects I build together with AI agents. That link takes you to every part '
                'of the series, including new ones.</em></p></div>')
    assert utils.series_footer_html(SERIES_CONFIG, "ai-agents", "en") == expected


def test_unknown_series_fails_fast():
    import pytest
    with pytest.raises(AssertionError):
        utils.series_footer_html(SERIES_CONFIG, "nope", "nl")


def test_fetch_strips_series_footer_and_restores_key():
    from scripts import convert
    html = (utils.meta_comment({"slug": "x"}, "nl") + "\n<p>Tekst</p>\n"
            + utils.series_footer_html(SERIES_CONFIG, "ai-agents", "nl"))
    post = {"id": "3", "title": "X", "content": html, "labels": ["AI", "Bouwen met AI-agents"]}
    art = convert.post_to_article(post, SERIES_CONFIG)
    assert art["series"] == "ai-agents"
    assert "hoort bij de serie" not in art["content"]
    assert "Tekst" in art["content"]
