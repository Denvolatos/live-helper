# -*- coding: utf-8 -*-
"""系统相关的小功能（不含界面，方便单独测试）：设置默认值与校验、开机自启、窗口位置记忆、
备份导入导出、头像缓存、单实例唤醒、托盘图标。"""
import copy
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import threading
import time

import core
import danmaku

# ---------------------------------------------------------------- 设置默认值与校验
GENERAL_DEFAULTS = dict(
    theme="light",
    auto_resume=True,
    update_check=True,
    close_action="exit",            # exit 退出 / tray 最小化到托盘 / ask 每次询问
    start_minimized=True,           # 开机自启时只在托盘待命，不弹出窗口
    remember_window=True,
    default_platforms=list(core.PLATFORMS),
    fav_refresh_on_start=True,
    fav_refresh_min=0,              # 0 = 不自动刷新
    sleep_minutes=0,                # 0 = 不启用
)
# 弹幕开关 danmaku_on 是主窗口上的运行状态，不算“设置项”：恢复默认和备份都不动它
SETTING_DEFAULTS = dict({k: v for k, v in danmaku.DEFAULTS.items() if k != "danmaku_on"}, **GENERAL_DEFAULTS)

CLOSE_ACTIONS = [("退出程序", "exit"), ("最小化到托盘", "tray"), ("每次询问", "ask")]
REFRESH_CHOICES = [("不自动刷新", 0), ("每 5 分钟", 5), ("每 10 分钟", 10), ("每 30 分钟", 30)]
SLEEP_CHOICES = [("不启用", 0), ("30 分钟", 30), ("1 小时", 60), ("1.5 小时", 90), ("2 小时", 120)]

_CHOICES = {
    "theme": ("light", "dark"),
    "close_action": tuple(v for _, v in CLOSE_ACTIONS),
    "fav_refresh_min": tuple(v for _, v in REFRESH_CHOICES),
    "sleep_minutes": tuple(v for _, v in SLEEP_CHOICES),
    "dm_area": tuple(danmaku.AREAS),
    "dm_renderer": tuple(danmaku.RENDERERS),
}
_RANGES = {"dm_font": (16, 56), "dm_alpha": (0.3, 1.0), "dm_speed": (4, 16), "dm_max": (20, 150)}


def clean_value(key, val):
    """校验一个设置值：合法返回规整后的值，不合法抛 ValueError。"""
    default = SETTING_DEFAULTS[key]
    if key in _CHOICES:
        if val not in _CHOICES[key]:
            raise ValueError(key)
        return val
    if key == "default_platforms":
        if not isinstance(val, list):
            raise ValueError(key)
        keep = [p for p in core.PLATFORMS if p in val]
        if not keep:
            raise ValueError(key)
        return keep
    if isinstance(default, bool):
        if not isinstance(val, bool):
            raise ValueError(key)
        return val
    if key in _RANGES:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(key)
        lo, hi = _RANGES[key]
        if not lo <= val <= hi:
            raise ValueError(key)
        return round(float(val), 2) if isinstance(default, float) else int(round(val))
    raise ValueError(key)


def restore_defaults(cfg):
    """把所有“设置项”改回默认；收藏、PotPlayer 路径、画质选择、更新跳过记录等不动。"""
    for k, v in SETTING_DEFAULTS.items():
        cfg[k] = copy.deepcopy(v)


# ---------------------------------------------------------------- 开机自启（只写当前用户的启动项，不需要管理员）
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
RUN_NAME = "LiveHelper"
AUTOSTART_FLAG = "--autostart"


def exe_path():
    return sys.executable if getattr(sys, "frozen", False) else None


def app_dir():
    """安装目录（打包后是 exe 所在目录，开发时是源码目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def autostart_available():
    return exe_path() is not None


def autostart_command():
    return '"%s" %s' % (exe_path(), AUTOSTART_FLAG)


def autostart_state(name=RUN_NAME):
    """返回 "on" / "off" / "blocked"（启动项在，但被“任务管理器 → 启动应用”禁用了）。"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, name)
    except OSError:
        return "off"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
            data, _ = winreg.QueryValueEx(k, name)
        if isinstance(data, (bytes, bytearray)) and data and data[0] % 2 == 1:   # 奇数 = 已禁用
            return "blocked"
    except OSError:
        pass
    return "on"


def autostart_set(on, name=RUN_NAME, command=None):
    """打开/关闭开机自启；失败抛 OSError。重新打开时顺便清掉“被禁用”的标记。"""
    import winreg
    if on:
        cmd = command or autostart_command()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, cmd)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


# ---------------------------------------------------------------- 窗口位置记忆
def virtual_screen():
    u = ctypes.windll.user32
    return u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)


_GEOM_RE = re.compile(r"^(\d+)x(\d+)\+?(-?\d+)\+?(-?\d+)$")   # Tk 把负坐标写成 +-1200+30，也可能是 -1200+30


def parse_geom(s):
    m = _GEOM_RE.match(s or "")
    return tuple(int(g) for g in m.groups()) if m else None


def format_geom(w, h, x, y):
    return "%dx%d+%d+%d" % (w, h, x, y)       # 负坐标会写成 +-1200，Tk 和 customtkinter 都认


def fit_geom(g, scale, screen, min_size=(760, 520)):
    """检查保存的窗口位置是否还在屏幕里（换过显示器/分辨率就可能跑出屏幕）。
    g 是未缩放的 (宽, 高, x, y)，scale 是界面缩放比；不合适返回 None（调用方改用居中）。"""
    if not g:
        return None
    w, h, x, y = g
    sx, sy, sw, sh = screen
    w, h = max(w, min_size[0]), max(h, min_size[1])
    pw, ph = w * scale, h * scale
    if pw > sw:
        w = max(min_size[0], int(sw / scale))
        pw = w * scale
    if ph > sh:
        h = max(min_size[1], int(sh / scale))
        ph = h * scale
    on_screen = (x + pw > sx + 120 and x < sx + sw - 120 and y >= sy - 10 and y < sy + sh - 60)
    return (w, h, x, y) if on_screen else None


# ---------------------------------------------------------------- 备份导入导出
BACKUP_KIND = "livehelper-backup"
FAV_KEYS = ("platform", "name", "rid", "avatar", "cate", "live")


class BackupError(Exception):
    pass


def clean_favorites(favs):
    out, seen = [], set()
    for f in favs if isinstance(favs, list) else []:
        if not isinstance(f, dict) or f.get("platform") not in core.PLATFORMS:
            continue
        rid = str(f.get("rid", "")).strip()
        key = (f["platform"], rid)
        if not rid or key in seen:
            continue
        seen.add(key)
        item = {k: f.get(k, "") for k in FAV_KEYS}
        item["rid"] = rid
        item["name"] = str(item["name"] or rid)
        item["live"] = bool(item["live"])
        out.append(item)
    return out


def make_backup(cfg, favs, version):
    return dict(kind=BACKUP_KIND, version=version, saved=time.strftime("%Y-%m-%d %H:%M:%S"),
                settings={k: cfg[k] for k in SETTING_DEFAULTS if k in cfg},
                favorites=clean_favorites(favs))


def write_backup(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_backup(path):
    """读取并校验备份文件；返回 dict(settings, favorites, skipped, saved)。看不懂的内容抛 BackupError。"""
    try:
        if os.path.getsize(path) > 2 * 1024 * 1024:
            raise BackupError("文件太大，不像是直播助手的备份")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except BackupError:
        raise
    except (OSError, ValueError) as e:
        raise BackupError("无法读取这个文件：%s" % e)
    if not isinstance(data, dict) or data.get("kind") != BACKUP_KIND:
        raise BackupError("这不是直播助手的备份文件")
    settings, skipped = {}, 0
    raw = data.get("settings")
    for k, v in (raw if isinstance(raw, dict) else {}).items():
        if k not in SETTING_DEFAULTS:
            continue
        try:
            settings[k] = clean_value(k, v)
        except ValueError:
            skipped += 1
    return dict(settings=settings, favorites=clean_favorites(data.get("favorites")),
                skipped=skipped, saved=str(data.get("saved", "")))


def merge_favorites(current, incoming):
    """导入时保留现有收藏，只补上备份里有而现在没有的；返回 (合并后列表, 新增数)。"""
    have = {(f["platform"], f["rid"]) for f in current}
    added = [f for f in incoming if (f["platform"], f["rid"]) not in have]
    return list(current) + added, len(added)


# ---------------------------------------------------------------- 头像缓存
def cache_info():
    n = size = 0
    try:
        for e in os.scandir(core.AVATAR_DIR):
            if e.is_file() and e.name.endswith(".img"):
                n += 1
                size += e.stat().st_size
    except OSError:
        pass
    return n, size


def clear_cache():
    n = size = 0
    try:
        entries = list(os.scandir(core.AVATAR_DIR))
    except OSError:
        return 0, 0
    for e in entries:
        if e.is_file() and e.name.endswith(".img"):
            try:
                s = e.stat().st_size
                os.remove(e.path)
                n += 1
                size += s
            except OSError:
                pass
    return n, size


def human_size(n):
    return "%d KB" % max(1, round(n / 1024)) if n < 1048576 else "%.1f MB" % (n / 1048576.0)


# ---------------------------------------------------------------- 单实例（再次双击图标时唤起已运行的窗口）
_TAG = os.environ.get("LIVEHELPER_INSTANCE_TAG", "")     # 仅测试用：让测试版和正在运行的正式版互不干扰
MUTEX_NAME = "Local\\LiveHelper.Instance" + _TAG
EVENT_NAME = "Local\\LiveHelper.ShowWindow" + _TAG
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wt.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
_k32.CreateEventW.restype = wt.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_k32.OpenEventW.restype = wt.HANDLE
_k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.SetEvent.argtypes = [wt.HANDLE]
_k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k32.CloseHandle.argtypes = [wt.HANDLE]
_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002


def acquire_single_instance(mutex=MUTEX_NAME):
    """返回 (是否第一个实例, 句柄)。句柄要一直持有到程序退出。"""
    h = _k32.CreateMutexW(None, False, mutex)
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS, h


def signal_existing(event=EVENT_NAME):
    """通知已在运行的那个实例“请把窗口显示出来”。"""
    h = _k32.OpenEventW(_EVENT_MODIFY_STATE, False, event)
    if h:
        _k32.SetEvent(h)
        _k32.CloseHandle(h)
        return True
    return False


class ShowWatcher:
    """后台线程等待“显示窗口”信号，收到就调用 callback（调用方负责把它投递回主线程）。"""

    def __init__(self, callback, event=EVENT_NAME):
        self.callback = callback
        self.handle = _k32.CreateEventW(None, False, False, event)
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        while not self._stop:
            if _k32.WaitForSingleObject(self.handle, 300) == 0:
                try:
                    self.callback()
                except Exception:
                    pass

    def stop(self):
        self._stop = True


# ---------------------------------------------------------------- 托盘图标（pystray；只往主线程投递，不碰界面）
class Tray:
    def __init__(self, title, icon_path, on_show, on_exit):
        self.title, self.icon_path = title, icon_path
        self.on_show, self.on_exit = on_show, on_exit
        self.icon = None

    @property
    def visible(self):
        return self.icon is not None

    def show(self):
        """显示托盘图标；库不可用或失败返回 False。"""
        if self.icon is not None:
            return True
        try:
            import pystray
            from PIL import Image
            image = Image.open(self.icon_path).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", lambda icon, item: self.on_show(), default=True),
                pystray.MenuItem("退出", lambda icon, item: self.on_exit()))
            self.icon = pystray.Icon("LiveHelper", image, self.title, menu)
            threading.Thread(target=self.icon.run, daemon=True).start()
            return True
        except Exception:
            self.icon = None
            return False

    def hide(self):
        ic, self.icon = self.icon, None
        if ic is not None:
            try:
                ic.stop()
            except Exception:
                pass
