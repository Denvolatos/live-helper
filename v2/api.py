# -*- coding: utf-8 -*-
"""v2 给前端调用的后端接口。

通用逻辑（搜索、解析、错误文案）都在这里，只依赖 ../core.py，不依赖任何界面库，
所以 Windows / macOS 通用，也能脱离窗口做单元测试。
平台相关的东西（播放器、安装、打包、弹幕悬浮层）不在本文件，将来单独成层。
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import core  # noqa: E402  （v1 的后端，原样复用）

PLATFORMS = core.PLATFORMS  # {"huya": "虎牙", "douyu": "斗鱼", "bili": "B站"}


# ---------------------------------------------------------------- 错误文案
def friendly_error(platform, exc):
    """把各种异常翻成一句用户看得懂的话。"""
    name = PLATFORMS.get(platform, platform)
    text = str(exc)
    cls = type(exc).__name__
    if "风控" in text or "风险" in text:
        return "%s搜索被风控拦住了，请过几分钟再试；或者直接输入房间号 / 粘贴房间链接。" % name
    if "Timeout" in cls or "timed out" in text:
        return "%s连接超时，请检查网络后重试。" % name
    if "ConnectionError" in cls or "Max retries" in text:
        return "%s连不上，请检查网络。" % name
    if "JSON" in cls or "KeyError" in cls or "Expecting value" in text:
        return "%s返回的数据格式不对（可能接口变了或被拦截），稍后重试。" % name
    if "不存在" in text:
        return "%s没有这个房间。" % name
    if text:
        return "%s查询失败：%s" % (name, text[:80])
    return "%s查询失败（%s）。" % (name, cls)


# ---------------------------------------------------------------- 后端实现
class CoreBackend:
    """真实联网：直接调 v1 的 core。"""

    def search(self, platform, kw):
        return core.SEARCHERS[platform](kw)

    def lookup(self, platform, rid):
        return core.lookup_room(platform, rid)


class DemoBackend:
    """假数据，用于截图和演示（`--demo`）。查询词含“风控”时斗鱼报风控，含“超时”时虎牙超时，
    含“慢”时每个平台多等 1.5 秒（用来看加载状态）。"""

    def search(self, platform, kw):
        if "慢" in kw:
            time.sleep(1.5)
        if platform == "douyu" and "风控" in kw:
            raise RuntimeError("斗鱼搜索被风控（行为存在风险），请稍等几分钟重试")
        if platform == "huya" and "超时" in kw:
            raise TimeoutError("timed out")
        if "无结果" in kw:
            return []
        base = {"huya": [("12.3万", True), ("5.7万", True), ("6.6万", False)],
                "douyu": [("8.1万", True), ("2.2万", False), ("15.0万", True)],
                "bili": [("3.4万", True), ("9800", False), ("1.1万", True)]}[platform]
        letters = "ABCDEFGHI"
        out = []
        for i, (hot, live) in enumerate(base):
            n = "示例主播 " + letters["huya douyu bili".split().index(platform) * 3 + i]
            out.append(dict(platform=platform, name=n, rid=str(1000 + i), live=live,
                            info="示例简介 · " + kw, cate="示例分区", avatar="", hot=hot))
        return out

    def lookup(self, platform, rid):
        return dict(platform=platform, name="示例主播 房间" + str(rid), rid=str(rid), live=True,
                    info="按房间号查到的示例房间", cate="", avatar="", hot="")


# ---------------------------------------------------------------- 纯逻辑
def _norm(it):
    return {"platform": it.get("platform", ""),
            "platform_name": PLATFORMS.get(it.get("platform", ""), ""),
            "name": it.get("name") or "未命名",
            "rid": str(it.get("rid", "")),
            "live": bool(it.get("live")),
            "info": it.get("info") or "",
            "cate": it.get("cate") or "",
            "avatar": it.get("avatar") or "",
            "hot": str(it.get("hot") or "")}


def _platform_job(backend, platform, kw, rid_like):
    """单个平台的查询：数字先按房间号查，再按名字搜；两者之一成功就算成功。
    返回 (items, error文案或None)。"""
    items, errs = [], []
    if rid_like:
        try:
            items.append(backend.lookup(platform, kw))
        except Exception as e:  # 房间号在该平台不存在是常态，不当成错误
            if "不存在" not in str(e):
                errs.append(e)
    try:
        items += backend.search(platform, kw)
    except Exception as e:
        errs.append(e)
    if items:
        return items, None
    return [], (friendly_error(platform, errs[0]) if errs else None)


def run_search(query, platforms, backend):
    """执行一次查询，返回前端用的结果字典（不涉及“是否过期”，那是 Api 的事）。"""
    t0 = time.time()
    kw = (query or "").strip()
    if not kw:
        return {"ok": False, "error": "请输入主播名、房间号或房间链接。"}
    parsed = core.parse_input(kw)
    plats = [p for p in (platforms or []) if p in PLATFORMS]
    mode = "name"
    if parsed:
        mode, plats = "link", [parsed[0]]
    elif not plats:
        return {"ok": False, "error": "请至少勾选一个平台。"}
    elif kw.isdigit():
        mode = "room"

    results, errors = {}, {}

    def job(p):
        if mode == "link":
            try:
                return p, [backend.lookup(p, parsed[1])], None
            except Exception as e:
                return p, [], friendly_error(p, e)
        items, err = _platform_job(backend, p, kw, mode == "room")
        return p, items, err

    with ThreadPoolExecutor(max_workers=len(plats)) as ex:
        for p, items, err in ex.map(job, plats):
            results[p] = items
            if err:
                errors[p] = err

    seen, merged = set(), []
    for p in plats:  # 保持平台顺序，再把在播的排前面（稳定排序）
        for it in results[p]:
            n = _norm(it)
            key = (n["platform"], n["rid"])
            if key not in seen:
                seen.add(key)
                merged.append(n)
    merged.sort(key=lambda x: not x["live"])
    return {"ok": True, "mode": mode, "query": kw, "items": merged, "errors": errors,
            "platforms": plats, "ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- 暴露给 JS 的类
class Api:
    """pywebview 的 js_api。每个公开方法都会在 JS 里变成 pywebview.api.方法名()，
    pywebview 在独立线程里调用它们，所以这里不会卡界面。以下划线开头的不暴露。"""

    def __init__(self, backend=None):
        self._backend = backend or CoreBackend()
        self._lock = threading.Lock()
        self._latest = 0

    def search(self, query, platforms):
        with self._lock:
            self._latest += 1
            seq = self._latest
        res = run_search(query, platforms, self._backend)
        with self._lock:
            if seq != self._latest:  # 期间又发起了新搜索：这次结果作废
                return {"ok": True, "stale": True, "seq": seq}
        res["seq"] = seq
        return res

    def platforms(self):
        return dict(PLATFORMS)
