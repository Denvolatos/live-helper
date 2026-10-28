# -*- coding: utf-8 -*-
"""更新横幅/设置开关的界面测试：本地假服务器 + 注入的确认/启动函数，不弹模态框、不运行任何安装程序。
窗口只短暂出现；用临时配置目录。"""
import hashlib, http.server, json, os, shutil, sys, tempfile, threading, time
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.argv = [os.path.join(here, "app.py")]
import core
core.APPDIR = os.path.join(tempfile.gettempdir(), "lt_updui_test")
core.FAV_FILE = os.path.join(core.APPDIR, "favorites.json")
core.CFG_FILE = os.path.join(core.APPDIR, "config.json")
core.AVATAR_DIR = os.path.join(core.APPDIR, "avatars")
shutil.rmtree(core.APPDIR, ignore_errors=True)
os.makedirs(core.APPDIR)
core.save_config({"update_check_seed": 1})          # 不写 update_check：验证默认开
import updater

INST = os.urandom(4000)
S = {"hits": {"latest": 0, "dl": 0, "sums": 0}, "sums": "good"}
BODY = "第一行更新说明\n第二行\n第三行"


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/octet-stream"):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_address[1]
        pre = "http://127.0.0.1:%d/releases/download/v9.9.9/" % port
        n = "LiveHelper-Setup-v9.9.9.exe"
        if self.path == "/releases/latest":
            S["hits"]["latest"] += 1
            d = {"tag_name": "v9.9.9", "body": BODY, "prerelease": False, "draft": False, "assets": [
                {"name": n, "size": len(INST), "browser_download_url": pre + n},
                {"name": "SHA256SUMS.txt", "browser_download_url": pre + "SHA256SUMS.txt"}]}
            return self._send(200, json.dumps(d).encode(), "application/json")
        if self.path.endswith("SHA256SUMS.txt"):
            S["hits"]["sums"] += 1
            h = hashlib.sha256(INST).hexdigest() if S["sums"] == "good" else "0" * 64
            return self._send(200, ("%s  %s\n" % (h, n)).encode())
        if self.path.endswith(n):
            S["hits"]["dl"] += 1
            return self._send(200, INST)
        self._send(404, b"")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
LP = updater.Policy(api_url="http://127.0.0.1:%d/releases/latest" % port,
                    prefix="http://127.0.0.1:%d/releases/download/" % port,
                    api_hosts=("127.0.0.1",), redirect_hosts=("127.0.0.1",), allow_http=True)

import app
res = []


def T(n, c):
    res.append((n, bool(c)))


a = app.App()
a.update_policy = LP
a.update_mirror = None            # 测试里不连真实的备用源
a.after_cancel  # (自动检查定时器 4 秒后触发；本测试 4 秒内结束，且下面显式控制)
conf, launched, quits = [], [], []
a.update_confirm = lambda t, m: (conf.append((t, m)), True)[1]
a.update_launch = lambda p: launched.append((p, os.path.isfile(p), open(p, "rb").read() if os.path.isfile(p) else None))
a.update_quit = lambda: quits.append(1)


def wait(cond, t=6.0):
    t0 = time.time()
    while time.time() - t0 < t:
        a.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def shown():
    a.update()
    return bool(a.upd_banner.winfo_ismapped())


a.update()
T("启动时横幅不显示", not shown())
win = app.SettingsWindow(a, "关于")
a.update()
usw = win.switches["update_check"]
T("设置：启动时检查更新默认开", bool(usw.get()))
usw.toggle(); a.update()
T("设置：关闭后写入配置", core.load_config().get("update_check") is False)
T("关闭后不自动检查", not updater.should_auto_check(a.cfg))
usw.toggle(); a.update()
T("设置：再打开后写入配置", core.load_config().get("update_check") is True)

# 手动检查：结果文字 + 横幅（不受每天一次限制）
a.cfg["update_last_check"] = time.time()           # 假装刚自动检查过
win._upd_check()
T("手动检查：结果文字显示发现新版本", wait(lambda: "发现新版本 v9.9.9" in win.upd_lbl.cget("text")))
T("手动检查：横幅出现", shown() and "9.9.9" in a.upd_text.cget("text"))
n1 = S["hits"]["latest"]
a.hide_update_banner(); a.update()
T("✕ 关闭横幅", not shown())
# 自动检查受节流
a.cfg["update_last_check"] = time.time()
a.auto_check_update(); wait(lambda: False, 0.4)
T("每天一次：刚检查过则不再请求", S["hits"]["latest"] == n1 and not shown())
a.cfg["update_last_check"] = time.time() - 90000
a.auto_check_update()
T("自动检查（超过一天）：横幅出现", wait(shown) and S["hits"]["latest"] == n1 + 1)
T("自动检查记录了检查时间", time.time() - core.load_config().get("update_last_check", 0) < 10)
# 更新说明展开/收起
T("说明默认收起", not a.upd_notes.winfo_ismapped())
a.toggle_update_notes(); a.update()
T("点更新说明展开且含正文", a.upd_notes.winfo_ismapped() and "第二行" in a.upd_notes.cget("text"))
shot = os.path.join(here, "screenshots", "09-update-banner.png")
try:
    from PIL import ImageGrab
    x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
    ImageGrab.grab((x, y, x + w, y + 140)).save(shot)
except Exception as e:
    print("截图跳过:", e)
a.toggle_update_notes(); a.update()
T("再点收起", not a.upd_notes.winfo_ismapped())

# 跳过此版本
a.skip_update(); a.update()
T("跳过：横幅消失并写入配置", not shown() and core.load_config().get("update_skip") == "9.9.9")
a.cfg["update_last_check"] = time.time() - 90000
a.auto_check_update(); wait(lambda: False, 0.6)
T("跳过后自动检查不再提示", not shown())
win._upd_check()
T("跳过后手动检查仍显示结果与横幅", wait(lambda: shown()) and "发现新版本" in win.upd_lbl.cget("text"))

# 立即更新：取消 -> 不下载
dl0 = S["hits"]["dl"]
a.update_confirm = lambda t, m: (conf.append((t, m)), False)[1]
a.start_update(); wait(lambda: False, 0.4)
T("确认框点取消：不下载", S["hits"]["dl"] == dl0 and not launched)
T("确认框内容含文件名/来源/校验说明", conf and "LiveHelper-Setup-v9.9.9.exe" in conf[0][1] and "127.0.0.1" in conf[0][1] and "校验" in conf[0][1] and "关闭" in conf[0][1])
# 哈希不一致 -> 失败、不启动
S["sums"] = "bad"
a.update_confirm = lambda t, m: True
a.start_update()
T("哈希不一致：横幅提示失败", wait(lambda: "不一致" in a.upd_text.cget("text")))
T("哈希不一致：没有启动安装程序", not launched and not quits)
T("失败后按钮变为重试且可再点", a.upd_btn_go.cget("text") == "重试" and not a.upd_busy)
# 成功
S["sums"] = "good"
a.start_update()
T("哈希一致：启动安装程序(注入)并请求退出", wait(lambda: launched and quits, 8))
T("启动时文件存在且内容正确", launched and launched[0][1] and launched[0][2] == INST)
T("文件名正确", launched and os.path.basename(launched[0][0]) == "LiveHelper-Setup-v9.9.9.exe")
if launched:
    shutil.rmtree(os.path.dirname(launched[0][0]), ignore_errors=True)

win.destroy(); a.dm.shutdown(); a.destroy()
srv.shutdown()
shutil.rmtree(core.APPDIR, ignore_errors=True)
bad = [n for n, ok in res if not ok]
for n, ok in res:
    print(("PASS " if ok else "FAIL ") + n)
print("共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(bad), len(bad)))
sys.exit(1 if bad else 0)
