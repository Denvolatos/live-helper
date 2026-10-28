# -*- coding: utf-8 -*-
"""matches_relay.py 的本地测试：假的 PandaScore 数据，不联网、不用真实令牌。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import matches_relay as R

res = []


def T(name, cond):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


TOKEN = "TEST-TOKEN-SHOULD-NEVER-APPEAR"
RAW = {"id": 7, "status": "not_started", "name": "Upper bracket: T1 vs KOI", "scheduled_at": "2026-10-28T20:00:00Z",
       "begin_at": None, "end_at": None, "number_of_games": 3, "league": {"name": "Worlds"}, "serie": {"full_name": "Worlds 2026"},
       "tournament": {"name": "Swiss"}, "winner_id": None,
       "opponents": [{"opponent": {"id": 1, "name": "T1", "acronym": "T1", "image_url": "u1"}},
                     {"opponent": {"id": 2, "name": "Movistar KOI", "acronym": "KOI", "image_url": "u2"}}],
       "results": [{"team_id": 1, "score": 1}, {"team_id": 2, "score": 0}],
       "streams_list": [{"raw_url": "https://live.bilibili.com/6", "language": "zh", "official": True, "main": False},
                        {"raw_url": None, "language": "en"}],
       "secret_field": "不该出现"}

m = R.slim(RAW, "lol")
T("精简：比分按队伍对应", [o["score"] for o in m["opponents"]] == [1, 0])
T("精简：保留带地址的直播流、丢掉空地址", len(m["streams"]) == 1 and "bilibili" in m["streams"][0]["url"])
T("精简：多余字段不外泄", "secret_field" not in json.dumps(m, ensure_ascii=False))
T("精简：缺字段不报错", R.slim({}, "csgo")["opponents"] == [] and R.slim({}, "csgo")["streams"] == [])

calls = []


def fake_ok(path, token):
    calls.append((path, token))
    return [RAW]


tmp = tempfile.mkdtemp(prefix="lt_relay_")
path = os.path.join(tmp, "c.json")
c = R.Cache(path)
T("刷新成功返回 True", c.refresh(TOKEN, fake_ok) is True)
T("三款游戏各取三类共 9 次请求", len(calls) == 9 and {x[0].split("/")[1] for x in calls} == {"lol", "csgo", "valorant"})
T("请求路径用的是 PandaScore 的 csgo", any(p.startswith("/csgo/matches/running") for p, _ in calls))
T("缓存落盘且不含令牌", os.path.isfile(path) and TOKEN not in open(path, encoding="utf-8").read())
c2 = R.Cache(path)
T("重启后从磁盘恢复数据", c2.snapshot("lol")["upcoming"][0]["id"] == 7)

state = {"n": 0}


def fake_partial(p, token):
    if p.startswith("/valorant/"):
        raise urllib.error.HTTPError("u", 429, "limit", {}, None)
    return [dict(RAW, id=8)]


ok = c.refresh(TOKEN, fake_partial)
T("部分失败返回 False", ok is False)
T("失败的游戏保留旧数据", c.snapshot("valorant")["upcoming"][0]["id"] == 7)
T("成功的游戏更新为新数据", c.snapshot("lol")["upcoming"][0]["id"] == 8)
T("错误信息里有状态码、没有令牌", "HTTP 429" in c.last_error and TOKEN not in c.last_error)


def fake_boom(p, token):
    raise urllib.error.URLError("net down")


T("网络全断：保留所有旧数据", c.refresh(TOKEN, fake_boom) is False and c.snapshot("lol")["upcoming"][0]["id"] == 8)

lim = R.Limiter(3)
T("限流：前 3 次放行第 4 次拒绝", [lim.allow("1.1.1.1", 100) for _ in range(4)] == [True, True, True, False])
T("限流：不同来源互不影响", lim.allow("2.2.2.2", 100) is True)
T("限流：一分钟后恢复", lim.allow("1.1.1.1", 161) is True)

srv = R.ThreadingHTTPServer(("127.0.0.1", 0), R.make_handler(c, R.Limiter(100)))
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(p):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, p), timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8")), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8")), e.headers


s, d, h = get("/health")
T("/health 正常且无令牌", s == 200 and d["ok"] and TOKEN not in json.dumps(d))
s, d, h = get("/matches/lol")
T("/matches/lol 返回三类比赛", s == 200 and set(d) >= {"running", "upcoming", "past", "fetched_at"})
T("响应是 UTF-8 JSON 且带缓存头", "utf-8" in h["Content-Type"] and "max-age" in h["Cache-Control"])
s, d, h = get("/matches")
T("/matches 返回三款游戏", s == 200 and set(d["games"]) == {"lol", "csgo", "valorant"})
T("未知游戏 404", get("/matches/dota2")[0] == 404 and get("/nope")[0] == 404)
T("带查询参数也能访问", get("/matches/csgo?x=1")[0] == 200)
srv.shutdown()
srv = R.ThreadingHTTPServer(("127.0.0.1", 0), R.make_handler(c, R.Limiter(5)))
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
codes = [get("/health")[0] for _ in range(7)]
T("接口层限流：前 5 次正常、之后返回 429", codes == [200] * 5 + [429, 429])
srv.shutdown()

old = os.environ.pop("PANDASCORE_TOKEN", None)
try:
    R.main()
    T("没有令牌时拒绝启动", False)
except SystemExit as e:
    T("没有令牌时拒绝启动（退出码 2）", e.code == 2)
if old:
    os.environ["PANDASCORE_TOKEN"] = old

shutil.rmtree(tmp, ignore_errors=True)
fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
