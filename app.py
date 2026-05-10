# -*- coding: utf-8 -*-
import json
import subprocess
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
TRENDING_FILE = BASE_DIR / "trending_words.json"
AFFILIATE_FILE = BASE_DIR / "affiliate_products.json"
LOGS_FILE = BASE_DIR / "logs.json"

INTERVAL_OPTIONS = [
    "5分ごと", "15分ごと", "30分ごと", "1時間ごと",
    "3時間ごと", "6時間ごと", "12時間ごと", "1日ごと"
]

app = Flask(__name__)
app.secret_key = "local-panel-secret"


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


def load_config():
    default = {
        "auto_post_enabled": False,
        "post_interval": "1日ごと",
        "manual_mode": True,
        "git_conflict_detected": False,
        "warning_message": "5分ごとの投稿はテスト用です。通常運用では1日1記事を推奨します。",
        "last_run_at": None
    }
    cfg = read_json(CONFIG_FILE, default)
    for k, v in default.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    write_json(CONFIG_FILE, cfg)


def load_trending():
    data = read_json(TRENDING_FILE, [])
    if isinstance(data, dict) and "words" in data:
        return data["words"]
    if isinstance(data, list):
        return data
    return []


def save_trending(words):
    write_json(TRENDING_FILE, words)


def load_affiliates():
    data = read_json(AFFILIATE_FILE, [])
    if isinstance(data, dict) and "products" in data:
        return data["products"]
    if isinstance(data, list):
        return data
    return []


def save_affiliates(products):
    write_json(AFFILIATE_FILE, products)


def load_logs():
    data = read_json(LOGS_FILE, [])
    return data if isinstance(data, list) else []


def append_log(log_item):
    logs = load_logs()
    logs.insert(0, log_item)
    write_json(LOGS_FILE, logs[:200])


def choose_title_and_keyword():
    words = sorted(load_trending(), key=lambda x: int(x.get("score", 0)), reverse=True)
    affiliates = [p for p in load_affiliates() if p.get("approved")]

    top_word = words[0]["word"] if words else "AI"
    if affiliates:
        product = affiliates[0]
        title = f"{top_word}活用ガイド：{product.get('name', 'おすすめ商品')}をやさしく解説"
        keyword = ",".join(product.get("related_keywords", [])) or top_word
        used_product = product.get("name", "")
    else:
        title = f"{top_word}を日常で活かす入門ガイド"
        keyword = top_word
        used_product = ""
    return title, keyword, used_product


@app.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        config=load_config(),
        interval_options=INTERVAL_OPTIONS,
        trending_words=load_trending(),
        affiliate_products=load_affiliates(),
        logs=load_logs()[:30]
    )


@app.post("/config/save")
def config_save():
    cfg = load_config()
    cfg["auto_post_enabled"] = request.form.get("auto_post_enabled") == "on"
    interval = request.form.get("post_interval", "1日ごと")
    if interval in INTERVAL_OPTIONS:
        cfg["post_interval"] = interval
    save_config(cfg)
    flash("設定を保存しました。", "success")
    return redirect(url_for("dashboard"))


@app.post("/trending/add")
def trending_add():
    words = load_trending()
    word = request.form.get("word", "").strip()
    score = int(request.form.get("score", "1"))
    if word:
        words.append({"word": word, "score": score})
        save_trending(words)
        flash("関心ワードを追��しました。", "success")
    return redirect(url_for("dashboard"))


@app.post("/trending/delete")
def trending_delete():
    words = load_trending()
    idx = int(request.form.get("index", "-1"))
    if 0 <= idx < len(words):
        words.pop(idx)
        save_trending(words)
        flash("関心ワードを削除しました。", "success")
    return redirect(url_for("dashboard"))


@app.post("/affiliate/add")
def affiliate_add():
    products = load_affiliates()
    name = request.form.get("name", "").strip()
    url = request.form.get("affiliate_url", "").strip()
    if not name or not url:
        flash("商品名とURLは必須です。", "error")
        return redirect(url_for("dashboard"))

    products.append({
        "id": int(datetime.now().timestamp()),
        "name": name,
        "affiliate_url": url,
        "category": request.form.get("category", "").strip(),
        "related_keywords": [k.strip() for k in request.form.get("related_keywords", "").split(",") if k.strip()],
        "memo": request.form.get("memo", "").strip(),
        "asp_name": request.form.get("asp_name", "").strip(),
        "approved": request.form.get("approved") == "on"
    })
    save_affiliates(products)
    flash("商品を追加しました。", "success")
    return redirect(url_for("dashboard"))


@app.post("/affiliate/delete")
def affiliate_delete():
    products = load_affiliates()
    idx = int(request.form.get("index", "-1"))
    if 0 <= idx < len(products):
        products.pop(idx)
        save_affiliates(products)
        flash("商品を削除しました。", "success")
    return redirect(url_for("dashboard"))


@app.post("/generate/now")
def generate_now():
    title, keyword, used_product = choose_title_and_keyword()
    cmd = ["python", "generate.py", "--title", title, "--keyword", keyword]

    try:
        result = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, check=True)
        cfg = load_config()
        cfg["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        save_config(cfg)

        append_log({
            "executed_at": datetime.now().isoformat(timespec="seconds"),
            "title": title,
            "used_keywords": [keyword],
            "used_product": used_product,
            "status": "success",
            "error": "",
            "output": (result.stdout or "")[-1200:]
        })
        flash("今すぐ1記事生成に成功しました。", "success")
    except Exception as e:
        append_log({
            "executed_at": datetime.now().isoformat(timespec="seconds"),
            "title": title,
            "used_keywords": [keyword],
            "used_product": used_product,
            "status": "failed",
            "error": str(e)
        })
        flash("記事生成に失敗しました。ログを確認してください。", "error")

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
