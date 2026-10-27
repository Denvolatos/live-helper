# -*- coding: utf-8 -*-
"""界面截图自检：运行界面，搜索、收藏，截图保存到 screenshots/。用临时目录，不污染用户数据。"""
import os, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.argv = [os.path.join(here, "app.py")]
import core
core.APPDIR = os.path.join(tempfile.gettempdir(), "lt_ui_test")
core.FAV_FILE = os.path.join(core.APPDIR, "favorites.json")
core.CFG_FILE = os.path.join(core.APPDIR, "config.json")
core.AVATAR_DIR = os.path.join(core.APPDIR, "avatars")
import shutil
shutil.rmtree(core.APPDIR, ignore_errors=True)
import app
from PIL import ImageGrab

out = os.path.join(here, "screenshots")
os.makedirs(out, exist_ok=True)
kw = sys.argv_kw if hasattr(sys, "argv_kw") else os.environ.get("UI_KW", "示例主播乙")
a = app.App()


def shot(name):
    a.update()
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(os.path.join(out, name))
    print("shot", name, w, h)


def s0():
    a.lift(); a.attributes("-topmost", True); shot("01-start.png")
    a.kw.insert(0, kw); a.do_search()


def s1():
    shot("02-results.png")
    for c in a.cards[:2]:
        c.fav_btn.invoke()
    if a.cards:
        a.select_card(a.cards[0])


def s2():
    shot("03-fav-selected.png")
    a.geometry("780x540")


def s3():
    shot("04-small.png"); a.geometry("960x640"); a.theme_sw.select(); a.switch_theme()


def s4():
    shot("05-dark.png")
    app.info(a, "未找到 PotPlayer", "这台电脑上没有检测到 PotPlayer。是否用 winget 自动安装？")


def s5():
    a.update(); shot("06-dialog-dark.png"); a.destroy()


a.after(1200, s0); a.after(9000, s1); a.after(11000, s2); a.after(12500, s3); a.after(14500, s4); a.after(16500, s5)
a.mainloop()
