"""v2.6.4: 재생 위치의 모달 정보 — 주축(S·회전 M), 이송(F·단위), G코드 그룹별 마지막 값, M코드 묶음.

뷰어 재생 바의 [모달 정보] 줄(기본 접힘)에 보인다. 실행 순서(seq, M98/M99 확장 결과)대로 줄을 읽어
값이 바뀐 seq에서만 스냅샷을 남기고, 재생 중에는 bisect로 찾는다. 계산에 영향을 주지 않는 표시 전용이다.
안드로이드 `src/core/modal.ts`가 같은 규칙을 쓴다(골든 비교).
"""
import bisect
import re

# Fanuc 밀링 기준 모달 그룹(번호, 이름, 코드).
MILL_GROUPS = (
    ("01", "이동", ("G00", "G01", "G02", "G03")),
    ("02", "평면", ("G17", "G18", "G19")),
    ("03", "지령", ("G90", "G91")),
    ("05", "이송", ("G93", "G94", "G95")),
    ("06", "단위", ("G20", "G21")),
    ("07", "경보정", ("G40", "G41", "G42")),
    ("08", "길이보정", ("G43", "G44", "G49", "G43.4", "G43.5")),
    ("09", "사이클", ("G73", "G74", "G76", "G80", "G81", "G82", "G83", "G84", "G85", "G86", "G87", "G88", "G89")),
    ("10", "복귀", ("G98", "G99")),
    ("14", "좌표계", ("G54", "G55", "G56", "G57", "G58", "G59", "G54.1")),
    ("15", "경로", ("G61", "G62", "G63", "G64")),
    ("16", "좌표회전", ("G68", "G69", "G68.2", "G68.3")),
)
# Fanuc 선반(A 계열) 기준.
LATHE_GROUPS = (
    ("01", "이동", ("G00", "G01", "G02", "G03", "G32", "G33", "G34")),
    ("02", "주속", ("G96", "G97")),
    ("05", "이송", ("G98", "G99")),
    ("06", "단위", ("G20", "G21")),
    ("07", "경보정", ("G40", "G41", "G42")),
    ("16", "평면", ("G17", "G18", "G19")),
    # G70~G76 복합형 반복 사이클은 그 줄에서만 도는 00 그룹이라 넣지 않는다(모달인 드릴 사이클만).
    ("10", "사이클", ("G80", "G83", "G84", "G85", "G87", "G88", "G89")),
    ("14", "좌표계", ("G54", "G55", "G56", "G57", "G58", "G59")),
    ("21", "극좌표", ("G12.1", "G13.1", "G112", "G113")),
)
# M코드는 공식 그룹이 없어 묶음으로 나눈다. 기타 = 아래에 없는 마지막 M(서브프로그램 호출 M98/M99는 뺀다).
M_SPINDLE = ("M03", "M04", "M05", "M19")
M_COOLANT = ("M07", "M08", "M09")
M_STOP = ("M00", "M01", "M02", "M30")
M_CATEGORIES = (("spindle", "주축"), ("coolant", "절삭유"), ("stop", "정지"), ("other", "기타"))
M_SKIP = ("M98", "M99")

_COMMENT_RE = re.compile(r"\([^)]*\)")
_WORD_RE = re.compile(r"([GMSFH])\s*([+-]?\d+(?:\.\d*)?)")
_MAX_RPM_RE = re.compile(r"G(?:50|92)(?![\d.])")


def _code_part(line):
    text = _COMMENT_RE.sub(" ", str(line))
    return text.split(";", 1)[0].upper()


def normalize_code(letter, number):
    """'G1' -> 'G01', 'G43.4' 그대로, 'M3' -> 'M03'."""
    head, _, tail = number.partition(".")
    try:
        value = int(head)
    except ValueError:
        return letter + number
    tail = tail.rstrip("0")
    return "%s%02d%s" % (letter, value, ("." + tail) if tail else "")


def _format_number(number):
    """'10000.' -> '10000', '3600.0' -> '3600', '0.15' -> '0.15'."""
    try:
        value = float(number)
    except ValueError:
        return number
    if value == int(value):
        return str(int(value))
    return ("%f" % value).rstrip("0").rstrip(".")


def group_table(lathe):
    return LATHE_GROUPS if lathe else MILL_GROUPS


def _code_to_group(lathe):
    table = {}
    for gid, _name, codes in group_table(lathe):
        for code in codes:
            table[code] = gid
    return table


def empty_state():
    return {"S": None, "F": None, "groups": {}, "m": {}}


def feed_unit(state, lathe):
    """이송 단위. 밀링 G94 mm/min · G95 mm/rev · G93 1/min, 선반 G98 mm/min · G99 mm/rev(선반 기본 G99)."""
    groups = state["groups"]
    inch = groups.get("06") == "G20"
    length = "in" if inch else "mm"
    code = groups.get("05")
    if lathe:
        per_rev = code != "G98"
    else:
        if code == "G93":
            return "1/min"
        per_rev = code == "G95"
    return "%s/%s" % (length, "rev" if per_rev else "min")


def apply_line(state, line, lathe, code_to_group=None):
    """한 줄을 읽어 state를 바꾼다. 바뀐 항목 이름(그룹 번호, 'S', 'F', 'm:묶음')의 집합을 돌려준다."""
    code_to_group = code_to_group or _code_to_group(lathe)
    code = _code_part(line)
    if not code.strip():
        return set()                          # '/' 블록 스킵 줄도 경로 계산처럼 실행한 것으로 본다
    words = _WORD_RE.findall(code)
    if not words:
        return set()
    changed = set()
    groups = state["groups"]
    max_rpm_line = bool(_MAX_RPM_RE.search(code.replace(" ", "")))
    h_word = None
    for letter, number in words:
        if letter == "H":
            h_word = _format_number(number)
    for letter, number in words:
        if letter == "G":
            g = normalize_code("G", number)
            gid = code_to_group.get(g)
            if gid is None:
                continue
            text = g
            if gid == "08" and g in ("G43", "G44", "G43.4", "G43.5") and h_word is not None:
                try:
                    text = "%s H%02d" % (g, int(float(h_word)))
                except ValueError:
                    text = "%s H%s" % (g, h_word)
            if groups.get(gid) != text:
                groups[gid] = text
                changed.add(gid)
        elif letter == "M":
            m = normalize_code("M", number)
            if m in M_SKIP:
                continue
            if m in M_SPINDLE:
                category = "spindle"
            elif m in M_COOLANT:
                category = "coolant"
            elif m in M_STOP:
                category = "stop"
            else:
                category = "other"
            if state["m"].get(category) != m:
                state["m"][category] = m
                changed.add("m:" + category)
        elif letter == "S":
            if max_rpm_line:
                continue                      # G50/G92 S는 최고 회전수 제한이라 주축 지령이 아니다
            s = _format_number(number)
            if state["S"] != s:
                state["S"] = s
                changed.add("S")
        elif letter == "F":
            f = _format_number(number)
            if state["F"] != f:
                state["F"] = f
                changed.add("F")
    # v2.6.5(VERICUT fan30im 비교): 경로 계산과 같은 규칙.
    g_codes = {normalize_code("G", number) for letter, number in words if letter == "G"}
    cycle_gid = "10" if lathe else "09"
    cycle_codes = {code for code, gid in code_to_group.items() if gid == cycle_gid}
    if (g_codes & {"G00", "G01", "G02", "G03"} and not (g_codes & cycle_codes)
            and groups.get(cycle_gid) not in (None, "G80")):
        groups[cycle_gid] = "G80"             # 01그룹(G00~G03)은 고정 사이클을 해제한다
        changed.add(cycle_gid)
    if not lathe and g_codes & {"G28", "G30"} and groups.get("08") != "G49":
        groups["08"] = "G49"                  # 원점 복귀는 공구 길이 보정을 해제한다
        changed.add("08")
    return changed


def _snapshot(state):
    return {"S": state["S"], "F": state["F"], "groups": dict(state["groups"]), "m": dict(state["m"])}


class ModalTimeline:
    """seq -> 그 시점의 모달 상태. 값이 바뀐 seq에서만 스냅샷을 둔다."""

    def __init__(self, line_sequence=(), lathe=False):
        self.lathe = bool(lathe)
        self.keys = []
        self.states = []
        self.changes = []
        state = empty_state()
        code_to_group = _code_to_group(self.lathe)
        for seq_pos, (_idx, line) in enumerate(line_sequence):
            changed = apply_line(state, line, self.lathe, code_to_group)
            if changed:
                self.keys.append(seq_pos)
                self.states.append(_snapshot(state))
                self.changes.append(frozenset(changed))

    def at(self, seq):
        """(state, 이 seq 줄에서 바뀐 항목 집합). 아무 것도 지령되기 전이면 빈 상태."""
        pos = bisect.bisect_right(self.keys, int(seq)) - 1
        if pos < 0:
            return empty_state(), frozenset()
        changed = self.changes[pos] if self.keys[pos] == int(seq) else frozenset()
        return self.states[pos], changed


def summary_text(state, lathe):
    """접혀 있을 때 한 줄 요약 — 'S10000 M03 · F3600 · G01 G68.2'."""
    parts = []
    spindle = " ".join(x for x in (("S" + state["S"]) if state["S"] else "", state["m"].get("spindle") or "") if x)
    if spindle:
        parts.append(spindle)
    if state["F"]:
        parts.append("F" + state["F"])
    groups = state["groups"]
    codes = [groups.get("01")]
    cycle = groups.get("10" if lathe else "09")
    if cycle and cycle != "G80":
        codes.append(cycle)
    rotate = groups.get("21" if lathe else "16")
    if rotate and rotate not in ("G69", "G13.1", "G113"):
        codes.append(rotate)
    codes = [c for c in codes if c]
    if codes:
        parts.append(" ".join(codes))
    return " · ".join(parts) if parts else "지령 전"
