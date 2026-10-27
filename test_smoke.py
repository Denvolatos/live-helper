# -*- coding: utf-8 -*-
"""冒烟测试：搜索 + 解析 + （可选 --play）真实拉起 PotPlayer 20 秒后关闭。"""
import os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
if not getattr(sys, "frozen", False):
    sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")

for kw in ["示例主播甲", "示例主播乙", "示例主播丙"]:
    for p in core.PLATFORMS:
        try:
            r = core.SEARCHERS[p](kw)
            print(kw, p, len(r), [(x["name"], x["rid"], x["live"]) for x in r[:2]])
        except Exception as e:
            print(kw, p, "ERR", e)
print("potplayer:", core.find_potplayer({}))
print("douyu url:", core.resolve_stream_url("https://www.douyu.com/222222")[:100])
print("huya url:", core.resolve_stream_url("https://www.huya.com/111111")[:100])
if "--play" in sys.argv:
    pp = core.find_potplayer({})
    pr = core.start_play(pp, "https://www.douyu.com/222222", "best")
    time.sleep(20)
    print("streamlink alive:", pr.poll() is None)
    q = 'tasklist /FI "IMAGENAME eq PotPlayerMini64.exe"'
    print("potplayer running:", "PotPlayerMini64" in subprocess.run(q, capture_output=True, text=True).stdout)
    core.kill_tree(pr); time.sleep(2)
    print("after kill, potplayer running:", "PotPlayerMini64" in subprocess.run(q, capture_output=True, text=True).stdout)
    print(pr.stdout.read().decode("utf8", "replace")[:500])
