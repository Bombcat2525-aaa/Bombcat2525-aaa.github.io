#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI自動ブログ生成スクリプト
=========================
Ollama APIを使って日本語の記事を自動生成し、
GitHub Pagesにデプロイするための静的HTMLファイルを作成します。

使い方:
    python generate.py [テーマ] [オプション]

例:
    python generate.py "Pythonプログラミング入門"
    python generate.py "機械学習とは" --model llama3
    python generate.py --list-models
"""

import os
import sys
import json
import re
import argparse
import subprocess
import datetime
import unicodedata
from pathlib import Path

# --- 外部ライブラリ（requests）---
try:
    import requests
except ImportError:
    print("エラー: 'requests' ライブラリがインストールされていません。")
    print("以下のコマンドを実行してインストールしてください:")
    print("  pip install -r requirements.txt")
    sys.exit(1)

# ============================================================
# 設定項目 - 必要に応じて変更してください
# ============================================================

# Ollama APIのベースURL（ローカルで起動している場合はそのまま）
OLLAMA_BASE_URL = "http://localhost:11434"

# デフォルトで使用するモデル名
DEFAULT_MODEL = "llama3"

# 生成記事の最低文字数
MIN_ARTICLE_CHARS = 2000

# postsフォルダのパス（スクリプトと同じ階層に作成）
POSTS_DIR = Path(__file__).parent / "posts"

# テンプレートフォルダのパス
TEMPLATES_DIR = Path(__file__).parent / "templates"

# index.htmlのパス
INDEX_HTML = Path(__file__).parent / "index.html"

# サイトのベースURL（GitHub Pagesの場合は自分のURLに変更）
SITE_BASE_URL = "https://your-username.github.io"

# サイトタイトル
SITE_TITLE = "AI自動生成ブログ"

# サイトの説明
SITE_DESCRIPTION = "Ollama AIが自動生成する日本語技術ブログ"


# ============================================================
# ユーティリティ関数
# ============================================================

def slugify(text: str) -> str:
    """
    テキストをURLに使えるスラッグ形式に変換します。
    日本語はローマ字に変換せず、英数字とハイフンのみ残します。
    日本語タイトルはタイムスタンプベースのスラッグを使用します。

    Args:
        text: 変換するテキスト

    Returns:
        URLに安全なスラッグ文字列
    """
    # ASCII文字のみ抽出して小文字化
    ascii_text = ""
    for char in text:
        # Unicode正規化
        normalized = unicodedata.normalize("NFKD", char)
        # ASCII範囲の文字のみ追加
        if ord(normalized[0]) < 128:
            ascii_text += normalized[0]

    # 英数字とハイフンのみ残す
    ascii_text = re.sub(r"[^a-zA-Z0-9\s-]", "", ascii_text)
    ascii_text = re.sub(r"\s+", "-", ascii_text.strip())
    ascii_text = re.sub(r"-+", "-", ascii_text).lower()

    # 英字スラッグが短すぎる場合（日本語タイトルが多い場合）はタイムスタンプを使用
    if len(ascii_text) < 3:
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        ascii_text = f"article-{timestamp}"

    return ascii_text


def check_ollama_running() -> bool:
    """
    Ollamaが起動しているか確認します。

    Returns:
        Ollamaが起動していれば True、そうでなければ False
    """
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.ConnectionError:
        return False
    except requests.Timeout:
        return False


def list_available_models() -> list:
    """
    Ollamaで利用可能なモデルの一覧を取得します。

    Returns:
        モデル名のリスト
    """
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
        response.raise_for_status()
        data = response.json()
        models = [m["name"] for m in data.get("models", [])]
        return models
    except requests.ConnectionError:
        print("エラー: Ollamaに接続できません。Ollamaが起動しているか確認してください。")
        print("  起動コマンド: ollama serve")
        return []
    except Exception as e:
        print(f"エラー: モデル一覧の取得に失敗しました: {e}")
        return []


def generate_article_with_ollama(topic: str, model: str = DEFAULT_MODEL) -> str:
    """
    Ollama APIを使って指定トピックの日本語記事を生成します。

    Args:
        topic: 記事のトピック（例: "Pythonプログラミング入門"）
        model: 使用するOllamaモデル名

    Returns:
        生成された記事のMarkdown文字列

    Raises:
        SystemExit: API呼び出しに失敗した場合
    """
    print(f"\n📝 記事を生成中... (モデル: {model})")
    print(f"   トピック: {topic}")
    print("   しばらくお待ちください...\n")

    # Ollamaに送るプロンプトを構築
    prompt = f"""あなたは日本語の技術ブログ記事を書く専門家です。
以下のトピックについて、初心者向けの詳しい日本語記事を書いてください。

トピック: {topic}

記事の要件:
1. 2000文字以上の詳しい内容
2. 以下の見出し構造を必ず使う:
   # (h1) - 記事タイトル（1つだけ）
   ## (h2) - 主要なセクション（3〜5個）
   ### (h3) - サブセクション（各h2に1〜3個）
3. 初心者向けに丁寧でわかりやすい説明
4. 具体的な例やコードを交える
5. 最後に「まとめ」セクションを入れる
6. 自然で読みやすい日本語を使う
7. 専門用語は必ず説明する

記事をMarkdown形式で書いてください。記事のみを出力し、前置きは不要です。"""

    # Ollama APIにリクエストを送信
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,  # ストリーミングなし（全文一括取得）
        "options": {
            "temperature": 0.7,   # 創造性の度合い（0〜1）
            "num_predict": 4096,  # 最大トークン数
        }
    }

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=300  # タイムアウト: 5分（大きなモデルは時間がかかります）
        )
        response.raise_for_status()
    except requests.ConnectionError:
        print("エラー: Ollamaに接続できません。")
        print("以下を確認してください:")
        print("  1. Ollamaがインストールされているか: https://ollama.ai")
        print("  2. Ollamaが起動しているか: ollama serve")
        print(f"  3. {OLLAMA_BASE_URL} でアクセスできるか")
        sys.exit(1)
    except requests.Timeout:
        print("エラー: Ollamaの応答がタイムアウトしました（5分）。")
        print("モデルが重い場合はより軽いモデルを試してください。")
        print("例: python generate.py \"トピック\" --model llama3:8b")
        sys.exit(1)
    except requests.HTTPError as e:
        if response.status_code == 404:
            print(f"エラー: モデル '{model}' が見つかりません。")
            print(f"利用可能なモデルを確認: python generate.py --list-models")
            print(f"モデルのダウンロード: ollama pull {model}")
        else:
            print(f"エラー: APIリクエストに失敗しました: {e}")
        sys.exit(1)

    # レスポンスから記事テキストを取得
    data = response.json()
    article_text = data.get("response", "").strip()

    if not article_text:
        print("エラー: 記事の生成に失敗しました（空のレスポンス）。")
        sys.exit(1)

    # 文字数チェック
    char_count = len(article_text)
    print(f"✅ 記事生成完了！ ({char_count}文字)")

    if char_count < MIN_ARTICLE_CHARS:
        print(f"⚠️  警告: 生成された記事が{MIN_ARTICLE_CHARS}文字未満です（{char_count}文字）。")
        print("   より長い記事が必要な場合は、再実行してみてください。")

    return article_text


def markdown_to_html(markdown_text: str) -> tuple:
    """
    Markdownテキストを基本的なHTMLに変換します。
    （外部ライブラリなしの簡易実装）

    Args:
        markdown_text: Markdown形式のテキスト

    Returns:
        (html_body, title) のタプル
        html_body: HTML形式の本文
        title: 記事タイトル（最初のh1から取得）
    """
    lines = markdown_text.split("\n")
    html_lines = []
    title = ""
    in_code_block = False
    code_language = ""
    code_lines = []
    in_list = False
    in_ordered_list = False

    for i, line in enumerate(lines):
        # コードブロックの処理
        if line.startswith("```"):
            if in_code_block:
                # コードブロック終了
                code_content = "\n".join(code_lines)
                # HTMLエスケープ
                code_content = (code_content
                                .replace("&", "&amp;")
                                .replace("<", "&lt;")
                                .replace(">", "&gt;"))
                lang_class = f' class="language-{code_language}"' if code_language else ""
                html_lines.append(f'<pre><code{lang_class}>{code_content}</code></pre>')
                in_code_block = False
                code_lines = []
                code_language = ""
            else:
                # コードブロック開始
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                if in_ordered_list:
                    html_lines.append("</ol>")
                    in_ordered_list = False
                in_code_block = True
                code_language = line[3:].strip()
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # リスト終了チェック
        if in_list and not line.startswith("- ") and not line.startswith("* "):
            html_lines.append("</ul>")
            in_list = False
        if in_ordered_list and not re.match(r"^\d+\.", line):
            html_lines.append("</ol>")
            in_ordered_list = False

        # 空行の処理
        if not line.strip():
            html_lines.append("")
            continue

        # 見出しの処理
        if line.startswith("# "):
            heading_text = apply_inline_formatting(line[2:].strip())
            if not title:
                title = line[2:].strip()  # 最初のh1をタイトルとして使用
            html_lines.append(f"<h1>{heading_text}</h1>")
        elif line.startswith("## "):
            heading_text = apply_inline_formatting(line[3:].strip())
            html_lines.append(f"<h2>{heading_text}</h2>")
        elif line.startswith("### "):
            heading_text = apply_inline_formatting(line[4:].strip())
            html_lines.append(f"<h3>{heading_text}</h3>")
        elif line.startswith("#### "):
            heading_text = apply_inline_formatting(line[5:].strip())
            html_lines.append(f"<h4>{heading_text}</h4>")

        # 箇条書きリスト
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item_text = apply_inline_formatting(line[2:].strip())
            html_lines.append(f"  <li>{item_text}</li>")

        # 番号付きリスト
        elif re.match(r"^\d+\.", line):
            if not in_ordered_list:
                html_lines.append("<ol>")
                in_ordered_list = True
            item_text = apply_inline_formatting(re.sub(r"^\d+\.\s*", "", line))
            html_lines.append(f"  <li>{item_text}</li>")

        # 引用
        elif line.startswith("> "):
            quote_text = apply_inline_formatting(line[2:].strip())
            html_lines.append(f"<blockquote><p>{quote_text}</p></blockquote>")

        # 水平線
        elif line.strip() in ("---", "***", "___"):
            html_lines.append("<hr>")

        # 通常の段落
        else:
            formatted_line = apply_inline_formatting(line)
            html_lines.append(f"<p>{formatted_line}</p>")

    # 未閉じのリストを閉じる
    if in_list:
        html_lines.append("</ul>")
    if in_ordered_list:
        html_lines.append("</ol>")

    html_body = "\n".join(html_lines)
    return html_body, title


def apply_inline_formatting(text: str) -> str:
    """
    インライン要素（太字、斜体、コード、リンク）をHTMLに変換します。

    Args:
        text: 変換するテキスト

    Returns:
        HTML形式に変換されたテキスト
    """
    # HTMLエスケープ（コードブロック以外）
    # 注意: コードブロックは別処理なので、ここでは行内コードのみ
    # 先にバッククォートを処理してからエスケープ

    # 行内コード（バッククォート）
    def replace_code(match):
        code_text = match.group(1)
        code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<code>{code_text}</code>"

    # リンク [text](url)
    def replace_link(match):
        link_text = match.group(1)
        link_url = match.group(2)
        return f'<a href="{link_url}" target="_blank" rel="noopener noreferrer">{link_text}</a>'

    # 処理順序: コード → 太字斜体 → 太字 → 斜体 → リンク
    text = re.sub(r"`([^`]+)`", replace_code, text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", replace_link, text)

    return text


def extract_title_from_markdown(markdown_text: str) -> str:
    """
    Markdownテキストから最初のh1見出しをタイトルとして抽出します。

    Args:
        markdown_text: Markdown形式のテキスト

    Returns:
        タイトル文字列（見つからない場合はデフォルト値）
    """
    for line in markdown_text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return "無題の記事"


def extract_description_from_markdown(markdown_text: str) -> str:
    """
    Markdownテキストから最初の段落をdescriptionとして抽出します（SEO用）。

    Args:
        markdown_text: Markdown形式のテキスト

    Returns:
        説明文字列（最大200文字）
    """
    in_heading = False
    for line in markdown_text.split("\n"):
        # 見出し・コードブロック・空行をスキップ
        if not line.strip() or line.startswith("#") or line.startswith("```"):
            continue
        if line.startswith("-") or line.startswith("*") or re.match(r"^\d+\.", line):
            continue
        # 通常テキストを説明として使用
        description = line.strip()
        # Markdownの装飾を除去
        description = re.sub(r"\*+(.+?)\*+", r"\1", description)
        description = re.sub(r"`(.+?)`", r"\1", description)
        description = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", description)
        # 200文字に制限
        if len(description) > 200:
            description = description[:197] + "..."
        return description
    return SITE_DESCRIPTION


def generate_html_from_template(
    title: str,
    html_body: str,
    description: str,
    date_str: str,
    article_slug: str
) -> str:
    """
    テンプレートを読み込んで記事HTMLを生成します。

    Args:
        title: 記事タイトル
        html_body: HTML形式の記事本文
        description: SEO用の記事説明
        date_str: 公開日（YYYY-MM-DD形式）
        article_slug: URLスラッグ

    Returns:
        完成したHTML文字列
    """
    template_path = TEMPLATES_DIR / "article_template.html"

    if not template_path.exists():
        print(f"エラー: テンプレートファイルが見つかりません: {template_path}")
        print("テンプレートフォルダが正しい場所にあるか確認してください。")
        sys.exit(1)

    # テンプレートを読み込み
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # プレースホルダーを実際の値に置換
    html = template
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{DESCRIPTION}}", description)
    html = html.replace("{{BODY}}", html_body)
    html = html.replace("{{DATE}}", date_str)
    html = html.replace("{{SITE_TITLE}}", SITE_TITLE)
    html = html.replace("{{SITE_BASE_URL}}", SITE_BASE_URL)
    html = html.replace("{{ARTICLE_URL}}", f"{SITE_BASE_URL}/posts/{article_slug}.html")

    return html


def save_article(html_content: str, slug: str) -> Path:
    """
    記事HTMLをpostsフォルダに保存します。

    Args:
        html_content: 保存するHTML文字列
        slug: ファイル名（拡張子なし）

    Returns:
        保存したファイルのPath
    """
    # postsフォルダが存在しない場合は作成
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    # ファイルパスを生成
    file_path = POSTS_DIR / f"{slug}.html"

    # 同名ファイルが存在する場合はタイムスタンプを付加
    if file_path.exists():
        timestamp = datetime.datetime.now().strftime("%H%M%S")
        file_path = POSTS_DIR / f"{slug}-{timestamp}.html"

    # ファイルに書き込み
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ 記事を保存しました: {file_path}")
    return file_path


def update_index_html(title: str, description: str, date_str: str, article_path: Path) -> None:
    """
    index.htmlに新しい記事のリンクを追加します。
    記事一覧は日付の新しい順（降順）に表示されます。

    Args:
        title: 記事タイトル
        description: 記事の説明
        date_str: 公開日（YYYY-MM-DD形式）
        article_path: 保存した記事ファイルのPath
    """
    # postsフォルダからの相対パスを計算
    relative_path = article_path.relative_to(INDEX_HTML.parent)

    # 新しい記事のHTMLカード
    new_article_card = f"""    <!-- 記事: {title} ({date_str}) -->
    <article class="article-card">
      <div class="article-meta">
        <time datetime="{date_str}">{date_str}</time>
      </div>
      <h2 class="article-title">
        <a href="{relative_path}">{title}</a>
      </h2>
      <p class="article-excerpt">{description}</p>
      <a href="{relative_path}" class="read-more">続きを読む →</a>
    </article>"""

    if INDEX_HTML.exists():
        # 既存のindex.htmlに記事を追記
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            content = f.read()

        # <!-- ARTICLES_LIST --> マーカーを探して記事を挿入
        marker = "<!-- ARTICLES_LIST -->"
        if marker in content:
            content = content.replace(marker, f"{marker}\n{new_article_card}")
            with open(INDEX_HTML, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✅ index.htmlを更新しました")
        else:
            print("⚠️  警告: index.htmlに <!-- ARTICLES_LIST --> マーカーが見つかりません。")
            print("   手動でindex.htmlに記事を追加してください。")
    else:
        # index.htmlが存在しない場合はテンプレートから生成
        print("📄 index.htmlが見つかりません。テンプレートから生成します...")
        create_index_html_from_template(
            [{"title": title, "description": description, "date": date_str,
              "path": str(relative_path)}]
        )


def create_index_html_from_template(articles: list) -> None:
    """
    テンプレートからindex.htmlを新規生成します。

    Args:
        articles: 記事情報のリスト（各要素はdict: title, description, date, path）
    """
    template_path = TEMPLATES_DIR / "index_template.html"

    if not template_path.exists():
        print(f"エラー: インデックステンプレートが見つかりません: {template_path}")
        sys.exit(1)

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # 記事リストHTMLを生成
    articles_html = ""
    for article in articles:
        articles_html += f"""    <article class="article-card">
      <div class="article-meta">
        <time datetime="{article['date']}">{article['date']}</time>
      </div>
      <h2 class="article-title">
        <a href="{article['path']}">{article['title']}</a>
      </h2>
      <p class="article-excerpt">{article['description']}</p>
      <a href="{article['path']}" class="read-more">続きを読む →</a>
    </article>\n"""

    # プレースホルダーを置換
    html = template
    html = html.replace("{{SITE_TITLE}}", SITE_TITLE)
    html = html.replace("{{SITE_DESCRIPTION}}", SITE_DESCRIPTION)
    html = html.replace("{{ARTICLES_LIST}}", articles_html)
    html = html.replace("{{SITE_BASE_URL}}", SITE_BASE_URL)

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ index.htmlを生成しました: {INDEX_HTML}")


def git_push(commit_message: str) -> bool:
    """
    変更をGitでコミットしてGitHubにプッシュします。

    Args:
        commit_message: コミットメッセージ

    Returns:
        成功した場合は True、失敗した場合は False
    """
    repo_dir = Path(__file__).parent

    print("\n🔄 GitHubへプッシュ中...")

    try:
        # git add - すべての変更をステージング
        result = subprocess.run(
            ["git", "add", "."],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if result.returncode != 0:
            print(f"エラー: git add に失敗しました: {result.stderr}")
            return False

        # git commit
        result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if result.returncode != 0:
            # コミットするものがない場合も returncode != 0 になることがある
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print("⚠️  コミットするものがありません（変更なし）。")
                return True
            print(f"エラー: git commit に失敗しました: {result.stderr}")
            return False

        print(f"   コミット: {commit_message}")

        # git push
        result = subprocess.run(
            ["git", "push"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if result.returncode != 0:
            print(f"エラー: git push に失敗しました: {result.stderr}")
            print("以下を確認してください:")
            print("  1. GitHubのリポジトリURLが正しく設定されているか")
            print("  2. SSH鍵またはGitHubトークンが設定されているか")
            print("  3. リモートリポジトリが正しく設定されているか: git remote -v")
            return False

        print("✅ GitHubへのプッシュが完了しました！")
        return True

    except FileNotFoundError:
        print("エラー: gitコマンドが見つかりません。")
        print("Gitがインストールされているか確認してください: https://git-scm.com")
        return False
    except Exception as e:
        print(f"エラー: Gitの操作中にエラーが発生しました: {e}")
        return False


# ============================================================
# メイン処理
# ============================================================

def main():
    """
    メイン処理：コマンドライン引数を解析して記事生成を実行します。
    """
    # コマンドライン引数の設定
    parser = argparse.ArgumentParser(
        description="AI自動ブログ記事生成ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python generate.py "Pythonプログラミング入門"
  python generate.py "機械学習とは" --model llama3
  python generate.py "Dockerの使い方" --no-push
  python generate.py --list-models
        """
    )

    parser.add_argument(
        "topic",
        nargs="?",
        help="記事のトピック（例: 'Pythonプログラミング入門'）"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"使用するOllamaモデル名（デフォルト: {DEFAULT_MODEL}）"
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="GitHubへのプッシュをスキップする"
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="利用可能なOllamaモデルの一覧を表示する"
    )

    args = parser.parse_args()

    # モデル一覧表示モード
    if args.list_models:
        print("利用可能なOllamaモデル:")
        if not check_ollama_running():
            print("エラー: Ollamaが起動していません。")
            print("起動コマンド: ollama serve")
            sys.exit(1)
        models = list_available_models()
        if models:
            for model in models:
                print(f"  - {model}")
        else:
            print("  モデルが見つかりません。")
            print("  モデルのダウンロード例: ollama pull llama3")
        sys.exit(0)

    # トピックが指定されていない場合はエラー
    if not args.topic:
        print("エラー: 記事のトピックを指定してください。")
        print("使い方: python generate.py \"記事のトピック\"")
        print("ヘルプ: python generate.py --help")
        sys.exit(1)

    # Ollamaが起動しているか確認
    print("🔍 Ollamaの接続を確認中...")
    if not check_ollama_running():
        print("エラー: Ollamaが起動していません。")
        print("以下の手順でOllamaを起動してください:")
        print("  1. Ollamaをインストール: https://ollama.ai")
        print("  2. Ollamaを起動: ollama serve")
        print(f"  3. モデルをダウンロード: ollama pull {args.model}")
        sys.exit(1)
    print("✅ Ollamaに接続しました")

    # 現在の日時を取得
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    # ===== ステップ1: 記事生成 =====
    markdown_text = generate_article_with_ollama(args.topic, args.model)

    # ===== ステップ2: タイトルとスラッグを生成 =====
    title = extract_title_from_markdown(markdown_text)
    if not title:
        title = args.topic

    description = extract_description_from_markdown(markdown_text)
    slug = slugify(title)
    if not slug or slug == f"article-{timestamp}":
        # タイムスタンプベースのスラッグを使用
        slug = f"article-{timestamp}"

    print(f"\n📌 記事情報:")
    print(f"   タイトル: {title}")
    print(f"   スラッグ:  {slug}")
    print(f"   日付:     {date_str}")

    # ===== ステップ3: MarkdownをHTMLに変換 =====
    html_body, _ = markdown_to_html(markdown_text)

    # ===== ステップ4: テンプレートに挿入してHTML生成 =====
    html_content = generate_html_from_template(
        title=title,
        html_body=html_body,
        description=description,
        date_str=date_str,
        article_slug=slug
    )

    # ===== ステップ5: ファイルに保存 =====
    article_path = save_article(html_content, slug)

    # ===== ステップ6: index.htmlを更新 =====
    update_index_html(title, description, date_str, article_path)

    # ===== ステップ7: GitHubへプッシュ =====
    if not args.no_push:
        commit_message = f"記事追加: {title} ({date_str})"
        success = git_push(commit_message)
        if success:
            print(f"\n🎉 完了！記事が公開されました。")
            print(f"   URL: {SITE_BASE_URL}/posts/{article_path.name}")
        else:
            print("\n⚠️  GitHubへのプッシュに失敗しました。")
            print("   手動でプッシュしてください: git push")
    else:
        print("\n✅ 記事の生成が完了しました（プッシュはスキップしました）。")
        print(f"   ファイル: {article_path}")
        print("   プッシュするには: git push")


if __name__ == "__main__":
    main()
