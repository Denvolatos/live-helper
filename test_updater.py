# -*- coding: utf-8 -*-
"""updater 单元测试 + 本地假服务器测试（不依赖外网，不运行任何安装程序）。"""
import hashlib, http.server, json, os, shutil, sys, tempfile, threading, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import updater as U

res = []


def T(name, cond):
    res.append((name, bool(cond)))


# ------------------------------------------------ 版本比较
T("1.10.0 > 1.9.0", U.is_newer("1.10.0", "1.9.0"))
T("1.9.0 不新于 1.10.0", not U.is_newer("1.9.0", "1.10.0"))
T("v 前缀", U.is_newer("v1.2.0", "1.1.4") and U.parse_version("V1.2.0") == (1, 2, 0))
T("相同版本不算新", not U.is_newer("1.2.0", "1.2.0"))
T("1.2 当作 1.2.0", U.parse_version("1.2") == (1, 2, 0) and not U.is_newer("1.2", "1.2.0"))
for bad in ("", "abc", "1.2.x", "v", "1.2.0-beta", "1..2", None, 5, "1.2.0 && calc"):
    T("非法版本 %r" % (bad,), U.parse_version(bad) is None and not U.is_newer(bad, "1.0.0") and not U.is_newer("2.0.0", bad))

# ------------------------------------------------ 策略 / URL 白名单（生产默认严格）
P = U.Policy()
base = "https://github.com/Denvolatos/live-helper/releases/download/v1.2.0/"
T("允许正确地址", U.url_allowed(base + "LiveHelper-Setup-v1.2.0.exe", P))
T("拒绝 http", not U.url_allowed(base.replace("https", "http") + "a.exe", P))
T("拒绝其他主机", not U.url_allowed("https://evil.example/Denvolatos/live-helper/releases/download/v1/a.exe", P))
T("拒绝其他仓库", not U.url_allowed("https://github.com/other/live-helper/releases/download/v1/a.exe", P))
T("拒绝非 download 路径", not U.url_allowed("https://github.com/Denvolatos/live-helper/archive/main.zip", P))
T("拒绝 .. 穿越", not U.url_allowed("https://github.com/Denvolatos/live-helper/releases/download/../../../evil/a.exe", P))
T("拒绝编码的 ..", not U.url_allowed("https://github.com/Denvolatos/live-helper/releases/download/%2e%2e/x/a.exe", P))
T("拒绝 @ 欺骗", not U.url_allowed("https://github.com@evil.example/Denvolatos/live-helper/releases/download/v1/a.exe", P))
T("拒绝子域欺骗", not U.url_allowed("https://github.com.evil.example/Denvolatos/live-helper/releases/download/v1/a.exe", P))
T("拒绝带端口", not U.url_allowed("https://github.com:8443/Denvolatos/live-helper/releases/download/v1/a.exe", P))
T("跳转白名单：允许 objects", U.redirect_allowed("https://objects.githubusercontent.com/x", P))
T("跳转白名单：允许 release-assets", U.redirect_allowed("https://release-assets.githubusercontent.com/x", P))
T("跳转白名单：拒绝其他/ http", not U.redirect_allowed("https://evil.example/x", P) and not U.redirect_allowed("http://objects.githubusercontent.com/x", P))
T("跳转白名单：拒绝 127.0.0.1（生产）", not U.redirect_allowed("https://127.0.0.1/x", P))
T("仓库常量唯一", U.UPDATE_REPO == "Denvolatos/live-helper" and P.api_url == "https://api.github.com/repos/Denvolatos/live-helper/releases/latest")


def rel(tag="v1.2.0", assets=None, **kw):
    n = "LiveHelper-Setup-%s.exe" % tag
    d = {"tag_name": tag, "body": "更新说明\n第二行", "prerelease": False, "draft": False,
         "assets": assets if assets is not None else [
             {"name": n, "size": 1000, "browser_download_url": base + n},
             {"name": "SHA256SUMS.txt", "size": 100, "browser_download_url": base + "SHA256SUMS.txt"}]}
    d.update(kw)
    return d


# ------------------------------------------------ 挑选 asset
a = U.pick_installer(rel(), "1.2.0", P)
T("挑到安装包", a["name"] == "LiveHelper-Setup-v1.2.0.exe" and a["sums_url"].endswith("SHA256SUMS.txt") and a["size"] == 1000)
try:
    U.pick_installer(rel(assets=[]), "1.2.0", P); T("没有安装包应报错", False)
except U.UpdateError:
    T("没有安装包应报错", True)
bad = rel(); bad["assets"][0]["browser_download_url"] = "https://evil.example/LiveHelper-Setup-v1.2.0.exe"
try:
    U.pick_installer(bad, "1.2.0", P); T("asset 地址不合白名单应拒绝", False)
except U.UpdateError:
    T("asset 地址不合白名单应拒绝", True)
other = rel(assets=[{"name": "LiveHelper-Setup-v1.1.0.exe", "browser_download_url": base + "LiveHelper-Setup-v1.1.0.exe"}])
try:
    U.pick_installer(other, "1.2.0", P); T("版本不符的安装包不选", False)
except U.UpdateError:
    T("版本不符的安装包不选", True)

# ------------------------------------------------ SHA256SUMS 解析
h1, h2 = "a" * 64, "B" * 64
txt = "%s  LiveHelper-Setup-v1.2.0.exe\r\n%s *LiveHelper-v1.2.0-win64.zip\n垃圾行\n" % (h1, h2)
T("解析双空格", U.parse_sums(txt, "LiveHelper-Setup-v1.2.0.exe") == h1)
T("解析 * 且转小写", U.parse_sums(txt, "LiveHelper-v1.2.0-win64.zip") == h2.lower())
T("找不到返回 None", U.parse_sums(txt, "nope.exe") is None and U.parse_sums("", "x") is None)
T("哈希长度不对不认", U.parse_sums("abc  x.exe", "x.exe") is None)

# ------------------------------------------------ check_latest（注入 fetch）
def fx(obj):
    return lambda url: json.dumps(obj).encode("utf-8")

r = U.check_latest("1.1.4", P, fx(rel()))
T("发现新版本", r["status"] == "new" and r["version"] == "1.2.0" and r["asset"]["name"].endswith("v1.2.0.exe") and "第二行" in r["notes"])
T("已是最新", U.check_latest("1.2.0", P, fx(rel()))["status"] == "latest")
T("本地更高：最新", U.check_latest("9.9.9", P, fx(rel()))["status"] == "latest")
T("预发布不提示", U.check_latest("1.0.0", P, fx(rel(prerelease=True)))["status"] == "latest")
T("草稿不提示", U.check_latest("1.0.0", P, fx(rel(draft=True)))["status"] == "latest")
T("tag 非法当无更新", U.check_latest("1.0.0", P, fx(rel(tag="nightly")))["status"] == "latest")
T("本地版本非法当无更新", U.check_latest("dev", P, fx(rel()))["status"] == "latest")
def boom(url): raise OSError("断网")
T("异常静默返回 error", U.check_latest("1.0.0", P, boom)["status"] == "error")
T("JSON 坏了返回 error", U.check_latest("1.0.0", P, lambda u: b"<html>")["status"] == "error")
T("JSON 不是对象返回 error", U.check_latest("1.0.0", P, lambda u: b"[1]")["status"] == "error")
r = U.check_latest("1.1.4", P, fx(rel(assets=[])))
T("新版本但无安装包：有 asset_error", r["status"] == "new" and r["asset"] is None and r["asset_error"])

# ------------------------------------------------ 节流 / 跳过
cfg = {}
T("默认开且从未检查：该检查", U.should_auto_check(cfg, 1000000))
U.mark_checked(cfg, 1000000)
T("1 小时后不检查", not U.should_auto_check(cfg, 1000000 + 3600))
T("23h59m 不检查", not U.should_auto_check(cfg, 1000000 + 24 * 3600 - 60))
T("24h 后检查", U.should_auto_check(cfg, 1000000 + 24 * 3600))
T("时间被调回：重新检查", U.should_auto_check(cfg, 1000000 - 86400))
T("开关关闭不检查", not U.should_auto_check({"update_check": False}, 1000000))
T("脏数据不崩", U.should_auto_check({"update_last_check": "x"}, 1))
new = {"status": "new", "version": "1.2.0"}
c2 = {}
T("未跳过：提示", U.should_notify(new, c2))
U.skip_version(c2, "1.2.0")
T("跳过后同版本不提示", not U.should_notify(new, c2))
T("更高版本仍提示", U.should_notify({"status": "new", "version": "1.2.1"}, c2) and U.should_notify({"status": "new", "version": "1.10.0"}, c2))
T("latest 不提示", not U.should_notify({"status": "latest"}, {}))
T("notes 预览截断", U.notes_preview("\n".join("行%d" % i for i in range(30))).count("\n") == 7 and U.notes_preview("").startswith("（"))

# ------------------------------------------------ 本地假服务器
SC = {}      # 当前场景
INST = os.urandom(5000)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body=b"", ctype="application/octet-stream", extra=None, clen=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body) if clen is None else clen))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path
        port = self.server.server_address[1]
        pre = "http://127.0.0.1:%d/releases/download/v1.2.0/" % port
        if p == "/releases/latest":
            if SC.get("api") == "404":
                return self._send(404, b"{}")
            if SC.get("api") == "slow":
                time.sleep(3); return self._send(200, b"{}")
            n = "LiveHelper-Setup-v1.2.0.exe"
            d = rel(assets=[{"name": n, "size": len(INST), "browser_download_url": pre + n},
                            {"name": "SHA256SUMS.txt", "size": 100, "browser_download_url": pre + "SHA256SUMS.txt"}])
            return self._send(200, json.dumps(d).encode(), "application/json")
        if p.endswith("/SHA256SUMS.txt"):
            if SC.get("sums") == "missing":
                return self._send(404)
            good = hashlib.sha256(INST).hexdigest()
            h = ("0" * 64) if SC.get("sums") == "bad" else good
            body = ("%s  LiveHelper-Setup-v1.2.0.exe\n" % h).encode()
            if SC.get("sums") == "noentry":
                body = ("%s  other.exe\n" % good).encode()
            return self._send(200, body, "text/plain")
        if p.endswith("/LiveHelper-Setup-v1.2.0.exe"):
            m = SC.get("dl")
            if m == "404": return self._send(404)
            if m == "redirect_evil": return self._send(302, b"", extra={"Location": "http://evil.invalid/x.exe"})
            if m == "redirect_ok": return self._send(302, b"", extra={"Location": "http://127.0.0.1:%d/cdn/file" % port})
            if m == "cut":
                self.send_response(200); self.send_header("Content-Length", str(len(INST))); self.end_headers()
                self.wfile.write(INST[:2000]); self.wfile.flush(); self.close_connection = True; return
            if m == "stall":
                self.send_response(200); self.send_header("Content-Length", str(len(INST))); self.end_headers()
                self.wfile.write(INST[:1000]); self.wfile.flush(); time.sleep(3); return
            return self._send(200, INST)
        if p == "/cdn/file":
            return self._send(200, INST)
        self._send(404)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
LP = U.Policy(api_url="http://127.0.0.1:%d/releases/latest" % port,
              prefix="http://127.0.0.1:%d/releases/download/" % port,
              api_hosts=("127.0.0.1",), redirect_hosts=("127.0.0.1",), allow_http=True)
TMP = tempfile.mkdtemp(prefix="lh_updtest_")
U.CHECK_TIMEOUT = 1
U.DOWNLOAD_TIMEOUT = 1


def leftover():
    return [x for x in os.listdir(TMP)]


def run_update():
    r = U.check_latest("1.1.4", LP)
    assert r["status"] == "new", r
    return U.download_and_verify(r["asset"], LP, tmp_root=TMP)


SC.clear()
r = U.check_latest("1.1.4", LP)
T("假服务器：发现新版本", r["status"] == "new" and r["version"] == "1.2.0")
prog = []
path, info = U.download_and_verify(r["asset"], LP, progress=lambda a, b: prog.append((a, b)), tmp_root=TMP)
T("哈希一致：成功且文件存在", os.path.isfile(path) and open(path, "rb").read() == INST and info["sha256"] == hashlib.sha256(INST).hexdigest())
T("进度回调到 100%", prog and prog[-1] == (len(INST), len(INST)))
T("文件名取自版本号", os.path.basename(path) == "LiveHelper-Setup-v1.2.0.exe")
shutil.rmtree(os.path.dirname(path))
T("成功后无需清理即为空", leftover() == [])


def expect_fail(name, sc, keyword):
    SC.clear(); SC.update(sc)
    try:
        run_update(); T(name + "（应失败）", False)
    except U.UpdateError as e:
        T(name + "：报错含“%s”且无残留文件" % keyword, keyword in str(e) and leftover() == [])
    except Exception as e:
        T(name + "：抛了非 UpdateError %r" % e, False)


expect_fail("哈希不一致", {"sums": "bad"}, "不一致")
expect_fail("校验文件缺失(404)", {"sums": "missing"}, "校验文件")
expect_fail("校验文件无该条目", {"sums": "noentry"}, "没有")
expect_fail("安装包 404", {"dl": "404"}, "404")
expect_fail("下载中断", {"dl": "cut"}, "中断")
expect_fail("下载停滞(读超时，表现为不完整)", {"dl": "stall"}, "中断")
expect_fail("跳转到非白名单主机", {"dl": "redirect_evil"}, "不受信任")

SC.clear(); SC["dl"] = "redirect_ok"
path, info = run_update()
T("白名单内跳转可通过并记录跳转主机", info["hops"] == ["127.0.0.1"] and info["final_host"] == "127.0.0.1")
shutil.rmtree(os.path.dirname(path))

SC.clear(); SC["api"] = "404"
T("接口 404：error 且含 404", U.check_latest("1.1.4", LP)["status"] == "error" and "404" in U.check_latest("1.1.4", LP)["reason"])
SC.clear(); SC["api"] = "slow"
t0 = time.time(); r = U.check_latest("1.1.4", LP)
T("接口超时：error 且不卡死", r["status"] == "error" and time.time() - t0 < 2.9 and "超时" in r["reason"])
# 生产策略不会去连本地服务器
T("生产策略拒绝本地 API", U.check_latest("1.1.4", U.Policy(api_url="http://127.0.0.1:%d/releases/latest" % port))["status"] == "error")
SC.clear()
T("生产策略拒绝本地下载地址", not U.url_allowed("http://127.0.0.1:%d/releases/download/v1.2.0/a.exe" % port, U.Policy()))
# 下载函数自身也拒绝不合白名单地址
try:
    U.download_file("https://evil.example/a.exe", os.path.join(TMP, "x"), U.Policy()); T("download_file 拒绝坏地址", False)
except U.UpdateError:
    T("download_file 拒绝坏地址", True)

# 启动安装程序可注入：这里只验证注入点存在，不运行任何东西
launched = []
T("launch_installer 可被注入替换", callable(U.launch_installer) and (launched.append(1) or True))
shutil.rmtree(TMP, ignore_errors=True)
srv.shutdown()

bad = [n for n, ok in res if not ok]
for n, ok in res:
    print(("PASS " if ok else "FAIL ") + n)
print("共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(bad), len(bad)))
sys.exit(1 if bad else 0)
