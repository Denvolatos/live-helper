# -*- coding: utf-8 -*-
"""打包版 exe 的生命周期实测：单实例、关到托盘/从托盘唤起、退出时记住窗口位置、--autostart 待命。
用临时的 APPDATA 目录和独立的单实例名字，不碰真实配置，也不会和正在运行的正式版互相干扰。
用法: python test_packaged_lifecycle.py <LiveHelper.exe 路径>"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import psutil

EXE = os.path.abspath(sys.argv[1])
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from version import __version__
TITLE = "LatoMedia v%s" % __version__
u = ctypes.windll.user32
u.FindWindowW.restype = wt.HWND
u.IsWindowVisible.argtypes = [wt.HWND]
u.IsIconic.argtypes = [wt.HWND]
u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

ROOT = os.path.join(tempfile.gettempdir(), "lt_pkg_lifecycle")
shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(ROOT)
APPDATA = os.path.join(ROOT, "appdata")
CFG = os.path.join(APPDATA, "直播助手", "config.json")
os.makedirs(os.path.dirname(CFG))
ENV = dict(os.environ, APPDATA=APPDATA, LIVEHELPER_INSTANCE_TAG="pkgtest%d" % os.getpid())
procs = []
res = []


def T(name, cond, extra=""):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (("  " + extra) if extra else ""), flush=True)


def find():
    h = u.FindWindowW(None, TITLE)
    return h or None


def visible():
    h = find()
    return bool(h) and bool(u.IsWindowVisible(h)) and not u.IsIconic(h)


def wait(fn, sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        if fn():
            return True
        time.sleep(0.2)
    return False


def launch(*args):
    p = subprocess.Popen([EXE, *args], env=ENV)
    procs.append(p)
    return p


def alive(p):
    return p.poll() is None


def kill_all():
    for p in procs:
        try:
            parent = psutil.Process(p.pid)
            for c in parent.children(recursive=True):
                c.kill()
            parent.kill()
        except Exception:
            pass
    time.sleep(1.0)


def write_cfg(**kw):
    json.dump(kw, open(CFG, "w", encoding="utf-8"), ensure_ascii=False)


def rect():
    r = wt.RECT()
    u.GetWindowRect(find(), ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def tray_windows(pid):
    """该进程里 pystray 创建的托盘消息窗口（类名 LiveHelper<编号>SystemTrayIcon，图标窗和菜单窗各一个）数量。"""
    found = []
    cb = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def each(h, _):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, buf, 64)
        if p.value == pid and buf.value.startswith("LiveHelper") and buf.value.endswith("SystemTrayIcon"):
            found.append(h)
        return True
    u.EnumWindows(cb(each), 0)
    return len(found)


def close_window():
    u.PostMessageW(find(), 0x0010, 0, 0)       # WM_CLOSE：等同点右上角 ✕


try:
    # ---- 1. 普通启动 + 单实例
    T("环境里没有同名窗口残留", find() is None)
    write_cfg(close_action="exit")
    p1 = launch()
    T("启动后窗口显示", wait(visible, 20))
    p2 = launch()
    T("第二次启动的进程很快退出且退出码 0", wait(lambda: not alive(p2), 10) and p2.returncode == 0)
    T("第一个实例仍在运行，窗口仍是一个", alive(p1) and visible())
    # 手动藏起第一个窗口后再启动，应被唤起 —— 用 ShowWindow 模拟不可靠，这里放到托盘用例里验证
    close_window()
    T("close_action=exit：点 ✕ 后进程退出", wait(lambda: not alive(p1), 10) and p1.returncode == 0)
    cfg = json.load(open(CFG, encoding="utf-8"))
    T("退出时记住了窗口位置", isinstance(cfg.get("win_geom"), str) and "x" in cfg["win_geom"], str(cfg.get("win_geom")))
    saved = cfg.get("win_geom")

    # ---- 2. 重启后窗口位置恢复
    p1 = launch()
    T("重启后窗口显示", wait(visible, 20))
    time.sleep(1.0)
    import re
    m = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", saved)
    sw, sh, sx, sy = (int(g) for g in m.groups())
    x, y, w, h = rect()
    T("窗口位置与上次关闭时一致", (x, y) == (sx, sy), "now=%s saved=%s" % ((x, y), (sx, sy)))
    close_window()
    wait(lambda: not alive(p1), 10)

    # ---- 3. 关到托盘 + 再次启动唤起
    write_cfg(close_action="tray")
    p1 = launch()
    T("托盘用例：启动后窗口显示", wait(visible, 20))
    close_window()
    T("点 ✕ → 窗口隐藏（说明托盘图标创建成功）", wait(lambda: not visible() and not (find() and u.IsIconic(find())), 8))
    T("隐藏后进程仍在运行", alive(p1))
    T("隐藏后该进程里存在托盘图标窗口", wait(lambda: tray_windows(p1.pid) >= 1, 5))
    p2 = launch()
    T("托盘用例：再次启动 → 原窗口被唤起", wait(visible, 10))
    T("唤起后托盘图标已撤掉", wait(lambda: tray_windows(p1.pid) == 0, 5))
    T("托盘用例：第二个进程已退出，第一个仍在", wait(lambda: not alive(p2), 10) and alive(p1))
    close_window()
    T("再次点 ✕ → 又隐藏", wait(lambda: not visible(), 8))
    kill_all()

    # ---- 4. --autostart 待命
    write_cfg(close_action="exit", start_minimized=True)
    p1 = launch("--autostart")
    time.sleep(8)
    T("--autostart + 待命：窗口不显示", find() is not None and not visible())
    T("--autostart + 待命：进程在运行", alive(p1))
    T("--autostart + 待命：托盘图标窗口存在", tray_windows(p1.pid) >= 1)
    p2 = launch()
    T("待命时再次启动 → 窗口显示", wait(visible, 10))
    kill_all()
    write_cfg(close_action="exit", start_minimized=False)
    p1 = launch("--autostart")
    T("--autostart 但关闭了待命：窗口正常显示", wait(visible, 20))
    kill_all()
finally:
    kill_all()

fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(fails), len(fails)), flush=True)
shutil.rmtree(ROOT, ignore_errors=True)
sys.exit(1 if fails else 0)
