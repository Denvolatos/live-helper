# -*- coding: utf-8 -*-
"""设置窗口里的“自动续播”开关：默认开、切换后写入配置（用临时配置目录）。"""
import os, sys, tempfile, shutil
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.argv = [os.path.join(here, "app.py")]
import core
core.APPDIR = os.path.join(tempfile.gettempdir(), "lt_settings_test")
core.FAV_FILE = os.path.join(core.APPDIR, "favorites.json")
core.CFG_FILE = os.path.join(core.APPDIR, "config.json")
shutil.rmtree(core.APPDIR, ignore_errors=True)
import app
a = app.App()
a.update()
win = app.DanmakuSettings(a, a.cfg, a.dm, True)
a.update()
ok = []
ok.append(("默认开", bool(win.auto_sw.get()) and a.cfg.get("auto_resume", True)))
win.auto_sw.deselect(); win._auto_resume(); a.update()
ok.append(("关闭后写入配置", core.load_config().get("auto_resume") is False))
win.auto_sw.select(); win._auto_resume(); a.update()
ok.append(("再打开后写入配置", core.load_config().get("auto_resume") is True))
win.destroy(); a.dm.shutdown(); a.destroy()
for n, v in ok:
    print(("PASS " if v else "FAIL ") + n)
sys.exit(0 if all(v for _, v in ok) else 1)
