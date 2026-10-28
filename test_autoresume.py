# -*- coding: utf-8 -*-
"""自动续播的防抖/判断逻辑模拟测试（不联网、不开 PotPlayer）。
用一个“立刻退出的假 streamlink 进程”反复触发 core.AutoResumer，检查：
  1) 3 分钟内最多续播 2 次，第 3 次停下并给出提示；
  2) 主播下播不续播，提示“主播已下播”；
  3) 用户关闭 PotPlayer（日志含 Player closed）/ 用户点停止（app 里 self.proc 已清空，不调用 on_exit）视为主动结束；
  4) 开关关闭、B 站（不在 EXPIRING）、播放不足 60 秒、退出码非 0 都不续播；
  5) 窗口期过后计数清零。
用法：python test_autoresume.py"""
import subprocess
import sys

import core

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def fake_proc():
    """立刻正常退出（退出码 0）的假 streamlink，stdout 里放一行日志。"""
    p = subprocess.Popen([sys.executable, "-c", "print('[cli][info] Stream ended')"], stdout=subprocess.PIPE,
                         creationflags=core.NO_WINDOW)
    lines = p.stdout.read().decode().splitlines()
    return p.wait(), lines


# 1) 防抖：模拟循环——每次“流到期”（假进程退出，已播 300 秒），时间只推进 5 秒
clk = Clock()
r = core.AutoResumer("douyu", "x", live_fn=lambda: True, now=clk)
seq = []
for i in range(4):
    code, lines = fake_proc()
    act, msg = r.on_exit(code, lines, played=300)
    seq.append((act, msg))
    clk.t += 5
check("3 分钟内第 1、2 次续播", [a for a, _ in seq[:2]] == ["resume", "resume"], seq[:2])
check("第 3 次停下并提示", seq[2][0] == "stop" and "连续断开，已停止自动续播，请点播放重试" == seq[2][1], seq[2])
check("第 4 次仍然停下", seq[3][0] == "stop", seq[3])
check("续播提示是人话", "斗鱼流到期断开（部分线路约每 5 分钟），正在自动续播…" == seq[0][1], seq[0][1])

# 5) 窗口期过后恢复
clk.t += core.RESUME_WINDOW + 1
check("窗口期过后可再次续播", r.on_exit(0, ["Stream ended"], 300)[0] == "resume")

# 正常节奏：每 300 秒到期一次，永远不会触发限制
clk = Clock()
r = core.AutoResumer("douyu", "x", live_fn=lambda: True, now=clk)
acts = []
for i in range(10):
    acts.append(r.on_exit(0, ["Stream ended"], 300)[0])
    clk.t += 300
check("每 5 分钟到期一次的正常节奏下，连续 10 次都续播", set(acts) == {"resume"}, acts)

# 2) 下播
r = core.AutoResumer("douyu", "x", live_fn=lambda: False, now=Clock())
check("主播下播不续播", r.on_exit(0, ["Stream ended"], 300) == ("stop", "主播已下播"))

# 3) 用户关闭播放器
r = core.AutoResumer("douyu", "x", live_fn=lambda: True, now=Clock())
check("关闭 PotPlayer 不续播", r.on_exit(0, ["[cli][info] Player closed", "[cli][info] Stream ended"], 300) == ("stop", None))

# 4) 其它不续播情形
check("开关关闭不续播", core.AutoResumer("douyu", "x", live_fn=lambda: True).on_exit(0, [], 300, enabled=False)[0] == "stop")
check("B 站不续播（实测不属于会到期断流的平台）", core.AutoResumer("bili", "x", live_fn=lambda: True).on_exit(0, [], 300)[0] == "stop")
check("播放不足 60 秒不续播", core.AutoResumer("douyu", "x", live_fn=lambda: True).on_exit(0, [], 20)[0] == "stop")
check("退出码非 0 不续播", core.AutoResumer("douyu", "x", live_fn=lambda: True).on_exit(1, [], 300)[0] == "stop")


def boom():
    raise RuntimeError("net")


check("查不到直播状态时仍尝试续播", core.AutoResumer("douyu", "x", live_fn=boom, now=Clock()).on_exit(0, [], 300)[0] == "resume")

print("\n失败 %d 项" % len(fails) if fails else "\n全部通过")
sys.exit(1 if fails else 0)
