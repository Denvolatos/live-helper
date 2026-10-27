# -*- coding: utf-8 -*-
"""全状态界面截图（浅/深色各一遍，全部假数据，不联网）。输出到 screenshots/theme/。
用法: python test_ui_all.py [light|dark]   —— 参数是启动时的主题；light 启动会再切到深色并重抓一遍（验证就地重绘）。"""
import os, sys, tempfile, shutil, time, ctypes
from ctypes import wintypes
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
START = sys.argv[1] if len(sys.argv) > 1 else "light"
sys.argv = [os.path.join(here, "app.py")]
import core
core.APPDIR = os.path.join(tempfile.gettempdir(), "lt_ui_all_" + START)
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
core.save_favorites([dict(FAKE[0]), dict(FAKE[1]), dict(FAKE[2])])
core.save_config({"theme": START, "danmaku_on": False})
import app
app.App.refresh_qualities = lambda self, it: None
app.App.refresh_fav_status = lambda self: None
app.App.check_potplayer = lambda self: setattr(self, "potplayer", "PotPlayerMini64.exe")
from PIL import ImageGrab

out = os.path.join(here, "screenshots", "theme")
os.makedirs(out, exist_ok=True)
dwm, user32 = ctypes.windll.dwmapi, ctypes.windll.user32


def rect_of(win):
    hwnd = user32.GetParent(win.winfo_id())
    r = wintypes.RECT()
    dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r))
    return (r.left, r.top, r.right, r.bottom)


a = app.App()
a.lift(); a.attributes("-topmost", True)
a.update()


def settle(win=None, n=12):
    for _ in range(n):
        a.update(); time.sleep(0.03)


def shot(tag, name, win=None):
    settle()
    win = win or a
    ImageGrab.grab(bbox=rect_of(win)).save(os.path.join(out, "%s-%s.png" % (tag, name)))
    print("shot", tag, name)


def run_states(tag):
    a.geometry("960x640"); a.results = []
    a.favs = [dict(x) for x in FAKE[:3]]; a.rebuild_favs()
    a.show_hint(a.res_box, "输入主播名字回车搜索，或粘贴房间链接/房间号"); a.res_title.configure(text="搜索结果")
    a.kw.delete(0, "end")
    shot(tag, "01-start")
    a.results = [dict(x) for x in FAKE]; a.render_results(); a.res_title.configure(text="搜索结果（4）")
    a.kw.insert(0, "测试")
    shot(tag, "02-results")
    a.cards[1].fav_btn.invoke()     # 取消收藏乙，再收藏回来，顺带验证收藏栏联动
    a.cards[3].fav_btn.invoke()
    a.select_card(a.fav_cards[0])
    shot(tag, "03-fav-selected")
    a.geometry("780x540"); shot(tag, "04-small")
    a.geometry("960x640")
    a.quality.configure(values=["最高画质（自动）", "原画 8M", "蓝光 4M", "超清 2M"])
    def _dd():
        x, y = a.quality.winfo_rootx(), a.quality.winfo_rooty()
        ImageGrab.grab(bbox=(x - 20, y - 190, x + 220, y + 50)).save(os.path.join(out, "%s-08-dropdown.png" % tag))
        user32.keybd_event(0x1B, 0, 0, 0); user32.keybd_event(0x1B, 0, 2, 0)
    a.after(500, _dd)
    a.quality._open_dropdown_menu()
    settle()
    d = app.Dialog(a, "未找到 PotPlayer", "这台电脑上没有检测到 PotPlayer。\n是否用 winget 自动安装？（约需几分钟，期间请耐心等待）", "同意安装", "暂不")
    d.attributes("-topmost", True); shot(tag, "05-dialog-install", d); d.destroy()
    d = app.Dialog(a, "请手动安装 PotPlayer", "这台电脑没有 winget。\n已为你打开 PotPlayer 官方下载页。\n装好后点底部的“重新检测”即可。", "知道了", None)
    d.attributes("-topmost", True); shot(tag, "06-dialog-info", d); d.destroy()
    ds = app.DanmakuSettings(a, dict(core.load_config(), dm_font=30, dm_alpha=0.9, dm_speed=8, dm_max=60), a_dm(), True)
    ds.attributes("-topmost", True); shot(tag, "07-danmaku-settings", ds)
    state["ds"] = ds


class FakeDM:
    def apply_settings(self): pass
    def set_renderer(self, v): pass


def a_dm():
    return FakeDM()


state = {}


def main_run():
    run_states("L" if START == "light" else "D")
    if START == "light":
        # 弹幕设置窗口开着时切主题（验证已开窗口就地重绘 + 标题栏）
        a.theme_sw.toggle(); settle(None, 20)
        shot("D2", "07-danmaku-settings-live-switched", state["ds"])
        state["ds"].destroy()
        run_states("D2")
    a.destroy()


a.after(800, main_run)
a.mainloop()
