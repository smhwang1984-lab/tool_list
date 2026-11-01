# -*- coding: utf-8 -*-
"""Sum Path(NC Tool List) 홍보영상 생성기 — 쇼츠(세로 9:16)와 약 3분 설명영상(가로 16:9).

사용법 (Windows 11, 저장소 폴더에서):
    python promo\\capture_app.py            # 1) 실제 앱 화면 캡처 (약 1분)
    python promo\\make_video.py --all        # 2) 영상 2편 합성 (자막 + 배경음악)
    python promo\\make_video.py --all --tts  # 2') edge-tts 한국어 나레이션까지 (인터넷 필요)

옵션: --shorts / --long / --all, --tts, --voice ko-KR-InJoonNeural, --fps 30, --preview(빠른 저해상도 확인용)
결과: promo/output/SumPath_Shorts.mp4, SumPath_Explainer.mp4 (+ .srt 자막)
"""
import argparse
import multiprocessing
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image

import video_kit as vk
from video_kit import (ACCENT, ACCENT2, GREEN, MUTED, WHITE, chip, clamp, draw_text, ease, ease_out,
                       font, highlight, lerp, overlay, paste_fit, paste_image, rounded_panel,
                       text_size, window)

PROMO = Path(__file__).resolve().parent
ROOT = PROMO.parent
BUILD = PROMO / 'build'
SHOTS = BUILD / 'shots'
FRAMES = BUILD / 'frames'
OUTPUT = PROMO / 'output'
LOGO = ROOT / 'assets' / 'nc_tool_list.png'
DEMO_MILL = PROMO / 'demo_nc' / 'DEMO_MILL.nc'

APP_TITLE = 'Sum Path · NC Tool List'
FULL = (0, 0, 1920, 1080)                 # 캡처 화면 전체
VIEW3D = (530, 115, 1920, 1075)           # 3D Viewer 영역
PART = (865, 215, 1565, 915)              # 밀링 시뮬레이션 소재가 놓인 영역(정사각형)
LPART = (905, 240, 1545, 880)             # 선반 시뮬레이션 소재 영역
RPART = (800, 175, 1640, 975)             # 5축 실가공 툴패스 영역
CODE = (0, 115, 520, 1075)                # 왼쪽 프로그램 패널
TABLE = (528, 120, 1910, 440)             # 툴리스트 표 (밀링 데모 기준)
MACHINE_PANEL = (0, 115, 520, 390)
PROCESS_LIST = (0, 895, 520, 1062)


# ---------------------------------------------------------------------------
# 자원 불러오기
# ---------------------------------------------------------------------------
class Assets:
    def __init__(self):
        missing = [p for p in ('mill_list', 'mill_sim_done', 'lathe_list') if not (SHOTS / (p + '.png')).exists()]
        if missing:
            raise SystemExit('캡처가 없습니다(%s). 먼저 python promo/capture_app.py 를 실행하세요.' % ', '.join(missing))
        self._shots = {}
        self.logo = Image.open(LOGO).convert('RGBA')
        self.mill_sim = vk.FrameSeq(FRAMES / 'mill_sim')
        self.lathe_sim = vk.FrameSeq(FRAMES / 'lathe_sim')
        self.real_rotate = vk.FrameSeq(FRAMES / 'real_rotate')
        self.tool_block = self._tool_block()

    def shot(self, name):
        if name not in self._shots:
            self._shots[name] = Image.open(SHOTS / (name + '.png')).convert('RGB')
        return self._shots[name]

    @staticmethod
    def _tool_block():
        """데모 프로그램에서 2번 공구의 CATIA 주석 블록을 그대로 가져온다."""
        lines = DEMO_MILL.read_text(encoding='utf-8').splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith('N2('))
        return lines[start:start + 6]


def logo_img(assets, size):
    return assets.logo.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# 장면 정의
# ---------------------------------------------------------------------------
class Scene:
    def __init__(self, dur, narration, draw, title=None):
        self.dur = dur
        self.narration = narration
        self.draw = draw
        self.title = title


# TTS가 영문 약어를 자연스럽게 읽도록 바꿔 읽기(자막에는 원문이 그대로 나간다)
TTS_PRONOUNCE = [
    ('Sum Path', '썸 패스'), ('PPTABLE', '피피 테이블'), ('CATIA', '카티아'), ('SO', '에스오'),
    ('코너 R', '코너 알'), ('A to C', '에이 투 씨'), ('B to C', '비 투 씨'), ('CAM', '캠'), ('CAD', '캐드'),
]


def tts_text(text):
    for src, dst in TTS_PRONOUNCE:
        text = text.replace(src, dst)
    return text


def caption_chunks(text):
    """나레이션을 자막 단위(문장/쉼표)로 쪼갠다."""
    parts = [p.strip() for p in re.split(r'(?<=[.?!])\s+', text) if p.strip()]
    out = []
    for p in parts:
        if len(p) > 44 and ', ' in p:
            pieces = p.split(', ')
            buf = ''
            for piece in pieces:
                cand = (buf + ', ' + piece) if buf else piece
                if len(cand) > 44 and buf:
                    out.append(buf + ',')
                    buf = piece
                else:
                    buf = cand
            if buf:
                out.append(buf)
        else:
            out.append(p)
    return out


def chunk_times(text, start, dur):
    """자막 조각별 (시작, 끝) — 글자 수 비례."""
    chunks = caption_chunks(text)
    total = sum(len(c) for c in chunks) or 1
    t = start + 0.25
    span = max(0.5, dur - 0.5)
    res = []
    for c in chunks:
        d = span * len(c) / total
        res.append((c, t, t + d))
        t += d
    return res


def draw_caption(img, scene, t, vertical):
    if not scene.narration:
        return
    w, h = img.size
    for text, s, e in chunk_times(scene.narration, 0, scene.dur):
        if s <= t <= e:
            a = window(t, s, e, 0.18)
            if vertical:
                size, max_w, y = 50, w - 140, 1590
            else:
                size, max_w, y = 40, w - 360, h - 120
            fnt = font(size)
            lines = vk.wrap(text, fnt, max_w)
            lh = int(size * 1.35)
            bw = max(text_size(line, fnt)[0] for line in lines) + 64
            bh = lh * len(lines) + 36
            box = ((w - bw) / 2, y - bh / 2, (w + bw) / 2, y + bh / 2)
            rounded_panel(img, box, 18, fill=(0, 0, 0, 175), opacity=a)
            draw_text(img, (w / 2, box[1] + 18), '\n'.join(lines), size, WHITE, anchor='ma', opacity=a,
                      spacing=1.35, align='center')
            break


def draw_header(img, scene, t, vertical):
    if not scene.title:
        return
    a = clamp(t / 0.5)
    if vertical:
        draw_text(img, (540, 250), scene.title, 70, WHITE, anchor='ma', opacity=a, max_w=960, align='center')
    else:
        chip(img, (60, 40), scene.title, 34, ACCENT, opacity=a)


def map_box(src_box, crop_box, dst_rect):
    """캡처 좌표 src_box가 (crop_box를 dst_rect로 확대한) 화면에서 어디에 오는지."""
    cx0, cy0, cx1, cy1 = crop_box
    dx0, dy0, dx1, dy1 = dst_rect
    sx = (dx1 - dx0) / (cx1 - cx0)
    sy = (dy1 - dy0) / (cy1 - cy0)
    x0, y0, x1, y1 = src_box
    return (dx0 + (x0 - cx0) * sx, dy0 + (y0 - cy0) * sy, dx0 + (x1 - cx0) * sx, dy0 + (y1 - cy0) * sy)


def fit_crop(box, aspect):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w / h > aspect:
        nh = w / aspect
        y0 -= (nh - h) / 2
        return (x0, y0, x1, y0 + nh)
    nw = h * aspect
    x0 -= (nw - w) / 2
    return (x0, y0, x0 + nw, y1)


def app_window(img, src, rect, crop_from, crop_to, k, opacity=1.0, highlights=()):
    """앱 캡처를 rect 창 안에서 crop_from→crop_to로 천천히 이동/확대하며 보여 준다.
    highlights: [(캡처 좌표 box, 시작 k, 라벨, 색)]"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    size = (x1 - x0, y1 - y0)
    aspect = size[0] / size[1]
    a, b = fit_crop(crop_from, aspect), fit_crop(crop_to, aspect)
    crop = vk.lerp_box(a, b, ease(k))
    view = vk.crop_resize(src, size, crop)
    paste_image(img, view, (x0, y0), opacity, radius=14, border=(51, 65, 85))
    for box, start, label, color in highlights:
        p = clamp((k - start) / 0.12)
        if p > 0:
            hb = map_box(box, crop, rect)
            highlight(img, hb, p, color=color, label=label, opacity=opacity)


def frame_player(img, seq, rect, k, crop, opacity=1.0):
    x0, y0, x1, y1 = [int(v) for v in rect]
    frame = seq.get(k)
    view = vk.crop_resize(frame, (x1 - x0, y1 - y0), fit_crop(crop, (x1 - x0) / (y1 - y0)))
    paste_image(img, view, (x0, y0), opacity, radius=14, border=(51, 65, 85))


def feature_cards(img, items, t, rect, cols, start=0.3, gap=0.35, size=40, sub_size=28):
    """번호 원 + 제목 + 설명 카드 묶음을 차례로 띄운다."""
    x0, y0, x1, y1 = rect
    rows = (len(items) + cols - 1) // cols
    cw = (x1 - x0 - (cols - 1) * 30) / cols
    ch = (y1 - y0 - (rows - 1) * 30) / rows
    for i, (head, sub, color) in enumerate(items):
        a = ease_out((t - start - i * gap) / 0.5)
        if a <= 0:
            continue
        r, c = divmod(i, cols)
        bx = x0 + c * (cw + 30)
        by = y0 + r * (ch + 30) + (1 - a) * 40
        rounded_panel(img, (bx, by, bx + cw, by + ch), 24, fill=(15, 23, 42, 225),
                      outline=tuple(color) + (255,), width=3, opacity=a)
        cx, cy, rad = bx + 34 + size * 0.7, by + 34 + size * 0.7, size * 0.7
        overlay(img, lambda d, _l: d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=tuple(color) + (255,)), a)
        draw_text(img, (cx, cy), str(i + 1), int(size * 0.8), WHITE, anchor='mm', opacity=a, shadow=False)
        head_h = draw_text(img, (bx + 34 + size * 1.7, by + 34), head, size, WHITE, opacity=a,
                           max_w=cw - 80 - size * 1.7)
        if sub:
            draw_text(img, (bx + 34, by + 54 + max(size * 1.4, head_h)), sub, sub_size, MUTED, kind='regular',
                      opacity=a, max_w=cw - 68, spacing=1.4)


# ---------------------------------------------------------------------------
# CATIA PPTABLE 주석 → 툴리스트 칸 연결 그래픽
# ---------------------------------------------------------------------------
PP_MAP = [
    # (줄 번호, 주석 안 토큰, 표 열, 표에 들어가는 값)
    (6, 'M6 T2', 'NO', 'T02'),
    (2, 'D10 F.EM', 'NAME', 'D10 F.EM'),
    (2, 'F.EM', 'TYPE', 'FLAT E/M'),
    (4, 'DC    10.000000', 'D', '10'),
    (3, 'FL    26.000000', 'FL', '26'),
    (3, 'LCF    38.500000', 'LCF', '38.5'),
    (3, 'F 3', 'F', '3'),
    (2, '[SO 40]', 'SO', '40'),
    (3, 'GL   160.000000', 'GL', '160'),
    (2, 'BT40-SK16-120', '홀더', 'BT40-SK16-120'),
    (5, 'SPINDL  8000.000000', 'SPINDL', '8000'),
    (5, 'FEED  2400.000000', 'FEED', '2400'),
]
PP_COLUMNS = [('NO', 1.0), ('TYPE', 1.6), ('NAME', 1.6), ('D', 0.7), ('FL', 0.7), ('LCF', 0.8), ('F', 0.6),
              ('SO', 0.7), ('GL', 0.8), ('홀더', 2.3), ('SPINDL', 1.1), ('FEED', 1.0)]
PP_COLORS = [ACCENT2, (96, 165, 250), (96, 165, 250), GREEN, GREEN, GREEN, GREEN, (244, 114, 182),
             GREEN, (250, 204, 21), (167, 139, 250), (167, 139, 250)]


def _token_box(line, token, fnt, x, y):
    i = line.find(token)
    if i < 0:
        i = line.find(token.split()[0])
    left = x + fnt.getlength(line[:max(i, 0)])
    return (left - 4, y - 4, left + fnt.getlength(token) + 4, y + fnt.size + 8)


def pptable_graphic(img, block, t, dur, vertical):
    w, h = img.size
    if vertical:
        code_size, code_rect = 27, (40, 480, 1040, 790)
        table_rect = (40, 1010, 1040, 1370)
    else:
        code_size, code_rect = 30, (230, 150, 1290, 470)
        table_rect = (80, 690, 1840, 850)
    a = clamp(t / 0.5)
    # 코드 상자
    rounded_panel(img, code_rect, 18, fill=(10, 14, 24, 240), outline=(51, 65, 85, 255), opacity=a)
    draw_text(img, (code_rect[0] + 24, code_rect[1] - 52), 'NC 프로그램  —  CATIA 포스트 출력 (PPTABLE 설정)', 30 if not vertical else 30,
              ACCENT2, opacity=a)
    mono = font(code_size, 'mono')
    lh = int(code_size * 1.45)
    cx, cy = code_rect[0] + 28, code_rect[1] + 26
    for i, line in enumerate(block):
        color = (226, 232, 240) if line.strip().startswith('(') else (248, 113, 113)
        draw_text(img, (cx, cy + i * lh), line, code_size, color, kind='mono', opacity=a, shadow=False)
    if not vertical:
        # 오른쪽 설명 상자
        info = (1340, 150, 1840, 470)
        rounded_panel(img, info, 18, fill=(30, 41, 59, 235), outline=tuple(ACCENT2) + (255,), opacity=a)
        draw_text(img, (info[0] + 28, info[1] + 26), 'CATIA PPTABLE', 36, ACCENT2, opacity=a)
        draw_text(img, (info[0] + 28, info[1] + 86),
                  '공구 교체마다 공구명·SO·홀더, 길이(LCF/FL/GL), 지름·R·선단각(DC/RE/SIG/PL), 회전수·이송을 '
                  '주석으로 출력하도록 한 번만 설정합니다.', 27, WHITE, kind='regular', opacity=a,
                  max_w=info[2] - info[0] - 56, spacing=1.45)
    # 표
    rounded_panel(img, table_rect, 14, fill=(15, 23, 42, 240), outline=(51, 65, 85, 255), opacity=a)
    draw_text(img, (table_rect[0] + 20, table_rect[1] - 52), 'Sum Path 툴리스트 (자동 산출)', 30, ACCENT, opacity=a)
    cols_per_row = 6 if vertical else len(PP_COLUMNS)
    rows = [PP_COLUMNS[i:i + cols_per_row] for i in range(0, len(PP_COLUMNS), cols_per_row)]
    row_h = (table_rect[3] - table_rect[1]) / len(rows)
    cells = {}
    for r, row in enumerate(rows):
        total = sum(wt for _k, wt in row)
        x = table_rect[0]
        ry = table_rect[1] + r * row_h
        for key, wt in row:
            cw = (table_rect[2] - table_rect[0]) * wt / total
            cells[key] = (x, ry, x + cw, ry + row_h)
            overlay(img, lambda d, _l, x=x, ry=ry, cw=cw: d.rectangle((x, ry, x + cw, ry + row_h * 0.42),
                                                                    fill=(30, 41, 59, 255), outline=(51, 65, 85, 255)), a)
            draw_text(img, (x + cw / 2, ry + row_h * 0.21), key, 26 if not vertical else 28, MUTED, anchor='mm',
                      opacity=a, shadow=False)
            x += cw
    # 토큰 → 열 연결 애니메이션
    step = (dur - 3.0) / len(PP_MAP)
    for i, (li, token, key, value) in enumerate(PP_MAP):
        s = 1.2 + i * step
        k = clamp((t - s) / 0.6)
        if k <= 0:
            continue
        color = PP_COLORS[i]
        tb = _token_box(block[li - 1], token, mono, cx, cy + (li - 1) * lh)
        highlight(img, tb, k, color=color, width=3, radius=6)
        cb = cells[key]
        start = ((tb[0] + tb[2]) / 2, tb[3])
        end = ((cb[0] + cb[2]) / 2, cb[1])
        kk = ease(k)
        mid = (lerp(start[0], end[0], kk), lerp(start[1], end[1], kk))
        line_a = 1.0 - clamp((t - s - 0.6 - step * 0.9) / 0.4)   # 다음 연결이 시작되면 선은 사라진다
        overlay(img, lambda d, _l, st=start, md=mid, c=color: d.line([st, md], fill=tuple(c) + (255,), width=3), line_a)
        if k >= 1:
            draw_text(img, ((cb[0] + cb[2]) / 2, cb[1] + row_h * 0.71), value, 26 if not vertical else 27, color,
                      anchor='mm', opacity=clamp((t - s - 0.6) / 0.3), shadow=False)


# ---------------------------------------------------------------------------
# 3분 설명영상 (1920x1080)
# ---------------------------------------------------------------------------
def long_scenes(A):
    W = 1920
    WIN = (200, 140, 1720, 995)

    def intro(img, t, d):
        a = ease_out(t / 1.0)
        lg = logo_img(A, 260)
        paste_image(img, lg.convert('RGB'), (W / 2 - 130, 230 - (1 - a) * 40), a, radius=40, shadow=True)
        draw_text(img, (W / 2, 540), APP_TITLE, 84, WHITE, anchor='ma', opacity=clamp((t - 0.4) / 0.6))
        draw_text(img, (W / 2, 660), 'NC 프로그램 하나로 툴리스트부터 가공 시뮬레이션까지', 44, ACCENT2, anchor='ma',
                  opacity=clamp((t - 1.0) / 0.6))
        draw_text(img, (W / 2, 750), 'v2.2.8  ·  밀링 3/4/5축  ·  CNC 선반(턴밀)', 32, MUTED, kind='regular', anchor='ma',
                  opacity=clamp((t - 1.6) / 0.6))

    def problem(img, t, d):
        draw_text(img, (W / 2, 150), '현장의 익숙한 고민', 64, WHITE, anchor='ma', opacity=clamp(t / 0.5))
        feature_cards(img, [
            ('툴리스트 수기 작성', '프로그램을 보며 공구명·홀더·길이·회전수를 한 줄씩 옮겨 적기', ACCENT2),
            ('프로그램·공구 불일치', '같은 공구가 여러 공정에 반복되면 누락·중복을 찾기 어려움', (244, 114, 182)),
            ('형상 확인은 CAM PC에서만', '현장 PC에서는 가공 후 모양을 미리 보기 어려움', (96, 165, 250)),
        ], t, (120, 300, 1800, 800), 3, start=0.6, gap=0.7, size=42, sub_size=32)

    def overview(img, t, d):
        draw_text(img, (W / 2, 130), 'Sum Path가 해결하는 4가지', 64, WHITE, anchor='ma', opacity=clamp(t / 0.5))
        feature_cards(img, [
            ('툴리스트 자동 산출', 'NC 파일 → 공구 리스트 · PDF · 표 복사', ACCENT),
            ('CATIA PPTABLE 주석 연동', '포스트가 출력한 공구 주석을 그대로 읽음', ACCENT2),
            ('장비별 모션 · 소재 시뮬레이션', '3/4/5축 MCT · 선반(턴밀) · 가공 후 형상', GREEN),
            ('저사양 PC에서도 가볍게', 'CAD/CAM 없이 NC 파일만 · 자동 해상도 · 안전 모드', (167, 139, 250)),
        ], t, (180, 260, 1740, 900), 2, start=0.8, gap=1.6, size=42, sub_size=32)

    def pptable(img, t, d):
        pptable_graphic(img, A.tool_block, t, d, vertical=False)

    def toollist(img, t, d):
        k = t / d
        app_window(img, A.shot('mill_list'), WIN, FULL, (380, 100, 1920, 520), k, highlights=[
            ((410, 50, 490, 110), 0.05, 'Tool List 버튼', ACCENT2),
            ((530, 260, 1905, 440), 0.35, '공구별 한 줄 · 반복 공구 N번호 정리', GREEN),
            ((1380, 120, 1618, 162), 0.7, 'PDF 출력 · 표 복사(엑셀)', ACCENT),
        ])

    def lathelist(img, t, d):
        k = t / d
        app_window(img, A.shot('lathe_list'), WIN, FULL, (440, 100, 1920, 470), k, highlights=[
            ((530, 220, 1150, 460), 0.2, '홀더 · 인서트 주석', ACCENT2),
            ((700, 200, 1000, 460), 0.55, 'ISO 규격 → R · PITCH 자동', GREEN),
        ])

    def real(img, t, d):
        if t < d * 0.35:
            k = t / (d * 0.35)
            app_window(img, A.shot('real_list'), WIN, FULL, (0, 100, 1920, 900), k,
                       highlights=[((0, 150, 520, 1075), 0.3, '32,903줄 5축 실가공 프로그램', ACCENT2)])
        else:
            k = (t - d * 0.35) / (d * 0.65)
            frame_player(img, A.real_rotate, WIN, k, (560, 160, 1880, 990),
                         opacity=clamp((t - d * 0.35) / 0.4))
            chip(img, (WIN[0] + 30, WIN[1] + 30), '5축 MCT (A to C)  ·  공정별 색 툴패스', 30, ACCENT2)

    def machines(img, t, d):
        names = ['3축 MCT (X Y Z)', '4축 MCT (B-Type)', '5축 MCT (A to C)', '5축 MCT (B to C)', 'CNC 선반 (턴밀 포함)']
        for i, name in enumerate(names):
            a = ease_out((t - 0.4 - i * 0.5) / 0.5)
            chip(img, (130, 200 + i * 105), name, 36, ACCENT if i != 4 else ACCENT2, opacity=a)
        shot = A.shot('machine_5ax_panel' if t < d * 0.6 else 'machine_lathe_panel')
        a = clamp((t - 0.8) / 0.5)
        rect = paste_fit(img, shot.crop(MACHINE_PANEL), (760, 190, 1780, 760), a, radius=14)
        draw_text(img, (rect[0], rect[3] + 26), '장비별 행정 · 회전축 범위를 기록해 그 장비의 모션으로 경로를 그립니다', 30, MUTED,
                  kind='regular', opacity=a, max_w=1020)

    def stock(img, t, d):
        a = clamp(t / 0.5)
        paste_fit(img, A.shot('mill_stock_dialog'), (120, 170, 700, 960), a, radius=12, border=ACCENT2)
        if t < d * 0.45:
            paste_fit(img, A.shot('mill_toolpath').crop(VIEW3D), (780, 170, 1820, 900), a, radius=14)
            chip(img, (800, 190), '소재 적용 전 · 툴패스', 28, (71, 85, 105), opacity=a)
        else:
            b = clamp((t - d * 0.45) / 0.5)
            paste_fit(img, A.shot('mill_stock_ready').crop(VIEW3D), (780, 170, 1820, 900), b, radius=14)
            chip(img, (800, 190), '소재 100 × 80 × 30 적용', 28, ACCENT2, opacity=b)
        highlight(img, (130, 175, 690, 400), clamp((t - 1.0) / 0.6), color=ACCENT2, label='치수 · 축 배정 · 기준 위치',
                  label_above=False)

    def mill_sim(img, t, d):
        k = clamp((t - 0.3) / (d * 0.78))
        frame_player(img, A.mill_sim, WIN, k, (700, 180, 1760, 980))
        label = re.sub(r' \| \d+:\d+$', '', A.mill_sim.label(k)) or '가공 시작 전'
        chip(img, (WIN[0] + 30, WIN[1] + 30), label, 30, ACCENT2)
        if t > d * 0.86:
            b = clamp((t - d * 0.86) / 0.4)
            paste_fit(img, A.shot('mill_sim_done').crop(PROCESS_LIST), (WIN[2] - 560, WIN[3] - 250, WIN[2] - 20, WIN[3] - 20),
                      b, radius=10, border=GREEN)

    def lathe_sim(img, t, d):
        a = clamp(t / 0.4)
        paste_fit(img, A.shot('lathe_stock_dialog'), (90, 200, 560, 830), a, radius=12, border=ACCENT2)
        k = clamp((t - 0.8) / (d * 0.8))
        frame_player(img, A.lathe_sim, (620, 150, 1840, 990), k, (800, 200, 1650, 920))
        label = re.sub(r' \| \d+:\d+$', '', A.lathe_sim.label(k)) or '가공 시작 전'
        chip(img, (650, 175), 'CNC 선반  ·  %s' % label, 30, ACCENT2)

    def lowspec(img, t, d):
        draw_text(img, (W / 2, 120), '저사양 PC에서도 가볍게', 64, WHITE, anchor='ma', opacity=clamp(t / 0.5))
        feature_cards(img, [
            ('CAD · CAM 없이 NC 파일만', '설치 파일 하나(Windows) · 파일 더블클릭으로 바로 열기', ACCENT),
            ('시뮬레이션 해상도 자동', '소재 크기에 맞춰 계산량을 자동 조절 · 직접 지정도 가능', GREEN),
            ('백그라운드 계산', '긴 계산은 뒤에서 · 다른 공정을 고르면 즉시 취소 후 재계산', ACCENT2),
            ('그래픽 안전 모드', '그래픽 드라이버 문제 시 3D만 끄고 툴리스트 · PDF는 계속 사용', (167, 139, 250)),
        ], t, (180, 250, 1740, 900), 2, start=0.6, gap=1.4, size=40, sub_size=30)

    def outro(img, t, d):
        a = ease_out(t / 0.8)
        lg = logo_img(A, 200)
        paste_image(img, lg.convert('RGB'), (W / 2 - 100, 220), a, radius=32)
        draw_text(img, (W / 2, 470), APP_TITLE, 80, WHITE, anchor='ma', opacity=a)
        draw_text(img, (W / 2, 590), '프로그램 작성 → 툴리스트 → 형상 확인, 한 번에', 46, ACCENT2, anchor='ma',
                  opacity=clamp((t - 0.6) / 0.6))
        draw_text(img, (W / 2, 690), 'Python · PyQt5 · pyqtgraph(OpenGL) · NumPy/Numba · ReportLab', 28, MUTED,
                  kind='regular', anchor='ma', opacity=clamp((t - 1.2) / 0.6))

    return [
        Scene(7, 'NC 프로그램 하나로, 툴리스트부터 가공 시뮬레이션까지. Sum Path NC 툴리스트를 소개합니다.', intro),
        Scene(11, '공구 리스트를 손으로 옮겨 적고, 프로그램과 공구가 맞는지 일일이 확인하고, 가공 후 형상은 CAM PC에서만 볼 수 있었습니다.',
              problem, '01  현장의 고민'),
        Scene(13, 'Sum Path는 네 가지로 이 고민을 줄입니다. 툴리스트 자동 산출, CATIA 주석 연동, 장비별 모션과 소재 시뮬레이션, '
                  '그리고 저사양 PC에서도 가벼운 동작입니다.', overview, '02  핵심 기능'),
        Scene(24, '먼저 CATIA 포스트프로세서의 PPTABLE에서, 공구 교체마다 공구 정보 주석이 출력되도록 한 번만 설정해 둡니다. '
                  '공구명과 SO, 홀더, 길이와 지름, 회전수와 이송이 주석으로 함께 나오면, Sum Path가 이 주석을 읽어 툴리스트 칸에 그대로 채웁니다.',
              pptable, '03  CATIA PPTABLE 주석 설정'),
        Scene(17, 'NC 파일을 열고 툴리스트 버튼을 누르면 끝입니다. 같은 공구가 여러 번 쓰여도 한 줄로 묶고, 사용한 N번호를 비고에 정리합니다. '
                  'PDF 출력과 표 복사로 현장 배포도 바로 됩니다.', toollist, '04  툴리스트 자동 산출'),
        Scene(12, '선반 프로그램은 홀더와 인서트 주석을 읽고, ISO 인서트 규격에서 코너 R과 나사 피치까지 자동으로 채웁니다.',
              lathelist, '04  선반 툴리스트'),
        Scene(14, '3만 줄이 넘는 실제 5축 가공 프로그램도 그대로 읽어, 공구 리스트와 공정별 색으로 구분된 3D 툴패스를 보여 줍니다.',
              real, '05  실가공 5축 프로그램'),
        Scene(14, '장비 타입은 3축, 4축, 5축 A to C와 B to C, 그리고 턴밀을 포함한 CNC 선반까지. '
                  '장비별 행정과 회전축 범위를 기록해 그 장비의 모션으로 경로를 그립니다.', machines, '06  장비별 모션'),
        Scene(12, '소재 창에서 크기와 축 배정, 기준 위치를 넣고 적용하면, 가공 전 소재가 툴패스와 함께 나타납니다.',
              stock, '07  소재 설정'),
        Scene(19, '이제 공정 순서대로 소재가 깎이며 최종 형상이 만들어집니다. 공정별 색으로 어느 공구가 어디를 가공했는지 한눈에 확인할 수 있고, '
                  '공정마다 가공 시간도 함께 계산됩니다.', mill_sim, '08  형상 시뮬레이션 · 밀링'),
        Scene(15, '선반도 마찬가지입니다. 지름과 길이를 넣으면 회전체 소재 위에 황삭, 정삭, 홈, 나사 가공이 차례로 나타납니다.',
              lathe_sim, '09  형상 시뮬레이션 · 선반'),
        Scene(18, '무거운 CAD나 CAM 없이 NC 파일만 있으면 됩니다. 시뮬레이션 해상도는 자동으로 맞추고 계산은 백그라운드에서 처리하며, '
                  '그래픽 드라이버 문제가 있는 PC는 안전 모드로 툴리스트와 PDF 출력을 계속 쓸 수 있습니다.', lowspec, '10  저사양 PC'),
        Scene(9, '프로그램 작성에서 툴리스트, 형상 확인까지. Sum Path NC 툴리스트.', outro),
    ]


# ---------------------------------------------------------------------------
# 쇼츠 (1080x1920)
# ---------------------------------------------------------------------------
def short_scenes(A):
    W = 1080
    MEDIA = (40, 520, 1040, 1420)

    def hook(img, t, d):
        a = ease_out(t / 0.6)
        draw_text(img, (W / 2, 640 - (1 - a) * 60), '툴리스트,\n아직도 손으로\n쓰세요?', 110, WHITE, anchor='ma', opacity=a,
                  align='center', spacing=1.2)
        lg = logo_img(A, 170)
        paste_image(img, lg.convert('RGB'), (W / 2 - 85, 1150), clamp((t - 0.8) / 0.5), radius=28)

    def pptable(img, t, d):
        pptable_graphic(img, A.tool_block, t, d, vertical=True)

    def toollist(img, t, d):
        a = clamp(t / 0.4)
        chip(img, (40, 470), '밀링', 30, ACCENT, opacity=a)
        r1 = paste_fit(img, A.shot('mill_list').crop((528, 195, 1250, 440)), (40, 530, 1040, 900), a, radius=10)
        highlight(img, (r1[0], r1[1] + (r1[3] - r1[1]) * 0.27, r1[2], r1[3]), clamp((t - 0.8) / 0.6), color=GREEN,
                  width=4, label='공구별 한 줄 자동 정리', label_size=30, label_above=False)
        b = clamp((t - 1.6) / 0.4)
        chip(img, (40, 1010), '선반', 30, ACCENT2, opacity=b)
        paste_fit(img, A.shot('lathe_list').crop((528, 195, 1250, 460)), (40, 1070, 1040, 1420), b, radius=10)
        paste_fit(img, A.shot('mill_list').crop((1380, 118, 1618, 164)), (240, 1440, 840, 1520),
                  clamp((t - 2.6) / 0.4), radius=10, border=ACCENT2)

    def mill(img, t, d):
        frame_player(img, A.mill_sim, MEDIA, clamp((t - 0.2) / (d * 0.85)), PART)
        chip(img, (MEDIA[0] + 24, MEDIA[1] + 24), '밀링 · 소재 100×80×30', 34, ACCENT2)

    def machines(img, t, d):
        if t < d * 0.55:
            frame_player(img, A.lathe_sim, MEDIA, clamp(t / (d * 0.5)), LPART)
            chip(img, (MEDIA[0] + 24, MEDIA[1] + 24), 'CNC 선반 (턴밀)', 34, ACCENT2)
        else:
            frame_player(img, A.real_rotate, MEDIA, clamp((t - d * 0.55) / (d * 0.45)), RPART)
            chip(img, (MEDIA[0] + 24, MEDIA[1] + 24), '5축 MCT (A to C)', 34, ACCENT2)

    def lowspec(img, t, d):
        feature_cards(img, [
            ('CAD · CAM 없이 NC 파일만', '설치 파일 하나 · NC 파일 더블클릭으로 바로 열기', ACCENT),
            ('해상도 자동 · 백그라운드 계산', '소재 크기에 맞춰 계산량 자동 조절', GREEN),
            ('그래픽 안전 모드', '그래픽 문제 PC도 툴리스트 · PDF는 그대로', (167, 139, 250)),
        ], t, (80, 540, 1000, 1400), 1, start=0.2, gap=0.5, size=50, sub_size=36)

    def outro(img, t, d):
        a = ease_out(t / 0.6)
        lg = logo_img(A, 260)
        paste_image(img, lg.convert('RGB'), (W / 2 - 130, 520), a, radius=40)
        draw_text(img, (W / 2, 860), 'Sum Path\nNC Tool List', 96, WHITE, anchor='ma', opacity=a, align='center')
        draw_text(img, (W / 2, 1140), 'NC 파일 → 툴리스트 → 형상 확인', 50, ACCENT2, anchor='ma',
                  opacity=clamp((t - 0.5) / 0.5))

    return [
        Scene(3.5, '툴리스트, 아직도 손으로 쓰세요?', hook),
        Scene(10, 'CATIA PPTABLE에 공구 주석만 설정하면, NC 파일에서 툴리스트가 자동으로 만들어집니다.', pptable,
              'CATIA 주석 → 툴리스트'),
        Scene(6, 'PDF 출력, 엑셀 표 복사까지 버튼 하나.', toollist, '버튼 하나로 산출'),
        Scene(8, '소재를 설정하면 가공 형상이 공정 순서대로 시뮬레이션됩니다.', mill, '소재 · 형상 시뮬레이션'),
        Scene(8, '3축, 5축부터 선반 턴밀까지, 장비별 모션 그대로.', machines, '장비별 모션'),
        Scene(6, 'CAM 없이, 저사양 PC에서도 가볍게.', lowspec, '저사양 PC OK'),
        Scene(4, 'Sum Path NC 툴리스트.', outro),
    ]


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------
_ASSETS = None


def render_segment(job):
    """프레임 구간 [f0, f1)을 렌더링해 영상 조각으로 저장한다(프로세스별 실행)."""
    global _ASSETS
    name, durations, size, fps, f0, f1, out = job
    if _ASSETS is None:
        _ASSETS = Assets()
    scenes = (short_scenes if name == 'Shorts' else long_scenes)(_ASSETS)
    for sc, d in zip(scenes, durations):
        sc.dur = d
    vertical = name == 'Shorts'
    starts, t0 = [], 0.0
    for sc in scenes:
        starts.append(t0)
        t0 += sc.dur
    total = t0
    xfade = 0.4
    bg = vk.background(*((1080, 1920) if vertical else (1920, 1080)))

    def compose(i, t):
        img = bg.copy()
        sc = scenes[i]
        sc.draw(img, t, sc.dur)
        draw_header(img, sc, t, vertical)
        draw_caption(img, sc, t, vertical)
        return img

    writer = vk.VideoWriter(out, size, fps)
    last = {}
    for f in range(f0, f1):
        gt = f / fps
        i = max(j for j, s in enumerate(starts) if gt >= s)
        lt = gt - starts[i]
        img = compose(i, lt)
        if i > 0 and lt < xfade:
            if (i - 1) not in last:
                last[i - 1] = compose(i - 1, scenes[i - 1].dur - 0.01)
            img = Image.blend(last[i - 1], img, ease(lt / xfade))
        vk.progress_bar(img, gt / total, ACCENT2 if vertical else ACCENT, 8 if vertical else 5)
        if img.size != tuple(size):
            img = img.resize(tuple(size), Image.BILINEAR)
        writer.write(img)
    writer.close()
    return out


def render(name, scenes, size, fps, tts, voice, preview=False):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    work = BUILD / ('work_' + name)
    work.mkdir(parents=True, exist_ok=True)
    vertical = size[1] > size[0]

    voice_clips = []
    if tts:
        print('[%s] 나레이션 합성(edge-tts, %s)...' % (name, voice), flush=True)
        for i, sc in enumerate(scenes):
            clip = work / ('voice_%02d.mp3' % i)
            length = vk.synth_tts(tts_text(sc.narration), clip, voice)
            if length + 0.9 > sc.dur:
                print('  장면 %d: 나레이션 %.1fs → 장면 길이 %.1fs → %.1fs로 늘림' % (i + 1, length, sc.dur, length + 0.9))
                sc.dur = length + 0.9
            voice_clips.append((clip, length))

    starts, t0 = [], 0.0
    for sc in scenes:
        starts.append(t0)
        t0 += sc.dur
    total = t0
    if preview:
        size, fps = (size[0] // 2, size[1] // 2), 12
    nframes = int(total * fps)
    print('[%s] %dx%d, %.1f초, %d프레임 렌더링...' % (name, size[0], size[1], total, nframes), flush=True)

    durations = [sc.dur for sc in scenes]
    workers = max(1, min(os.cpu_count() or 1, 8))
    bounds = [nframes * k // workers for k in range(workers + 1)]
    jobs = [(name, durations, size, fps, bounds[k], bounds[k + 1], str(work / ('seg_%02d.mp4' % k)))
            for k in range(workers) if bounds[k + 1] > bounds[k]]
    began = time.time()
    print('  병렬 렌더링: %d개 작업' % len(jobs), flush=True)
    if len(jobs) == 1:
        render_segment(jobs[0])
    else:
        with multiprocessing.Pool(len(jobs)) as pool:
            for done in pool.imap_unordered(render_segment, jobs):
                print('  구간 완료: %s (%.0fs)' % (Path(done).name, time.time() - began), flush=True)
    silent = work / 'video.mp4'
    vk.concat([j[-1] for j in jobs], silent)

    bgm = work / 'bgm.wav'
    vk.synth_bgm(total + 0.5, bgm, bpm=104 if vertical else 96, seed=3 if vertical else 7)
    out = OUTPUT / ('SumPath_%s%s.mp4' % (name, '_preview' if preview else ''))
    clips = [(c, starts[i] + 0.35) for i, (c, _len) in enumerate(voice_clips)]
    vk.mux(silent, bgm, out, clips)

    # 자막 파일(.srt) — 유튜브 업로드용
    lines, n = [], 1
    for i, sc in enumerate(scenes):
        for text, s, e in chunk_times(sc.narration, starts[i], sc.dur):
            lines += [str(n), '%s --> %s' % (vk.srt_time(s), vk.srt_time(e)), text, '']
            n += 1
    out.with_suffix('.srt').write_text('\n'.join(lines), encoding='utf-8')
    print('[%s] 완료 → %s (%.0fs)' % (name, out, time.time() - began), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description='Sum Path 홍보영상 생성')
    ap.add_argument('--shorts', action='store_true', help='쇼츠(세로 1080x1920)')
    ap.add_argument('--long', action='store_true', help='약 3분 설명영상(1920x1080)')
    ap.add_argument('--all', action='store_true', help='둘 다')
    ap.add_argument('--tts', action='store_true', help='edge-tts 한국어 나레이션 넣기(인터넷 필요)')
    ap.add_argument('--voice', default='ko-KR-SunHiNeural', help='ko-KR-SunHiNeural(여) / ko-KR-InJoonNeural(남)')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--preview', action='store_true', help='절반 해상도·12fps 빠른 확인용')
    args = ap.parse_args()
    if not (args.shorts or args.long or args.all):
        args.all = True
    if args.tts and not vk.tts_available():
        sys.exit('edge-tts가 없습니다: pip install edge-tts')
    assets = Assets()
    if args.shorts or args.all:
        render('Shorts', short_scenes(assets), (1080, 1920), args.fps, args.tts, args.voice, args.preview)
    if args.long or args.all:
        render('Explainer', long_scenes(assets), (1920, 1080), args.fps, args.tts, args.voice, args.preview)


if __name__ == '__main__':
    main()
