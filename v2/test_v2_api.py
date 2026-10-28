# -*- coding: utf-8 -*-
"""v2 api 层单元测试（全部假数据，不联网）。运行：python v2/test_v2_api.py
联网实测另见 --live：python v2/test_v2_api.py --live（每个平台各查一次，只打印条数和耗时）。"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api  # noqa: E402


def fake_item(platform, i=0, live=True):
    return dict(platform=platform, name="示例主播%d" % i, rid=str(100 + i), live=live,
                info="示例简介", cate="", avatar="", hot="1.0万")


class FakeBackend:
    """可编程的假后端：fail 里的平台搜索抛异常；delay 控制每个查询词的耗时。"""

    def __init__(self, fail=None, delay=None, lookup_fail=()):
        self.fail = fail or {}
        self.delay = delay or {}
        self.lookup_fail = set(lookup_fail)
        self.calls = []

    def search(self, platform, kw):
        self.calls.append(("search", platform, kw))
        time.sleep(self.delay.get(kw, 0))
        if platform in self.fail:
            raise self.fail[platform]
        return [fake_item(platform, 1, live=False), fake_item(platform, 2, live=True)]

    def lookup(self, platform, rid):
        self.calls.append(("lookup", platform, rid))
        if platform in self.lookup_fail:
            raise RuntimeError("%s房间不存在" % platform)
        return fake_item(platform, 9)


ALL = ["huya", "douyu", "bili"]


class TestRunSearch(unittest.TestCase):
    def test_all_ok_live_first(self):
        r = api.run_search("示例", ALL, FakeBackend())
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["items"]), 6)
        self.assertEqual(r["errors"], {})
        lives = [x["live"] for x in r["items"]]
        self.assertEqual(lives, sorted(lives, reverse=True))  # 在播排前面
        self.assertEqual(r["items"][0]["platform_name"] in ("虎牙", "斗鱼", "B站"), True)

    def test_one_platform_fails_others_ok(self):
        be = FakeBackend(fail={"douyu": RuntimeError("斗鱼搜索被风控（行为存在风险）")})
        r = api.run_search("示例", ALL, be)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["items"]), 4)
        self.assertEqual(list(r["errors"]), ["douyu"])
        self.assertIn("房间号", r["errors"]["douyu"])  # 风控提示建议改用房间号

    def test_all_fail_no_crash(self):
        be = FakeBackend(fail={p: TimeoutError("timed out") for p in ALL})
        r = api.run_search("示例", ALL, be)
        self.assertTrue(r["ok"])
        self.assertEqual(r["items"], [])
        self.assertEqual(set(r["errors"]), set(ALL))
        self.assertIn("超时", r["errors"]["huya"])

    def test_empty_input(self):
        for q in ("", "   ", None):
            r = api.run_search(q, ALL, FakeBackend())
            self.assertFalse(r["ok"])
            self.assertIn("请输入", r["error"])

    def test_no_platform(self):
        r = api.run_search("示例", [], FakeBackend())
        self.assertFalse(r["ok"])
        self.assertIn("平台", r["error"])

    def test_unknown_platform_ignored(self):
        r = api.run_search("示例", ["nope"], FakeBackend())
        self.assertFalse(r["ok"])

    def test_link_only_queries_that_platform(self):
        be = FakeBackend()
        r = api.run_search("https://live.bilibili.com/12345", ["huya"], be)
        self.assertEqual(r["mode"], "link")
        self.assertEqual(r["platforms"], ["bili"])
        self.assertEqual(be.calls, [("lookup", "bili", "12345")])
        self.assertEqual(len(r["items"]), 1)

    def test_link_parsing_all_platforms(self):
        cases = {"https://www.douyu.com/987654": ("douyu", "987654"),
                 "https://www.huya.com/abc_1": ("huya", "abc_1"),
                 "https://live.bilibili.com/h5/555": ("bili", "555")}
        for url, (p, rid) in cases.items():
            be = FakeBackend()
            api.run_search(url, ALL, be)
            self.assertEqual(be.calls, [("lookup", p, rid)], url)

    def test_link_failure_message(self):
        r = api.run_search("https://www.douyu.com/1", ALL, FakeBackend(lookup_fail=["douyu"]))
        self.assertEqual(r["items"], [])
        self.assertIn("没有这个房间", r["errors"]["douyu"])

    def test_room_number_looks_up_and_searches(self):
        be = FakeBackend()
        r = api.run_search("12345", ALL, be)
        self.assertEqual(r["mode"], "room")
        kinds = sorted(c[0] for c in be.calls)
        self.assertEqual(kinds, ["lookup"] * 3 + ["search"] * 3)
        self.assertEqual(len(r["items"]), 3 * 3)

    def test_room_number_missing_on_one_platform_not_an_error(self):
        be = FakeBackend(lookup_fail=["huya"])
        r = api.run_search("12345", ALL, be)
        self.assertEqual(r["errors"], {})

    def test_dedupe_same_room(self):
        class Dup(FakeBackend):
            def search(self, platform, kw):
                return [fake_item(platform, 9)]
        r = api.run_search("12345", ["huya"], Dup())  # lookup 与 search 都返回 rid=109
        self.assertEqual(len(r["items"]), 1)

    def test_platforms_run_in_parallel(self):
        be = FakeBackend(delay={"慢": 0.3})
        t0 = time.time()
        api.run_search("慢", ALL, be)
        self.assertLess(time.time() - t0, 0.7)  # 串行至少 0.9 秒


class TestFriendlyError(unittest.TestCase):
    def test_messages(self):
        f = api.friendly_error
        self.assertIn("风控", f("douyu", RuntimeError("斗鱼搜索被风控（行为存在风险）")))
        self.assertIn("超时", f("huya", TimeoutError("timed out")))
        self.assertIn("检查网络", f("bili", type("ConnectionError", (Exception,), {})("x")))
        self.assertIn("格式不对", f("bili", KeyError("data")))
        self.assertIn("虎牙", f("huya", RuntimeError("")))
        self.assertIn("没有这个房间", f("huya", RuntimeError("虎牙房间不存在")))


class TestApiStale(unittest.TestCase):
    def test_out_of_order_results_dropped(self):
        be = FakeBackend(delay={"旧": 0.4, "新": 0.0})
        a = api.Api(be)
        out = {}
        t = threading.Thread(target=lambda: out.update(old=a.search("旧", ["huya"])))
        t.start()
        time.sleep(0.1)                       # 保证“旧”先发起
        out["new"] = a.search("新", ["huya"])  # “新”先返回
        t.join()
        self.assertTrue(out["old"].get("stale"))
        self.assertNotIn("items", out["old"])
        self.assertEqual(out["new"]["query"], "新")
        self.assertEqual(len(out["new"]["items"]), 2)

    def test_sequential_searches_both_valid(self):
        a = api.Api(FakeBackend())
        r1, r2 = a.search("甲", ["huya"]), a.search("乙", ["huya"])
        self.assertFalse(r1.get("stale"))
        self.assertFalse(r2.get("stale"))
        self.assertEqual((r1["seq"], r2["seq"]), (1, 2))

    def test_rapid_fire_only_last_survives(self):
        a = api.Api(FakeBackend(delay={"x": 0.2}))
        res = [None] * 5

        def go(i):
            res[i] = a.search("x", ["huya", "bili"])
        ts = []
        for i in range(5):
            t = threading.Thread(target=go, args=(i,))
            t.start()
            ts.append(t)
            time.sleep(0.02)
        for t in ts:
            t.join()
        fresh = [r for r in res if not r.get("stale")]
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]["seq"], 5)


class TestDemoBackend(unittest.TestCase):
    def test_demo_no_network_and_failure_modes(self):
        r = api.run_search("游戏", ALL, api.DemoBackend())
        self.assertEqual(len(r["items"]), 9)
        self.assertTrue(all(x["name"].startswith("示例主播") for x in r["items"]))
        r = api.run_search("风控", ALL, api.DemoBackend())
        self.assertIn("douyu", r["errors"])
        self.assertEqual(len(r["items"]), 6)

    def test_public_surface(self):
        pub = [n for n in dir(api.Api) if not n.startswith("_")]
        self.assertEqual(sorted(pub), ["platforms", "search"])


def live():
    """联网实测（不属于单元测试，不写入任何真实结果，只打印条数和耗时）。"""
    be = api.CoreBackend()
    for p in ALL:
        t0 = time.time()
        r = api.run_search("游戏", [p], be)
        print("%s: %d 条, 错误=%s, %.2fs" % (p, len(r["items"]), r["errors"].get(p, "无"), time.time() - t0))
    t0 = time.time()
    r = api.run_search("游戏", ALL, be)
    print("三平台并行: %d 条, 错误=%s, %.2fs" % (len(r["items"]), list(r["errors"]), time.time() - t0))


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
    else:
        unittest.main(verbosity=1)
