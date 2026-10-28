# -*- coding: utf-8 -*-
"""v1.3.0 设置窗口与相关功能的界面测试（用临时配置目录，不碰真实数据；网络、注册表、文件对话框都用假的）。
运行：python test_settings_ui.py [截图输出目录]"""
import os
import shutil
import sys
import tempfile
import threading
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
_out_arg = sys.argv[1] if len(sys.argv) > 1 else None
sys.argv = [os.path.join(here, "app.py")]
import core

TMP = os.path.join(tempfile.gettempdir(), "lt_settings_ui")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
core.APPDIR = TMP
core.FAV_FILE = os.path.join(TMP, "favorites.json")
core.CFG_FILE = os.path.join(TMP, "config.json")
core.AVATAR_DIR = os.path.join(TMP, "avatars")
OUT = _out_arg or os.path.join(tempfile.gettempdir(), "lt_settings_shots")
os.makedirs(OUT, exist_ok=True)

import app
import sysset
from PIL import ImageGrab

res = []


def T(name, cond):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def pump(a, sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        a.update()
        time.sleep(0.01)


def wait(a, fn, sec=4.0):
    t0 = time.time()
    while time.time() - t0 < sec:
        a.update()
        if fn():
            return True
        time.sleep(0.02)
    return False


def shot(a, win, name):
    win.attributes("-topmost", True)
    pump(a, 0.5)
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    ImageGrab.grab(bbox=(x - 8, y - 40, x + w + 8, y + h + 8)).save(os.path.join(OUT, name + ".png"))
    win.attributes("-topmost", False)


# ---- 假的外部依赖
LOG = {"info": [], "ask": [], "choose": []}
ASK_ANSWER = [True]
app.info = lambda master, title, msg: LOG["info"].append((title, msg))
app.ask = lambda master, title, msg, yes="确定", no="取消": (LOG["ask"].append((title, msg)), ASK_ANSWER[0])[1]
CHOOSE_ANSWER = [("exit", False)]
app.choose = lambda *a, **k: (LOG["choose"].append(a[1]), CHOOSE_ANSWER[0])[1]
REG = {"state": "off", "set": [], "fail": False}
sysset.autostart_available = lambda: True
sysset.autostart_state = lambda name=sysset.RUN_NAME: REG["state"]


def fake_set(on, name=sysset.RUN_NAME, command=None):
    if REG["fail"]:
        raise PermissionError("denied")
    REG["set"].append(on)
    REG["state"] = "on" if on else "off"


sysset.autostart_set = fake_set
core.kill_tree = lambda proc: None
core.lookup_room = lambda p, r: {"live": True, "avatar": ""}
FAVS = [dict(platform="huya", name="甲", rid="1", avatar="", cate="", live=False),
        dict(platform="douyu", name="乙", rid="2", avatar="", cate="", live=False)]
core.save_favorites(FAVS)


class FakeProc:
    pid = os.getpid()

    def __init__(self):
        self._ev = threading.Event()
        self.stdout = self._lines()

    def _lines(self):          # 生成器：被读取时才阻塞，直到 _ev 被置位
        self._ev.wait()
        return
        yield

    def wait(self):
        self._ev.wait()
        return 0


def new_app():
    a = app.App()
    a.update()
    return a


# ================================================================ 1. 首次启动：默认值 + 各页能建出来
a = new_app()
T("默认值补全到配置", all(k in a.cfg for k in sysset.SETTING_DEFAULTS))
T("默认三个平台都开", all(a.pstate.values()))
T("首次启动窗口居中（无记忆）", a._saved_geometry() is None)
T("播放栏有设置按钮、旧的右侧按钮没了", not hasattr(a, "open_danmaku_settings"))
a.open_settings()
a.update()
w = a._settings
T("设置窗口打开，默认通用页", w is not None and w.current == "通用")
for i, name in enumerate(w.PAGES):
    w.show_page(name)
    pump(a, 0.2)
    shot(a, w, "%02d-%s" % (i + 1, name))
T("六个页面都能建出来", set(w.pages) == set(w.PAGES))
a.open_settings("播放")
T("再次打开只切页不新开窗口", a._settings is w and w.current == "播放")
T("导航高亮当前页", w.navs["播放"].cget("text_color") == app.PRIMARY)

# ================================================================ 2. 通用页
w.show_page("通用")
sw = w.switches
T("开机自启当前为关", not w.autostart_sw.get())
w.autostart_sw.toggle(); a.update()
T("打开开机自启 → 写入启动项", REG["set"] == [True] and w.autostart_sw.get() == 1)
w.autostart_sw.toggle(); a.update()
T("关闭开机自启 → 删除启动项", REG["set"] == [True, False] and not w.autostart_sw.get())
REG["fail"] = True
w.autostart_sw.toggle(); a.update()
T("写入失败 → 开关回弹并提示", not w.autostart_sw.get() and LOG["info"] and "denied" in LOG["info"][-1][1])
REG["fail"] = False
REG["state"] = "blocked"
w._autostart_sync()
T("被系统禁用 → 开关为关并红字提示", not w.autostart_sw.get() and "已被系统禁用" in w.auto_desc.cget("text"))
w.autostart_sw.toggle(); a.update()
T("在禁用状态再打开 → 重新启用", REG["state"] == "on" and w.autostart_sw.get() == 1)
w.autostart_sw.toggle(); a.update()

T("待命开关默认开并可关", sw["start_minimized"].get() == 1)
sw["start_minimized"].toggle(); a.update()
T("待命开关写入配置", core.load_config()["start_minimized"] is False)
sw["start_minimized"].toggle(); a.update()

m = w.menus["close_action"]
T("关闭行为默认“退出程序”", m.get() == "退出程序")
m.set("最小化到托盘"); m._command("最小化到托盘"); a.update()
T("关闭行为写入配置", core.load_config()["close_action"] == "tray")
m.set("每次询问"); m._command("每次询问"); a.update()
T("关闭行为 ask 写入配置", core.load_config()["close_action"] == "ask")

sw["remember_window"].toggle(); a.update()
T("记住窗口可关", core.load_config()["remember_window"] is False)
sw["remember_window"].toggle(); a.update()

w.plat_cb["douyu"].toggle(); a.update()
T("取消一个默认平台 → 保存并让搜索栏按钮同步", core.load_config()["default_platforms"] == ["huya", "bili"] and not a.pstate["douyu"] and a.pstate["huya"])
w.plat_cb["huya"].toggle(); w.plat_cb["bili"].toggle(); a.update()
T("不能取消最后一个平台", core.load_config()["default_platforms"] == ["bili"] and w.plat_cb["bili"].get() == 1
  and "至少要保留一个平台" in w.plat_desc.cget("text"))
w.plat_cb["huya"].toggle(); w.plat_cb["douyu"].toggle(); a.update()
T("恢复三个平台", core.load_config()["default_platforms"] == ["huya", "douyu", "bili"] and all(a.pstate.values()))

m = w.menus["fav_refresh_min"]
m.set("每 5 分钟"); m._command("每 5 分钟"); a.update()
T("自动刷新间隔写入配置", core.load_config()["fav_refresh_min"] == 5)
shot(a, w, "10-通用-改动后")

# ================================================================ 3. 播放页：PotPlayer 显示 + 睡眠定时
w.show_page("播放")
a.potplayer = None
w.refresh_player()
T("没找到 PotPlayer → 红字提示", "未找到" in w.player_lbl.cget("text"))
a.potplayer = r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe"
a._settings_refresh()
T("找到后显示路径", "PotPlayerMini64.exe" in w.player_lbl.cget("text"))
shot(a, w, "11-播放-有路径")
a.potplayer = r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe"
m = w.menus["sleep_minutes"]
m.set("30 分钟"); m._command("30 分钟"); a.update()
T("睡眠定时写入配置", core.load_config()["sleep_minutes"] == 30)
orig_start = core.start_play
fp = FakeProc()
core.start_play = lambda *x, **k: fp
a.play_item(dict(platform="huya", name="甲", rid="1", avatar="", cate="", live=True))
a.update()
T("开始播放后设置了睡眠定时", a._sleep_job is not None and a.proc is fp)
a.stop_play(quiet=True)
T("手动停止会取消睡眠定时", a._sleep_job is None and a.proc is None)
fp._ev.set()
fp = FakeProc()
core.start_play = lambda *x, **k: fp
a.play_item(dict(platform="huya", name="甲", rid="1", avatar="", cate="", live=True))
a.update()
a._sleep_fire()
T("定时到点 → 停止播放并提示", a.proc is None and "睡眠定时已到" in a.status.cget("text"))
fp._ev.set()
m.set("不启用"); m._command("不启用"); a.update()
fp = FakeProc()
core.start_play = lambda *x, **k: fp
a.play_item(dict(platform="huya", name="甲", rid="1", avatar="", cate="", live=True))
a.update()
T("不启用时不设置定时", a._sleep_job is None)
a.stop_play(quiet=True)
fp._ev.set()
core.start_play = orig_start

# ================================================================ 4. 弹幕页 / 外观页
w.show_page("弹幕")
T("弹幕页有区域和渲染菜单", {"dm_area", "dm_renderer"} <= set(w.menus))
w.menus["dm_area"].set("全屏"); w.menus["dm_area"]._command("全屏"); a.update()
T("弹幕区域写入配置", core.load_config()["dm_area"] == "全屏")
w.show_page("外观")
T("外观页主题开关为关（浅色）", w.theme_sw.get() == 0 and app.THEME == "light")
w.theme_sw.toggle(); pump(a, 0.4)
T("设置里切深色 → 主窗口开关与主题同步", app.THEME == "dark" and a.theme_sw.get() == 1 and core.load_config()["theme"] == "dark")
shot(a, w, "12-外观-深色")
a.theme_sw.toggle(); a.switch_theme(); pump(a, 0.3)
T("主窗口切回浅色 → 设置页开关同步", app.THEME == "light" and w.theme_sw.get() == 0)

# ================================================================ 5. 数据页：缓存 / 备份 / 恢复默认
os.makedirs(core.AVATAR_DIR, exist_ok=True)
for i in range(3):
    open(os.path.join(core.AVATAR_DIR, "x%d.img" % i), "wb").write(b"0" * 3000)
w.rebuild()
w.show_page("数据")
T("缓存统计显示张数", "3 张" in w.cache_lbl.cget("text"))
shot(a, w, "13-数据")
w._clear_cache(); a.update()
T("清理后文件没了、文字更新", sysset.cache_info() == (0, 0) and "已清理 3 张" in w.cache_lbl.cget("text"))

bk_path = os.path.join(TMP, "backup.json")
app.filedialog.asksaveasfilename = lambda **k: bk_path
a.favs = [dict(f) for f in FAVS]
a.cfg["dm_font"] = 44
w._export(); a.update()
T("导出生成文件且提示成功", os.path.isfile(bk_path) and LOG["info"][-1][0] == "已导出")
# 改乱当前状态，再导入
a.cfg["dm_font"] = 20
a.favs = [dict(platform="bili", name="丙", rid="3", avatar="", cate="", live=False)]
a.rebuild_favs()
app.filedialog.askopenfilename = lambda **k: bk_path
ASK_ANSWER[0] = True
w._import(); pump(a, 0.3)
T("导入：设置被覆盖", a.cfg["dm_font"] == 44 and core.load_config()["dm_font"] == 44)
T("导入：保留现有收藏并补上缺的", sorted(f["rid"] for f in a.favs) == ["1", "2", "3"] and len(a.fav_cards) == 3)
T("导入：提示新增 2 个收藏", "新增 2 个收藏" in LOG["info"][-1][1])
ASK_ANSWER[0] = False
n_before = len(a.favs)
w._import(); a.update()
T("导入时点取消 → 什么都不改", len(a.favs) == n_before)
ASK_ANSWER[0] = True
open(bk_path, "w", encoding="utf-8").write("{not json")
w._import(); a.update()
T("导入坏文件 → 友好提示", LOG["info"][-1][0] == "无法导入")

a.cfg["close_action"] = "tray"; a.cfg["theme"] = "light"; a.cfg["potplayer"] = "C:/keep.exe"
w.show_page("数据")
w._reset(); pump(a, 0.3)
T("恢复默认：设置回到默认", a.cfg["close_action"] == "exit" and a.cfg["dm_font"] == 28 and core.load_config()["dm_font"] == 28)
T("恢复默认：PotPlayer 路径和收藏保留", a.cfg["potplayer"] == "C:/keep.exe" and len(a.favs) == 3)
T("恢复默认：同时关闭开机自启", REG["state"] == "off")
ASK_ANSWER[0] = False
a.cfg["dm_font"] = 40
w._reset(); a.update()
T("恢复默认点取消 → 不改", a.cfg["dm_font"] == 40)
a.cfg["dm_font"] = 28
ASK_ANSWER[0] = True

# ================================================================ 6. 关于页
w.show_page("关于")
shot(a, w, "14-关于")
T("关于页显示当前版本", "v%s" % app.__version__ in w.upd_lbl.cget("text"))
T("启动时检查更新开关存在", "update_check" in w.switches)

# ================================================================ 7. 收藏刷新（就地更新，不重建）
w.destroy(); a.update()
a.favs = [dict(f) for f in FAVS]
a.rebuild_favs()
cards_before = list(a.fav_cards)
a._fav_busy = False
a.refresh_fav_status()
T("刷新期间标记忙", a._fav_busy is True)
T("刷新完成后标记清除", wait(a, lambda: not a._fav_busy))
T("就地更新：卡片对象没变、状态变成直播中", a.fav_cards == cards_before and all(f["live"] for f in a.favs)
  and all("直播" in c.live_lbl.cget("text") for c in a.fav_cards))
a.refresh_fav_status(); a.refresh_fav_status()
T("重复触发不会叠加请求", wait(a, lambda: not a._fav_busy))
calls = []
core.lookup_room = lambda p, r: (calls.append(r), {"live": False, "avatar": ""})[1]
a.cfg["fav_refresh_min"] = 5
a._fav_last = time.time()
a._fav_tick()
T("没到间隔不刷新", not calls and not a._fav_busy)
a._fav_last = time.time() - 6 * 60
a._fav_tick()
T("到了间隔自动刷新", wait(a, lambda: len(calls) == 2 and not a._fav_busy))
a.cfg["fav_refresh_min"] = 0
a._fav_last = time.time() - 3600
calls.clear()
a._fav_tick(); pump(a, 0.3)
T("间隔设为不自动刷新则不动", not calls)

# ================================================================ 8. 关闭行为：托盘 / 询问 / 退出
a.cfg["close_action"] = "tray"
a.geometry("900x600+120+80"); pump(a, 0.3)
a.on_close(); pump(a, 0.8)
T("关到托盘：窗口隐藏、托盘出现", a.state() == "withdrawn" and a.tray is not None and a.tray.visible)
T("关到托盘时记住了窗口位置", sysset.parse_geom(core.load_config().get("win_geom")) == (900, 600, 120, 80))
a.show_window(); pump(a, 0.8)
T("从托盘唤起：窗口恢复、托盘撤掉", a.state() == "normal" and not a.tray.visible)
a.cfg["close_action"] = "ask"
CHOOSE_ANSWER[0] = (None, False)
a.on_close(); a.update()
T("询问后点取消 → 不关闭", a.state() == "normal" and LOG["choose"])
CHOOSE_ANSWER[0] = ("tray", True)
a.on_close(); pump(a, 0.6)
T("询问选托盘并勾选记住 → 隐藏且记住选择", a.state() == "withdrawn" and core.load_config()["close_action"] == "tray")
a.show_window(); pump(a, 0.6)
a.cfg["close_action"] = "exit"
a.on_close()
try:
    alive = bool(a.winfo_exists())
except Exception:
    alive = False
T("close_action=exit → 窗口销毁", not alive)

# ================================================================ 9. 重启：记住位置 + 默认平台
cfg_now = core.load_config()
cfg_now["default_platforms"] = ["huya"]
core.save_config(cfg_now)
b = new_app()
g = sysset.parse_geom(b.geometry())
T("重启后窗口回到上次的大小和位置", g == (900, 600, 120, 80))
T("重启后搜索栏按钮按默认平台", b.pstate == {"huya": True, "douyu": False, "bili": False})
b.quit_app()
cfg_now = core.load_config()
cfg_now["win_geom"] = "900x600+99999+80"
core.save_config(cfg_now)
c = new_app()
T("记忆的位置跑出屏幕 → 回到居中", c._saved_geometry() is None)
c.destroy()

# ================================================================ 10. 开机自启待命：不弹窗、托盘出现、不弹安装询问
cfg_now = core.load_config()
cfg_now["start_minimized"] = True
core.save_config(cfg_now)
sys.argv = [os.path.join(here, "app.py"), "--autostart"]
asked = []
orig_ask_install = app.App.ask_install
app.App.ask_install = lambda self: asked.append(1)
d = new_app()
pump(d, 0.8)
T("--autostart 且开启待命：窗口不显示", d.start_hidden and d.state() == "withdrawn")
T("--autostart：托盘图标出现", d.tray is not None and d.tray.visible)
d.potplayer = None
pump(d, 0.6)
T("待命时即使没装 PotPlayer 也不弹安装询问", not asked)
d.show_window(); pump(d, 0.8)
T("托盘点开后窗口显示", d.state() == "normal" and not d.tray.visible)
d.quit_app()
cfg_now = core.load_config()
cfg_now["start_minimized"] = False
core.save_config(cfg_now)
e = new_app()
T("--autostart 但关闭了待命：正常显示", not e.start_hidden and e.state() == "normal")
e.quit_app()
app.App.ask_install = orig_ask_install

fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d；截图在 %s" % (len(res), len(res) - len(fails), len(fails), OUT), flush=True)
shutil.rmtree(TMP, ignore_errors=True)
os._exit(1 if fails else 0)
