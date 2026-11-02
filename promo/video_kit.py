# -*- coding: utf-8 -*-
"""홍보영상 합성용 공용 도구 — 글꼴, 그리기, 화면 이동(켄 번즈), 배경음악 합성, 인코딩.

외부 의존성: Pillow, NumPy, ffmpeg(실행 파일). TTS 나레이션은 edge-tts(선택).
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# 색 / 글꼴
# ---------------------------------------------------------------------------
BG_TOP = (11, 17, 30)
BG_BOTTOM = (20, 30, 52)
ACCENT = (59, 130, 246)       # 앱 툴바 파랑
ACCENT2 = (249, 115, 22)      # 시뮬레이션 주황
GREEN = (52, 211, 153)
WHITE = (241, 245, 249)
MUTED = (148, 163, 184)
PANEL = (15, 23, 42)

_FONT_CANDIDATES = {
    'bold': [
        r'C:\Windows\Fonts\malgunbd.ttf',
        '/usr/share/fonts/truetype/nanum/NanumSquareB.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
    ],
    'regular': [
        r'C:\Windows\Fonts\malgun.ttf',
        '/usr/share/fonts/truetype/nanum/NanumSquareR.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
    ],
    'mono': [
        r'C:\Windows\Fonts\consola.ttf',
        '/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        r'C:\Windows\Fonts\cour.ttf',
    ],
}


@lru_cache(maxsize=None)
def font(size, kind='bold'):
    for path in _FONT_CANDIDATES[kind]:
        if os.path.exists(path):
            index = 1 if path.endswith('.ttc') and 'CJK' in path else 0
            try:
                return ImageFont.truetype(path, int(size), index=index)
            except OSError:
                continue
    sys.stderr.write('[경고] %s 글꼴을 찾지 못해 기본 글꼴을 씁니다(한글이 깨질 수 있음)\n' % kind)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# 시간 보간
# ---------------------------------------------------------------------------
def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def ease(x):
    """ease-in-out (0~1)."""
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def window(t, start, end, fade=0.35):
    """start~end 동안 1, 앞뒤 fade초 동안 0↔1로 변하는 투명도."""
    if t < start or t > end:
        return 0.0
    return clamp(min((t - start) / fade, (end - t) / fade))


def lerp(a, b, k):
    return a + (b - a) * k


def lerp_box(a, b, k):
    return tuple(lerp(x, y, k) for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# 그리기
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4)
def background(w, h, grid=True):
    """짙은 남색 그라데이션 + 옅은 격자(가공 테이블 느낌)."""
    y = np.linspace(0, 1, h)[:, None, None]
    top = np.array(BG_TOP, dtype=np.float32)[None, None, :]
    bot = np.array(BG_BOTTOM, dtype=np.float32)[None, None, :]
    arr = np.repeat(top * (1 - y) + bot * y, w, axis=1)
    if grid:
        step = 60
        arr[::step, :, :] += 7
        arr[:, ::step, :] += 7
    # 가장자리를 살짝 어둡게(비네팅)
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    arr *= (1 - 0.25 * np.clip(d - 0.6, 0, 1))[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')


def overlay(base, alpha_layer_fn, opacity=1.0):
    """RGBA 레이어를 그려 base(RGB)에 합성한다. alpha_layer_fn(draw, layer)."""
    if opacity <= 0:
        return
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    alpha_layer_fn(ImageDraw.Draw(layer), layer)
    if opacity < 1:
        a = layer.getchannel('A').point(lambda v: int(v * opacity))
        layer.putalpha(a)
    base.paste(layer, (0, 0), layer)


def text_size(text, fnt):
    box = fnt.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


def wrap(text, fnt, max_w):
    """한글 문장을 폭에 맞게 줄바꿈(공백 우선, 필요하면 글자 단위)."""
    lines = []
    for para in text.split('\n'):
        cur = ''
        for word in para.split(' '):
            trial = (cur + ' ' + word).strip()
            if text_size(trial, fnt)[0] <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            cur = word
            while text_size(cur, fnt)[0] > max_w and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and text_size(cur[:cut], fnt)[0] > max_w:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        lines.append(cur)
    return lines


def draw_text(img, xy, text, size, color=WHITE, kind='bold', anchor='la', opacity=1.0,
              shadow=True, max_w=None, spacing=1.25, align='left'):
    """텍스트(여러 줄 가능)를 그린다. anchor: 'la' 왼쪽 위, 'ma' 가운데 위, 'mm' 가운데."""
    if opacity <= 0:
        return 0
    fnt = font(size, kind)
    lines = wrap(text, fnt, max_w) if max_w else text.split('\n')
    line_h = int(size * spacing)
    total_h = line_h * len(lines)
    x, y = xy
    if anchor[1] == 'm':
        y -= total_h / 2

    def paint(d, _layer):
        for i, line in enumerate(lines):
            w, _ = text_size(line, fnt)
            lx = x - w / 2 if anchor[0] == 'm' or align == 'center' else x
            ly = y + i * line_h
            if shadow:
                d.text((lx + 2, ly + 3), line, font=fnt, fill=(0, 0, 0, 150))
            d.text((lx, ly), line, font=fnt, fill=tuple(color) + (255,))
    overlay(img, paint, opacity)
    return total_h


def rounded_panel(img, box, radius=22, fill=(15, 23, 42, 215), outline=None, width=2, opacity=1.0):
    def paint(d, _layer):
        d.rounded_rectangle(box, radius, fill=fill, outline=outline, width=width)
    overlay(img, paint, opacity)


def highlight(img, box, progress, color=ACCENT2, width=6, radius=12, label=None, label_size=34,
              opacity=1.0, label_above=True):
    """box 둘레를 progress(0~1)만큼 그려 나가는 강조 테두리 + 라벨."""
    if progress <= 0 or opacity <= 0:
        return
    x0, y0, x1, y1 = box
    per = 2 * ((x1 - x0) + (y1 - y0))
    length = per * clamp(progress)
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]

    def paint(d, _layer):
        if progress >= 1:
            d.rounded_rectangle(box, radius, outline=tuple(color) + (255,), width=width)
            d.rounded_rectangle(box, radius, fill=tuple(color) + (28,))
        else:
            remain = length
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                seg = math.hypot(bx - ax, by - ay)
                if remain <= 0:
                    break
                k = min(1.0, remain / seg)
                d.line([(ax, ay), (ax + (bx - ax) * k, ay + (by - ay) * k)], fill=tuple(color) + (255,), width=width)
                remain -= seg
        if label:
            fnt = font(label_size)
            tw, th = text_size(label, fnt)
            pad = 12
            lx = x0
            ly = y0 - th - 2 * pad - 8 if label_above else y1 + 8
            d.rounded_rectangle((lx, ly, lx + tw + 2 * pad, ly + th + 2 * pad + 4), 10, fill=tuple(color) + (240,))
            d.text((lx + pad, ly + pad - fnt.getbbox(label)[1]), label, font=fnt, fill=(255, 255, 255, 255))
    overlay(img, paint, opacity)


def paste_fit(dst, src, box, opacity=1.0, radius=0, shadow=True, border=None):
    """src를 box(x0,y0,x1,y1)에 비율 유지로 맞춰 넣는다. 실제 놓인 영역을 돌려준다."""
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    bw, bh = x1 - x0, y1 - y0
    scale = min(bw / src.width, bh / src.height)
    w, h = max(1, int(src.width * scale)), max(1, int(src.height * scale))
    im = src.resize((w, h), Image.LANCZOS if scale < 0.6 else Image.BILINEAR).convert('RGB')
    px, py = x0 + (bw - w) // 2, y0 + (bh - h) // 2
    paste_image(dst, im, (px, py), opacity, radius, shadow, border)
    return px, py, px + w, py + h


def paste_image(dst, im, pos, opacity=1.0, radius=0, shadow=True, border=None):
    if opacity <= 0:
        return
    px, py = int(pos[0]), int(pos[1])
    w, h = im.size
    if shadow:
        sh = Image.new('RGBA', (w + 80, h + 80), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((40, 48, 40 + w, 48 + h), radius or 8, fill=(0, 0, 0, int(140 * opacity)))
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        dst.paste(sh, (px - 40, py - 40), sh)
    mask = Image.new('L', (w, h), int(255 * opacity))
    if radius:
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=int(255 * opacity))
    dst.paste(im, (px, py), mask)
    if border:
        overlay(dst, lambda d, _l: d.rounded_rectangle((px, py, px + w - 1, py + h - 1), radius or 4,
                                                      outline=tuple(border) + (255,), width=3), opacity)


def ken_burns(src, out_size, box_from, box_to, k):
    """src의 box_from → box_to 영역을 k(0~1)에 따라 보간해 out_size로 잘라 확대."""
    box = lerp_box(box_from, box_to, ease(k))
    ow, oh = out_size
    # 출력 비율을 지키도록 상자를 보정
    bx0, by0, bx1, by1 = box
    bw, bh = bx1 - bx0, by1 - by0
    target = ow / oh
    if bw / bh > target:
        nh = bw / target
        by0 -= (nh - bh) / 2
        by1 = by0 + nh
    else:
        nw = bh * target
        bx0 -= (nw - bw) / 2
        bx1 = bx0 + nw
    return src.resize((ow, oh), Image.BILINEAR, box=(bx0, by0, bx1, by1))


def chip(img, xy, text, size=30, color=ACCENT, opacity=1.0):
    fnt = font(size)
    tw, th = text_size(text, fnt)
    pad_x, pad_y = int(size * 0.6), int(size * 0.35)
    x, y = xy

    def paint(d, _layer):
        d.rounded_rectangle((x, y, x + tw + 2 * pad_x, y + th + 2 * pad_y + 4), (th + 2 * pad_y) // 2,
                            fill=tuple(color) + (235,))
        d.text((x + pad_x, y + pad_y - fnt.getbbox(text)[1]), text, font=fnt, fill=(255, 255, 255, 255))
    overlay(img, paint, opacity)
    return tw + 2 * pad_x


def progress_bar(img, k, color=ACCENT, height=6):
    w, h = img.size
    overlay(img, lambda d, _l: d.rectangle((0, h - height, int(w * clamp(k)), h), fill=tuple(color) + (255,)))


class FrameSeq:
    """캡처한 연속 프레임(PNG 폴더)을 잘라·축소해 메모리에 들고 있는다."""

    def __init__(self, folder, crop=None, size=None):
        self.paths = sorted(Path(folder).glob('*.png'))
        if not self.paths:
            raise FileNotFoundError('프레임이 없습니다: %s (먼저 capture_app.py 실행)' % folder)
        self.crop = crop
        self.size = size
        self._cache = {}
        meta = Path(folder) / 'meta.json'
        self.labels = json.loads(meta.read_text(encoding='utf-8')).get('labels', []) if meta.exists() else []

    def __len__(self):
        return len(self.paths)

    def label(self, k):
        """k 시점 프레임의 공정 이름(캡처할 때 기록한 값)."""
        if not self.labels:
            return ''
        return self.labels[int(round(clamp(k) * (len(self.labels) - 1)))]

    def get(self, k):
        i = int(round(clamp(k) * (len(self.paths) - 1)))
        if i not in self._cache:
            im = Image.open(self.paths[i]).convert('RGB')
            if self.crop:
                im = im.crop(self.crop)
            if self.size:
                im = im.resize(self.size, Image.LANCZOS)
            self._cache[i] = im
        return self._cache[i]


# ---------------------------------------------------------------------------
# 배경음악(저작권 걱정 없는 자체 합성)
# ---------------------------------------------------------------------------
SR = 44100


def _note(n):
    return 440.0 * 2 ** ((n - 69) / 12.0)


def synth_bgm(seconds, path, bpm=100, seed=7):
    """잔잔한 테크 계열 배경음악: 패드(Am–F–C–G) + 아르페지오 + 킥/하이햇."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros((n, 2), dtype=np.float64)
    beat = 60.0 / bpm
    bar = beat * 4
    chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]   # Am F C G
    # 패드
    for i in range(int(seconds / bar) + 1):
        root = chords[i % 4]
        s0 = int(i * bar * SR)
        s1 = min(n, int((i + 1) * bar * SR + 0.6 * SR))
        if s0 >= n:
            break
        tt = t[s0:s1] - i * bar
        env = np.minimum(1, tt / 0.8) * np.exp(-np.maximum(0, tt - bar) * 3)
        sig = np.zeros_like(tt)
        for m in root:
            f = _note(m)
            sig += np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * tt + 0.3) + 0.15 * np.sin(2 * np.pi * 0.5 * f * tt)
        sig *= env * 0.045
        out[s0:s1, 0] += sig * 1.0
        out[s0:s1, 1] += sig * 0.9
    # 아르페지오(8분음)
    step = beat / 2
    for j in range(int(seconds / step)):
        root = chords[int(j * step / bar) % 4]
        m = root[j % 3] + (12 if (j // 3) % 2 else 0) + 12
        s0 = int(j * step * SR)
        s1 = min(n, s0 + int(0.45 * SR))
        tt = t[s0:s1] - j * step
        sig = np.sin(2 * np.pi * _note(m) * tt) * np.exp(-tt * 7) * 0.05
        pan = 0.5 + 0.3 * math.sin(j * 0.7)
        out[s0:s1, 0] += sig * (1 - pan) * 2
        out[s0:s1, 1] += sig * pan * 2
    # 킥(1,3박) / 하이햇(엇박)
    for j in range(int(seconds / beat)):
        s0 = int(j * beat * SR)
        if j % 2 == 0:
            s1 = min(n, s0 + int(0.35 * SR))
            tt = t[s0:s1] - j * beat
            f = 50 + 70 * np.exp(-tt * 30)
            kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9) * 0.16
            out[s0:s1] += kick[:, None]
        h0 = s0 + int(beat / 2 * SR)
        h1 = min(n, h0 + int(0.06 * SR))
        if h0 < n:
            noise = rng.standard_normal(h1 - h0)
            noise = np.diff(noise, prepend=0)
            hat = noise * np.exp(-np.arange(h1 - h0) / SR * 60) * 0.025
            out[h0:h1] += hat[:, None]
    # 앞뒤 페이드
    fade_in, fade_out = int(1.5 * SR), int(2.5 * SR)
    out[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    out[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    out /= max(1e-9, np.abs(out).max()) / 0.8
    write_wav(path, out)


def write_wav(path, stereo):
    data = (np.clip(stereo, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(data.tobytes())


# ---------------------------------------------------------------------------
# TTS 나레이션 (선택: pip install edge-tts, 인터넷 필요)
# ---------------------------------------------------------------------------
def tts_available():
    import importlib.util
    return importlib.util.find_spec('edge_tts') is not None


def synth_tts(text, path, voice='ko-KR-SunHiNeural', rate='+8%'):
    import asyncio
    import edge_tts

    async def run():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
    asyncio.run(run())
    return audio_duration(path)


def audio_duration(path):
    """오디오 길이(초). ffprobe가 없어도 되도록 ffmpeg 출력의 Duration 줄을 읽는다."""
    out = subprocess.run([ffmpeg_bin(), '-hide_banner', '-i', str(path)], capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', out.stderr)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------
def ffmpeg_bin():
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise SystemExit('ffmpeg가 없습니다. "winget install Gyan.FFmpeg" 또는 "pip install imageio-ffmpeg" 후 다시 실행하세요.')


class VideoWriter:
    def __init__(self, path, size, fps):
        self.proc = subprocess.Popen(
            [ffmpeg_bin(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
             '-s', '%dx%d' % size, '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'medium',
             '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)],
            stdin=subprocess.PIPE)

    def write(self, img):
        self.proc.stdin.write(img.tobytes())

    def close(self):
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError('ffmpeg 인코딩 실패')


def mux(video, bgm, out, voice_clips=(), bgm_volume=0.55):
    """영상 + 배경음악(+ 나레이션 클립 [(path, start_sec), ...]) → out."""
    cmd = [ffmpeg_bin(), '-y', '-loglevel', 'error', '-i', str(video), '-i', str(bgm)]
    for clip, _start in voice_clips:
        cmd += ['-i', str(clip)]
    if voice_clips:
        parts = ['[1:a]volume=%.2f[bg]' % (bgm_volume * 0.45)]
        labels = []
        for i, (_clip, start) in enumerate(voice_clips):
            ms = int(start * 1000)
            parts.append('[%d:a]adelay=%d|%d,volume=1.6[v%d]' % (i + 2, ms, ms, i))
            labels.append('[v%d]' % i)
        parts.append('[bg]%samix=inputs=%d:normalize=0:duration=first[a]' % (''.join(labels), len(labels) + 1))
        cmd += ['-filter_complex', ';'.join(parts), '-map', '0:v', '-map', '[a]']
    else:
        cmd += ['-filter_complex', '[1:a]volume=%.2f[a]' % bgm_volume, '-map', '0:v', '-map', '[a]']
    cmd += ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(out)]
    subprocess.run(cmd, check=True)


def srt_time(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


def concat(parts, out):
    """같은 설정으로 인코딩한 영상 조각들을 이어 붙인다(재인코딩 없음)."""
    listing = Path(out).with_suffix('.txt')
    listing.write_text(''.join("file '%s'\n" % Path(p).resolve().as_posix() for p in parts), encoding='utf-8')
    subprocess.run([ffmpeg_bin(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-c', 'copy', str(out)], check=True)


def crop_resize(src, size, box):
    """src의 box 영역을 size로 확대/축소. box가 이미지 밖으로 나가면 가장자리 색으로 채운다."""
    x0, y0, x1, y1 = box
    if x0 >= 0 and y0 >= 0 and x1 <= src.width and y1 <= src.height:
        return src.resize(size, Image.BILINEAR, box=box)
    ix0, iy0 = int(math.floor(x0)), int(math.floor(y0))
    ix1, iy1 = int(math.ceil(x1)), int(math.ceil(y1))
    canvas = Image.new('RGB', (ix1 - ix0, iy1 - iy0), src.getpixel((min(src.width - 1, 600), src.height // 2)))
    sx0, sy0 = max(0, ix0), max(0, iy0)
    sx1, sy1 = min(src.width, ix1), min(src.height, iy1)
    if sx1 > sx0 and sy1 > sy0:
        canvas.paste(src.crop((sx0, sy0, sx1, sy1)), (sx0 - ix0, sy0 - iy0))
    return canvas.resize(size, Image.BILINEAR, box=(x0 - ix0, y0 - iy0, x1 - ix0, y1 - iy0))
