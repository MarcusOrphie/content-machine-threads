# -*- coding: utf-8 -*-
"""
Threads-клиент для аккаунта multihub.ai (облачная routine, только stdlib).

Токен берётся из переменной окружения MH_THREADS_TOKEN (его выставляет routine),
в репозитории токена нет.

Команды:
  python3 mh_threads.py me                 - проверить токен, показать аккаунт
  python3 mh_threads.py recent [N]         - последние N наших постов (чтобы не повторяться)
  python3 mh_threads.py publish post.json  - опубликовать пост + первый коммент со ссылкой
  python3 mh_threads.py check post.json    - только проверить пост, ничего не публикуя

post.json:
  {
    "slug": "gpt6-vs-claude",            # коротко, латиница, без пробелов -> utm_medium
    "post": "текст поста",
    "comment": "Один Хаб, чтоб править всеми ИИ: {link}"   # {link} заменится на ссылку с UTM
  }
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://graph.threads.net/v1.0"
MAX_LEN = 500
BANNED = ["—", "–"]  # длинное и среднее тире
MSK = datetime.timezone(datetime.timedelta(hours=3))


def token():
    t = os.environ.get("MH_THREADS_TOKEN", "").strip()
    if not t:
        print("ОШИБКА: не задан MH_THREADS_TOKEN")
        sys.exit(2)
    return t


def http(method, path, params):
    params = dict(params, access_token=token())
    data = urllib.parse.urlencode(params).encode("utf-8")
    if method == "GET":
        req = urllib.request.Request(BASE + path + "?" + data.decode("utf-8"))
    else:
        req = urllib.request.Request(BASE + path, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace"))
        sys.exit(1)


def build_link(slug):
    date = datetime.datetime.now(MSK).strftime("%d%m%y")
    return ("https://multihub.ai/?utm_source=threads&utm_medium=%s&utm_campaign=%s"
            % (slug, date))


def load_post(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        p = json.load(f)
    slug = re.sub(r"[^a-z0-9_-]", "", p.get("slug", "").strip().lower())
    if not slug:
        print("ОШИБКА: пустой slug")
        sys.exit(3)
    link = build_link(slug)
    post = p.get("post", "").strip()
    raw = p.get("comment", "").strip()
    # comment (со ссылкой) необязателен - ссылку даём НЕ в каждом посте, чтобы не спамить
    if raw:
        comment = raw.replace("{link}", link) if "{link}" in raw else (raw + " " + link).strip()
    else:
        comment = ""

    errors = []
    if not post:
        errors.append("post пустой")
    checks = [("post", post)] + ([("comment", comment)] if comment else [])
    for name, text in checks:
        if len(text) > MAX_LEN:
            errors.append("%s длиннее %d символов (%d)" % (name, MAX_LEN, len(text)))
        for ch in BANNED:
            if ch in text:
                errors.append("%s содержит длинное тире, замени на дефис" % name)
    if "multihub.ai" in post.lower():
        errors.append("ссылку/бренд в сам пост не ставим, только в коммент")
    if errors:
        print("REJECTED:", "; ".join(errors))
        sys.exit(3)
    return slug, post, comment


def publish_text(uid, text, reply_to=None):
    params = {"media_type": "TEXT", "text": text}
    if reply_to:
        params["reply_to_id"] = reply_to
    cid = http("POST", "/%s/threads" % uid, params)["id"]
    time.sleep(5)
    return http("POST", "/%s/threads_publish" % uid, {"creation_id": cid})["id"]


def me():
    return http("GET", "/me", {"fields": "id,username"})


def link_posted_today(uid):
    """Есть ли среди наших ответов за сегодня (МСК) ссылка на multihub.ai."""
    today = datetime.datetime.now(MSK).date()
    res = http("GET", "/%s/replies" % uid, {"fields": "text,timestamp", "limit": 25})
    for r in res.get("data", []):
        ts = r.get("timestamp", "")
        try:
            d = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(MSK).date()
        except ValueError:
            continue
        if d == today and "multihub.ai" in (r.get("text") or ""):
            return True
    return False


def cmd_recent(n):
    uid = me()["id"]
    res = http("GET", "/%s/threads" % uid, {"fields": "id,text,timestamp,permalink", "limit": n})
    for item in res.get("data", []):
        text = (item.get("text") or "").replace("\n", " ")
        print("-", item.get("timestamp", "")[:16], "|", text[:160])


def cmd_publish(path, dry=False):
    slug, post, comment = load_post(path)
    print("POST:\n" + post + "\n\nCOMMENT:\n" + comment + "\n")
    if dry:
        print("CHECK OK")
        return
    uid = me()["id"]
    if comment and link_posted_today(uid):
        print("REJECTED: ссылка сегодня уже была, второй раз не ставим. Оставь comment пустым.")
        sys.exit(3)
    post_id = publish_text(uid, post)
    print("PUBLISHED post", post_id)
    if comment:
        time.sleep(30)
        comment_id = publish_text(uid, comment, reply_to=post_id)
        print("PUBLISHED comment", comment_id)
    else:
        print("без коммента (ссылку в этот раз не даём)")
    info = http("GET", "/%s" % post_id, {"fields": "permalink"})
    print("URL", info.get("permalink"))


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "me":
        print(me())
    elif a[0] == "recent":
        cmd_recent(int(a[1]) if len(a) > 1 else 15)
    elif a[0] == "publish":
        cmd_publish(a[1])
    elif a[0] == "check":
        cmd_publish(a[1], dry=True)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
