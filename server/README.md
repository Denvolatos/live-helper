# 🖥️ 服务器端（赛事数据转发 + 备用更新源）

跑在服务器上的小程序：每 5 分钟从 [PandaScore](https://pandascore.co) 取一次无畏契约 / CS / LOL 的赛程和比分，缓存后供软件读取。

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

---

## 📦 备用更新源（`updates_server.py`）

GitHub 连不上时，软件会改从这里取新版。🔐 用自签证书，软件里写死了证书的 SHA256 指纹（`updater.MIRROR_PINS`）严格比对。

| 文件 | 作用 |
|---|---|
| `updates_server.py` | HTTPS 静态文件服务，只提供 `latest.json` / `SHA256SUMS.txt` / `LiveHelper-Setup-vX.Y.Z.exe`，每来源每分钟 30 次、每小时下载 4 次安装包 |
| `livehelper-updates.service` | systemd 配置（私钥通过 `LoadCredential` 交给低权限进程，不可被别的用户读取） |
| `publish_update.py` | 发版时一条命令同步安装包到服务器：`python server/publish_update.py Output/LiveHelper-Setup-v1.4.0.exe --notes 说明.txt --verify` |

换证书时：在服务器重新生成，把新指纹**加进** `MIRROR_PINS`（保留旧的），随新版本发布。
