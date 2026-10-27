# -*- coding: utf-8 -*-
"""打包版 LiveHelper.exe 切主题抓帧实测：用临时 APPDATA（假收藏、假配置），不碰用户数据；
点击界面上的"深色"开关，独立进程抓帧。用法: python test_packaged_flicker.py <exe路径> [结果json]"""
import os, sys, tempfile, shutil, time, json, subprocess, pickle, ctypes
from ctypes import wintypes
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from PIL import Image
from flicker_lib import analyze
exe = sys.argv[1]
outfile = sys.argv[2] if len(sys.argv) > 2 else None
tmp = os.path.join(tempfile.gettempdir(), "lt_pkg_test")
shutil.rmtree(tmp, ignore_errors=True)
d = os.path.join(tmp, "直播助手"); os.makedirs(d)
favs = [dict(platform="huya", name="测试主播甲", rid="100001", avatar="", cate="英雄联盟", live=True),
        dict(platform="douyu", name="测试主播乙", rid="100002", avatar="", cate="户外", live=False)]
json.dump(favs, open(os.path.join(d, "favorites.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"theme": "light", "danmaku_on": False, "potplayer": exe}, open(os.path.join(d, "config.json"), "w", encoding="utf-8"))
env = dict(os.environ, APPDATA=tmp)
user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
user32.SetProcessDPIAware()
proc = subprocess.Popen([exe], env=env)
try:
    hwnd = 0
    for _ in range(100):
        time.sleep(0.2)
        hwnd = user32.FindWindowW(None, "直播助手 v1.1.2")
        if hwnd:
            break
    print("hwnd", bool(hwnd), "title ok" if hwnd else "NOT FOUND")
    time.sleep(2.5)
    ok = user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # 仅把被测窗口置顶，避免被别的窗口挡住
    print("SetWindowPos topmost ->", ok, "err", ctypes.GetLastError(), "exstyle topmost:", bool(user32.GetWindowLongW(wintypes.HWND(hwnd), -20) & 8))
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    res = {}
    if os.environ.get("PKG_SHOT"):
        from PIL import ImageGrab
        r0 = wintypes.RECT(); dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r0), ctypes.sizeof(r0))
        print("rect", r0.left, r0.top, r0.right, r0.bottom)
        ImageGrab.grab(bbox=(r0.left, r0.top, r0.right, r0.bottom)).save(os.environ["PKG_SHOT"])
    for label in ("light_to_dark", "dark_to_light", "light_to_dark_2"):
        r = wintypes.RECT()
        dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r))
        rect = (r.left, r.top, r.right, r.bottom)
        outp = os.path.join(tmp, "frames.pkl"); ready = os.path.join(tmp, "ready.flag")
        for f in (outp, ready):
            if os.path.exists(f): os.remove(f)
        g = subprocess.Popen([sys.executable, os.path.join(here, "test_theme_flicker.py"), "--grab"] + [str(x) for x in rect] + ["3.2", outp, ready])
        while not os.path.exists(ready):
            time.sleep(0.01)
        time.sleep(0.6)
        t_toggle = time.perf_counter()
        # 点击"深色"开关：窗口右上，标题栏下方约 125px、距右缘约 77px（960x640 默认尺寸的实测位置）
        x, y = rect[2] - 77, rect[1] + 125
        pt = wintypes.POINT(x, y)
        top = user32.GetAncestor(user32.WindowFromPoint(pt), 2)   # GA_ROOT
        if top != hwnd:      # 点击位置不是被测窗口就不点，免得误点别的程序
            buf = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(top, buf, 256)
            print("top", top, repr(buf.value), "hwnd", hwnd, "pt", x, y, "rect", rect)
            print("ABORT: click point is not over the test window"); g.wait(); break
        user32.SetCursorPos(x, y)
        user32.mouse_event(2, 0, 0, 0, 0); user32.mouse_event(4, 0, 0, 0, 0)
        time.sleep(2.4)
        g.wait()
        frames = [(t, Image.frombytes("RGB", sz, raw)) for t, sz, raw in pickle.load(open(outp, "rb"))]
        r = analyze(frames, t_toggle)
        res[label] = r
        print(label, json.dumps({k: v for k, v in r.items() if k != "seq"}, ensure_ascii=False))
    cfg = json.load(open(os.path.join(d, "config.json"), encoding="utf-8"))
    print("config theme after:", cfg.get("theme"))
    if outfile:
        json.dump(res, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
finally:
    proc.terminate()
