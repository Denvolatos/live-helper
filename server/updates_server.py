# -*- coding: utf-8 -*-
"""LatoMedia 更新文件服务（HTTPS，只用 Python 自带的库）。

只提供三类文件（别的路径一律 404）：
  /latest.json                      最新版本信息（格式仿 GitHub 的 releases/latest）
  /SHA256SUMS.txt                   校验值
  /LiveHelper-Setup-vX.Y.Z.exe      安装包
用自签证书；客户端不靠证书链，而是把证书的 SHA256 指纹写死在软件里比对。
带限流：每个来源每分钟最多 30 次请求，每小时最多下载 4 次安装包，防止被刷流量。

环境变量：UPDATES_DIR 文件目录（默认 ./updates）、PORT（默认 8443）、BIND、TLS_CERT、TLS_KEY
（TLS_KEY 缺省时读 systemd 凭据 $CREDENTIALS_DIRECTORY/tls.key）。
"""
import os
import re
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = re.compile(r"^/(latest\.json|SHA256SUMS\.txt|LiveHelper-Setup-v\d{1,3}\.\d{1,3}\.\d{1,3}\.exe)$")
REQ_PER_MIN = 30
BIG_PER_HOUR = 4
CHUNK = 64 * 1024


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


class Limiter:
    def __init__(self, req_per_min=REQ_PER_MIN, big_per_hour=BIG_PER_HOUR):
        self.req_per_min, self.big_per_hour = req_per_min, big_per_hour
        self.req, self.big, self.lock = {}, {}, threading.Lock()

    @staticmethod
    def _take(table, ip, window, limit, now):
        q = [t for t in table.get(ip, []) if now - t < window]
        ok = len(q) < limit
        if ok:
            q.append(now)
        table[ip] = q
        if len(table) > 5000:
            for k in [k for k, v in table.items() if not v or now - v[-1] >= window]:
                del table[k]
        return ok

    def allow(self, ip, big=False, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if not self._take(self.req, ip, 60, self.req_per_min, now):
                return False
            return self._take(self.big, ip, 3600, self.big_per_hour, now) if big else True


def content_type(name):
    return "application/json; charset=utf-8" if name.endswith(".json") else \
        "text/plain; charset=utf-8" if name.endswith(".txt") else "application/octet-stream"


def make_handler(root, limiter):
    root = os.path.realpath(root)

    class H(BaseHTTPRequestHandler):
        timeout = 30                              # 防止慢速连接一直占着线程
        server_version = "LatoMediaUpdates"
        sys_version = ""

        def log_message(self, *a):
            pass

        def _plain(self, code, text):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if not ALLOWED.match(path):
                return self._plain(404, "not found")
            name = path[1:]
            big = name.endswith(".exe")
            if not limiter.allow(self.client_address[0], big):
                return self._plain(429, "too many requests")
            full = os.path.realpath(os.path.join(root, name))
            if os.path.dirname(full) != root or not os.path.isfile(full):
                return self._plain(404, "not found")
            size = os.path.getsize(full)
            self.send_response(200)
            self.send_header("Content-Type", content_type(name))
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                with open(full, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        self.wfile.write(b)
            except (BrokenPipeError, ConnectionError, TimeoutError, ssl.SSLError, OSError):
                pass
    return H


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):      # 探测器、非 TLS 连接造成的握手错误不打印堆栈
        pass


def make_server(root, host, port, cert, key, limiter=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    srv = QuietServer((host, port), make_handler(root, limiter or Limiter()))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    return srv


def main():
    root = os.environ.get("UPDATES_DIR", "./updates")
    cert = os.environ.get("TLS_CERT", "/etc/livehelper/tls/server.crt")
    key = os.environ.get("TLS_KEY") or os.path.join(os.environ.get("CREDENTIALS_DIRECTORY", "."), "tls.key")
    if not (os.path.isdir(root) and os.path.isfile(cert) and os.path.isfile(key)):
        log("缺少文件目录或证书/私钥，退出")
        sys.exit(2)
    srv = make_server(root, os.environ.get("BIND", "0.0.0.0"), int(os.environ.get("PORT", "8443")), cert, key)
    log("开始监听 %s:%s，文件目录 %s" % (srv.server_address[0], srv.server_address[1], root))
    srv.serve_forever()


if __name__ == "__main__":
    main()
