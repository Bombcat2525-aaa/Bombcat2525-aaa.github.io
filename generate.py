# -*- coding: utf-8 -*-
"""
記事自動生成スクリプト (Pythonのみ)
- 外部の信頼できる情報源から参照情報を取得
- 参照情報が十分な場合のみ trusted-writer で記事生成
- postsフォルダへ保存
- index.htmlへ記事一覧を自動追加
- Gitへ自動コミット・プッシュ
- Windows対応

使い方:
    python generate.py --title "Houdini 入門" --keyword "Houdini" --debug

事前準備:
    1) Ollamaをインストールして起動
    2) trusted-writer モデルを利用可能にする
    3) このプロジェクトをgit管理下に置く
"""

import argparse
import datetime
import html
import re
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

# =========================
# 設定（必要に応じて変更）
# =========================
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "trusted-writer"  # 要件: 必ず trusted-writer
SITE_TITLE = "知識ナビ"
SITE_DESCRIPTION = "生活や仕事に役立つ情報を、わかりやすく整理してお届けします。"

MIN_REFERENCE_SOURCES = 3
MIN_REFERENCE_CHARS = 1000
REQUEST_TIMEOUT = 20
MAX_FETCH_URLS = 12
MAX_TEXT_PER_SOURCE = 2500

# 信頼できるドメイン（必要に応じて追加）
TRUSTED_DOMAIN_KEYWORDS = [
    # 公的機関 / 教育 / 公式に寄せる
    ".go.jp", ".gov", ".edu",
    # 技術メディア
    "developer.mozilla.org", "docs.python.org", "microsoft.com", "learn.microsoft.com",
    "aws.amazon.com", "cloud.google.com", "kubernetes.io", "docker.com",
    "unity.com", "unrealengine.com", "sidefx.com",
    # 補助
    "wikipedia.org",
    # 一般的な大手ドキュメント/媒体
    "github.com", "stackoverflow.com"
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# ディレクトリ定義
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
POSTS_DIR = BASE_DIR / "posts"
INDEX_FILE = BASE_DIR / "index.html"
DEBUG_DIR = BASE_DIR / "debug"

# Jinja2初期化
env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def slugify(text: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    if ascii_part:
        return f"{timestamp}-{ascii_part[:30]}"
    return f"{timestamp}-post"


def is_trusted_url(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in TRUSTED_DOMAIN_KEYWORDS)


def search_candidate_urls(query: str) -> list[str]:
    """
    DuckDuckGo HTML検索結果から候補URLを抽出
    （軽量でキー不要。環境によっては取得できない場合あり）
    """
    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": USER_AGENT}
    urls = []

    try:
        r = requests.get(search_url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # DuckDuckGo HTML版の結果リンク
        for a in soup.select("a.result__a"):
            href = a.get("href", "").strip()
            if href.startswith("http"):
                urls.append(href)

        # フォールバック（一般aタグ）
        if not urls:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("http"):
                    urls.append(href)

    except Exception:
        # 検索取得失敗時は空返し
        return []

    # 重複削除（順序維持）
    seen = set()
    dedup = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            dedup.append(u)

    return dedup[:MAX_FETCH_URLS]


def extract_main_text_from_html(html_text: str) -> str:
    """
    HTMLから本文候補テキストを抽出
    """
    soup = BeautifulSoup(html_text, "html.parser")

    # 不要タグ除去
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    # article優先、なければmain、さらにだめならbody
    target = soup.find("article") or soup.find("main") or soup.body or soup

    # 段落中心で抽出
    parts = []
    for p in target.find_all(["p", "li", "h1", "h2", "h3"]):
        t = p.get_text(" ", strip=True)
        if t:
            parts.append(t)

    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # 長すぎる場合はトリム
    return text[:MAX_TEXT_PER_SOURCE]


def fetch_text_from_url(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "").lower()

    if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
        return ""

    return extract_main_text_from_html(r.text)


def gather_references(title: str, keyword: str) -> tuple[str, list[str]]:
    """
    参照情報を収集して reference_text を返す
    戻り値: (reference_text, used_urls)
    """
    query = f"{title} {keyword}".strip()
    candidate_urls = search_candidate_urls(query)

    # 信頼できるURLを優先
    trusted_urls = [u for u in candidate_urls if is_trusted_url(u)]

    # 不足時は全候補からも補う（ただし最終的に信頼性低いものは可能な限り避ける）
    if len(trusted_urls) < MIN_REFERENCE_SOURCES:
        for u in candidate_urls:
            if u not in trusted_urls:
                trusted_urls.append(u)
            if len(trusted_urls) >= MAX_FETCH_URLS:
                break

    used_urls = []
    chunks = []

    for url in trusted_urls:
        if len(used_urls) >= MAX_FETCH_URLS:
            break
        try:
            text = fetch_text_from_url(url)
            # 最低限の本文長があるものだけ採用
            if len(text) >= 200:
                chunks.append(f"[Source: {url}]\n{text}")
                used_urls.append(url)
                if len(used_urls) >= MIN_REFERENCE_SOURCES and sum(len(c) for c in chunks) >= MIN_REFERENCE_CHARS:
                    # 条件を満たしたら早めに終了
                    break
        except Exception:
            continue

    reference_text = "\n\n".join(chunks).strip()
    return reference_text, used_urls


def build_prompt(title: str, reference_text: str) -> str:
    """
    要件指定のプロンプト形式
    """
    return f"""以下は信頼できる参照情報です。
この情報のみを使用して記事を書いてください。

【参照情報】
{reference_text}

【記事タイトル】
{title}
"""


def call_ollama_generate_article(title: str, reference_text: str) -> str:
    prompt = build_prompt(title, reference_text)
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}

    try:
        res = requests.post(OLLAMA_API_URL, json=payload, timeout=300)
        res.raise_for_status()
        data = res.json()

        article = data.get("response", "").strip()
        if not article:
            raise ValueError("Ollamaの応答が空です。")
        return article

    except Exception as e:
        raise RuntimeError(
            f"Ollama APIの呼び出しに失敗しました: {e}\n"
            "Ollamaが起動しているか、trusted-writerモデルが利用可能か確認してください。"
        )


def append_references_section(article_md: str, used_urls: list[str]) -> str:
    lines = [article_md.strip(), "", "## 参考情報", ""]
    for u in used_urls:
        lines.append(f"* {u}")
    return "\n".join(lines).strip() + "\n"


def markdown_to_html_simple(md_text: str) -> str:
    lines = md_text.splitlines()
    html_lines = []
    in_ul = False

    for line in lines:
        s = line.strip()

        if not s:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            continue

        if s.startswith("### "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h3>{html.escape(s[4:])}</h3>")
            continue
        if s.startswith("## "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h2>{html.escape(s[3:])}</h2>")
            continue
        if s.startswith("# "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h1>{html.escape(s[2:])}</h1>")
            continue

        if s.startswith("- ") or s.startswith("* "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{html.escape(s[2:])}</li>")
            continue

        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        html_lines.append(f"<p>{html.escape(s)}</p>")

    if in_ul:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def load_posts_metadata():
    posts = []
    for p in sorted(POSTS_DIR.glob("*.html"), reverse=True):
        text = p.read_text(encoding="utf-8", errors="ignore")
        title_match = re.search(r"<!--TITLE:(.*?)-->", text)
        date_match = re.search(r"<!--DATE:(.*?)-->", text)

        title = title_match.group(1).strip() if title_match else p.stem
        date = date_match.group(1).strip() if date_match else ""
        posts.append({"title": title, "date": date, "url": f"posts/{p.name}"})
    return posts


def render_article_html(title: str, date_str: str, article_html: str, slug: str) -> str:
    template = env.get_template("article_template.html")
    return template.render(
        site_title=SITE_TITLE,
        site_description=SITE_DESCRIPTION,
        article_title=title,
        article_date=date_str,
        article_html=article_html,
        slug=slug,
    )


def render_index_html(posts):
    template = env.get_template("index_template.html")
    return template.render(
        site_title=SITE_TITLE,
        site_description=SITE_DESCRIPTION,
        posts=posts,
    )


def git_auto_push(commit_message: str):
    try:
        subprocess.run(["git", "add", "."], check=True)
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "push"], check=True)

        print("[OK] Git push 完了")
        if commit_result.stdout:
            print(commit_result.stdout.strip())

    except Exception as e:
        print("[WARN] Git自動pushに失敗しました。手動でpushしてください。")
        print(f"       詳細: {e}")


def main():
    parser = argparse.ArgumentParser(description="記事自動生成")
    parser.add_argument("--title", required=True, help="記事タイトル")
    parser.add_argument("--keyword", default="", help="補助キーワード")
    parser.add_argument("--no-push", action="store_true", help="Git pushを無効化")
    parser.add_argument("--debug", action="store_true", help="参照情報をdebugフォルダへ保存")
    args = parser.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if args.debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    title = args.title.strip()
    keyword = args.keyword.strip()
    date_str = datetime.date.today().isoformat()
    slug = slugify(title)

    print("[1/6] 外部参照情報を取得中...")
    reference_text, used_urls = gather_references(title, keyword)

    # ログ出力（要件）
    print(f"[INFO] 参照情報文字数: {len(reference_text)}")
    print("[INFO] 使用URL一覧:")
    for u in used_urls:
        print(f"  - {u}")

    # 要件: 3件以上 & 1000文字以上 なければ中止
    if len(used_urls) < MIN_REFERENCE_SOURCES or len(reference_text) < MIN_REFERENCE_CHARS:
        raise RuntimeError("十分な参照情報を取得できなかったため記事生成を中止しました")

    # --debug: 参照情報保存
    if args.debug:
        debug_file = DEBUG_DIR / f"{slug}_reference.txt"
        debug_file.write_text(reference_text, encoding="utf-8")
        debug_urls = DEBUG_DIR / f"{slug}_urls.txt"
        debug_urls.write_text("\n".join(used_urls), encoding="utf-8")
        print(f"[DEBUG] 参照情報保存: {debug_file}")
        print(f"[DEBUG] URL一覧保存: {debug_urls}")

    print("[2/6] trusted-writerで記事生成中...")
    md_article = call_ollama_generate_article(title, reference_text)

    print("[3/6] 参考情報セクションを追加中...")
    md_article = append_references_section(md_article, used_urls)

    print("[4/6] MarkdownをHTMLへ変換中...")
    article_html_body = markdown_to_html_simple(md_article)

    print("[5/6] 記事ファイルを保存中...")
    article_full_html = render_article_html(
        title=title, date_str=date_str, article_html=article_html_body, slug=slug
    )

    post_file = POSTS_DIR / f"{slug}.html"
    article_full_html = f"<!--TITLE:{title}-->\n<!--DATE:{date_str}-->\n" + article_full_html
    post_file.write_text(article_full_html, encoding="utf-8")
    print(f"[OK] 保存: {post_file}")

    print("[6/6] index.htmlを更新中...")
    posts = load_posts_metadata()
    index_html = render_index_html(posts)
    INDEX_FILE.write_text(index_html, encoding="utf-8")
    print(f"[OK] 更新: {INDEX_FILE}")

    if not args.no_push:
        print("[Git] push中...")
        git_auto_push(f"Add new post with references: {title}")
    else:
        print("[SKIP] --no-push が指定されたためpushしません。")

    print("\n完了しました。公開ページを確認してください。")


if __name__ == "__main__":
    main()
