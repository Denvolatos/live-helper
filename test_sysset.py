# -*- coding: utf-8 -*-
"""sysset.py 的单元测试：设置校验、开机自启（用测试专用名，不碰真实启动项）、窗口位置、备份、缓存、单实例、托盘。"""
import json
import os
import shutil
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import core
import danmaku
import sysset

res = []


def check(name, cond):
    res.append((name, bool(cond)))


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


tmp = tempfile.mkdtemp(prefix="lt_sysset_")

# ---- 设置校验
check("默认值全部通过校验", all(_ok for _ok in (sysset.clean_value(k, v) == v for k, v in sysset.SETTING_DEFAULTS.items())))
check("包含弹幕默认值（开关本身除外）", all(k in sysset.SETTING_DEFAULTS for k in danmaku.DEFAULTS if k != "danmaku_on")
      and "danmaku_on" not in sysset.SETTING_DEFAULTS)
check("非法选项被拒", raises(lambda: sysset.clean_value("close_action", "boom"), ValueError))
check("越界滑块被拒", raises(lambda: sysset.clean_value("dm_font", 999), ValueError))
check("布尔不能给字符串", raises(lambda: sysset.clean_value("auto_resume", "yes"), ValueError))
check("布尔不能当数字用", raises(lambda: sysset.clean_value("dm_font", True), ValueError))
check("平台列表去掉未知项并保序", sysset.clean_value("default_platforms", ["bili", "x", "huya"]) == ["huya", "bili"])
check("平台列表不能为空", raises(lambda: sysset.clean_value("default_platforms", ["x"]), ValueError))
check("透明度保留两位", sysset.clean_value("dm_alpha", 0.5555) == 0.56)
cfg = {"potplayer": "C:/p.exe", "theme": "dark", "dm_font": 40, "update_skip": "9.9.9", "default_platforms": ["huya"]}
sysset.restore_defaults(cfg)
check("恢复默认改回设置项", cfg["theme"] == "light" and cfg["dm_font"] == 28 and cfg["default_platforms"] == ["huya", "douyu", "bili"])
check("恢复默认不动路径和更新跳过", cfg["potplayer"] == "C:/p.exe" and cfg["update_skip"] == "9.9.9")
cfg["default_platforms"].append("x")
check("默认值不被共享引用污染", sysset.SETTING_DEFAULTS["default_platforms"] == ["huya", "douyu", "bili"])

# ---- 开机自启（测试专用名）
NAME = "LiveHelperTest_%d" % os.getpid()
try:
    check("自启初始为关", sysset.autostart_state(NAME) == "off")
    sysset.autostart_set(True, NAME, '"C:\\x\\LiveHelper.exe" --autostart')
    check("打开后为开", sysset.autostart_state(NAME) == "on")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sysset.RUN_KEY) as k:
        check("写入的命令正确", winreg.QueryValueEx(k, NAME)[0] == '"C:\\x\\LiveHelper.exe" --autostart')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sysset.APPROVED_KEY) as k:
        winreg.SetValueEx(k, NAME, 0, winreg.REG_BINARY, bytes([3] + [0] * 11))
    check("被系统禁用识别为 blocked", sysset.autostart_state(NAME) == "blocked")
    sysset.autostart_set(True, NAME, '"C:\\x\\LiveHelper.exe" --autostart')
    check("重新打开会清掉禁用标记", sysset.autostart_state(NAME) == "on")
    sysset.autostart_set(False, NAME)
    check("关闭后为关", sysset.autostart_state(NAME) == "off")
    sysset.autostart_set(False, NAME)
    check("重复关闭不报错", True)
finally:
    try:
        sysset.autostart_set(False, NAME)
    except Exception:
        pass
check("开发环境下自启不可用", not sysset.autostart_available())
check("命令里带自启标记", "--autostart" in (lambda: (setattr(sys, "frozen", True), setattr(sys, "executable", "C:\\a b\\LiveHelper.exe"),
                                                       sysset.autostart_command())[-1])() and sys.executable == "C:\\a b\\LiveHelper.exe")
del sys.frozen

# ---- 窗口位置
check("解析并还原", sysset.parse_geom("960x640+100+50") == (960, 640, 100, 50) and sysset.format_geom(960, 640, 100, 50) == "960x640+100+50")
check("负坐标（副屏在左）两种写法都能解析", sysset.parse_geom("960x640+-1200+30") == (960, 640, -1200, 30)
      and sysset.parse_geom("960x640-1200+30") == (960, 640, -1200, 30) and sysset.parse_geom("960x640+100+-20") == (960, 640, 100, -20))
import tkinter as _tk
_r = _tk.Tk(); _r.geometry(sysset.format_geom(300, 200, -1200, 30)); _r.update()
check("Tk 读回的负坐标可解析", sysset.parse_geom(_r.geometry()) == (300, 200, -1200, 30)); _r.destroy()
check("乱码解析为 None", sysset.parse_geom("abc") is None and sysset.parse_geom("") is None and sysset.parse_geom(None) is None)
scr = (0, 0, 1920, 1080)
check("在屏幕内保持不变", sysset.fit_geom((960, 640, 100, 50), 1.0, scr) == (960, 640, 100, 50))
check("整个跑出屏幕返回 None", sysset.fit_geom((960, 640, 5000, 50), 1.0, scr) is None)
check("只露出一点点也算跑出", sysset.fit_geom((960, 640, 1900, 50), 1.0, scr) is None)
check("标题栏在屏幕下方算跑出", sysset.fit_geom((960, 640, 100, 1070), 1.0, scr) is None)
check("副屏在左（负坐标）可用", sysset.fit_geom((960, 640, -1200, 50), 1.0, (-1920, 0, 3840, 1080)) == (960, 640, -1200, 50))
check("窗口比屏幕大会缩小", sysset.fit_geom((2400, 1500, 0, 0), 1.0, scr) == (1920, 1080, 0, 0))
check("缩放后尺寸按物理像素算", sysset.fit_geom((1500, 700, 0, 0), 1.5, scr) == (1280, 700, 0, 0))
check("部分伸出屏幕但标题栏可见则保留", sysset.fit_geom((960, 640, 1000, 0), 1.5, scr) == (960, 640, 1000, 0))
check("太小会抬到最小尺寸", sysset.fit_geom((300, 200, 10, 10), 1.0, scr) == (760, 520, 10, 10))
sx, sy, sw, sh = sysset.virtual_screen()
check("能读到真实屏幕大小", sw > 0 and sh > 0)

# ---- 备份
favs = [{"platform": "huya", "name": "甲", "rid": "123", "avatar": "u", "cate": "c", "live": True},
        {"platform": "huya", "name": "重复", "rid": "123"},
        {"platform": "bad", "name": "坏平台", "rid": "1"},
        {"platform": "douyu", "name": "乙", "rid": 456},
        "junk", {"platform": "bili", "rid": ""}]
cl = sysset.clean_favorites(favs)
check("收藏清洗：去重/去坏/rid转字符串", [(f["platform"], f["rid"]) for f in cl] == [("huya", "123"), ("douyu", "456")])
cfg2 = dict(theme="dark", dm_font=40, potplayer="C:/secret/p.exe", update_skip="1.2.3", win_geom="1x1+0+0", quality="x")
bk = sysset.make_backup(cfg2, favs, "1.3.0")
check("备份不含路径/窗口位置/更新记录", set(bk["settings"]) == {"theme", "dm_font"} and "potplayer" not in json.dumps(bk))
p = os.path.join(tmp, "b.json")
sysset.write_backup(p, bk)
back = sysset.read_backup(p)
check("备份往返一致", back["settings"] == {"theme": "dark", "dm_font": 40} and len(back["favorites"]) == 2 and back["skipped"] == 0)
bad = dict(bk, settings={"theme": "purple", "dm_font": 40, "evil": 1, "dm_alpha": 5})
json.dump(bad, open(p, "w", encoding="utf-8"))
b2 = sysset.read_backup(p)
check("非法值被丢弃并计数，未知键忽略", b2["settings"] == {"dm_font": 40} and b2["skipped"] == 2)
open(p, "w", encoding="utf-8").write("not json")
check("坏文件报 BackupError", raises(lambda: sysset.read_backup(p), sysset.BackupError))
json.dump({"kind": "other"}, open(p, "w"))
check("别的 JSON 报 BackupError", raises(lambda: sysset.read_backup(p), sysset.BackupError))
check("文件不存在报 BackupError", raises(lambda: sysset.read_backup(os.path.join(tmp, "nope.json")), sysset.BackupError))
open(p, "wb").write(b"x" * (2 * 1024 * 1024 + 1))
check("过大文件被拒", raises(lambda: sysset.read_backup(p), sysset.BackupError))
cur = [{"platform": "huya", "rid": "123", "name": "本地", "avatar": "", "cate": "", "live": False}]
merged, added = sysset.merge_favorites(cur, cl)
check("合并：保留本地、只补缺的", added == 1 and merged[0]["name"] == "本地" and len(merged) == 2)

# ---- 缓存
core.AVATAR_DIR = os.path.join(tmp, "avatars")
os.makedirs(core.AVATAR_DIR)
for i in range(3):
    open(os.path.join(core.AVATAR_DIR, "a%d.img" % i), "wb").write(b"x" * 2048)
open(os.path.join(core.AVATAR_DIR, "keep.txt"), "wb").write(b"k")
check("缓存统计", sysset.cache_info() == (3, 6144))
check("清理返回数量", sysset.clear_cache() == (3, 6144))
check("清理后为空且不碰别的文件", sysset.cache_info() == (0, 0) and os.path.isfile(os.path.join(core.AVATAR_DIR, "keep.txt")))
core.AVATAR_DIR = os.path.join(tmp, "missing")
check("目录不存在时不报错", sysset.cache_info() == (0, 0) and sysset.clear_cache() == (0, 0))
check("大小显示", sysset.human_size(100) == "1 KB" and sysset.human_size(5 * 1048576) == "5.0 MB")

# ---- 单实例
mx, ev = "Local\\LiveHelperTest.M%d" % os.getpid(), "Local\\LiveHelperTest.E%d" % os.getpid()
first, h1 = sysset.acquire_single_instance(mx)
second, h2 = sysset.acquire_single_instance(mx)
check("第一次拿到、第二次拿不到", first and not second)
check("没人监听时通知失败", sysset.signal_existing(ev) is False)
got = []
w = sysset.ShowWatcher(lambda: got.append(1), ev)
check("通知成功", sysset.signal_existing(ev) is True)
t0 = time.time()
while not got and time.time() - t0 < 3:
    time.sleep(0.05)
check("监听线程收到信号", len(got) == 1)
w.stop()

# ---- 托盘（会在系统托盘闪现约 1 秒）
fired = []
tray = sysset.Tray("测试", os.path.join(here, "icon.ico"), lambda: fired.append("show"), lambda: fired.append("exit"))
check("托盘初始不可见", not tray.visible)
ok = tray.show()
time.sleep(1.0)
check("托盘显示成功", ok and tray.visible)
check("重复 show 不新建", tray.show() is True)
tray.hide()
check("隐藏后不可见且可再次隐藏", not tray.visible and (tray.hide() or True))
bad_tray = sysset.Tray("x", os.path.join(tmp, "no.ico"), lambda: None, lambda: None)
check("图标文件缺失时返回 False 而不崩", bad_tray.show() is False and not bad_tray.visible)

shutil.rmtree(tmp, ignore_errors=True)
for n, v in res:
    print(("PASS " if v else "FAIL ") + n)
print("%d/%d" % (sum(v for _, v in res), len(res)))
sys.exit(0 if all(v for _, v in res) else 1)
