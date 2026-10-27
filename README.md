# 🎬 直播助手 LiveHelper

Windows 小工具：搜索虎牙 / 斗鱼 / B 站主播，选中后用 **PotPlayer** 播放直播，并可在 PotPlayer 上叠加**弹幕悬浮层**（带开关）。

> 自己的练手和记录项目（私有仓库）。与各直播平台无关，仅用于个人观看公开直播。

## ✨ 功能
- 🔍 三平台主播搜索（也可直接输入房间号或房间链接）
- ▶️ 用 streamlink 管道播放进 PotPlayer（斗鱼流地址很快过期，管道播放不会断）
- 🎚️ 画质按房间真实档位显示（同一个流被虚标成多个码率的会合并）
- ⭐ 收藏主播，启动时后台刷新是否在播
- 💬 弹幕悬浮层：透明、置顶、点击穿透，跟随 PotPlayer 窗口；播放栏开关，全局快捷键 `Ctrl+Alt+D`
- 🧰 启动时检测 PotPlayer，没有则征得同意后用 winget 安装
- 🌗 浅色 / 深色主题

## 📸 截图
见 `screenshots/`。

## 🚀 使用
- 运行源码：`pip install customtkinter streamlink requests pillow websocket-client brotli psutil`，然后 `python app.py`
- 打包：设置环境变量 `PY` 指向装好依赖和 PyInstaller 的 Python（默认 `%USERPROFILE%\miniconda3\envs\livetool\python.exe`），运行 `release.bat`，会生成 exe 文件夹、zip 和 Inno Setup 安装包（需先装 Inno Setup 6，用 `winget install JRSoftware.InnoSetup`）
- 版本号只在 `version.py` 改，更新记录见 `CHANGELOG.md`

## ⚠️ 已知限制
- 三个平台的弹幕接口都是逆向的，平台改动后可能失效
- PotPlayer 独占全屏时弹幕可能看不到
- 斗鱼搜索接口会风控，频繁搜索会提示"行为存在风险"，可改用房间号
- 没有代码签名，安装时 Windows 会提示"未知发布者"
- 只做 Windows；别人的电脑、杀毒误报、没有 PotPlayer 的机器上的自动安装均未充分验证

## 🧱 依赖
streamlink（BSD-2-Clause）、customtkinter（MIT）、requests、Pillow、websocket-client、brotli、psutil、PyInstaller、Inno Setup。PotPlayer 不随软件分发。

## 📄 许可证
本项目使用 **GNU AGPL-3.0** 许可证，详见 `LICENSE`。Copyright (C) 2026 Denvolatos。

- 可以自由使用、修改、分发；分发（或把修改版作为网络服务提供）时，必须同样以 AGPL-3.0 公开对应源码。
- 与各直播平台、PotPlayer 均无关联；PotPlayer 不随本软件分发。
- 设计上参考过开源项目「纯粹直播 Pure Live」（AGPL-3.0）的整体风格思路，**未复制其代码或图片素材**。
