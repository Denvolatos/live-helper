# -*- coding: utf-8 -*-
"""发版时把安装包同步到更新服务器（备用更新源）。

用法：python server/publish_update.py <安装包路径> [--notes 更新说明文件] [--verify]
会做：算 SHA256 → 生成 latest.json（格式仿 GitHub 的 releases/latest）和 SHA256SUMS.txt → 用 scp 上传
（先传安装包、最后才传 latest.json，保证 latest.json 永远不会指向不存在的文件）→ 只保留最新两个版本的安装包
→ 用软件里同一套"指纹比对"代码从外面读回来确认（加 --verify 还会完整下载并校验一次）。
需要本机有 ~/.ssh/livehelper_server 这把专用钥匙（私钥永远不进仓库）。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))

HOST = "admin@43.103.50.235"
REMOTE_DIR = "/var/lib/livehelper-updates"
KEY = os.path.expanduser("~/.ssh/livehelper_server")
NAME_RE = re.compile(r"^LiveHelper-Setup-v(\d{1,3}\.\d{1,3}\.\d{1,3})\.exe$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_release_json(version, notes, size, base, sums_size):
    name = "LiveHelper-Setup-v%s.exe" % version
    return {"tag_name": "v" + version, "name": "v" + version, "body": notes[:6000], "prerelease": False, "draft": False,
            "assets": [{"name": name, "browser_download_url": "%s/%s" % (base, name), "size": size},
                       {"name": "SHA256SUMS.txt", "browser_download_url": base + "/SHA256SUMS.txt", "size": sums_size}]}


def sums_line(digest, name):
    return "%s  %s\n" % (digest, name)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("命令失败：%s\n%s" % (" ".join(cmd[:3]), (r.stderr or r.stdout).strip()[:400]))
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("installer")
    ap.add_argument("--notes", help="更新说明文本文件（utf-8）")
    ap.add_argument("--verify", action="store_true", help="上传后完整下载并校验一次")
    args = ap.parse_args()
    name = os.path.basename(args.installer)
    m = NAME_RE.match(name)
    if not m or not os.path.isfile(args.installer):
        raise SystemExit("安装包文件名必须形如 LiveHelper-Setup-v1.4.0.exe 且文件存在")
    version = m.group(1)
    import updater
    base = "https://" + updater.MIRROR_HOST
    digest, size = sha256_file(args.installer), os.path.getsize(args.installer)
    notes = open(args.notes, encoding="utf-8").read() if args.notes else ""
    sums = sums_line(digest, name)
    stage = os.path.join(os.environ.get("TEMP", "."), "lt_publish_stage")
    os.makedirs(stage, exist_ok=True)
    sums_path, json_path = os.path.join(stage, "SHA256SUMS.txt"), os.path.join(stage, "latest.json")
    open(sums_path, "w", encoding="utf-8", newline="\n").write(sums)
    json.dump(build_release_json(version, notes, size, base, len(sums.encode())), open(json_path, "w", encoding="utf-8"), ensure_ascii=False)
    ssh = ["-i", KEY, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=20"]
    print("上传安装包 %s（%.1f MB）…" % (name, size / 1048576.0))
    run(["scp"] + ssh + [args.installer, "%s:%s/%s.part" % (HOST, REMOTE_DIR, name)])
    run(["ssh"] + ssh + [HOST, "mv -f %s/%s.part %s/%s && chmod 644 %s/%s" % (REMOTE_DIR, name, REMOTE_DIR, name, REMOTE_DIR, name)])
    print("上传校验文件和版本信息…")
    run(["scp"] + ssh + [sums_path, "%s:%s/SHA256SUMS.txt" % (HOST, REMOTE_DIR)])
    run(["scp"] + ssh + [json_path, "%s:%s/latest.json" % (HOST, REMOTE_DIR)])
    run(["ssh"] + ssh + [HOST, "chmod 644 %s/latest.json %s/SHA256SUMS.txt; cd %s && ls -1t LiveHelper-Setup-v*.exe | tail -n +3 | xargs -r rm -f" % (REMOTE_DIR, REMOTE_DIR, REMOTE_DIR)])
    print("从外面读回来验证（走软件里同一套指纹比对）…")
    r = updater.check_latest("0.0.1", updater.mirror_policy())
    if r["status"] != "new" or r["version"] != version:
        raise SystemExit("读回的版本不对：%s" % r)
    if args.verify:
        path, info = updater.download_and_verify(r["asset"], r["policy"])
        os.remove(path)
        print("完整下载并校验通过（%d 字节）" % info["size"])
    print("完成：备用源现在提供 v%s" % version)


if __name__ == "__main__":
    main()
