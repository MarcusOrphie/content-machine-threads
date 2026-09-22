# -*- coding: utf-8 -*-
"""
Threads autopilot client for the "Контент-машина на AI" warm-up account.

Posts short first-person story-hooks from content_bank.json to Threads via the
official Threads Graph API. Pure stdlib (urllib) - no pip installs needed.

Commands:
  python threads_client.py me            - verify token, print Threads user id + username
  python threads_client.py status        - how many posts left in the bank
  python threads_client.py post-next     - publish the next unposted item from the bank
  python threads_client.py post-next --force   - ignore the min-interval guard
  python threads_client.py token-exchange       - short-lived -> long-lived (60 days)
  python threads_client.py token-refresh        - refresh long-lived token (extend 60 days)
  python threads_client.py add "текст поста"    - append a post to the bank

Secrets live in secrets.json (never commit):
  { "access_token": "...", "user_id": "...", "app_secret": "..." }
user_id and app_secret are optional (user_id is auto-fetched; app_secret only
needed for token-exchange).
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://graph.threads.net/v1.0"
GRAPH = "https://graph.threads.net"          # for token exchange/refresh endpoints
HERE = os.path.dirname(os.path.abspath(__file__))

SECRETS_PATH = os.path.join(HERE, "secrets.json")
BANK_PATH = os.path.join(HERE, "content_bank.json")
STATE_PATH = os.path.join(HERE, "state.json")
LOG_PATH = os.path.join(HERE, "post.log")

# Don't post twice within this many minutes (guards double-fired scheduled tasks).
MIN_INTERVAL_MIN = 90


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def secrets():
    s = load_json(SECRETS_PATH, None)
    if not s or not s.get("access_token"):
        log("ОШИБКА: нет secrets.json или пустой access_token. Заполни secrets.json.")
        sys.exit(2)
    return s


def http_get(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post(url, params):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def api_error(e):
    try:
        body = e.read().decode("utf-8")
    except Exception:
        body = str(e)
    return body


def get_user_id(token):
    """Return numeric Threads user id, from secrets or /me."""
    s = load_json(SECRETS_PATH, {})
    if s.get("user_id"):
        return s["user_id"]
    info = http_get(BASE + "/me?fields=id,username&access_token=" + urllib.parse.quote(token))
    uid = info["id"]
    s["user_id"] = uid
    save_json(SECRETS_PATH, s)
    log("Получен и сохранён user_id: %s (@%s)" % (uid, info.get("username", "?")))
    return uid


def cmd_me():
    token = secrets()["access_token"]
    try:
        info = http_get(BASE + "/me?fields=id,username,threads_profile_picture_url&access_token="
                        + urllib.parse.quote(token))
    except urllib.error.HTTPError as e:
        log("Токен НЕ работает: " + api_error(e))
        sys.exit(1)
    log("Токен рабочий. id=%s  username=@%s" % (info["id"], info.get("username", "?")))
    # cache user_id
    s = load_json(SECRETS_PATH, {})
    s["user_id"] = info["id"]
    save_json(SECRETS_PATH, s)


def _parts_of(post):
    """Return list of text parts for a bank post (supports thread chains via 'parts')."""
    if post.get("parts"):
        return [p for p in post["parts"] if p and p.strip()]
    return [post.get("text", "")]


BANKS = {
    "content": (BANK_PATH, STATE_PATH),
    "questions": (os.path.join(HERE, "questions_bank.json"),
                  os.path.join(HERE, "state_questions.json")),
    "brands": (os.path.join(HERE, "brands_bank.json"),
               os.path.join(HERE, "state_brands.json")),
}


def _resolve_bank(args):
    for i, a in enumerate(args):
        if a == "--bank" and i + 1 < len(args):
            return BANKS.get(args[i + 1], BANKS["content"])
    return BANKS["content"]


def cmd_status(bank_path=BANK_PATH, state_path=STATE_PATH):
    bank = load_json(bank_path, [])
    state = load_json(state_path, {"posted_ids": []})
    posted = set(state.get("posted_ids", []))
    left = [p for p in bank if p["id"] not in posted]
    log("В банке: %d постов, опубликовано: %d, осталось: %d" %
        (len(bank), len(posted), len(left)))
    if left:
        head = _parts_of(left[0])[0][:60].replace("\n", " ")
        log("Следующий: [%s] (%d ч.) %s..." % (left[0]["id"], len(_parts_of(left[0])), head))


def _publish_text(uid, token, text, reply_to_id=None):
    """Create a TEXT container (optionally as a reply) and publish it. Returns media id."""
    params = {"media_type": "TEXT", "text": text, "access_token": token}
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    cont = http_post(BASE + "/%s/threads" % uid, params)
    creation_id = cont["id"]
    time.sleep(5)  # let the container settle before publishing
    res = http_post(BASE + "/%s/threads_publish" % uid, {
        "creation_id": creation_id, "access_token": token,
    })
    return res.get("id", "?")


def _published_texts(uid, token, limit=100):
    """Recent published post texts, newest first (for stateless dedup)."""
    url = (BASE + "/%s/threads?fields=id,text&limit=%d&access_token=%s"
           % (uid, limit, urllib.parse.quote(token)))
    return [(d.get("text") or "") for d in http_get(url).get("data", [])]


def _pick_stateless(bank, published):
    """Pick the bank item published least recently (never-posted first, else oldest)."""
    def recency(item):
        hook = _parts_of(item)[0][:50]
        for i, t in enumerate(published):
            if hook and hook in t:
                return i  # smaller index = more recently posted
        return len(published) + 1  # never posted = most stale
    return max(bank, key=recency) if bank else None


def cmd_post_next(force=False, bank_path=BANK_PATH, state_path=STATE_PATH, stateless=False):
    token = secrets()["access_token"]
    bank = load_json(bank_path, [])
    if not bank:
        log("Банк пуст.")
        return
    state = load_json(state_path, {"posted_ids": [], "last_post_ts": 0})
    uid = get_user_id(token)

    if stateless:
        # cloud mode: ask Threads what is already published, post the most stale item
        try:
            pub = _published_texts(uid, token)
        except urllib.error.HTTPError as e:
            log("Ошибка чтения ленты: " + api_error(e))
            sys.exit(1)
        nxt = _pick_stateless(bank, pub)
    else:
        posted = set(state.get("posted_ids", []))
        # min-interval guard against double-fired tasks
        last = state.get("last_post_ts", 0)
        if not force and last and (time.time() - last) < MIN_INTERVAL_MIN * 60:
            mins = int((time.time() - last) / 60)
            log("Пропуск: последний пост был %d мин назад (< %d). Используй --force для обхода."
                % (mins, MIN_INTERVAL_MIN))
            return
        nxt = next((p for p in bank if p["id"] not in posted), None)
        if not nxt:
            log("Банк пуст - все посты опубликованы. Пополни банк.")
            return

    parts = _parts_of(nxt)
    for i, t in enumerate(parts):
        if len(t) > 500:
            log("ВНИМАНИЕ: часть %d поста [%s] длиннее 500 (%d), обрезка." % (i + 1, nxt["id"], len(t)))
            parts[i] = t[:500]

    root_id = None
    prev_id = None
    for i, t in enumerate(parts):
        try:
            mid = _publish_text(uid, token, t, reply_to_id=prev_id)
        except urllib.error.HTTPError as e:
            where = "корень" if i == 0 else ("ответ %d" % i)
            log("Ошибка публикации [%s] (%s): %s" % (nxt["id"], where, api_error(e)))
            if i == 0:
                sys.exit(1)  # nothing posted yet
            # root already out - mark posted so we don't duplicate it, then stop
            break
        if i == 0:
            root_id = mid
        prev_id = mid
        if i < len(parts) - 1:
            time.sleep(3)  # pace between parts of the same thread

    state.setdefault("posted_ids", []).append(nxt["id"])
    state["last_post_ts"] = time.time()
    save_json(state_path, state)
    log("ОПУБЛИКОВАНО [%s] тред из %d ч. root=%s тема=%s"
        % (nxt["id"], len(parts), root_id, nxt.get("theme", "?")))


def cmd_token_exchange():
    """Short-lived token -> long-lived (60 days). Needs app_secret in secrets.json."""
    s = secrets()
    if not s.get("app_secret"):
        log("Нужен app_secret в secrets.json для обмена токена.")
        sys.exit(2)
    url = (GRAPH + "/access_token?grant_type=th_exchange_token"
           + "&client_secret=" + urllib.parse.quote(s["app_secret"])
           + "&access_token=" + urllib.parse.quote(s["access_token"]))
    try:
        res = http_get(url)
    except urllib.error.HTTPError as e:
        log("Ошибка обмена: " + api_error(e))
        sys.exit(1)
    s["access_token"] = res["access_token"]
    save_json(SECRETS_PATH, s)
    log("Получен long-lived токен (действует ~%s сек / 60 дней). Сохранён." %
        res.get("expires_in", "?"))


def cmd_token_refresh():
    """Refresh a long-lived token (must be >24h old, <60 days). Extends 60 days."""
    s = secrets()
    url = (GRAPH + "/refresh_access_token?grant_type=th_refresh_token"
           + "&access_token=" + urllib.parse.quote(s["access_token"]))
    try:
        res = http_get(url)
    except urllib.error.HTTPError as e:
        log("Ошибка обновления: " + api_error(e))
        sys.exit(1)
    s["access_token"] = res["access_token"]
    save_json(SECRETS_PATH, s)
    log("Токен обновлён на ещё ~%s сек / 60 дней. Сохранён." % res.get("expires_in", "?"))


def cmd_add(text):
    bank = load_json(BANK_PATH, [])
    new_id = "add-%d" % (len([p for p in bank if p["id"].startswith("add-")]) + 1)
    bank.append({"id": new_id, "theme": "manual", "text": text})
    save_json(BANK_PATH, bank)
    log("Добавлен пост [%s] в банк." % new_id)


INSIGHTS_JSON = os.path.join(HERE, "insights.json")
INSIGHTS_MD = os.path.join(HERE, "insights.md")


def _theme_for_text(text, bank):
    """Recover the bank id/theme for a published post by matching its text (any thread part)."""
    head = (text or "")[:50]
    for p in bank:
        for part in _parts_of(p):
            if part[:50] == head or part[:80] in (text or ""):
                return p["id"], p.get("theme", "?")
    return "?", "?"


def cmd_insights():
    """Pull metrics for recent posts, write insights.json + insights.md, print top."""
    token = secrets()["access_token"]
    uid = get_user_id(token)
    bank = load_json(BANK_PATH, [])

    # list recent posts
    try:
        listing = http_get(BASE + "/%s/threads?fields=id,text,timestamp,permalink&limit=50&access_token=%s"
                           % (uid, urllib.parse.quote(token)))
    except urllib.error.HTTPError as e:
        log("Ошибка получения списка постов: " + api_error(e))
        sys.exit(1)
    posts = listing.get("data", [])
    if not posts:
        log("Постов пока нет.")
        return

    metrics = "views,likes,replies,reposts,quotes"
    rows = []
    for p in posts:
        pid = p["id"]
        vals = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0}
        try:
            ins = http_get(BASE + "/%s/insights?metric=%s&access_token=%s"
                           % (pid, metrics, urllib.parse.quote(token)))
            for m in ins.get("data", []):
                name = m.get("name")
                v = m.get("values", [{}])
                vals[name] = (v[0].get("value", 0) if v else 0)
        except urllib.error.HTTPError:
            pass  # very fresh posts may not have insights yet
        bank_id, theme = _theme_for_text(p.get("text", ""), bank)
        eng = vals["likes"] + vals["replies"] * 3 + vals["reposts"] * 2 + vals["quotes"] * 2
        rows.append({
            "media_id": pid, "bank_id": bank_id, "theme": theme,
            "timestamp": p.get("timestamp", ""), "permalink": p.get("permalink", ""),
            "text": (p.get("text", "") or "").replace("\n", " ")[:90],
            "views": vals["views"], "likes": vals["likes"], "replies": vals["replies"],
            "reposts": vals["reposts"], "quotes": vals["quotes"], "engagement": eng,
        })

    rows.sort(key=lambda r: r["engagement"], reverse=True)
    save_json(INSIGHTS_JSON, {"generated": time.strftime("%Y-%m-%d %H:%M"), "posts": rows})

    # theme averages
    themes = {}
    for r in rows:
        t = themes.setdefault(r["theme"], {"n": 0, "views": 0, "likes": 0, "replies": 0, "eng": 0})
        t["n"] += 1
        t["views"] += r["views"]; t["likes"] += r["likes"]
        t["replies"] += r["replies"]; t["eng"] += r["engagement"]

    lines = ["# Threads - статистика постов", "",
             "Сгенерировано: " + time.strftime("%Y-%m-%d %H:%M"),
             "Метрика вовлечённости = лайки + ответы*3 + репосты*2 + цитаты*2.", "",
             "## Средние по темам (что заходит)", "",
             "| Тема | Постов | Ср. просмотры | Ср. лайки | Ср. ответы | Ср. вовл. |",
             "|---|---|---|---|---|---|"]
    for t, d in sorted(themes.items(), key=lambda x: x[1]["eng"] / max(x[1]["n"], 1), reverse=True):
        n = max(d["n"], 1)
        lines.append("| %s | %d | %.0f | %.1f | %.1f | %.1f |"
                     % (t, d["n"], d["views"]/n, d["likes"]/n, d["replies"]/n, d["eng"]/n))

    lines += ["", "## Топ постов по вовлечённости", "",
              "| # | Тема | Просм | Лайки | Ответы | Вовл. | Текст |",
              "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:15], 1):
        lines.append("| %d | %s | %d | %d | %d | %d | %s |"
                     % (i, r["theme"], r["views"], r["likes"], r["replies"], r["engagement"], r["text"]))

    with open(INSIGHTS_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    log("Статистика собрана по %d постам. Отчёт: insights.md" % len(rows))
    for r in rows[:5]:
        log("  ТОП [%s] вовл=%d просм=%d лайки=%d ответы=%d | %s"
            % (r["theme"], r["engagement"], r["views"], r["likes"], r["replies"], r["text"][:50]))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    bank_path, state_path = _resolve_bank(args)
    if cmd == "me":
        cmd_me()
    elif cmd == "status":
        cmd_status(bank_path, state_path)
    elif cmd == "post-next":
        cmd_post_next(force=("--force" in args), bank_path=bank_path, state_path=state_path,
                      stateless=("--stateless" in args))
    elif cmd == "token-exchange":
        cmd_token_exchange()
    elif cmd == "token-refresh":
        cmd_token_refresh()
    elif cmd == "add" and len(args) > 1:
        cmd_add(args[1])
    elif cmd == "insights":
        cmd_insights()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
