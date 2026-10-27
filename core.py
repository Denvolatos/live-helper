# -*- coding: utf-8 -*-
"""直播助手核心逻辑：搜索、PotPlayer 检测/安装、管道播放、收藏存储。"""
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
PLATFORMS = {"huya": "虎牙", "douyu": "斗鱼", "bili": "B站"}
# 画质选项：平台的流名是“线路_码率”（hs_8000k、4000k、al_source…），没有 1080p/720p。
# 选中主播后向 streamlink 查询该房间真实有的档位，界面显示成“超清 8 Mbps”这样的描述；
# 查询前或查询失败时只有“最高画质（自动）”。
AUTO_QUALITY = "最高画质（自动）"
QUALITIES = [AUTO_QUALITY]
DEFAULT_QUALITY = AUTO_QUALITY
QUAL_CACHE = {}  # url -> {界面标签: streamlink 选择串}
_ALIASES = {"best", "worst", "best-unfiltered", "worst-unfiltered"}


def _tier(k):
    return "超清" if k >= 8000 else "高清" if k >= 4000 else "标清" if k >= 2000 else "流畅"


def _mbps(k):
    v = k / 1000.0
    return ("%d" % v if v == int(v) else "%.1f" % v) + " Mbps"


def list_qualities(url):
    """查询房间真实可用的档位，返回 [(标签, 选择串)]，最高在前；失败返回空列表。

    注意：有的平台（斗鱼）插件会把同一个流标成好几个码率名（4000k/8000k/16xxxk 指向同一文件，
    最高档的数字还每次查询都在变），所以按“真实地址”（文件名+ratio 参数）去重后再显示。
    """
    import json as _json
    from urllib.parse import urlparse, parse_qs
    try:
        p = subprocess.run(self_command() + ["--json", url], capture_output=True, text=True,
                           timeout=60, creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        streams = _json.loads(p.stdout).get("streams", {})
    except Exception:
        return []
    names = [n for n in streams if n not in _ALIASES]
    order = {"hs": 0, "tx": 1, "al": 2}
    names.sort(key=lambda n: (order.get(n.split("_")[0], 9), n))

    def real_key(n):  # 同一个真实流 -> 同一个 key
        u = (streams.get(n) or {}).get("url")
        if not u:
            return ("name", n)
        pr = urlparse(u)
        return (pr.path.rsplit("/", 1)[-1], parse_qs(pr.query).get("ratio", [""])[0])

    groups = {}
    for n in names:
        groups.setdefault(real_key(n), []).append(n)

    def kbps(n):
        m = re.search(r"(\d+)k$", n)
        return int(m.group(1)) if m else None

    def gmax(g):
        ks = [kbps(n) for n in g if kbps(n)]
        return max(ks) if ks else None

    def is_source(g):
        return any("source" in n.lower() for n in g)

    glist = list(groups.values())
    # 最高在前：源码流 > 码率大的 > 其它
    glist.sort(key=lambda g: (0 if is_source(g) else 1, -(gmax(g) or 0)))
    items = []
    for idx, g in enumerate(glist):
        k_lo = min([kbps(n) for n in g if kbps(n)] or [0])
        if is_source(g):
            items.append(("原画（源码流）", ",".join(g)))
        elif idx == 0 and not any(is_source(x) for x in glist):
            # 没有源码流时最高档的码率每次查询都会浮动，不显示数字、直接用 best
            items.append(("原画（最高档）", "best"))
        elif k_lo:
            items.append(("%s %s" % (_tier(k_lo), _mbps(k_lo)), ",".join(g + ["best"])))
        else:
            items.append((g[0], g[0]))
    if items:
        QUAL_CACHE[url] = dict(items)
    return items


def quality_arg(label, url=None):
    """界面档位 -> streamlink 画质参数；该房间查不到对应档位时回退 best。"""
    sel = QUAL_CACHE.get(url, {}).get(label)
    if sel:
        return sel
    m = re.search(r"([\d.]+) Mbps", label or "")
    if m:
        k = int(float(m.group(1)) * 1000)
        names = [f"{c}_{k}k" for c in ("hs", "tx", "al")] + [f"{k}k"]
        return ",".join(names + ["best"])
    return "best"
POTPLAYER_DL_URL = "https://potplayer.daum.net/"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

APPDIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "直播助手")
FAV_FILE = os.path.join(APPDIR, "favorites.json")
CFG_FILE = os.path.join(APPDIR, "config.json")


# ---------------------------------------------------------------- 存储
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    os.makedirs(APPDIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_favorites():
    return _load(FAV_FILE, [])


def save_favorites(favs):
    _save(FAV_FILE, favs)


def load_config():
    return _load(CFG_FILE, {})


def save_config(cfg):
    _save(CFG_FILE, cfg)


# ---------------------------------------------------------------- 房间 URL
def room_url(platform, rid):
    rid = str(rid)
    return {"huya": "https://www.huya.com/" + rid,
            "douyu": "https://www.douyu.com/" + rid,
            "bili": "https://live.bilibili.com/" + rid}[platform]


def parse_input(text):
    """识别输入：房间页链接 -> (平台, 房间号/名)；否则 None。"""
    text = text.strip()
    m = re.search(r"huya\.com/([A-Za-z0-9_]+)", text)
    if m:
        return "huya", m.group(1)
    m = re.search(r"douyu\.com/(?:topic/\w+\?rid=|)(\d+)", text)
    if m:
        return "douyu", m.group(1)
    m = re.search(r"live\.bilibili\.com/(?:h5/)?(\d+)", text)
    if m:
        return "bili", m.group(1)
    return None


# ---------------------------------------------------------------- 搜索
def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def _fmt_hot(n):
    try:
        n = int(n)
    except Exception:
        return str(n or "")
    return "%.1f万" % (n / 10000) if n >= 10000 else str(n)


def search_douyu(kw):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get("https://www.douyu.com/", timeout=10)
    r = s.get("https://www.douyu.com/japi/search/api/searchShow",
              params={"kw": kw, "page": 1, "pageSize": 10},
              headers={"Referer": "https://www.douyu.com/search/"}, timeout=10)
    j = r.json()
    if j.get("error"):  # 例如 error=8：触发斗鱼风控（短时间搜索太频繁）
        raise RuntimeError("斗鱼搜索被风控（%s），请稍等几分钟重试，或直接输入房间号/粘贴房间链接" % j.get("msg"))
    out = []
    for x in j["data"].get("relateShow", []):
        out.append(dict(platform="douyu", name=_strip_tags(x["nickName"]),
                        rid=str(x["rid"]), live=bool(x.get("isLive") == 1),
                        info=x.get("roomName") or x.get("cateName") or "",
                        cate=x.get("cateName") or "", avatar=x.get("avatar") or "",
                        hot=str(x.get("hot", ""))))
    return out


def search_huya(kw):
    r = requests.get(
        "https://search.cdn.huya.com/",
        params={"m": "Search", "do": "getSearchContent", "q": kw, "uid": 0, "v": 4,
                "typ": -5, "livestate": 0, "rows": 15, "start": 0},
        headers={"User-Agent": UA, "Referer": "https://www.huya.com/"}, timeout=10)
    docs = r.json()["response"]["1"]["docs"]
    out = []
    for d in docs:
        out.append(dict(platform="huya", name=_strip_tags(d.get("game_nick")),
                        rid=str(d.get("room_id")), live=bool(d.get("gameLiveOn")),
                        info=d.get("live_intro") or d.get("game_name") or "",
                        cate=d.get("game_name") or "",
                        avatar=d.get("game_avatarUrl180") or d.get("game_avatarUrl52") or "",
                        hot=_fmt_hot(d.get("game_activityCount"))))
    return out


def search_bili(kw):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://search.bilibili.com/"})
    s.get("https://www.bilibili.com/", timeout=10)  # 取 buvid cookie，否则被拦
    r = s.get("https://api.bilibili.com/x/web-interface/search/type",
              params={"search_type": "live_user", "keyword": kw, "page": 1}, timeout=10)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError("B站搜索失败：%s" % j.get("message"))
    out = []
    for x in j["data"].get("result") or []:
        out.append(dict(platform="bili", name=_strip_tags(x.get("uname")),
                        rid=str(x.get("roomid")), live=bool(x.get("is_live")),
                        info=x.get("cate_name") or "", cate=x.get("cate_name") or "",
                        avatar=("https:" + x["uface"]) if str(x.get("uface", "")).startswith("//") else (x.get("uface") or ""),
                        hot=_fmt_hot(x.get("attentions"))))
    return out


SEARCHERS = {"huya": search_huya, "douyu": search_douyu, "bili": search_bili}


# ---- 按房间号/链接直接查询（搜索被风控或搜不到时的兜底）
def lookup_room(platform, rid):
    """返回与搜索结果同结构的一条记录；查不到抛异常。"""
    rid = str(rid)
    if platform == "douyu":
        j = requests.get("https://www.douyu.com/betard/" + rid,
                         headers={"User-Agent": UA}, timeout=10).json()["room"]
        return dict(platform="douyu", name=j["nickname"], rid=str(j["room_id"]),
                    live=j.get("show_status") == 1, info=j.get("room_name", ""), hot="",
                    avatar=j.get("avatar", {}).get("middle", "") if isinstance(j.get("avatar"), dict) else "")
    if platform == "huya":
        t = requests.get("https://www.huya.com/" + rid,
                         headers={"User-Agent": UA}, timeout=10).text
        nick = re.search(r'"nick":"([^"]+)"', t)
        if not nick:
            raise RuntimeError("虎牙房间不存在")
        on = re.search(r'"isOn":(true|false)', t)
        intro = re.search(r'"introduction":"([^"]*)"', t)
        return dict(platform="huya", name=nick.group(1), rid=rid,
                    live=bool(on and on.group(1) == "true"),
                    info=intro.group(1) if intro else "", hot="")
    h = {"User-Agent": UA}
    j = requests.get("https://api.live.bilibili.com/room/v1/Room/get_info",
                     params={"room_id": rid}, headers=h, timeout=10).json()
    if j.get("code") != 0:
        raise RuntimeError("B站房间不存在")
    d = j["data"]
    name = "B站房间 " + rid
    try:
        m = requests.get("https://api.live.bilibili.com/live_user/v1/Master/info",
                         params={"uid": d["uid"]}, headers=h, timeout=10).json()
        name = m["data"]["info"]["uname"]
    except Exception:
        pass
    return dict(platform="bili", name=name, rid=str(d["room_id"]),
                live=d.get("live_status") == 1, info=d.get("title", ""), hot="")


def lookup_many(platforms, rid, log=lambda m: None):
    res = []
    for p in platforms:
        try:
            res.append(lookup_room(p, rid))
        except Exception as e:
            log("%s 房间 %s 查询失败：%s" % (PLATFORMS[p], rid, e))
    return res


def search_all(kw, platforms, log=lambda m: None):
    """依次搜索各平台，单平台失败不影响其他。返回结果列表（在播的排前面）。"""
    res = []
    for p in platforms:
        try:
            part = SEARCHERS[p](kw)
            log("%s：找到 %d 个" % (PLATFORMS[p], len(part)))
            res += part
        except Exception as e:
            log("%s 搜索失败：%s" % (PLATFORMS[p], e))
    res.sort(key=lambda x: not x["live"])
    return res


# ---------------------------------------------------------------- PotPlayer
def find_potplayer(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    p = cfg.get("potplayer")
    if p and os.path.isfile(p):
        return p
    local = os.environ.get("LOCALAPPDATA", "")
    dirs = [r"D:\PotPlayer", r"C:\Program Files\DAUM\PotPlayer",
            r"C:\Program Files (x86)\DAUM\PotPlayer", r"C:\Program Files\PotPlayer",
            os.path.join(local, "Programs", "PotPlayer")]
    for d in dirs:
        for exe in ("PotPlayerMini64.exe", "PotPlayerMini.exe"):
            f = os.path.join(d, exe)
            if os.path.isfile(f):
                return f
    for exe in ("PotPlayerMini64.exe", "PotPlayerMini.exe"):
        w = shutil.which(exe)
        if w:
            return w
    return None


def has_winget():
    return shutil.which("winget") is not None


def install_potplayer_winget(log=lambda m: None):
    """用 winget 安装 PotPlayer（调用前必须已得到用户同意）。成功返回 True。"""
    if not has_winget():
        return False
    cmd = ["winget", "install", "--id", "Daum.PotPlayer", "-e",
           "--accept-source-agreements", "--accept-package-agreements"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                           creationflags=NO_WINDOW)
        log("winget 退出码 %s" % p.returncode)
        return p.returncode == 0
    except Exception as e:
        log("winget 执行失败：%s" % e)
        return False


AVATAR_DIR = os.path.join(APPDIR, "avatars")


def fetch_avatar(url):
    """下载头像并缓存到用户目录，返回本地路径；失败返回 None。"""
    if not url:
        return None
    import hashlib
    path = os.path.join(AVATAR_DIR, hashlib.md5(url.encode()).hexdigest() + ".img")
    if os.path.isfile(path):
        return path
    try:
        os.makedirs(AVATAR_DIR, exist_ok=True)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
        if r.status_code == 200 and r.content:
            with open(path, "wb") as f:
                f.write(r.content)
            return path
    except Exception:
        pass
    return None


def open_potplayer_download():
    webbrowser.open(POTPLAYER_DL_URL)


# ---------------------------------------------------------------- 播放
def self_command():
    """返回“再次调用自身并进入 streamlink 模式”的命令前缀。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--streamlink-cli"]
    return [sys.executable, os.path.abspath(sys.argv[0]), "--streamlink-cli"]


def build_play_cmd(potplayer, url, quality):
    # 等价于：streamlink -p <PotPlayer> --player-args "/new {playerinput}" <URL> <画质>
    # /new 让 PotPlayer 开独立新实例，关闭时不会误伤用户已开着的播放器
    return self_command() + ["-p", potplayer, "--player-args", "/new {playerinput}",
                             url, quality_arg(quality, url)]


def start_play(potplayer, url, quality=DEFAULT_QUALITY):
    """启动管道播放，返回 Popen（stdout 合并 stderr，供读取日志）。"""
    cmd = build_play_cmd(potplayer, url, quality)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, env=env)


def kill_tree(proc):
    """结束 streamlink 子进程及其拉起的播放器。"""
    if proc is None or proc.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=NO_WINDOW, timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def resolve_stream_url(url, quality=DEFAULT_QUALITY):
    """仅解析流地址（冒烟测试/调试用），内部同样走自身的 streamlink 模式。"""
    cmd = self_command() + ["--stream-url", url, quality_arg(quality, url)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                       creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    return (p.stdout or "").strip() or (p.stderr or "").strip()
