# -*- coding: utf-8 -*-
"""赛事页界面测试：用假数据（不联网），临时配置目录。运行：python test_matches_ui.py [截图输出目录]"""
import os
import shutil
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
_out = sys.argv[1] if len(sys.argv) > 1 else None
sys.argv = [os.path.join(here, "app.py")]
import core

TMP = os.path.join(tempfile.gettempdir(), "lt_matches_ui")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
core.APPDIR = TMP
core.FAV_FILE = os.path.join(TMP, "favorites.json")
core.CFG_FILE = os.path.join(TMP, "config.json")
core.AVATAR_DIR = os.path.join(TMP, "avatars")
OUT = _out or os.path.join(tempfile.gettempdir(), "lt_matches_shots")
os.makedirs(OUT, exist_ok=True)

import app
import matches as M
from PIL import ImageGrab

res = []


def T(name, cond):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def pump(a, sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        a.update()
        time.sleep(0.01)


def wait(a, fn, sec=4.0):
    t0 = time.time()
    while time.time() - t0 < sec:
        a.update()
        if fn():
            return True
        time.sleep(0.02)
    return False


def shot(a, name):
    a.attributes("-topmost", True)
    pump(a, 0.5)
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab(bbox=(x - 8, y - 40, x + w + 8, y + h + 8)).save(os.path.join(OUT, name + ".png"))
    a.attributes("-topmost", False)


def mk(i, status, names, scores=(None, None), winner=None, at="2026-10-28T20:00:00Z", league="Worlds", serie="Worlds 2026", bo=3):
    return {"id": i, "status": status, "scheduled_at": at, "begin_at": None, "best_of": bo, "league": league, "serie": serie,
            "tournament": "", "winner_id": winner,
            "opponents": [{"id": 10 * i + 1, "name": names[0], "score": scores[0]}, {"id": 10 * i + 2, "name": names[1], "score": scores[1]}]}


def game(g, run, up, past):
    return {"game": g, "fetched_at": "2026-10-28T17:26:05Z", "running": run, "upcoming": up, "past": past}


DATA = {
    "lol": game("lol", [], [mk(1, "not_started", ("Movistar KOI", "T1")), mk(2, "not_started", ("Invictus Gaming", "LYON"), at="2026-10-28T23:00:00Z"),
                            mk(3, "not_started", ("Top Esports", "Bilibili Gaming"), at="2026-10-29T23:00:00Z")],
                [mk(4, "finished", ("T1", "Gen.G"), (3, 2), winner=41), mk(5, "finished", ("BLG", "JDG"), (1, 3), winner=52)]),
    "csgo": game("csgo", [mk(6, "running", ("Spirit", "Natus Vincere"), (1, 0), league="PGL", serie="PGL Masters Bucharest 2026")], [mk(7, "not_started", ("Winx", "X-CITY"))], []),
    "valorant": game("valorant", [], [], []),
}
CALLS = []
FAIL = {"on": False}


def fake_fetch(g, base=M.DEFAULT_API, timeout=8):
    CALLS.append(g)
    if FAIL["on"]:
        raise M.MatchError("连不上赛事服务器，请检查网络")
    return DATA[g]


M.fetch_game = fake_fetch


def texts(w, acc=None):
    acc = [] if acc is None else acc
    for c in w.winfo_children():
        try:
            t = c.cget("text")
            if t:
                acc.append(t)
        except Exception:
            pass
        texts(c, acc)
    return acc


def cards(a):
    return [c for c in a.match_box.winfo_children() if c.winfo_children() and isinstance(c, app.ctk.CTkFrame) and c.cget("height") == 72]


a = app.App()
a.update()
T("启动时是直播页，赛事页没显示", a.view == "live" and not a.match_view.winfo_ismapped() and a.body.winfo_ismapped())
T("搜索栏和平台按钮在直播页可见", a.bar.winfo_ismapped() and a.plat_frame.winfo_ismapped())
a.view_btns["matches"].invoke()
pump(a, 0.5)
T("切到赛事：赛事页显示，直播页和搜索栏隐藏", a.view == "matches" and a.match_view.winfo_ismapped() and not a.body.winfo_ismapped()
  and not a.bar.winfo_ismapped() and not a.plat_frame.winfo_ismapped())
T("底部播放栏仍在", a._pb.winfo_ismapped() and a.btn_play.winfo_ismapped())
T("切到赛事时开始读取默认游戏 LOL", wait(a, lambda: CALLS == ["lol"]))
T("LOL 渲染三个分组里的有数据组", wait(a, lambda: len(cards(a)) == 5))
tx = texts(a.match_box)
T("显示分组标题和数量", "即将开始（3）" in tx and "刚结束（2）" in tx and not any("正在进行" in t for t in tx))
T("显示队伍和赛事信息", "Movistar KOI" in tx and "T1" in tx and "Worlds · Worlds 2026 · BO3" in tx)
T("已结束显示比分", "3 : 2" in tx and "已结束" in tx and "未开始" in tx)
T("显示更新时间", any(t.startswith("更新于 ") for t in texts(a.match_view)))
shot(a, "01-lol")

a.game_btns["csgo"].invoke()
T("切到 CS：只读 CS 并显示进行中的比赛", wait(a, lambda: CALLS[-1] == "csgo" and "进行中" in "".join(texts(a.match_box))) and "1 : 0" in texts(a.match_box))
T("进行中的分组显示", "正在进行（1）" in texts(a.match_box))
T("选择的游戏写入配置", core.load_config().get("match_game") == "csgo")
shot(a, "02-cs")
a.game_btns["valorant"].invoke()
T("没有比赛的游戏显示提示", wait(a, lambda: "暂时没有比赛信息" in texts(a.match_box)))

n = len(CALLS)
a.refresh_matches()
pump(a, 0.3)
T("30 秒内再次进入不重复读取", len(CALLS) == n)
a.refresh_matches(True)
T("手动刷新会强制读取", wait(a, lambda: len(CALLS) == n + 1))

FAIL["on"] = True
a.game_btns["lol"].invoke()
a._match_last.clear()
a.refresh_matches(True)
T("读取失败：红字提示且保留上次数据", wait(a, lambda: "连不上赛事服务器" in a.match_status.cget("text")) and "显示的是上次的数据" in a.match_status.cget("text")
  and len(cards(a)) == 5)
shot(a, "03-error-with-cache")
a.match_data.pop("lol")
a._match_last.clear()
a.refresh_matches(True)
T("读取失败且没有数据：提示刷新", wait(a, lambda: any("还没有赛事数据" in t for t in texts(a.match_box)) or any("暂时没有" in t for t in texts(a.match_box)) or "连不上" in a.match_status.cget("text")))
FAIL["on"] = False
a.refresh_matches(True)
T("网络恢复后自动好起来", wait(a, lambda: len(cards(a)) == 5 and "连不上" not in a.match_status.cget("text")))
T("成功数据写进了本地缓存", "lol" in M.load_cache())

a.view_btns["live"].invoke()
pump(a, 0.5)
T("切回直播：搜索栏、平台按钮、收藏页都恢复", a.view == "live" and a.bar.winfo_ismapped() and a.plat_frame.winfo_ismapped() and a.body.winfo_ismapped()
  and not a.match_view.winfo_ismapped())
a.kw.insert(0, "测试")
T("切回后搜索框内容保留", a.kw.get() == "测试")
a.view_btns["matches"].invoke()
pump(a, 0.3)
T("再次进入赛事：直接显示已有数据", len(cards(a)) == 5)
a.theme_sw.select()
a.switch_theme()
pump(a, 0.5)
shot(a, "04-dark")
a.theme_sw.deselect()
a.switch_theme()
a.quit_app()

b = app.App()
b.update()
T("重启后记住上次选的游戏", b.game == "lol" or b.game == core.load_config().get("match_game"))
T("重启后先用本地缓存显示（不用等网络）", "lol" in b.match_data)
b.quit_app()

fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d；截图在 %s" % (len(res), len(res) - len(fails), len(fails), OUT), flush=True)
shutil.rmtree(TMP, ignore_errors=True)
os._exit(1 if fails else 0)
