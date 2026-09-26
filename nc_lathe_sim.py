"""nc_lathe_sim.py — 선반 형상 가공 시뮬레이션 엔진 (v2.2.0: M1 선삭 축대칭 + M2 턴밀 하이브리드).

Qt 비의존 · 선반 전용(밀링 nc_sim/nc_sim3d와 분리, LATHE_MODE_GUIDELINES §0).

- 소재 = 반단면 점유 격자(z 주축 방향 × r 반경). 칸마다 "남아 있음"과 "마지막으로 깎은 공정 색 id".
- 공구 = (z, r) 단면의 볼록 다각형(선삭 인서트·홈·절단·나사·중심 드릴). 프로그램 좌표점(가상 인선 등)이
  다각형의 원점이다. 이동 하나가 쓸고 간 영역 = 다각형을 시작/끝에 놓은 두 복사본의 볼록 껍질.
- 밀링 엔진과 같은 인터페이스(cut_batch / snapshot / restore / clone / rapid_cut_warnings / display_mesh)를
  구현해 뷰어의 백그라운드 계산·스냅샷·되돌리기를 그대로 쓴다.
- 좌표: 월드 점 (x, y, z) = (주축 방향 Z, C 회전 성분, X/2 반경). 선삭 이동은 (z, r) = (pt[0], pt[2]).
- 턴밀(M2): TurnMillStock = 축대칭 격자(선삭, 진실 원천) + 3D 복셀(nc_sim3d.VoxelStock, 턴밀). 재료 제거는
  순서와 무관하게 최종 형상이 같으므로 따로 깎고, 턴밀 절삭 직전·표시 직전에 선삭 결과를 복셀에 한 번에 반영한다.
  턴밀 공구 축은 가공 묶음의 "진입 벡터" 반대 방향(사용자 결정 I), 날장 최대는 SO(결정 J).
"""
import math
import zlib

import numpy as np

import nc_sim
import nc_sim3d
from nc_sim import DEFAULT_STOCK_COLOR, EDGE_COLOR, SIM_CHUNK_SEGMENTS, _load_numba, depth_colors

UNCUT_COLOR = 255                     # 색 평면: 한 번도 안 깎인 곳
LATHE_TARGET_CELLS = 4_000_000        # 자동 해상도가 노리는 격자 칸 수
LATHE_MIN_RES = 0.02
LATHE_MAX_RES = 0.25
UNLIMITED_LENGTH = 1000.0             # SO도 날 길이도 없는 공구의 "날장 최대"
GROOVE_REACH = 60.0                   # 홈·절단 블레이드가 홀더 쪽으로 뻗는 길이(충돌은 검사하지 않는다)
DEFAULT_KAPPA = {'C': 95.0, 'D': 93.0, 'E': 93.0, 'M': 93.0, 'V': 93.0, 'S': 90.0,
                 'T': 91.0, 'W': 95.0}                 # 홀더 접근각을 모를 때(도)
CAP_COLOR = (0.66, 0.74, 0.86, 1.0)                   # 단면(자른 면) 색
SECTION_MODES = (('3q', '3/4 단면'), ('half', '반 단면'), ('full', '전체'))
NUMBA_MIN_SEGMENTS = 16
THREAD_TOOL_HEIGHT_FACTOR = 2.0       # 나사 공구가 파는 높이 = 나사산 높이 x 이 값
RAPID_HIT_MIN_AREA = 0.5              # 급속 이동이 소재와 겹친 단면적(mm²)이 이보다 작으면 경고하지 않는다
                                      # (내경 공구가 벽면을 스치는 격자 반올림 수준의 접촉 — 실측: O1699 0.15mm²)
DISPLAY_ARC_STEP_DEG = 12.0


class ToolShapeError(Exception):
    """공구 형상을 만들 수 없는 이유(사람이 읽는 문장)."""


# --------------------------------------------------------------------------
# 공구 형상 (단면 다각형)
# --------------------------------------------------------------------------

class LatheTool:
    """선반 공구 하나 — poly: (K, 2) 반시계 볼록 다각형 [z, r], 프로그램 좌표점이 원점."""

    def __init__(self, poly, name='', kind='', thread_angle=None, internal=False, notes=(),
                 mill_shape=None):
        # poly: 선삭(축대칭) 단면 — 페이스커터처럼 선삭으로는 못 쓰는 공구는 None
        # mill_shape: 턴밀(3D)용 nc_sim.ToolShape — 드릴·엔드밀·페이스커터만
        self.poly = None if poly is None else np.ascontiguousarray(poly, dtype=np.float64)
        self.mill_shape = mill_shape
        self.name = name
        self.kind = kind
        self.thread_angle = thread_angle          # 도(나사 공구만)
        self.internal = bool(internal)
        self.notes = tuple(notes)                 # 진단에 보여줄 안내(예: "날 길이 무제한")

    @property
    def cut_length(self):
        """(호환) 진단의 도달 거리 계산용 — 선삭 단면의 z 폭, 없으면 턴밀 공구 날장."""
        if self.poly is not None:
            return float(np.ptp(self.poly[:, 0]))
        return float(self.mill_shape.cut_length) if self.mill_shape is not None else 0.0

    @property
    def radius(self):
        if self.poly is not None:
            return float(np.ptp(self.poly[:, 1])) / 2.0
        return float(self.mill_shape.radius) if self.mill_shape is not None else 0.0


def _signed_area(poly):
    z, r = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.sum(z * np.roll(r, -1) - np.roll(z, -1) * r))


def _apply_flips(poly, sz, sr):
    """z/r 부호 반전(좌수·내경 공구) 뒤 반시계 방향을 유지한다."""
    poly = poly * np.array([sz, sr], dtype=np.float64)
    if _signed_area(poly) < 0:
        poly = poly[::-1]
    return poly


def _walk_polygon(heading_deg, side, interiors):
    """원점에서 heading 방향으로 출발해 왼쪽으로 돌며 그린 다각형의 꼭짓점.
    interiors: 꼭짓점별 내각(첫 값 = 원점의 내각)."""
    pts = [(0.0, 0.0)]
    heading = float(heading_deg)
    for k in range(1, len(interiors)):
        z, r = pts[-1]
        pts.append((z + side * math.cos(math.radians(heading)),
                    r + side * math.sin(math.radians(heading))))
        heading += 180.0 - interiors[k]
    return pts


_SHAPE_INTERIORS = {
    'C': lambda a: [a, 180.0 - a, a, 180.0 - a], 'D': lambda a: [a, 180.0 - a, a, 180.0 - a],
    'E': lambda a: [a, 180.0 - a, a, 180.0 - a], 'M': lambda a: [a, 180.0 - a, a, 180.0 - a],
    'V': lambda a: [a, 180.0 - a, a, 180.0 - a], 'S': lambda a: [90.0] * 4,
    'T': lambda a: [60.0] * 3, 'W': lambda a: [80.0, 160.0] * 3,
}
_TIP_FLIPS = {'3': (1, 1), '2': (-1, 1), '4': (1, -1), '1': (-1, -1), '9': (1, 1)}


def insert_polygon(geometry, tip=None):
    """선삭 인서트 단면 다각형. 기준 방향 = 인선 3(좌하: 노즈가 -Z, -X쪽, 척 쪽으로 깎는 외경 우수 공구),
    나머지 인선은 z/r를 뒤집어 만든다. 프로그램 좌표점 = 가상 인선(노즈 원의 X·Z 접선 교점),
    인선 9는 노즈 원 중심.
    돌려줌: (poly, 사용한 인선 문자열). 만들 수 없으면 ToolShapeError."""
    shape = geometry.get('shape')
    if not shape:
        raise ToolShapeError('인서트 형상을 해석하지 못함(INSERT 문구 확인)')
    tip = str(tip or geometry.get('tip') or '')
    if tip not in _TIP_FLIPS:
        tip = '4' if geometry.get('kind') in ('내경', '내경나사') else '3'
    nose = float(geometry.get('nose_r') or 0.0)
    if shape == 'R':
        radius = (geometry.get('ic') or 0.0) / 2.0
        if radius <= 0:
            raise ToolShapeError('원형 인서트의 지름을 모름')
        angles = np.linspace(0.0, 2.0 * math.pi, 41)[:-1]
        circle = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
        ref = np.zeros(2) if tip == '9' else np.array([-radius, -radius])
        poly = circle - ref
        sz, sr = _TIP_FLIPS[tip]
        return _apply_flips(poly, sz, sr), tip
    alpha = geometry.get('tip_angle')
    side = geometry.get('edge_length')
    if not alpha or not side:
        raise ToolShapeError('인서트 크기를 해석하지 못함(내접원·날 길이)')
    kappa = geometry.get('approach_angle') or DEFAULT_KAPPA.get(shape, 95.0)
    theta1 = 180.0 - kappa                       # 주절삭날 방향(+z에서 반시계, 도)
    theta2 = theta1 - alpha                      # 부절삭날 방향
    verts = _walk_polygon(theta2, side, _SHAPE_INTERIORS[shape](alpha))
    half = math.radians(alpha / 2.0)
    nose = min(nose, 0.9 * side * math.tan(half)) if nose > 0 else 0.0
    if nose > 0:
        bis = math.radians(theta1 - alpha / 2.0)
        dist = nose / math.sin(half)
        cz, cr = dist * math.cos(bis), dist * math.sin(bis)
        span = 180.0 - alpha
        n_arc = max(2, int(math.ceil(span / 10.0)))
        phis = np.radians(np.linspace(theta1 + 90.0, theta2 + 270.0, n_arc + 1))
        arc = [(cz + nose * math.cos(p), cr + nose * math.sin(p)) for p in phis]
        poly = np.array(arc + verts[1:], dtype=np.float64)
        origin = np.array([cz, cr]) if tip == '9' else np.array([cz - nose, cr - nose])
    else:
        poly = np.array(verts, dtype=np.float64)
        origin = np.zeros(2)
    sz, sr = _TIP_FLIPS[tip]
    return _apply_flips(poly - origin, sz, sr), tip


def _rect_polygon(z_lo, z_hi, r_lo, r_hi, corner_r, round_low_r=True, round_high_r=False,
                  round_low_z=False, round_high_z=False):
    """축 정렬 직사각형(선택한 모서리를 둥글림). 반시계 다각형."""
    def arc(cz, cr, a0, a1, n=5):
        return [(cz + corner_r * math.cos(math.radians(a)), cr + corner_r * math.sin(math.radians(a)))
                for a in np.linspace(a0, a1, n)]
    R = max(0.0, min(corner_r, (z_hi - z_lo) / 2.0, (r_hi - r_lo) / 2.0))
    corner_r = R
    pts = []
    # 반시계: (z_lo,r_lo) -> (z_hi,r_lo) -> (z_hi,r_hi) -> (z_lo,r_hi)
    pts += arc(z_lo + R, r_lo + R, 180, 270) if (R and round_low_r and round_low_z) else [(z_lo, r_lo)]
    pts += arc(z_hi - R, r_lo + R, 270, 360) if (R and round_low_r and round_high_z) else [(z_hi, r_lo)]
    pts += arc(z_hi - R, r_hi - R, 0, 90) if (R and round_high_r and round_high_z) else [(z_hi, r_hi)]
    pts += arc(z_lo + R, r_hi - R, 90, 180) if (R and round_high_r and round_low_z) else [(z_lo, r_hi)]
    return np.array(pts, dtype=np.float64)


def groove_polygon(geometry, tip=None):
    """홈·절단 공구: 폭 T 직사각형, 끝 모서리에 코너 R. 외경/절단 = 블레이드 끝이 -r쪽(홀더는 +r),
    내경홈 = 끝이 +r쪽, 정면홈 = 끝이 -z쪽(폭이 r 방향). 기준 모서리는 인선으로 고른다:
    외경 3 좌(-z) / 2 우(+z) / 9 중심, 내경 4 좌 / 1 우 / 9, 정면 4 바깥(+r) / 3 안쪽(-r) / 9."""
    width = geometry.get('width')
    if not width or width <= 0:
        raise ToolShapeError('홈 폭(T)을 모름 — 툴리스트 T 칸에 입력하세요')
    corner = float(geometry.get('nose_r') or 0.0)
    kind = geometry.get('kind')
    tip = str(tip or geometry.get('tip') or '')
    reach = GROOVE_REACH
    if kind == '정면홈':
        tip = tip if tip in ('3', '4', '9') else '4'
        r_lo, r_hi = {'4': (-width, 0.0), '3': (0.0, width), '9': (-width / 2.0, width / 2.0)}[tip]
        # 끝(z=0, -z쪽) 두 모서리를 둥글림, 홀더 쪽(+z)으로 reach
        return _rect_polygon(0.0, reach, r_lo, r_hi, corner, round_low_r=True, round_high_r=True,
                             round_low_z=True, round_high_z=False), tip
    internal = kind == '내경홈'
    allowed = ('4', '1', '9') if internal else ('3', '2', '9')
    tip = tip if tip in allowed else allowed[0]
    z_lo, z_hi = {allowed[0]: (0.0, width), allowed[1]: (-width, 0.0),
                  '9': (-width / 2.0, width / 2.0)}[tip]
    if internal:
        return _rect_polygon(z_lo, z_hi, -reach, 0.0, corner, round_low_r=False, round_high_r=True,
                             round_low_z=True, round_high_z=True), tip
    return _rect_polygon(z_lo, z_hi, 0.0, reach, corner, round_low_r=True, round_high_r=False,
                         round_low_z=True, round_high_z=True), tip


def _ensure_ccw_convex(pts):
    """점 집합의 볼록 껍질(반시계). 방향/순서가 섞인 입력을 안전하게 정리한다."""
    pts = np.unique(np.round(pts, 9), axis=0)
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    pts = pts[order]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1], dtype=np.float64)


def thread_polygon(geometry, tip=None):
    """나사 공구: 나사각 V(끝이 -r쪽, 외경) — 내경은 +r쪽. 이동 중 몸체 확인용(나사 자체는 G76 처리)."""
    angle = geometry.get('thread_angle') or 60.0
    height = 4.0
    half = height * math.tan(math.radians(angle / 2.0))
    poly = np.array([(0.0, 0.0), (half, height), (-half, height)], dtype=np.float64)
    internal = geometry.get('kind') == '내경나사'
    return _apply_flips(poly, 1, -1 if internal else 1), ('4' if internal else '3')


def mill_tool_shape(geometry):
    """드릴·엔드밀·페이스커터의 3D 공구 형상(nc_sim.ToolShape). 날 길이 = FL이 없으므로 SO(날장 최대,
    결정 J), SO도 없으면 무제한. 돌려줌: (shape, 안내 목록)."""
    diameter = geometry.get('diameter')
    mill_type = geometry.get('mill_type')
    if not diameter or not mill_type:
        raise ToolShapeError('공구 지름(D) 또는 종류를 모름 — 툴리스트 D·종류 칸을 확인하세요')
    notes = []
    so = geometry.get('so')
    if not so:
        so = UNLIMITED_LENGTH
        notes.append('날장 최대(SO) 없음 — 무제한으로 계산')
    shape = nc_sim.tool_shape_from_values(mill_type, diameter, fl=None, r=geometry.get('nose_r'),
                                          sig=None, pl=None, so=so)
    if shape is None:
        raise ToolShapeError('공구 형상을 만들 수 없음')
    return shape, notes


def center_tool_polygon(geometry, shape=None, notes=None):
    """중심 드릴/엔드밀(주축 중심선에서 Z로만 움직이는 축대칭 공구): 공구 반단면.
    shape/notes: 이미 만든 mill_tool_shape 결과(없으면 여기서 만든다). 돌려줌: (poly, 안내 목록)."""
    if shape is None:
        shape, notes = mill_tool_shape(geometry)
    notes = list(notes or [])
    radii = np.linspace(0.0, shape.radius, 25)
    tip = [(float(shape.height_at(r) or 0.0), float(r)) for r in radii]
    length = float(shape.cut_length)
    poly = np.array(tip + [(length, shape.radius), (length, 0.0)], dtype=np.float64)
    return _ensure_ccw_convex(poly), notes


_TURNING_KINDS = ('외경', '내경')
_GROOVE_KINDS = ('외경홈', '내경홈', '정면홈', '절단')
_THREAD_KINDS = ('외경나사', '내경나사')
_CENTER_KINDS = ('드릴', '엔드밀')


def tool_from_geometry(geometry, name=''):
    """v2.1.0 형상 맵의 한 항목 -> LatheTool. 만들 수 없으면 ToolShapeError(이유)."""
    kind = geometry.get('kind') or ''
    notes = []
    mill_shape = None
    if kind in _TURNING_KINDS:
        poly, tip = insert_polygon(geometry)
    elif kind in _GROOVE_KINDS:
        poly, tip = groove_polygon(geometry)
    elif kind in _THREAD_KINDS:
        poly, tip = thread_polygon(geometry)
    elif kind in _CENTER_KINDS:
        mill_shape, notes = mill_tool_shape(geometry)
        poly, notes = center_tool_polygon(geometry, mill_shape, notes)
    elif kind == '페이스커터':
        poly = None                               # 선삭(축대칭)으로는 쓰지 않는다 — 턴밀(3D) 전용
        mill_shape, notes = mill_tool_shape(geometry)
    elif kind == '비절삭':
        raise ToolShapeError('비절삭 공구')
    else:
        raise ToolShapeError('공구 종류를 모름 — 툴리스트 종류 칸을 확인하세요')
    return LatheTool(poly, name=name, kind=kind,
                     thread_angle=geometry.get('thread_angle') if kind in _THREAD_KINDS else None,
                     internal=(kind == '내경나사'), notes=notes, mill_shape=mill_shape)


# --------------------------------------------------------------------------
# 소재 사양 · 자동 해상도
# --------------------------------------------------------------------------

class LatheStockSpec:
    """소재 지름·길이·앞면 Z·내경. 소재는 앞면(front_z)에서 -Z쪽으로 length만큼."""

    def __init__(self, diameter, length, front_z=0.0, bore=0.0):
        self.diameter = float(diameter)
        self.length = float(length)
        self.front_z = float(front_z)
        self.bore = max(0.0, float(bore))

    def bounds(self):
        return {'z': (self.front_z - self.length, self.front_z),
                'r': (self.bore / 2.0, self.diameter / 2.0)}


def auto_resolution(bounds, target_cells=LATHE_TARGET_CELLS, safe_mode=False):
    z_len = max(bounds['z'][1] - bounds['z'][0], 1e-6)
    r_len = max(bounds['r'][1], 1e-6)
    if safe_mode:
        target_cells = max(target_cells // 4, 1)
    res = math.sqrt(z_len * r_len / max(target_cells, 1))
    return round(min(max(res, LATHE_MIN_RES), LATHE_MAX_RES), 4)


# --------------------------------------------------------------------------
# 절삭 (numpy 대체 경로 — nc_sim_numba.cut_chunk_lathe 와 같은 산식)
# --------------------------------------------------------------------------

def _hull_numpy(pts):
    """(N, 2) 점의 볼록 껍질(반시계)."""
    return _ensure_ccw_convex(pts)


def _fill_hull_numpy(stock, hull, color, cut):
    """껍질 안에 중심이 든 소재 칸 수(cut이면 지움). 산식은 numba _fill_hull과 같다."""
    nz, nr = stock.nz, stock.nr
    z0, dz, dr = stock.z0, stock.dz, stock.dr
    if hull.shape[0] < 1:
        return 0
    zmin, zmax = float(hull[:, 0].min()), float(hull[:, 0].max())
    iz0 = max(int(math.ceil((zmin - z0) / dz - 0.5)), 0)
    iz1 = min(int(math.floor((zmax - z0) / dz - 0.5)), nz - 1)
    if iz1 < iz0:
        return 0
    iz = np.arange(iz0, iz1 + 1)
    zc = z0 + (iz + 0.5) * dz
    lo = np.full(zc.shape, np.inf)
    hi = np.full(zc.shape, -np.inf)
    count = hull.shape[0]
    for i in range(count):
        j = i + 1 if i + 1 < count else 0
        za, ra = hull[i]
        zb, rb = hull[j]
        if za == zb:
            m = zc == za
            if m.any():
                lo[m] = np.minimum(lo[m], min(ra, rb))
                hi[m] = np.maximum(hi[m], max(ra, rb))
            continue
        m = ((za <= zc) & (zc <= zb)) | ((zb <= zc) & (zc <= za))
        if m.any():
            r = ra + (zc[m] - za) / (zb - za) * (rb - ra)
            lo[m] = np.minimum(lo[m], r)
            hi[m] = np.maximum(hi[m], r)
    ok = hi >= lo
    if not ok.any():
        return 0
    lo = np.where(ok, lo, 0.0)
    hi = np.where(ok, hi, -1.0)
    ir0 = np.maximum(np.ceil(lo / dr - 0.5), 0).astype(np.int64)
    ir1 = np.minimum(np.floor(hi / dr - 0.5), nr - 1).astype(np.int64)
    ok &= ir1 >= ir0
    if not ok.any():
        return 0
    ir1 = np.where(ok, ir1, ir0 - 1)                       # 빈 열은 구간을 비운다
    r_lo, r_hi = int(ir0[ok].min()), int(ir1[ok].max())
    rows = np.arange(r_lo, r_hi + 1)
    mask = (rows[None, :] >= ir0[:, None]) & (rows[None, :] <= ir1[:, None])
    sub = stock.occ[iz0:iz1 + 1, r_lo:r_hi + 1]
    hit = mask & (sub == 1)
    removed = int(hit.sum())
    if cut and removed:
        sub[hit] = 0
        stock.col[iz0:iz1 + 1, r_lo:r_hi + 1][hit] = color
    return removed


# --------------------------------------------------------------------------
# 소재 (축대칭 점유 격자)
# --------------------------------------------------------------------------

class LatheStock:
    """반단면 점유 격자. 칸 (iz, ir)의 중심 = (z0 + (iz+.5)*dz, (ir+.5)*dr)."""

    is_voxel = False
    is_lathe = True

    def __init__(self, bounds, resolution):
        self.resolution = float(resolution)
        z_lo, z_hi = bounds['z']
        r_lo, r_hi = bounds['r']
        self.z0 = float(z_lo)
        self.zlo, self.ztop = float(z_lo), float(z_hi)
        self.r_min, self.r_max = float(r_lo), float(r_hi)
        self.nz = max(2, int(round((z_hi - z_lo) / self.resolution)))
        self.nr = max(2, int(round(r_hi / self.resolution)))
        self.dz = (z_hi - z_lo) / self.nz
        self.dr = r_hi / self.nr
        rows = (np.arange(self.nr) + 0.5) * self.dr
        self._occ0 = np.ascontiguousarray(
            np.repeat((rows >= self.r_min).astype(np.uint8)[None, :], self.nz, axis=0))
        self.occ = self._occ0.copy()
        self.col = np.full((self.nz, self.nr), UNCUT_COLOR, dtype=np.uint8)
        self.rapid_cut_warnings = []
        self.thread_cut_count = 0

    # -- 정보 ---------------------------------------------------------------
    def cell_count(self):
        return self.nz * self.nr

    def any_cut(self):
        return bool((self.occ != self._occ0).any())

    def removed_fraction(self):
        weight = (np.arange(self.nr) + 0.5)
        total = float((self._occ0 * weight[None, :]).sum())
        if total <= 0:
            return 0.0
        left = float((self.occ * weight[None, :]).sum())
        return 1.0 - left / total

    def extent(self):
        return ((self.z0, self.z0 + self.nz * self.dz), (-self.r_max, self.r_max))

    # -- 상태 ---------------------------------------------------------------
    def reset(self):
        self.occ = self._occ0.copy()
        self.col = np.full((self.nz, self.nr), UNCUT_COLOR, dtype=np.uint8)
        self.rapid_cut_warnings = []
        self.thread_cut_count = 0

    def clone(self):
        other = LatheStock.__new__(LatheStock)
        other.__dict__.update(self.__dict__)
        other.occ = self.occ.copy()
        other.col = self.col.copy()
        other.rapid_cut_warnings = list(self.rapid_cut_warnings)
        return other

    def snapshot(self):
        return (zlib.compress(self.occ.tobytes(), 1), zlib.compress(self.col.tobytes(), 1),
                self.thread_cut_count)

    @staticmethod
    def snapshot_bytes(snap):
        return len(snap[0]) + len(snap[1])

    def restore(self, snap):
        shape = (self.nz, self.nr)
        self.occ = np.frombuffer(zlib.decompress(snap[0]), dtype=np.uint8).reshape(shape).copy()
        self.col = np.frombuffer(zlib.decompress(snap[1]), dtype=np.uint8).reshape(shape).copy()
        self.thread_cut_count = int(snap[2]) if len(snap) > 2 else 0

    # -- 절삭 ---------------------------------------------------------------
    def cut_batch(self, P0, P1, tools, tool_idx, rapid, color, src_lines=None, seqs=None,
                  cancel=None, progress=None, chunk=SIM_CHUNK_SEGMENTS, use_numba=None,
                  thread_pitch=None, thread_height=None, **_ignored):
        """선분 묶음을 순서대로 깎는다(밀링 엔진과 같은 규약).

        P0/P1     : (M, 3) 월드 점 — (z, r)는 (열 0, 열 2)
        tools     : LatheTool(또는 None) 목록, tool_idx[m] = 그 선분의 공구 위치(음수/None 공구면 건너뜀)
        thread_pitch/height : (M,) 나사(G76) 선분 표시 — 피치 > 0이면 그 선분은 절삭 이동이 아니라
                              나사 구간(시작점→끝점)으로 처리한다.
        돌려줌: 끝까지 했으면 True, 취소로 멈췄으면 False."""
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        total = P0.shape[0]
        if total == 0:
            return True
        tool_idx = np.asarray(tool_idx, dtype=np.int64).copy()
        invalid = np.array([t is None or t.poly is None for t in tools] + [True], dtype=bool)
        tool_idx[(tool_idx < 0) | invalid[np.minimum(tool_idx, len(tools))]] = -1
        rapid = np.asarray(rapid, dtype=bool)
        color = np.clip(np.asarray(color, dtype=np.int64), 0, UNCUT_COLOR - 1).astype(np.uint8)
        pitch = np.zeros(total) if thread_pitch is None else np.asarray(thread_pitch, dtype=np.float64)
        height = np.zeros(total) if thread_height is None else np.asarray(thread_height, dtype=np.float64)

        min_hit_cells = max(1, int(math.ceil(RAPID_HIT_MIN_AREA / (self.dz * self.dr))))
        # 반경: 보통의 선삭 점은 y = 0이라 부호 있는 z를 그대로 쓴다(X 음수 = 축을 지나가는 정면 가공).
        # M35 뒤 C가 남은 채 선삭하면 회전된 점(y ≠ 0)이 오므로 그때만 hypot(y, z)로 반경을 구한다.
        R0 = np.where(np.abs(P0[:, 1]) < 1e-9, P0[:, 2], np.hypot(P0[:, 1], P0[:, 2]))
        R1 = np.where(np.abs(P1[:, 1]) < 1e-9, P1[:, 2], np.hypot(P1[:, 1], P1[:, 2]))
        numba_mod = None
        if use_numba is None:
            use_numba = total >= NUMBA_MIN_SEGMENTS
        if use_numba:
            numba_mod = _load_numba()
            if numba_mod is not None and not hasattr(numba_mod, 'cut_chunk_lathe'):
                numba_mod = None
        polys = [t.poly if (t is not None and t.poly is not None) else np.zeros((1, 2)) for t in tools]
        counts = np.array([p.shape[0] for p in polys], dtype=np.int64)
        offsets = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.int64)
        poly_z = np.ascontiguousarray(np.concatenate([p[:, 0] for p in polys]))
        poly_r = np.ascontiguousarray(np.concatenate([p[:, 1] for p in polys]))

        for start in range(0, total, chunk):
            if cancel is not None and cancel():
                return False
            end = min(start + chunk, total)
            is_thread = pitch[start:end] > 0            # G76 선분(뷰어에서는 급속 사선으로 기록됨)
            spans = []
            cursor = start
            for m in np.nonzero(is_thread)[0]:
                g = start + int(m)
                if g > cursor:
                    spans.append((cursor, g, False))
                spans.append((g, g + 1, True))
                cursor = g + 1
            if cursor < end:
                spans.append((cursor, end, False))
            for a, b, thread in spans:
                if thread:
                    self._cut_thread(np.array([P0[a, 0], 0.0, R0[a]]), np.array([P1[a, 0], 0.0, R1[a]]),
                                     tools[tool_idx[a]] if tool_idx[a] >= 0 else None,
                                     pitch[a], height[a], int(color[a]))
                    continue
                hit = np.zeros(b - a, dtype=np.int32)
                if numba_mod is not None:
                    numba_mod.cut_chunk_lathe(
                        self.occ, self.col, self.z0, self.dz, self.dr,
                        np.ascontiguousarray(P0[a:b, 0]), np.ascontiguousarray(R0[a:b]),
                        np.ascontiguousarray(P1[a:b, 0]), np.ascontiguousarray(R1[a:b]),
                        tool_idx[a:b].astype(np.int32), color[a:b], rapid[a:b],
                        poly_z, poly_r, offsets, counts, hit)
                else:
                    self._cut_chunk_numpy(P0[a:b], P1[a:b], R0[a:b], R1[a:b], polys, tool_idx[a:b],
                                          color[a:b], rapid[a:b], hit)
                for m in np.nonzero((hit >= min_hit_cells) & rapid[a:b])[0]:
                    g = a + int(m)
                    src = None if src_lines is None else src_lines[g]
                    seq = None if seqs is None else seqs[g]
                    self.rapid_cut_warnings.append((None if src is None else int(src),
                                                    None if seq is None else int(seq)))
            if progress is not None:
                progress(end, total)
        return True

    def _cut_chunk_numpy(self, P0, P1, R0, R1, polys, tool_idx, color, rapid, hit):
        for m in range(P0.shape[0]):
            t = int(tool_idx[m])
            if t < 0:
                continue
            poly = polys[t]
            a = np.array([P0[m, 0], R0[m]])
            b = np.array([P1[m, 0], R1[m]])
            hull = _hull_numpy(np.vstack([poly + a, poly + b]))
            hit[m] = _fill_hull_numpy(self, hull, int(color[m]), cut=not rapid[m])

    def _cut_thread(self, p0, p1, tool, pitch, height, color):
        """G76 나사 — 시작점(p0)→끝점(p1)의 z 구간에 피치 간격으로 V홈 고리를 판다.
        끝점의 r = 나사 골(외경) / 큰 지름(내경). height(mm)는 나사산 높이(0이면 피치 x 0.6134)."""
        if tool is None or pitch <= 0:
            return
        half = math.radians((tool.thread_angle or 60.0) / 2.0)
        internal = tool.internal
        r_end = abs(float(p1[2]))
        depth = float(height) if height > 0 else pitch * 0.6134
        flat = pitch / 8.0
        z_a, z_b = float(p0[0]), float(p1[0])
        sign = 1.0 if z_a >= z_b else -1.0
        count = int(math.floor(abs(z_a - z_b) / pitch + 1e-9)) + 1
        tan_half = math.tan(half)
        rows = (np.arange(self.nr) + 0.5) * self.dr
        # V홈은 골에서 바깥(외경)/안쪽(내경)으로 열린다. 나사 공구의 날 높이를 나사산 높이의 2배로
        # 보고(THREAD_TOOL_HEIGHT_FACTOR) 그 안의 소재만 판다 — 큰 지름보다 조금 큰 소재는 얇은 막이
        # 남지 않게 처리하고, 나사 구간 밖의 어깨까지 V가 넓어져 깎아 먹는 일은 막는다.
        reach = depth * THREAD_TOOL_HEIGHT_FACTOR
        wmax = flat / 2.0 + reach * tan_half
        for k in range(count):
            zk = z_b + sign * pitch * k
            iz0 = max(int(math.ceil((zk - wmax - self.z0) / self.dz - 0.5)), 0)
            iz1 = min(int(math.floor((zk + wmax - self.z0) / self.dz - 0.5)), self.nz - 1)
            if iz1 < iz0:
                continue
            zc = self.z0 + (np.arange(iz0, iz1 + 1) + 0.5) * self.dz
            climb = np.maximum(np.abs(zc - zk) - flat / 2.0, 0.0) / tan_half
            if internal:
                inside = (rows[None, :] <= (r_end - climb)[:, None]) & (rows[None, :] >= r_end - reach)
            else:
                inside = (rows[None, :] >= (r_end + climb)[:, None]) & (rows[None, :] <= r_end + reach)
            sub = self.occ[iz0:iz1 + 1]
            hit = inside & (sub == 1)
            if hit.any():
                sub[hit] = 0
                self.col[iz0:iz1 + 1][hit] = color
        self.thread_cut_count += 1

    # -- 표시 메쉬 ------------------------------------------------------------
    def display_mesh(self, max_n=600, color_map=None, mode='tool', default_color=DEFAULT_STOCK_COLOR,
                     edges=True, section='3q'):
        """화면용 메쉬(회전체) — 돌려줌: (verts Nx3 float32, faces Mx3 int32, colors Nx4 float32,
        edge_verts Kx3 float32). 조명 없이 정점 색만 쓰고 뒷면 제거도 안 하므로 열린 면이어도 된다.

        section: '3q' 3/4 단면(앞쪽 위 사분면 제거) / 'half' 반 단면 / 'full' 전체."""
        occ, cid, dz, dr = self._coarse(max_n)
        nzd, nrd = occ.shape
        theta0, theta1, caps = {'3q': (0.0, 270.0, True), 'half': (0.0, 180.0, True),
                                'full': (0.0, 360.0, False)}.get(section, (0.0, 270.0, True))
        segs = _boundary_segments(occ, cid, self.z0, dz, dr)
        n_theta = _theta_steps(self.r_max, theta1 - theta0)
        thetas = np.radians(np.linspace(theta0, theta1, n_theta + 1))
        verts, faces, colors = _revolve_segments(segs, thetas, color_map, mode, default_color, self.r_max)
        if caps:
            cap_v, cap_f, cap_c = _section_caps(occ, self.z0, dz, dr, (theta0, theta1))
            if cap_v.shape[0]:
                faces = np.concatenate([faces, cap_f + verts.shape[0]])
                verts = np.concatenate([verts, cap_v])
                colors = np.concatenate([colors, cap_c])
        edge_pts = _edge_lines(segs, thetas, (theta0, theta1), caps) if edges else []
        edge_verts = (np.array(edge_pts, dtype=np.float32).reshape(-1, 3) if edge_pts
                      else np.zeros((0, 3), dtype=np.float32))
        return (verts.astype(np.float32), faces.astype(np.int32), colors.astype(np.float32),
                edge_verts)

    def to_mesh(self, *_args, **_kwargs):
        raise NotImplementedError('선반 소재는 STL 내보내기를 지원하지 않는다')

    def _coarse(self, max_n):
        """표시용으로 격자를 합친다(블록의 절반 이상이 소재면 소재). 돌려줌: (occ bool, 색 id, dz, dr)."""
        fz = max(1, int(math.ceil(self.nz / (2.0 * max_n))))
        fr = max(1, int(math.ceil(self.nr / float(max_n))))
        if fz == 1 and fr == 1:
            return self.occ.astype(bool), self.col, self.dz, self.dr
        nzc, nrc = -(-self.nz // fz), -(-self.nr // fr)
        pad_o = np.zeros((nzc * fz, nrc * fr), dtype=np.uint8)
        pad_o[:self.nz, :self.nr] = self.occ
        pad_c = np.full((nzc * fz, nrc * fr), UNCUT_COLOR, dtype=np.uint8)
        pad_c[:self.nz, :self.nr] = self.col
        blocks_o = pad_o.reshape(nzc, fz, nrc, fr).mean(axis=(1, 3))
        blocks_c = pad_c.reshape(nzc, fz, nrc, fr)
        cut_only = np.where(blocks_c == UNCUT_COLOR, -1, blocks_c.astype(np.int16))
        best = cut_only.max(axis=(1, 3))
        cid = np.where(best < 0, UNCUT_COLOR, best).astype(np.uint8)
        return blocks_o >= 0.5, cid, self.dz * fz, self.dr * fr


# --------------------------------------------------------------------------
# 표시 메쉬 도우미
# --------------------------------------------------------------------------

def _theta_steps(r_max, span_deg):
    """호의 현 오차(sagitta) 0.1mm 이하가 되는 각도 분할 수(36~144 / 360°)."""
    r = max(float(r_max), 1.0)
    step = 2.0 * math.degrees(math.acos(max(1.0 - 0.1 / r, 0.5)))
    per_turn = int(min(max(math.ceil(360.0 / max(step, 1e-3)), 36), 144))
    return max(4, int(math.ceil(per_turn * span_deg / 360.0)))


def _boundary_segments(occ, cid, z0, dz, dr):
    """점유 격자의 경계(소재/빈 칸 사이) 선분 (z1, r1, z2, r2, 색id)를 모은다. 축(r=0) 쪽은 경계가 아니다.
    색은 빈 쪽 칸(깎은 공정)의 것, 소재 바깥과 만나는 면은 미절삭 색. 같은 색의 이어진 칸은 합친다."""
    nz, nr = occ.shape
    padz = np.zeros((nz + 2, nr), dtype=bool)
    padz[1:-1] = occ
    color_pad = np.full((nz + 2, nr), UNCUT_COLOR, dtype=np.uint8)
    color_pad[1:-1] = cid
    out = []
    # z 방향 경계: 인접한 두 열이 다르면 z = 경계에 세로 선분(r 구간)
    diff = padz[:-1] != padz[1:]
    for k in range(nz + 1):
        row = diff[k]
        if not row.any():
            continue
        void_color = np.where(padz[k], color_pad[k + 1], color_pad[k])
        out += _runs(row, void_color, lambda a, b, c, kk=k: (z0 + kk * dz, a * dr, z0 + kk * dz, b * dr, c))
    # r 방향 경계: 축 쪽(-1)은 첫 행을 그대로 복제(경계 없음), 바깥쪽 끝은 소재 바깥(빈 칸)
    padr = np.zeros((nz, nr + 2), dtype=bool)
    padr[:, 0] = occ[:, 0]
    padr[:, 1:-1] = occ
    color_r = np.full((nz, nr + 2), UNCUT_COLOR, dtype=np.uint8)
    color_r[:, 1:-1] = cid
    color_r[:, 0] = cid[:, 0]
    diff_r = padr[:, :-1] != padr[:, 1:]
    for k in range(nr + 1):
        col = diff_r[:, k]
        if not col.any():
            continue
        if k == 0:
            continue                               # 축 — 실제 표면이 아니다
        void_color = np.where(padr[:, k], color_r[:, k + 1], color_r[:, k])
        out += _runs(col, void_color, lambda a, b, c, kk=k: (z0 + a * dz, (kk) * dr, z0 + b * dz, kk * dr, c))
    return np.array(out, dtype=np.float64).reshape(-1, 5)


def _runs(mask, colors, make):
    """mask가 True인 칸의 이어진 구간(같은 색끼리)을 make(시작, 끝(포함+1), 색)로 바꿔 돌려준다."""
    idx = np.nonzero(mask)[0]
    if idx.size == 0:
        return []
    result = []
    start = idx[0]
    prev = idx[0]
    cur = int(colors[idx[0]])
    for i in idx[1:]:
        c = int(colors[i])
        if i == prev + 1 and c == cur:
            prev = i
            continue
        result.append(make(start, prev + 1, cur))
        start, prev, cur = i, i, c
    result.append(make(start, prev + 1, cur))
    return result


def _segment_colors(cids, color_map, mode, default_color):
    default = np.array(default_color, dtype=np.float32)
    out = np.tile(default, (len(cids), 1))
    if mode == 'solid' or not color_map:
        return out
    for cid, rgba in color_map.items():
        out[cids == cid] = np.asarray(rgba, dtype=np.float32)
    return out


def _revolve_segments(segs, thetas, color_map, mode, default_color, r_max):
    """경계 선분을 주축(월드 X) 둘레로 thetas만큼 돌려 사각형 띠 메쉬를 만든다.
    월드 점 = (z, r sin θ, r cos θ) (lathe_world_point와 같은 규약)."""
    if segs.shape[0] == 0:
        return (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), np.zeros((0, 4)))
    keep = (segs[:, 1] > 0) | (segs[:, 3] > 0)
    segs = segs[keep]
    n = segs.shape[0]
    nt = thetas.size
    ends = np.stack([segs[:, 0:2], segs[:, 2:4]], axis=1)                   # (n, 2, 2) [z, r]
    sin_t, cos_t = np.sin(thetas), np.cos(thetas)
    x = np.broadcast_to(ends[:, :, 0:1], (n, 2, nt))
    y = ends[:, :, 1:2] * sin_t[None, None, :]
    z = ends[:, :, 1:2] * cos_t[None, None, :]
    verts = np.stack([x, y, z], axis=-1).reshape(-1, 3)
    base = (np.arange(n) * 2 * nt)[:, None]
    j = np.arange(nt - 1)[None, :]
    a = base + j
    b = base + nt + j
    faces = np.stack([np.stack([a, b, b + 1], axis=-1), np.stack([a, b + 1, a + 1], axis=-1)], axis=2)
    faces = faces.reshape(-1, 3)
    seg_color = _segment_colors(segs[:, 4].astype(np.int64), color_map, mode, default_color)
    if mode == 'depth':
        radii = ends[:, :, 1]                                              # (n, 2)
        depth = depth_colors(radii.reshape(-1), r_max, 0.0, float(default_color[3]))
        colors = np.repeat(depth, nt, axis=0)
    else:
        colors = np.repeat(seg_color, 2 * nt, axis=0)
    return verts, faces, colors


def _section_caps(occ, z0, dz, dr, theta_range):
    """단면(잘라낸 면)의 채움 사각형 — 두 단면 평면에 각각 그린다. 같은 열 패턴이 이어지면 합친다."""
    nz, nr = occ.shape
    if nz == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), np.zeros((0, 4))
    same = (occ[1:] == occ[:-1]).all(axis=1)
    starts = np.concatenate([[0], np.nonzero(~same)[0] + 1])
    ends = np.concatenate([starts[1:], [nz]])
    quads = []
    for s, e in zip(starts, ends):
        column = occ[s]
        if not column.any():
            continue
        d = np.diff(np.concatenate([[0], column.astype(np.int8), [0]]))
        for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            quads.append((z0 + s * dz, z0 + e * dz, a * dr, b * dr))
    if not quads:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), np.zeros((0, 4))
    q = np.array(quads)
    verts, faces = [], []
    for theta in theta_range:
        t = math.radians(theta)
        st, ct = math.sin(t), math.cos(t)
        for z_a, z_b, r_a, r_b in q:
            k = len(verts)
            verts += [(z_a, r_a * st, r_a * ct), (z_b, r_a * st, r_a * ct),
                      (z_b, r_b * st, r_b * ct), (z_a, r_b * st, r_b * ct)]
            faces += [(k, k + 1, k + 2), (k, k + 2, k + 3)]
    verts = np.array(verts, dtype=np.float64)
    faces = np.array(faces, dtype=np.int64)
    colors = np.tile(np.array(CAP_COLOR, dtype=np.float32), (verts.shape[0], 1))
    return verts, faces, colors


def _edge_lines(segs, thetas, theta_range, caps):
    """모서리 선: 단면 윤곽(두 단면 평면) + 큰 단차(길이 0.6mm 이상 세로 선분)의 둘레 고리."""
    pts = []
    if segs.shape[0] == 0:
        return pts
    if caps:
        for theta in theta_range:
            t = math.radians(theta)
            st, ct = math.sin(t), math.cos(t)
            for z1, r1, z2, r2, _c in segs:
                pts.append((z1, r1 * st, r1 * ct))
                pts.append((z2, r2 * st, r2 * ct))
    vertical = segs[(segs[:, 0] == segs[:, 2]) & (np.abs(segs[:, 3] - segs[:, 1]) >= 0.6)]
    for z1, r1, _z2, r2, _c in vertical[:400]:
        for radius in (r1, r2):
            if radius <= 0:
                continue
            ring = np.stack([np.full(thetas.size, z1), radius * np.sin(thetas), radius * np.cos(thetas)], axis=1)
            for a, b in zip(ring[:-1], ring[1:]):
                pts.append(tuple(a))
                pts.append(tuple(b))
    return pts


# --------------------------------------------------------------------------
# 턴밀(M2): 진입 벡터로 공구 축 정하기
# --------------------------------------------------------------------------

AXIS_PLANE_TOLERANCE_DEG = 30.0       # 진입 벡터가 평면 법선에서 이만큼 넘게 벗어나면 평면 코드로 보정


def plane_normal(plane, point, c_deg=None):
    """평면 코드의 공구 축 후보(팁→홀더): G17 = +월드 X(기계 +Z쪽에서 접근), G19 = C 각도에서의 기계 +X 방향
    (월드 (0, sin C, cos C) — lathe_rotate_c와 같은 규약). Y 오프셋이 있는 옆면 가공(페이스커터 등)도 축은 기계 X
    방향이므로 공구 위치가 아니라 C 각도로 정한다. C를 모르면 그 점의 반경 방향. 그 밖은 None."""
    if plane == 'G17':
        return np.array([1.0, 0.0, 0.0])
    if plane == 'G19':
        if c_deg is not None:
            c = math.radians(float(c_deg))
            return np.array([0.0, math.sin(c), math.cos(c)])
        radial = np.array([0.0, float(point[1]), float(point[2])])
        norm = float(np.linalg.norm(radial))
        return radial / norm if norm > 1e-6 else np.array([0.0, 0.0, 1.0])
    return None


def entry_axes(p0, p1, rapid, breaks, planes=None, c_angles=None):
    """턴밀 선분마다 공구 축(단위벡터, 팁→홀더)을 정한다(사용자 결정 I: 진입 벡터 방향).

    가공 묶음 = 급속 이동이나 breaks(공정이 바뀌는 곳) 사이의 연속 절삭 이송. 묶음의 첫 절삭 이동(진입)의
    방향 e에서 축 = -e. 진입이 평면 법선(plane_normal)에서 AXIS_PLANE_TOLERANCE_DEG보다 크게 벗어나면
    (측면 진입 등) 평면 법선으로 보정한다. 두 묶음 사이의 급속 이동들은 앞 묶음의 축(후퇴 — 공구는 아직
    그 자세)을 쓰고, 마지막 급속(다음 진입 직전의 접근)만 뒤 묶음의 축을 쓴다. 앞 묶음이 없으면 모두 뒤 묶음,
    뒤 묶음이 없으면 모두 앞 묶음의 축.
    돌려줌: (axes (M,3), 보정한 묶음 수)."""
    p0 = np.asarray(p0, dtype=np.float64).reshape(-1, 3)
    p1 = np.asarray(p1, dtype=np.float64).reshape(-1, 3)
    rapid = np.asarray(rapid, dtype=bool)
    breaks = np.asarray(breaks, dtype=bool)
    count = p0.shape[0]
    axes = np.tile([1.0, 0.0, 0.0], (count, 1))
    assigned = np.zeros(count, dtype=bool)
    corrected = 0
    cos_tol = math.cos(math.radians(AXIS_PLANE_TOLERANCE_DEG))
    m = 0
    while m < count:
        if rapid[m]:
            m += 1
            continue
        start = m
        end = m + 1
        while end < count and not rapid[end] and not breaks[end]:
            end += 1
        axis = None
        for k in range(start, end):
            e = p1[k] - p0[k]
            length = float(np.linalg.norm(e))
            if length > 1e-6:
                axis = -e / length
                normal = plane_normal(planes[k] if planes is not None else None, p0[k],
                                      c_angles[k] if c_angles is not None else None)
                if normal is not None and abs(float(np.dot(axis, normal))) < cos_tol:
                    axis = normal
                    corrected += 1
                elif normal is not None and float(np.dot(axis, normal)) < 0:
                    axis = normal           # 법선 쪽으로 진입(반대로 빠져나감)하는 경우도 홀더는 바깥쪽
                break
        if axis is None:
            normal = plane_normal(planes[start] if planes is not None else None, p0[start],
                                  c_angles[start] if c_angles is not None else None)
            axis = normal if normal is not None else np.array([1.0, 0.0, 0.0])
        axes[start:end] = axis
        assigned[start:end] = True
        m = end
    # 급속 이동(묶음 사이 구간): 후퇴·중간 = 앞 묶음 축, 마지막 접근 = 뒤 묶음 축
    k = 0
    while k < count:
        if assigned[k]:
            k += 1
            continue
        run_start = k
        while k < count and not assigned[k]:
            k += 1
        run_end = k                                    # [run_start, run_end) 는 축이 없는 급속 구간
        # 공정(공구)이 바뀌는 곳(breaks)에서는 앞 공정의 자세를 이어 쓰지 않는다 — 경계 앞은 앞 묶음,
        # 경계부터는 뒤 묶음의 축(O4811 실측: 페이스커터 접근이 앞 공정 드릴의 C-180 자세를 물려받아
        # 몸체가 소재를 관통하는 것으로 계산됐다).
        cut = next((j for j in range(run_start, run_end) if breaks[j]), None)
        if cut is not None:
            prev_axis = axes[run_start - 1].copy() if run_start > 0 else None
            next_axis = axes[run_end].copy() if run_end < count else None
            if prev_axis is not None and cut > run_start:
                axes[run_start:cut] = prev_axis
            fill = next_axis if next_axis is not None else prev_axis
            if fill is not None:
                axes[cut:run_end] = fill
            continue
        prev_axis = axes[run_start - 1].copy() if run_start > 0 else None
        next_axis = axes[run_end].copy() if run_end < count else None
        if prev_axis is None and next_axis is None:
            continue
        if prev_axis is None:
            axes[run_start:run_end] = next_axis
        elif next_axis is None or run_end - run_start == 1:
            axes[run_start:run_end] = prev_axis
        else:
            axes[run_start:run_end - 1] = prev_axis
            axes[run_end - 1] = next_axis
    return axes, corrected


# --------------------------------------------------------------------------
# 턴밀(M2): 축대칭 격자 + 3D 복셀 하이브리드 소재
# --------------------------------------------------------------------------

TURNMILL_TARGET_VOXELS = 20_000_000
SYNC_SLAB = 32                        # 축대칭 → 복셀 동기화를 이만큼의 X 칸씩 나눠 한다(메모리 절약)


class TurnMillStock:
    """선삭(LatheStock, 진실 원천) + 턴밀(nc_sim3d.VoxelStock). 뷰어에서는 선반 소재로 다룬다(is_lathe).

    - 선삭 선분은 축대칭 격자에서 깎는다(미세). 턴밀 선분은 복셀에서 깎는다.
    - 턴밀을 깎기 직전과 표시 직전에 선삭 결과를 복셀에 반영한다(sync). 재료 제거는 순서와 무관하게
      최종 형상이 같다(교환 법칙) — 선삭이 턴밀 뒤에 와도 결과가 같다.
    - 표시는 복셀 메쉬(표면 넷). 선삭 세부는 복셀 크기로 표시된다(결정 G)."""

    is_lathe = True
    is_voxel = False
    is_turnmill = True
    heavy = True                      # 작은 묶음도 백그라운드 계산(3D라 무겁다)

    def __init__(self, bounds, resolution, voxel_resolution):
        self.lathe = LatheStock(bounds, resolution)
        r = float(bounds['r'][1])
        self.voxel = nc_sim3d.VoxelStock({'X': bounds['z'], 'Y': (-r, r), 'Z': (-r, r)}, voxel_resolution)
        self.resolution = float(resolution)
        self.voxel_resolution = float(voxel_resolution)
        self._build_maps()
        self.rapid_cut_warnings = []
        self.milled = False
        self._dirty = True
        self._section_cache = None
        self.sync()

    # -- 좌표 대응 -----------------------------------------------------------
    def _build_maps(self):
        a, v = self.lathe, self.voxel
        rx, ry, rz = v.step
        xs = v.x0 + (np.arange(v.nx) + 0.5) * rx
        iz = np.floor((xs - a.z0) / a.dz).astype(np.int64)
        self._iz = np.where((iz >= 0) & (iz < a.nz), iz, -1)
        ys = v.y0 + (np.arange(v.ny) + 0.5) * ry
        zs = v.z0 + (np.arange(v.nz) + 0.5) * rz
        radius = np.hypot(ys[:, None], zs[None, :])
        ir = np.floor(radius / a.dr).astype(np.int64)
        self._ir = np.where(ir < a.nr, ir, -1)
        self._ys, self._zs = ys, zs

    def sync(self):
        """선삭 결과(축대칭 격자)를 복셀에 반영한다 — 선삭으로 새로 사라진 복셀을 지우고 그 공정 색을 남긴다."""
        if not self._dirty:
            return
        a, v = self.lathe, self.voxel
        ir_ok = self._ir >= 0
        ir = np.where(ir_ok, self._ir, 0)
        changed = False
        for i0 in range(0, v.nx, SYNC_SLAB):
            i1 = min(i0 + SYNC_SLAB, v.nx)
            iz = self._iz[i0:i1]
            iz_ok = iz >= 0
            izc = np.where(iz_ok, iz, 0)
            keep = a.occ[izc[:, None, None], ir[None, :, :]].astype(bool)
            keep &= iz_ok[:, None, None] & ir_ok[None, :, :]
            occ = v.occ[i0:i1]
            gone = (occ == 1) & ~keep
            if gone.any():
                occ[gone] = 0
                v.col[i0:i1][gone] = a.col[izc[:, None, None], ir[None, :, :]][gone]
                changed = True
        if changed:
            v._version += 1                    # 표시 캐시는 실제로 바뀌었을 때만 무효화
            self._section_cache = None
        self._dirty = False

    # -- 정보 ---------------------------------------------------------------
    def any_cut(self):
        return self.lathe.any_cut() or self.milled

    def removed_fraction(self):
        return self.lathe.removed_fraction()

    def extent(self):
        return self.lathe.extent()

    @property
    def thread_cut_count(self):
        return self.lathe.thread_cut_count

    @property
    def occ(self):
        return self.lathe.occ

    def cell_count(self):
        return self.lathe.cell_count() + self.voxel.cell_count()

    # -- 상태 ---------------------------------------------------------------
    def reset(self):
        self.lathe.reset()
        self.voxel.reset()
        self.rapid_cut_warnings = []
        self.milled = False
        self._dirty = True
        self._section_cache = None
        self.sync()

    def clone(self):
        other = TurnMillStock.__new__(TurnMillStock)
        other.__dict__.update(self.__dict__)
        other.lathe = self.lathe.clone()
        other.voxel = self.voxel.clone()
        other.rapid_cut_warnings = list(self.rapid_cut_warnings)
        other._section_cache = None
        return other

    def snapshot(self):
        self.sync()
        return (self.lathe.snapshot(), self.voxel.snapshot(), self.milled)

    @staticmethod
    def snapshot_bytes(snap):
        return LatheStock.snapshot_bytes(snap[0]) + nc_sim3d.VoxelStock.snapshot_bytes(snap[1])

    def restore(self, snap):
        self.lathe.restore(snap[0])
        self.voxel.restore(snap[1])
        self.milled = bool(snap[2])
        self._dirty = False                # 스냅샷은 동기화된 상태로 찍었다
        self._section_cache = None

    # -- 절삭 ---------------------------------------------------------------
    def cut_batch(self, P0, P1, tools, tool_idx, rapid, color, src_lines=None, seqs=None,
                  cancel=None, progress=None, chunk=SIM_CHUNK_SEGMENTS, use_numba=None,
                  thread_pitch=None, thread_height=None, axes0=None, axes1=None, mill=None, **_ignored):
        """선삭 선분(mill=False)은 축대칭 격자로, 턴밀 선분(mill=True)은 복셀로 순서대로 깎는다."""
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        total = P0.shape[0]
        if total == 0:
            return True
        mill = np.zeros(total, dtype=bool) if mill is None else np.asarray(mill, dtype=bool)
        tool_idx = np.asarray(tool_idx)
        rapid = np.asarray(rapid, dtype=bool)
        color = np.asarray(color)
        pitch = np.zeros(total) if thread_pitch is None else np.asarray(thread_pitch, dtype=np.float64)
        height = np.zeros(total) if thread_height is None else np.asarray(thread_height, dtype=np.float64)
        axes0 = np.tile([1.0, 0.0, 0.0], (total, 1)) if axes0 is None else np.asarray(axes0, dtype=np.float64)
        axes1 = axes0 if axes1 is None else np.asarray(axes1, dtype=np.float64)
        src = np.full(total, -1) if src_lines is None else np.asarray(src_lines)
        seq = np.zeros(total, dtype=np.int64) if seqs is None else np.asarray(seqs)
        mill_tools = [t.mill_shape if t is not None else None for t in tools]
        edges = np.nonzero(np.diff(mill.astype(np.int8)))[0] + 1
        bounds = [0] + edges.tolist() + [total]
        for a, b in zip(bounds[:-1], bounds[1:]):
            def sub_progress(done, _total, offset=a):
                if progress is not None:
                    progress(offset + done, total)
            if mill[a]:
                self.sync()
                before = int(np.count_nonzero(self.voxel.occ))
                # 턴밀 선분은 적어도(페이스커터 한 번에 수백만 복셀) 무겁다 — 개수와 상관없이 numba를 쓴다
                # (nc_sim3d는 16개 미만이면 numpy로 가는데, O4811 실측 12개 선분에 44초가 걸렸다).
                voxel_numba = True if use_numba is None else use_numba
                ok = self.voxel.cut_batch(P0[a:b], P1[a:b], mill_tools, tool_idx[a:b], rapid[a:b], color[a:b],
                                          src_lines=src[a:b], seqs=seq[a:b], cancel=cancel, progress=sub_progress,
                                          chunk=chunk, use_numba=voxel_numba, axes0=axes0[a:b], axes1=axes1[a:b])
                if int(np.count_nonzero(self.voxel.occ)) < before:
                    self.milled = True
                    self._section_cache = None
                self.rapid_cut_warnings.extend(self.voxel.rapid_cut_warnings)
                self.voxel.rapid_cut_warnings = []
            else:
                ok = self.lathe.cut_batch(P0[a:b], P1[a:b], tools, tool_idx[a:b], rapid[a:b], color[a:b],
                                          src_lines=src[a:b], seqs=seq[a:b], cancel=cancel, progress=sub_progress,
                                          chunk=chunk, use_numba=use_numba,
                                          thread_pitch=pitch[a:b], thread_height=height[a:b])
                self._dirty = True
                self.rapid_cut_warnings.extend(self.lathe.rapid_cut_warnings)
                self.lathe.rapid_cut_warnings = []
            if not ok:
                return False
        return True

    # -- 표시 메쉬 ------------------------------------------------------------
    def display_mesh(self, max_n=600, color_map=None, mode='tool', default_color=DEFAULT_STOCK_COLOR,
                     edges=True, section='3q'):
        """복셀 메쉬(표면 넷). 단면 보기는 앞쪽 사분면(3/4)·앞쪽 반(반 단면)의 복셀을 비운 사본으로 그린다.
        깎인 깊이 색은 반경(바깥에서 얼마나 들어갔나) 기준."""
        self.sync()
        key = (self.voxel._version, section)
        cache = self._section_cache
        if cache is None or cache[0] != key:
            view = self.voxel
            if section in ('3q', 'half'):
                view = nc_sim3d.VoxelStock.__new__(nc_sim3d.VoxelStock)
                view.__dict__.update(self.voxel.__dict__)
                view.occ = self.voxel.occ.copy()           # 색(col)은 원본과 공유 — 표시에서 읽기만 한다
                view._mesh_cache = None
                cut_y = self._ys < 0.0
                cut_z = self._zs > 0.0 if section == '3q' else np.ones_like(self._zs, dtype=bool)
                view.occ[:, cut_y[:, None] & cut_z[None, :]] = 0     # (ny, nz) 마스크를 모든 X 칸에
                view._version += 1
            cache = (key, view)
            self._section_cache = cache
        view = cache[1]
        verts, faces, colors, edge_verts = view.display_mesh(
            color_map=color_map, mode='solid' if mode == 'depth' else mode,
            default_color=default_color, edges=edges)
        if mode == 'depth' and len(verts):
            radius = np.hypot(verts[:, 1], verts[:, 2])
            colors = depth_colors(radius, self.lathe.r_max, 0.0, float(default_color[3])).astype(np.float32)
        return verts, faces, colors, edge_verts

    def to_mesh(self, *_args, **_kwargs):
        raise NotImplementedError('선반 소재는 STL 내보내기를 지원하지 않는다')


def turnmill_voxel_resolution(bounds, safe_mode=False, numba_ok=True):
    """턴밀 복셀 해상도 — 소재를 감싸는 상자 기준 약 2,000만 복셀(numba가 없거나 안전 모드면 1/8)."""
    r = float(bounds['r'][1])
    box = {'X': bounds['z'], 'Y': (-r, r), 'Z': (-r, r)}
    target = TURNMILL_TARGET_VOXELS
    if safe_mode or not numba_ok:
        target //= 8
    return nc_sim3d.auto_resolution_3d(box, target)

