# -*- coding: utf-8 -*-
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import feedparser
from flask import Flask, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
POSTS_DIR = BASE_DIR / "posts"
DELETED_DIR = BASE_DIR / "deleted_posts"

CONFIG_FILE = BASE_DIR / "config.json"
TRENDING_FILE = BASE_DIR / "trending_words.json"
AFFILIATE_FILE = BASE_DIR / "affiliate_products.json"
LOGS_FILE = BASE_DIR / "logs.json"
DELETED_META_FILE = BASE_DIR / "deleted_posts.json"
NEWS_SOURCES_FILE = BASE_DIR / "news_sources.json"

INDEX_FILE = BASE_DIR / "index.html"

SITE_URL = "https://bombcat2525-aaa.github.io/"
REPO_URL = "https://github.com/Bombcat2525-aaa/Bombcat2525-aaa.github.io"

INTERVAL_OPTIONS = [
    ("5m", "5分ごと"),
    ("15m", "15分ごと"),
    ("30m", "30分ごと"),
    ("1h", "1時間ごと"),
    ("3h", "3時間ごと"),
    ("6h", "6時間ごと"),
    ("12h", "12時間ごと"),
    ("1d", "1日ごと"),
]

app = Flask(__name__)
app.secret_key = "local-dev-secret"


def read_json(path: Path, default):
    if not path.exists():
        write_json(path, default)
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log(status: str, title: str = "", used_keywords=None, used_product="", error=""):
    used_keywords = used_keywords or []
    logs = read_json(LOGS_FILE, [])
    if isinstance(logs, dict):
        logs = logs.get("logs", [])
    logs.insert(0, {
        "executed_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "used_keywords": used_keywords,
        "used_product": used_product,
        "status": status,
        "error": error,
    })
    write_json(LOGS_FILE, logs[:300])


def load_config():
    default = {
        "auto_post_enabled": False,
        "post_frequency": "1d",
        "article_source_mode": "auto_keyword",  # auto_keyword or manual_title
        "manual_title": "",
        "warning_message": "5分ごとの投稿はテスト用です。通常運用では1日1記事を推奨します。",
        "last_run_at": None,
        "last_keyword_update_at": None,
    }
    cfg = read_json(CONFIG_FILE, default)
    for k, v in default.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    write_json(CONFIG_FILE, cfg)


def load_trending():
    data = read_json(TRENDING_FILE, [])
    if isinstance(data, dict):
        words = data.get("words", [])
    else:
        words = data
    normalized = []
    for item in words:
        if isinstance(item, dict) and item.get("word"):
            normalized.append({"word": str(item["word"]), "score": int(item.get("score", 1))})
    return normalized


def save_trending(words):
    # list形式で保存（既存との互換優先）
    write_json(TRENDING_FILE, words)


def load_affiliate():
    data = read_json(AFFILIATE_FILE, [])
    if isinstance(data, dict):
        return data.get("products", [])
    return data


def save_affiliate(products):
    write_json(AFFILIATE_FILE, products)


def load_deleted_meta():
    data = read_json(DELETED_META_FILE, [])
    return data if isinstance(data, list) else []


def save_deleted_meta(items):
    write_json(DELETED_META_FILE, items)


def safe_git_update():
    try:
        subprocess.run(["git", "pull", "origin", "main"], cwd=str(BASE_DIR), check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=str(BASE_DIR), check=True, capture_output=True, text=True)
        commit = subprocess.run(
            ["git", "commit", "-m", "Update posts"],
            cwd=str(BASE_DIR),
            check=False,
            capture_output=True,
            text=True
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE_DIR), check=True, capture_output=True, text=True)
        return True, commit.stdout.strip() or "updated"
    except subprocess.CalledProcessError as e:
        msg = f"Git競合または通信エラー: {e.stderr or e.stdout or str(e)}"
        append_log("failed", error=msg)
        return False, msg


def load_posts():
    POSTS_DIR.mkdir(exist_ok=True)
    posts = []
    for p in sorted(POSTS_DIR.glob("*.html"), reverse=True):
        text = p.read_text(encoding="utf-8", errors="ignore")
        title_m = re.search(r"<!--TITLE:(.*?)-->", text)
        date_m = re.search(r"<!--DATE:(.*?)-->", text)
        title = title_m.group(1).strip() if title_m else p.stem
        date = date_m.group(1).strip() if date_m else ""
        posts.append({
            "title": title,
            "date": date,
            "filename": p.name,
            "path": str(p),
            "url": f"{SITE_URL}posts/{quote(p.name)}",
        })
    return posts


def regenerate_index_only():
    import generate  # 既存の関数を再利用
    posts = generate.load_posts_metadata()
    html = generate.render_index_html(posts)
    INDEX_FILE.write_text(html, encoding="utf-8")


def choose_auto_title():
    words = sorted(load_trending(), key=lambda x: int(x.get("score", 0)), reverse=True)
    approved_products = [p for p in load_affiliate() if p.get("approved")]

    top = words[0]["word"] if words else "AI"

    if approved_products:
        for p in approved_products:
            kws = p.get("related_keywords", [])
            for w in words:
                if w["word"] in kws:
                    return f"{w['word']}活用ガイド：{p.get('name','おすすめ商品')}を自然に使う方法", w["word"], p.get("name", "")
        p = approved_products[0]
        return f"{top}活用ガイド：{p.get('name','おすすめ商品')}を自然に使う方法", top, p.get("name", "")

    return f"{top}を仕事と生活に活かす実践ガイド", top, ""


def title_exists(title: str) -> bool:
    for post in load_posts():
        if post["title"].strip() == title.strip():
            return True
    return False


def run_generate(title: str, keyword: str):
    if title_exists(title):
        raise RuntimeError("同じタイトルの記事が既に存在します。")

    cmd = ["python", "generate.py", "--title", title, "--keyword", keyword]
    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(
            "記事生成スクリプトが失敗しました。\n"
            f"終了コード: {result.returncode}\n"
            f"STDERR:\n{stderr if stderr else '(なし)'}\n\n"
            f"STDOUT:\n{stdout if stdout else '(なし)'}"
        )


def update_keywords_from_rss():
    sources = read_json(NEWS_SOURCES_FILE, {"sources": []})
    source_list = sources if isinstance(sources, list) else sources.get("sources", [])

    words = load_trending()
    score_map = {w["word"]: int(w["score"]) for w in words}

    token_re = re.compile(r"[A-Za-z][A-Za-z0-9\+\.\-]{1,}|[一-龥ぁ-んァ-ヴー]{2,}")

    for src in source_list:
        url = src["url"] if isinstance(src, dict) else str(src)
        feed = feedparser.parse(url)
        for entry in feed.entries[:30]:
            title = (entry.get("title", "") or "").strip()
            for token in token_re.findall(title):
                stop = {"速報", "最新", "まとめ", "ニュース", "発表", "利用", "方法"}
                if token in stop:
                    continue
                score_map[token] = score_map.get(token, 0) + 1

    merged = [{"word": k, "score": v} for k, v in score_map.items()]
    merged.sort(key=lambda x: x["score"], reverse=True)
    save_trending(merged[:300])

    cfg = load_config()
    cfg["last_keyword_update_at"] = datetime.now().isoformat(timespec="seconds")
    save_config(cfg)


@app.route("/")
def dashboard():
    cfg = load_config()
    posts = load_posts()
    deleted = load_deleted_meta()[:5]
    trending = sorted(load_trending(), key=lambda x: x["score"], reverse=True)[:100]
    affiliate = load_affiliate()
    logs = read_json(LOGS_FILE, [])
    if isinstance(logs, dict):
        logs = logs.get("logs", [])
    return render_template(
        "dashboard.html",
        config=cfg,
        interval_options=INTERVAL_OPTIONS,
        site_url=SITE_URL,
        repo_url=REPO_URL,
        posts=posts,
        deleted_posts=deleted,
        trending=trending,
        affiliate_products=affiliate,
        logs=logs[:50],
    )


@app.post("/config/save")
def save_settings():
    cfg = load_config()
    cfg["auto_post_enabled"] = request.form.get("auto_post_enabled") == "on"
    cfg["post_frequency"] = request.form.get("post_frequency", "1d")
    cfg["article_source_mode"] = request.form.get("article_source_mode", "auto_keyword")
    cfg["manual_title"] = request.form.get("manual_title", "").strip()
    save_config(cfg)
    flash("設定を保存しました。", "success")
    return redirect(url_for("dashboard"))


@app.post("/generate-now")
def generate_now():
    cfg = load_config()
    mode = request.form.get("article_source_mode", cfg.get("article_source_mode", "auto_keyword"))
    manual_title = request.form.get("manual_title", "").strip() or cfg.get("manual_title", "")

    try:
        if mode == "manual_title":
            if not manual_title:
                raise RuntimeError("手動タイトルが未入力です。")
            title = manual_title
            keyword = manual_title
            used_product = ""
        else:
            title, keyword, used_product = choose_auto_title()

        run_generate(title, keyword)

        cfg["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        cfg["article_source_mode"] = mode
        cfg["manual_title"] = manual_title
        save_config(cfg)

        append_log("success", title=title, used_keywords=[keyword], used_product=used_product)
        flash("記事生成と投稿に成功しました。", "success")
    except Exception as e:
        append_log("failed", title=manual_title, error=str(e))
        flash(f"記事生成に失敗: {e}", "error")

    return redirect(url_for("dashboard"))


@app.post("/post/delete")
def delete_post():
    filename = request.form.get("filename", "").strip()
    target = POSTS_DIR / filename
    if not target.exists():
        flash("削除対象が見つかりません。", "error")
        return redirect(url_for("dashboard"))

    DELETED_DIR.mkdir(exist_ok=True)
    deleted_target = DELETED_DIR / filename

    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
        title_m = re.search(r"<!--TITLE:(.*?)-->", text)
        title = title_m.group(1).strip() if title_m else filename

        shutil.move(str(target), str(deleted_target))
        regenerate_index_only()

        meta = load_deleted_meta()
        meta.insert(0, {
            "filename": filename,
            "original_path": "posts/" + filename,
            "deleted_at": datetime.now().isoformat(timespec="seconds"),
            "title": title,
            "url": f"{SITE_URL}posts/{quote(filename)}",
        })
        save_deleted_meta(meta[:5])

        ok, msg = safe_git_update()
        if not ok:
            flash(msg, "error")
        else:
            flash("記事を削除（退避）しました。", "success")
    except Exception as e:
        append_log("failed", error=str(e))
        flash(f"削除失敗: {e}", "error")

    return redirect(url_for("dashboard"))


@app.post("/post/restore")
def restore_post():
    filename = request.form.get("filename", "").strip()
    src = DELETED_DIR / filename
    dst = POSTS_DIR / filename

    if not src.exists():
        flash("復元元が見つかりません。", "error")
        return redirect(url_for("dashboard"))

    try:
        shutil.move(str(src), str(dst))
        regenerate_index_only()

        meta = [m for m in load_deleted_meta() if m.get("filename") != filename]
        save_deleted_meta(meta[:5])

        ok, msg = safe_git_update()
        if not ok:
            flash(msg, "error")
        else:
            flash("記事を復元しました。", "success")
    except Exception as e:
        append_log("failed", error=str(e))
        flash(f"復元失敗: {e}", "error")

    return redirect(url_for("dashboard"))


@app.post("/keywords/update")
def update_keywords():
    try:
        update_keywords_from_rss()
        flash("キーワード更新が完了しました。", "success")
    except Exception as e:
        append_log("failed", error=str(e))
        flash(f"キーワード更新に失敗: {e}", "error")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    POSTS_DIR.mkdir(exist_ok=True)
    DELETED_DIR.mkdir(exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=True)
