# -*- coding: utf-8 -*-
"""新渲染逐帧位置诊断：记录第一条弹幕每帧取整后的 x，统计相邻帧位移直方图（匀速应只有 floor/ceil 两种值）。"""
import importlib.util, os, sys, time, collections, statistics, ctypes, random
ctypes.windll.user32.SetProcessDPIAware()
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("dm", os.path.join(here, "danmaku.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
import tkinter as tk
root = tk.Tk(); root.withdraw()
st = dict(danmaku_on=True, dm_font=28, dm_alpha=1.0, dm_speed=6, dm_area="上半屏", dm_max=80)
ov = mod.LayeredOverlay(root, st); ov.show((0, 0, 1920, 1080), None, True); ov.trace_on = True
ov.push("匀速测试匀速测试匀速测试")
t_end = time.time() + 6
while time.time() < t_end:
    root.update(); time.sleep(0.005)
tr = ov.trace
xs = [t[2] for t in tr]; ts = [t[0] for t in tr]
steps = [a - b for a, b in zip(xs, xs[1:])]
hist = collections.Counter(steps)
ideal = [(a[1] - b[1]) for a, b in zip(tr, tr[1:])]
print("frames", len(tr), "refresh", ov.refresh, "step hist", dict(sorted(hist.items())), "mean step", round(statistics.mean(steps), 3),
      "ideal mean", round(statistics.mean(ideal), 3), "rounding err max px", round(max(abs(t[1] - t[2]) for t in tr), 3), "errors", ov.errors, flush=True)
ov.destroy(); os._exit(0)
