# -*- coding: utf-8 -*-
"""抓帧分析公共函数（被 test_theme_flicker.py / test_packaged_flicker.py 使用）。"""
from PIL import Image, ImageChops, ImageStat


def analyze(frames, t_toggle):
    """frames: [(t, PIL image)]。以切换前最后一帧、切换后最后一帧为参照。"""
    small = [(t, im.convert("L").resize((120, 80))) for t, im in frames]
    pre = [s for t, s in small if t < t_toggle]
    ref_a, ref_b = pre[-1], small[-1][1]

    def d(x, y):
        return ImageStat.Stat(ImageChops.difference(x, y)).mean[0]
    rows = []
    # 窗口中部（卡片区）是否为空：灰度标准差很低 = 只有底色，没有卡片/文字
    def body_std(im):
        w, h = im.size
        return ImageStat.Stat(im.convert("L").crop((int(w * .03), int(h * .30), int(w * .97), int(h * .80)))).stddev[0]
    stds = [body_std(im) for _, im in frames]
    blank_idx = [i for i, sd in enumerate(stds) if frames[i][0] >= t_toggle and sd < 5.0]
    for (t, s) in small:
        rows.append((t, d(s, ref_a), d(s, ref_b), ImageStat.Stat(s).mean[0]))
    TH = 6.0   # 平均灰度差低于它视为"已经等同于某个稳定状态"
    # 过渡帧：切换发出之后，既不像 A 也不像 B
    trans = [r for r in rows if r[0] >= t_toggle and r[1] > TH and r[2] > TH]
    # 反复：到过 B 之后又回到 A 或别的东西
    first_b = next((i for i, r in enumerate(rows) if r[0] >= t_toggle and r[2] <= TH), None)
    relapse = [r for r in rows[first_b:] if r[2] > TH] if first_b is not None else rows
    # 过渡期：第一个偏离 A 的帧 到 稳定在 B 的帧（最后一次进入 B）
    dev = next((r[0] for r in rows if r[0] >= t_toggle and r[1] > TH), None)
    last_nonb = max((r[0] for r in rows if r[0] >= t_toggle and r[2] > TH), default=None)
    dark_pen = [r for r in trans if r[3] < 20]   # 近乎全黑的帧
    n_after = len([r for r in rows if r[0] >= t_toggle])
    gaps = [rows[i + 1][0] - rows[i][0] for i in range(len(rows) - 1)]
    blank_ms = round(1000 * sum(frames[i + 1][0] - frames[i][0] for i in blank_idx if i + 1 < len(frames)), 1)
    return dict(blank_body_frames=len(blank_idx), blank_body_ms=blank_ms, frames=len(rows), frames_after_toggle=n_after, avg_grab_ms=round(1000 * sum(gaps) / max(len(gaps), 1), 1),
                max_gap_ms=round(1000 * max(gaps), 1),
                transition_frames=len(trans), relapse_frames=len(relapse),
                transition_span_ms=round(1000 * (last_nonb - dev), 1) if dev and last_nonb else 0,
                near_black_frames=len(dark_pen), min_mean_gray=round(min(r[3] for r in rows), 1),
                seq=[(round(1000 * (r[0] - t_toggle)), round(r[1], 1), round(r[2], 1), round(r[3], 1)) for r in rows
                     if r[0] >= t_toggle and r[1] > TH and r[2] > TH][:40])
