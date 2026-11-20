"""v2.6.6: 공정(공구 교체)의 "시작 표시 줄" — 그 공정의 첫 N 시퀀스와 주석.

재생 바 [이전 공구]/[다음 공구]는 M6 줄이 아니라 이 줄로 이동해, 공정 머리말의 주석
(공구명·가공 내용)을 프로그램 화면에서 함께 볼 수 있게 한다. 순수 함수만 둔다(Qt 없음).
안드로이드 tool_list_android/src/core/processMarker.ts와 같은 결과를 내야 한다.
"""
import re

_N_RE = re.compile(r'^\s*/?\s*N\s*\d+', re.I)
_MOTION_RE = re.compile(r'G0?[0-3](?!\d)')
_AXIS_RE = re.compile(r'[XYZABCUVW]\s*[-+]?[\d.]')
_STOP_RE = re.compile(r'M0?[01](?!\d)|M30(?!\d)')
_PAREN_RE = re.compile(r'\(([^)]*)\)')


def _code(line):
    """주석(괄호·세미콜론 이후)을 뺀 대문자 코드, 공백 제거."""
    text = _PAREN_RE.sub(' ', str(line or '')).split(';')[0]
    return text.upper().replace(' ', '')


def is_motion_line(line):
    """G0~G3 이동 + 좌표가 있는 줄(앞 공정의 마지막 가공/이동 줄을 알아보는 데 쓴다)."""
    code = _code(line)
    return bool(_MOTION_RE.search(code)) and bool(_AXIS_RE.search(code))


def is_n_line(line):
    return bool(_N_RE.match(str(line or '')))


def line_comments(line):
    """한 줄의 주석 텍스트들: (…) 안 글자와 ; 뒤 글자. 비어 있으면 건너뛴다."""
    text = str(line or '')
    found = [m.group(1).strip() for m in _PAREN_RE.finditer(text)]
    rest = _PAREN_RE.sub(' ', text)
    if ';' in rest:
        found.append(rest.split(';', 1)[1].strip())
    return [c for c in found if c]


def find_process_marker(lines, change_seq, floor_seq=-1, max_comments=2):
    """공구 교체 줄(change_seq)에서 위로 올라가며 공정의 첫 N 줄을 찾는다.

    lines: 실행 순서(seq)대로의 줄 텍스트. floor_seq: 앞 공정의 공구 교체 seq(없으면 -1,
    이 줄 자신은 탐색하지 않는다). 앞 공정의 마지막 이동 줄을 만나거나, N 줄을 찾은 뒤
    프로그램 정지(M00/M01/M30)를 만나면 거기서 멈추고 그 아래 가장 위의 N 줄을 쓴다.
    N 줄이 없으면 공구 교체 줄 자신. 돌려주는 값: (marker_seq, [주석 최대 max_comments개])."""
    total = len(lines)
    change_seq = max(0, min(int(change_seq), total - 1)) if total else 0
    best = None
    seq = change_seq
    while seq > floor_seq and seq >= 0:
        text = lines[seq]
        if seq != change_seq:
            if is_motion_line(text):
                break
            if best is not None and _STOP_RE.search(_code(text)):
                break
        if is_n_line(text):
            best = seq
        seq -= 1
    start = change_seq if best is None else best
    comments = []
    for s in range(start, change_seq + 1):
        comments.extend(line_comments(lines[s]))
        if len(comments) >= max_comments:
            break
    return start, comments[:max_comments]
