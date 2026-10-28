# -*- coding: utf-8 -*-
"""LatoMedia · 赛事数据转发小程序（跑在服务器上，只用 Python 自带的库）。

每隔几分钟去 PandaScore 取一次无畏契约 / CS / LOL 的"正在进行、即将开始、刚结束"的比赛，整理成精简的 JSON 存起来；
软件来问的时候直接给存的那份，所以令牌只放在服务器上，用户多了也不会超过 PandaScore 的每小时请求上限。

环境变量（由 systemd 的 EnvironmentFile 提供，令牌绝不写进代码、不进日志）：
  PANDASCORE_TOKEN   必填
  PORT               监听端口，默认 8080
  BIND               监听地址，默认 0.0.0.0
  REFRESH_SECONDS    刷新间隔，默认 300
  STATE_DIR          缓存文件目录，默认 ./
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API = "https://api.pandascore.co"
GAMES = ("lol", "csgo", "valorant")          # PandaScore 里 CS2 的路径仍叫 csgo
KINDS = (("running", "per_page=20&sort=begin_at"),
         ("upcoming", "per_page=30&sort=scheduled_at"),
         ("past", "per_page=15&sort=-scheduled_at"))
RATE_LIMIT = 60                              # 每个来源 IP 每分钟最多请求次数


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def slim(m, game):
    """只留软件要用的字段，体积小、也不泄露多余信息。"""
    opps = []
    for o in m.get("opponents") or []:
        t = (o or {}).get("opponent") or {}
        opps.append({"id": t.get("id"), "name": t.get("name"), "acronym": t.get("acronym"), "logo": t.get("image_url")})
    score = {r.get("team_id"): r.get("score") for r in (m.get("results") or [])}
    for o in opps:
        o["score"] = score.get(o["id"])
    streams = [{"url": s.get("raw_url"), "language": s.get("language"), "official": bool(s.get("official")), "main": bool(s.get("main"))}
               for s in (m.get("streams_list") or []) if s.get("raw_url")]
    return {"id": m.get("id"), "game": game, "status": m.get("status"), "name": m.get("name"),
            "scheduled_at": m.get("scheduled_at"), "begin_at": m.get("begin_at"), "end_at": m.get("end_at"),
            "best_of": m.get("number_of_games"), "league": (m.get("league") or {}).get("name"),
            "serie": (m.get("serie") or {}).get("full_name"), "tournament": (m.get("tournament") or {}).get("name"),
            "opponents": opps, "winner_id": m.get("winner_id"), "streams": streams}


def fetch_json(path, token, timeout=25):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                                                      "User-Agent": "LiveHelper-relay"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Cache:
    def __init__(self, path=None):
        self.lock = threading.Lock()
        self.path = path
        self.data = {"fetched_at": None, "games": {g: {k: [] for k, _ in KINDS} for g in GAMES}}
        self.last_error = None
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass

    def snapshot(self, game=None):
        with self.lock:
            d = json.loads(json.dumps(self.data))
        if game:
            return {"fetched_at": d.get("fetched_at"), "game": game, **d["games"].get(game, {})}
        return d

    def refresh(self, token, fetch=fetch_json):
        """取全部数据；任何一个游戏失败就保留它的旧数据，其余照常更新。"""
        games, errors = {}, []
        for g in GAMES:
            one = {}
            for kind, q in KINDS:
                try:
                    one[kind] = [slim(m, g) for m in fetch("/%s/matches/%s?%s" % (g, kind, q), token)]
                except (urllib.error.URLError, ValueError, OSError) as e:
                    code = getattr(e, "code", None)
                    errors.append("%s/%s: %s" % (g, kind, ("HTTP %s" % code) if code else type(e).__name__))
                    one[kind] = (self.data["games"].get(g) or {}).get(kind, [])
            games[g] = one
        with self.lock:
            self.data = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "games": games}
            self.last_error = "; ".join(errors) or None
        if self.path:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        return not errors


class Limiter:
    def __init__(self, per_minute=RATE_LIMIT):
        self.per_minute, self.hits, self.lock = per_minute, {}, threading.Lock()

    def allow(self, ip, now=None):
        now = time.time() if now is None else now
        with self.lock:
            q = [t for t in self.hits.get(ip, []) if now - t < 60]
            ok = len(q) < self.per_minute
            if ok:
                q.append(now)
            self.hits[ip] = q
            if len(self.hits) > 5000:
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 60}
            return ok


def make_handler(cache, limiter):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):           # 不记录访问日志，也就不会记下任何来源信息
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=60")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not limiter.allow(self.client_address[0]):
                return self._send(429, {"error": "too many requests"})
            path = self.path.split("?")[0].rstrip("/")
            if path == "/health":
                return self._send(200, {"ok": True, "fetched_at": cache.data.get("fetched_at"), "last_error": cache.last_error})
            if path == "/matches":
                return self._send(200, cache.snapshot())
            if path.startswith("/matches/") and path.split("/")[2] in GAMES:
                return self._send(200, cache.snapshot(path.split("/")[2]))
            self._send(404, {"error": "not found"})
    return H


def loop(cache, token, every):
    while True:
        try:
            ok = cache.refresh(token)
            log("刷新完成" if ok else "刷新有失败项：%s" % cache.last_error)
        except Exception as e:                # 任何意外都不能让后台线程退出
            log("刷新异常：%s" % type(e).__name__)
        time.sleep(every)


def main():
    token = os.environ.get("PANDASCORE_TOKEN", "").strip()
    if not token:
        log("缺少 PANDASCORE_TOKEN，退出")
        sys.exit(2)
    every = max(60, int(os.environ.get("REFRESH_SECONDS", "300")))
    state = os.environ.get("STATE_DIR", ".")
    os.makedirs(state, exist_ok=True)
    cache = Cache(os.path.join(state, "matches_cache.json"))
    threading.Thread(target=loop, args=(cache, token, every), daemon=True).start()
    srv = ThreadingHTTPServer((os.environ.get("BIND", "0.0.0.0"), int(os.environ.get("PORT", "8080"))), make_handler(cache, Limiter()))
    log("开始监听 %s:%s，每 %d 秒刷新一次" % (srv.server_address[0], srv.server_address[1], every))
    srv.serve_forever()


if __name__ == "__main__":
    main()
