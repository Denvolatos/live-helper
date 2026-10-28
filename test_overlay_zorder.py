# -*- coding: utf-8 -*-
"""平滑渲染悬浮层的窗口层级回归测试：播放器事后把自己提到最上面时，悬浮层要在 1 秒内回到它上方。
用一个小的假“播放器”窗口代替 PotPlayer，不联网、不播放；窗口只在屏幕角落出现几秒。"""
import ctypes
import os
import sys
import time
import tkinter as tk

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import danmaku

u = ctypes.windll.user32
u.GetWindow.restype = ctypes.c_void_p
u.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
u.GetParent.restype = ctypes.c_void_p
u.GetWindowLongPtrW.restype = ctypes.c_void_p
u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
NOMOVE_NOSIZE_NOACTIVATE = 0x0001 | 0x0002 | 0x0010
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = 0, -1, -2
res = []


def T(name, cond, extra=""):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (("  " + extra) if extra else ""), flush=True)


root = tk.Tk()
root.withdraw()
player = tk.Toplevel(root)
player.title("zorder-fake-player")
player.geometry("260x160+30+30")
player.update()
ph = u.GetParent(player.winfo_id())
ov = danmaku.LayeredOverlay(root, dict(danmaku.DEFAULTS))
RECT = (30, 30, 260, 160)

calls = []
_orig = danmaku.user32.SetWindowPos


def counting(*a):
    calls.append(a)
    return _orig(*a)


danmaku.user32.SetWindowPos = counting


def above(a, b):
    """a 是否在 b 的上方（从 b 沿 Z 序往上找）"""
    h = u.GetWindow(b, 3)      # GW_HWNDPREV
    while h:
        if h == a:
            return True
        h = u.GetWindow(h, 3)
    return False


def follow(sec, topmost=False):
    """和主程序 _follow 一样：每 60ms 重复给出同样的期望状态"""
    t0 = time.time()
    while time.time() - t0 < sec:
        ov.show(RECT, ph, topmost)
        root.update()
        time.sleep(0.06)


def wait_above(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        ov.show(RECT, ph, False)
        root.update()
        if above(ov.hwnd, ph):
            return time.time() - t0
        time.sleep(0.03)
    return None


try:
    follow(0.8)
    T("起始：悬浮层紧贴在播放器上方", above(ov.hwnd, ph))
    n0 = len(calls)
    follow(1.5)
    T("层级没变时不重复摆放（1.5 秒内最多 8 次 SetWindowPos 调用）", len(calls) - n0 <= 8, "calls=%d" % (len(calls) - n0))

    for i in range(3):
        u.SetWindowPos(ph, HWND_TOP, 0, 0, 0, 0, NOMOVE_NOSIZE_NOACTIVATE)      # 播放器自己提到最上面
        covered = not above(ov.hwnd, ph)
        t = wait_above(1.5)
        T("第 %d 次：播放器提到最上面后，悬浮层在 1 秒内回到上方" % (i + 1), covered and t is not None and t <= 1.0,
          "covered=%s t=%s" % (covered, None if t is None else round(t, 2)))

    # 播放器变成置顶（全屏）：悬浮层应跟着置顶
    u.SetWindowPos(ph, HWND_TOPMOST, 0, 0, 0, 0, NOMOVE_NOSIZE_NOACTIVATE)
    follow(0.8, topmost=True)
    ex = u.GetWindowLongPtrW(ov.hwnd, -20) or 0
    T("播放器置顶时悬浮层也置顶", bool(ex & 0x8))
    # 回到非置顶：悬浮层应取消置顶并回到播放器上方
    u.SetWindowPos(ph, HWND_NOTOPMOST, 0, 0, 0, 0, NOMOVE_NOSIZE_NOACTIVATE)
    follow(0.5)
    ex = u.GetWindowLongPtrW(ov.hwnd, -20) or 0
    T("播放器取消置顶后悬浮层取消置顶并仍在上方", not (ex & 0x8) and above(ov.hwnd, ph))
    u.SetWindowPos(ph, HWND_TOP, 0, 0, 0, 0, NOMOVE_NOSIZE_NOACTIVATE)
    T("取消置顶后同样能自动恢复", wait_above(1.5) is not None)
finally:
    danmaku.user32.SetWindowPos = _orig
    ov.destroy()
    root.destroy()

fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(fails), len(fails)), flush=True)
os._exit(1 if fails else 0)
