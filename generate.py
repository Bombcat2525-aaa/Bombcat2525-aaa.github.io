# -*- coding: utf-8 -*-
"""
記事自動生成スクリプト
- 外部参照情報を取得
- 参照取得状況を記事に明記
- 参照0件時はAI生成を行わず固定文を出力
- posts/ に保存
- index.html を再生成
- Gitへ自動push可能
"""

import argparse
import datetime
import html
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "trusted-writer"

SITE_TITLE = "知識ナビ"
SITE_DESCRIPTION = "生活や仕事に役立つ情報を、わかりやすく整理してお届けします。"

MIN_REFERENCE_SOURCES = 3
REQUEST_TIMEOUT = 20
MAX_FETCH_URLS = 12
MAX_TEXT_PER_SOURCE = 2500
MAX_REFERENCE_EXCERPT = 3000

TRUSTED_DOMAIN_KEYWORDS = [
    ".go.jp", ".gov", ".edu",
    "developer.mozilla.org", "docs.python.org", "microsoft.com", "learn.microsoft.com",
    "aws.amazon.com", "cloud.google.com", "kubernetes.io", "docker.com",
    "unity.com", "unrealengine.com", "sidefx.com",
    "wikipedia.org",
    "github.com", "stackoverflow.com",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
POSTS_DIR = BASE_DIR / "posts"
INDEX_FILE = BASE_DIR / "index.html"
DEBUG_DIR = BASE_DIR / "debug"

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = text.replace("\ufffd", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_print(message: str):
    try:
        print(sanitize_text(str(message)))
    except Exception:
        print("[WARN] log output failed")


def slugify(text: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{timestamp}-{ascii_part[:30]}" if ascii_part else f"{timestamp}-post"


def is_trusted_url(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in TRUSTED_DOMAIN_KEYWORDS)


def search_candidate_urls(query: str) -> list[str]:
    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": USER_AGENT}
    urls = []

    try:
        response = requests.get(search_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.select("a.result__a"):
            href = (a.get("href") or "").strip()
            if href.startswith("http"):
                urls.append(href)

        if not urls:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("http"):
                    urls.append(href)

    except Exception as e:
        safe_print(f"[WARN] search failed: {e}")
        return []

    seen = set()
    dedup = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            dedup.append(u)

    return dedup[:MAX_FETCH_URLS]


def extract_main_text_from_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    target = soup.find("article") or soup.find("main") or soup.body or soup

    parts = []
    for p in target.find_all(["p", "li", "h1", "h2", "h3"]):
        t = sanitize_text(p.get_text(" ", strip=True))
        if t:
            parts.append(t)

    text = sanitize_text("\n".join(parts))
    return text[:MAX_TEXT_PER_SOURCE]


def fetch_text_from_url(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding

    ctype = (response.headers.get("Content-Type") or "").lower()
    if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
        return ""

    text = extract_main_text_from_html(response.text)
    return sanitize_text(text)


def build_reference_status(url_count: int) -> str:
    if url_count == 0:
        return "参照情報は取得できませんでした。この記事は参照情報なしで生成されています。"
    if url_count < 3:
        return f"参照情報は{url_count}件取得されました。十分な件数ではない可能性があります。"
    return f"参照情報は{url_count}件取得されました。"


def gather_references(title: str, keyword: str) -> tuple[str, list[str], str]:
    query = f"{title} {keyword}".strip()
    candidate_urls = search_candidate_urls(query)

    trusted_urls = [u for u in candidate_urls if is_trusted_url(u)]
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
            if len(text) >= 200:
                chunks.append(f"[Source: {url}]\n{text}")
                used_urls.append(url)
        except Exception as e:
            safe_print(f"[WARN] fetch failed: {url} / {e}")

    reference_text = sanitize_text("\n\n".join(chunks))
    reference_status = build_reference_status(len(used_urls))
    return reference_text, used_urls, reference_status


def build_prompt(title: str, reference_status: str, reference_text: str) -> str:
    return f"""以下は信頼できる参照情報です。
この情報のみを使用して記事を書いてください。

【参照情報の取得状況】
{reference_status}

【参照情報】
{reference_text}

【記事タイトル】
{title}
"""


def call_ollama_generate_article(title: str, reference_status: str, reference_text: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": build_prompt(title, reference_status, reference_text),
        "stream": False,
    }

    response = requests.post(OLLAMA_API_URL, json=payload, timeout=300)
    response.raise_for_status()
    data = response.json()

    article = sanitize_text(data.get("response", ""))
    if not article:
        raise RuntimeError("Ollama response was empty.")
    return article


def build_no_reference_article(title: str) -> str:
    return f"""# {title}

この記事を作成するための参照情報が取得できませんでした。

そのため、事実に基づく本文は作成できません。
"""


def append_reference_report(article_md: str, reference_status: str, used_urls: list[str], reference_text: str) -> str:
    reference_text_excerpt = sanitize_text(reference_text)[:MAX_REFERENCE_EXCERPT]

    lines = [
        sanitize_text(article_md),
        "",
        "---",
        "",
        "## 参照情報の取得状況",
        "",
        reference_status,
        "",
        "## 参考URL",
        "",
    ]

    if used_urls:
        for url in used_urls:
            lines.append(f"- {url}")
    else:
        lines.append("取得できた参考URLはありません。")

    lines.extend([
        "",
        "## 取得した参照情報の抜粋",
        "",
        "```text",
        reference_text_excerpt if reference_text_excerpt else "（参照情報は取得できませんでした）",
        "```",
        "",
    ])

    return "\n".join(lines)


def markdown_to_html_simple(md_text: str) -> str:
    lines = sanitize_text(md_text).splitlines()
    html_lines = []
    in_ul = False
    in_code = False

    for raw in lines:
        s = raw.rstrip()

        if s.startswith("```"):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False

            if not in_code:
                html_lines.append("<pre><code>")
                in_code = True
            else:
                html_lines.append("</code></pre>")
                in_code = False
            continue

        if in_code:
            html_lines.append(html.escape(s))
            continue

        if not s.strip():
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            continue

        t = s.strip()

        if t.startswith("### "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h3>{html.escape(t[4:])}</h3>")
            continue

        if t.startswith("## "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h2>{html.escape(t[3:])}</h2>")
            continue

        if t.startswith("# "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h1>{html.escape(t[2:])}</h1>")
            continue

        if t == "---":
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append("<hr>")
            continue

        if t.startswith("- ") or t.startswith("* "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{html.escape(t[2:])}</li>")
            continue

        if in_ul:
            html_lines.append("</ul>")
            in_ul = False

        html_lines.append(f"<p>{html.escape(t)}</p>")

    if in_ul:
        html_lines.append("</ul>")
    if in_code:
        html_lines.append("</code></pre>")

    return "\n".join(html_lines)


def load_posts_metadata():
    posts = []
    for p in sorted(POSTS_DIR.glob("*.html"), reverse=True):
        text = p.read_text(encoding="utf-8", errors="ignore")
        title_match = re.search(r"<!--TITLE:(.*?)-->", text)
        date_match = re.search(r"<!--DATE:(.*?)-->", text)

        title = title_match.group(1).strip() if title_match else p.stem
        date = date_match.group(1).strip() if date_match else ""
        posts.append({
            "title": title,
            "date": date,
            "url": f"posts/{p.name}",
        })
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
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "push"], check=True)
        safe_print("[OK] git push completed")
    except Exception as e:
        safe_print(f"[WARN] git push failed: {e}")


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

    title = sanitize_text(args.title)
    keyword = sanitize_text(args.keyword)
    date_str = datetime.date.today().isoformat()
    slug = slugify(title)

    safe_print("[1/6] Fetching references...")
    reference_text, used_urls, reference_status = gather_references(title, keyword)

    safe_print(f"[INFO] Reference chars: {len(reference_text)}")
    safe_print(f"[INFO] Reference count: {len(used_urls)}")
    safe_print("[INFO] URLs:")
    for url in used_urls:
        safe_print(f"  - {url}")

    if args.debug:
        (DEBUG_DIR / f"{slug}_reference.txt").write_text(reference_text, encoding="utf-8")
        (DEBUG_DIR / f"{slug}_urls.txt").write_text("\n".join(used_urls), encoding="utf-8")
        (DEBUG_DIR / f"{slug}_status.txt").write_text(reference_status, encoding="utf-8")
        safe_print(f"[DEBUG] saved to: {DEBUG_DIR}")

    safe_print("[2/6] Building article...")
    if len(used_urls) == 0:
        md_article = build_no_reference_article(title)
    else:
        md_article = call_ollama_generate_article(title, reference_status, reference_text)

    safe_print("[3/6] Appending reference report...")
    md_article = append_reference_report(md_article, reference_status, used_urls, reference_text)

    safe_print("[4/6] Rendering HTML...")
    article_html_body = markdown_to_html_simple(md_article)

    safe_print("[5/6] Saving post...")
    article_full_html = render_article_html(
        title=title,
        date_str=date_str,
        article_html=article_html_body,
        slug=slug,
    )

    post_file = POSTS_DIR / f"{slug}.html"
    article_full_html = f"<!--TITLE:{title}-->\n<!--DATE:{date_str}-->\n" + article_full_html
    post_file.write_text(article_full_html, encoding="utf-8")
    safe_print(f"[OK] saved: {post_file}")

    safe_print("[6/6] Updating index.html...")
    posts = load_posts_metadata()
    index_html = render_index_html(posts)
    INDEX_FILE.write_text(index_html, encoding="utf-8")
    safe_print(f"[OK] updated: {INDEX_FILE}")

    if not args.no_push:
        git_auto_push(f"Add post with reference status: {title}")
    else:
        safe_print("[SKIP] push disabled by --no-push")

    safe_print("Done.")


if __name__ == "__main__":
    main()
