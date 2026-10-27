# -*- coding: utf-8 -*-
"""直播助手 - 弹幕模块。

包含：
  1. 三个平台的弹幕客户端（斗鱼 / 虎牙 / B站），都是后台线程，断线自动重连（指数退避）；
  2. 悬浮层 Overlay：透明、置顶、点击穿透的 tkinter 窗口，弹幕从右向左飘；
  3. 窗口跟随：找到我们启动的 PotPlayer 窗口，定时同步位置大小；
  4. 全局快捷键 Ctrl+Alt+D（RegisterHotKey，独立线程）；
  5. DanmakuManager：把以上串起来，供 app.py 调用。

所有平台协议都是逆向接口，会失效；验证日期见 工作日志/直播助手-日志.md。
"""
import ctypes
import json
import os
import queue
import random
import re
import socket
import struct
import threading
import time
import zlib
from ctypes import wintypes

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# 每个平台是否启用弹幕（做不成的平台置 False，界面里会提示并跳过）
SUPPORTED = {"douyu": True, "huya": True, "bili": True}
AREAS = ["全屏", "上半屏", "上三分之一"]
AREA_FRAC = {"全屏": 1.0, "上半屏": 0.5, "上三分之一": 1 / 3.0}
DEFAULTS = dict(danmaku_on=False, dm_font=28, dm_alpha=0.9, dm_speed=8, dm_area="上半屏")


# ====================================================================== 客户端基类
class DanmakuClient(threading.Thread):
    """后台线程：连接→收弹幕→回调 on_msg(text)；断线按 2,4,8..30 秒退避重连。"""

    platform = ""

    def __init__(self, rid, on_msg, on_status=None):
        super().__init__(daemon=True, name="danmaku-" + self.platform)
        self.rid = str(rid)
        self.on_msg = on_msg
        self.on_status = on_status or (lambda s: None)
        self._stop_evt = threading.Event()
        self._sock = None   # 供 stop() 强制关闭，打断阻塞中的 recv
        self.connected = False

    def stop(self):
        self._stop_evt.set()
        s = self._sock
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

    @property
    def stopped(self):
        return self._stop_evt.is_set()

    def run(self):
        delay = 2
        while not self.stopped:
            t0 = time.time()
            try:
                self.run_once()
            except Exception as e:  # 网络/协议错误都不能影响播放
                if not self.stopped:
                    self.on_status("弹幕连接出错：%s" % str(e)[:60])
            self.connected = False
            if self.stopped:
                break
            # 连得久说明是正常断线，退避从头开始
            delay = 2 if time.time() - t0 > 60 else min(delay * 2, 30)
            self.on_status("弹幕断线，%d 秒后重连" % delay)
            self._stop_evt.wait(delay)

    def run_once(self):
        raise NotImplementedError

    def _ok(self):
        self.connected = True
        self.on_status("弹幕已连接")


# ====================================================================== 斗鱼
def _stt_escape(s):
    return s.replace("@", "@A").replace("/", "@S")


def _stt_unescape(s):
    return s.replace("@S", "/").replace("@A", "@")


def stt_decode(s):
    """STT 串（k@=v/k@=v/）解析成 dict；嵌套值保持转义后的原串。"""
    out = {}
    for part in s.split("/"):
        if "@=" in part:
            k, v = part.split("@=", 1)
            out[k] = _stt_unescape(v)
    return out


def douyu_pack(s):
    d = s.encode("utf-8") + b"\0"
    n = len(d) + 8
    return struct.pack("<IIHBB", n, n, 689, 0, 0) + d


class DouyuClient(DanmakuClient):
    """斗鱼弹幕。

    官方文档写的是 wss://danmuproxy.douyu.com:8506/，但在海外（意大利）DNS 会解析到
    海外节点，TLS 握手直接被拒；实测同一 STT 协议走 TCP 8601（danmu.douyu.com）可用，
    所以先走 TCP 8601，失败再试 wss 8506。
    """
    platform = "douyu"
    TCP_HOSTS = [("danmu.douyu.com", 8601), ("danmuproxy.douyu.com", 8601)]
    WSS_URL = "wss://danmuproxy.douyu.com:8506/"

    def run_once(self):
        errs = []
        for host, port in self.TCP_HOSTS:
            if self.stopped:
                return
            try:
                return self._run_tcp(host, port)
            except (OSError, socket.timeout) as e:
                errs.append(str(e))
        try:
            return self._run_ws()
        except Exception as e:
            raise RuntimeError("斗鱼弹幕服务器连不上（%s）" % (errs[-1] if errs else e))

    def _login(self, send):
        send(douyu_pack("type@=loginreq/roomid@=%s/" % self.rid))
        send(douyu_pack("type@=joingroup/rid@=%s/gid@=-9999/" % self.rid))

    def _handle(self, body):
        d = stt_decode(body)
        t = d.get("type")
        if t == "chatmsg" and d.get("txt"):
            self.on_msg(d["txt"])
        elif t == "loginres":
            self._ok()

    def _run_tcp(self, host, port):
        s = socket.create_connection((host, port), timeout=8)
        self._sock = s
        s.settimeout(1.0)
        self._login(s.sendall)
        buf = b""
        last_hb = time.time()
        got_any = False
        try:
            while not self.stopped:
                if time.time() - last_hb > 40:
                    s.sendall(douyu_pack("type@=mrkl/"))
                    last_hb = time.time()
                try:
                    d = s.recv(65536)
                except socket.timeout:
                    continue
                if not d:
                    raise ConnectionError("服务器关闭了连接")
                got_any = True
                buf += d
                while len(buf) >= 4:
                    n = struct.unpack("<I", buf[:4])[0]
                    if len(buf) < n + 4:
                        break
                    body = buf[12:n + 3].decode("utf-8", "replace")
                    buf = buf[n + 4:]
                    self._handle(body)
        finally:
            self._sock = None
            try:
                s.close()
            except Exception:
                pass
        return got_any

    def _run_ws(self):
        import websocket
        ws = websocket.create_connection(self.WSS_URL, timeout=8,
                                         header=["User-Agent: " + UA], origin="https://www.douyu.com")
        self._sock = ws
        ws.settimeout(1.0)
        self._login(lambda b: ws.send_binary(b))
        last_hb = time.time()
        try:
            while not self.stopped:
                if time.time() - last_hb > 40:
                    ws.send_binary(douyu_pack("type@=mrkl/"))
                    last_hb = time.time()
                try:
                    m = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if isinstance(m, bytes) and len(m) > 12:
                    self._handle(m[12:].rstrip(b"\0").decode("utf-8", "replace"))
        finally:
            self._sock = None
            try:
                ws.close()
            except Exception:
                pass


# ====================================================================== B站
_WBI_MIX = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14,
            39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59,
            6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def bili_wbi_sign(params, mixin_key):
    import hashlib
    from urllib.parse import urlencode
    p = dict(params)
    p["wts"] = int(time.time())
    p = dict(sorted(p.items()))
    p = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in p.items()}
    p["w_rid"] = hashlib.md5((urlencode(p) + mixin_key).encode()).hexdigest()
    return p


def bili_danmu_info(rid):
    """返回 (真实房间号, token, [wss 地址], buvid3)。需要 buvid3 cookie + wbi 签名。"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://live.bilibili.com/"})
    s.get("https://www.bilibili.com/", timeout=10)
    buvid = s.cookies.get("buvid3", "")
    nav = s.get("https://api.bilibili.com/x/web-interface/nav", timeout=10).json()
    w = nav["data"]["wbi_img"]
    k = w["img_url"].rsplit("/", 1)[1].split(".")[0] + w["sub_url"].rsplit("/", 1)[1].split(".")[0]
    mixin = "".join(k[i] for i in _WBI_MIX)[:32]
    real = rid
    try:
        r = s.get("https://api.live.bilibili.com/room/v1/Room/room_init", params={"id": rid}, timeout=10).json()
        real = str(r["data"]["room_id"])
    except Exception:
        pass
    j = s.get("https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo",
              params=bili_wbi_sign({"id": real, "type": 0}, mixin), timeout=10).json()
    if j.get("code") != 0:
        raise RuntimeError("B站 getDanmuInfo 失败：%s %s" % (j.get("code"), j.get("message")))
    d = j["data"]
    hosts = ["wss://%s:%s/sub" % (h["host"], h.get("wss_port", 443)) for h in d.get("host_list", [])]
    hosts.append("wss://broadcastlv.chat.bilibili.com/sub")
    return real, d["token"], hosts, buvid


def bili_pack(op, body=b"", ver=1):
    return struct.pack(">IHHII", 16 + len(body), 16, ver, op, 1) + body


def bili_unpack(data):
    """把一个 WebSocket 二进制帧拆成 [(op, payload bytes)]，自动解压嵌套包。"""
    out = []
    off = 0
    while off + 16 <= len(data):
        plen, hlen, ver, op, _ = struct.unpack(">IHHII", data[off:off + 16])
        if plen < 16:
            break
        body = data[off + hlen:off + plen]
        off += plen
        if op == 5 and ver in (2, 3):
            try:
                if ver == 3:
                    import brotli
                    body = brotli.decompress(body)
                else:
                    body = zlib.decompress(body)
                out += bili_unpack(body)
            except Exception:
                pass
        else:
            out.append((op, body))
    return out


class BiliClient(DanmakuClient):
    platform = "bili"

    def run_once(self):
        import websocket
        real, token, hosts, buvid = bili_danmu_info(self.rid)
        last = None
        for url in hosts:
            if self.stopped:
                return
            try:
                ws = websocket.create_connection(url, timeout=8, header=["User-Agent: " + UA],
                                                 origin="https://live.bilibili.com")
                break
            except Exception as e:
                last = e
        else:
            raise RuntimeError("B站弹幕服务器连不上：%s" % last)
        self._sock = ws
        ws.settimeout(1.0)
        auth = {"uid": 0, "roomid": int(real), "protover": 3, "buvid": buvid, "platform": "web",
                "type": 2, "key": token}
        ws.send_binary(bili_pack(7, json.dumps(auth).encode(), 1))
        last_hb = time.time()
        try:
            while not self.stopped:
                if time.time() - last_hb > 25:
                    ws.send_binary(bili_pack(2, b"[object Object]", 1))
                    last_hb = time.time()
                try:
                    m = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(m, bytes):
                    continue
                for op, body in bili_unpack(m):
                    if op == 8:
                        if json.loads(body.decode() or "{}").get("code", 0) != 0:
                            raise RuntimeError("B站弹幕认证失败")
                        self._ok()
                    elif op == 5:
                        try:
                            j = json.loads(body.decode("utf-8", "replace"))
                        except Exception:
                            continue
                        if str(j.get("cmd", "")).startswith("DANMU_MSG"):
                            info = j.get("info") or []
                            if len(info) > 1 and isinstance(info[1], str) and info[1]:
                                t = info[1]
                                # 纯表情包占位（如 [xxx_害羞]）没有文字意义，不显示
                                if not re.fullmatch(r"\[[^\]]+\]", t.strip()):
                                    self.on_msg(t)
        finally:
            self._sock = None
            try:
                ws.close()
            except Exception:
                pass


# ====================================================================== 虎牙（Tars 协议）
class TarsW:
    """最小 Tars 编码器：只支持本模块用到的类型。"""

    def __init__(self):
        self.b = bytearray()

    def _head(self, tag, typ):
        if tag < 15:
            self.b.append((tag << 4) | typ)
        else:
            self.b += bytes([0xF0 | typ, tag])

    def int(self, tag, v):
        if v == 0:
            self._head(tag, 12)
        elif -128 <= v < 128:
            self._head(tag, 0)
            self.b += struct.pack(">b", v)
        elif -32768 <= v < 32768:
            self._head(tag, 1)
            self.b += struct.pack(">h", v)
        elif -2 ** 31 <= v < 2 ** 31:
            self._head(tag, 2)
            self.b += struct.pack(">i", v)
        else:
            self._head(tag, 3)
            self.b += struct.pack(">q", v)

    def string(self, tag, s):
        d = s.encode("utf-8")
        if len(d) < 256:
            self._head(tag, 6)
            self.b.append(len(d))
        else:
            self._head(tag, 7)
            self.b += struct.pack(">I", len(d))
        self.b += d

    def bytes(self, tag, d):
        self._head(tag, 13)
        self._head(0, 0)
        self.int(0, len(d))
        self.b += d

    def string_list(self, tag, items):
        self._head(tag, 9)
        self.int(0, len(items))
        for s in items:
            self.string(0, s)


def tars_read(buf, off=0, end=None):
    """通用 Tars 解码：返回 ({tag: value}, 新偏移)。结构体 -> dict，list -> list，simplelist -> bytes。"""
    end = len(buf) if end is None else end
    out = {}
    while off < end:
        h = buf[off]
        typ, tag = h & 15, h >> 4
        off += 1
        if tag == 15:
            tag = buf[off]
            off += 1
        if typ == 11:  # 结构体结束
            return out, off
        val, off = _tars_val(buf, off, typ)
        out[tag] = val
    return out, off


def _tars_val(buf, off, typ):
    if typ == 0:
        return struct.unpack_from(">b", buf, off)[0], off + 1
    if typ == 1:
        return struct.unpack_from(">h", buf, off)[0], off + 2
    if typ == 2:
        return struct.unpack_from(">i", buf, off)[0], off + 4
    if typ == 3:
        return struct.unpack_from(">q", buf, off)[0], off + 8
    if typ == 4:
        return struct.unpack_from(">f", buf, off)[0], off + 4
    if typ == 5:
        return struct.unpack_from(">d", buf, off)[0], off + 8
    if typ == 6:
        n = buf[off]
        return bytes(buf[off + 1:off + 1 + n]), off + 1 + n
    if typ == 7:
        n = struct.unpack_from(">I", buf, off)[0]
        return bytes(buf[off + 4:off + 4 + n]), off + 4 + n
    if typ == 8:  # map
        n, off = _tars_elem(buf, off)
        res = {}
        for _ in range(n):
            k, off = _tars_elem(buf, off)
            v, off = _tars_elem(buf, off)
            res[k if not isinstance(k, (dict, list)) else id(k)] = v
        return res, off
    if typ == 9:  # list
        n, off = _tars_elem(buf, off)
        res = []
        for _ in range(n):
            v, off = _tars_elem(buf, off)
            res.append(v)
        return res, off
    if typ == 10:
        return tars_read(buf, off)
    if typ == 12:
        return 0, off
    if typ == 13:  # simple list
        off += 1  # 元素类型头（byte）
        n, off = _tars_elem(buf, off)
        return bytes(buf[off:off + n]), off + n
    raise ValueError("未知 Tars 类型 %d" % typ)


def _tars_elem(buf, off):
    h = buf[off]
    typ, tag = h & 15, h >> 4
    off += 1
    if tag == 15:
        off += 1
    return _tars_val(buf, off, typ)


def _txt(b):
    return b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else str(b)


def huya_room_info(rid):
    """从房间页取主播 yyid / 频道号 lChannelId / lSubChannelId（订阅弹幕用）。"""
    t = requests.get("https://www.huya.com/" + str(rid), headers={"User-Agent": UA}, timeout=10).text
    vals = []
    for k in ("yyid", "lChannelId", "lSubChannelId"):
        m = re.search(r'"%s"\s*:\s*"?(\d+)' % k, t)
        if not m:
            raise RuntimeError("虎牙房间页里没找到 %s（房间不存在、未开播或页面改版）" % k)
        vals.append(int(m.group(1)))
    return tuple(vals)


class HuyaClient(DanmakuClient):
    platform = "huya"
    URL = "wss://cdnws.api.huya.com"
    HEARTBEAT = bytes.fromhex("00141d000c2c36004c")  # 实测可维持连接的 WebSocketCommand 心跳

    def run_once(self):
        import websocket
        yyid, top, sub = huya_room_info(self.rid)
        ws = websocket.create_connection(self.URL, timeout=8, header=["User-Agent: " + UA],
                                         origin="https://www.huya.com")
        self._sock = ws
        ws.settimeout(1.0)
        # EWSCmd_RegisterReq(1)：主播 yyid + 频道号 + 子频道号
        inner = TarsW()
        inner.int(0, yyid)
        inner.int(1, 1)
        inner.string(2, "")
        inner.string(3, "")
        inner.int(4, top)
        inner.int(5, sub)
        inner.int(6, int(time.time() * 1000))
        inner.int(7, 0)
        cmd = TarsW()
        cmd.int(0, 1)
        cmd.bytes(1, bytes(inner.b))
        ws.send_binary(bytes(cmd.b))
        self._ok()
        last_hb = time.time()
        try:
            while not self.stopped:
                if time.time() - last_hb > 30:
                    ws.send_binary(self.HEARTBEAT)
                    last_hb = time.time()
                try:
                    m = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(m, bytes):
                    continue
                try:
                    self._handle(m)
                except Exception:
                    pass
        finally:
            self._sock = None
            try:
                ws.close()
            except Exception:
                pass

    def _handle(self, data):
        top, _ = tars_read(data)
        if top.get(0) != 7:  # EWSCmdS2C_MsgPushReq
            return
        push, _ = tars_read(top.get(1, b""))
        if push.get(1) != 1400:  # 1400 = MessageNotice（弹幕）
            return
        notice, _ = tars_read(push.get(2, b""))
        txt = _txt(notice.get(3, b""))
        if txt:
            self.on_msg(txt)


CLIENTS = {"douyu": DouyuClient, "huya": HuyaClient, "bili": BiliClient}


# ====================================================================== Win32 小工具
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = (
    0x8, 0x20, 0x80, 0x80000, 0x08000000)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = 0, -1, -2
GW_HWNDPREV = 3

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumProc, wintypes.LPARAM]


def make_click_through(tk_window):
    """给 tk 顶层窗口加：分层 + 鼠标穿透 + 不抢焦点 + 工具窗口（不进任务栏）。"""
    hwnd = user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
    return hwnd


def list_windows(class_names=("PotPlayer64", "PotPlayer")):
    """枚举可见顶层窗口，返回 [(hwnd, pid, class)]，只含指定窗口类。"""
    res = []

    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, buf, 128)
        if buf.value in class_names:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            res.append((hwnd, pid.value, buf.value))
        return True
    user32.EnumWindows(EnumProc(cb), 0)
    return res


def descendant_pids(root_pid):
    """root_pid 及其所有子孙进程的 PID 集合。"""
    pids = {root_pid}
    try:
        import psutil
        for c in psutil.Process(root_pid).children(recursive=True):
            pids.add(c.pid)
    except Exception:
        pass
    return pids


def client_rect(hwnd):
    """窗口客户区在屏幕上的 (x, y, w, h)；失败返回 None。"""
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


# ====================================================================== 悬浮层
KEY = "#010203"  # 透明色键，不会和任何弹幕颜色冲突


class Overlay:
    """透明、置顶（或紧贴 PotPlayer 之上）、点击穿透的弹幕窗口。必须在 tk 主线程里使用。"""

    MAX_ON_SCREEN = 80
    MAX_PENDING = 150

    def __init__(self, tk_root, settings):
        import tkinter as tk
        import tkinter.font as tkfont
        self.tk, self.root = tk, tk_root
        self.s = settings
        self.win = tk.Toplevel(tk_root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg=KEY)
        self.cv = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.win.attributes("-transparentcolor", KEY)
        self.win.attributes("-alpha", float(self.s["dm_alpha"]))
        self.win.geometry("200x100+0+0")
        self.win.update_idletasks()
        self.hwnd = make_click_through(self.win)
        self.font_name = "Microsoft YaHei UI"
        self.tkfont = tkfont
        self._font = None
        self._apply_font()
        self.q = queue.Queue(maxsize=self.MAX_PENDING)
        self.items = []        # [dict(ids, x, w, lane)]
        self.lane_tail = {}    # lane -> 该行最后一条弹幕的右端 x
        self.visible = False
        self.W = self.H = 200
        self._last_t = time.time()
        self._job = None
        self.dropped = 0
        self.topmost = None
        self.win.after(33, self._tick)

    # ---- 外部接口
    def push(self, text):
        """线程安全：队列满就丢弃（限速防卡顿）。"""
        try:
            self.q.put_nowait(text)
        except queue.Full:
            self.dropped += 1

    def apply_settings(self):
        self.win.attributes("-alpha", float(self.s["dm_alpha"]))
        self._apply_font()

    def show(self, rect, above_hwnd=None, topmost=False):
        x, y, w, h = rect
        w, h = max(w, 50), max(h, 50)
        self.W, self.H = w, h
        self.win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        if not self.visible:
            self.win.deiconify()
            self.visible = True
            make_click_through(self.win)
        self._zorder(above_hwnd, topmost)

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def clear(self):
        self.cv.delete("all")
        self.items.clear()
        self.lane_tail.clear()
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass

    # ---- 内部
    def _zorder(self, above_hwnd, topmost):
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        if topmost or above_hwnd is None:
            if self.topmost is not True:
                user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
                self.topmost = True
            return
        # 播放器不是置顶窗口：把悬浮层紧贴在它上面，别的窗口盖住播放器时也盖住弹幕
        if self.topmost is not False:
            user32.SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            self.topmost = False
        prev = user32.GetWindow(above_hwnd, GW_HWNDPREV)
        if prev == self.hwnd:
            return
        user32.SetWindowPos(self.hwnd, prev if prev else HWND_TOP, 0, 0, 0, 0, flags)

    def _apply_font(self):
        size = int(self.s["dm_font"])
        self._font = self.tkfont.Font(family=self.font_name, size=-size, weight="bold")
        self.line_h = int(size * 1.35)

    def _lane_count(self):
        frac = AREA_FRAC.get(self.s["dm_area"], 0.5)
        return max(1, int(self.H * frac // self.line_h))

    def _speed(self):
        # “飘过屏幕用几秒”，所有弹幕同速，避免后面的追上前面的
        return max(2.0, float(self.s["dm_speed"]))

    def _spawn(self, text):
        lanes = self._lane_count()
        order = list(range(lanes))
        # 优先用空闲且靠前的行；该行最后一条弹幕尾部离右边缘有空隙即可
        gap = self.line_h
        for lane in order:
            tail = self.lane_tail.get(lane, -1e9)
            if tail < self.W - gap:
                break
        else:
            return False
        w = self._font.measure(text)
        x = float(self.W)
        y = lane * self.line_h + 2
        ids = []
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            ids.append(self.cv.create_text(x + dx, y + dy, text=text, anchor="nw", font=self._font, fill="#000000"))
        ids.append(self.cv.create_text(x, y, text=text, anchor="nw", font=self._font, fill="#FFFFFF"))
        self.items.append(dict(ids=ids, x=x, w=w, lane=lane))
        self.lane_tail[lane] = x + w
        return True

    def _tick(self):
        try:
            now = time.time()
            dt = min(now - self._last_t, 0.2)
            self._last_t = now
            if self.visible:
                v = self.W / self._speed()
                dx = v * dt
                keep = []
                for it in self.items:
                    it["x"] -= dx
                    for i in it["ids"]:
                        self.cv.move(i, -dx, 0)
                    if it["x"] + it["w"] < -4:
                        for i in it["ids"]:
                            self.cv.delete(i)
                    else:
                        keep.append(it)
                self.items = keep
                for lane in list(self.lane_tail):
                    self.lane_tail[lane] -= dx
                # 每帧最多发 3 条；屏幕上太多就先等
                n = 0
                while n < 3 and len(self.items) < self.MAX_ON_SCREEN:
                    try:
                        text = self.q.get_nowait()
                    except queue.Empty:
                        break
                    if not self._spawn(text[:60]):
                        # 没空行：只保留不太老的弹幕，其余丢弃
                        if self.q.qsize() < 40:
                            try:
                                self.q.put_nowait(text)
                            except queue.Full:
                                pass
                        else:
                            self.dropped += 1
                        break
                    n += 1
            else:
                # 隐藏时队列只保留最近的，避免恢复后一股脑涌出
                while self.q.qsize() > 20:
                    try:
                        self.q.get_nowait()
                    except queue.Empty:
                        break
        except Exception:
            pass
        self.win.after(33, self._tick)


# ====================================================================== 全局快捷键
class HotkeyThread(threading.Thread):
    """独立线程里 RegisterHotKey + 消息循环；按下时调用 callback()。"""
    WM_HOTKEY, WM_QUIT = 0x312, 0x12
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000

    def __init__(self, callback, vk=ord("D")):
        super().__init__(daemon=True, name="hotkey")
        self.cb, self.vk = callback, vk
        self.ok = None
        self.tid = None
        self._ready = threading.Event()

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, 1, self.MOD_CONTROL | self.MOD_ALT | self.MOD_NOREPEAT, self.vk))
        self._ready.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == self.WM_HOTKEY:
                try:
                    self.cb()
                except Exception:
                    pass
        user32.UnregisterHotKey(None, 1)

    def wait_ready(self, t=2):
        self._ready.wait(t)
        return self.ok

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, self.WM_QUIT, 0, 0)


# ====================================================================== 管理器
class DanmakuManager:
    """串起：开关 / 弹幕客户端 / 悬浮层 / 窗口跟随。所有方法都在 tk 主线程里调用。"""

    FOLLOW_MS = 150

    def __init__(self, root, cfg, save_cfg, status=lambda s, c=None: None):
        self.root, self.cfg, self.save_cfg, self.status = root, cfg, save_cfg, status
        for k, v in DEFAULTS.items():
            self.cfg.setdefault(k, v)
        self.overlay = None
        self.client = None
        self.session = None   # dict(platform, rid, proc, pre)
        self.hwnd = None
        self._follow_job = None
        self._lost = 0
        self.hotkey = None
        self.count = 0
        self.last_status = ""
        self._shown_status = ""

    # ---- 状态
    @property
    def enabled(self):
        return bool(self.cfg.get("danmaku_on"))

    def settings(self):
        return self.cfg

    # ---- 快捷键
    def start_hotkey(self, on_toggle):
        """on_toggle 会在热键线程里被调用，需自行转回主线程。"""
        self.hotkey = HotkeyThread(on_toggle)
        self.hotkey.start()
        return self.hotkey.wait_ready()

    # ---- 开关
    def set_enabled(self, v):
        self.cfg["danmaku_on"] = bool(v)
        self.save_cfg()
        self._sync()

    # ---- 会话（播放开始 / 停止）
    def begin(self, platform, rid, proc):
        """开始一次播放：记录会话，若开关已开则连接弹幕。"""
        self.end()
        pre = {h for h, _, _ in list_windows()}
        self.session = dict(platform=platform, rid=rid, proc=proc, pre=pre)
        self.hwnd = None
        self._lost = 0
        self._sync()

    def end(self):
        self.session = None
        self._stop_client()
        if self.overlay:
            self.overlay.hide()
            self.overlay.clear()
        self.hwnd = None
        if self._follow_job:
            self.root.after_cancel(self._follow_job)
            self._follow_job = None

    def shutdown(self):
        self.end()
        if self.hotkey:
            self.hotkey.stop()
        if self.overlay:
            self.overlay.destroy()
            self.overlay = None

    def _stop_client(self):
        c, self.client = self.client, None
        if c:
            c.stop()

    def _sync(self):
        """按“开关 + 是否在播放”启停客户端和悬浮层。"""
        playing = self.session is not None
        if self.enabled and playing:
            plat = self.session["platform"]
            if not SUPPORTED.get(plat):
                self.status("该平台的弹幕暂不支持", None)
                return
            if self.overlay is None:
                self.overlay = Overlay(self.root, self.cfg)
            if self.client is None or not self.client.is_alive():
                self.count = 0
                self.client = CLIENTS[plat](self.session["rid"], self._on_msg, self._on_status)
                self.client.start()
            if self._follow_job is None:
                self._follow()
            self.status("弹幕已开启（Ctrl+Alt+D 开关）", None)
        else:
            self._stop_client()
            if self.overlay:
                self.overlay.hide()
                self.overlay.clear()
            if self._follow_job:
                self.root.after_cancel(self._follow_job)
                self._follow_job = None

    def _on_msg(self, text):  # 客户端线程里调用
        self.count += 1
        ov = self.overlay
        if ov:
            ov.push(text)

    def _on_status(self, s):  # 客户端线程里调用（只记录，由主线程读）
        self.last_status = s

    def apply_settings(self):
        self.save_cfg()
        if self.overlay:
            self.overlay.apply_settings()

    # ---- 窗口跟随
    def _find_window(self):
        s = self.session
        if not s:
            return None
        pids = descendant_pids(s["proc"].pid) if s["proc"] is not None else set()
        wins = list_windows()
        for h, pid, _ in wins:
            if pid in pids:
                return h
        # 兜底：播放开始后新出现的 PotPlayer 窗口（PotPlayer 可能由别的进程转交）
        for h, pid, _ in wins:
            if h not in s["pre"]:
                return h
        return None

    def _follow(self):
        self._follow_job = None
        if not (self.enabled and self.session and self.overlay):
            return
        try:
            if self.last_status != self._shown_status:
                self._shown_status = self.last_status
                self.status(self.last_status, None)
            if self.hwnd is None or not user32.IsWindow(self.hwnd):
                self.hwnd = self._find_window()
            h = self.hwnd
            ok = False
            if h and user32.IsWindowVisible(h) and not user32.IsIconic(h):
                r = client_rect(h)
                if r and r[2] > 0 and r[3] > 0:
                    top = bool(user32.GetWindowLongPtrW(h, GWL_EXSTYLE) & WS_EX_TOPMOST)
                    self.overlay.show(r, h, top)
                    ok = True
            if not ok:
                self.overlay.hide()
        except Exception:
            pass
        self._follow_job = self.root.after(self.FOLLOW_MS, self._follow)
