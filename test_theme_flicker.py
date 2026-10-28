# -*- coding: utf-8 -*-
"""主题切换闪烁实测：切换浅/深色的同时用 ImageGrab 以最高频率抓取整个窗口（含标题栏），
统计"既不像切换前、也不像切换后"的过渡帧数量与持续时间。全部用假数据，临时配置目录。
用法: python test_theme_flicker.py [结果json路径]"""
import os, sys, tempfile, shutil, time, json, threading, ctypes, subprocess, pickle
from ctypes import wintypes
if len(sys.argv) > 1 and sys.argv[1] == "--grab":
    # 独立进程里抓帧，避免和被测界面抢 GIL。参数: left top right bottom 秒数 输出 就绪标记
    from PIL import ImageGrab
    l, t, r, b, dur, outp, ready = sys.argv[2:9]
    bbox = (int(l), int(t), int(r), int(b))
    fr = []
    open(ready, "w").write("1")
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < float(dur):
        tt = time.perf_counter()
        im = ImageGrab.grab(bbox=bbox)
        fr.append((tt, im.size, im.tobytes()))
    pickle.dump(fr, open(outp, "wb"))
    sys.exit(0)
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.argv = [os.path.join(here, "app.py")]
import core
core.APPDIR = os.path.join(tempfile.gettempdir(), "lt_flicker_test")
core.FAV_FILE = os.path.join(core.APPDIR, "favorites.json")
core.CFG_FILE = os.path.join(core.APPDIR, "config.json")
core.AVATAR_DIR = os.path.join(core.APPDIR, "avatars")
shutil.rmtree(core.APPDIR, ignore_errors=True)
os.makedirs(core.APPDIR, exist_ok=True)
FAKE = [
    dict(platform="huya", name="测试主播甲", rid="100001", avatar="", cate="英雄联盟", live=True, hot=12345),
    dict(platform="douyu", name="测试主播乙", rid="100002", avatar="", cate="户外", live=False, hot=0),
    dict(platform="bili", name="测试主播丙", rid="100003", avatar="", cate="聊天", live=True, hot=987),
    dict(platform="huya", name="测试主播丁", rid="100004", avatar="", cate="单机", live=False, hot=0),
]
core.save_favorites([dict(FAKE[0]), dict(FAKE[1])])
import app
app.App.refresh_qualities = lambda self, it: None
app.App.refresh_fav_status = lambda self: None
app.App.check_potplayer = lambda self, prompt=True: None
from PIL import Image, ImageGrab, ImageChops, ImageStat

dwm = ctypes.windll.dwmapi
user32 = ctypes.windll.user32


def frame_rect(win):
    hwnd = user32.GetParent(win.winfo_id())
    r = wintypes.RECT()
    dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r))
    return (r.left, r.top, r.right, r.bottom)


from flicker_lib import analyze


def main(outfile=None):
    a = app.App()
    a.results = [dict(it) for it in FAKE]
    a.render_results()
    a.res_title.configure(text="搜索结果（%d）" % len(a.results))
    a.kw.insert(0, "测试输入")
    a.lift(); a.attributes("-topmost", True)
    results = {}
    state = {}


    def run_toggle(label, nxt):
        a.update()
        rect = frame_rect(a)
        nograb = bool(os.environ.get("NOGRAB"))
        outp = os.path.join(core.APPDIR, "frames.pkl"); ready = os.path.join(core.APPDIR, "ready.flag")
        for f in (outp, ready):
            if os.path.exists(f): os.remove(f)
        proc = None
        if not nograb:
            proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--grab"] + [str(x) for x in rect] + ["3.2", outp, ready])
            while not os.path.exists(ready):
                a.update(); time.sleep(0.01)
        end = time.perf_counter() + 0.6
        while time.perf_counter() < end:
            a.update()
        t_toggle = time.perf_counter()
        a.theme_sw.toggle()
        t_done = time.perf_counter()
        end = time.perf_counter() + 2.2
        while time.perf_counter() < end:
            a.update()
        if nograb:
            results[label] = dict(switch_call_ms=round(1000 * (t_done - t_toggle), 1), theme=app.THEME)
            print(label, results[label]); return
        proc.wait()
        frames = [(t, Image.frombytes("RGB", sz, raw)) for t, sz, raw in pickle.load(open(outp, "rb"))]
        res = analyze(frames, t_toggle)
        res["switch_call_ms"] = round(1000 * (t_done - t_toggle), 1)
        results[label] = res
        res["state"] = dict(kw=a.kw.get(), results=len(a.results), cards=len(a.cards), favs=len(a.fav_cards),
                            quality=a.quality.get(), theme=app.THEME,
                            selected=bool(a.selected_card is not None and a.selected_card.selected and a.selected_card.item['rid']),
                            switch=bool(a.theme_sw.get()))
        print(label, json.dumps({k: v for k, v in res.items() if k != "seq"}, ensure_ascii=False))
        if os.environ.get("SAVE_FRAMES"):
            d = os.environ["SAVE_FRAMES"]; os.makedirs(d, exist_ok=True)
            for i, (t, im) in enumerate(frames):
                if t >= t_toggle - 0.05 and t <= t_toggle + 1.0:
                    im.save(os.path.join(d, "%s_%03d_%dms.png" % (label, i, round(1000 * (t - t_toggle)))))

    def go():
        a.quality.configure(values=[core.DEFAULT_QUALITY, "原画 8M", "蓝光 4M"]); a.quality.set("蓝光 4M")
        a.select_card(a.cards[0])
        # toggle() 内会触发 command=switch_theme
        run_toggle("light_to_dark", None)
        run_toggle("dark_to_light", None)
        run_toggle("light_to_dark_2", None)
        if outfile:
            json.dump(results, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        a.destroy()
    a.after(1500, go)
    a.mainloop()


if __name__ == "__main__":
    main(sys.argv_out if hasattr(sys, "argv_out") else os.environ.get("FLICKER_OUT"))
