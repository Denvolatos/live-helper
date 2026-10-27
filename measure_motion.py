# -*- coding: utf-8 -*-
"""实屏运动测量：悬浮层里只放 1 条弹幕（第 0 行），另起线程用 PIL 连续截屏（含分层窗口），
记录每次截屏时这条弹幕白字的最左/最右列，拟合 x = a + b*t，看残差（px）——残差越大越“抖/拖”。
用法：python measure_motion.py <danmaku.py 路径> <标签> [--layered]
结果追加到 screenshots/motion_results.jsonl。灰色背景窗口垫底，不涉及任何真实画面。"""
import importlib.util, json, os, statistics, sys, threading, time, random

args = sys.argv[1:]
LAYERED = "--layered" in args
pos = [a for a in args if not a.startswith("--")]
path, label = pos[0], pos[1]
import ctypes
ctypes.windll.user32.SetProcessDPIAware()
spec = importlib.util.spec_from_file_location("dm_under_test", path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
import tkinter as tk
from PIL import ImageGrab

W, H = 1920, 1080
root = tk.Tk(); root.withdraw()
bg = tk.Toplevel(root); bg.overrideredirect(True); bg.configure(bg="#808080"); bg.geometry("%dx%d+0+0" % (W, H)); bg.update()
random.choice = lambda seq: seq[0]          # 固定落在第 0 行
st = dict(danmaku_on=True, dm_font=28, dm_alpha=1.0, dm_speed=4, dm_area="上半屏", dm_max=80)
ov = (mod.LayeredOverlay if LAYERED else mod.Overlay)(root, st)
ov.show((0, 0, W, H), None, True)
samples = []
def grabber():
    time.sleep(1.0)
    ov.push("测试弹幕ABC123测试弹幕ABC123")
    t_end = time.perf_counter() + 6.5
    while time.perf_counter() < t_end:
        t0 = time.perf_counter()
        im = ImageGrab.grab(bbox=(0, 0, W, 48), all_screens=True, include_layered_windows=True).convert("L")
        t1 = time.perf_counter()
        bb = im.point(lambda v: 255 if v > 240 else 0).getbbox()
        if bb:
            samples.append(((t0 + t1) / 2, bb[0], bb[2], t1 - t0))
    # 分析：只取弹幕完整在屏内的段
    seg = [s for s in samples if s[1] > 20 and s[2] < W - 20]
    t = [s[0] for s in seg]; x = [s[1] for s in seg]
    n = len(seg)
    mt, mx = statistics.mean(t), statistics.mean(x)
    b = sum((a - mt) * (c - mx) for a, c in zip(t, x)) / sum((a - mt) ** 2 for a in t)
    a0 = mx - b * mt
    res = [c - (a0 + b * a) for a, c in zip(t, x)]
    wid = [s[2] - s[1] for s in seg]
    gaps = [(q - p) * 1000 for p, q in zip(t, t[1:])]
    out = dict(label=label, grabs=n, grab_ms_mean=round(statistics.mean(s[3] for s in seg) * 1000, 1),
               speed_px_s=round(-b, 1), resid_std_px=round(statistics.pstdev(res), 2), resid_max_px=round(max(abs(r) for r in res), 2),
               width_std_px=round(statistics.pstdev(wid), 2), width_range=(min(wid), max(wid)),
               unique_x=len(set(x)), repeats_pct=round(100 * sum(1 for p, q in zip(x, x[1:]) if p == q) / max(n - 1, 1), 1))
    print(json.dumps(out, ensure_ascii=False), flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", "motion_results.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    os._exit(0)
threading.Thread(target=grabber, daemon=True).start()
root.mainloop()
