# -*- coding: utf-8 -*-
"""备用更新源（自签证书 + 指纹）的测试：本地起 server/updates_server.py，用临时生成的证书，不联网。"""
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.path.insert(0, os.path.join(here, "server"))
import updater as U
import updates_server as S

res = []


def T(name, cond):
    res.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


tmp = tempfile.mkdtemp(prefix="lt_mirror_")
cert, key = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
try:
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", key,
                    "-out", cert, "-days", "2", "-subj", "/CN=test", "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
except (OSError, subprocess.CalledProcessError):
    print("SKIP 没有 openssl，无法生成测试证书")
    sys.exit(0)
FP = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(cert).read())).hexdigest()

root = os.path.join(tmp, "updates")
os.makedirs(root)
INSTALLER = b"MZ" + os.urandom(60000)
NAME = "LiveHelper-Setup-v1.9.0.exe"
open(os.path.join(root, NAME), "wb").write(INSTALLER)
open(os.path.join(root, "SHA256SUMS.txt"), "w").write("%s  %s\n" % (hashlib.sha256(INSTALLER).hexdigest(), NAME))
open(os.path.join(root, "secret.txt"), "w").write("不该被访问")

srv = S.make_server(root, "127.0.0.1", 0, cert, key, S.Limiter(req_per_min=1000, big_per_hour=1000))
port = srv.server_address[1]
base = "https://127.0.0.1:%d" % port
json.dump({"tag_name": "v1.9.0", "body": "测试说明", "prerelease": False, "draft": False,
           "assets": [{"name": NAME, "browser_download_url": base + "/" + NAME, "size": len(INSTALLER)},
                      {"name": "SHA256SUMS.txt", "browser_download_url": base + "/SHA256SUMS.txt", "size": 80}]},
          open(os.path.join(root, "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def pol(pins=(FP,), api="/latest.json", label="备用源"):
    return U.Policy(api_url=base + api, prefix=base + "/", api_hosts=("127.0.0.1",), redirect_hosts=(), pins=pins, label=label)


r = U.check_latest("1.0.0", pol())
T("指纹对得上：能取到新版本信息", r["status"] == "new" and r["version"] == "1.9.0" and r["source"] == "备用源")
T("安装包和校验文件地址都在备用源前缀内", r["asset"] and r["asset"]["url"].endswith(NAME) and r["asset"]["sums_url"].endswith("SHA256SUMS.txt"))
path, info = U.download_and_verify(r["asset"], r["policy"])
T("下载并校验通过，内容一致", open(path, "rb").read() == INSTALLER)
shutil.rmtree(os.path.dirname(path), ignore_errors=True)
T("返回的结果带着该来源的策略（下载用同一个）", r["policy"].pins == (FP,))

bad = U.check_latest("1.0.0", pol(pins=("00" * 32,)))
T("指纹对不上：拒绝连接并说明原因", bad["status"] == "error" and "指纹不匹配" in bad["reason"])
T("指纹大小写不敏感", U.check_latest("1.0.0", pol(pins=(FP.upper(),)))["status"] == "new")
nopin = U.check_latest("1.0.0", pol(pins=()))
T("不设指纹时按普通证书校验，自签证书被拒", nopin["status"] == "error")

dead = U.Policy(api_url="https://127.0.0.1:1/x", prefix="https://127.0.0.1:1/", api_hosts=("127.0.0.1",), redirect_hosts=(), label="GitHub")
m = U.check_latest_multi([dead, pol()], "1.0.0")
T("GitHub 连不上 → 自动改用备用源", m["status"] == "new" and m["source"] == "备用源")
m2 = U.check_latest_multi([dead, pol(pins=("11" * 32,))], "1.0.0")
T("两个都失败：原因里写明各自的失败", m2["status"] == "error" and "GitHub" in m2["reason"] and "备用源" in m2["reason"])

calls = []
_orig = U.check_latest


def spy(v, p, f=None):
    calls.append(p.label)
    return {"status": "latest", "version": "1.0.0"} if p.label == "GitHub" else _orig(v, p, f)


U.check_latest = spy
mm = U.check_latest_multi([U.Policy(label="GitHub"), pol()], "1.0.0")
U.check_latest = _orig
T("第一个来源能给出结论就不再试备用源", mm["status"] == "latest" and calls == ["GitHub"])
T("没有任何来源", U.check_latest_multi([], "1.0.0")["status"] == "error")

mp = U.mirror_policy()
T("生产备用源策略：https、带指纹、不允许跳转", mp.api_url.startswith("https://") and mp.pins == tuple(U.MIRROR_PINS) and mp.redirect_hosts == ())
T("生产备用源只允许自己的主机和前缀", U.url_allowed("https://%s/LiveHelper-Setup-v1.0.0.exe" % U.MIRROR_HOST, mp)
  and not U.url_allowed("https://evil.example/LiveHelper-Setup-v1.0.0.exe", mp) and not U.url_allowed("http://%s/x" % U.MIRROR_HOST, mp))


def status_of(path, p=None):
    try:
        with U._open(base + path, p or pol(), 5, no_redirect=True) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


T("白名单：未列出的文件不能取", status_of("/secret.txt") == 404)
T("白名单：目录穿越被拒", status_of("/..%2Fsecret.txt") == 404 and status_of("/../etc/passwd") == 404)
T("白名单：不存在的版本号 404", status_of("/LiveHelper-Setup-v9.9.9.exe") == 404)
T("白名单：latest.json 和校验文件正常", status_of("/latest.json") == 200 and status_of("/SHA256SUMS.txt") == 200)

srv.shutdown()
srv2 = S.make_server(root, "127.0.0.1", 0, cert, key, S.Limiter(req_per_min=6, big_per_hour=2))
port = srv2.server_address[1]
base = "https://127.0.0.1:%d" % port
threading.Thread(target=srv2.serve_forever, daemon=True).start()
codes = [status_of("/" + NAME) for _ in range(3)]
T("限流：每小时下载安装包超过 2 次返回 429", codes == [200, 200, 429])
codes = [status_of("/latest.json") for _ in range(5)]
T("限流：每分钟请求超过上限返回 429", 429 in codes)
srv2.shutdown()

shutil.rmtree(tmp, ignore_errors=True)
fails = [n for n, v in res if not v]
print("\n共 %d 项，通过 %d，失败 %d" % (len(res), len(res) - len(fails), len(fails)), flush=True)
sys.exit(1 if fails else 0)
