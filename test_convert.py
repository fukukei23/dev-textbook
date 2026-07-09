"""convert.py のテスト — リンク書き換え・HTML生成・章スキャン."""

import html
import re
from unittest.mock import patch

import pytest

from convert import (
    CHAPTER_MAP,
    CHAPTER_TEMPLATE,
    INDEX_TEMPLATE,
    MERMAID_DIAGRAMS,
    OUTPUT_DIR,
    SOURCE_DIR,
    _extract_desc_from_h1,
    _extract_title_from_h1,
    _filename_to_slug,
    build_chapter_map,
    convert_md_to_html,
    enhance_html,
    filter_sections,
    group_chapters_by_category,
    inject_mermaid,
    rewrite_links,
)


# === 1. ファイル名 → slug 変換 ===

class TestFilenameToSlug:

    def test_basic_ascii(self):
        assert _filename_to_slug("13_glm-rate-proxy.md") == "13-glm-rate-proxy"

    def test_leading_zeros(self):
        assert _filename_to_slug("00_overview.md") == "00-overview"

    def test_japanese_stripped(self):
        slug = _filename_to_slug("01_ディレクトリ設計.md")
        assert "01" in slug
        assert not any(c > "\x7f" for c in slug), "日本語文字がslugに残っている"

    def test_no_trailing_hyphen(self):
        slug = _filename_to_slug("05_記録・ドキュメント.md")
        assert not slug.endswith("-")

    def test_no_consecutive_hyphens(self):
        slug = _filename_to_slug("06_開発手法カタログ.md")
        assert "--" not in slug


# === 2. H1からタイトル・説明を抽出 ===

class TestExtractFromH1:

    def test_title_strips_number(self):
        md = "# 01 ディレクトリ設計 — vault階層構造と責務分離\n"
        assert _extract_title_from_h1(md) == "ディレクトリ設計"

    def test_title_no_number(self):
        md = "# SSOTとは\n"
        assert _extract_title_from_h1(md) == "SSOTとは"

    def test_desc_after_dash(self):
        md = "# 02 LLMルーティング — 複数LLMの使い分け設計\n"
        assert _extract_desc_from_h1(md) == "複数LLMの使い分け設計"

    def test_desc_empty_when_no_dash(self):
        md = "# タイトルのみ\n"
        assert _extract_desc_from_h1(md) == ""

    def test_no_h1_returns_empty(self):
        assert _extract_title_from_h1("## セクション\nテキスト") == ""


# === 3. セクションフィルタリング ===

class TestFilterSections:

    def test_preserves_normal_content(self):
        md = "## コマンド一覧\n`/clear` でリセット\n### 使い方\n説明"
        result = filter_sections(md)
        assert "## コマンド一覧" in result
        assert "`/clear`" in result

    def test_removes_anata_no_kankyo(self):
        result = filter_sections("path: あなたの環境では~/foo")
        assert "あなたの環境では" not in result

    def test_removes_anata_no_kankyo_colon(self):
        result = filter_sections("あなたの環境: /home/xxx")
        assert "あなたの環境:" not in result

    def test_inline_replacements_applied(self):
        from convert import INLINE_REPLACEMENTS
        if not INLINE_REPLACEMENTS:
            pytest.skip("INLINE_REPLACEMENTS is empty")
        pattern, replacement = INLINE_REPLACEMENTS[0]
        text = re.sub(pattern, replacement, "test")
        assert isinstance(text, str)


# === 4. Markdown → HTML変換 ===

class TestConvertMdToHtml:

    def test_heading_converted(self):
        html = convert_md_to_html("## テスト見出し")
        assert "<h2>" in html
        assert "テスト見出し" in html

    def test_code_block_converted(self):
        html = convert_md_to_html("```\ncode here\n```")
        assert "<code>" in html

    def test_table_converted(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = convert_md_to_html(md)
        assert "<table>" in html
        assert "<td>" in html

    def test_bold_converted(self):
        html = convert_md_to_html("**太字**テキスト")
        assert "<strong>" in html

    def test_raw_html_is_escaped_not_rendered(self):
        """source の生 HTML は出力でエスケープされ、要素として解釈されない."""
        html = convert_md_to_html("<script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_inline_html_in_text_is_escaped(self):
        html = convert_md_to_html("本文 <iframe src=x> 末尾")
        assert "<iframe" not in html
        assert "&lt;iframe" in html


# === 4.5 テンプレートautoescape（XSS回帰テスト） ===

class TestTemplateAutoEscape:

    def _chapter_payload(self):
        return {
            "title": "<script>alert(1)</script>",
            "slug": "00-x",
            "current_slug": "00-x",
            "content": "<p>OK</p>",
            "chapters": [
                {
                    "slug": "00-x",
                    "number": "00",
                    "title": "<b>t</b>",
                    "icon": "🎵",
                    "desc": "<img src=x onerror=alert(1)>",
                    "filename": "00.md",
                }
            ],
            "prev_ch": None,
            "next_ch": None,
            "version": "1",
            "build_date": "2026.01.01",
        }

    def test_chapter_template_escapes_title_and_desc(self):
        out = CHAPTER_TEMPLATE.render(**self._chapter_payload())
        assert "<script>alert(1)</script>" not in out
        assert "<img src=x onerror=alert(1)>" not in out
        assert "&lt;script&gt;" in out

    def test_chapter_template_keeps_safe_content_html(self):
        out = CHAPTER_TEMPLATE.render(**self._chapter_payload())
        assert "<p>OK</p>" in out  # content|safe で本文HTMLは保持

    def test_index_template_escapes_desc(self):
        # INDEX_TEMPLATE は categories(group_chapters_by_category の結果)を受け取る
        # (convert.py:583 の実使用署名に合わせる。chapters 直渡しでは描画されない)
        categories = group_chapters_by_category(self._chapter_payload()["chapters"])
        out = INDEX_TEMPLATE.render(
            categories=categories,
            version="1",
            build_date="2026.01.01",
        )
        assert "<img src=x onerror=alert(1)>" not in out
        assert "&lt;img" in out


# === 5. Mermaid注入 ===

class TestMermaidInjection:

    def test_no_injection_when_diagrams_empty(self):
        html = "<h2>テスト</h2><p>本文</p>"
        result = inject_mermaid(html, "00_概要.md")
        assert "mermaid" not in result

    def test_no_injection_for_unknown_file(self):
        html = "<h2>アーキテクチャ</h2>"
        result = inject_mermaid(html, "99_存在しない.md")
        assert "mermaid-wrapper" not in result

    def test_injection_when_diagram_exists(self):
        from convert import MERMAID_DIAGRAMS as MD
        if not MD:
            pytest.skip("MERMAID_DIAGRAMS is empty — no diagrams to test")
        filename = next(iter(MD))
        heading, code = MD[filename][0]
        heading_text = heading.replace("## ", "").strip()
        html = f"<h2>{heading_text}</h2><p>text</p>"
        result = inject_mermaid(html, filename)
        assert "mermaid-wrapper" in result


# === 6. リンク書き換え ===

class TestRewriteLinks:

    def test_md_link_to_html(self):
        html = '<a href="00_はじめに.md">link</a>'
        result = rewrite_links(html)
        assert 'href="00-intro.html"' in result
        assert ".md" not in result

    def test_md_link_with_anchor(self):
        html = '<a href="01_CI-CD.md#section">link</a>'
        result = rewrite_links(html)
        assert "01-ci-cd.html#section" in result

    def test_unknown_md_link_to_hash(self):
        html = '<a href="unknown_file.md">link</a>'
        result = rewrite_links(html)
        assert 'href="#"' in result

    def test_relative_links_removed(self):
        html = '<a href="../other/file.md">link</a>'
        result = rewrite_links(html)
        assert 'href="#"' in result

    def test_decisions_links_removed(self):
        html = '<a href="01_DECISIONS/project/2026-01-01_foo.md">link</a>'
        result = rewrite_links(html)
        assert 'href="#"' in result

    def test_all_chapter_slugs_valid(self):
        html = "".join(f'<a href="{f}"></a>' for f in CHAPTER_MAP)
        result = rewrite_links(html)
        for info in CHAPTER_MAP.values():
            assert f'{info["slug"]}.html' in result

    def test_custom_chapter_map(self):
        custom_map = {"test.md": {"slug": "test-slug"}}
        html = '<a href="test.md">link</a>'
        result = rewrite_links(html, chapter_map=custom_map)
        assert 'href="test-slug.html"' in result


# === 7. HTML装飾 ===

class TestEnhanceHtml:

    def test_table_wrapped(self):
        html = "<table><tr><td>cell</td></tr></table>"
        result = enhance_html(html)
        assert 'class="table-wrapper"' in result
        assert "<table>" in result

    def test_blockquote_to_callout(self):
        html = "<blockquote>\n<p>補足情報</p>\n</blockquote>"
        result = enhance_html(html)
        assert "callout" in result
        assert "<blockquote>" not in result

    def test_warn_callout_for_warning(self):
        html = "<blockquote>\n<p>⚠ 注意事項</p>\n</blockquote>"
        result = enhance_html(html)
        assert "callout-warn" in result

    def test_tip_callout_for_tip(self):
        html = "<blockquote>\n<p>💡 Tip: 良い方法</p>\n</blockquote>"
        result = enhance_html(html)
        assert "callout-tip" in result

    def test_danger_callout_for_important(self):
        html = "<blockquote>\n<p>重要: この手順を守る</p>\n</blockquote>"
        result = enhance_html(html)
        assert "callout-danger" in result


# === 8. build_chapter_map ===

class TestBuildChapterMap:

    def test_contains_all_manual_chapters(self):
        cmap = build_chapter_map()
        for filename in CHAPTER_MAP:
            assert filename in cmap

    def test_manual_chapter_data_preserved(self):
        cmap = build_chapter_map()
        assert cmap["00_はじめに.md"]["slug"] == "00-intro"
        assert cmap["00_はじめに.md"]["title"] == "はじめに"

    def test_skips_underscore_files(self):
        cmap = build_chapter_map()
        for filename in cmap:
            assert not filename.startswith("_")

    def test_all_entries_have_required_keys(self):
        cmap = build_chapter_map()
        for filename, info in cmap.items():
            for key in ("slug", "title", "icon", "desc"):
                assert key in info, f"{filename} missing key: {key}"


# === 9. ビルド整合性 ===

class TestBuildIntegrity:
    """生成済みHTMLの構造チェック（convert.py 実行済みを前提）."""

    @pytest.fixture(autouse=True)
    def _build(self):
        """バージョンをバンプせずにビルドを実行。"""
        import convert
        with patch.object(convert, "get_build_info", return_value=("TEST", "2026.01.01")):
            convert.main()

    def test_all_chapters_generated(self):
        for info in CHAPTER_MAP.values():
            path = OUTPUT_DIR / "chapters" / f'{info["slug"]}.html'
            assert path.exists(), f"{info['slug']}.html が生成されていない"

    def test_index_generated(self):
        assert (OUTPUT_DIR / "index.html").exists()

    def test_all_chapters_have_nav(self):
        for html_file in sorted((OUTPUT_DIR / "chapters").glob("*.html")):
            content = html_file.read_text(encoding="utf-8")
            assert "chapter-nav-bottom" in content
            assert "sidebar" in content

    def test_all_chapters_have_ogp(self):
        for html_file in sorted((OUTPUT_DIR / "chapters").glob("*.html")):
            content = html_file.read_text(encoding="utf-8")
            assert "og:title" in content
            assert "og:image" in content
            assert "ogp.png" in content

    def test_no_broken_md_links(self):
        for html_file in sorted((OUTPUT_DIR / "chapters").glob("*.html")):
            content = html_file.read_text(encoding="utf-8")
            md_hrefs = re.findall(r'href="[^"]*\.md[^"]*"', content)
            assert len(md_hrefs) == 0, (
                f".md href が残っている in {html_file.name}: {md_hrefs}"
            )

    def test_index_has_all_chapter_cards(self):
        index = (OUTPUT_DIR / "index.html").read_text(encoding="utf-8")
        for info in CHAPTER_MAP.values():
            assert info["slug"] in index

    def test_chapter_titles_in_index(self):
        index = (OUTPUT_DIR / "index.html").read_text(encoding="utf-8")
        for info in CHAPTER_MAP.values():
            # タイトルはHTML出力時にエスケープされる（"&" → "&amp;" 等）。
            # "&" を含むタイトル（"Git & GitHub"）に対応するためエスケープ済み文字列で比較。
            assert html.escape(info["title"]) in index

    def test_mermaid_rendered_when_defined(self):
        for md_name in MERMAID_DIAGRAMS:
            if md_name not in CHAPTER_MAP:
                continue
            slug = CHAPTER_MAP[md_name]["slug"]
            html_file = OUTPUT_DIR / "chapters" / f"{slug}.html"
            if html_file.exists():
                content = html_file.read_text(encoding="utf-8")
                assert "mermaid" in content.lower()
