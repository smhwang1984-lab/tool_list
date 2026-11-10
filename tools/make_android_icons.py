"""public/icon.png(원본 assets/nc_tool_list.png)로 Android 런처 아이콘과 시작 화면을 만든다.

사용: python tools/make_android_icons.py   (Pillow 필요: pip install pillow)
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'android' / 'app' / 'src' / 'main' / 'res'
SRC = Image.open(ROOT / 'public' / 'icon.png').convert('RGBA')
SPLASH_BG = (0x1f, 0x3a, 0x5f, 255)  # 원본 header_bg

LAUNCHER = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}


def fit(size, ratio):
    side = round(size * ratio)
    return SRC.resize((side, side), Image.LANCZOS)


def centered(canvas_size, ratio, bg):
    w, h = canvas_size
    canvas = Image.new('RGBA', (w, h), bg)
    ic = fit(min(w, h), ratio)
    canvas.alpha_composite(ic, ((w - ic.width) // 2, (h - ic.height) // 2))
    return canvas


for density, px in LAUNCHER.items():
    folder = RES / f'mipmap-{density}'
    plain = centered((px, px), 0.92, (0, 0, 0, 0))
    plain.save(folder / 'ic_launcher.png')
    plain.save(folder / 'ic_launcher_round.png')
    fg = round(px * 108 / 48)  # 적응형 아이콘 전경 108dp, 안전 영역 66dp
    centered((fg, fg), 0.60, (0, 0, 0, 0)).save(folder / 'ic_launcher_foreground.png')

for splash in RES.glob('drawable*/splash.png'):
    size = Image.open(splash).size
    centered(size, 0.32, SPLASH_BG).convert('RGB').save(splash)

print('icons ok')
