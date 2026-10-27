# -*- coding: utf-8 -*-
"""弹幕悬浮层基准测试：用假弹幕驱动 Overlay，不连任何平台、不需要 PotPlayer。
用法：python bench_overlay.py <danmaku.py 路径> <标签> <同屏条数N> [秒数=12] [--follow] [--shot 输出png] [--lanes 区域]
输出一行 JSON：帧间隔均值/标准差/最大值/p99（毫秒）、tick 耗时、CPU（占单核 %）、末尾屏上条数。
--shot：测完前 2 秒用 PIL 截取悬浮层区域（背景是纯灰窗口，便于查彩边）。"""
import importlib.util, json, os, random, sys, time, statistics

args = sys.argv[1:]
flags = {a for a in args if a.startswith("--")}
shot = None
if "--shot" in args:
    i = args.index("--shot"); shot = args[i + 1]; del args[i:i + 2]
pos = [a for a in args if not a.startswith("--")]
path, label, N = pos[0], pos[1], int(pos[2])
DUR = float(pos[3]) if len(pos) > 3 else 12.0

import ctypes
ctypes.windll.user32.SetProcessDPIAware()
spec = importlib.util.spec_from_file_location("dm_under_test", path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

import tkinter as tk
import psutil

root = tk.Tk()
root.geometry("200x100+50+50"); root.withdraw()
W, H = 1920, 1080
bg = None
if shot:
    bg = tk.Toplevel(root); bg.overrideredirect(True); bg.configure(bg="#808080")
    bg.geometry("%dx%d+0+0" % (W, H)); bg.update()

ticks, durs = [], []
orig_tick = mod.Overlay._tick
def wrapped(self):
    t0 = time.perf_counter(); ticks.append(t0)
    orig_tick(self)
    durs.append((time.perf_counter() - t0) * 1000)
LAYERED = "--layered" in flags
if not LAYERED:
    mod.Overlay._tick = wrapped

st = dict(danmaku_on=True, dm_font=24, dm_alpha=1.0 if shot else 0.9, dm_speed=6, dm_area="全屏", dm_max=N)
mod.Overlay.MAX_ON_SCREEN = N
ov = (mod.LayeredOverlay if LAYERED else mod.Overlay)(root, st)
ov.show((0, 0, W, H), None, True)
random.seed(7)
POOL = ["666", "哈哈哈哈哈哈", "主播好强", "这波操作太秀了", "前排", "晚上好", "这个打法有点东西", "再来一把再来一把",
        "笑死我了哈哈哈哈", "老板大气", "ABC test 123", "加油加油加油", "这是一条比较长的弹幕用来测试长文本的飘动效果和重叠判断"]
def feed():
    n = 0
    while len(ov.items) + ov.q.qsize() < N + 5 and n < 6:
        ov.push(random.choice(POOL) + ("" if random.random() < .5 else str(random.randint(1, 99)))); n += 1
    root.after(10, feed)
feed()
if "--follow" in flags:
    def fol():
        ov.show((0, 0, W, H), None, True); root.after(150, fol)
    fol()

OV = dict(min_gap=None, bad=0, n=0)
def watch():
    if LAYERED:
        clk, lanes = ov._clock, {}
        for it in list(ov._items):
            xl = it["x0"] - it["v"] * (clk - it["c0"]); lanes.setdefault(it["lane"], []).append((xl, xl + it["w"]))
        for L in lanes.values():
            L.sort()
            for (l1, r1), (l2, r2) in zip(L, L[1:]):
                g = l2 - r1; OV["n"] += 1; OV["min_gap"] = g if OV["min_gap"] is None else min(OV["min_gap"], g)
                if g < 0: OV["bad"] += 1
    root.after(100, watch)
watch()
proc = psutil.Process()
WARM = 3.0
t_start = time.perf_counter()
state = {}
def mark():
    state["cpu0"] = proc.cpu_times(); state["t0"] = time.perf_counter(); state["i0"] = len(ticks)
root.after(int(WARM * 1000), mark)
if shot:
    def grab():
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(0, 0, W, H), all_screens=True, include_layered_windows=True).save(shot); state["shot_n"] = len(ov.items)
    root.after(int((WARM + DUR - 2) * 1000), grab)
def finish():
    c1 = proc.cpu_times(); t1 = time.perf_counter()
    cpu = ((c1.user + c1.system) - (state["cpu0"].user + state["cpu0"].system)) / (t1 - state["t0"]) * 100
    if LAYERED:
        fl = [x for x in ov.frame_log if x[0] >= state["t0"]]
        ts = [x[0] for x in fl]; d = [x[1] for x in fl]
    else:
        ts = ticks[state["i0"]:]; d = durs[state["i0"]:]
    iv = [(b - a) * 1000 for a, b in zip(ts, ts[1:])]
    iv_s = sorted(iv)
    res = dict(label=label, refresh=getattr(ov, "refresh", None), N=N, follow="--follow" in flags, frames=len(iv),
               iv_mean=round(statistics.mean(iv), 2), iv_std=round(statistics.pstdev(iv), 2), iv_max=round(max(iv), 1),
               iv_p99=round(iv_s[int(len(iv_s) * .99)], 1), tick_ms_mean=round(statistics.mean(d), 2), tick_ms_max=round(max(d), 1),
               cpu_pct_1core=round(cpu, 1), overlap_bad=OV['bad'], gap_samples=OV['n'], min_gap=None if OV['min_gap'] is None else round(OV['min_gap'], 1), items_end=len(ov.items), dropped=ov.dropped)
    print(json.dumps(res, ensure_ascii=False), flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", "bench_results.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(res, ensure_ascii=False) + "\n")
    os._exit(0)
root.after(int((WARM + DUR) * 1000), finish)
root.mainloop()
