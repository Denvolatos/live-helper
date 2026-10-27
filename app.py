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
    """隐藏自检：搜索三平台 + 房间查询 + 解析流地址 + 检测 PotPlayer，结果写入文件。"""
    import core
    lines = []
    for p, kw in (("douyu", "示例主播甲"), ("huya", "示例主播乙"), ("bili", "示例主播丙")):
        try:
            r = core.SEARCHERS[p](kw)
            lines.append("搜索 %s '%s': %d 条, 首条=%s" % (p, kw, len(r), r[0]["name"] if r else None))
        except Exception as e:
            lines.append("搜索 %s 失败: %s" % (p, e))
    for p, rid in (("douyu", "222222"), ("huya", "111111"), ("bili", "15075163")):
        try:
            r = core.lookup_room(p, rid)
            lines.append("房间查询 %s %s: %s 在播=%s" % (p, rid, r["name"], r["live"]))
        except Exception as e:
            lines.append("房间查询 %s 失败: %s" % (p, e))
    for u in ("https://www.douyu.com/222222", "https://www.huya.com/111111"):
        lines.append("解析 %s -> %s" % (u, core.resolve_stream_url(u)[:80]))
    # 弹幕：各连 12 秒，统计收到的条数（文本前 2 条做样例）
    try:
        import danmaku, time as _t
        for p, rid in (("douyu", "222222"), ("huya", "111111"), ("bili", "333333")):
            got = []
            c = danmaku.CLIENTS[p](rid, got.append)
            c.start()
            t0 = _t.time()
            while _t.time() - t0 < 12 and len(got) < 3:
                _t.sleep(0.3)
            c.stop()
            lines.append("弹幕 %s %s: 收到 %d 条, 样例=%s" % (p, rid, len(got), got[:2]))
    except Exception as e:
        lines.append("弹幕自检失败: %s" % e)
    lines.append("PotPlayer: %s" % core.find_potplayer({}))
    with open(outfile, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if len(sys.argv) > 1 and sys.argv[1] == "--streamlink-cli":
    _run_streamlink_cli()
if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
    _selftest(sys.argv[2])
    sys.exit(0)

import queue
import ctypes
from version import __version__
import threading
import tkinter as tk
from tkinter import filedialog
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from PIL import Image, ImageDraw

import core
import danmaku

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


# ---------------------------------------------------------------- 弹幕设置
class DanmakuSettings(ctk.CTkToplevel):
    _deactivate_windows_window_header_manipulation = True

    def __init__(self, app, cfg, dm, hotkey_ok):
        super().__init__(app)
        self.withdraw()
        self.cfg, self.dm = cfg, dm
        self.title("弹幕设置")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(app)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        box = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        box.pack(padx=16, pady=16)
        ctk.CTkLabel(box, text="弹幕设置", font=F(16, True), text_color=FG).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=22, pady=(18, 10))
        self.lbls = {}

        def slider(row, label, key, lo, hi, steps, fmt):
            ctk.CTkLabel(box, text=label, font=F(13), text_color=FG2).grid(row=row, column=0, sticky="w", padx=(22, 10), pady=6)
            lb = ctk.CTkLabel(box, text=fmt(cfg[key]), font=F(13), text_color=FG, width=56)
            lb.grid(row=row, column=2, padx=(6, 22))

            def on(v, key=key, lb=lb):
                cfg[key] = round(float(v), 2) if key == "dm_alpha" else int(round(v))
                lb.configure(text=fmt(cfg[key]))
                dm.apply_settings()
            sl = ctk.CTkSlider(box, from_=lo, to=hi, number_of_steps=steps, width=190, fg_color=TRACK, progress_color=PRIMARY,
                               button_color=PRIMARY, button_hover_color=PRIMARY_HOVER, command=on)
            sl.set(cfg[key])
            sl.grid(row=row, column=1, pady=6)
        slider(1, "字号", "dm_font", 16, 56, 40, lambda v: "%d" % v)
        slider(2, "透明度", "dm_alpha", 0.3, 1.0, 14, lambda v: "%d%%" % round(float(v) * 100))
        slider(3, "飘过时间", "dm_speed", 4, 16, 12, lambda v: "%d 秒" % v)
        slider(4, "同屏最多", "dm_max", 20, 150, 13, lambda v: "%d 条" % v)
        ctk.CTkLabel(box, text="显示区域", font=F(13), text_color=FG2).grid(row=5, column=0, sticky="w", padx=(22, 10), pady=6)
        self.area = ctk.CTkOptionMenu(box, values=danmaku.AREAS, width=190, height=34, corner_radius=17, font=F(13),
                                      dropdown_font=F(13), fg_color=BTN2, text_color=FG, button_color=BTN2_HOVER,
                                      button_hover_color=BTN2_HOVER, dropdown_fg_color=CARD, dropdown_text_color=FG,
                                      dropdown_hover_color=CARD_HOVER, command=self._area)
        self.area.set(cfg.get("dm_area", "上半屏"))
        self.area.grid(row=5, column=1, columnspan=2, sticky="w", pady=6)
        ctk.CTkLabel(box, text="渲染方式", font=F(13), text_color=FG2).grid(row=6, column=0, sticky="w", padx=(22, 10), pady=6)
        self.rend = ctk.CTkOptionMenu(box, values=danmaku.RENDERERS, width=190, height=34, corner_radius=17, font=F(13),
                                      dropdown_font=F(13), fg_color=BTN2, text_color=FG, button_color=BTN2_HOVER,
                                      button_hover_color=BTN2_HOVER, dropdown_fg_color=CARD, dropdown_text_color=FG,
                                      dropdown_hover_color=CARD_HOVER, command=self._renderer)
        self.rend.set(cfg.get("dm_renderer", danmaku.RENDERERS[0]))
        self.rend.grid(row=6, column=1, columnspan=2, sticky="w", pady=6)
        hk = "快捷键 Ctrl+Alt+D 随时开关弹幕。" if hotkey_ok else "快捷键 Ctrl+Alt+D 注册失败（被别的软件占用），请用界面上的开关。"
        tip = (hk + "\n弹幕是盖在 PotPlayer 上的透明窗口：窗口化和普通全屏可见；"
               "若 PotPlayer 设为“独占全屏”（Exclusive），弹幕可能被挡住看不到。\n弹幕显示异常（重影、不显示）时，把“渲染方式”切到“兼容（旧）”。")
        ctk.CTkLabel(box, text=tip, font=F(12), text_color=FG2, justify="left", wraplength=400).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=22, pady=(10, 6))
        ctk.CTkButton(box, text="完成", width=100, height=36, corner_radius=18, fg_color=PRIMARY,
                      hover_color=PRIMARY_HOVER, text_color=ON_PRIMARY, font=F(13, True),
                      command=self.destroy).grid(row=8, column=0, columnspan=3, sticky="e", padx=22, pady=(6, 18))
        center_show(self, app)

    def _area(self, v):
        self.cfg["dm_area"] = v
        self.dm.apply_settings()

    def _renderer(self, v):
        self.dm.set_renderer(v)   # “平滑”= 自绘分层窗口（默认）；“兼容”= 旧的 Tk 画布，万一平滑版在某台电脑上异常可切回


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
        w, h = 960, 640
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max((sh - h) // 2 - 20, 0)))
        self.minsize(760, 520)
        self.cfg = core.load_config()
        self.favs = core.load_favorites()
        self.results = []
        self.cards = []
        self.fav_cards = []
        self.selected_card = None
        self.proc = None
        self.potplayer = None
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.pstate = {k: True for k in core.PLATFORMS}
        self.pbtn = {}
        self._build()
        # 弹幕：悬浮层 + 全局快捷键 Ctrl+Alt+D（热键线程里只投递到主线程，不直接碰界面）
        self.dm = danmaku.DanmakuManager(self, self.cfg, lambda: core.save_config(self.cfg), self._dm_status)
        self.hotkey_ok = self.dm.start_hotkey(lambda: self.post(self.toggle_danmaku))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._pump)
        self.after(300, self.check_potplayer)
        self.after(600, self.refresh_fav_status)
        self.show_hint(self.res_box, "输入主播名字回车搜索，或粘贴房间链接/房间号")
        self.update_idletasks()
        track_titlebar(self)
        self.deiconify()

    # ------------------------------------------------------------ 界面
    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(18, 8))
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
        ctk.CTkLabel(pb, text="画质", font=F(12), text_color=FG2).pack(side="left", padx=(20, 6))
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
        ctk.CTkButton(pb, text="⚙", width=30, height=28, corner_radius=14, font=F(13), fg_color=BTN2,
                      hover_color=BTN2_HOVER, text_color=FG2, command=self.open_danmaku_settings
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(pb, text="PotPlayer 路径", width=94, height=28, corner_radius=14, font=F(11),
                      fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG2,
                      command=self.pick_potplayer).pack(side="right", padx=(4, 20))
        ctk.CTkButton(pb, text="重新检测", width=68, height=28, corner_radius=14, font=F(11),
                      fg_color=BTN2, hover_color=BTN2_HOVER, text_color=FG2,
                      command=self.check_potplayer).pack(side="right")
        self.status = ctk.CTkLabel(pb, text="就绪", font=F(12), text_color=FG2, anchor="w", width=10)
        self.status.pack(side="left", fill="x", expand=True, padx=12)

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
    def check_potplayer(self):
        self.potplayer = core.find_potplayer(self.cfg)
        if self.potplayer:
            self.set_status("已找到 PotPlayer：" + self.potplayer)
            return
        self.set_status("未找到 PotPlayer", LIVE_RED)
        self.ask_install()

    def ask_install(self):
        if core.has_winget():
            if ask(self, "未找到 PotPlayer",
                   "这台电脑上没有检测到 PotPlayer。\n是否用 winget 自动安装？（约需几分钟，期间请耐心等待）",
                   "同意安装", "暂不"):
                self.set_status("正在用 winget 安装 PotPlayer，请稍候…")
                threading.Thread(target=self._install_worker, daemon=True).start()
                return
            self.set_status("未安装 PotPlayer；可手动选择路径，或装好后点“重新检测”")
        else:
            self._fallback_download("这台电脑没有 winget。")

    def _install_worker(self):
        ok = core.install_potplayer_winget(self.log)

        def done():
            p = core.find_potplayer(self.cfg)
            if ok and p:
                self.potplayer = p
                self.set_status("PotPlayer 安装完成：" + p)
            else:
                self._fallback_download("winget 安装失败。")
        self.post(done)

    def _fallback_download(self, why):
        core.open_potplayer_download()
        info(self, "请手动安装 PotPlayer",
             why + "\n已为你打开 PotPlayer 官方下载页。\n装好后点底部的“重新检测”即可。")
        self.set_status("等待手动安装 PotPlayer，装好后点“重新检测”")

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

        def one(f):
            try:
                r = core.lookup_room(f["platform"], f["rid"])
                f["live"] = r["live"]
                if r.get("avatar") and not f.get("avatar"):
                    f["avatar"] = r["avatar"]
            except Exception:
                pass
        def work():
            list(self.pool.map(one, favs))
            def done():
                core.save_favorites(self.favs)
                self.rebuild_favs()
            self.post(done)
        if favs:
            threading.Thread(target=work, daemon=True).start()

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
        threading.Thread(target=self._watch, args=(self.proc, it["name"]), daemon=True).start()

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

    def _watch(self, proc, name):
        lines = []
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                lines.append(line)
                if "Opening stream" in line:
                    self.log("已开始播放：" + name)
        code = proc.wait()

        def done():
            if self.proc is proc:
                self.proc = None
                self.dm.end()
                self.btn_stop.configure(state="disabled")
                if code != 0:
                    self.set_status(self.friendly(lines), LIVE_RED)
                else:
                    self.set_status("播放已结束：" + name)
        self.post(done)

    def stop_play(self, quiet=False):
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

    def open_danmaku_settings(self):
        DanmakuSettings(self, self.cfg, self.dm, self.hotkey_ok)

    def on_close(self):
        self.stop_play(quiet=True)
        self.dm.shutdown()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
