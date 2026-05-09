# AI自動ブログ生成システム

PythonとOllama APIを使って、日本語の技術ブログ記事を自動生成し、GitHub Pagesに公開するシステムです。

---

## 📋 機能一覧

- **Ollama APIによる日本語記事自動生成** - ローカルで動作するAIモデルを使用
- **SEO対応HTML生成** - メタタグ・OGP・正規URL対応
- **h1/h2/h3構造の記事** - 読みやすい見出し構造
- **postsフォルダへ自動保存** - 記事ファイルを整理して保存
- **index.htmlへ記事一覧自動追加** - トップページに新着記事を追加
- **GitHubへ自動push** - 記事生成後に自動でデプロイ
- **Windows/Mac/Linux対応** - Pythonのみで動作

---

## 🗂️ ファイル構成

```
.
├── generate.py                  # メインスクリプト（記事生成・デプロイ）
├── requirements.txt             # Python依存ライブラリ
├── index.html                   # ブログトップページ
├── posts/                       # 生成された記事HTMLファイル
│   └── *.html
├── templates/
│   ├── article_template.html    # 記事ページのHTMLテンプレート
│   └── index_template.html      # インデックスページのHTMLテンプレート
└── README.md                    # このファイル
```

---

## 🚀 セットアップ

### 1. 前提条件

- **Python 3.8以上** がインストールされていること
- **Git** がインストールされていること
- **Ollama** がインストールされていること

### 2. Ollamaのインストールと起動

```bash
# Ollamaをインストール（公式サイト参照）
# https://ollama.ai

# モデルをダウンロード（例: llama3）
ollama pull llama3

# Ollamaサーバーを起動
ollama serve
```

### 3. このリポジトリをクローン

```bash
git clone https://github.com/your-username/your-username.github.io.git
cd your-username.github.io
```

### 4. Pythonライブラリのインストール

```bash
pip install -r requirements.txt
```

### 5. generate.pyの設定を変更

`generate.py` を開いて、以下の設定項目を変更してください：

```python
# サイトのベースURL（自分のGitHub PagesのURLに変更）
SITE_BASE_URL = "https://your-username.github.io"

# サイトタイトル（任意）
SITE_TITLE = "AI自動生成ブログ"

# 使用するOllamaモデル（pullしたモデルを指定）
DEFAULT_MODEL = "llama3"
```

---

## 💻 使い方

### 基本的な使い方

```bash
# 記事のトピックを指定して実行
python generate.py "Pythonプログラミング入門"

# 別のモデルを指定する場合
python generate.py "機械学習とは" --model llama3:8b

# GitHubへのプッシュをスキップする場合
python generate.py "Dockerの使い方" --no-push

# 利用可能なモデル一覧を表示
python generate.py --list-models

# ヘルプを表示
python generate.py --help
```

### 実行の流れ

1. `generate.py` がOllama APIに記事生成を依頼
2. 生成されたMarkdownをHTMLに変換
3. `posts/` フォルダに記事HTMLを保存
4. `index.html` に記事一覧を追加
5. `git add`, `git commit`, `git push` を自動実行
6. GitHub Pagesにデプロイ完了 🎉

---

## 📄 生成される記事の条件

- **2000文字以上** の本文
- **h1/h2/h3の見出し構造** でわかりやすく整理
- **初心者向け** の丁寧な説明
- **具体的な例やコード** を交えた内容
- 最後に **「まとめ」セクション** を含む
- **自然で読みやすい日本語**

---

## 🔧 コマンドラインオプション

| オプション | 説明 | 例 |
|-----------|------|-----|
| `topic` | 記事のトピック（必須） | `"Pythonプログラミング入門"` |
| `--model` | 使用するOllamaモデル | `--model llama3` |
| `--no-push` | GitHubへのプッシュをスキップ | `--no-push` |
| `--list-models` | 利用可能なモデル一覧を表示 | `--list-models` |
| `--help` | ヘルプを表示 | `--help` |

---

## ⚠️ よくあるエラーと対処法

### Ollamaに接続できない

```
エラー: Ollamaに接続できません。
```

**対処法:**
1. `ollama serve` でOllamaを起動してください
2. ブラウザで `http://localhost:11434` にアクセスできるか確認

### モデルが見つからない

```
エラー: モデル 'llama3' が見つかりません。
```

**対処法:**
1. `ollama pull llama3` でモデルをダウンロードしてください
2. `python generate.py --list-models` で利用可能なモデルを確認

### GitHubへのプッシュが失敗する

```
エラー: git push に失敗しました
```

**対処法:**
1. GitHubのSSH鍵またはPersonal Access Tokenが設定されているか確認
2. `git remote -v` でリモートURLが正しいか確認

### requestsがインストールされていない

```
エラー: 'requests' ライブラリがインストールされていません。
```

**対処法:**
```bash
pip install -r requirements.txt
```

---

## 🌐 GitHub Pagesの設定

1. GitHubのリポジトリページを開く
2. **Settings** → **Pages** を開く
3. **Source** を `Deploy from a branch` に設定
4. **Branch** を `main`（または `master`）の `/` (root) に設定
5. **Save** をクリック

数分後に `https://your-username.github.io` でブログが公開されます。

---

## 📝 ライセンス

MIT License

---

## 🤝 貢献

バグ報告や機能追加のリクエストはIssueやPull Requestでお知らせください。