# -*- coding: utf-8 -*-
"""直播助手 - 入口。无参数启动界面；带 --streamlink-cli 时作为隐藏的 streamlink 命令行。"""
import sys
import os


def _run_streamlink_cli():
    # 打包成 windowed exe 时没有控制台，stdout/stderr 可能为 None，先兜底
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.argv = ["streamlink"] + sys.argv[2:]
    from streamlink_cli.main import main
    sys.exit(main())


def _selftest(outfile):
    """隐藏自检：用中性关键词在三平台各找一个正在直播的房间（或读环境变量
    LIVEHELPER_SELFTEST_ROOMS=douyu:xxx,huya:yyy,bili:zzz），再测搜索、房间查询、解析流地址、弹幕、PotPlayer 检测。
    结果写入文件；只写平台、条数、是否通过，不写主播昵称和房间号。"""
    import core
    lines = []
    rooms = core.pick_live_rooms(log=lambda m: lines.append("提示: " + m))
    for p in core.PLATFORMS:
        if p not in rooms:
            lines.append("找房间 %s: 未找到正在直播的房间" % p)
    for p in rooms:
        try:
            r = core.SEARCHERS[p](core.NEUTRAL_KEYWORDS[0])
            lines.append("搜索 %s: %d 条, 通过=%s" % (p, len(r), bool(r)))
        except Exception as e:
            lines.append("搜索 %s 失败: %s" % (p, e))
    for p, rid in rooms.items():
        try:
            r = core.lookup_room(p, rid)
            lines.append("房间查询 %s: 通过=%s 在播=%s" % (p, True, r["live"]))
        except Exception as e:
            lines.append("房间查询 %s 失败: %s" % (p, e))
    for p in ("douyu", "huya"):
        if p not in rooms:
            continue
        try:
            u = core.resolve_stream_url(core.room_url(p, rooms[p]))
            lines.append("解析 %s: 通过=%s" % (p, bool(u)))
        except Exception as e:
            lines.append("解析 %s 失败: %s" % (p, e))
    # 弹幕：各连 12 秒，统计收到的条数（不记录内容）
    try:
        import danmaku, time as _t
        for p, rid in rooms.items():
            got = []
            c = danmaku.CLIENTS[p](rid, got.append)
            c.start()
            t0 = _t.time()
            while _t.time() - t0 < 12 and len(got) < 3:
                _t.sleep(0.3)
            c.stop()
            lines.append("弹幕 %s: 收到 %d 条, 通过=%s" % (p, len(got), len(got) > 0))
    except Exception as e:
        lines.append("弹幕自检失败: %s" % e)
    lines.append("PotPlayer: %s" % core.find_potplayer({}))
    ok = _selftest_update(lines)
    with open(outfile, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return ok


def _selftest_update(lines):
    """更新模块自检：离线部分决定结果（失败返回 False）；联网查询只作参考，失败不影响退出码。"""
    import updater
    from version import __version__ as ver
    P = updater.Policy()
    base = "https://github.com/%s/releases/download/v9.9.9/" % updater.UPDATE_REPO
    rel = {"tag_name": "v9.9.9", "body": "x", "assets": [
        {"name": "LiveHelper-Setup-v9.9.9.exe", "size": 10, "browser_download_url": base + "LiveHelper-Setup-v9.9.9.exe"},
        {"name": "SHA256SUMS.txt", "browser_download_url": base + "SHA256SUMS.txt"}]}
    import json as _j
    r = updater.check_latest(ver, P, lambda u: _j.dumps(rel).encode())
    checks = [
        ("版本比较", updater.is_newer("1.10.0", "1.9.0") and not updater.is_newer("1.2.0", "1.2.0")),
        ("发现新版本(离线模拟)", r["status"] == "new" and r["asset"]["name"] == "LiveHelper-Setup-v9.9.9.exe"),
        ("地址白名单", updater.url_allowed(base + "a.exe", P) and not updater.url_allowed("https://evil.example/a.exe", P)),
        ("SHA256SUMS 解析", updater.parse_sums("a" * 64 + "  f.exe", "f.exe") == "a" * 64),
        ("每日一次节流", not updater.should_auto_check({"update_last_check": 1000}, 1000 + 60)),
    ]
    ok = True
    for n, v in checks:
        lines.append("更新模块 %s: 通过=%s" % (n, bool(v)))
        ok = ok and bool(v)
    try:
        net = updater.check_latest(ver, P)
        lines.append("更新联网检查(仅参考): %s%s" % (net["status"], (" " + net["version"]) if net.get("version") else ""))
    except Exception as e:
        lines.append("更新联网检查(仅参考)失败: %s" % e)
    return ok


if len(sys.argv) > 1 and sys.argv[1] == "--streamlink-cli":
    _run_streamlink_cli()
if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
    sys.exit(0 if _selftest(sys.argv[2]) else 1)

import copy
import queue
import subprocess
import ctypes
import ctypes.wintypes
from version import __version__
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from PIL import Image, ImageDraw

import core
import danmaku
import sysset
import updater

# ---------------------------------------------------------------- 主题
# 所有颜色都是 (浅色, 深色) 元组：切换主题时只调 ctk.set_appearance_mode，控件自己按主题重绘，不销毁重建。
PCOL = {"huya": "#FF9600", "douyu": "#FF5D23", "bili": "#FB7299"}
BG = ("#F4F5F7", "#14161A")
CARD = ("#FFFFFF", "#1F2229")
CARD_HOVER = ("#F0F2F5", "#2A2E37")
CARD_SEL = ("#FFF4E8", "#31353F")
BORDER = ("#E6E8EC", "#1F2229")
FG = ("#1F2329", "#E8EAED")
FG2 = ("#5F6672", "#8A8F98")
LIVE_RED = ("#FF3B30", "#FF4D4F")
PRIMARY = ("#FF7A00", "#FF9600")
PRIMARY_HOVER = ("#E56D00", "#E08600")
ON_PRIMARY = ("#FFFFFF", "#1A1A1A")
SEL_BORDER = ("#FFB266", "#FF9600")
BTN2 = ("#EEF0F3", "#2A2E37")
BTN2_HOVER = ("#E3E6EA", "#31353F")
PILL_BG = {"huya": ("#FFF3E0", PCOL["huya"]), "douyu": ("#FFEDE6", PCOL["douyu"]), "bili": ("#FFE8F0", PCOL["bili"])}
PILL_FG = {"huya": ("#C26F00", "#1A1A1A"), "douyu": ("#E04A12", "#1A1A1A"), "bili": ("#D9457A", "#1A1A1A")}
TRACK = ("#D5D9DF", "#3A3F4A")          # 滑块轨道 / 开关底
KNOB = ("#FFFFFF", "#E8EAED")           # 开关圆钮
SCROLL = ("#C9CDD3", "#3A3F4A")         # 滚动条
SCROLL_HOVER = ("#AEB3BB", "#4C5262")
FONT = "Microsoft YaHei UI"
THEME = "light"   # 当前主题名，仅用于记录/显示；颜色本身由 customtkinter 按 appearance mode 选择


def apply_theme(name):
    global THEME
    THEME = name if name in ("light", "dark") else "light"
    ctk.set_appearance_mode(THEME)


apply_theme("light")


def F(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


# ---------------------------------------------------------------- Windows 标题栏深浅色
# customtkinter 每次切换主题/创建窗口都会把窗口 withdraw 再 deiconify 来刷新标题栏，肉眼就是"整窗闪一下"。
# 这里关掉它的做法，自己用 DwmSetWindowAttribute 设置并强制重画标题栏，窗口全程保持显示。
_TITLED = []


def set_titlebar(win):
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if ctk.get_appearance_mode() == "Dark" else 0)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
        # 不移动不改大小，只通知系统重画非客户区（标题栏）
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass


def track_titlebar(win):
    _TITLED.append(win)
    set_titlebar(win)


def retitle_all():
    for w in list(_TITLED):
        try:
            if w.winfo_exists():
                set_titlebar(w)
            else:
                _TITLED.remove(w)
        except Exception:
            pass


def center_show(win, master, third=True):
    """窗口先隐藏建好控件，算好位置再一次性显示，避免弹出时闪白/闪黑。"""
    win.update_idletasks()
    x = master.winfo_rootx() + (master.winfo_width() - win.winfo_width()) // 2
    y = master.winfo_rooty() + (master.winfo_height() - win.winfo_height()) // 3
    win.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
    track_titlebar(win)
    win.deiconify()


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def circle_image(path, size, name, color):
    """圆形头像；没有图片则用首字母色块占位。"""
    big = size * 3
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    if path:
        try:
            im = Image.open(path).convert("RGB").resize((big, big), Image.LANCZOS)
        except Exception:
            im = None
    else:
        im = None
    if im is None:
        im = Image.new("RGB", (big, big), color)
        ch = (name or "?").strip()[:1].upper() or "?"
        try:
            from PIL import ImageFont
            fnt = ImageFont.truetype("msyh.ttc", int(big * 0.5))
        except Exception:
            fnt = None
        d = ImageDraw.Draw(im)
        if fnt:
            d.text((big / 2, big / 2), ch, fill="white", font=fnt, anchor="mm")
        else:
            d.text((big / 2 - 10, big / 2 - 10), ch, fill="white")
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    out = out.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=out, dark_image=out, size=(size, size))


# ---------------------------------------------------------------- 弹窗（统一风格）
class Dialog(ctk.CTkToplevel):
    _deactivate_windows_window_header_manipulation = True

    def __init__(self, master, title, msg, yes="确定", no=None):
        super().__init__(master)
        self.withdraw()
        self.result = False
        self.title(title)
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(master)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        box = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        box.pack(padx=16, pady=16)
        ctk.CTkLabel(box, text=title, font=F(16, True), text_color=FG).pack(anchor="w", padx=22, pady=(18, 4))
        ctk.CTkLabel(box, text=msg, font=F(13), text_color=FG2, justify="left", wraplength=380).pack(
            anchor="w", padx=22, pady=(0, 16))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="e", padx=22, pady=(0, 18))
        if no:
            ctk.CTkButton(row, text=no, width=90, height=36, corner_radius=18, fg_color=BTN2, text_color=FG,
                          hover_color=BTN2_HOVER, font=F(13), command=lambda: self._done(False)).pack(side="left", padx=6)
        ctk.CTkButton(row, text=yes, width=110, height=36, corner_radius=18, fg_color=PRIMARY,
                      hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY, font=F(13, True),
                      command=lambda: self._done(True)).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", lambda: self._done(False))
        center_show(self, master)
        self.after(100, self.grab_set)

    def _done(self, v):
        self.result = v
        self.destroy()


def ask(master, title, msg, yes="确定", no="取消"):
    d = Dialog(master, title, msg, yes, no)
    master.wait_window(d)
    return d.result


def info(master, title, msg):
    d = Dialog(master, title, msg, "知道了", None)
    master.wait_window(d)


# ---------------------------------------------------------------- 卡片
class Card(ctk.CTkFrame):
    def __init__(self, parent, app, item, fav_mode=False):
        super().__init__(parent, fg_color=CARD, corner_radius=12, height=72, border_width=1, border_color=BORDER)
        self.app, self.item, self.fav_mode = app, item, fav_mode
        self.selected = False
        self.pack_propagate(False)
        col = PCOL[item["platform"]]
        self.avatar = ctk.CTkLabel(self, text="", width=48, height=48,
                                   image=circle_image(None, 48, item["name"], col))
        self.avatar.pack(side="left", padx=(12, 10), pady=12)
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(side="right", padx=10)
        self.play_btn = ctk.CTkButton(btns, text="▶", width=46, height=34, corner_radius=17, border_spacing=0, font=F(13),
                                      fg_color=col, hover_color=col, text_color=ON_PRIMARY,
                                      command=lambda: app.play_item(item))
        self.play_btn.pack(side="left", padx=3)
        self.fav_btn = ctk.CTkButton(btns, text="", width=46, height=34, corner_radius=17, border_spacing=0, font=F(15),
                                     fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG,
                                     command=self._fav_click)
        self.fav_btn.pack(side="left", padx=3)
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, pady=8)
        r1 = ctk.CTkFrame(mid, fg_color="transparent")
        r1.pack(fill="x", anchor="w")
        self.name_lbl = ctk.CTkLabel(r1, text=self._short(item["name"], 9 if fav_mode else 13), font=F(14, True), text_color=FG, anchor="w")
        self.name_lbl.pack(side="left")
        r2 = ctk.CTkFrame(mid, fg_color="transparent")
        r2.pack(fill="x", anchor="w", pady=(2, 0))
        # 平台胶囊：搜索卡放在名字右侧；窄的收藏卡放在第二行最前，避免被挤出
        self.pill = ctk.CTkLabel(r2 if fav_mode else r1, text=core.PLATFORMS[item["platform"]], font=F(10, True),
                                 text_color=PILL_FG[item["platform"]], fg_color=PILL_BG[item["platform"]], corner_radius=9,
                                 height=18, width=46)
        self.pill.pack(side="left", padx=(0, 6) if fav_mode else 8)
        self.live_lbl = ctk.CTkLabel(r2, text="", font=F(11), anchor="w")
        self.live_lbl.pack(side="left")
        self.sub_lbl = ctk.CTkLabel(r2, text="", font=F(11), text_color=FG2, anchor="w")
        self.sub_lbl.pack(side="left", padx=(8, 0))
        self.refresh()
        self._narrow = False
        if fav_mode:
            self.bind("<Configure>", self._fit, add="+")
        self._bind_all(self)
        if item.get("avatar"):
            app.load_avatar(item, self)

    def _fit(self, e):
        """收藏卡太窄（小窗口）时收起房间号和平台胶囊（头像颜色已区分平台），保证直播状态完整可见。"""
        narrow = e.width < 310
        if narrow != self._narrow:
            self._narrow = narrow
            if narrow:
                self.pill.pack_forget()
                self.sub_lbl.pack_forget()
            else:
                self.pill.pack(side="left", padx=(0, 6), before=self.live_lbl)
                self.sub_lbl.pack(side="left", padx=(8, 0))
            self.name_lbl.configure(text=self._short(self.item["name"], 6 if narrow else 9))

    @staticmethod
    def _short(s, n):
        return s if len(s) <= n else s[:n - 1] + "…"

    def refresh(self):
        it = self.item
        if it.get("live"):
            self.live_lbl.configure(text="● 直播" if self.fav_mode else "● 直播中", text_color=LIVE_RED)
        else:
            self.live_lbl.configure(text="未开播", text_color=FG2)
        bits = [it["rid"]]
        if it.get("cate"):
            bits.append(it["cate"])
        if it.get("hot"):
            bits.append("人气 " + str(it["hot"]))
        if self.fav_mode:
            bits = bits[:1]          # 收藏栏窄，只显示房间号，避免 "·" 被截断在行尾
        self.sub_lbl.configure(text=self._short("  ·  ".join(bits), 12 if self.fav_mode else 34))
        faved = self.app.is_fav(it)
        if self.fav_mode:
            self.fav_btn.configure(text="✕")
        else:
            self.fav_btn.configure(text="★" if faved else "☆", text_color=PRIMARY if faved else FG)

    def set_avatar(self, path):
        img = circle_image(path, 48, self.item["name"], PCOL[self.item["platform"]])
        self.avatar.configure(image=img)

    def _fav_click(self):
        if self.fav_mode:
            self.app.remove_fav(self.item)
        else:
            self.app.toggle_fav(self.item)

    def _bind_all(self, w):
        if isinstance(w, ctk.CTkButton):
            return
        w.bind("<Enter>", lambda e: self._hover(True), add="+")
        w.bind("<Leave>", lambda e: self._hover(False), add="+")
        w.bind("<Button-1>", lambda e: self.app.select_card(self), add="+")
        w.bind("<Double-Button-1>", lambda e: self.app.play_item(self.item), add="+")
        for c in w.winfo_children():
            self._bind_all(c)

    def _hover(self, on):
        if on:
            self.configure(fg_color=CARD_HOVER if not self.selected else CARD_SEL)
        else:
            # 指针仍在卡片内（进入了子控件）则保持高亮
            x, y = self.winfo_pointerxy()
            w = self.winfo_containing(x, y)
            while w is not None and w is not self:
                w = getattr(w, "master", None)
            if w is self:
                return
            self.configure(fg_color=CARD_SEL if self.selected else CARD)

    def set_selected(self, v):
        self.selected = v
        self.configure(fg_color=CARD_SEL if v else CARD, border_width=2 if v else 1,
                       border_color=SEL_BORDER if v else BORDER)


# ---------------------------------------------------------------- 更新结果文字
def updater_text(r):
    st = r.get("status")
    if st == "new":
        tip = "" if r.get("asset") else "（无法自动更新：%s）" % r.get("asset_error")
        return "发现新版本 v%s，主窗口顶部有提示%s" % (r["version"], tip)
    if st == "latest":
        return "已是最新版本（v%s）" % __version__
    return "检查失败：%s" % r.get("reason", "未知原因")


# ---------------------------------------------------------------- 选择弹窗（多个按钮 + 可选“记住我的选择”）
class Choice(ctk.CTkToplevel):
    _deactivate_windows_window_header_manipulation = True

    def __init__(self, master, title, msg, options, cancel, remember_text):
        super().__init__(master)
        self.withdraw()
        self.value, self.remember = None, False
        self.has_remember = bool(remember_text)
        self.title(title)
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(master)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        box = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        box.pack(padx=16, pady=16)
        ctk.CTkLabel(box, text=title, font=F(16, True), text_color=FG).pack(anchor="w", padx=22, pady=(18, 4))
        ctk.CTkLabel(box, text=msg, font=F(13), text_color=FG2, justify="left", wraplength=380).pack(
            anchor="w", padx=22, pady=(0, 14))
        if remember_text:
            self.rem = ctk.CTkCheckBox(box, text=remember_text, font=F(12), text_color=FG2, checkbox_width=20,
                                       checkbox_height=20, corner_radius=6, border_width=2, fg_color=PRIMARY,
                                       hover_color=PRIMARY_HOVER, border_color=TRACK, checkmark_color=ON_PRIMARY)
            self.rem.pack(anchor="w", padx=22, pady=(0, 14))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="e", padx=22, pady=(0, 18))
        ctk.CTkButton(row, text=cancel, width=80, height=36, corner_radius=18, fg_color=BTN2, text_color=FG,
                      hover_color=BTN2_HOVER, font=F(13), command=lambda: self._done(None)).pack(side="left", padx=4)
        for i, (text, val) in enumerate(options):
            first = i == len(options) - 1      # 最右边的按钮是主按钮
            ctk.CTkButton(row, text=text, width=110, height=36, corner_radius=18,
                          fg_color=PRIMARY if first else BTN2, hover_color=PRIMARY_HOVER if first else BTN2_HOVER,
                          text_color=ON_PRIMARY if first else FG, font=F(13, first),
                          command=lambda v=val: self._done(v)).pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", lambda: self._done(None))
        center_show(self, master)
        self.after(100, self.grab_set)

    def _done(self, v):
        self.value = v
        self.remember = bool(self.rem.get()) if self.has_remember else False
        self.destroy()


def choose(master, title, msg, options, cancel="取消", remember_text=None):
    """多选一弹窗；返回 (所选的值，点了取消/关闭则为 None；是否勾选了“记住”)。options: [(按钮文字, 值), ...]"""
    d = Choice(master, title, msg, options, cancel, remember_text)
    master.wait_window(d)
    return d.value, d.remember


# ---------------------------------------------------------------- 设置
SWITCH_STYLE = dict(fg_color=TRACK, button_color=KNOB, button_hover_color=KNOB, progress_color=PRIMARY)


def _menu_style():
    return dict(height=34, corner_radius=17, font=F(13), dropdown_font=F(13), fg_color=BTN2, text_color=FG,
                button_color=BTN2_HOVER, button_hover_color=BTN2_HOVER, dropdown_fg_color=CARD,
                dropdown_text_color=FG, dropdown_hover_color=CARD_HOVER)


def _short_path(p, n=38):
    """太长的路径保留盘符和最后两级目录：C:\\…\\PotPlayer\\PotPlayerMini64.exe"""
    if len(p) <= n:
        return p
    parts = p.replace("/", "\\").split("\\")
    short = parts[0] + "\\…\\" + "\\".join(parts[-2:]) if len(parts) > 3 else p
    return short if len(short) <= n + 6 else "…" + p[-(n - 1):]


class SettingsWindow(ctk.CTkToplevel):
    """左边分类、右边内容；每个开关/选项一改就立即生效并保存，没有“确定/取消”。"""
    _deactivate_windows_window_header_manipulation = True
    PAGES = ("通用", "播放", "弹幕", "外观", "数据", "关于")
    BUILDERS = {"通用": "_build_general", "播放": "_build_play", "弹幕": "_build_danmaku",
                "外观": "_build_look", "数据": "_build_data", "关于": "_build_about"}
    W, H = 540, 520

    def __init__(self, app, page="通用"):
        super().__init__(app)
        self.withdraw()
        self.app, self.cfg = app, app.cfg
        self.current = None
        self.pages, self.navs = {}, {}
        self._reset_refs()
        self.title("设置")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(app)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.pack(padx=16, pady=16)
        nav = ctk.CTkFrame(shell, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER,
                           width=130, height=self.H)
        nav.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        nav.pack_propagate(False)
        ctk.CTkLabel(nav, text="设置", font=F(16, True), text_color=FG, anchor="w").pack(fill="x", padx=18, pady=(18, 8))
        for name in self.PAGES:
            b = ctk.CTkButton(nav, text=name, anchor="w", height=36, corner_radius=10, font=F(13),
                              fg_color="transparent", hover_color=BTN2, text_color=FG,
                              command=lambda n=name: self.show_page(n))
            b.pack(fill="x", padx=10, pady=2)
            self.navs[name] = b
        ctk.CTkButton(nav, text="完成", height=34, corner_radius=17, fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
                      text_color=ON_PRIMARY, font=F(13, True), command=self.destroy).pack(side="bottom", fill="x", padx=14, pady=16)
        self.body = ctk.CTkFrame(shell, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER,
                                 width=self.W, height=self.H)
        self.body.grid(row=0, column=1)
        self.body.pack_propagate(False)
        self.show_page(page)
        self.bind("<Escape>", lambda e: self.destroy())
        center_show(self, app)

    def _reset_refs(self):
        self.player_lbl = self.upd_lbl = self.upd_btn = self.cache_lbl = self.theme_sw = None
        self.autostart_sw = self.auto_desc = self.plat_desc = None
        self.plat_cb = {}
        self.switches, self.menus = {}, {}       # 按设置项名字记下各开关/下拉框，方便测试和批量同步

    # ---- 页面切换 / 重建
    def show_page(self, name):
        if name not in self.PAGES:
            name = self.PAGES[0]
        if self.current in self.pages:
            self.pages[self.current].pack_forget()
        if name not in self.pages:
            p = ctk.CTkFrame(self.body, fg_color="transparent")
            ctk.CTkLabel(p, text=name, font=F(16, True), text_color=FG, anchor="w").pack(fill="x", padx=20, pady=(18, 4))
            getattr(self, self.BUILDERS[name])(p)
            self.pages[name] = p
        self.pages[name].pack(fill="both", expand=True)
        self.current = name
        for n, b in self.navs.items():
            on = n == name
            b.configure(fg_color=CARD_SEL if on else "transparent", text_color=PRIMARY if on else FG, font=F(13, on))

    def rebuild(self):
        """设置被批量改动（导入备份 / 恢复默认）后，丢掉已建好的页面，按新值重新生成。"""
        cur = self.current
        for p in self.pages.values():
            p.destroy()
        self.pages.clear()
        self._reset_refs()
        self.current = None
        self.show_page(cur or self.PAGES[0])

    # ---- 小零件
    def _row(self, p, title, desc=None, wrap=290):
        """一行设置：左边标题+说明，右边放控件。返回 (右侧容器, 说明标签)。"""
        n = getattr(p, "_nrows", 0)
        if n:
            ctk.CTkFrame(p, height=1, fg_color=BTN2, corner_radius=0).pack(fill="x", padx=20)
        p._nrows = n + 1
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=20)
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right", padx=(10, 0))
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, pady=9)
        ctk.CTkLabel(left, text=title, font=F(13), text_color=FG, anchor="w").pack(fill="x")
        lbl = None
        if desc is not None:
            lbl = ctk.CTkLabel(left, text=desc, font=F(11), text_color=FG2, anchor="w", justify="left", wraplength=wrap)
            lbl.pack(fill="x", pady=(2, 0))
        return right, lbl

    def _btn(self, parent, text, cmd, width=88):
        return ctk.CTkButton(parent, text=text, width=width, height=30, corner_radius=15, font=F(12),
                             fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG, command=cmd)

    def _set(self, key, val):
        self.cfg[key] = val
        core.save_config(self.cfg)

    def _switch(self, right, key, command=None):
        sw = ctk.CTkSwitch(right, text="", width=46, command=lambda: self._on_switch(key, sw, command), **SWITCH_STYLE)
        if self.cfg.get(key, sysset.SETTING_DEFAULTS[key]):
            sw.select()
        sw.pack()
        self.switches[key] = sw
        return sw

    def _on_switch(self, key, sw, command):
        self._set(key, bool(sw.get()))
        if command:
            command()

    def _menu(self, right, key, choices, command=None, width=150):
        by_label = dict(choices)
        by_value = {v: l for l, v in choices}
        m = ctk.CTkOptionMenu(right, values=[l for l, _ in choices], width=width,
                              command=lambda l: self._on_menu(key, by_label[l], command), **_menu_style())
        m.set(by_value.get(self.cfg.get(key, sysset.SETTING_DEFAULTS[key]), choices[0][0]))
        m.pack()
        self.menus[key] = m
        return m

    def _on_menu(self, key, val, command):
        self._set(key, val)
        if command:
            command(val)

    # ---- 通用
    def _build_general(self, p):
        right, self.auto_desc = self._row(p, "开机自启", "登录 Windows 后自动运行直播助手")
        self.autostart_sw = ctk.CTkSwitch(right, text="", width=46, command=self._autostart_toggle, **SWITCH_STYLE)
        self.autostart_sw.pack()
        self._autostart_sync()
        right, _ = self._row(p, "开机自启后只在托盘待命", "不弹出主窗口；点托盘图标或再次打开程序即可显示")
        self._switch(right, "start_minimized")
        right, _ = self._row(p, "点窗口右上角 ✕ 时")
        self._menu(right, "close_action", sysset.CLOSE_ACTIONS)
        right, _ = self._row(p, "记住窗口大小和位置")
        self._switch(right, "remember_window")
        right, self.plat_desc = self._row(p, "默认搜索的平台", "搜索栏下方的平台按钮按这里的选择开关")
        for k, name in core.PLATFORMS.items():
            cb = ctk.CTkCheckBox(right, text=name, width=20, font=F(12), text_color=FG, checkbox_width=20,
                                 checkbox_height=20, corner_radius=6, border_width=2, fg_color=PRIMARY,
                                 hover_color=PRIMARY_HOVER, border_color=TRACK, checkmark_color=ON_PRIMARY,
                                 command=lambda k=k: self._platform_toggle(k))
            if k in self.cfg.get("default_platforms", list(core.PLATFORMS)):
                cb.select()
            cb.pack(side="left", padx=4)
            self.plat_cb[k] = cb
        right, _ = self._row(p, "启动时刷新收藏状态")
        self._switch(right, "fav_refresh_on_start")
        right, _ = self._row(p, "自动刷新收藏状态", "后台定时查看收藏的主播是否开播")
        self._menu(right, "fav_refresh_min", sysset.REFRESH_CHOICES, width=130)

    def _autostart_sync(self):
        sw, d = self.autostart_sw, self.auto_desc
        base = "登录 Windows 后自动运行直播助手"
        if not sysset.autostart_available():
            sw.deselect()
            sw.configure(state="disabled")
            d.configure(text=base + "\n（仅安装版可用，当前是源码运行）", text_color=FG2)
            return
        st = sysset.autostart_state()
        sw.configure(state="normal")
        sw.select() if st == "on" else sw.deselect()
        if st == "blocked":
            d.configure(text=base + "\n已被系统禁用：到“任务管理器 → 启动应用”里重新启用，或把这个开关打开一次", text_color=LIVE_RED)
        else:
            d.configure(text=base, text_color=FG2)

    def _autostart_toggle(self):
        want = bool(self.autostart_sw.get())
        try:
            sysset.autostart_set(want)
        except OSError as e:
            self._autostart_sync()
            info(self, "设置失败", "无法修改开机自启：%s" % e)
            return
        self._autostart_sync()

    def _platform_toggle(self, k):
        chosen = [x for x, cb in self.plat_cb.items() if cb.get()]
        if not chosen:
            self.plat_cb[k].select()
            self.plat_desc.configure(text="至少要保留一个平台", text_color=LIVE_RED)
            return
        self.plat_desc.configure(text="搜索栏下方的平台按钮按这里的选择开关", text_color=FG2)
        self._set("default_platforms", chosen)
        self.app.set_platforms(chosen)

    # ---- 播放
    def _build_play(self, p):
        right, self.player_lbl = self._row(p, "PotPlayer", "", wrap=230)
        self._btn(right, "重新检测", self.app.check_potplayer, 80).pack(side="left", padx=(0, 6))
        self._btn(right, "重选路径", self.app.pick_potplayer, 80).pack(side="left")
        self.refresh_player()
        right, _ = self._row(p, "断流自动续播", "斗鱼 / 虎牙流到期断开时自动重连")
        self._switch(right, "auto_resume")
        right, _ = self._row(p, "睡眠定时", "开始播放后到点自动停止；改动对下一次播放生效")
        self._menu(right, "sleep_minutes", sysset.SLEEP_CHOICES, width=130)

    def refresh_player(self):
        if self.player_lbl is None:
            return
        pp = self.app.potplayer
        if pp:
            self.player_lbl.configure(text=_short_path(pp, 34), text_color=FG2)
        else:
            self.player_lbl.configure(text="未找到。可以重新检测，或手动选择 PotPlayerMini64.exe", text_color=LIVE_RED)

    # ---- 弹幕
    def _build_danmaku(self, p):
        dm, cfg = self.app.dm, self.cfg

        def slider(label, key, lo, hi, steps, fmt):
            right, _ = self._row(p, label)
            lb = ctk.CTkLabel(right, text=fmt(cfg[key]), font=F(13), text_color=FG, width=56)
            lb.pack(side="right")

            def on(v, key=key, lb=lb):
                cfg[key] = round(float(v), 2) if key == "dm_alpha" else int(round(v))
                lb.configure(text=fmt(cfg[key]))
                dm.apply_settings()
            sl = ctk.CTkSlider(right, from_=lo, to=hi, number_of_steps=steps, width=170, fg_color=TRACK,
                               progress_color=PRIMARY, button_color=PRIMARY, button_hover_color=PRIMARY_HOVER, command=on)
            sl.set(cfg[key])
            sl.pack(side="right", padx=(0, 6))
        slider("字号", "dm_font", 16, 56, 40, lambda v: "%d" % v)
        slider("透明度", "dm_alpha", 0.3, 1.0, 14, lambda v: "%d%%" % round(float(v) * 100))
        slider("飘过时间", "dm_speed", 4, 16, 12, lambda v: "%d 秒" % v)
        slider("同屏最多", "dm_max", 20, 150, 13, lambda v: "%d 条" % v)
        right, _ = self._row(p, "显示区域")
        self._menu(right, "dm_area", [(a, a) for a in danmaku.AREAS], lambda v: dm.apply_settings(), width=170)
        right, _ = self._row(p, "渲染方式")
        self._menu(right, "dm_renderer", [(r, r) for r in danmaku.RENDERERS], lambda v: dm.set_renderer(v), width=170)
        hk = "快捷键 Ctrl+Alt+D 随时开关弹幕。" if self.app.hotkey_ok else "快捷键 Ctrl+Alt+D 注册失败（被别的软件占用），请用界面上的开关。"
        tip = (hk + "\n弹幕是盖在 PotPlayer 上的透明窗口：窗口化和普通全屏可见；"
               "若 PotPlayer 设为“独占全屏”（Exclusive），弹幕可能被挡住看不到。\n弹幕显示异常（重影、不显示）时，把“渲染方式”切到“兼容（旧）”。")
        ctk.CTkLabel(p, text=tip, font=F(11), text_color=FG2, justify="left", wraplength=470, anchor="w").pack(
            fill="x", padx=20, pady=(10, 6))

    # ---- 外观
    def _build_look(self, p):
        right, _ = self._row(p, "深色主题", "浅色 / 深色界面，立即生效；主窗口右上角也有同一个开关")
        self.theme_sw = ctk.CTkSwitch(right, text="", width=46, command=self._theme_toggle, **SWITCH_STYLE)
        if THEME == "dark":
            self.theme_sw.select()
        self.theme_sw.pack()

    def _theme_toggle(self):
        (self.app.theme_sw.select if self.theme_sw.get() else self.app.theme_sw.deselect)()
        self.app.switch_theme()

    def sync_theme(self):
        if self.theme_sw is not None:
            (self.theme_sw.select if THEME == "dark" else self.theme_sw.deselect)()

    # ---- 数据
    def _build_data(self, p):
        right, _ = self._row(p, "数据文件夹", _short_path(core.APPDIR, 38) + "\n存放收藏、设置和头像缓存")
        self._btn(right, "打开", self._open_data_dir, 70).pack()
        right, self.cache_lbl = self._row(p, "头像缓存", "")
        self._btn(right, "清理", self._clear_cache, 70).pack()
        self._cache_refresh()
        right, _ = self._row(p, "备份与恢复", "把收藏和设置存成一个文件，换电脑时导入；导入时保留现有收藏，只补上缺的")
        self._btn(right, "导出…", self._export, 70).pack(side="left", padx=(0, 6))
        self._btn(right, "导入…", self._import, 70).pack(side="left")
        right, _ = self._row(p, "恢复默认设置", "只重置设置项；收藏和 PotPlayer 路径不受影响")
        self._btn(right, "恢复默认…", self._reset, 90).pack()

    def _open_data_dir(self):
        try:
            os.makedirs(core.APPDIR, exist_ok=True)
            os.startfile(core.APPDIR)
        except OSError as e:
            info(self, "打不开", str(e))

    def _cache_refresh(self):
        n, size = sysset.cache_info()
        self.cache_lbl.configure(text="已缓存 %d 张头像，占用 %s；清理后会按需重新下载" % (n, sysset.human_size(size)) if n
                                 else "目前没有缓存")

    def _clear_cache(self):
        n, size = sysset.clear_cache()
        self.cache_lbl.configure(text="已清理 %d 张头像，释放 %s" % (n, sysset.human_size(size)) if n else "目前没有缓存")

    def _export(self):
        name = "直播助手备份-%s.json" % time.strftime("%Y%m%d")
        path = filedialog.asksaveasfilename(parent=self, title="导出备份", defaultextension=".json", initialfile=name,
                                            filetypes=[("直播助手备份", "*.json")])
        if not path:
            return
        try:
            sysset.write_backup(path, sysset.make_backup(self.cfg, self.app.favs, __version__))
        except OSError as e:
            info(self, "导出失败", str(e))
            return
        info(self, "已导出", "已保存到：\n%s" % path)

    def _import(self):
        path = filedialog.askopenfilename(parent=self, title="导入备份",
                                          filetypes=[("直播助手备份", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            bk = sysset.read_backup(path)
        except sysset.BackupError as e:
            info(self, "无法导入", str(e))
            return
        msg = ("备份时间：%s\n包含 %d 个收藏、%d 项设置。\n\n导入会用备份里的设置覆盖当前设置；现有收藏保留，只补上缺的。继续？"
               % (bk["saved"] or "未知", len(bk["favorites"]), len(bk["settings"])))
        if not ask(self, "导入备份", msg, "导入", "取消"):
            return
        added = self.app.apply_backup(bk)
        self.rebuild()
        extra = "（有 %d 项设置的值无效，已跳过）" % bk["skipped"] if bk["skipped"] else ""
        info(self, "导入完成", "新增 %d 个收藏，导入 %d 项设置。%s" % (added, len(bk["settings"]), extra))

    def _reset(self):
        if not ask(self, "恢复默认设置", "把所有设置改回默认值（包括关闭开机自启）。\n收藏和 PotPlayer 路径不受影响。继续？",
                   "恢复默认", "取消"):
            return
        self.app.reset_settings()
        self.rebuild()

    # ---- 关于与更新
    def _build_about(self, p):
        right, self.upd_lbl = self._row(p, "软件更新", "当前版本 v%s" % __version__, wrap=270)
        self.upd_btn = self._btn(right, "检查更新", self._upd_check, 90)
        self.upd_btn.pack()
        right, _ = self._row(p, "启动时检查更新", "每天最多检查一次；有新版本时主窗口顶部会提示")
        self._switch(right, "update_check")
        right, _ = self._row(p, "项目主页", "github.com/" + updater.UPDATE_REPO)
        self._btn(right, "打开", lambda: webbrowser.open("https://github.com/" + updater.UPDATE_REPO), 70).pack()
        right, _ = self._row(p, "开源许可", "AGPL-3.0 开源；第三方组件的许可见清单")
        self._btn(right, "查看清单", self._open_notices, 90).pack()

    def _upd_check(self):
        """手动检查：不受每天一次限制；结果文字显示在这里，发现新版本时主窗口顶部出现横幅（不弹窗）。"""
        self.upd_btn.configure(state="disabled")
        self.upd_lbl.configure(text="正在检查…")

        def done(r):
            if not self.winfo_exists() or self.upd_btn is None:
                return
            self.upd_btn.configure(state="normal")
            self.upd_lbl.configure(text=updater_text(r))
        self.app.check_update(True, done)

    def _open_notices(self):
        path = os.path.join(sysset.app_dir(), "THIRD_PARTY_NOTICES.md")
        if not os.path.isfile(path):
            info(self, "找不到清单", "没找到 THIRD_PARTY_NOTICES.md；可以在项目主页的仓库里查看。")
            return
        subprocess.Popen(["notepad.exe", path])


# ---------------------------------------------------------------- 主窗口
class App(ctk.CTk):
    _deactivate_windows_window_header_manipulation = True

    def __init__(self):
        apply_theme(core.load_config().get("theme", "light"))
        super().__init__(fg_color=BG)
        self.withdraw()          # 先隐藏建好界面，最后一次性显示（含深/浅标题栏），启动不闪
        self.title("直播助手 v%s" % __version__)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        self.cfg = core.load_config()
        for k, v in sysset.SETTING_DEFAULTS.items():       # 新增的设置项补上默认值；坏值（手改配置文件）回到默认
            try:
                self.cfg[k] = sysset.clean_value(k, self.cfg[k]) if k in self.cfg else copy.deepcopy(v)
            except ValueError:
                self.cfg[k] = copy.deepcopy(v)
        self.start_hidden = "--autostart" in sys.argv and bool(self.cfg["start_minimized"])
        w, h = 960, 640
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(self._saved_geometry() or "%dx%d+%d+%d" % (w, h, (sw - w) // 2, max((sh - h) // 2 - 20, 0)))
        self.minsize(760, 520)
        self.favs = core.load_favorites()
        self.results = []
        self.cards = []
        self.fav_cards = []
        self.selected_card = None
        self.proc = None
        self.resumer = None      # 自动续播判断（core.AutoResumer）
        self.play_ctx = None     # 当前播放：主播/地址/画质，续播时复用
        self._geom = None        # 最近一次记录的 PotPlayer 窗口位置，续播后摆回去
        self.potplayer = None
        self.tray = None         # 托盘图标（sysset.Tray），关到托盘/自启待命时才创建
        self.watcher = None      # 再次双击图标时唤起本窗口的监听（只在 __main__ 里启用）
        self._settings = None    # 打开着的设置窗口
        self._sleep_job = None   # 睡眠定时的 after 句柄
        self._fav_busy = False   # 正在刷新收藏状态
        self._fav_last = time.time()
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.pstate = {k: k in self.cfg["default_platforms"] for k in core.PLATFORMS}
        self.pbtn = {}
        self._build()
        # 弹幕：悬浮层 + 全局快捷键 Ctrl+Alt+D（热键线程里只投递到主线程，不直接碰界面）
        self.dm = danmaku.DanmakuManager(self, self.cfg, lambda: core.save_config(self.cfg), self._dm_status)
        self.hotkey_ok = self.dm.start_hotkey(lambda: self.post(self.toggle_danmaku))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._pump)
        self.after(300, lambda: self.check_potplayer(prompt=not self.start_hidden))   # 开机自启待命时不弹安装询问
        if self.cfg["fav_refresh_on_start"]:
            self.after(600, self.refresh_fav_status)
        self.after(30000, self._fav_tick)
        updater.LOG_PATH = os.path.join(core.APPDIR, "update.log")
        self.after(4000, self.auto_check_update)       # 启动几秒后后台检查，不阻塞界面
        self.show_hint(self.res_box, "输入主播名字回车搜索，或粘贴房间链接/房间号")
        self.update_idletasks()
        track_titlebar(self)
        if self.start_hidden:
            if not self.tray_show():
                self.iconify()      # 没有托盘可用就最小化到任务栏，别让用户找不到窗口
        else:
            self.deiconify()

    def _saved_geometry(self):
        """上次关闭时的窗口大小位置；没记录/关闭了记忆/已经跑出屏幕（换了显示器）则返回 None，用居中。"""
        if not self.cfg.get("remember_window"):
            return None
        try:
            scale = self._get_window_scaling()
        except Exception:
            scale = 1.0
        g = sysset.fit_geom(sysset.parse_geom(self.cfg.get("win_geom")), scale, sysset.virtual_screen())
        return sysset.format_geom(*g) if g else None

    def _remember_geometry(self):
        if self.cfg.get("remember_window") and self.state() == "normal":   # 最大化/最小化/隐藏时不记
            self.cfg["win_geom"] = self.geometry()
            core.save_config(self.cfg)

    # ------------------------------------------------------------ 界面
    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(18, 8))
        self._top = top
        self._build_update_banner()
        bar = ctk.CTkFrame(top, fg_color=CARD, corner_radius=26, height=52, border_width=1, border_color=BORDER)
        self.bar = bar
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="🔍", font=F(16), text_color=FG2, width=24).pack(side="left", padx=(18, 0))
        self.kw = ctk.CTkEntry(bar, placeholder_text="搜索主播名字 / 房间号 / 房间链接", height=40,
                               border_width=0, fg_color=CARD, text_color=FG, font=F(15),
                               placeholder_text_color=FG2)
        self.kw.pack(side="left", fill="x", expand=True, padx=8)
        self.kw.bind("<Return>", lambda e: self.do_search())
        self.kw.bind("<FocusIn>", lambda e: bar.configure(border_color=PRIMARY, border_width=2), add="+")
        self.kw.bind("<FocusOut>", lambda e: bar.configure(border_color=BORDER, border_width=1), add="+")
        self.btn_search = ctk.CTkButton(bar, text="搜索", width=84, height=38, corner_radius=19, font=F(14, True),
                                        fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY,
                                        command=self.do_search)
        self.btn_search.pack(side="right", padx=7)

        pills = ctk.CTkFrame(top, fg_color="transparent")
        pills.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(pills, text="平台", font=F(12), text_color=FG2).pack(side="left", padx=(4, 8))
        for k, name in core.PLATFORMS.items():
            b = ctk.CTkButton(pills, text=name, width=64, height=28, corner_radius=14, font=F(12, True),
                              command=lambda k=k: self.toggle_platform(k))
            b.pack(side="left", padx=4)
            self.pbtn[k] = b
            self._style_pill(k)
        self.theme_sw = ctk.CTkSwitch(pills, text="深色", font=F(12), text_color=FG2, width=70,
                                      fg_color=TRACK, button_color=KNOB, button_hover_color=KNOB,
                                      progress_color=PRIMARY, command=self.switch_theme)
        if THEME == "dark":
            self.theme_sw.select()
        self.theme_sw.pack(side="right", padx=(0, 4))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(4, 0))
        body.grid_columnconfigure(0, weight=3, uniform="c")
        body.grid_columnconfigure(1, weight=2, uniform="c")
        body.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.res_title = ctk.CTkLabel(left, text="搜索结果", font=F(14, True), text_color=FG, anchor="w")
        self.res_title.pack(fill="x", pady=(0, 6))
        self.res_box = ctk.CTkScrollableFrame(left, fg_color="transparent", corner_radius=0, scrollbar_button_color=SCROLL,
                                              scrollbar_button_hover_color=SCROLL_HOVER)
        self.res_box.pack(fill="both", expand=True)
        hd = ctk.CTkFrame(right, fg_color="transparent")
        hd.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(hd, text="我的收藏", font=F(14, True), text_color=FG).pack(side="left")
        ctk.CTkButton(hd, text="刷新状态", width=70, height=24, corner_radius=12, font=F(11), fg_color=BTN2,
                      hover_color=BTN2_HOVER, text_color=FG2, command=self.refresh_fav_status).pack(side="right")
        self.fav_box = ctk.CTkScrollableFrame(right, fg_color="transparent", corner_radius=0, scrollbar_button_color=SCROLL,
                                              scrollbar_button_hover_color=SCROLL_HOVER)
        self.fav_box.pack(fill="both", expand=True)
        self.rebuild_favs()

        pb = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=76, border_width=0)
        pb.pack(fill="x", side="bottom", pady=(10, 0))
        pb.pack_propagate(False)
        ctk.CTkButton(pb, text="⚙ 设置", width=76, height=30, corner_radius=15, font=F(12), fg_color=BTN2,
                      hover_color=BTN2_HOVER, text_color=FG2, command=self.open_settings).pack(side="left", padx=(20, 4))
        ctk.CTkLabel(pb, text="画质", font=F(12), text_color=FG2).pack(side="left", padx=(12, 6))
        self.quality = ctk.CTkOptionMenu(pb, values=core.QUALITIES, width=146, height=34, corner_radius=17,
                                         font=F(13), dropdown_font=F(13), fg_color=BTN2, text_color=FG, button_color=BTN2_HOVER, button_hover_color=BTN2_HOVER,
                                         dropdown_fg_color=CARD, dropdown_text_color=FG, dropdown_hover_color=CARD_HOVER)
        q0 = self.cfg.get("quality")
        self.quality.set(core.DEFAULT_QUALITY)
        self.quality.pack(side="left")
        self.btn_play = ctk.CTkButton(pb, text="▶  播放", width=120, height=44, corner_radius=22, font=F(16, True),
                                      fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY,
                                      command=self.play_selected)
        self.btn_play.pack(side="left", padx=14)
        self.btn_stop = ctk.CTkButton(pb, text="停止", width=64, height=34, corner_radius=17, font=F(13),
                                      fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG, state="disabled",
                                      command=self.stop_play)
        self.btn_stop.pack(side="left")
        self.dm_sw = ctk.CTkSwitch(pb, text="弹幕", font=F(13), text_color=FG, width=64, fg_color=TRACK,
                                   button_color=KNOB, button_hover_color=KNOB, progress_color=PRIMARY,
                                   command=self.on_danmaku_switch)
        if self.cfg.get("danmaku_on"):
            self.dm_sw.select()
        self.dm_sw.pack(side="left", padx=(14, 0))
        self.status = ctk.CTkLabel(pb, text="就绪", font=F(12), text_color=FG2, anchor="w", width=10)
        self.status.pack(side="left", fill="x", expand=True, padx=(12, 20))

    # ------------------------------------------------------------ 更新横幅（非模态，绝不弹窗）
    def _build_update_banner(self):
        self.upd_banner = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1, border_color=PRIMARY)
        row = ctk.CTkFrame(self.upd_banner, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(8, 8))
        self.upd_text = ctk.CTkLabel(row, text="", font=F(12, True), text_color=FG, anchor="w", justify="left")
        self.upd_text.pack(side="left", padx=(2, 8))
        self.upd_close = ctk.CTkButton(row, text="✕", width=26, height=26, corner_radius=13, font=F(12), fg_color=BTN2,
                                       hover_color=BTN2_HOVER, text_color=FG2, command=self.hide_update_banner)
        self.upd_close.pack(side="right")
        self.upd_btn_skip = ctk.CTkButton(row, text="跳过此版本", width=82, height=26, corner_radius=13, font=F(11),
                                          fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG2, command=self.skip_update)
        self.upd_btn_skip.pack(side="right", padx=(0, 6))
        self.upd_btn_go = ctk.CTkButton(row, text="立即更新", width=76, height=26, corner_radius=13, font=F(11, True),
                                        fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY,
                                        command=self.start_update)
        self.upd_btn_go.pack(side="right", padx=(0, 6))
        self.upd_btn_notes = ctk.CTkButton(row, text="更新说明", width=70, height=26, corner_radius=13, font=F(11),
                                           fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG2, command=self.toggle_update_notes)
        self.upd_btn_notes.pack(side="right", padx=(0, 6))
        self.upd_notes = ctk.CTkLabel(self.upd_banner, text="", font=F(12), text_color=FG2, anchor="w", justify="left",
                                      wraplength=840)
        self.upd_result = None
        self.upd_busy = False
        self.upd_notes_open = False
        self.update_policy = updater.Policy()          # 测试时可替换成指向本地假服务器的策略
        self.update_confirm = lambda title, msg: ask(self, title, msg, "下载并更新", "取消")
        self.update_launch = updater.launch_installer  # 测试时可替换，避免真的运行
        self.update_quit = lambda: self.quit_app()      # 更新必须真退出，不能被“关到托盘”拦住

    def show_update_banner(self, r):
        self.upd_result = r
        self.upd_busy = False
        self.upd_text.configure(text="发现新版本 v%s" % r["version"], text_color=FG)
        self.upd_btn_go.configure(state="normal" if r.get("asset") else "disabled", text="立即更新")
        for b in (self.upd_btn_skip, self.upd_btn_notes):
            b.configure(state="normal")
        self._set_notes(False)
        if not self.upd_banner.winfo_ismapped():
            self.upd_banner.pack(fill="x", padx=20, pady=(12, 0), before=self._top)

    def hide_update_banner(self):
        if self.upd_busy:
            return
        self.upd_banner.pack_forget()

    def _set_notes(self, open_):
        self.upd_notes_open = open_
        if open_ and self.upd_result:
            self.upd_notes.configure(text=updater.notes_preview(self.upd_result.get("notes")))
            self.upd_notes.pack(fill="x", padx=14, pady=(0, 10))
        else:
            self.upd_notes.pack_forget()

    def toggle_update_notes(self):
        self._set_notes(not self.upd_notes_open)

    def skip_update(self):
        if self.upd_result and not self.upd_busy:
            updater.skip_version(self.cfg, self.upd_result["version"])
            core.save_config(self.cfg)
            self.upd_banner.pack_forget()

    def check_update(self, manual, cb=None):
        """后台线程检查；结果回到主线程。手动检查忽略“已跳过”并显示结果；自动检查失败只写日志。"""
        if not manual:
            updater.mark_checked(self.cfg)
            core.save_config(self.cfg)

        def work():
            r = updater.check_latest(policy=self.update_policy)

            def done():
                try:
                    if r["status"] == "new" and (manual or updater.should_notify(r, self.cfg)):
                        self.show_update_banner(r)
                    if cb:
                        cb(r)
                except Exception as e:
                    updater._log("显示更新结果出错: %s" % e)
            self.post(done)
        threading.Thread(target=work, daemon=True).start()

    def auto_check_update(self):
        if updater.should_auto_check(self.cfg):
            self.check_update(False)

    def start_update(self):
        r = self.upd_result
        if self.upd_busy or not r or not r.get("asset"):
            return
        a = r["asset"]
        size = "约 %.1f MB" % (a["size"] / 1048576.0) if a.get("size") else "大小未知"
        msg = ("文件：%s（%s）\n来源：%s\n\n将下载并校验（SHA256），校验通过后运行安装程序，当前程序会关闭。"
               "安装包未做代码签名，Windows 可能提示未知发布者；校验值来自同一个发布页，只能防下载损坏。"
               % (a["name"], size, a["url"]))
        if not self.update_confirm("立即更新到 v%s？" % r["version"], msg):
            return
        self.upd_busy = True
        for b in (self.upd_btn_go, self.upd_btn_skip, self.upd_btn_notes):
            b.configure(state="disabled")
        self.upd_text.configure(text="正在下载 v%s … 0%%" % r["version"], text_color=FG)

        def prog(got, total):
            pct = "%d%%" % (got * 100 // total) if total else "%.1f MB" % (got / 1048576.0)
            self.post(lambda: self.upd_text.configure(text="正在下载 v%s … %s" % (r["version"], pct)))

        def work():
            try:
                path, info = updater.download_and_verify(a, self.update_policy, prog)
            except updater.UpdateError as e:
                msg = str(e)
                self.post(lambda: self._update_failed(msg))
                return
            except Exception as e:
                updater._log("更新异常: %s" % e)
                msg = "更新失败：%s" % e
                self.post(lambda: self._update_failed(msg))
                return
            self.post(lambda: self._update_ready(path))
        threading.Thread(target=work, daemon=True).start()

    def _update_failed(self, msg):
        self.upd_busy = False
        self.upd_text.configure(text="更新失败：%s" % msg.replace("更新失败：", ""), text_color="#D14343")
        for b in (self.upd_btn_skip, self.upd_btn_notes):
            b.configure(state="normal")
        self.upd_btn_go.configure(state="normal", text="重试")

    def _update_ready(self, path):
        self.upd_text.configure(text="校验通过，正在启动安装程序…")
        try:
            self.update_launch(path)
        except Exception as e:
            updater._log("启动安装程序失败: %s" % e)
            self._update_failed("无法启动安装程序（%s），安装包在 %s" % (e, path))
            return
        self.after(400, self.update_quit)

    def switch_theme(self):
        """切换浅/深色：只切 appearance mode，控件按 (浅, 深) 元组颜色就地重绘，不销毁重建，状态天然保留。"""
        self.cfg["quality"] = self.quality.get() or core.DEFAULT_QUALITY
        self.cfg["theme"] = "dark" if self.theme_sw.get() else "light"
        core.save_config(self.cfg)
        hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
        ctypes.windll.user32.LockWindowUpdate(hwnd)      # 冻结屏幕刷新：先在后台把所有控件重绘完，再一次性放出
        try:
            apply_theme(self.cfg["theme"])
            retitle_all()
            self.set_status("已切换为%s主题" % ("深色" if THEME == "dark" else "浅色"))
            self.update_idletasks()
        finally:
            ctypes.windll.user32.LockWindowUpdate(0)
        ctypes.windll.user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)  # INVALIDATE|ERASE|ALLCHILDREN|UPDATENOW
        w = self._settings
        if w is not None and w.winfo_exists():
            w.sync_theme()

    def set_platforms(self, keys):
        """设置里改了“默认搜索的平台”：搜索栏下方的平台按钮跟着变。"""
        for k in core.PLATFORMS:
            self.pstate[k] = k in keys
            self._style_pill(k)

    def _style_pill(self, k):
        on = self.pstate[k]
        self.pbtn[k].configure(fg_color=PILL_BG[k] if on else CARD, hover_color=PILL_BG[k] if on else CARD_HOVER,
                               text_color=PILL_FG[k] if on else FG2, border_width=1,
                               border_color=PCOL[k] if on else BORDER)

    def toggle_platform(self, k):
        self.pstate[k] = not self.pstate[k]
        self._style_pill(k)

    # ------------------------------------------------------------ 线程 -> 界面
    def _pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def post(self, fn):
        self.q.put(fn)

    def log(self, msg):
        self.post(lambda: self.set_status(msg))

    def set_status(self, msg, color=FG2):
        self.status.configure(text=msg[:110], text_color=color)

    # ------------------------------------------------------------ 列表渲染
    def show_hint(self, box, text):
        for c in box.winfo_children():
            c.destroy()
        ctk.CTkLabel(box, text=text, font=F(13), text_color=FG2, wraplength=420, justify="center").pack(pady=60)

    def render_results(self):
        for c in self.res_box.winfo_children():
            c.destroy()
        self.cards = []
        self.selected_card = None
        if not self.results:
            self.show_hint(self.res_box, "没有找到相关主播\n换个关键词，或直接输入房间号 / 粘贴房间链接试试")
            return
        for it in self.results:
            c = Card(self.res_box, self, it)
            c.pack(fill="x", pady=4, padx=2)
            self.cards.append(c)

    def rebuild_favs(self):
        for c in self.fav_box.winfo_children():
            c.destroy()
        self.fav_cards = []
        if not self.favs:
            self.show_hint(self.fav_box, "还没有收藏\n点搜索结果里的 ☆ 加入")
            return
        for it in self.favs:
            c = Card(self.fav_box, self, it, fav_mode=True)
            c.pack(fill="x", pady=4, padx=2)
            self.fav_cards.append(c)

    def select_card(self, card):
        if self.selected_card is not None and self.selected_card.winfo_exists():
            self.selected_card.set_selected(False)
        self.selected_card = card
        card.set_selected(True)
        self.refresh_qualities(card.item)

    def refresh_qualities(self, it):
        """选中主播后，后台查询该房间真实有的画质档位，填进下拉框。"""
        url = core.room_url(it["platform"], it["rid"])

        def work():
            items = core.list_qualities(url)
            def done():
                if not items or self.selected_card is None or not self.selected_card.winfo_exists()                         or core.room_url(self.selected_card.item["platform"], self.selected_card.item["rid"]) != url:
                    return
                labels = [l for l, _ in items]
                cur = self.quality.get()
                self.quality.configure(values=labels)
                # 之前选的是某个码率就尽量保持，否则用最高档
                self.quality.set(cur if cur in labels else labels[0])
            self.post(done)
        threading.Thread(target=work, daemon=True).start()

    def load_avatar(self, item, card):
        def work():
            p = core.fetch_avatar(item.get("avatar"))
            if p:
                self.post(lambda: card.winfo_exists() and card.set_avatar(p))
        self.pool.submit(work)

    # ------------------------------------------------------------ PotPlayer
    def check_potplayer(self, prompt=True):
        self.potplayer = core.find_potplayer(self.cfg)
        self._settings_refresh()
        if self.potplayer:
            self.set_status("已找到 PotPlayer：" + _short_path(self.potplayer, 48))
            return
        self.set_status("未找到 PotPlayer（设置 → 播放 里可以重新检测或手动选择）", LIVE_RED)
        if prompt:
            self.ask_install()

    def _settings_refresh(self):
        w = self._settings
        if w is not None and w.winfo_exists():
            w.refresh_player()

    def ask_install(self):
        if core.has_winget():
            if ask(self, "未找到 PotPlayer",
                   "这台电脑上没有检测到 PotPlayer。\n是否用 winget 自动安装？（约需几分钟，期间请耐心等待）",
                   "同意安装", "暂不"):
                self.set_status("正在用 winget 安装 PotPlayer，请稍候…")
                threading.Thread(target=self._install_worker, daemon=True).start()
                return
            self.set_status("未安装 PotPlayer；可在 设置 → 播放 里手动选择路径，或装好后点“重新检测”")
        else:
            self._fallback_download("这台电脑没有 winget。")

    def _install_worker(self):
        ok = core.install_potplayer_winget(self.log)

        def done():
            p = core.find_potplayer(self.cfg)
            if ok and p:
                self.potplayer = p
                self._settings_refresh()
                self.set_status("PotPlayer 安装完成：" + p)
            else:
                self._fallback_download("winget 安装失败。")
        self.post(done)

    def _fallback_download(self, why):
        core.open_potplayer_download()
        info(self, "请手动安装 PotPlayer",
             why + "\n已为你打开 PotPlayer 官方下载页。\n装好后在 设置 → 播放 里点“重新检测”即可。")
        self.set_status("等待手动安装 PotPlayer，装好后在 设置 → 播放 里点“重新检测”")

    def pick_potplayer(self):
        f = filedialog.askopenfilename(title="选择 PotPlayerMini64.exe",
                                       filetypes=[("PotPlayer", "PotPlayer*.exe"), ("exe", "*.exe")])
        if f:
            self.cfg["potplayer"] = f
            core.save_config(self.cfg)
            self.check_potplayer()

    # ------------------------------------------------------------ 搜索
    def do_search(self):
        kw = self.kw.get().strip()
        if not kw:
            return
        parsed = core.parse_input(kw)
        plats = [k for k, v in self.pstate.items() if v]
        if not parsed and not plats:
            info(self, "提示", "请至少打开一个平台开关")
            return
        self.btn_search.configure(state="disabled", text="搜索中…")
        self.set_status("搜索中…")
        self.show_hint(self.res_box, "搜索中…")

        def work():
            if parsed:
                res = core.lookup_many([parsed[0]], parsed[1], self.log)
            elif kw.isdigit():
                res = core.lookup_many(plats, kw, self.log) + core.search_all(kw, plats, self.log)
            else:
                res = core.search_all(kw, plats, self.log)

            def done():
                self.results = res
                self.render_results()
                self.btn_search.configure(state="normal", text="搜索")
                self.res_title.configure(text="搜索结果（%d）" % len(res) if res else "搜索结果")
                if res:
                    self.set_status("找到 %d 个结果，双击卡片或点 ▶ 播放" % len(res))
            self.post(done)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 收藏
    def is_fav(self, it):
        return any(f["platform"] == it["platform"] and f["rid"] == it["rid"] for f in self.favs)

    def toggle_fav(self, it):
        if self.is_fav(it):
            self.remove_fav(it)
            return
        self.favs.append({k: it.get(k, "") for k in ("platform", "name", "rid", "avatar", "cate", "live")})
        core.save_favorites(self.favs)
        self.rebuild_favs()
        for c in self.cards:
            c.refresh()
        self.set_status("已收藏：" + it["name"])

    def remove_fav(self, it):
        self.favs = [f for f in self.favs if not (f["platform"] == it["platform"] and f["rid"] == it["rid"])]
        core.save_favorites(self.favs)
        self.rebuild_favs()
        for c in self.cards:
            c.refresh()
        self.set_status("已取消收藏：" + it["name"])

    def refresh_fav_status(self):
        """后台逐个查询收藏主播是否在播。"""
        favs = list(self.favs)
        if not favs or self._fav_busy:
            return
        self._fav_busy = True
        new_avatar = []

        def one(f):
            try:
                r = core.lookup_room(f["platform"], f["rid"])
                f["live"] = r["live"]
                if r.get("avatar") and not f.get("avatar"):
                    f["avatar"] = r["avatar"]
                    new_avatar.append(1)
            except Exception:
                pass
        def work():
            try:
                list(self.pool.map(one, favs))
            finally:
                def done():
                    self._fav_busy = False
                    self._fav_last = time.time()
                    core.save_favorites(self.favs)
                    if new_avatar:
                        self.rebuild_favs()          # 有新头像要加载才重建；否则只更新“直播中”标记，不打断滚动位置
                    else:
                        for c in self.fav_cards:
                            if c.winfo_exists():
                                c.refresh()
                self.post(done)
        threading.Thread(target=work, daemon=True).start()

    def _fav_tick(self):
        """设置里选了“每 N 分钟自动刷新”时，到点后台刷新一次收藏状态。"""
        m = int(self.cfg.get("fav_refresh_min") or 0)
        if m > 0 and self.favs and not self._fav_busy and time.time() - self._fav_last >= m * 60:
            self.refresh_fav_status()
        self.after(30000, self._fav_tick)

    # ------------------------------------------------------------ 播放
    def play_selected(self):
        if self.selected_card is None or not self.selected_card.winfo_exists():
            info(self, "提示", "请先点选一个主播卡片（或直接点卡片上的 ▶）")
            return
        self.play_item(self.selected_card.item)

    def play_item(self, it):
        if not self.potplayer:
            self.check_potplayer()
            if not self.potplayer:
                return
        self.stop_play(quiet=True)
        q = self.quality.get() or core.DEFAULT_QUALITY
        self.cfg["quality"] = q
        core.save_config(self.cfg)
        url = core.room_url(it["platform"], it["rid"])
        self.set_status("正在解析并启动：%s …" % it["name"], PCOL[it["platform"]])
        try:
            self.proc = core.start_play(self.potplayer, url, q)
        except Exception as e:
            info(self, "启动失败", "没能启动播放：%s" % e)
            return
        self.btn_stop.configure(state="normal")
        self.dm.begin(it["platform"], it["rid"], self.proc)
        self.play_ctx = dict(item=it, url=url, q=q)
        self.resumer = core.AutoResumer(it["platform"], it["rid"])
        self._geom = None
        self._track_geom(self.proc)
        threading.Thread(target=self._watch, args=(self.proc, it["name"], time.time(), False), daemon=True).start()
        m = int(self.cfg.get("sleep_minutes") or 0)
        if m > 0:       # 睡眠定时：从开始播放算起，到点自动停止（自动续播不重新计时）
            self._sleep_job = self.after(m * 60000, self._sleep_fire)

    def _cancel_sleep(self):
        if self._sleep_job is not None:
            self.after_cancel(self._sleep_job)
            self._sleep_job = None

    def _sleep_fire(self):
        self._sleep_job = None
        if self.proc:
            self.stop_play(quiet=True)
            self.set_status("睡眠定时已到，已停止播放")

    # ------------------------------------------------------------ 自动续播
    def _track_geom(self, proc):
        """播放期间每 0.5 秒记下 PotPlayer 窗口的位置/是否最大化，续播后摆回去。"""
        if self.proc is not proc:
            return
        try:
            h = self.dm.player_window()
            u = danmaku.user32
            if h and u.IsWindowVisible(h) and not u.IsIconic(h):
                r = ctypes.wintypes.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                pid = ctypes.wintypes.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                self._geom = dict(hwnd=h, pid=pid.value, rect=(r.left, r.top, r.right - r.left, r.bottom - r.top),
                                  zoomed=bool(u.IsZoomed(h)))
        except Exception:
            pass
        self.after(500, lambda: self._track_geom(proc))

    def _restore_geom(self, geom, proc, st=None):
        """新窗口出现后把它摆回旧窗口的位置/大小，不抢焦点。PotPlayer 打开视频后会自己按视频大小再调一次窗口，
        所以窗口出现后的 15 秒内发现被改回去就再摆一次（最多 4 次）。"""
        if self.proc is not proc or not geom:
            return
        st = st or dict(t0=time.time(), seen=None, n=0)
        now = time.time()
        h = self.dm.player_window()
        u = danmaku.user32
        if h and u.IsWindowVisible(h) and h != geom.get("hwnd"):
            if st["seen"] is None:
                st["seen"] = now
            x, y, w, hh = geom["rect"]
            r = ctypes.wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            cur = (r.left, r.top, r.right - r.left, r.bottom - r.top)
            if geom["zoomed"]:
                if not u.IsZoomed(h) and st["n"] < 4:
                    u.ShowWindow(h, 3)  # SW_MAXIMIZE
                    st["n"] += 1
            elif cur != (x, y, w, hh) and st["n"] < 4:
                u.SetWindowPos(h, 0, x, y, w, hh, 0x0004 | 0x0010)  # NOZORDER|NOACTIVATE
                st["n"] += 1
            if now - st["seen"] >= 15:
                return
        elif now - st["t0"] > 25:
            return
        self.after(300, lambda: self._restore_geom(geom, proc, st))

    def _resume(self, name, msg):
        """流到期后重新拉起 streamlink：弹幕客户端/悬浮层不动，只换播放进程，并清掉残留的旧 PotPlayer 窗口。"""
        ctx = self.play_ctx
        it = ctx["item"]
        self.set_status(msg, PCOL[it["platform"]])
        geom = self._geom
        if geom and danmaku.user32.IsWindow(geom["hwnd"]):   # 旧窗口还在（没被 streamlink 一起关掉）就清掉，避免堆积
            try:
                subprocess.run(["taskkill", "/PID", str(geom["pid"]), "/T", "/F"], capture_output=True,
                               creationflags=core.NO_WINDOW, timeout=10)
            except Exception:
                pass
        try:
            newp = core.start_play(self.potplayer, ctx["url"], ctx["q"])
        except Exception as e:
            self.proc = None
            self.dm.end()
            self.btn_stop.configure(state="disabled")
            self.set_status("自动续播失败：%s" % e, LIVE_RED)
            return
        self.proc = newp
        self.dm.rebind(newp)
        self._track_geom(newp)
        self._restore_geom(geom, newp)
        threading.Thread(target=self._watch, args=(newp, name, time.time(), True), daemon=True).start()

    @staticmethod
    def friendly(lines):
        t = "\n".join(lines).lower()
        if "no playable streams" in t or "offline" in t or "not live" in t:
            return "这位主播现在没有开播（或房间没有可播放的流）"
        if "no plugin can handle" in t:
            return "房间链接无法识别"
        if "unable to open url" in t or "connection" in t or "timed out" in t:
            return "网络连接失败，请检查网络后重试"
        if "403" in t or "forbidden" in t:
            return "平台拒绝了请求（403），稍后再试"
        err = [l for l in lines if "error" in l.lower()]
        return "播放失败：" + (err[-1].split("error:")[-1].strip()[:80] if err else "未知原因")

    def _watch(self, proc, name, started, resumed):
        lines = []
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                lines.append(line)
                if "Opening stream" in line:
                    self.log(("已自动续播：" if resumed else "已开始播放：") + name)
        code = proc.wait()
        act, msg = "stop", None
        rs = self.resumer
        if self.proc is proc and rs is not None:   # 用户点了“停止”时 self.proc 已被清空，不续播
            try:
                act, msg = rs.on_exit(code, lines, time.time() - started, bool(self.cfg.get("auto_resume", True)))
            except Exception:
                act, msg = "stop", None

        def done():
            if self.proc is not proc:
                return
            if act == "resume":
                self._resume(name, msg)
                return
            self.proc = None
            self._cancel_sleep()
            self.dm.end()
            self.btn_stop.configure(state="disabled")
            if msg:
                self.set_status(msg, LIVE_RED)
            elif code != 0:
                self.set_status(self.friendly(lines), LIVE_RED)
            else:
                self.set_status("播放已结束：" + name)
        self.post(done)

    def stop_play(self, quiet=False):
        self._cancel_sleep()
        if self.proc:
            core.kill_tree(self.proc)
            self.proc = None
            self.dm.end()
            self.btn_stop.configure(state="disabled")
            if not quiet:
                self.set_status("已停止播放")

    # ------------------------------------------------------------ 弹幕
    def _dm_status(self, msg, color=None):
        self.set_status(msg, color or FG2)

    def on_danmaku_switch(self):
        on = bool(self.dm_sw.get())
        self.dm.set_enabled(on)
        if on and self.proc is None:
            self.set_status("弹幕已开启（Ctrl+Alt+D 开关）")
        elif not on:
            self.set_status("弹幕已关闭")

    def toggle_danmaku(self):
        """全局快捷键 Ctrl+Alt+D：切换开关并同步界面上的开关。"""
        if self.dm.enabled:
            self.dm_sw.deselect()
        else:
            self.dm_sw.select()
        self.on_danmaku_switch()

    # ------------------------------------------------------------ 设置 / 备份
    def open_settings(self, page=None):
        w = self._settings
        if w is not None and w.winfo_exists():
            if page:
                w.show_page(page)
            w.lift()
            w.focus_force()
            return
        self._settings = SettingsWindow(self, page or "通用")

    def apply_cfg_live(self, old):
        """设置被批量改动后（导入备份/恢复默认）让正在运行的界面跟上；old 是改动前的配置副本。"""
        want = self.cfg.get("theme", "light")
        if want != THEME:
            (self.theme_sw.select if want == "dark" else self.theme_sw.deselect)()
            self.switch_theme()
        self.set_platforms(self.cfg["default_platforms"])
        self.dm.apply_settings()
        if old.get("dm_renderer") != self.cfg.get("dm_renderer"):
            self.dm.set_renderer(self.cfg["dm_renderer"])

    def apply_backup(self, bk):
        """导入备份：设置覆盖，收藏只补缺的；返回新增的收藏数。"""
        old = dict(self.cfg)
        self.cfg.update(bk["settings"])
        core.save_config(self.cfg)
        self.favs, added = sysset.merge_favorites(self.favs, bk["favorites"])
        core.save_favorites(self.favs)
        self.rebuild_favs()
        self.apply_cfg_live(old)
        return added

    def reset_settings(self):
        old = dict(self.cfg)
        sysset.restore_defaults(self.cfg)
        core.save_config(self.cfg)
        if sysset.autostart_available():
            try:
                sysset.autostart_set(False)
            except OSError:
                pass
        self.apply_cfg_live(old)

    # ------------------------------------------------------------ 关闭 / 托盘
    def on_close(self):
        """点窗口右上角 ✕：按设置退出、最小化到托盘或先问一下。"""
        act = self.cfg.get("close_action", "exit")
        if act == "ask":
            act, remember = choose(self, "关闭直播助手",
                                   "要退出程序，还是最小化到托盘继续在后台运行？\n（播放和弹幕不受影响）",
                                   [("退出程序", "exit"), ("最小化到托盘", "tray")], "取消",
                                   "以后不再询问，记住我的选择")
            if act is None:
                return
            if remember:
                self.cfg["close_action"] = act
                core.save_config(self.cfg)
        if act == "tray":
            self._remember_geometry()
            if not self.tray_show():
                self.iconify()          # 托盘不可用就退而求其次，最小化到任务栏
            return
        self.quit_app()

    def tray_show(self):
        """显示托盘图标并隐藏主窗口；托盘库不可用返回 False（窗口保持原样）。"""
        if self.tray is None:
            self.tray = sysset.Tray("直播助手", resource("icon.ico"),
                                    lambda: self.post(self.show_window), lambda: self.post(self.quit_app))
        if not self.tray.show():
            return False
        self.withdraw()
        return True

    def show_window(self):
        """从托盘/再次双击图标唤起主窗口。"""
        if self.tray is not None:
            self.tray.hide()
        self.deiconify()
        self.state("normal")
        self.lift()
        self.attributes("-topmost", True)       # 临时置顶一下，绕过 Windows 对后台程序抢焦点的限制
        self.after(250, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def watch_second_launch(self):
        """用户又双击了图标：不开第二个窗口，而是把这个窗口显示出来（只在 __main__ 里启用）。"""
        self.watcher = sysset.ShowWatcher(lambda: self.post(self.show_window))

    def quit_app(self):
        """真正退出：停播放、关弹幕、撤托盘。"""
        self._remember_geometry()
        self._cancel_sleep()
        self.stop_play(quiet=True)
        if self.tray is not None:
            self.tray.hide()
        if self.watcher is not None:
            self.watcher.stop()
        self.dm.shutdown()
        self.destroy()


if __name__ == "__main__":
    first, _single_instance_handle = sysset.acquire_single_instance()
    if not first:       # 已经有一个在运行（可能躲在托盘里）：让它把窗口显示出来，自己退出
        sysset.signal_existing()
        sys.exit(0)
    _app = App()
    _app.watch_second_launch()
    _app.mainloop()
