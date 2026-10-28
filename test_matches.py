# -*- coding: utf-8 -*-
"""matches.py 的测试：本地假服务器 + 假数据，不联网。"""
import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import core
import matches as M

res = []


def T(name, cond):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def raises(fn):
    try:
        fn()
    except M.MatchError as e:
        return str(e)
    return None


def mk(i, status="not_started", scores=(None, None), winner=None, at="2026-10-28T20:00:00Z"):
    return {"id": i, "status": status, "scheduled_at": at, "begin_at": None, "best_of": 3, "league": "Worlds", "serie": "Worlds 2026",
            "tournament": "Swiss", "winner_id": winner,
            "opponents": [{"id": 1, "name": "T1", "score": scores[0], "logo": "http://evil/x.png"},
                          {"id": 2, "name": "Movistar KOI", "score": scores[1]}],
            "streams": [{"url": "http://evil.example/steal", "language": "zh"}], "secret": "x"}


PAYLOAD = {"fetched_at": "2026-10-28T17:26:05Z", "game": "lol", "running": [mk(1, "running", (1, 0))],
           "upcoming": [mk(i) for i in range(10, 40)], "past": [mk(100 + i, "finished", (2, 1), 1) for i in range(15)]}
MODE = {"kind": "ok"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        k = MODE["kind"]
        if k == "500":
            self.send_response(500); self.end_headers(); return
        body = {"ok": json.dumps(PAYLOAD), "junk": "not json {", "list": "[1,2]", "big": " " * (M.MAX_BYTES + 10)}[k].encode("utf-8")
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]

g = M.fetch_game("lol", base)
T("读取成功并整理", g["game"] == "lol" and len(g["running"]) == 1 and g["fetched_at"] == "2026-10-28T17:26:05Z")
T("不保留服务器给的网址和多余字段", "evil" not in json.dumps(g) and "secret" not in json.dumps(g) and "streams" not in g["running"][0])
T("队伍和比分按顺序对应", [o["score"] for o in g["running"][0]["opponents"]] == [1, 0])
MODE["kind"] = "500"
T("服务器 500 → 友好提示", "HTTP 500" in (raises(lambda: M.fetch_game("lol", base)) or ""))
MODE["kind"] = "junk"
T("返回不是 JSON → 友好提示", "看不懂" in (raises(lambda: M.fetch_game("lol", base)) or ""))
MODE["kind"] = "list"
T("返回结构不对 → 友好提示", "看不懂" in (raises(lambda: M.fetch_game("lol", base)) or ""))
MODE["kind"] = "big"
T("返回过大 → 拒绝", "太大" in (raises(lambda: M.fetch_game("lol", base)) or ""))
T("连不上 → 友好提示", "连不上" in (raises(lambda: M.fetch_game("lol", "http://127.0.0.1:1", timeout=2)) or ""))
T("不支持的游戏/坏地址被拒", raises(lambda: M.fetch_game("dota2", base)) and raises(lambda: M.fetch_game("lol", "ftp://x")))
srv.shutdown()

T("坏比赛数据被丢弃", M.clean_match("x") is None and M.clean_match({"status": "weird"}) is None)
T("缺字段不报错", M.clean_match({})["opponents"] == [] and M.team_names(M.clean_match({})) == ["待定", "待定"])
T("字段类型被规整（布尔不当数字、长文本截断）", M.clean_match({"id": True, "league": "x" * 500})["id"] is None and len(M.clean_match({"league": "x" * 500})["league"]) == 40)

m = M.clean_match(mk(1, "running", (1, 0)))
T("比分文字", M.score_text(m) == "1 : 0")
T("未开始不显示比分", M.score_text(M.clean_match(mk(2))) == "")
T("一方比分缺失显示 -", M.score_text(M.clean_match(mk(3, "running", (1, None)))) == "1 : -")
fin = M.clean_match(mk(4, "finished", (2, 1), winner=1))
T("胜者序号", M.winner_index(fin) == 0 and M.winner_index(M.clean_match(mk(5))) is None)
T("状态文字", [M.status_text(M.clean_match(mk(1, s))) for s in ("running", "not_started", "finished")] == ["进行中", "未开始", "已结束"])
T("信息行含联赛、赛段、BO", M.info_line(m) == "Worlds · Worlds 2026 · BO3")
T("联赛和赛段相同不重复", M.info_line(M.clean_match({"league": "A", "serie": "A", "status": "running"})) == "A")

now = datetime(2026, 10, 28, 12, 0).astimezone()
iso = lambda dt: dt.astimezone().isoformat()
tm, day = M.when(iso(now.replace(hour=21, minute=5)), now)
T("今天的比赛显示钟点和“今天”", tm == "21:05" and day == "今天")
T("明天", M.when(iso(now + timedelta(days=1)), now)[1] == "明天")
T("更远的显示日期和星期", "周" in M.when(iso(now + timedelta(days=5)), now)[1] and "-" in M.when(iso(now + timedelta(days=5)), now)[1])
T("时间未定", M.when("", now) == ("待定", "") and M.when("乱码", now) == ("待定", ""))
T("按本机时区转换（UTC 20:00 与本地一致）", M.local_time("2026-10-28T20:00:00Z").utcoffset() is not None
  and M.local_time("2026-10-28T20:00:00Z").astimezone(M.local_time("2026-10-28T20:00:00Z").tzinfo).hour == M.local_time("2026-10-28T20:00:00Z").hour)

secs = M.sections(M.clean_game(PAYLOAD, "lol"))
T("分组顺序和标题", [t for t, _ in secs] == ["正在进行", "即将开始", "刚结束"])
T("数量上限：即将开始 20、刚结束 10", len(secs[1][1]) == 20 and len(secs[2][1]) == 10)
T("没有比赛的组不显示", [t for t, _ in M.sections({"running": [], "upcoming": [M.clean_match(mk(1))], "past": []})] == ["即将开始"])
T("更新时间文字", M.age_text("2026-10-28T17:26:05Z").startswith("更新于 ") and M.age_text("") == "")

tmp = tempfile.mkdtemp(prefix="lt_matches_")
core.APPDIR = tmp
T("无缓存时为空", M.load_cache() == {})
M.save_cache({"lol": g})
T("缓存读回一致", M.load_cache()["lol"]["running"][0]["id"] == 1)
open(M.cache_path(), "w", encoding="utf-8").write("{坏的")
T("缓存损坏时安全返回空", M.load_cache() == {})
shutil.rmtree(tmp, ignore_errors=True)

fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
