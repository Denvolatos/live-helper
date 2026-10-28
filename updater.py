# -*- coding: utf-8 -*-
"""应用内更新：检查 GitHub Release（连不上时改用我们自己的服务器）、下载安装包并校验 SHA256。

只用标准库。所有网络函数都应在后台线程调用（本模块不碰界面）。
安全约束（见 docs/VERIFICATION.md 的“更新功能”一节）：
  - 只从 https://github.com/<UPDATE_REPO>/releases/download/ 前缀下载；
  - 重定向的每一跳都校验：必须 https 且主机在 GitHub 自家下载域白名单内；
  - 不内嵌任何 token；是否下载由界面层在用户点击并确认后才调用；
  - SHA256 取自同一个 Release 的 SHA256SUMS.txt，只能防传输损坏，防不了仓库被入侵；
  - 备用源（我们自己的服务器）用自签证书，不走证书链，而是把证书的 SHA256 指纹写死在下面的 MIRROR_PINS 里严格比对。
"""
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from version import __version__

UPDATE_REPO = "Denvolatos/live-helper"          # 更新地址只在这里写一次
MIRROR_HOST = "43.103.50.235:8443"             # 备用源：我们自己的服务器（server/updates_server.py）
MIRROR_PINS = ("40f5cd7a5bf4cb928fbf2425976369e25b8ed71ab31afc0d0121d4cd6d263f51",)   # 服务器证书（整张 DER）的 SHA256；换证书时加一个新指纹随新版发布
CHECK_TIMEOUT = 8                               # 检查更新的超时（秒）
DOWNLOAD_TIMEOUT = 20                           # 下载时每次读取的超时（秒）
CHECK_INTERVAL = 24 * 3600                      # 自动检查最短间隔
SUMS_NAME = "SHA256SUMS.txt"
MAX_SUMS_BYTES = 1024 * 1024
MAX_INSTALLER_BYTES = 500 * 1024 * 1024
MAX_REDIRECTS = 5

LOG_PATH = None                                 # 由 app 设置；None 则不写文件


def _log(msg):
    """记录失败原因等（静默，不影响主程序）。"""
    if not LOG_PATH:
        return
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 100 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


class UpdateError(Exception):
    """带中文原因的更新错误，原因可直接显示给用户。"""


class Policy:
    """下载/接口地址的安全策略。默认（生产）严格；测试时注入本地地址。"""

    def __init__(self, repo=UPDATE_REPO, api_url=None, prefix=None, api_hosts=("api.github.com",),
                 redirect_hosts=("github.com", "objects.githubusercontent.com",
                                 "release-assets.githubusercontent.com"),
                 allow_http=False, pins=(), label="GitHub"):
        self.label = label
        self.pins = tuple(str(x).lower() for x in pins)
        self.repo = repo
        self.api_url = api_url or "https://api.github.com/repos/%s/releases/latest" % repo
        self.prefix = prefix or "https://github.com/%s/releases/download/" % repo
        self.api_hosts = tuple(h.lower() for h in api_hosts)
        self.redirect_hosts = tuple(h.lower() for h in redirect_hosts)
        self.allow_http = allow_http


def mirror_policy():
    """备用源：只信任指纹对得上的那台服务器；不允许任何跳转。"""
    return Policy(api_url="https://%s/latest.json" % MIRROR_HOST, prefix="https://%s/" % MIRROR_HOST,
                  api_hosts=(MIRROR_HOST.split(":")[0],), redirect_hosts=(), pins=MIRROR_PINS, label="备用源")


# ---------------------------------------------------------------- 版本
def parse_version(s):
    """'v1.10.0' -> (1,10,0)；解析不了（含预发布后缀、空、非字符串）返回 None。"""
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"[vV]?(\d{1,6}(?:\.\d{1,6}){0,3})", s.strip())
    if not m:
        return None
    parts = [int(x) for x in m.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote, local):
    """remote 比 local 新才返回 True；任一边解析不了返回 False。"""
    a, b = parse_version(remote), parse_version(local)
    if a is None or b is None:
        return False
    return a > b


def norm_version(s):
    v = parse_version(s)
    return ".".join(str(x) for x in v) if v else None


# ---------------------------------------------------------------- 地址白名单
def _has_dotdot(path):
    p = urllib.parse.unquote(urllib.parse.unquote(path))
    return ".." in p.replace("\\", "/").split("/") or "\\" in p


def url_allowed(url, policy):
    """下载地址必须以策略前缀开头（同协议、同主机端口、路径前缀），不含用户信息和 ..。"""
    try:
        u = urllib.parse.urlsplit(url)
        p = urllib.parse.urlsplit(policy.prefix)
    except Exception:
        return False
    if u.scheme != p.scheme or (u.scheme == "http" and not policy.allow_http) or u.scheme not in ("https", "http"):
        return False
    if u.username or u.password or "@" in u.netloc:
        return False
    if u.netloc.lower() != p.netloc.lower():
        return False
    if not u.path.startswith(p.path) or _has_dotdot(u.path):
        return False
    return True


def redirect_allowed(url, policy):
    try:
        u = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if u.scheme != "https" and not (u.scheme == "http" and policy.allow_http):
        return False
    if u.username or u.password:
        return False
    return (u.hostname or "").lower() in policy.redirect_hosts


# ---------------------------------------------------------------- HTTP（校验每一跳）
class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self, policy, hops, strict_none=False):
        self.policy, self.hops, self.strict_none = policy, hops, strict_none

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.strict_none:
            raise UpdateError("接口地址发生跳转，已拒绝")
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        if not redirect_allowed(newurl, self.policy):
            raise UpdateError("下载被跳转到不受信任的地址（%s），已拒绝" %
                              (urllib.parse.urlsplit(newurl).hostname or "未知"))
        self.hops.append((urllib.parse.urlsplit(newurl).hostname or "").lower())
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """不验证证书链，改为握手后严格比对服务器证书的 SHA256 指纹；对不上就断开。"""

    def __init__(self, pins):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        super().__init__(context=ctx)
        self.pins = tuple(pins)

    def https_open(self, req):
        pins = self.pins

        class Conn(http.client.HTTPSConnection):
            def connect(self):
                super().connect()
                der = self.sock.getpeercert(binary_form=True) or b""
                if hashlib.sha256(der).hexdigest() not in pins:
                    self.close()
                    raise UpdateError("服务器证书指纹不匹配，已拒绝连接")
        return self.do_open(Conn, req, context=self._context)


def _open(url, policy, timeout, no_redirect=False, hops=None):
    hops = hops if hops is not None else []
    handlers = [_Redirect(policy, hops, no_redirect)]
    if policy.pins:
        handlers.append(_PinnedHTTPSHandler(policy.pins))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "LiveHelper/%s" % __version__,
                                               "Accept": "application/vnd.github+json, application/octet-stream, */*"})
    return opener.open(req, timeout=timeout)


def _explain(e):
    if isinstance(e, UpdateError):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        return "服务器返回 %s" % e.code
    if isinstance(e, urllib.error.URLError):
        r = e.reason
        if isinstance(r, UpdateError):
            return str(r)
        return "网络连接失败（%s）" % (r,)
    if isinstance(e, (TimeoutError,)) or "timed out" in str(e):
        return "连接超时"
    return "%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------- 检查
def pick_installer(release, version, policy):
    """从 release 的 assets 里挑 LiveHelper-Setup-v<version>.exe 与 SHA256SUMS.txt。
    返回 dict(name,url,size,sums_url)；找不到或地址不合白名单抛 UpdateError。"""
    name = "LiveHelper-Setup-v%s.exe" % version
    assets = release.get("assets") or []
    inst = sums = None
    for a in assets:
        if not isinstance(a, dict):
            continue
        if a.get("name") == name:
            inst = a
        elif a.get("name") == SUMS_NAME:
            sums = a
    if inst is None:
        raise UpdateError("新版本里没有找到安装包 %s" % name)
    url = inst.get("browser_download_url") or ""
    if not url_allowed(url, policy):
        raise UpdateError("安装包地址不在允许的来源内，已拒绝")
    sums_url = (sums or {}).get("browser_download_url") or ""
    if sums_url and not url_allowed(sums_url, policy):
        raise UpdateError("校验文件地址不在允许的来源内，已拒绝")
    size = inst.get("size")
    return {"name": name, "url": url, "size": size if isinstance(size, int) and size > 0 else None,
            "sums_url": sums_url or None}


def check_latest(local_version=None, policy=None, fetch=None):
    """查询最新 release 并和本地版本比较。永不抛异常，返回：
      {"status": "latest"|"new"|"error", "version": "x.y.z", "tag":..., "notes":..., "asset":{...}, "reason":...}
    fetch(url)->bytes 可注入（测试）；默认走 urllib。"""
    local_version = local_version or __version__
    policy = policy or Policy()
    try:
        if fetch:
            raw = fetch(policy.api_url)
        else:
            if urllib.parse.urlsplit(policy.api_url).hostname not in policy.api_hosts:
                raise UpdateError("接口主机不在允许范围内")
            with _open(policy.api_url, policy, CHECK_TIMEOUT, no_redirect=True) as r:
                raw = r.read(2 * 1024 * 1024)
        rel = json.loads(raw.decode("utf-8"))
        if not isinstance(rel, dict):
            raise UpdateError("接口返回内容异常")
    except Exception as e:
        reason = _explain(e)
        _log("检查更新失败: %s" % reason)
        return {"status": "error", "reason": reason}
    if rel.get("prerelease") or rel.get("draft"):
        _log("最新 release 是预发布/草稿，忽略")
        return {"status": "latest", "reason": "预发布不提示"}
    tag = rel.get("tag_name")
    ver = norm_version(tag)
    if ver is None or parse_version(local_version) is None:
        _log("版本号解析不了: tag=%r local=%r" % (tag, local_version))
        return {"status": "latest", "reason": "版本号无法比较"}
    if not is_newer(ver, local_version):
        return {"status": "latest", "version": ver}
    notes = rel.get("body") if isinstance(rel.get("body"), str) else ""
    try:
        asset = pick_installer(rel, ver, policy)
        err = None
    except UpdateError as e:
        asset, err = None, str(e)
        _log("发现新版本 %s 但无法更新: %s" % (ver, err))
    return {"status": "new", "version": ver, "tag": tag, "notes": notes, "asset": asset, "asset_error": err,
            "policy": policy, "source": policy.label}


def check_latest_multi(policies, local_version=None, fetch=None):
    """按顺序尝试多个来源（先 GitHub，再备用源）：第一个能给出结论（已是最新/有新版）的就用它；
    全部失败才返回错误，原因里写明每个来源各自怎么失败的。"""
    errors = []
    for pol in policies:
        r = check_latest(local_version, pol, fetch)
        if r["status"] != "error":
            r.setdefault("policy", pol)
            r.setdefault("source", pol.label)
            return r
        errors.append("%s：%s" % (pol.label, r.get("reason", "未知原因")))
    return {"status": "error", "reason": "；".join(errors) or "没有可用的更新来源"}


# ---------------------------------------------------------------- 每日一次 / 跳过版本
def should_auto_check(cfg, now=None):
    if not cfg.get("update_check", True):
        return False
    now = time.time() if now is None else now
    last = cfg.get("update_last_check", 0)
    if not isinstance(last, (int, float)):
        return True
    if last > now + 3600:          # 时间被调回过：当作没检查过
        return True
    return now - last >= CHECK_INTERVAL


def mark_checked(cfg, now=None):
    cfg["update_last_check"] = time.time() if now is None else now


def should_notify(result, cfg):
    """发现新版本且没被用户跳过才提示。"""
    if result.get("status") != "new":
        return False
    return norm_version(cfg.get("update_skip", "")) != result.get("version")


def skip_version(cfg, version):
    cfg["update_skip"] = version


def notes_preview(notes, max_lines=8, max_chars=700):
    lines = [l.rstrip() for l in (notes or "").replace("\r", "").split("\n")]
    lines = [l for l in lines if l.strip()]
    text = "\n".join(lines[:max_lines])
    if len(lines) > max_lines or len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …"
    return text or "（这个版本没有写更新说明）"


# ---------------------------------------------------------------- SHA256SUMS
def parse_sums(text, filename):
    """支持 'hash  name' 与 'hash *name'；找不到返回 None。"""
    for line in (text or "").splitlines():
        m = re.fullmatch(r"\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*", line)
        if m and m.group(2) == filename:
            return m.group(1).lower()
    return None


# ---------------------------------------------------------------- 下载 + 校验
def download_file(url, dest, policy, progress=None, expected_size=None, timeout=DOWNLOAD_TIMEOUT, cancel=None):
    """下载到 dest，返回 {"sha256","size","final_host","hops"}。失败抛 UpdateError（不留半截文件由调用方清理）。"""
    if not url_allowed(url, policy):
        raise UpdateError("下载地址不在允许的来源内，已拒绝")
    hops = []
    h = hashlib.sha256()
    total = got = 0
    try:
        with _open(url, policy, timeout, hops=hops) as r:
            final = urllib.parse.urlsplit(r.geturl())
            # 最终地址必须在跳转白名单内；备用源（带指纹的）没有跳转，最终地址就是它自己前缀下的地址
            if not (redirect_allowed(r.geturl(), policy) or (policy.pins and url_allowed(r.geturl(), policy))):
                raise UpdateError("最终下载地址不受信任（%s），已拒绝" % final.hostname)
            cl = r.headers.get("Content-Length")
            total = int(cl) if cl and cl.isdigit() else (expected_size or 0)
            if total > MAX_INSTALLER_BYTES:
                raise UpdateError("文件大小异常，已拒绝")
            with open(dest, "wb") as f:
                while True:
                    if cancel and cancel():
                        raise UpdateError("已取消")
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if got > MAX_INSTALLER_BYTES:
                        raise UpdateError("文件大小异常，已拒绝")
                    if progress:
                        progress(got, total)
            if total and got != total:
                raise UpdateError("下载中断（收到 %d / %d 字节）" % (got, total))
            if expected_size and got != expected_size:
                raise UpdateError("文件大小与发布信息不符（%d / %d 字节）" % (got, expected_size))
            if got == 0:
                raise UpdateError("下载到的文件是空的")
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError("下载失败：" + _explain(e))
    return {"sha256": h.hexdigest(), "size": got, "final_host": final.hostname, "hops": hops}


def fetch_sums_text(url, policy):
    if not url:
        raise UpdateError("这个版本没有发布 %s，无法校验，已拒绝更新" % SUMS_NAME)
    if not url_allowed(url, policy):
        raise UpdateError("校验文件地址不在允许的来源内，已拒绝")
    try:
        with _open(url, policy, CHECK_TIMEOUT * 2) as r:
            if not (redirect_allowed(r.geturl(), policy) or (policy.pins and url_allowed(r.geturl(), policy))):
                raise UpdateError("校验文件最终地址不受信任，已拒绝")
            raw = r.read(MAX_SUMS_BYTES + 1)
        if len(raw) > MAX_SUMS_BYTES:
            raise UpdateError("校验文件过大，已拒绝")
        return raw.decode("utf-8-sig", errors="replace")
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError("下载校验文件失败：" + _explain(e))


def download_and_verify(asset, policy=None, progress=None, tmp_root=None, cancel=None):
    """下载安装包 -> 下载 SHA256SUMS.txt -> 比对。一致返回安装包路径；
    任何失败都会删除已下载文件并抛 UpdateError。"""
    policy = policy or Policy()
    d = tempfile.mkdtemp(prefix="LiveHelper-update-", dir=tmp_root)
    dest = os.path.join(d, asset["name"])          # 文件名取自我们按版本号拼出的名字，不取自服务器
    try:
        info = download_file(asset["url"], dest, policy, progress, asset.get("size"), cancel=cancel)
        want = parse_sums(fetch_sums_text(asset.get("sums_url"), policy), asset["name"])
        if not want:
            raise UpdateError("校验文件里没有 %s 的哈希，已拒绝更新" % asset["name"])
        if want != info["sha256"]:
            raise UpdateError("SHA256 校验不一致，文件已删除，没有运行任何东西")
        _log("下载校验通过 %s %d 字节 经 %s" % (asset["name"], info["size"], ",".join(info["hops"]) or "直连"))
        return dest, info
    except BaseException as e:
        shutil.rmtree(d, ignore_errors=True)
        if not isinstance(e, UpdateError):
            if isinstance(e, Exception):
                e = UpdateError("更新失败：" + _explain(e))
        _log("更新失败: %s" % e)
        raise e


def launch_installer(path):
    """启动安装程序（独立进程，不继承本程序句柄）。安装向导正常显示，由用户完成。"""
    flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path], close_fds=True, creationflags=flags if sys.platform == "win32" else 0)
