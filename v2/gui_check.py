# -*- coding: utf-8 -*-
"""v2 界面自检（仅 Windows，演示模式假数据，不联网、不弹模态框）。
python v2/gui_check.py <截图输出目录>
做的事：起窗口 -> 各状态截图 -> 乱序搜索检查 -> 程序化连续缩放/移动窗口并统计页面帧间隔。
注意：程序化缩放不等于用户用鼠标拖，数字只能说明重排/重绘开销，不代表手感。"""
import ctypes
import ctypes.wintypes
import json
import os
import statistics
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import webview  # noqa: E402
from PIL import ImageGrab  # noqa: E402

import app_web  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "_shots")
os.makedirs(OUT, exist_ok=True)
RESULT = {}


def rect(title_part):
    u = ctypes.windll.user32
    found = []
    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        lambda h, _: (found.append(h) if title_part in _title(u, h) and u.IsWindowVisible(h) else None) or True)
    u.EnumWindows(cb, 0)
    r = ctypes.wintypes.RECT()
    # 取可见边框（不含阴影），否则截图边缘会带进窗口后面的桌面内容
    ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(found[0]), 9, ctypes.byref(r), ctypes.sizeof(r))
    return r.left, r.top, r.right, r.bottom


def _title(u, h):
    b = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, b, 256)
    return b.value


def shot(name):
    time.sleep(0.5)
    ImageGrab.grab(bbox=rect("演示模式"), all_screens=True).save(os.path.join(OUT, name + ".png"))


def search(w, kw):
    w.evaluate_js("document.getElementById('q').value=%s;window.__lh.doSearch()" % json.dumps(kw))


def run(w):
    w.events.loaded.wait(15)
    time.sleep(0.8)
    w.resize(1100, 720)
    w.evaluate_js("document.documentElement.dataset.theme='light'")
    shot("01-浅色-初始")
    search(w, "游戏")
    time.sleep(0.8)
    shot("02-浅色-搜索结果")
    search(w, "风控")
    time.sleep(0.8)
    shot("03-错误态-斗鱼风控")
    search(w, "慢")
    time.sleep(0.5)
    shot("04-加载中")
    time.sleep(2.0)
    w.evaluate_js("document.getElementById('theme').click()")
    time.sleep(0.5)
    search(w, "游戏")
    time.sleep(0.8)
    shot("05-深色-搜索结果")
    w.resize(760, 520)
    time.sleep(0.5)
    shot("06-深色-最小窗口")
    w.resize(1100, 720)

    # 乱序：先发“慢”，马上发“游戏”，最终界面必须是“游戏”的结果
    search(w, "慢")
    time.sleep(0.2)
    search(w, "游戏")
    time.sleep(3.5)
    RESULT["stale_final_status"] = w.evaluate_js("document.getElementById('status').textContent")
    RESULT["stale_cards"] = w.evaluate_js("document.querySelectorAll('.card').length")
    RESULT["stale_info_has_query"] = w.evaluate_js(
        "document.querySelector('.info') && document.querySelector('.info').textContent")
    # 播放按钮禁用
    RESULT["play_disabled_all"] = w.evaluate_js(
        "Array.from(document.querySelectorAll('.play')).every(b=>b.disabled)")

    # 帧间隔：页面里用 rAF 记录，同时 Python 侧连续 resize / move
    w.evaluate_js("""window.__f=[];(function t(p){requestAnimationFrame(function(n){
        if(p)window.__f.push(n-p);if(!window.__stop)t(n)})})(0);""")
    time.sleep(0.3)
    t_calls = []
    for i in range(80):
        t0 = time.perf_counter()
        w.resize(900 + int(250 * abs((i % 40) - 20) / 20), 600 + int(150 * abs((i % 40) - 20) / 20))
        t_calls.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.016)
    resize_frames = w.evaluate_js("window.__f.slice()")
    w.evaluate_js("window.__f=[]")
    for i in range(80):
        t0 = time.perf_counter()
        w.move(100 + i * 5, 80 + (i % 20) * 3)
        t_calls.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.016)
    move_frames = w.evaluate_js("window.__f.slice()")
    w.evaluate_js("window.__stop=1")

    def stats(a):
        a = sorted(a)
        return {"n": len(a), "mean_ms": round(statistics.mean(a), 1),
                "p95_ms": round(a[int(len(a) * .95) - 1], 1), "max_ms": round(a[-1], 1),
                "over_33ms": sum(1 for x in a if x > 33.4)} if a else {"n": 0}
    RESULT["resize_page_frames"] = stats(resize_frames or [])
    RESULT["move_page_frames"] = stats(move_frames or [])
    RESULT["resize_call_ms"] = stats(t_calls[:80])
    with open(os.path.join(OUT, "gui_check.json"), "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=1)
    print(json.dumps(RESULT, ensure_ascii=False, indent=1))
    w.destroy()


if __name__ == "__main__":
    win = app_web.create_window(demo=True)
    webview.start(run, win)
