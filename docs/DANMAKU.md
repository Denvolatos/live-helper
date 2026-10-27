# 💬 弹幕：协议笔记与渲染

> 三个平台的弹幕接口都是**逆向得到的**，不是官方文档公开的接口，平台改动后随时可能失效。下面记录的是 2026-10-27 在作者的电脑（海外网络环境）上用真实直播间验证过的做法。

## 一、接收弹幕

### 斗鱼
- STT 文本协议：`loginreq` → `joingroup`（gid=-9999）→ 收 `chatmsg`，每 40 秒发一次 `mrkl` 心跳。
- 官方的 `wss://danmuproxy.douyu.com:8506/` 在作者的网络里 TLS 握手被拒（DNS 解析到了海外节点）；**同一协议走裸 TCP `danmu.douyu.com:8601` 可用**，所以程序先走 TCP 8601，失败再试 wss 8506（wss 备用路径未验证）。
- 实测房间：某个在播的公开直播间（号码略）。

### B 站
- 先访问 `bilibili.com` 取 `buvid3` → 请求 `x/web-interface/nav` 取 wbi 的 key → 用 **wbi 签名**请求 `xlive/web-room/v1/index/getDanmuInfo`（不签名会返回 -352）→ 得到 token 和服务器列表。
- 连接 wss `/sub`，认证包 op=7（匿名 uid=0，protover=3），心跳 op=2 每 25 秒。包体 protover 3 用 brotli、2 用 zlib 压缩；取 `DANMU_MSG` 的 `info[1]` 作为弹幕文字，纯表情占位（如 `[xxx_xxx]`）会被过滤。
- 匿名连接时发送者昵称被屏蔽，只显示文字。
- 实测房间：某个在播的公开直播间（号码略）。

### 虎牙
- 从房间页取 `yyid`、`lChannelId`、`lSubChannelId` → 连 `wss://cdnws.api.huya.com` → 发 Tars 的 `WebSocketCommand`（iCmdType=1，带 yyid 与频道号）→ 每 30 秒一次心跳 → 收 cmd=7 的 `WSPushMessage`，`iUri=1400` 是 `MessageNotice`，其中 `sContent` 就是弹幕。
- 走过的弯路：用 cmd=16 按 `live:/chat:yyid` 分组订阅，能连上（会收到 cmd=17 回执）但收不到 1400 弹幕，所以改用 yyid 加频道号注册。
- 主播未开播时房间页里没有 `lChannelId`，客户端会报错并退避重试。
- 实测房间：某个在播的公开直播间（号码略）。

## 二、渲染（v1.1.1 起）

v1.1.0 用 Tk Canvas + 抠色透明，实测问题：

- 动画 `after(33)` 被 Windows 取整成 3×15.6ms，实际约 21 帧每秒，每帧位移很大，同屏 100 条时占满一个 CPU 核；
- ClearType 字体渲染在抠色背景上有彩边（灰底截屏里约 28% 的非背景像素带蓝橙色）。

v1.1.1 改为自建 Win32 分层窗口：

- 窗口样式 `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`，点击穿透、不抢焦点；
- 用 Pillow 把每条弹幕预渲染成带描边的预乘 alpha 精灵（微软雅黑粗体，描边宽度约为字号的 1/14），直接写 DIB 内存，`UpdateLayeredWindow` 逐像素 alpha 提交，`DwmFlush` 对齐显示器刷新；
- 位置按"起点 − 速度 × 动画时钟"计算，每帧只取整一次；刷新率高于 165Hz 时隔帧绘制；
- 选行在空闲行里随机，速度按字数小幅差异（±8%），并用"追不上前一条"的判断防止重叠；
- 没有用 numpy，打包体积不变。

实测对比（1920×1080 全屏假弹幕，作者显示器 200Hz）：

| 同屏条数 | 旧：帧间隔均值 / CPU | 新：帧间隔均值 / CPU |
|---|---|---|
| 30 | 46.5 ms / 40% | 10.0 ms / 17% |
| 60 | 48.2 ms / 74% | 10.0 ms / 18% |
| 100 | 48.4 ms / 97% | 10.0 ms / 18% |

彩边对比截图：新 [`dm_fringe_new_layered.png`](img/dm_fringe_new_layered.png)、旧 [`dm_fringe_old_tk.png`](img/dm_fringe_old_tk.png)。"舒不舒服"是主观感受，上面的数据无法替代你自己的目视判断。

旧的 Tk 画法保留为设置里的"兼容（旧）"，新渲染建不起来时会自动回退。

## 三、跟随 PotPlayer 与快捷键

- 找到本程序拉起的那个 PotPlayer 窗口，约每 60ms 读一次位置和大小来同步悬浮层；PotPlayer 最小化时隐藏、还原后恢复，停止播放时清理连接和悬浮层。
- 全局快捷键 `Ctrl+Alt+D`：独立线程里 `RegisterHotKey`，只往主线程投递消息；PotPlayer 全屏时也能用。
- 普通全屏下悬浮层可见；**独占全屏**未实测，可能看不到。
