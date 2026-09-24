"""nc_sim.py — 밀링 3축 형상 가공 시뮬레이션 엔진 (v1.9.0, 속도·표시 개선 v1.9.2).

Qt에 의존하지 않는 순수 numpy 모듈이다. STOCK을 Z-map(XY 격자마다 남은 소재
윗면 높이 하나)으로 표현하고, Tool tip 경로를 따라 공구 형상(회전체)을 빼서
가공 형상을 근사한다.

3축 전용이다 — 공구 축이 항상 월드 +Z라고 가정한다. G68.2 경사면(3+2)이나
동시 5축처럼 공구 축이 기울어지는 구간은 이 모듈이 알지 못하므로, 호출부
(nc_viewer_widget)가 그런 구간의 노드를 걸러내고 넘겨야 한다.

공구 형상 규칙(사용자 확정, 2026-09-23):
  FLAT E/M, DYNAMIC E/M        : 평바닥 원기둥
  FILLET E/M, CUTTER, FACE MILL: 평바닥 + 바닥 모서리 R (곡면 코너)
  BALL E/M                     : 반구형 팁(코너 R = D/2인 FILLET과 같은 식)
  DRILL                        : 원뿔 팁, 각도 SIG(전각, 기본 118°)
  PL 값이 있는 그 외 공구       : 중심은 평평하고 반경 D/2 - PL 지점부터
                                  45°로 깎여 올라가는 "각진 U자"(평 챔퍼) 팁
  그 외(PL도 없음)              : 평바닥 원기둥(D)으로 대체
"""

from __future__ import annotations

import os
import struct

import numpy as np

# --------------------------------------------------------------------------
# 공구 형상(ToolShape)
# --------------------------------------------------------------------------

TYPE_FLAT = {'FLAT E/M', 'DYNAMIC E/M'}
TYPE_FILLET = {'FILLET E/M', 'CUTTER', 'FACE MILL'}
TYPE_BALL = {'BALL E/M'}
TYPE_DRILL = {'DRILL'}

DEFAULT_DRILL_ANGLE_DEG = 118.0


class ToolShape:
    """공구 축 = +Z, 원점 = Tool tip(가장 아래 점) 기준 회전체 형상.

    height_grid(r)은 공구 중심에서 수평 거리 r인 곳까지 팁에서 위로 얼마나
    올라가야 공구 표면인지 돌려준다. r이 radius를 넘는 자리는 nan이다
    (그 반경 밖은 이 공구가 닿지 않는다)."""

    def __init__(self, radius, profile_fn, length, type_name='', cut_length=None):
        self.radius = float(radius)
        self.length = float(length)
        # 소재를 깎는 축 방향 길이 — 날장(FL), 없으면 돌출(SO). 홀더는 표현하지 않는다.
        self.cut_length = float(cut_length) if cut_length else float(length)
        self.type_name = type_name
        self._profile_fn = profile_fn

    def height_grid(self, r):
        r = np.asarray(r, dtype=np.float64)
        h = self._profile_fn(r)
        return np.where(r <= self.radius + 1e-9, h, np.nan)

    def radial_lut(self, res):
        """격자 간격 res에 맞춘 반경 방향 높이표(LUT): (lut float64, 1/간격).

        lut[k] = 공구 중심에서 수평으로 k*간격 떨어진 곳의 팁 기준 높이. 간격 =
        반경/올림(반경/(res/32))라서 마지막 칸(k=N)이 정확히 반경(공구 끝)이고,
        보간을 위해 한 칸(N+1)을 더 둔다. 절삭은 칸-선분 거리 d로 이 표를 선형
        보간해 쓴다(v1.9.2). 해상도별로 캐시한다."""
        cache = self.__dict__.setdefault('_luts', {})
        key = round(float(res), 6)
        entry = cache.get(key)
        if entry is None:
            n = max(1, int(np.ceil(self.radius / (res / 32.0))))
            step = self.radius / n
            r = np.minimum(np.arange(n + 2) * step, self.radius)
            lut = np.ascontiguousarray(self.height_grid(r), dtype=np.float64)
            entry = (lut, 1.0 / step)
            cache[key] = entry
        return entry

    def height_at(self, r):
        """스칼라 반경 하나에 대한 팁 기준 높이. r > radius면 None."""
        if r > self.radius + 1e-9:
            return None
        return float(self._profile_fn(np.array([float(r)]))[0])


def _flat_profile():
    def fn(r):
        return np.zeros_like(r)
    return fn


def _corner_r_profile(radius, corner_r):
    corner_r = min(max(corner_r, 0.0), radius)
    flat_r = radius - corner_r

    def fn(r):
        h = np.zeros_like(r)
        if corner_r > 1e-9:
            mask = r > flat_r
            dr = np.clip(r[mask] - flat_r, 0.0, corner_r)
            h[mask] = corner_r - np.sqrt(np.maximum(corner_r ** 2 - dr ** 2, 0.0))
        return h
    return fn


def _cone_profile(half_angle_rad):
    slope = 1.0 / max(np.tan(max(half_angle_rad, 1e-4)), 1e-6)

    def fn(r):
        return r * slope
    return fn


def _chamfer_profile(radius, chamfer_height):
    chamfer_height = min(max(chamfer_height, 0.0), radius)
    flat_r = radius - chamfer_height

    def fn(r):
        return np.clip(r - flat_r, 0.0, None)
    return fn


def tool_shape_from_values(tool_type, d, fl=None, r=None, sig=None, pl=None, so=None):
    """툴리스트 한 공구의 값으로 ToolShape를 만든다.

    d(지름)가 없거나 0 이하면 형상을 만들 수 없어 None을 돌려준다 — 호출부가
    이 공구를 시뮬레이션에서 빼고 사용자에게 알려야 한다."""
    if not d or d <= 0:
        return None
    radius = d / 2.0
    length = so if so else (fl if fl else d * 3.0)
    cut_length = fl if fl else length
    name = (tool_type or '').strip().upper()

    if name in TYPE_BALL:
        return ToolShape(radius, _corner_r_profile(radius, radius), length, name, cut_length)
    if name in TYPE_DRILL:
        angle = sig if sig else DEFAULT_DRILL_ANGLE_DEG
        half = np.radians(max(angle, 1.0) / 2.0)
        return ToolShape(radius, _cone_profile(half), length, name, cut_length)
    if name in TYPE_FILLET:
        corner_r = r if r else 0.0
        return ToolShape(radius, _corner_r_profile(radius, corner_r), length, name, cut_length)
    if name in TYPE_FLAT:
        return ToolShape(radius, _flat_profile(), length, name, cut_length)
    if pl:
        return ToolShape(radius, _chamfer_profile(radius, pl), length, name, cut_length)
    return ToolShape(radius, _flat_profile(), length, name, cut_length)


# --------------------------------------------------------------------------
# 소재 배치(StockSpec)
# --------------------------------------------------------------------------

_AXES = ('X', 'Y', 'Z')
_HORIZONTAL_REFS = {'center', 'neg', 'pos'}
_VERTICAL_REFS = {'top', 'bottom', 'center'}


class StockSpec:
    """T/W/L 치수 + 축 배정 + 기준 위치 + 추가 이동 → 월드 bounds.

    dims: {'T':.., 'W':.., 'L':..} (mm, 0 이상)
    axis_of: {'T':'X'|'Y'|'Z', 'W':.., 'L':..} — 서로 다른 축이어야 함(1:1)
    reference: {'X':'center'|'neg'|'pos'|'top'|'bottom', 'Y':.., 'Z':..}
        X/Y: center(원점 중심, 기본) / neg(-쪽 끝=0) / pos(+쪽 끝=0)
        Z  : top(윗면=0, 기본 — 0에서 아래로) / bottom(바닥=0) / center
    offset: {'X':float, 'Y':float, 'Z':float} — 기준 위치에서 + 방향으로
        더 옮기는 양(추가 이동), 기본 0
    """

    def __init__(self, dims, axis_of, reference=None, offset=None):
        self.dims = {k: float(v) for k, v in dims.items()}
        self.axis_of = dict(axis_of)
        assigned = list(self.axis_of.values())
        if sorted(assigned) != sorted(_AXES):
            raise ValueError('axis_of must assign X/Y/Z exactly once each: %r' % (axis_of,))
        self.reference = {axis: 'center' for axis in _AXES}
        self.reference['Z'] = 'top'
        if reference:
            self.reference.update(reference)
        self.offset = {axis: 0.0 for axis in _AXES}
        if offset:
            self.offset.update({k: float(v) for k, v in offset.items()})

    def length_of(self, axis):
        for key, ax in self.axis_of.items():
            if ax == axis:
                return self.dims.get(key, 0.0)
        return 0.0

    def bounds(self):
        """{'X': (min, max), 'Y': (...), 'Z': (...)}"""
        result = {}
        for axis in _AXES:
            length = max(self.length_of(axis), 0.0)
            ref = self.reference.get(axis, 'center')
            off = self.offset.get(axis, 0.0)
            if ref == 'neg' or ref == 'bottom':
                lo, hi = 0.0, length
            elif ref == 'pos' or ref == 'top':
                lo, hi = -length, 0.0
            else:  # center
                lo, hi = -length / 2.0, length / 2.0
            result[axis] = (lo + off, hi + off)
        return result


def auto_resolution(bounds, target_cells=1_000_000, safe_mode=False):
    """소재 XY 면적이 대략 target_cells 격자가 되도록 해상도(mm)를 고른다.
    0.05~0.5mm 사이로 제한한다. safe_mode(그래픽 안전 모드)에서는 셀 수
    목표를 1/4로 낮춰 더 거친(빠른) 해상도를 고른다."""
    xlo, xhi = bounds['X']
    ylo, yhi = bounds['Y']
    area = max(xhi - xlo, 1e-6) * max(yhi - ylo, 1e-6)
    if safe_mode:
        target_cells = max(target_cells // 4, 1)
    res = float(np.sqrt(area / max(target_cells, 1)))
    res = min(max(res, 0.05), 0.5)
    return round(res, 3)


# --------------------------------------------------------------------------
# 성능 상수 (v1.9.2 — 튜닝은 여기서만)
# --------------------------------------------------------------------------

SIM_DISPLAY_GRID_MAX = 600          # 화면에 그리는 격자 한 변 최대 정점 수
SIM_DISPLAY_GRID_MAX_SAFE = 300     # 그래픽 안전 모드(v1.8.3)
SIM_SNAPSHOT_MEMORY_MB = 200        # 공정 시작 스냅샷 총 메모리 상한
SIM_CHUNK_SEGMENTS = 2000           # 취소·진행률 확인 단위(선분 수)
SIM_NUMBA_MIN_SEGMENTS = 64         # 이보다 적은 선분은 numpy로(컴파일 대기 회피)
SIM_EDGE_SEGMENT_LIMIT = 150000     # 모서리 선 개수 상한
SIM_EDGE_SLOPE = 1.0                # 이 기울기(dz/표시격자간격) 이상이면 "모서리"(45°)

# 표시 색(조명 없음 — 밝은 계통 단색 채움, 2026-09-24 사용자 지시)
DEFAULT_STOCK_COLOR = (0.80, 0.87, 0.96, 1.0)
EDGE_COLOR = (0.16, 0.22, 0.32, 1.0)
DEPTH_COLOR_STOPS = ((1.00, 0.94, 0.58), (0.62, 0.90, 0.62), (0.52, 0.76, 1.00))


# --------------------------------------------------------------------------
# Numba 경로(선택) — 없으면 numpy로 계산한다. 결과는 같다.
# --------------------------------------------------------------------------

_numba_module = None
_numba_tried = False


def _load_numba():
    """nc_sim_numba를 지연 import. 환경변수 NC_SIM_NUMBA=0이면 쓰지 않는다."""
    global _numba_module, _numba_tried
    if _numba_tried:
        return _numba_module
    _numba_tried = True
    if os.environ.get('NC_SIM_NUMBA', '1').strip() == '0':
        return None
    try:
        import nc_sim_numba
        _numba_module = nc_sim_numba
    except Exception:
        _numba_module = None
    return _numba_module


def numba_available():
    return _load_numba() is not None


SUB_Z = 0.25          # 조각당 최대 Z 변화 = 격자 간격 x SUB_Z (nc_sim_numba.SUB_Z와 같아야 함)
MAX_SUB = 400


def _stamp_numpy(stock, ax, ay, bx, by, z, lut, radius, inv_step, color, zlo32):
    """수평 선분 (ax,ay)->(bx,by)를 팁 높이 z로 훑는다(numpy). nc_sim_numba._stamp와
    같은 산식·같은 순서 — 각 칸에서 선분까지의 거리 d로 z + h(d)를 계산한다.
    깎인 칸이 있으면 True."""
    res = stock.resolution
    heights = stock.heights
    dx = bx - ax
    dy = by - ay
    len2 = dx * dx + dy * dy
    r2 = radius * radius + 1e-9
    ix0 = max(int(np.floor((min(ax, bx) - radius - stock.x0) / res)), 0)
    ix1 = min(int(np.ceil((max(ax, bx) + radius - stock.x0) / res)), stock.nx - 1)
    iy0 = max(int(np.floor((min(ay, by) - radius - stock.y0) / res)), 0)
    iy1 = min(int(np.ceil((max(ay, by) + radius - stock.y0) / res)), stock.ny - 1)
    if ix0 > ix1 or iy0 > iy1:
        return False
    px = (stock._gx[ix0:ix1 + 1] - ax)[None, :]
    py = (stock._gy[iy0:iy1 + 1] - ay)[:, None]
    if len2 > 0.0:
        t = np.clip((px * dx + py * dy) / len2, 0.0, 1.0)
        qx = px - t * dx
        qy = py - t * dy
    else:
        qx = px
        qy = py
    d2 = qx * qx + qy * qy
    inside = d2 <= r2
    pos = np.sqrt(d2) * inv_step
    k = np.minimum(pos.astype(np.int64), lut.size - 2)
    frac = pos - k
    h = lut[k] * (1.0 - frac) + lut[k + 1] * frac
    new = (z + h).astype(np.float32)
    np.maximum(new, zlo32, out=new)
    sub = heights[iy0:iy1 + 1, ix0:ix1 + 1]
    low = inside & (new < sub)
    np.copyto(sub, new, where=low)
    np.copyto(stock.color_ids[iy0:iy1 + 1, ix0:ix1 + 1], color, where=low)
    return bool(low.any())


# --------------------------------------------------------------------------
# Z-map 소재(ZMapStock)
# --------------------------------------------------------------------------

class ZMapStock:
    """XY 격자마다 남은 소재 윗면 높이 하나를 들고 있는 Z-map 소재.

    3축 전용(공구 축 = 월드 +Z) — 절삭은 각 격자점 위에서 공구 팁 기준
    높이(profile)를 빼는 것으로 근사한다. v1.9.2: 높이는 float32, 공구 색 id는
    int16이고, 각 칸에서 이동 선분까지의 수평 거리 d로 팁 Z + h(d)를 바로 구한다
    (h는 ToolShape.radial_lut로 미리 만든 반경별 높이표) — 샘플 위치를 격자에
    맞추지 않아 오차가 없고, 커널을 여러 번 찍는 것보다 훨씬 적게 계산한다."""

    def __init__(self, bounds, resolution):
        self.resolution = float(resolution)
        xlo, xhi = bounds['X']
        ylo, yhi = bounds['Y']
        zlo, zhi = bounds['Z']
        self.x0, self.y0 = float(xlo), float(ylo)
        self.nx = max(2, int(round((xhi - xlo) / self.resolution)) + 1)
        self.ny = max(2, int(round((yhi - ylo) / self.resolution)) + 1)
        self.zlo = float(zlo)
        self.ztop = float(zhi)
        self._gx = self.x0 + np.arange(self.nx) * self.resolution   # 칸 중심 좌표(float64)
        self._gy = self.y0 + np.arange(self.ny) * self.resolution
        self.heights = np.full((self.ny, self.nx), self.ztop, dtype=np.float32)
        # 그 칸을 마지막으로 깎은 공구의 색 id(공구 툴패스와 같은 색 매김,
        # v1.9.1) — -1이면 아직 안 깎인 원래 소재 표면.
        self.color_ids = np.full((self.ny, self.nx), -1, dtype=np.int16)
        # G00(급속) 이동이 소재를 깎으면 (src_line, seq)를 여기에 남긴다.
        self.rapid_cut_warnings = []

    # -- 좌표 -------------------------------------------------------------
    def grid_x(self):
        return self.x0 + np.arange(self.nx) * self.resolution

    def grid_y(self):
        return self.y0 + np.arange(self.ny) * self.resolution

    def cell_count(self):
        return self.nx * self.ny

    is_voxel = False

    def any_cut(self):
        """소재가 하나라도 깎였는가."""
        return bool(np.any(self.heights < self.ztop - 1e-6))

    def extent(self):
        """소재 XY 범위 ((xmin, xmax), (ymin, ymax))."""
        return ((self.x0, self.x0 + (self.nx - 1) * self.resolution),
                (self.y0, self.y0 + (self.ny - 1) * self.resolution))

    @staticmethod
    def snapshot_bytes(snap):
        return int(snap[0].nbytes + snap[1].nbytes)

    # -- 절삭 ---------------------------------------------------------------
    def cut_batch(self, P0, P1, tools, tool_idx, rapid, color, src_lines=None, seqs=None,
                  cancel=None, progress=None, chunk=SIM_CHUNK_SEGMENTS, use_numba=None):
        """선분 묶음을 순서대로 깎는다.

        P0, P1   : (M, 3) Tool tip 시작/끝 좌표
        tools    : ToolShape(또는 None) 목록 — tool_idx가 이 목록의 위치를 가리킨다
        tool_idx : (M,) 정수. tools[tool_idx[m]]이 None이면 그 선분은 건너뛴다
        rapid    : (M,) bool — G00 여부. 깎았으면 rapid_cut_warnings에 남긴다
        color    : (M,) 정수 — 절삭면 색 id
        cancel() : True를 돌려주면 다음 청크 앞에서 멈춘다
        progress(done, total): 청크마다 호출
        돌려줌: 끝까지 했으면 True, 취소로 멈췄으면 False (그 경우 소재는 일부만
        깎인 상태 — 호출부가 버려야 한다)."""
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        total = P0.shape[0]
        if total == 0:
            return True
        res = self.resolution
        luts = [tool.radial_lut(res) if tool is not None else None for tool in tools]
        tool_idx = np.asarray(tool_idx, dtype=np.int64).copy()
        invalid = np.array([entry is None for entry in luts] + [True], dtype=bool)
        tool_idx[(tool_idx < 0) | invalid[np.minimum(tool_idx, len(luts))]] = -1
        rapid = np.asarray(rapid, dtype=bool)
        color = np.asarray(color, dtype=np.int16)
        radii = np.array([0.0 if tool is None else tool.radius for tool in tools],
                         dtype=np.float64)

        numba_mod = None
        if use_numba is None:
            use_numba = total >= SIM_NUMBA_MIN_SEGMENTS
        if use_numba:
            numba_mod = _load_numba()
        if numba_mod is not None:
            sizes = [0 if entry is None else entry[0].size for entry in luts]
            loff = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int64)
            linv = np.array([0.0 if entry is None else entry[1] for entry in luts],
                            dtype=np.float64)
            parts = [entry[0] for entry in luts if entry is not None]
            lut_flat = np.concatenate(parts) if parts else np.zeros(2, dtype=np.float64)
            tool_idx32 = tool_idx.astype(np.int32)

        for start in range(0, total, chunk):
            if cancel is not None and cancel():
                return False
            end = min(start + chunk, total)
            hit = np.zeros(end - start, dtype=bool)
            if numba_mod is not None:
                numba_mod.cut_chunk(
                    self.heights, self.color_ids, self.x0, self.y0, res, self.zlo, self.ztop,
                    P0[start:end], P1[start:end], tool_idx32[start:end], color[start:end],
                    lut_flat, loff, radii, linv, hit,
                )
            else:
                self._cut_chunk_numpy(P0[start:end], P1[start:end], luts, radii,
                                      tool_idx[start:end], color[start:end], hit)
            for m in np.nonzero(hit & rapid[start:end])[0]:
                g = start + int(m)
                src = None if src_lines is None else src_lines[g]
                seq = None if seqs is None else seqs[g]
                self.rapid_cut_warnings.append((
                    None if src is None else int(src),
                    None if seq is None else int(seq),
                ))
            if progress is not None:
                progress(end, total)
        return True

    def _cut_chunk_numpy(self, P0, P1, luts, radii, tool_idx, color, hit):
        res = self.resolution
        ztop = self.ztop
        zlo32 = np.float32(self.zlo)
        for m in range(P0.shape[0]):
            t = int(tool_idx[m])
            if t < 0:
                continue
            ax, ay, az = P0[m]
            bx, by, bz = P1[m]
            if min(az, bz) >= ztop:
                continue  # 소재 윗면보다 위 — 깎을 것이 없다
            dx, dy, dz = bx - ax, by - ay, bz - az
            if dx * dx + dy * dy < 1e-18:
                n_sub = 1                     # 수직 이동 — 낮은 끝점 한 번이면 된다
            else:
                n_sub = min(max(1, int(np.ceil(abs(dz) / (res * SUB_Z)))), MAX_SUB)
            lut, inv_step = luts[t]
            radius = float(radii[t])
            c = color[m]
            any_low = False
            for k in range(n_sub):
                ta = k / n_sub
                tb = (k + 1) / n_sub
                z = min(az + dz * ta, az + dz * tb)
                if z >= ztop:
                    continue
                if _stamp_numpy(self, ax + dx * ta, ay + dy * ta, ax + dx * tb, ay + dy * tb,
                                z, lut, radius, inv_step, c, zlo32):
                    any_low = True
            hit[m] = any_low

    def cut_point(self, pt, tool, color_id=None):
        """Tool tip이 정지해 있는 한 점(pt=[x,y,z])에서 소재를 깎는다."""
        p = np.asarray(pt, dtype=np.float64).reshape(1, 3)
        self.cut_batch(p, p, [tool], [0], [False], [-1 if color_id is None else color_id],
                       use_numba=False)

    def cut_segment(self, p0, p1, tool, rapid=False, src_line=None, seq=None, color_id=None):
        """Tool tip이 p0에서 p1로 이동하는 동안 소재를 깎는다.

        rapid=True(G00)인데 실제로 깎이는 셀이 있으면 rapid_cut_warnings에
        (src_line, seq)를 남긴다 — 계산 자체는 그대로 반영한다(사용자가
        급속에서 충돌한 것을 그대로 형상으로 확인할 수 있어야 한다)."""
        self.cut_batch(
            np.asarray(p0, dtype=np.float64).reshape(1, 3),
            np.asarray(p1, dtype=np.float64).reshape(1, 3),
            [tool], [0], [rapid], [-1 if color_id is None else color_id],
            src_lines=[src_line], seqs=[seq], use_numba=False,
        )

    # -- 스냅샷 ---------------------------------------------------------------
    def snapshot(self):
        """(heights, color_ids) 사본 튜플. restore()에 그대로 넘긴다."""
        return self.heights.copy(), self.color_ids.copy()

    def snapshot_nbytes(self):
        return self.heights.nbytes + self.color_ids.nbytes

    def restore(self, snap):
        heights, color_ids = snap
        self.heights = np.array(heights, dtype=np.float32, copy=True)
        self.color_ids = np.array(color_ids, dtype=np.int16, copy=True)

    def reset(self):
        self.heights = np.full((self.ny, self.nx), self.ztop, dtype=np.float32)
        self.color_ids = np.full((self.ny, self.nx), -1, dtype=np.int16)
        self.rapid_cut_warnings = []

    def clone(self):
        """같은 격자·현재 상태의 복사본(워커 스레드가 자기 사본으로 계산한다)."""
        other = ZMapStock.__new__(ZMapStock)
        other.__dict__.update(self.__dict__)
        other.heights = self.heights.copy()
        other.color_ids = self.color_ids.copy()
        other.rapid_cut_warnings = list(self.rapid_cut_warnings)
        return other

    # -- 표시용 격자 ----------------------------------------------------------
    def display_grid(self, max_n=SIM_DISPLAY_GRID_MAX):
        """계산 격자를 화면용으로 줄인다. 돌려줌: (xs, ys, Z, C) — 정점 좌표와
        높이(float32, ny_v x nx_v), 색 id(int16).

        블록마다 **최솟값**을 써서 좁은 홈이 사라지지 않게 한다. 정점 높이는
        이웃한 블록들의 최솟값이고, 색 id는 그 최저점 칸의 것이다. 변당 격자가
        max_n 이하면 계산 격자를 그대로 쓴다."""
        bx = max(1, -(-self.nx // max_n))
        by = max(1, -(-self.ny // max_n))
        if bx == 1 and by == 1:
            return self.grid_x(), self.grid_y(), self.heights, self.color_ids
        nbx = -(-self.nx // bx)
        nby = -(-self.ny // by)
        pad_h = np.full((nby * by, nbx * bx), np.inf, dtype=np.float32)
        pad_h[:self.ny, :self.nx] = self.heights
        pad_c = np.full((nby * by, nbx * bx), -1, dtype=np.int16)
        pad_c[:self.ny, :self.nx] = self.color_ids
        blocks_h = pad_h.reshape(nby, by, nbx, bx).transpose(0, 2, 1, 3).reshape(nby, nbx, by * bx)
        blocks_c = pad_c.reshape(nby, by, nbx, bx).transpose(0, 2, 1, 3).reshape(nby, nbx, by * bx)
        arg = blocks_h.argmin(axis=2)[..., None]
        block_z = np.take_along_axis(blocks_h, arg, 2)[..., 0]
        block_c = np.take_along_axis(blocks_c, arg, 2)[..., 0]
        bz = np.pad(block_z, 1, constant_values=np.inf)
        bc = np.pad(block_c, 1, constant_values=-1)
        stack_z = np.stack([bz[:-1, :-1], bz[:-1, 1:], bz[1:, :-1], bz[1:, 1:]])
        stack_c = np.stack([bc[:-1, :-1], bc[:-1, 1:], bc[1:, :-1], bc[1:, 1:]])
        which = stack_z.argmin(axis=0)[None]
        Z = np.take_along_axis(stack_z, which, 0)[0]
        C = np.take_along_axis(stack_c, which, 0)[0]
        xi = np.minimum(np.arange(nbx + 1) * bx, self.nx - 1)
        yi = np.minimum(np.arange(nby + 1) * by, self.ny - 1)
        if xi[-1] == xi[-2]:
            xi, Z, C = xi[:-1], Z[:, :-1], C[:, :-1]
        if yi[-1] == yi[-2]:
            yi, Z, C = yi[:-1], Z[:-1], C[:-1]
        xs = self.x0 + xi * self.resolution
        ys = self.y0 + yi * self.resolution
        return xs, ys, np.ascontiguousarray(Z), np.ascontiguousarray(C)

    # -- 색 ---------------------------------------------------------------
    def vertex_colors(self, C, Z, color_map=None, mode='tool', default_color=DEFAULT_STOCK_COLOR):
        """정점 격자 (C 색 id, Z 높이) -> RGBA(ny, nx, 4) float32.

        mode: 'tool'(공구 색 — color_map {id: rgba}, 미절삭은 기본색) /
        'depth'(깎인 깊이별) / 'solid'(단색 기본색)."""
        default_rgba = np.array(default_color, dtype=np.float32)
        if mode == 'solid':
            return np.tile(default_rgba, Z.shape + (1,))
        if mode == 'depth':
            return depth_colors(Z, self.ztop, self.zlo, default_rgba[3])
        if not color_map:
            return np.tile(default_rgba, Z.shape + (1,))
        max_id = max(color_map)
        palette = np.tile(default_rgba, (max_id + 2, 1))  # index 0 = -1(미절삭)
        for cid, rgba in color_map.items():
            if 0 <= cid <= max_id:
                palette[cid + 1] = np.asarray(rgba, dtype=np.float32)
        return palette[np.clip(C, -1, max_id).astype(np.int64) + 1]

    # -- 메쉬 ---------------------------------------------------------------
    def to_mesh(self, color_map=None, default_color=DEFAULT_STOCK_COLOR, mode='tool'):
        """계산 격자 **전체 해상도**의 닫힌 삼각형 메쉬(STL 내보내기용).
        돌려줌: (verts Nx3 float32, faces Mx3 int32, colors Nx4 float32).
        정점을 공유하는 인덱스 메쉬이고 바깥 방향이 법선이다."""
        rgba = self.vertex_colors(self.color_ids, self.heights, color_map, mode, default_color)
        verts, faces, colors = mesh_from_grid(
            self.grid_x(), self.grid_y(), self.heights, rgba, self.zlo, default_color)
        return verts, faces, colors

    def display_mesh(self, max_n=SIM_DISPLAY_GRID_MAX, color_map=None, mode='tool',
                     default_color=DEFAULT_STOCK_COLOR, edges=True):
        """화면용 메쉬: 표시 격자로 줄인 (verts, faces, colors, edge_verts).
        edge_verts는 모서리 선(2M x 3, 'lines' 모드) — edges=False면 빈 배열."""
        xs, ys, Z, C = self.display_grid(max_n)
        rgba = self.vertex_colors(C, Z, color_map, mode, default_color)
        verts, faces, colors = mesh_from_grid(xs, ys, Z, rgba, self.zlo, default_color)
        if mode == 'tool' and color_map:
            verts, faces, colors = sharpen_color_edges(verts, faces, colors, default_color)
        if edges:
            spacing = float(np.mean(np.diff(xs))) if len(xs) > 1 else self.resolution
            edge_verts = edge_lines(xs, ys, Z, self.zlo, spacing * SIM_EDGE_SLOPE)
        else:
            edge_verts = np.zeros((0, 3), dtype=np.float32)
        return verts, faces, colors, edge_verts


# --------------------------------------------------------------------------
# 격자 → 메쉬 (Qt 없음)
# --------------------------------------------------------------------------

_TOPOLOGY_CACHE = {}


def depth_colors(Z, ztop, zlo, alpha=1.0):
    """깎인 깊이(ztop - z)를 밝은 3단 색(노랑 → 연두 → 하늘)으로 바꾼다."""
    span = max(float(ztop) - float(zlo), 1e-9)
    t = np.clip((float(ztop) - np.asarray(Z, dtype=np.float64)) / span, 0.0, 1.0)
    stops = np.array(DEPTH_COLOR_STOPS, dtype=np.float64)
    pos = t * (len(stops) - 1)
    lo = np.minimum(pos.astype(np.int64), len(stops) - 2)
    frac = (pos - lo)[..., None]
    rgb = stops[lo] * (1.0 - frac) + stops[lo + 1] * frac
    out = np.empty(Z.shape + (4,), dtype=np.float32)
    out[..., :3] = rgb
    out[..., 3] = alpha
    return out


def _perimeter_indices(nvy, nvx):
    """격자 테두리 정점 번호(위에서 봐서 반시계, 시작 (0,0), 반복 없음)."""
    idx = np.arange(nvy * nvx).reshape(nvy, nvx)
    return np.concatenate([
        idx[0, :],                # 앞(y 최소) 왼→오
        idx[1:, -1],              # 오른쪽 아래→위
        idx[-1, -2::-1],          # 뒤 오→왼
        idx[-2:0:-1, 0],          # 왼쪽 위→아래
    ])


def _topology(nvy, nvx):
    """(nvy, nvx) 격자의 면 인덱스와 테두리. 격자 크기가 같으면 재사용한다
    (면 인덱스는 격자 크기가 바뀔 때만 만든다 — 외부 플랜 §3)."""
    key = (nvy, nvx)
    cached = _TOPOLOGY_CACHE.get(key)
    if cached is not None:
        return cached
    idx = np.arange(nvy * nvx, dtype=np.int32).reshape(nvy, nvx)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]
    top = np.concatenate([
        np.stack([a, b, c], axis=-1).reshape(-1, 3),
        np.stack([a, c, d], axis=-1).reshape(-1, 3),
    ])
    perim = _perimeter_indices(nvy, nvx).astype(np.int32)
    p = perim.size
    nt = nvy * nvx
    k = np.arange(p, dtype=np.int32)
    t0, t1 = perim, np.roll(perim, -1)
    b0 = nt + k
    b1 = nt + (k + 1) % p
    center = np.full(p, nt + p, dtype=np.int32)
    walls = np.concatenate([
        np.stack([t0, b0, b1], axis=-1),
        np.stack([t0, b1, t1], axis=-1),
        np.stack([center, b1, b0], axis=-1),   # 바닥면(아래를 향하도록 순서 반대)
    ])
    faces = np.concatenate([top, walls]).astype(np.int32)
    if len(_TOPOLOGY_CACHE) >= 6:
        _TOPOLOGY_CACHE.pop(next(iter(_TOPOLOGY_CACHE)))
    _TOPOLOGY_CACHE[key] = (faces, perim)
    return faces, perim


def mesh_from_grid(xs, ys, Z, rgba, zlo, default_color=DEFAULT_STOCK_COLOR):
    """정점 격자(xs, ys, Z) -> 닫힌 인덱스 메쉬 (verts, faces, colors).

    윗면 격자 + 옆벽(테두리 정점을 zlo까지 내린 띠) + 바닥(가운데 한 점에서
    부채꼴). 옆벽은 윗면 테두리 정점을 그대로 공유하므로 색도 테두리 색을
    따른다. 모든 삼각형의 법선이 바깥쪽을 향한다."""
    nvy, nvx = Z.shape
    faces, perim = _topology(nvy, nvx)
    nt = nvy * nvx
    gx, gy = np.meshgrid(np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32))
    verts = np.empty((nt + perim.size + 1, 3), dtype=np.float32)
    verts[:nt, 0] = gx.ravel()
    verts[:nt, 1] = gy.ravel()
    verts[:nt, 2] = np.asarray(Z, dtype=np.float32).ravel()
    verts[nt:nt + perim.size] = verts[perim]
    verts[nt:nt + perim.size, 2] = zlo
    verts[nt + perim.size] = ((xs[0] + xs[-1]) / 2.0, (ys[0] + ys[-1]) / 2.0, zlo)
    flat = np.asarray(rgba, dtype=np.float32).reshape(-1, 4)
    colors = np.empty((verts.shape[0], 4), dtype=np.float32)
    colors[:nt] = flat
    colors[nt:nt + perim.size] = flat[perim]
    colors[nt + perim.size] = np.asarray(default_color, dtype=np.float32)
    return verts, faces, colors


def _color_keys(colors):
    """정점 색(RGB) -> 같은 색이면 같은 uint64 키. 삼각형 안에서 색이 다른지 빠르게 본다."""
    bits = np.ascontiguousarray(colors[:, :3], dtype=np.float32).view(np.uint32).astype(np.uint64)
    mul = np.uint64(1000003)
    with np.errstate(over='ignore'):
        return (bits[:, 0] * mul + bits[:, 1]) * mul + bits[:, 2]


def sharpen_color_edges(verts, faces, colors, default_color=DEFAULT_STOCK_COLOR):
    """공정 색 경계를 선명하게 — 삼각형 안에서 색이 섞이는(그라데이션) 면만 정점을 복제해
    면 하나를 한 가지 색으로 칠한다(v2.0.2). 나머지 면은 정점을 그대로 공유하므로 정점은
    (섞이는 면 수 x 3)개만 늘어난다.

    색 결정: 세 정점 중 같은 색이 둘 이상이면 그 색(다수결), 셋이 모두 다르면 기본색이
    아닌 첫 정점의 색. 그래서 깎인 정점이 하나뿐인 면은 기본색, 둘 이상인 면은 공정 색이 된다.
    돌려줌: (verts, faces, colors) — 섞이는 면이 없으면 입력을 그대로 돌려준다."""
    if faces.shape[0] == 0:
        return verts, faces, colors
    keys = _color_keys(colors)
    k0, k1, k2 = keys[faces[:, 0]], keys[faces[:, 1]], keys[faces[:, 2]]
    mixed = np.nonzero(~((k0 == k1) & (k1 == k2)))[0]
    if mixed.size == 0:
        return verts, faces, colors
    f = faces[mixed]
    m0, m1, m2 = k0[mixed], k1[mixed], k2[mixed]
    default_key = _color_keys(np.asarray(default_color, dtype=np.float32).reshape(1, 4))[0]
    pick = np.zeros(mixed.size, dtype=np.int64)            # 면 색을 가져올 정점 위치(0~2)
    major = (m0 == m1) | (m0 == m2)
    pick[~major & (m1 == m2)] = 1
    none = ~major & (m1 != m2)                              # 셋이 모두 다름
    first_cut = np.where(m0 != default_key, 0, np.where(m1 != default_key, 1, 2))
    pick[none] = first_cut[none]
    face_color = colors[f[np.arange(mixed.size), pick]]
    base = verts.shape[0]
    count = mixed.size
    new_verts = verts[f.reshape(-1)]
    new_colors = np.repeat(face_color, 3, axis=0)
    new_faces = faces.copy()
    new_faces[mixed] = (base + np.arange(count * 3, dtype=np.int64)).reshape(count, 3).astype(faces.dtype)
    return (np.concatenate([verts, new_verts]), new_faces,
            np.concatenate([colors, new_colors]).astype(np.float32))


def edge_lines(xs, ys, Z, zlo, thr, limit=SIM_EDGE_SEGMENT_LIMIT):
    """모서리 선 — (2M, 3) float32('lines' 모드로 그린다).

    ① 소재 블록 외곽(윗면 테두리는 실제 높이를 따라가고, 바닥 사각형, 네 귀퉁이 세로선)
    ② 절삭으로 생긴 단차: 기울기가 thr(≈45°) 넘게 꺾이는 곳의 윗 테두리와
       아랫 테두리 선. limit을 넘으면 균등하게 솎는다."""
    nvy, nvx = Z.shape
    xs = np.asarray(xs, dtype=np.float32)
    ys = np.asarray(ys, dtype=np.float32)
    Z = np.asarray(Z, dtype=np.float32)
    pieces = []

    perim = _perimeter_indices(nvy, nvx)
    py, px = np.divmod(perim, nvx)
    loop = np.stack([xs[px], ys[py], Z[py, px]], axis=-1)
    nxt = np.roll(loop, -1, axis=0)
    pieces.append(np.stack([loop, nxt], axis=1).reshape(-1, 3))

    x_lo, x_hi, y_lo, y_hi = xs[0], xs[-1], ys[0], ys[-1]
    corners = np.array([[x_lo, y_lo], [x_hi, y_lo], [x_hi, y_hi], [x_lo, y_hi]], dtype=np.float32)
    bottom = np.column_stack([corners, np.full(4, zlo, dtype=np.float32)])
    pieces.append(np.stack([bottom, np.roll(bottom, -1, axis=0)], axis=1).reshape(-1, 3))
    corner_top_z = np.array([Z[0, 0], Z[0, -1], Z[-1, -1], Z[-1, 0]], dtype=np.float32)
    top = np.column_stack([corners, corner_top_z])
    pieces.append(np.stack([bottom, top], axis=1).reshape(-1, 3))

    # 모서리 = 기울기가 크게 꺾이는 곳(윗 테두리·아랫 테두리). 정점의 2차 차분
    # |Z[i-1] - 2Z[i] + Z[i+1]|이 thr(≈45° 꺾임)를 넘는 곳이다 — 가파른 벽 한
    # 겹에는 위/아래 두 줄만 남고, 곡면 벽이 빗살무늬로 도배되지 않는다.
    crease_x = np.zeros(Z.shape, dtype=bool)         # x 방향으로 꺾이는 정점
    crease_y = np.zeros(Z.shape, dtype=bool)
    if nvx > 2:
        crease_x[:, 1:-1] = np.abs(Z[:, 2:] - 2.0 * Z[:, 1:-1] + Z[:, :-2]) > thr
    if nvy > 2:
        crease_y[1:-1, :] = np.abs(Z[2:, :] - 2.0 * Z[1:-1, :] + Z[:-2, :]) > thr
    seg_a = []
    seg_b = []
    if crease_x.any():
        iy, ix = np.nonzero(crease_x[:-1] & crease_x[1:])     # 열을 따라 y 방향 선
        seg_a.append((iy, ix))
        seg_b.append((iy + 1, ix))
    if crease_y.any():
        iy, ix = np.nonzero(crease_y[:, :-1] & crease_y[:, 1:])   # 행을 따라 x 방향 선
        seg_a.append((iy, ix))
        seg_b.append((iy, ix + 1))
    if seg_a:
        ay = np.concatenate([s[0] for s in seg_a])
        ax = np.concatenate([s[1] for s in seg_a])
        by = np.concatenate([s[0] for s in seg_b])
        bx = np.concatenate([s[1] for s in seg_b])
        if ay.size > limit:
            keep = np.linspace(0, ay.size - 1, limit).astype(np.int64)
            ay, ax, by, bx = ay[keep], ax[keep], by[keep], bx[keep]
        a_pts = np.stack([xs[ax], ys[ay], Z[ay, ax]], axis=-1)
        b_pts = np.stack([xs[bx], ys[by], Z[by, bx]], axis=-1)
        pieces.append(np.stack([a_pts, b_pts], axis=1).reshape(-1, 3))
    return np.ascontiguousarray(np.concatenate(pieces), dtype=np.float32)


# --------------------------------------------------------------------------
# STL 내보내기
# --------------------------------------------------------------------------

def write_stl_binary(path, verts, faces):
    """verts(Nx3)/faces(Mx3)를 바이너리 STL로 쓴다. 외부 라이브러리 없음."""
    verts = np.asarray(verts, dtype=np.float32)
    faces = np.asarray(faces, dtype=np.int64)
    tri = verts[faces]
    n = tri.shape[0]
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    normals = np.cross(e1, e2)
    lengths = np.linalg.norm(normals, axis=1)
    lengths = np.where(lengths == 0, 1.0, lengths)
    normals = (normals / lengths[:, None]).astype(np.float32)

    record_dtype = np.dtype([
        ('normal', '<f4', (3,)),
        ('v0', '<f4', (3,)),
        ('v1', '<f4', (3,)),
        ('v2', '<f4', (3,)),
        ('attr', '<u2'),
    ])
    records = np.zeros(n, dtype=record_dtype)
    records['normal'] = normals
    records['v0'] = tri[:, 0]
    records['v1'] = tri[:, 1]
    records['v2'] = tri[:, 2]

    with open(path, 'wb') as f:
        header = (b'NC Tool List v1.9.2 simulation STL' + b' ' * 80)[:80]
        f.write(header)
        f.write(struct.pack('<I', n))
        f.write(records.tobytes())
