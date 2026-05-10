# -*- coding: utf-8 -*-
"""
記事自動生成スクリプト (Pythonのみ)
- 外部の信頼できる情報源から参照情報を取得
- 参照情報の取得状況を記事に明記
- 参照0件時はAI推測生成を禁止し、固定の注意本文を出力
- postsフォルダへ保存
- index.htmlへ記事一覧を自動追加
- Gitへ自動コミット・プッシュ
- Windows対応
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

# =========================
# 設定（必要に応じて変更）
# =========================
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "trusted-writer"  # 要件: 必ず trusted-writer
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


def safe_print(msg: str):
    try:
        print(sanitize_text(str(msg)))
    except Exception:
        print("[WARN] ログ出力時に問題が発生しました。")


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
        r = requests.get(search_url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")

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
        safe_print(f"[WARN] 検索取得失敗: {e}")
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
    response.encoding = response.apparent_encoding  # 要件

    ctype = (response.headers.get("Content-Type") or "").lower()
    if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
        return ""

    text = extract_main_text_from_html(response.text)
    return sanitize_text(text)


def build_reference_status(used_urls_count: int) -> str:
    if used_urls_count == 0:
        return "参照情報は取得できませんでした。この記事は参照情報なしで生成されています。"
    elif used_urls_count < 3:
        return f"参照情報は{used_urls_count}件取得されました。十分な件数ではない可能性があります。"
    else:
        return f"参照情報は{used_urls_count}件取得されました。"


def gather_references(title: str, keyword: str) -> tuple[str, list[str], str]:
    """
    要件:
    - 参照不足でも即raiseしない
    - 戻り値: reference_text, used_urls, reference_status
    """
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
                chunks.append(f"[Source: {url}]\n{sanitize_text(text)}")
                used_urls.append(url)
        except Exception as e:
            safe_print(f"[WARN] URL取得失敗: {url} / {e}")

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
    prompt = build_prompt(title, reference_status, reference_text)
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    res = requests.post(OLLAMA_API_URL, json=payload, timeout=300)
    res.raise_for_status()
    data = res.json()
    article = sanitize_text(data.get("response", ""))
    if not article:
        raise RuntimeError("Ollamaの応答が空です。")
    return article


def build_no_reference_article(title: str) -> str:
    """
    要件:
    参照0件の場合は推測記事を禁止し、固定本文にする
    """
    return f"""# {title}

この記事を作成するための参照情報が取得できませんでした。

そのため、事実に基づく本文は作成できません。
"""


def append_reference_report(article_md: str, reference_status: str, used_urls: list[str], reference_text: str) -> str:
    excerpt = sanitize_text(reference_text)[:MAX_REFERENCE_EXCERPT]

    lines = [sanitize_text(article_md), "", "---", "", "## 参照情報の取得状況", "", reference_status, "", "## 参考URL", ""]
    if len(used_urls) == 0:
        lines.append("取得できた参考URLはありません。")
    else:
        for u in used_urls:
            lines.append(f"- {u}")

    lines += ["", "## 取得した参照情報の抜粋", "", "```text", excerpt if excerpt else "（参照情報は取得できませんでした）", "```", ""]
    return "\n".join(lines)


def markdown_to_html_simple(md_text: str) -> str:
    lines = sanitize_text(md_text).splitlines()
    html_lines = []
    in_ul = False
    in_code = False

    for raw in lines:
        s = raw.rstrip()

        # コードブロック対応
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
        subprocess.run(["git", "commit", "-m", commit_message], check=False, capture_output=True, text=True)
        subprocess.run(["git", "push"], check=True)
        safe_print("[OK] Git push 完了")
    except Exception as e:
        safe_print(f"[WARN] Git push失敗: {e}")


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

    safe_print("[1/6] 参照情報を取得中...")
    reference_text, used_urls, reference_status = gather_references(title, keyword)

    safe_print(f"[INFO] 参照情報文字数: {len(reference_text)}")
    safe_print(f"[INFO] 参照取得件数: {len(used_urls)}")
    safe_print("[INFO] 使用URL一覧:")
    for u in used_urls:
        safe_print(f"  - {u}")

    if args.debug:
        (DEBUG_DIR / f"{slug}_reference.txt").write_text(reference_text, encoding="utf-8")
        (DEBUG_DIR / f"{slug}_urls.txt").write_text("\n".join(used_urls), encoding="utf-8")
        (DEBUG_DIR / f"{slug}_status.txt").write_text(reference_status, encoding="utf-8")
        safe_print(f"[DEBUG] debug保存: {DEBUG_DIR}")

    safe_print("[2/6] 本文生成処理...")
    if len(used_urls) == 0:
        # 重要要件: 参照0件時はAI推測禁止
        md_article = build_no_reference_article(title)
    else:
        md_article = call_ollama_generate_article(title, reference_status, reference_text)

    safe_print("[3/6] 参照レポートを記事末尾へ追加...")
    md_article = append_reference_report(md_article, reference_status, used_urls, reference_text)

    safe_print("[4/6] HTMLへ変換...")
    article_html_body = markdown_to_html_simple(md_article)

    safe_print("[5/6] 記事保存...")
    article_full_html = render_article_html(
        title=title, date_str=date_str, article_html=article_html_body, slug=slug
    )
    post_file = POSTS_DIR / f"{slug}.html"
    article_full_html = f"<!--TITLE:{title}-->\n<!--DATE:{date_str}-->\n" + article_full_html
    post_file.write_text(article_full_html, encoding="utf-8")
    safe_print(f"[OK] 保存: {post_file}")

    safe_print("[6/6] index.html更新...")
    posts = load_posts_metadata()
    INDEX_FILE.write_text(render_index_html(posts), encoding="utf-8")
    safe_print(f"[OK] 更新: {INDEX_FILE}")

    if not args.no_push:
        git_auto_push(f"Add post with reference status: {title}")
    else:
        safe_print("[SKIP] --no-push のためpushしません。")

    safe_print("完了しました。")


if __name__ == "__main__":
    main()
