# -*- coding: utf-8 -*-
"""
AI自動ブログ生成スクリプト (Pythonのみ)
- Ollama APIで日本語記事を生成
- SEO向けのHTML構造で記事ページを生成
- postsフォルダへ���存
- index.htmlへ記事一覧を自動追加
- Gitへ自動コミット・プッシュ
- Windows対応

使い方:
    python generate.py --title "Python初心者向け学習ロードマップ"

事前準備:
    1) Ollamaをインストールして起動
    2) モデルをpull (例: ollama pull qwen2.5:7b)
    3) このプロジェクトをgit管理下に置く
"""

import argparse
import datetime
import html
import os
import re
import subprocess
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader

# =========================
# 設定（必要に応じて変更）
# =========================
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"  # 日本語が比較的得意なモデル例
SITE_TITLE = "AI自動ブログ"
SITE_DESCRIPTION = "AIで記事を自動生成してGitHub Pagesに公開するブログ"

# ディレクトリ定義
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
POSTS_DIR = BASE_DIR / "posts"
INDEX_FILE = BASE_DIR / "index.html"

# Jinja2初期化
env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def slugify(text: str) -> str:
    """
    タイトルからURL用スラッグを生成する関数。
    日本語の場合は完全なローマ字変換が難しいため、
    日時ベースにして安全なファイル名を返す。
    """
    # 英数字のみ抽出（補助）
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    if ascii_part:
        return f"{timestamp}-{ascii_part[:30]}"
    return f"{timestamp}-jp-post"


def call_ollama_generate_article(title: str, keyword: str = "") -> str:
    """
    Ollama APIを呼び出して、SEO向けの日本語記事本文（Markdown）を生成する。
    記事条件:
      - 2000文字以上
      - h1/h2/h3構造
      - 自然な日本語
      - 最後にまとめ
    """
    # AIへの指示（プロンプト）
    # できるだけ要件を厳密に伝える
    prompt = f"""
あなたは日本語のSEOライターです。以下の条件を必ず守って、ブログ記事をMarkdown形式で出力してください。

# テーマ
{title}

# 補助キーワード
{keyword if keyword else "（なし）"}

# 必須条件
- 日本語で書く
- 2000文字以上
- 見出し構造は h1, h2, h3 を使う（Markdownで #, ##, ###）
- 読みやすく自然な日本語
- 初心者にも分かるように丁寧
- 具体例を含める
- 最後に「まとめ」セクションを作る
- 過度な誇張表現は避ける
- 冒頭で読者の悩みに共感する導入を入れる

# 出力形式
Markdown本文のみを返してください。余計な説明は不要です。
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    try:
        res = requests.post(OLLAMA_API_URL, json=payload, timeout=300)
        res.raise_for_status()
        data = res.json()

        article = data.get("response", "").strip()
        if not article:
            raise ValueError("Ollamaの応答が空です。")

        # 文字数不足時の簡易フォールバック（必要なら再生成）
        if len(article) < 2000:
            article += "\n\n## 追補\n上記内容をより深く理解するために、実践を繰り返すことが重要です。"

        return article

    except Exception as e:
        raise RuntimeError(
            f"Ollama APIの呼び出しに失敗しました: {e}\n"
            "Ollamaが起動しているか、モデル名が正しいか確認してください。"
        )


def markdown_to_html_simple(md_text: str) -> str:
    """
    MarkdownをシンプルにHTMLへ変換する関数。
    依存を少なくするため、最小限の変換を実装。
    （h1/h2/h3, 段落, 箇条書き）
    """
    lines = md_text.splitlines()
    html_lines = []
    in_ul = False

    for line in lines:
        s = line.strip()

        # 空行
        if not s:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            continue

        # 見出し
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

        # 箇条書き
        if s.startswith("- "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{html.escape(s[2:])}</li>")
            continue

        # 通常段落
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        html_lines.append(f"<p>{html.escape(s)}</p>")

    if in_ul:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def load_posts_metadata():
    """
    postsフォルダ内のHTML記事を走査し、メタ情報を抽出して一覧用に返す。
    ここではファイル先頭の簡易メタコメントからタイトル・日付を読む。
    """
    posts = []
    for p in sorted(POSTS_DIR.glob("*.html"), reverse=True):
        text = p.read_text(encoding="utf-8", errors="ignore")
        # メタコメント形式:
        # <!--TITLE:xxx-->
        # <!--DATE:yyyy-mm-dd-->
        title_match = re.search(r"<!--TITLE:(.*?)-->", text)
        date_match = re.search(r"<!--DATE:(.*?)-->", text)

        title = title_match.group(1).strip() if title_match else p.stem
        date = date_match.group(1).strip() if date_match else ""
        posts.append({
            "title": title,
            "date": date,
            "url": f"posts/{p.name}"
        })
    return posts


def render_article_html(title: str, date_str: str, article_html: str, slug: str) -> str:
    """
    記事テンプレートを使って最終HTMLを生成する。
    """
    template = env.get_template("article_template.html")
    return template.render(
        site_title=SITE_TITLE,
        site_description=SITE_DESCRIPTION,
        article_title=title,
        article_date=date_str,
        article_html=article_html,
        slug=slug
    )


def render_index_html(posts):
    """
    indexテンプレートを使ってトップページを生成する。
    """
    template = env.get_template("index_template.html")
    return template.render(
        site_title=SITE_TITLE,
        site_description=SITE_DESCRIPTION,
        posts=posts
    )


def git_auto_push(commit_message: str):
    """
    Gitに自動コミット＆プッシュする関数。
    失敗しても記事生成自体は成功扱いにしたいので、例外を握ってメッセージ表示。
    """
    try:
        subprocess.run(["git", "add", "."], check=True)
        # 変更がない場合のエラーを許容するため check=False
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            check=False,
            capture_output=True,
            text=True
        )

        # "nothing to commit" の場合でも push は試す
        subprocess.run(["git", "push"], check=True)

        print("[OK] Git push 完了")
        if commit_result.stdout:
            print(commit_result.stdout.strip())

    except Exception as e:
        print("[WARN] Git自動pushに失敗しました。手動でpushしてください。")
        print(f"       詳細: {e}")


def main():
    """
    メイン処理:
      1) 引数取得
      2) Ollamaで記事生成
      3) HTML変換してposts保存
      4) index.html再生成
      5) git push
    """
    parser = argparse.ArgumentParser(description="AI自動ブログ生成")
    parser.add_argument("--title", required=True, help="記事タイトル")
    parser.add_argument("--keyword", default="", help="SEO補助キーワード")
    parser.add_argument("--no-push", action="store_true", help="Git pushを無効化")
    args = parser.parse_args()

    # 必要フォルダ作成
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    title = args.title.strip()
    keyword = args.keyword.strip()
    date_str = datetime.date.today().isoformat()
    slug = slugify(title)

    print("[1/5] Ollamaで記事生成中...")
    md_article = call_ollama_generate_article(title, keyword)

    print("[2/5] MarkdownをHTMLへ変換中...")
    article_html_body = markdown_to_html_simple(md_article)

    print("[3/5] 記事ファイルを保存中...")
    article_full_html = render_article_html(
        title=title,
        date_str=date_str,
        article_html=article_html_body,
        slug=slug
    )

    post_file = POSTS_DIR / f"{slug}.html"
    # タイトルと日付をメタコメントとして埋め込み（一覧更新で使用）
    article_full_html = f"<!--TITLE:{title}-->\n<!--DATE:{date_str}-->\n" + article_full_html
    post_file.write_text(article_full_html, encoding="utf-8")
    print(f"[OK] 保存: {post_file}")

    print("[4/5] index.htmlを更新中...")
    posts = load_posts_metadata()
    index_html = render_index_html(posts)
    INDEX_FILE.write_text(index_html, encoding="utf-8")
    print(f"[OK] 更新: {INDEX_FILE}")

    print("[5/5] Gitへpush...")
    if not args.no_push:
        git_auto_push(f"Add new post: {title}")
    else:
        print("[SKIP] --no-push が指定されたためpushしません。")

    print("\n完了しました。GitHub Pagesの公開を確認してください。")


if __name__ == "__main__":
    main()
