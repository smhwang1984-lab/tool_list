"""lathe_insert_spec.py — 선반 인서트·홀더 규격표와 툴리스트 자동 입력 (v2.1.0).

선반 형상 시뮬레이션이 쓸 공구 데이터의 기반이다. Qt 비의존 · 밀링과 완전 분리.

- ISO 1832 선삭 인서트 코드(CNMG 120408 ...)를 형상/여유각/내접원/두께/노즈 R로 푼다.
- 나사 인서트(16ER 1.5 ISO ...)에서 외경/내경·방향·피치를 읽는다.
- 홈 인서트는 규격이 제조사마다 달라 잘 알려진 표기 몇 가지(N123..., MGMN..., GTN-.., GIP ...)만
  읽고, 그 밖에는 툴리스트의 R / T(홈 폭) / PITCH 칸에 사용자가 직접 넣는다.
- ISO 5608 홀더 코드(PCLNR 2525M 12 ...)에서 접근각·좌우(방향)·섕크를 읽는다.
- 값의 출처와 우선순위(앞이 이긴다):
    R, T   : NC 주석 태그 > 직접 입력 저장값 > 인서트 문구의 R > ISO 규격 해석
    PITCH  : NC 주석 태그 > 인서트 표기(16ER 1.5 ISO) > 프로그램 G76/G32의 F > 직접 입력 저장값
    종류/방향: 직접 입력 저장값(홀더+인서트별) > 자동 추천
  저장값이 BLANK('-')이면 "일부러 비운 칸"으로 보고 자동 추천도 채우지 않는다.
  프로그램에서 온 값(태그/인서트 표기/G76·G32)은 저장값보다 우선하므로, 툴리스트에서 그 값을 고쳐도
  저장하지 않고 이번 표에서만 유지한다(PROGRAM_SPECIFIC_SOURCES).

읽지 못한 값은 절대 지어내지 않고 빈 문자열로 둔다."""
import functools
import json
import math
import os
import re

# --------------------------------------------------------------------------
# 표 (ISO 1832 / ISO 5608)
# --------------------------------------------------------------------------

# 인서트 형상 문자 -> (이름, 날끝각°). R(원형)은 각이 없다.
INSERT_SHAPES = {
    'C': ('80° 마름모', 80.0),
    'D': ('55° 마름모', 55.0),
    'E': ('75° 마름모', 75.0),
    'M': ('86° 마름모', 86.0),
    'V': ('35° 마름모', 35.0),
    'S': ('정사각형', 90.0),
    'T': ('정삼각형', 60.0),
    'W': ('80° 트라이곤', 80.0),
    'R': ('원형', None),
}
# 여유각 문자 -> °
CLEARANCE_ANGLES = {'A': 3.0, 'B': 5.0, 'C': 7.0, 'D': 15.0, 'E': 20.0, 'F': 25.0,
                    'G': 30.0, 'N': 0.0, 'P': 11.0}
# 두께 코드 -> mm
THICKNESS_MM = {'01': 1.59, 'T1': 1.98, '02': 2.38, '03': 3.18, 'T3': 3.97, '04': 4.76,
                '05': 5.56, '06': 6.35, '07': 7.94, '09': 9.52}
# 표준 내접원(mm) — 인치계열(6.35 = 1/4")와 미터계열
IC_INCH = (3.97, 4.76, 5.56, 6.35, 7.94, 9.525, 12.7, 15.875, 19.05, 25.4, 31.75)
IC_METRIC = (6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 25.0)
_IC_ALL = tuple(sorted(set(IC_INCH) | set(IC_METRIC)))

# 홀더(ISO 5608) 접근각(공구 주절인각) — 형태 문자 -> °
HOLDER_APPROACH_ANGLES = {
    'A': 90.0, 'B': 75.0, 'C': 90.0, 'D': 45.0, 'E': 60.0, 'F': 90.0, 'G': 90.0,
    'H': 107.5, 'J': 93.0, 'K': 75.0, 'L': 95.0, 'M': 50.0, 'N': 63.0, 'P': 117.5,
    'R': 75.0, 'S': 45.0, 'T': 60.0, 'U': 93.0, 'V': 72.5, 'W': 60.0, 'Y': 85.0,
}
# 홀더 전체 길이 문자 -> mm
HOLDER_LENGTHS = {'A': 32, 'B': 40, 'C': 50, 'D': 60, 'E': 70, 'F': 80, 'G': 90, 'H': 100,
                  'J': 110, 'K': 125, 'L': 140, 'M': 150, 'N': 160, 'P': 170, 'Q': 180,
                  'R': 200, 'S': 250, 'T': 300, 'U': 350, 'V': 400, 'W': 450, 'Y': 500}

# 툴리스트 열 값
KINDS = ('외경', '내경', '외경홈', '내경홈', '정면홈', '외경나사', '내경나사', '절단',
         '드릴', '엔드밀', '페이스커터', '비절삭')
# 턴밀(M35 구동공구)·중심 드릴 — 지름(D)이 필요하다
MILLING_KINDS = ('드릴', '엔드밀', '페이스커터')
NON_CUTTING_KIND = '비절삭'
# 인선(가상 인선 번호) — 노즈 중심에서 가상 인선(프로그램 좌표점)이 있는 방향.
# 화면에서 X(반경)가 위, Z가 오른쪽(+Z = 심압대 쪽) 기준:
#   1 = 우상(+X +Z), 2 = 우하(-X +Z), 3 = 좌하(-X -Z), 4 = 좌상(+X -Z), 9 = 노즈 중심.
# 외경 우수 공구(척 쪽 -Z로 깎음)는 3, 외경 좌수는 2, 내경 우수는 4, 내경 좌수는 1.
TIPS = ('1', '2', '3', '4', '9')
TIP_LABELS = {'1': '1 (우상)', '2': '2 (우하)', '3': '3 (좌하)', '4': '4 (좌상)', '9': '9 (중심)'}
DIRECTIONS = ('R', 'L', 'N')
DIRECTION_LABELS = {'R': 'R (우수)', 'L': 'L (좌수)', 'N': 'N (중립)'}

SOURCE_TAG = 'NC 주석 태그'
SOURCE_INSERT = '인서트 표기'
SOURCE_PROGRAM = '프로그램(G76/G32)'
SOURCE_SAVED = '직접 입력(저장)'
SOURCE_TEXT = '인서트 문구'
SOURCE_ISO = 'ISO 규격 해석'
SOURCE_AUTO = '자동 추천'
SOURCE_MANUAL = '직접 입력(이번 표만)'
# 저장소에 넣는 "일부러 비움" 표식 — 잘못된 자동 추천을 지웠을 때 다음 파싱에서 되살아나지 않게 한다.
BLANK = '-'
# 프로그램(주석 태그/인서트 표기/G76·G32)에서 온 값 — 인서트 이름별 저장값보다 우선하므로,
# 이 값을 [수정]에서 고쳐도 저장값으로는 다시 적용되지 않는다(이번 표에서만 유지).
PROGRAM_SPECIFIC_SOURCES = (SOURCE_TAG, SOURCE_INSERT, SOURCE_PROGRAM)

# --------------------------------------------------------------------------
# 정규식
# --------------------------------------------------------------------------

# ISO 1832 선삭 인서트: 형상 여유각 공차 고정 + 크기(2) 두께(2, 또는 T#) [노즈 R(2)]
INSERT_RE = re.compile(
    r'(?<![A-Z0-9])([CDEMVSTWR])([ABCDEFGNP])([AFCHEGJKLMNU])([ABFGHJMNQRTUWX])'
    r'\s*(\d{2})\s*(T\d|\d{2})\s*(\d{2})?(?!\d)', re.I)
# 나사 인서트: 길이 [E|I][R|L] 피치 [규격]  (예: 16ER 1.5 ISO, 16IR 14W, 22ER 3.0 ISO)
THREAD_INSERT_RE = re.compile(
    r'(?<![A-Z0-9])(\d{2})\s*([EI])\s*([RL])\s*(\d+(?:[.,]\d+)?)\s*(ISO|UNJ|UNC|UNF|UNEF|UNS|UN|W|NPTF|NPT|BSPT|BSPP|G|ACME)?'
    r'(?![A-Z0-9])', re.I)
# 부분 프로파일 나사 인서트: 16ER AG60, 16IR A60 (피치 없음)
THREAD_PARTIAL_RE = re.compile(
    r'(?<![A-Z0-9])(\d{2})\s*([EI])\s*([RL])\s*(?:A|AG|N|NG|G)\s*(55|60)(?![0-9])', re.I)
# 잘 알려진 홈 인서트 표기
GROOVE_N123_RE = re.compile(r'(?<![A-Z0-9])N123[A-Z]\d?\s*-\s*(\d{4})(?:\s*-\s*(\d{4}))?', re.I)
GROOVE_MGXN_RE = re.compile(r'(?<![A-Z0-9])M[GR][GM]N\s*(\d{3,4})(?![0-9])', re.I)
GROOVE_GTN_RE = re.compile(r'(?<![A-Z0-9])GTN\s*-?\s*(\d+(?:\.\d+)?)(?![0-9.])', re.I)
GROOVE_GIP_RE = re.compile(r'(?<![A-Z0-9])GIP\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)', re.I)
# ISO 5608 홀더: 클램프 인서트형상 접근각 여유각 좌우 [섕크 폭x높이 길이] [인서트 크기]
HOLDER_RE = re.compile(
    r'(?<![A-Z])([A-Z])([CDEMVSTWRKLABHOP])([A-Z])([A-Z])([RLN])'
    r'(?:\s*(\d{2})(\d{2})\s*([A-Z])?)?\s*(\d{2})?(?![0-9])', re.I)
# ISO 5608 형식이 아닌 홀더(홈/나사/절단용: MGEHR 2525-3, SER 2525M16)의 좌우 — 코드 끝 R/L + 섕크
HOLDER_HAND_RE = re.compile(r'(?<![A-Z])[A-Z]{2,5}([RL])\s*\d{4}(?![0-9])', re.I)
# 내경 바(boring bar) 접두어: S25T-PCLNR, A32S-MCLNR
BAR_PREFIX_RE = re.compile(r'(?<![A-Z0-9])[A-Z]\d{2}[A-Z]\s*-?\s*[A-Z]{4,5}[RLN]', re.I)
# 문구 안 노즈 R 표기: "| R-0.8", "R0.4"
TEXT_R_RE = re.compile(r'(?<![A-Za-z0-9])R\s*[-=]?\s*(\d+(?:\.\d+)?)(?![0-9.]*[A-Za-z])')

# NC 주석 태그: [R 0.8] [T 3.0] [P 1.5] / [PITCH 1.5] / [D 10](턴밀 공구 지름)
TAG_RES = {
    'D': re.compile(r'\[\s*D\s*=?\s*([\d.]+)\s*\]', re.I),
    'R': re.compile(r'\[\s*R\s*=?\s*([\d.]+)\s*\]', re.I),
    'T': re.compile(r'\[\s*T\s*=?\s*([\d.]+)\s*\]', re.I),
    'PITCH': re.compile(r'\[\s*P(?:ITCH)?\s*=?\s*([\d.]+)\s*\]', re.I),
}

_KW_NONCUT = re.compile(r'SETTING[\s.-]*PIN|NULLING|KNURL|ROLLE|널링|세팅', re.I)
_KW_DRILL = re.compile(r'드릴|DRILL|CENTER|CENTRE|센터', re.I)
_KW_FACECUT = re.compile(r'FACE[\s-]*(?:CUTTER|MILL)|페이스', re.I)
_KW_ENDMILL = re.compile(r'END[\s-]*MILL|엔드밀|E/M', re.I)
# 공구 지름 표기: "D10 X 90 NC DRILL", "D5.5 CARBIDE DRILL", "D3. FLAT END MILL", "MTI 0808 D30 A60"
TOOL_D_RE = re.compile(r'(?<![A-Z0-9.])D\s*(\d+(?:\.\d+)?)(?![0-9A-Za-z])', re.I)
_KW_CUTOFF = re.compile(r'절단|CUT[\s-]?OFF|PARTING', re.I)
_KW_THREAD = re.compile(r'나사|THREAD|THRD', re.I)
_KW_GROOVE = re.compile(r'홈|GROOV|GRV', re.I)
_KW_FACE = re.compile(r'정면|\bFACE\b', re.I)
_KW_INTERNAL = re.compile(r'내경|BORING|\bBORE\b|(?<![A-Z])ID(?![A-Z])|INTERNAL', re.I)
_KW_EXTERNAL = re.compile(r'외경|(?<![A-Z])OD(?![A-Z])|EXTERNAL|TURNING', re.I)

_GCODE_THREAD_RE = re.compile(r'G(?:76|32)(?!\d)', re.I)
_GCODE_GROOVE_RE = re.compile(r'G75(?!\d)', re.I)
_GCODE_FACE_GROOVE_RE = re.compile(r'G74(?!\d)', re.I)
_GCODE_TURN_CYCLE_RE = re.compile(r'G7[0-3](?!\d)', re.I)
_F_WORD_RE = re.compile(r'F\s*([\d.]+)', re.I)


# --------------------------------------------------------------------------
# 유틸
# --------------------------------------------------------------------------

def fmt_number(value):
    """3.0 -> '3', 0.8 -> '0.8', None -> ''."""
    if value is None:
        return ''
    text = ('%.3f' % float(value)).rstrip('0').rstrip('.')
    return text or '0'


def normalize_key(text):
    """저장소 키 — 태그·대소문자·공백 차이를 없앤다."""
    text = str(text or '')
    for pattern in TAG_RES.values():
        text = pattern.sub('', text)
    return re.sub(r'\s+', ' ', text).strip().upper()


def strip_tags(text):
    """표시 문구에서 [R ..]/[T ..]/[P ..] 태그를 걷어낸다."""
    text = str(text or '')
    for pattern in TAG_RES.values():
        text = pattern.sub('', text)
    return text.strip()


def find_tags(text):
    """text 안의 태그 값을 {'R': '0.8', ...}로 돌려준다(없는 것은 생략)."""
    found = {}
    for key, pattern in TAG_RES.items():
        match = pattern.search(str(text or ''))
        if match:
            value = _clean_number(match.group(1))
            if value:
                found[key] = value
    return found


def _cached_dict(function):
    """텍스트 -> dict 해석 결과를 캐시한다(표를 새로 그릴 때마다 같은 문구를 다시 풀지 않게).
    호출자가 마음대로 고쳐도 되도록 복사본을 돌려준다."""
    cached = functools.lru_cache(maxsize=1024)(function)

    @functools.wraps(function)
    def wrapper(text):
        result = cached(str(text or ''))
        return None if result is None else dict(result)

    return wrapper


def _clean_number(text):
    try:
        return fmt_number(float(str(text).replace(',', '.')))
    except (TypeError, ValueError):
        return ''


def _float(text):
    try:
        return float(str(text).strip().replace(',', '.'))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# ISO 1832 인서트
# --------------------------------------------------------------------------

def edge_length_from_ic(shape, ic):
    """내접원 지름 ic(mm)에서 절삭날 길이(mm). 원형은 None."""
    if shape == 'R':
        return None
    if shape == 'S':
        return ic
    if shape == 'T':
        return ic * math.sqrt(3.0)
    if shape == 'W':                        # 80°/160° 교대 육각 — 이웃 두 꼭짓점의 접선 길이 합
        r = ic / 2.0
        return r * (1.0 / math.tan(math.radians(40.0)) + 1.0 / math.tan(math.radians(80.0)))
    angle = INSERT_SHAPES[shape][1]
    return ic / math.sin(math.radians(angle))


def size_code_for_ic(shape, ic):
    """ISO 1832 크기 코드(정수, 자릿수 2) — 절삭날 길이(원형은 지름)를 내림한 값."""
    length = ic if shape == 'R' else edge_length_from_ic(shape, ic)
    return int(math.floor(length + 0.05))


def ic_for_size_code(shape, code, clearance='N'):
    """크기 코드에서 내접원 지름을 찾는다. (ic, 대안 목록) — 못 찾으면 (None, []).
    후보가 둘 이상(12.0/12.7처럼)이면 인치계열을 우선하고, 원형 + 여유각이 N이 아니면
    미터계열을 우선한다(RNMG 1204 = 12.7, RCMT 1204 = 12.0)."""
    candidates = [ic for ic in _IC_ALL if size_code_for_ic(shape, ic) == code]
    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], []
    prefer_metric = shape == 'R' and clearance != 'N'
    preferred = IC_METRIC if prefer_metric else IC_INCH
    picked = [ic for ic in candidates if ic in preferred]
    ic = picked[0] if picked else candidates[0]
    return ic, [c for c in candidates if c != ic]


@_cached_dict
def parse_insert(text):
    """텍스트에서 ISO 1832 선삭 인서트 코드를 찾아 푼다. 없으면 None.

    돌려줌: dict — code, shape, shape_name, angle, clearance, clearance_angle, ic,
    ic_alt(애매할 때 다른 후보), edge_length, thickness, nose_r."""
    match = INSERT_RE.search(str(text or ''))
    if not match:
        return None
    shape, clear, tol, mount, size, thick, nose = (g.upper() if g else g for g in match.groups())
    if thick not in THICKNESS_MM:
        return None
    ic, alt = ic_for_size_code(shape, int(size), clear)
    info = {
        'code': '%s%s%s%s %s%s%s' % (shape, clear, tol, mount, size, thick, nose or ''),
        'shape': shape,
        'shape_name': INSERT_SHAPES[shape][0],
        'angle': INSERT_SHAPES[shape][1],
        'clearance': clear,
        'clearance_angle': CLEARANCE_ANGLES.get(clear),
        'tolerance': tol,
        'mounting': mount,
        'size_code': int(size),
        'ic': ic,
        'ic_alt': tuple(alt),
        'edge_length': None if ic is None else edge_length_from_ic(shape, ic),
        'thickness': THICKNESS_MM[thick],
        'nose_r': None,
    }
    if shape == 'R':
        info['nose_r'] = None if ic is None else ic / 2.0
    elif nose and int(nose) > 0:              # '00'은 날끝이 날카롭거나 미지정 — R 값을 지어내지 않는다
        info['nose_r'] = int(nose) / 10.0
    return info


TPI_FORMS = ('UN', 'UNJ', 'UNC', 'UNF', 'UNEF', 'UNS', 'W', 'NPT', 'NPTF', 'BSPT', 'BSPP', 'G')


@_cached_dict
def parse_thread_insert(text):
    """나사 인서트(16ER 1.5 ISO / 16IR AG60 ...). 없으면 None.
    돌려줌: dict — side('외경'/'내경'), hand('R'/'L'), pitch(mm, 없으면 None), form, angle."""
    text = str(text or '')
    match = THREAD_INSERT_RE.search(text)
    if match:
        length, side, hand, number, form = match.groups()
        value = _float(number)
        form = (form or '').upper()
        if value is None or value <= 0:
            return None
        if form in TPI_FORMS:                                          # 산/inch
            pitch = 25.4 / value
        else:
            pitch = value
        return {
            'side': '외경' if side.upper() == 'E' else '내경', 'hand': hand.upper(),
            'pitch': pitch, 'form': form or 'ISO', 'length': int(length),
            'angle': 55.0 if form in ('W', 'BSPT', 'BSPP', 'G') else 60.0,
        }
    match = THREAD_PARTIAL_RE.search(text)
    if match:
        length, side, hand, angle = match.groups()
        return {
            'side': '외경' if side.upper() == 'E' else '내경', 'hand': hand.upper(),
            'pitch': None, 'form': 'PARTIAL', 'length': int(length), 'angle': float(angle),
        }
    return None


@_cached_dict
def parse_groove_insert(text):
    """잘 알려진 홈 인서트 표기에서 폭(mm)·코너 R을 읽는다. 없으면 None.
    돌려줌: dict — width, corner_r(없으면 None), series."""
    text = str(text or '')
    match = GROOVE_N123_RE.search(text)
    if match:
        return {'width': int(match.group(1)) / 100.0,
                'corner_r': None if match.group(2) is None else int(match.group(2)) / 10.0,
                'series': 'N123'}
    match = GROOVE_MGXN_RE.search(text)
    if match:
        return {'width': int(match.group(1)) / 100.0, 'corner_r': None, 'series': 'MGMN'}
    match = GROOVE_GIP_RE.search(text)
    if match:
        return {'width': float(match.group(1)), 'corner_r': float(match.group(2)), 'series': 'GIP'}
    match = GROOVE_GTN_RE.search(text)
    if match:
        return {'width': float(match.group(1)), 'corner_r': None, 'series': 'GTN'}
    return None


# --------------------------------------------------------------------------
# ISO 5608 홀더
# --------------------------------------------------------------------------

def parse_tool_diameter(text):
    """문구의 D<숫자>(턴밀·중심 드릴 공구 지름, mm). 없으면 None."""
    match = TOOL_D_RE.search(str(text or ''))
    if not match:
        return None
    value = _float(match.group(1))
    return value if value and value > 0 else None


@_cached_dict
def parse_holder(text):
    """ISO 5608 홀더 코드를 푼다. 없으면 None.
    'BORING BAR PCLNR 2525'처럼 앞에 다른 단어가 있어도 유효한 코드를 찾는다.
    돌려줌: dict — code, clamp, insert_shape, style, approach_angle, clearance, hand,
    shank_w, shank_h, length, insert_size, is_bar(내경 바)."""
    for match in HOLDER_RE.finditer(text):
        clamp, shape, style, clear, hand, sw, sh, length_letter, size = match.groups()
        clamp, shape, style, clear, hand = (v.upper() for v in (clamp, shape, style, clear, hand))
        if clear not in CLEARANCE_ANGLES and clear != 'O':
            continue
        return {
            'code': match.group(0).strip(),
            'clamp': clamp,
            'insert_shape': shape,
            'style': style,
            'approach_angle': HOLDER_APPROACH_ANGLES.get(style),
            'clearance': clear,
            'hand': hand,
            'shank_w': int(sw) if sw else None,
            'shank_h': int(sh) if sh else None,
            'length': HOLDER_LENGTHS.get((length_letter or '').upper()),
            'insert_size': int(size) if size else None,
            'is_bar': bool(BAR_PREFIX_RE.search(text)),
        }
    return None


# --------------------------------------------------------------------------
# 종류·방향 자동 추천
# --------------------------------------------------------------------------

def program_hints(code_lines):
    """공구 블록 코드(주석 제외, 줄 목록)에서 종류/피치 힌트를 뽑는다.
    돌려줌: dict — thread, groove, face_groove, turning(bool), pitch(mm 문자열, 없으면 '')."""
    hints = {'thread': False, 'groove': False, 'face_groove': False, 'turning': False,
             'pitch': ''}
    lines = list(code_lines)
    for index, line in enumerate(lines):
        if _GCODE_THREAD_RE.search(line):
            hints['thread'] = True
            if not hints['pitch']:
                # G76 두 줄 형식은 둘째 줄에도 G76이 있어 그 줄의 F가 잡힌다. 같은 줄의 F만 쓴다 —
                # 다음 줄들을 뒤지면 나사와 무관한 이송 F를 피치로 읽는다.
                f_match = _F_WORD_RE.search(line)
                value = _float(f_match.group(1)) if f_match else None
                if value is not None and 0.05 <= value <= 12.0:
                    hints['pitch'] = fmt_number(value)
        if _GCODE_GROOVE_RE.search(line):
            hints['groove'] = True
        if _GCODE_FACE_GROOVE_RE.search(line):
            hints['face_groove'] = True
        if _GCODE_TURN_CYCLE_RE.search(line):
            hints['turning'] = True
    return hints


def merge_hints(base, extra):
    """같은 공구가 여러 N 블록에서 쓰일 때 힌트를 합친다(피치는 처음 값 유지)."""
    merged = dict(base)
    for key in ('thread', 'groove', 'face_groove', 'turning'):
        merged[key] = bool(base.get(key)) or bool(extra.get(key))
    merged['pitch'] = base.get('pitch') or extra.get('pitch') or ''
    return merged


def infer_kind(insert_text, holder_text, hints=None):
    """공구 종류 자동 추천. 알 수 없으면 ''."""
    hints = hints or {}
    text = '%s %s' % (insert_text or '', holder_text or '')
    thread = parse_thread_insert(text)
    holder = parse_holder(holder_text) or parse_holder(insert_text)
    internal = bool(
        _KW_INTERNAL.search(text) or BAR_PREFIX_RE.search(text)
        or (thread and thread['side'] == '내경'))
    if _KW_NONCUT.search(text):
        return NON_CUTTING_KIND
    if _KW_DRILL.search(text):
        return '드릴'
    if _KW_FACECUT.search(text):
        return '페이스커터'
    if _KW_ENDMILL.search(text):
        return '엔드밀'
    if _KW_CUTOFF.search(text):
        return '절단'
    if _KW_THREAD.search(text) or thread:
        return '내경나사' if internal else '외경나사'
    if _KW_GROOVE.search(text) or parse_groove_insert(text):
        if _KW_FACE.search(text):
            return '정면홈'
        return '내경홈' if internal else '외경홈'
    if parse_insert(text):
        return '내경' if internal else '외경'
    if _KW_INTERNAL.search(text):
        return '내경'
    if _KW_EXTERNAL.search(text):
        return '외경'
    if hints.get('thread'):
        return '내경나사' if internal else '외경나사'
    if hints.get('groove'):
        return '내경홈' if internal else '외경홈'
    if hints.get('face_groove'):
        return '정면홈'
    if hints.get('turning'):
        return '내경' if internal else '외경'
    if holder:
        return '내경' if (internal or holder['is_bar']) else '외경'
    return ''


def infer_direction(kind, insert_text, holder_text):
    """공구 방향(R 우수 / L 좌수 / N 중립) 자동 추천. 알 수 없으면 ''."""
    text = '%s %s' % (insert_text or '', holder_text or '')
    thread = parse_thread_insert(text)
    if thread:
        return thread['hand']
    holder = parse_holder(holder_text) or parse_holder(insert_text)
    if holder:
        return holder['hand']
    hand_match = HOLDER_HAND_RE.search(str(holder_text or ''))
    if hand_match:
        return hand_match.group(1).upper()
    if kind in ('절단', '드릴', '외경홈', '내경홈', '정면홈'):
        return 'N'
    return ''


def infer_tip(kind, hand):
    """가상 인선 번호 자동 추천 — 외경 R 3 / L 2, 내경 R 4 / L 1, 정면홈 4. 그 밖(외경·내경 홈, 손을 모를 때)은 ''.
    (외경·내경 홈은 프로그램 기준 모서리를 알 수 없어 추천하지 않는다 — 직접 지정, 비우면 왼쪽 모서리.)"""
    hand = str(hand or '').upper()
    if kind in ('외경', '외경나사'):
        return {'R': '3', 'L': '2'}.get(hand, '')
    if kind in ('내경', '내경나사'):
        return {'R': '4', 'L': '1'}.get(hand, '')
    if kind == '정면홈':
        return '4'         # 실측(O2222/O4811 정면홈 가공 경로): 프로그램 기준점 = 바깥(+r) 모서리
    return ''


# --------------------------------------------------------------------------
# 값 결정 (출처 우선순위)
# --------------------------------------------------------------------------

def iso_values(insert_text, holder_text=''):
    """텍스트만으로 알 수 있는(ISO 해석/문구) R·T·PITCH 값과 출처.
    돌려줌: {'R': (값, 출처), 'T': ..., 'PITCH': ...} — 모르면 키 없음."""
    text = '%s' % (insert_text or '')
    found = {}
    text_r = TEXT_R_RE.search(text)
    if text_r and (_float(text_r.group(1)) or 0.0) > 0:          # "R-0." 같은 0은 값이 아니다
        found['R'] = (_clean_number(text_r.group(1)), SOURCE_TEXT)
    insert = parse_insert(text)
    groove = parse_groove_insert(text)
    thread = parse_thread_insert(text)
    if 'R' not in found:
        if insert and insert['nose_r'] is not None:
            found['R'] = (fmt_number(insert['nose_r']), SOURCE_ISO)
        elif groove and groove['corner_r'] is not None:
            found['R'] = (fmt_number(groove['corner_r']), SOURCE_ISO)
    if groove:
        found['T'] = (fmt_number(groove['width']), SOURCE_ISO)
    if thread and thread['pitch'] is not None:
        found['PITCH'] = (fmt_number(thread['pitch']), SOURCE_INSERT)
    return found


def resolve_fields(insert_text, holder_text, tags=None, hints=None, store=None):
    """툴리스트 한 행의 R/T/PITCH/KIND/DIR 값을 출처 우선순위대로 정한다.

    tags  : NC 주석 태그 {'R','T','PITCH'}
    hints : program_hints() 결과(공구 블록 코드에서)
    store : LatheSpecStore(직접 입력 저장값) 또는 None
    돌려줌: (values, sources) — 둘 다 {'R','T','PITCH','KIND','DIR'} 키, 모르는 값은 ''."""
    tags = tags or {}
    hints = hints or {}
    saved = store.get_insert(insert_text, holder_text) if store is not None else {}
    saved_tool = store.get_tool(holder_text, insert_text) if store is not None else {}
    iso = iso_values(insert_text, holder_text)
    values = {'R': '', 'T': '', 'PITCH': '', 'KIND': '', 'DIR': '', 'TIP': '', 'D': ''}
    sources = {key: '' for key in values}

    def take(key, candidates):
        for value, source in candidates:
            if value == BLANK:                     # 사용자가 일부러 비운 칸 — 낮은 우선순위 값도 쓰지 않는다
                values[key], sources[key] = '', source
                return
            if value:
                values[key], sources[key] = value, source
                return

    take('R', [(tags.get('R', ''), SOURCE_TAG), (saved.get('R', ''), SOURCE_SAVED),
               iso.get('R', ('', ''))])
    take('T', [(tags.get('T', ''), SOURCE_TAG), (saved.get('T', ''), SOURCE_SAVED),
               iso.get('T', ('', ''))])
    take('PITCH', [(tags.get('PITCH', ''), SOURCE_TAG), iso.get('PITCH', ('', '')),
                   (hints.get('pitch', ''), SOURCE_PROGRAM), (saved.get('PITCH', ''), SOURCE_SAVED)])
    auto_kind = infer_kind(insert_text, holder_text, hints)
    take('KIND', [(saved_tool.get('KIND', ''), SOURCE_SAVED), (auto_kind, SOURCE_AUTO)])
    auto_dir = infer_direction(values['KIND'] or auto_kind, insert_text, holder_text)
    take('DIR', [(saved_tool.get('DIR', ''), SOURCE_SAVED), (auto_dir, SOURCE_AUTO)])
    auto_tip = infer_tip(values['KIND'] or auto_kind, values['DIR'] or auto_dir)
    take('TIP', [(saved_tool.get('TIP', ''), SOURCE_SAVED), (auto_tip, SOURCE_AUTO)])
    # 턴밀·중심 드릴 공구 지름 — 인서트 문구의 D<숫자>(홀더 문구는 밀링 공구일 때만 뒤져 본다)
    diameter = parse_tool_diameter(insert_text)
    if diameter is None and (values['KIND'] or auto_kind) in MILLING_KINDS:
        diameter = parse_tool_diameter(holder_text)
    take('D', [(tags.get('D', ''), SOURCE_TAG), (saved.get('D', ''), SOURCE_SAVED),
               (fmt_number(diameter) if diameter else '', SOURCE_TEXT)])
    return values, sources


def recommend_fields(insert_text, holder_text):
    """[자동 추천] 버튼용 — 문구만으로 추천할 수 있는 값(저장값·태그 제외)."""
    values, _sources = resolve_fields(insert_text, holder_text)
    return values


# --------------------------------------------------------------------------
# 표시용 설명 (툴팁)
# --------------------------------------------------------------------------

def describe_insert(text):
    """인서트 문구의 규격 해석 요약(툴팁). 해석할 게 없으면 ''."""
    insert = parse_insert(text)
    if insert:
        parts = [insert['shape_name']]
        if insert['clearance_angle'] is not None:
            parts.append('여유각 %s°' % fmt_number(insert['clearance_angle']))
        if insert['ic'] is not None:
            parts.append('내접원 %s' % fmt_number(insert['ic']))
        if insert['edge_length'] is not None:
            parts.append('날 길이 %s' % fmt_number(round(insert['edge_length'], 1)))
        parts.append('두께 %s' % fmt_number(insert['thickness']))
        if insert['nose_r'] is not None:
            parts.append('노즈R %s' % fmt_number(insert['nose_r']))
        note = ' (내접원 후보: %s)' % ', '.join(fmt_number(v) for v in insert['ic_alt']) \
            if insert['ic_alt'] else ''
        return 'ISO 1832 %s: %s%s' % (insert['code'], ' / '.join(parts), note)
    thread = parse_thread_insert(text)
    if thread:
        parts = [thread['side'] + ' 나사', '%s (%s)' % (thread['hand'], '우수' if thread['hand'] == 'R' else '좌수')]
        if thread['pitch'] is not None:
            parts.append('피치 %s' % fmt_number(thread['pitch']))
        parts.append('%s°' % fmt_number(thread['angle']))
        return '나사 인서트: ' + ' / '.join(parts)
    groove = parse_groove_insert(text)
    if groove:
        parts = ['폭 %s' % fmt_number(groove['width'])]
        if groove['corner_r'] is not None:
            parts.append('코너R %s' % fmt_number(groove['corner_r']))
        return '홈 인서트(%s): %s' % (groove['series'], ' / '.join(parts))
    return ''


def describe_holder(text):
    """홀더 문구의 규격 해석 요약(툴팁). 해석할 게 없으면 ''."""
    holder = parse_holder(text)
    if not holder:
        return ''
    parts = []
    if holder['approach_angle'] is not None:
        parts.append('접근각 %s°' % fmt_number(holder['approach_angle']))
    parts.append({'R': '우수(R)', 'L': '좌수(L)', 'N': '중립(N)'}[holder['hand']])
    if holder['shank_w']:
        parts.append('섕크 %d×%d' % (holder['shank_w'], holder['shank_h']))
    if holder['length']:
        parts.append('길이 %d' % holder['length'])
    if holder['is_bar']:
        parts.append('내경 바')
    return 'ISO 5608 %s: %s' % (holder['code'], ' / '.join(parts))


# --------------------------------------------------------------------------
# 시뮬레이션용 형상 맵
# --------------------------------------------------------------------------

def mill_type_for(kind, insert_text=''):
    """턴밀·중심 드릴 종류 -> nc_sim.tool_shape_from_values의 type 문자열. 해당 없으면 None."""
    text = str(insert_text or '').upper()
    if kind == '드릴':
        return 'DRILL'
    if kind == '페이스커터':
        return 'FACE MILL'
    if kind == '엔드밀':
        if 'BALL' in text or '볼' in text:
            return 'BALL E/M'
        if 'FILLET' in text:
            return 'FILLET E/M'
        return 'FLAT E/M'
    return None


def geometry_from_row(row):
    """툴리스트 행 하나 -> 선반 시뮬레이션이 쓸 공구 형상 dict.
    값이 없거나 해석 못한 항목은 None."""
    insert_text = str(row.get('INSERT', ''))
    holder_text = str(row.get('HOLDER', ''))
    insert = parse_insert(insert_text)
    holder = parse_holder(holder_text) or parse_holder(insert_text)
    thread = parse_thread_insert(insert_text)
    groove = parse_groove_insert(insert_text)
    tip_text = str(row.get('TIP', '')).strip()
    geometry = {
        'kind': str(row.get('KIND', '')).strip(),
        'hand': str(row.get('DIR', '')).strip().upper(),
        'tip': int(tip_text) if tip_text.isdigit() else None,
        'diameter': _float(row.get('D')),
        'so': _float(row.get('SO')),                       # 날장 최대(날 길이가 없을 때, 사용자 확정 2026-09-26)
        'mill_type': None,
        'nose_r': _float(row.get('R')),
        'width': _float(row.get('T')),
        'pitch': _float(row.get('PITCH')),
        'shape': None, 'tip_angle': None, 'clearance_angle': None, 'ic': None,
        'edge_length': None, 'thickness': None,
        'thread_angle': None,
        'approach_angle': None, 'shank': None,
    }
    if geometry['nose_r'] is None and insert and insert['nose_r'] is not None:
        geometry['nose_r'] = insert['nose_r']
    if geometry['nose_r'] is None and groove and groove['corner_r'] is not None:
        geometry['nose_r'] = groove['corner_r']            # 홈 인서트는 코너 R을 노즈 R 자리에 둔다
    if insert:
        geometry.update(shape=insert['shape'], tip_angle=insert['angle'],
                        clearance_angle=insert['clearance_angle'], ic=insert['ic'],
                        edge_length=insert['edge_length'], thickness=insert['thickness'])
    if thread:
        geometry['thread_angle'] = thread['angle']
        if geometry['pitch'] is None:
            geometry['pitch'] = thread['pitch']
    if groove and geometry['width'] is None:
        geometry['width'] = groove['width']
    geometry['mill_type'] = mill_type_for(geometry['kind'], insert_text)
    if holder:
        geometry['approach_angle'] = holder['approach_angle']
        if holder['shank_w']:
            geometry['shank'] = (holder['shank_w'], holder['shank_h'])
        if not geometry['hand']:
            geometry['hand'] = holder['hand']
    return geometry


def geometry_map_from_rows(rows):
    """툴리스트 행들 -> {'T01'/'T1'/'1': 공구 형상 dict} (밀링 tool_shape_map과 같은 키 규약).
    같은 공구번호가 옵셋 다르게 여러 행이면 먼저 나온 행을 쓴다."""
    mapping = {}
    for row in rows or []:
        match = re.fullmatch(r'T(\d{2})\d{2}', str(row.get('NO', '')).strip().upper())
        if not match:
            continue
        number = int(match.group(1))
        geometry = geometry_from_row(row)
        for key in ('T%02d' % number, 'T%d' % number, str(number)):
            mapping.setdefault(key, geometry)
    return mapping


# --------------------------------------------------------------------------
# 직접 입력 저장소
# --------------------------------------------------------------------------

def specs_path(base_dir):
    return os.path.join(str(base_dir), 'lathe_insert_specs.json')


class LatheSpecStore:
    """사용자가 툴리스트 [수정] 창에서 넣은 값을 인서트 이름별로 기억한다.

    insert : 정규화한 인서트 문구 -> {'R','T','PITCH','D'}
    tool   : '홀더||인서트' -> {'KIND','DIR','TIP'}  (같은 인서트도 홀더에 따라 종류가 다르다)"""

    INSERT_FIELDS = ('R', 'T', 'PITCH', 'D')
    TOOL_FIELDS = ('KIND', 'DIR', 'TIP')

    def __init__(self, path=None):
        self.path = None if path is None else str(path)
        self.insert = {}
        self.tool = {}
        self.load()

    @staticmethod
    def insert_key(insert_text, holder_text=''):
        """R/T/PITCH 저장 키 — 인서트 이름. 인서트 칸이 비어 있으면(홈 홀더만 적힌 공구 등)
        홀더 이름을 대신 쓴다('@' 접두어로 구분)."""
        key = normalize_key(insert_text)
        if key:
            return key
        holder = normalize_key(holder_text)
        return '@' + holder if holder else ''

    @staticmethod
    def tool_key(holder_text, insert_text):
        return '%s||%s' % (normalize_key(holder_text), normalize_key(insert_text))

    def load(self):
        self.insert, self.tool = {}, {}
        if not self.path:
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        for section, target, fields in (('insert', self.insert, self.INSERT_FIELDS),
                                        ('tool', self.tool, self.TOOL_FIELDS)):
            entries = data.get(section)
            if not isinstance(entries, dict):
                continue
            for key, value in entries.items():
                if isinstance(value, dict):
                    clean = {f: str(value[f]).strip() for f in fields
                             if f in value and str(value[f]).strip()}
                    if clean:
                        target[str(key)] = clean

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as fp:
            json.dump({'version': 1, 'insert': self.insert, 'tool': self.tool}, fp,
                      ensure_ascii=False, indent=2, sort_keys=True)

    def get_insert(self, insert_text, holder_text=''):
        return dict(self.insert.get(self.insert_key(insert_text, holder_text), {}))

    def get_tool(self, holder_text, insert_text):
        return dict(self.tool.get(self.tool_key(holder_text, insert_text), {}))

    @staticmethod
    def _update(target, key, values, fields):
        entry = dict(target.get(key, {}))
        for field in fields:
            if field not in values:
                continue
            value = str(values[field] or '').strip()
            if value:
                entry[field] = value
            else:
                entry.pop(field, None)
        if entry:
            target[key] = entry
        else:
            target.pop(key, None)

    def update_insert(self, insert_text, values, holder_text=''):
        """values에 든 R/T/PITCH만 갱신한다(빈 값 = 저장값 삭제). 인서트·홀더 이름이 모두 비면 무시."""
        key = self.insert_key(insert_text, holder_text)
        if key:
            self._update(self.insert, key, values, self.INSERT_FIELDS)

    def update_tool(self, holder_text, insert_text, values):
        key = self.tool_key(holder_text, insert_text)
        if key != '||':
            self._update(self.tool, key, values, self.TOOL_FIELDS)
