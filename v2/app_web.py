# -*- coding: utf-8 -*-
"""v2 入口：python v2/app_web.py [--demo]
用 pywebview 开一个窗口（Windows 上是系统自带的 WebView2），界面在 web/ 下，后端接口在 api.py。
--demo：不联网，用假数据（截图/演示用）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import webview  # noqa: E402

from api import Api, CoreBackend, DemoBackend  # noqa: E402


def create_window(demo=False, title="直播助手"):
    api = Api(DemoBackend() if demo else CoreBackend())
    return webview.create_window(
        title + (" · 演示模式" if demo else ""),
        url=os.path.join(HERE, "web", "index.html"),
        js_api=api, width=1100, height=720, min_size=(760, 520))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    create_window(demo="--demo" in argv or os.environ.get("LIVEHELPER_DEMO") == "1")
    webview.start()


if __name__ == "__main__":
    main()
