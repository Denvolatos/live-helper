# -*- coding: utf-8 -*-
"""赛事数据（不含界面）：从我们自己的服务器读取瓦 / CS / LOL 的赛程和比分，转成本地时间，并做本地缓存。
只保留显示要用的字段、不使用服务器给的任何网址，所以即使收到异常内容也只会显示成文字。"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

import core

DEFAULT_API = "http://43.103.50.235:8080"          # 我们的赛事数据服务器（server/matches_relay.py）
GAMES = (("lol", "LOL"), ("csgo", "CS"), ("valorant", "瓦"))
GAME_IDS = tuple(g for g, _ in GAMES)
KINDS = (("running", "正在进行"), ("upcoming", "即将开始"), ("past", "刚结束"))
SHOW_LIMIT = {"running": 20, "upcoming": 20, "past": 10}
WEEK = "一二三四五六日"
MAX_BYTES = 2 * 1024 * 1024


class MatchError(Exception):
    pass


def cache_path():
    return os.path.join(core.APPDIR, "matches_cache.json")


def _s(v, n=60):
    return str(v).strip()[:n] if v not in (None, "") else ""


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def clean_match(m):
    """把服务器给的一场比赛整理成显示用的固定格式；坏数据返回 None。"""
    if not isinstance(m, dict) or m.get("status") not in ("running", "not_started", "finished", "canceled", "postponed", None):
        return None
    opps = []
    for o in (m.get("opponents") or [])[:2]:
        o = o if isinstance(o, dict) else {}
        opps.append({"id": _int(o.get("id")), "name": _s(o.get("name") or o.get("acronym"), 40), "score": _int(o.get("score"))})
    return {"id": _int(m.get("id")), "status": m.get("status") or "not_started", "scheduled_at": _s(m.get("scheduled_at"), 40),
            "begin_at": _s(m.get("begin_at"), 40), "best_of": _int(m.get("best_of")), "league": _s(m.get("league"), 40),
            "serie": _s(m.get("serie"), 50), "tournament": _s(m.get("tournament"), 40), "opponents": opps,
            "winner_id": _int(m.get("winner_id"))}


def clean_game(d, game):
    if not isinstance(d, dict):
        raise MatchError("赛事服务器返回了看不懂的内容")
    out = {"game": game, "fetched_at": _s(d.get("fetched_at"), 40)}
    for kind, _ in KINDS:
        items = d.get(kind)
        out[kind] = [x for x in (clean_match(m) for m in (items if isinstance(items, list) else [])[:50]) if x]
    return out


def fetch_game(game, base=DEFAULT_API, timeout=8):
    """读取一款游戏的比赛；连不上或内容异常抛 MatchError（中文提示）。"""
    if game not in GAME_IDS:
        raise MatchError("不支持的游戏")
    if not str(base).startswith(("http://", "https://")):
        raise MatchError("赛事服务器地址不对")
    req = urllib.request.Request("%s/matches/%s" % (str(base).rstrip("/"), game), headers={"User-Agent": "LiveHelper-matches"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise MatchError("赛事服务器出错了（HTTP %s）" % e.code)
    except (urllib.error.URLError, OSError):
        raise MatchError("连不上赛事服务器，请检查网络")
    if len(raw) > MAX_BYTES:
        raise MatchError("赛事服务器返回的内容太大")
    try:
        return clean_game(json.loads(raw.decode("utf-8")), game)
    except (ValueError, UnicodeDecodeError):
        raise MatchError("赛事服务器返回了看不懂的内容")


def load_cache():
    try:
        with open(cache_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return {g: clean_game(d[g], g) for g in GAME_IDS if isinstance(d.get(g), dict)}
    except (OSError, ValueError, MatchError):
        return {}


def save_cache(cache):
    try:
        os.makedirs(core.APPDIR, exist_ok=True)
        tmp = cache_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, cache_path())
    except OSError:
        pass


def local_time(iso):
    """ISO 时间（带 Z）-> 本机时区的 datetime；不认识返回 None。"""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def when(iso, now=None):
    """-> (钟点 '21:00', 日期 '今天' / '明天' / '10-28 周三')；时间未定返回 ('待定', '')。"""
    t = local_time(iso)
    if t is None:
        return "待定", ""
    now = (now or datetime.now().astimezone()).astimezone(t.tzinfo)
    days = (t.date() - now.date()).days
    day = {0: "今天", 1: "明天", -1: "昨天"}.get(days) or "%s 周%s" % (t.strftime("%m-%d"), WEEK[t.weekday()])
    return t.strftime("%H:%M"), day


def team_names(m):
    names = [o["name"] or "待定" for o in m["opponents"]]
    while len(names) < 2:
        names.append("待定")
    return names


def score_text(m):
    sc = [o["score"] for o in m["opponents"]]
    if len(sc) < 2 or all(s is None for s in sc) or m["status"] == "not_started":
        return ""
    return "%s : %s" % tuple("-" if s is None else s for s in sc[:2])


def winner_index(m):
    for i, o in enumerate(m["opponents"][:2]):
        if m["winner_id"] is not None and o["id"] == m["winner_id"]:
            return i
    return None


def status_text(m):
    return {"running": "进行中", "not_started": "未开始", "finished": "已结束", "canceled": "已取消", "postponed": "已延期"}.get(m["status"], "")


def info_line(m):
    bits = [b for b in (m["league"], m["serie"] if m["serie"] != m["league"] else "") if b]
    if m["best_of"]:
        bits.append("BO%d" % m["best_of"])
    return " · ".join(bits)


def sections(game_data):
    """按“正在进行 / 即将开始 / 刚结束”分组并限制数量；返回 [(标题, [比赛...])]，没有比赛的组不返回。"""
    out = []
    for kind, title in KINDS:
        items = ((game_data or {}).get(kind) or [])[:SHOW_LIMIT[kind]]
        if items:
            out.append((title, items))
    return out


def age_text(fetched_at):
    t = local_time(fetched_at)
    if t is None:
        return ""
    return "更新于 " + t.strftime("%H:%M")
