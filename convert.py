#!/usr/bin/env python3
"""開発の常識・作法: Markdown → モバイル最適化HTML変換スクリプト."""

import re
import unicodedata
from datetime import date
from pathlib import Path

from jinja2 import Template
from markdown_it import MarkdownIt

# --- 設定 ---

SOURCE_DIR = Path(__file__).parent / "source"
OUTPUT_DIR = Path(__file__).parent / "docs"
VERSION_FILE = Path(__file__).parent / "VERSION"


# --- バージョン管理 ---

def _read_version() -> str:
    """VERSIONファイルを読み込む。なければ '1.0' を返す。"""
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "1.0"


def _bump_version(version: str) -> str:
    """マイナーバージョンをインクリメント: '1.3' → '1.4'"""
    parts = version.split(".")
    major = parts[0]
    minor = int(parts[1]) if len(parts) > 1 else 0
    return f"{major}.{minor + 1}"


def get_build_info() -> tuple[str, str]:
    """(version_str, date_str) を返す。ビルドごとにマイナーをインクリメント。"""
    current = _read_version()
    new_version = _bump_version(current)
    VERSION_FILE.write_text(new_version + "\n", encoding="utf-8")
    today = date.today().strftime("%Y.%m.%d")
    return new_version, today

# 既存章の手動定義（第2章完成フェーズ: 00 はじめに + 01 CI/CD + 02 Git & GitHub。03-14は追加時に追記・自動スキャンで対応）
CHAPTER_MAP = {
    "00_はじめに.md": {"slug": "00-intro", "title": "はじめに", "icon": "📚", "desc": "この教科書の対象読者・使い方・全14章の全体構成"},
    "01_CI-CD.md": {"slug": "01-ci-cd", "title": "CI/CD", "icon": "🔄", "desc": "継続的インテグレーション・緑が証明すること/しないこと・デプロイ・ロールバック"},
    "02_Git-GitHub.md": {"slug": "02-git-github", "title": "Git & GitHub", "icon": "🌿", "desc": "変更履歴の管理・commit/push/pullの違い・ブランチ・Pull Request・コンフリクト解決・コミットメッセージ作法"},
}


# --- 自動スキャン ---

def _filename_to_slug(filename: str) -> str:
    """ファイル名からslugを生成: '13_glm-rate-proxy.md' → '13-glm-rate-proxy'"""
    stem = Path(filename).stem  # 拡張子除去
    # 先頭の数字+区切り文字を抽出: "13_foo" → "13-foo", "00_早見表" → "00-cheatsheet相当"
    # アンダースコアをハイフンに、日本語はASCIIに変換できないのでそのまま残す
    slug = stem.replace("_", "-", 1)  # 最初の _ のみハイフン化
    # 残りの _ もハイフン化
    slug = slug.replace("_", "-")
    # ASCII以外の文字を除去してslugを作る
    ascii_slug = ""
    for ch in slug:
        if ch.isascii():
            ascii_slug += ch.lower()
        elif ch == "-":
            ascii_slug += "-"
    # 連続ハイフン・末尾ハイフンを整理
    ascii_slug = re.sub(r"-+", "-", ascii_slug).strip("-")
    return ascii_slug or slug


def _extract_frontmatter(text: str) -> tuple[dict, str]:
    """YAMLフロントマターを抽出。なければ空dictとテキストをそのまま返す。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, body


def _extract_title_from_h1(text: str) -> str:
    """H1ヘッダーからタイトルを抽出。'# 13 GLM Rate Proxy — ...' → 'GLM Rate Proxy'"""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            # 番号プレフィックスを除去: "13 GLM Rate Proxy" → "GLM Rate Proxy"
            title = re.sub(r"^\d+\s+", "", title)
            # ダッシュ以降の説明を除去: "GLM Rate Proxy — 説明" → "GLM Rate Proxy"
            title = re.split(r"\s+[—–-]\s+", title)[0].strip()
            return title
    return ""


def _extract_desc_from_h1(text: str) -> str:
    """H1ヘッダーのダッシュ以降を説明として抽出。"""
    for line in text.splitlines():
        if line.startswith("# "):
            parts = re.split(r"\s+[—–-]\s+", line[2:].strip(), maxsplit=1)
            if len(parts) > 1:
                return parts[1].strip()
    return ""


def build_chapter_map() -> dict:
    """source/ をスキャンして完全なCHAPTER_MAPを構築。
    CHAPTER_MAPに未登録のファイルは自動検出して追加する。"""
    result = dict(CHAPTER_MAP)

    for md_file in sorted(SOURCE_DIR.glob("*.md")):
        filename = md_file.name
        if filename.startswith("_"):
            continue  # _README.md等は除外
        if filename in result:
            continue  # 既登録はスキップ

        text = md_file.read_text(encoding="utf-8")
        meta, body = _extract_frontmatter(text)

        title = meta.get("title") or _extract_title_from_h1(text) or Path(filename).stem
        desc = meta.get("card_desc") or meta.get("desc") or _extract_desc_from_h1(text) or title
        icon = meta.get("icon", "📄")
        slug = meta.get("slug") or _filename_to_slug(filename)

        result[filename] = {"slug": slug, "title": title, "icon": icon, "desc": desc}
        print(f"AUTO: {filename} → {slug} ({title})")

    return result

REMOVE_SECTIONS: list[str] = []
REMOVE_PATTERNS: list[str] = []
INLINE_REPLACEMENTS: list[tuple[str, str]] = []
TABLE_COL_SANITIZE: list[tuple[str, str]] = []

MERMAID_DIAGRAMS: dict[str, list[tuple[str, str]]] = {}

# --- HTMLテンプレート ---

CHAPTER_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="ja" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — 開発の常識・作法</title>
    <meta name="description" content="{{ title }} — 開発の常識・作法（開発現場の常識をまとめた統合教科書）">
    <meta property="og:title" content="{{ title }} — 開発の常識・作法">
    <meta property="og:description" content="{{ title }} — 開発の常識・作法（開発現場の常識をまとめた統合教科書）">
    <meta property="og:type" content="article">
    <meta property="og:url" content="https://fukukei23.github.io/dev-textbook/chapters/{{ slug }}.html">
    <meta property="og:image" content="https://fukukei23.github.io/dev-textbook/assets/ogp.png">
    <meta name="twitter:card" content="summary_large_image">
    <link rel="stylesheet" href="../assets/style.css">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
</head>
<body>
    <header class="site-header">
        <button class="menu-toggle" aria-label="メニュー" id="menuToggle">
            <span></span><span></span><span></span>
        </button>
        <a href="../index.html" class="site-title">📚 開発の常識・作法</a>
        <button class="theme-toggle" id="themeToggle" aria-label="テーマ切替">
            <span class="icon-light">☀️</span>
            <span class="icon-dark">🌙</span>
        </button>
    </header>

    <nav class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <a href="../index.html">🏠 ホーム</a>
        </div>
        {% for ch in chapters %}
        <a href="{{ ch.slug }}.html"
           class="sidebar-link{{ ' active' if ch.slug == current_slug }}">
            <span class="sidebar-icon">{{ ch.icon }}</span>
            {{ ch.title }}
        </a>
        {% endfor %}
    </nav>
    <div class="sidebar-overlay" id="sidebarOverlay"></div>

    <main class="content">
        <div class="chapter-nav-top">
            {% if prev_ch %}
            <a href="{{ prev_ch.slug }}.html" class="nav-prev">← {{ prev_ch.title }}</a>
            {% endif %}
            {% if next_ch %}
            <a href="{{ next_ch.slug }}.html" class="nav-next">{{ next_ch.title }} →</a>
            {% endif %}
        </div>

        <article class="chapter-body">
            {{ content|safe }}
        </article>

        <nav class="chapter-nav-bottom">
            {% if prev_ch %}
            <a href="{{ prev_ch.slug }}.html" class="nav-card prev">
                <span class="nav-label">← 前の章</span>
                <span class="nav-title">{{ prev_ch.icon }} {{ prev_ch.title }}</span>
            </a>
            {% endif %}
            {% if next_ch %}
            <a href="{{ next_ch.slug }}.html" class="nav-card next">
                <span class="nav-label">次の章 →</span>
                <span class="nav-title">{{ next_ch.icon }} {{ next_ch.title }}</span>
            </a>
            {% endif %}
        </nav>
    </main>

    <footer class="site-footer">
        <p>開発の常識・作法 — <a href="https://github.com/fukukei23/dev-textbook">GitHub</a>
         · <a href="https://fukukei23.github.io/claude-code-guide/">Claude Code Guide</a>
         · <a href="https://fukukei23.github.io/guides/">技術ガイド集</a>
         · <a href="https://fukukei23.github.io/">fukukei23</a></p>
        <p class="site-version">v{{ version }} · {{ build_date }}</p>
    </footer>

    <script src="../assets/script.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({
            startOnLoad: true,
            theme: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default',
            themeVariables: { fontSize: '14px' }
        });
    </script>
</body>
</html>
""", autoescape=True)

INDEX_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="ja" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>開発の常識・作法</title>
    <meta name="description" content="非IT出身でも開発者と話が通じる・面接で響く、開発現場の常識をまとめた統合教科書">
    <meta property="og:title" content="開発の常識・作法">
    <meta property="og:description" content="非IT出身でも開発者と話が通じる・面接で響く、開発現場の常識をまとめた統合教科書">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://fukukei23.github.io/dev-textbook/">
    <meta property="og:image" content="https://fukukei23.github.io/dev-textbook/assets/ogp.png">
    <meta name="twitter:card" content="summary_large_image">
    <link rel="stylesheet" href="assets/style.css">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
</head>
<body class="index-page">
    <header class="site-header">
        <span class="site-title">📚 開発の常識・作法</span>
        <button class="theme-toggle" id="themeToggle" aria-label="テーマ切替">
            <span class="icon-light">☀️</span>
            <span class="icon-dark">🌙</span>
        </button>
    </header>

    <main class="content">
        <section class="hero">
            <h1>開発の常識・作法</h1>
            <p>AIと人間が協働するための<br>Single Source of Truth 設計・運用ガイド</p>
        </section>

        {% for cat in categories %}
        <section class="chapter-category">
            <h2 class="chapter-category-heading">{{ cat.name }}</h2>
            <div class="chapter-grid">
                {% for ch in cat.chapters %}
                <a href="chapters/{{ ch.slug }}.html" class="chapter-card">
                    <div class="card-icon">{{ ch.icon }}</div>
                    <div class="card-number">第{{ ch.number }}章</div>
                    <h2 class="card-title">{{ ch.title }}</h2>
                    <p class="card-desc">{{ ch.desc }}</p>
                </a>
                {% endfor %}
            </div>
        </section>
        {% endfor %}

        <section class="features">
            <h2>📖 このガイドの特徴</h2>
            <div class="feature-grid">
                <div class="feature-item">
                    <span class="feature-icon">🧩</span>
                    <h3>独学の盲点を埋める</h3>
                    <p>「CIの緑は何を証明するのか」など、独学だと抜け落ちる開発の常識を体系的に</p>
                </div>
                <div class="feature-item">
                    <span class="feature-icon">🗣️</span>
                    <h3>面接・実務で効く</h3>
                    <p>開発者と話が通じる・面接で聞かれる開発常識を網羅</p>
                </div>
                <div class="feature-item">
                    <span class="feature-icon">📱</span>
                    <h3>モバイル対応</h3>
                    <p>スマホからいつでも見返せるレスポンシブデザイン</p>
                </div>
                <div class="feature-item">
                    <span class="feature-icon">🌙</span>
                    <h3>ダークモード</h3>
                    <p>目に優しいテーマ切替対応</p>
                </div>
            </div>
        </section>
    </main>

    <footer class="site-footer">
        <p>開発の常識・作法 — <a href="https://github.com/fukukei23/dev-textbook">GitHub</a>
         · <a href="https://fukukei23.github.io/claude-code-guide/">Claude Code Guide</a>
         · <a href="https://fukukei23.github.io/guides/">技術ガイド集</a>
         · <a href="https://fukukei23.github.io/">fukukei23</a></p>
        <p class="site-version">v{{ version }} · {{ build_date }}</p>
    </footer>

    <script src="assets/script.js"></script>
</body>
</html>
""", autoescape=True)


# --- フィルタリング ---

def filter_sections(text: str) -> str:
    """個人情報・環境固有セクションを除去."""
    lines = text.split("\n")
    result = []
    skip = False

    for line in lines:
        stripped = line.strip()

        # 除去対象セクションの開始（## または ### セクション）
        if stripped.startswith("## ") and any(stripped.startswith(s) for s in REMOVE_SECTIONS):
            skip = True
            continue

        # 「あなたの」で始まる## / ### セクションも除去
        if (stripped.startswith("## ") or stripped.startswith("### ")) and any(p in stripped for p in REMOVE_PATTERNS):
            skip = True
            continue

        # 次の ## セクションでスキップ解除（### はスキップ解除しない）
        if skip and stripped.startswith("## ") and not any(p in stripped for p in REMOVE_PATTERNS):
            skip = False

        if not skip:
            result.append(line)

    text = "\n".join(result)

    # 個人識別子のサニタイズ（dev-textbookはパブリック公開コンテンツのため不要）
    pass

    # インライン個人情報のサニタイズ
    for pattern, replacement in INLINE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    for pattern, replacement in TABLE_COL_SANITIZE:
        text = re.sub(pattern, replacement, text)

    # 未処理の「あなたの」を行内テキストから除去
    text = re.sub(r"あなたの環境では", "", text)
    text = re.sub(r"あなたの環境:", "", text)

    return text


# --- Markdown → HTML変換 ---

def convert_md_to_html(md_text: str) -> str:
    """MarkdownをHTMLに変換."""
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    return md.render(md_text)


def inject_mermaid(html: str, filename: str) -> str:
    """Mermaid図を指定位置に挿入."""
    diagrams = MERMAID_DIAGRAMS.get(filename, [])
    if not diagrams:
        return html

    for heading, diagram_code in diagrams:
        # HTMLの見出しタグを検索（<a id>タグ込みも対応）
        heading_text = heading.replace("## ", "").strip()
        mermaid_block = (
            f'<div class="mermaid-wrapper">'
            f'<div class="mermaid">\n{diagram_code}\n</div>'
            f'</div>'
        )

        # <h2>テキスト</h2> または <h2><a ...></a>テキスト</h2> の前に挿入
        pattern = f"(<h2>(?:<a[^>]*></a>)?{re.escape(heading_text)}</h2>)"
        if re.search(pattern, html):
            html = re.sub(pattern, mermaid_block + r"\1", html, count=1)

    return html


def rewrite_links(html: str, chapter_map: dict | None = None) -> str:
    """内部リンクをHTML URLに書き換え."""
    from urllib.parse import quote, unquote

    cmap = chapter_map or CHAPTER_MAP

    for filename, info in cmap.items():
        # [テキスト](XX_YY.md) → XX-yy.html
        html = html.replace(f'href="{filename}', f'href="{info["slug"]}.html')
        # [テキスト](XX_YY.md#anchor) → XX-yy.html#anchor
        html = re.sub(
            rf'href="{re.escape(filename)}#',
            f'href="{info["slug"]}.html#',
            html,
        )

        # URLエンコードされたリンク（例: 11_%E7%8F%BE%E5%A0%B4...）も処理
        encoded_name = quote(filename, safe='')
        if encoded_name != filename:
            html = html.replace(f'href="{encoded_name}', f'href="{info["slug"]}.html')
            html = re.sub(
                rf'href="{re.escape(encoded_name)}#',
                f'href="{info["slug"]}.html#',
                html,
            )

    # 未変換の.mdリンクをすべて処理
    def replace_md_link(match):
        href = match.group(1)
        for filename, info in cmap.items():
            decoded = unquote(href)
            if filename in decoded or filename in href:
                anchor = ""
                if "#" in href:
                    anchor = "#" + href.split("#", 1)[1]
                elif "#" in decoded:
                    anchor = "#" + decoded.split("#", 1)[1]
                return f'href="{info["slug"]}.html{anchor}"'
        return f'href="#"'

    html = re.sub(r'href="([^"]*\.md[^"]*)"', replace_md_link, html)

    # 外部リンク（obsidian-ssot内の他ファイル）を除去
    html = re.sub(r'href="\.\./[^"]*"', 'href="#"', html)
    html = re.sub(r'href="01_DECISIONS[^"]*"', 'href="#"', html)

    return html


def convert_tldr(html: str) -> str:
    """H1直後の『3行で分かる』blockquote を <aside class="tldr"> に変換.

    平易化（2026-07-17移植）: 各ページH1直後に置いた `> **3行で分かる**` blockquoteを
    目立つTLDR枠に変換する。enhance_html の単一段落callout変換（<blockquote><p>…</p></blockquote>）
    にマッチしない複数要素blockquoteを対象とするため、enhance_html の後に呼ぶこと。
    H1直後の最初のblockquoteのみ（位置保証）。'3行で分かる' を含まなければ変換しない（後方互換）。
    ※ enhance_html の【前】に呼ぶこと（後だと enhance_html のcallout変換にTLDRが食われる）。
    """
    pattern = re.compile(
        r'(<h1[^>]*>.*?</h1>\s*)(<blockquote>.*?</blockquote>)',
        re.DOTALL,
    )
    m = pattern.search(html)
    if not m:
        return html
    head, block = m.group(1), m.group(2)
    if '3行で分かる' not in block:
        return html
    inner = block[len('<blockquote>'):-len('</blockquote>')]
    converted = head + f'<aside class="tldr">{inner}</aside>'
    return html[:m.start()] + converted + html[m.end():]


def enhance_html(html: str) -> str:
    """HTMLに装飾を追加（テーブルラップ・コールアウト等）."""
    # テーブルをスクロールラッパーで囲む
    html = re.sub(
        r"(<table[^>]*>.*?</table>)",
        r'<div class="table-wrapper">\1</div>',
        html,
        flags=re.DOTALL,
    )

    # 引用ブロックをコールアウトに変換
    def callout_replace(match):
        content = match.group(1)
        if "注意" in content or "⚠" in content:
            return f'<div class="callout callout-warn"><p>{content}</p></div>'
        if "重要" in content:
            return f'<div class="callout callout-danger"><p>{content}</p></div>'
        if "現場の知見" in content or "💡" in content or "Tip" in content:
            return f'<div class="callout callout-tip"><p>{content}</p></div>'
        return f'<div class="callout callout-info"><p>{content}</p></div>'

    html = re.sub(r"<blockquote>\s*<p>(.*?)</p>\s*</blockquote>", callout_replace, html, flags=re.DOTALL)

    return html


def linkify_chapter_refs(md_text: str, cmap: dict) -> str:
    """平文「第N章」を該当章へのMarkdownリンクに変換（code fence/インラインcode内は除外）."""
    # 章番号(1〜) → filename のマッピング
    num_to_file: dict[str, str] = {}
    for filename in cmap:
        m = re.match(r"^(\d+)_", filename)
        if m:
            num = str(int(m.group(1)))  # 先頭0詰め除去: "07" → "7"
            num_to_file[num] = filename

    lines = md_text.split("\n")
    in_fence = False
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            result.append(line)
            continue
        if in_fence:
            result.append(line)
            continue

        # インラインcode（`...`）を一時退避して保護
        placeholders: list[str] = []

        def _stash_code(m):
            placeholders.append(m.group(0))
            return f"\x00CODE{len(placeholders) - 1}\x00"

        safe_line = re.sub(r"`[^`]+`", _stash_code, line)

        # 平文「第N章」をリンク化（既存 [..](..) 内は回避）
        def _linkify(m):
            n = m.group(1)
            if n in num_to_file:
                return f"[第{n}章]({num_to_file[n]})"
            return m.group(0)

        safe_line = re.sub(r"第(\d+)章", _linkify, safe_line)

        # プレースホルダ復元
        for i, code in enumerate(placeholders):
            safe_line = safe_line.replace(f"\x00CODE{i}\x00", code)
        result.append(safe_line)

    return "\n".join(result)


def add_toc_and_heading_ids(html: str) -> str:
    """H2見出しにidを付与し、章冒頭にページ内TOC（details式・クリック開閉）を生成."""
    headings = re.findall(r"<h2>(.*?)</h2>", html, flags=re.DOTALL)
    if len(headings) < 3:
        return html  # 見出し少なすぎる章はTOC省略

    # H2 に id 付与（sec-1, sec-2, ...）
    counter = [0]

    def _add_id(match):
        counter[0] += 1
        text = match.group(1)
        return f'<h2 id="sec-{counter[0]}">{text}</h2>'

    html = re.sub(r"<h2>(.*?)</h2>", _add_id, html, flags=re.DOTALL)

    # TOC HTML 組み立て
    items = []
    for i, text in enumerate(headings, start=1):
        clean = re.sub(r"<[^>]+>", "", text).strip()
        items.append(f'<li><a href="#sec-{i}">{clean}</a></li>')
    toc_html = (
        '<details class="page-toc" open>\n'
        '<summary>📑 この章の目次</summary>\n'
        '<ul>\n' + "\n".join(items) + "\n</ul>\n"
        "</details>\n"
    )

    # 最初の <h2 の直前に挿入
    html = re.sub(r"(<h2 id=\"sec-1\")", toc_html + r"\1", html, count=1)
    return html


def collapse_glossary_items(html: str) -> str:
    """用語集: callout(使い方/実例)付きの単独エントリを details（クリック開閉）に変換。

    <ul><li><strong>CI</strong>...説明</li></ul>
    <div class="callout">使い方...</div>
    <div class="callout">実例...</div>
    ↓
    <details class="glossary-item"><summary><strong>CI</strong>...説明</summary>
    <div class="callout">使い方...</div>...</details>
    """
    pattern = re.compile(
        r'<ul>\s*<li>(.*?)</li>\s*</ul>\s*((?:<div class="callout[^"]*">.*?</div>\s*)+)',
        flags=re.DOTALL,
    )

    def repl(m):
        summary_html = m.group(1).strip()
        callouts_html = m.group(2).rstrip()
        return (
            f'<details class="glossary-item">\n'
            f'<summary>{summary_html}</summary>\n'
            f'{callouts_html}\n'
            f'</details>'
        )

    return pattern.sub(repl, html)


# --- トップページのカテゴリ分け ---

# 章番号→カテゴリの境界（番号レンジは閉区間）
INDEX_CATEGORIES = [
    ("📚 基礎・設計", 0, 1),
    ("🤖 運用・自動化", 2, 5),
    ("📚 知見・キャリア", 6, 8),
    ("🔧 メタ", 9, 9),
]
INDEX_CATEGORY_FALLBACK = "📚 その他"


def group_chapters_by_category(chapters: list) -> list:
    """章番号レンジに基づき、トップページ表示用にカテゴリへグルーピング."""
    buckets = {name: [] for name, _, _ in INDEX_CATEGORIES}
    buckets[INDEX_CATEGORY_FALLBACK] = []

    for ch in chapters:
        number = ch["number"]
        category_name = INDEX_CATEGORY_FALLBACK
        if number.isdigit():
            n = int(number)
            for name, lo, hi in INDEX_CATEGORIES:
                if lo <= n <= hi:
                    category_name = name
                    break
        buckets[category_name].append(ch)

    ordered_names = [name for name, _, _ in INDEX_CATEGORIES] + [INDEX_CATEGORY_FALLBACK]
    return [{"name": name, "chapters": buckets[name]} for name in ordered_names if buckets[name]]


# --- メイン ---

def main():
    # ディレクトリ準備
    chapters_dir = OUTPUT_DIR / "chapters"
    assets_dir = OUTPUT_DIR / "assets"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # バージョン・日付を取得（ビルドごとにインクリメント）
    version, build_date = get_build_info()
    print(f"Build: v{version} · {build_date}")

    # 章リストを構築（自動スキャン込み）
    effective_map = build_chapter_map()
    chapters = []
    for filename, info in sorted(effective_map.items()):
        chapters.append({
            "number": info["slug"][:2],
            "slug": info["slug"],
            "title": info["title"],
            "icon": info["icon"],
            "desc": info["desc"],
            "filename": filename,
        })

    # 各章を変換
    for i, ch in enumerate(chapters):
        src = SOURCE_DIR / ch["filename"]
        if not src.exists():
            print(f"SKIP: {ch['filename']} not found")
            continue

        md_text = src.read_text(encoding="utf-8")
        md_text = filter_sections(md_text)
        md_text = linkify_chapter_refs(md_text, effective_map)
        html_body = convert_md_to_html(md_text)
        html_body = inject_mermaid(html_body, ch["filename"])
        html_body = rewrite_links(html_body, effective_map)
        html_body = convert_tldr(html_body)
        html_body = enhance_html(html_body)
        if ch["slug"] != "14-glossary":
            html_body = add_toc_and_heading_ids(html_body)
        else:
            html_body = collapse_glossary_items(html_body)

        prev_ch = chapters[i - 1] if i > 0 else None
        next_ch = chapters[i + 1] if i < len(chapters) - 1 else None

        full_html = CHAPTER_TEMPLATE.render(
            title=ch["title"],
            slug=ch["slug"],
            current_slug=ch["slug"],
            content=html_body,
            chapters=chapters,
            prev_ch=prev_ch,
            next_ch=next_ch,
            version=version,
            build_date=build_date,
        )

        out = chapters_dir / f"{ch['slug']}.html"
        out.write_text(full_html, encoding="utf-8")
        print(f"OK: {ch['slug']}.html")

    # index.html 生成（カテゴリ分けして表示）
    categories = group_chapters_by_category(chapters)
    index_html = INDEX_TEMPLATE.render(categories=categories, version=version, build_date=build_date)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print("OK: index.html")

    print(f"\n完了: {len(chapters)}章 + index → {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
