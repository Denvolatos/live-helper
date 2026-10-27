# -*- coding: utf-8 -*-
"""冒烟测试：搜索 + 解析 + （可选 --play）真实拉起 PotPlayer 20 秒后关闭。"""
import os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
if not getattr(sys, "frozen", False):
    sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")

ROOMS = core.pick_live_rooms(log=print)  # 中性关键词搜索，取各平台第一个在播房间；可用 LIVEHELPER_SELFTEST_ROOMS 覆盖
print("找到在播房间的平台:", list(ROOMS))
for kw in core.NEUTRAL_KEYWORDS[:3]:
    for p in core.PLATFORMS:
        try:
            r = core.SEARCHERS[p](kw)
            print(kw, p, len(r), "在播", sum(1 for x in r if x["live"]))
        except Exception as e:
            print(kw, p, "ERR", e)
print("potplayer:", core.find_potplayer({}))
for p in ("douyu", "huya"):
    if p in ROOMS:
        print(p, "url ok:", bool(core.resolve_stream_url(core.room_url(p, ROOMS[p]))))
if "--play" in sys.argv:
    pp = core.find_potplayer({})
    play_p = next((p for p in ("douyu", "huya") if p in ROOMS), None)
    if not play_p:
        sys.exit("没有找到可播放的在播房间")
    pr = core.start_play(pp, core.room_url(play_p, ROOMS[play_p]), "best")
    time.sleep(20)
    print("streamlink alive:", pr.poll() is None)
    q = 'tasklist /FI "IMAGENAME eq PotPlayerMini64.exe"'
    print("potplayer running:", "PotPlayerMini64" in subprocess.run(q, capture_output=True, text=True).stdout)
    core.kill_tree(pr); time.sleep(2)
    print("after kill, potplayer running:", "PotPlayerMini64" in subprocess.run(q, capture_output=True, text=True).stdout)
    print(pr.stdout.read().decode("utf8", "replace")[:500])
