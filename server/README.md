# 🖥️ 赛事数据转发（服务器端）

跑在服务器上的小程序：每 5 分钟从 [PandaScore](https://pandascore.co) 取一次瓦 / CS / LOL 的赛程和比分，缓存后供软件读取。

## ✨ 为什么要它
- 🔑 令牌只放在服务器上，不写进公开的软件和仓库。
- 📉 用户再多，也只由服务器每 5 分钟请求 9 次，不会超过 PandaScore 免费档每小时 1000 次的上限。
- 🌏 软件只连这台服务器，不用各自去连国外接口。

## 📂 文件
| 文件 | 作用 |
|---|---|
| `matches_relay.py` | 主程序，只用 Python 自带的库，无需安装依赖 |
| `livehelper-relay.service` | systemd 配置：开机自启、崩溃自动重启、权限收紧 |
| `test_relay.py` | 本地测试（假数据，不联网、不用真令牌） |

## 🌐 接口
| 地址 | 返回 |
|---|---|
| `/health` | 是否正常、上次刷新时间、上次错误（不含令牌） |
| `/matches` | 三款游戏全部数据 |
| `/matches/lol`、`/matches/csgo`、`/matches/valorant` | 单款游戏的 `running` / `upcoming` / `past` |

每个来源 IP 每分钟最多 60 次请求，超过返回 429。

## 🔐 安全说明
- 令牌放在服务器的 `/etc/livehelper/relay.env`（权限 600，仅管理员可读），**绝不提交到仓库、不写进日志**。
- 程序以随机的低权限用户运行（systemd `DynamicUser`），只能写自己的缓存目录。
- 目前是 **HTTP（无加密）+ IP + 端口**，仅用于试验；比赛数据本身是公开信息。正式使用前应配域名和 HTTPS。
