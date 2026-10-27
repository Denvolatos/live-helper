# -*- coding: utf-8 -*-
"""用 Pillow 画图标：橙色圆角方块 + 白色播放三角，输出 icon.ico（多尺寸）。"""
import os
from PIL import Image, ImageDraw

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((16, 16, S - 16, S - 16), radius=110, fill=(255, 122, 0, 255))
d.polygon([(200, 140), (200, 372), (390, 256)], fill=(255, 255, 255, 255))
here = os.path.dirname(os.path.abspath(__file__))
img.save(os.path.join(here, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon.ico ok")
