# -*- coding: utf-8 -*-
"""弹幕悬浮层端到端实测：真实启动 PotPlayer 播放斗鱼/虎牙，开弹幕，截图，测跟随/最小化/快捷键/全屏。
用临时配置目录，不污染用户数据。结果写 screenshots/danmaku_test.log。"""
import os, sys, tempfile, shutil, time, ctypes
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.argv = [os.path.join(here, "app.py")]
import core
core.APPDIR = os.path.join(tempfile.gettempdir(), "lt_dm_test")
core.FAV_FILE = os.path.join(core.APPDIR, "favorites.json")
core.CFG_FILE = os.path.join(core.APPDIR, "config.json")
core.AVATAR_DIR = os.path.join(core.APPDIR, "avatars")
shutil.rmtree(core.APPDIR, ignore_errors=True)
import app, danmaku
from danmaku import user32
from PIL import ImageGrab
PLAT, RID = (sys.argv_extra if hasattr(sys, "argv_extra") else os.environ.get("DM_TEST", "douyu:222222").split(":"))
out = os.path.join(here, "screenshots"); os.makedirs(out, exist_ok=True)
logf = open(os.path.join(out, "danmaku_test.log"), "a", encoding="utf-8")
def log(*a):
    s = " ".join(str(x) for x in a); print(s); logf.write(s + "\n"); logf.flush()
log("=== %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"), PLAT, RID)
a = app.App()
a.cfg["danmaku_on"] = True; a.dm_sw.select()
def shot(name):
    a.update(); ImageGrab.grab(all_screens=True).save(os.path.join(out, name)); log("shot", name)
def key(vk, mods=()):
    for m in mods: user32.keybd_event(m, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0); user32.keybd_event(vk, 0, 2, 0)
    for m in reversed(mods): user32.keybd_event(m, 0, 2, 0)
def state(tag):
    dm = a.dm; ov = dm.overlay
    r = danmaku.client_rect(dm.hwnd) if dm.hwnd else None
    log(tag, "pot_hwnd", dm.hwnd, "client", r, "overlay_visible", ov.visible if ov else None,
        "overlay_geo", ov.win.winfo_geometry() if ov else None, "收到弹幕数", dm.count,
        "屏上", len(ov.items) if ov else None, "丢弃", ov.dropped if ov else None, "client_ok", dm.client.connected if dm.client else None)
steps = []
def s_play():
    a.potplayer = core.find_potplayer(a.cfg); log("potplayer", a.potplayer)
    a.play_item(dict(platform=PLAT, rid=RID, name="测试", avatar="")); log("hotkey_ok", a.hotkey_ok)
def s_state1(): state("播放20s后")
def s_shot1(): shot("dm_01_playing.png"); log("前3条弹幕文本(overlay已收):", getattr(a.dm, "sample", None))
def s_move():
    h = a.dm.hwnd
    user32.MoveWindow(h, 100, 100, 800, 500, True); log("移动PotPlayer到(100,100,800x500)")
def s_state2(): state("移动后"); shot("dm_02_moved.png")
def s_min():
    user32.ShowWindow(a.dm.hwnd, 6); log("最小化PotPlayer")
def s_state3(): state("最小化后")
def s_restore(): user32.ShowWindow(a.dm.hwnd, 9); log("还原PotPlayer")
def s_state4(): state("还原后")
def s_hot():
    key(0x44, (0x11, 0x12)); log("发送 Ctrl+Alt+D")
def s_state5(): state("快捷键后(应关闭)"); log("开关状态 enabled=", a.dm.enabled, "ui switch=", a.dm_sw.get())
def s_hot2(): key(0x44, (0x11, 0x12)); log("再发送 Ctrl+Alt+D")
def s_state6(): state("再次快捷键后(应开启)"); log("enabled=", a.dm.enabled)
def s_fs():
    user32.SetForegroundWindow(a.dm.hwnd); time.sleep(0.3); key(0x0D); log("发送 Enter(PotPlayer 全屏)")
def s_state7(): state("全屏后"); shot("dm_03_fullscreen.png")
def s_fs2(): user32.SetForegroundWindow(a.dm.hwnd); time.sleep(0.3); key(0x0D); log("退出全屏")
def s_stop():
    a.stop_play(); log("停止播放后 overlay_visible=", a.dm.overlay.visible, "client=", a.dm.client)
def s_end(): log("线程数", __import__("threading").active_count()); a.on_close(); log("DONE"); os._exit(0)
seq = [(1500, s_play), (22000, s_state1), (200, s_shot1), (500, s_move), (2000, s_state2), (500, s_min), (1500, s_state3),
       (200, s_restore), (1500, s_state4), (200, s_hot), (1500, s_state5), (200, s_hot2), (1500, s_state6),
       (200, s_fs), (3000, s_state7), (200, s_fs2), (2000, s_stop), (1500, s_end)]
t = 0
for d, f in seq:
    t += d; a.after(t, f)
# 记录前3条弹幕
orig = danmaku.Overlay.push
def push(self, text):
    a.dm.sample = getattr(a.dm, "sample", None) or []
    if len(a.dm.sample) < 3: a.dm.sample.append(text)
    orig(self, text)
danmaku.Overlay.push = push
a.mainloop()
