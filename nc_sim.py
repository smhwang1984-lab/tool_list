"""nc_sim.py — 밀링 3축 형상 가공 시뮬레이션 엔진 (v1.9.0).

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

    def __init__(self, radius, profile_fn, length, type_name=''):
        self.radius = float(radius)
        self.length = float(length)
        self.type_name = type_name
        self._profile_fn = profile_fn

    def height_grid(self, r):
        r = np.asarray(r, dtype=np.float64)
        h = self._profile_fn(r)
        return np.where(r <= self.radius + 1e-9, h, np.nan)

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
    name = (tool_type or '').strip().upper()

    if name in TYPE_BALL:
        return ToolShape(radius, _corner_r_profile(radius, radius), length, name)
    if name in TYPE_DRILL:
        angle = sig if sig else DEFAULT_DRILL_ANGLE_DEG
        half = np.radians(max(angle, 1.0) / 2.0)
        return ToolShape(radius, _cone_profile(half), length, name)
    if name in TYPE_FILLET:
        corner_r = r if r else 0.0
        return ToolShape(radius, _corner_r_profile(radius, corner_r), length, name)
    if name in TYPE_FLAT:
        return ToolShape(radius, _flat_profile(), length, name)
    if pl:
        return ToolShape(radius, _chamfer_profile(radius, pl), length, name)
    return ToolShape(radius, _flat_profile(), length, name)


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
# Z-map 소재(ZMapStock)
# --------------------------------------------------------------------------

class ZMapStock:
    """XY 격자마다 남은 소재 윗면 높이 하나를 들고 있는 Z-map 소재.

    3축 전용(공구 축 = 월드 +Z) — 절삭은 각 격자점 위에서 공구 팁 기준
    높이(profile)를 빼는 것으로 근사한다."""

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
        self.heights = np.full((self.ny, self.nx), self.ztop, dtype=np.float64)
        # G00(급속) 이동이 소재를 깎으면 (src_line, seq)를 여기에 남긴다.
        self.rapid_cut_warnings = []

    # -- 좌표 -------------------------------------------------------------
    def grid_x(self):
        return self.x0 + np.arange(self.nx) * self.resolution

    def grid_y(self):
        return self.y0 + np.arange(self.ny) * self.resolution

    def cell_count(self):
        return self.nx * self.ny

    # -- 절삭 ---------------------------------------------------------------
    def cut_point(self, pt, tool):
        """Tool tip이 정지해 있는 한 점(pt=[x,y,z])에서 소재를 깎는다."""
        cx, cy, cz = float(pt[0]), float(pt[1]), float(pt[2])
        r = tool.radius
        ix0 = int(np.floor((cx - r - self.x0) / self.resolution))
        ix1 = int(np.ceil((cx + r - self.x0) / self.resolution))
        iy0 = int(np.floor((cy - r - self.y0) / self.resolution))
        iy1 = int(np.ceil((cy + r - self.y0) / self.resolution))
        ix0 = max(ix0, 0)
        iy0 = max(iy0, 0)
        ix1 = min(ix1, self.nx - 1)
        iy1 = min(iy1, self.ny - 1)
        if ix0 > ix1 or iy0 > iy1:
            return
        xs = self.x0 + np.arange(ix0, ix1 + 1) * self.resolution
        ys = self.y0 + np.arange(iy0, iy1 + 1) * self.resolution
        gx, gy = np.meshgrid(xs, ys)
        rr = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
        h = tool.height_grid(rr)
        surface_z = cz + h
        sub = self.heights[iy0:iy1 + 1, ix0:ix1 + 1]
        valid = ~np.isnan(surface_z)
        np.minimum(sub, np.where(valid, surface_z, sub), out=sub)
        np.maximum(sub, self.zlo, out=sub)

    def cut_segment(self, p0, p1, tool, rapid=False, src_line=None, seq=None):
        """Tool tip이 p0에서 p1로 이동하는 동안 소재를 깎는다.

        rapid=True(G00)인데 실제로 깎이는 셀이 있으면 rapid_cut_warnings에
        (src_line, seq)를 남긴다 — 계산 자체는 그대로 반영한다(사용자가
        급속에서 충돌한 것을 그대로 형상으로 확인할 수 있어야 한다)."""
        p0 = np.asarray(p0, dtype=np.float64)
        p1 = np.asarray(p1, dtype=np.float64)
        dist_xy = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        dist_z = abs(float(p1[2] - p0[2]))
        span = max(dist_xy, dist_z)
        steps = max(1, int(np.ceil(span / (self.resolution * 0.5))))

        before = None
        if rapid:
            ix0, ix1, iy0, iy1 = self._bbox_indices(p0, p1, tool.radius)
            if ix0 is not None:
                before = self.heights[iy0:iy1 + 1, ix0:ix1 + 1].copy()

        for i in range(steps + 1):
            t = i / steps
            pt = p0 + (p1 - p0) * t
            self.cut_point(pt, tool)

        if rapid and before is not None:
            after = self.heights[iy0:iy1 + 1, ix0:ix1 + 1]
            if np.any(after < before - 1e-9):
                self.rapid_cut_warnings.append((src_line, seq))

    def _bbox_indices(self, p0, p1, radius):
        cx0, cx1 = sorted((p0[0], p1[0]))
        cy0, cy1 = sorted((p0[1], p1[1]))
        ix0 = int(np.floor((cx0 - radius - self.x0) / self.resolution))
        ix1 = int(np.ceil((cx1 + radius - self.x0) / self.resolution))
        iy0 = int(np.floor((cy0 - radius - self.y0) / self.resolution))
        iy1 = int(np.ceil((cy1 + radius - self.y0) / self.resolution))
        ix0 = max(ix0, 0)
        iy0 = max(iy0, 0)
        ix1 = min(ix1, self.nx - 1)
        iy1 = min(iy1, self.ny - 1)
        if ix0 > ix1 or iy0 > iy1:
            return None, None, None, None
        return ix0, ix1, iy0, iy1

    # -- 스냅샷 ---------------------------------------------------------------
    def snapshot(self):
        return self.heights.copy()

    def restore(self, snap):
        self.heights = np.array(snap, dtype=np.float64, copy=True)

    def reset(self):
        self.heights = np.full((self.ny, self.nx), self.ztop, dtype=np.float64)
        self.rapid_cut_warnings = []

    # -- 메쉬 ---------------------------------------------------------------
    def to_mesh(self):
        """돌려줌: (verts Nx3 float32, faces Mx3 int32).

        정점을 공유하지 않는 '삼각형 더미(soup)' 방식이라 인덱스 계산이
        단순하다 — GLMeshItem과 STL 내보내기 양쪽에 그대로 쓸 수 있다."""
        gx, gy = np.meshgrid(self.grid_x(), self.grid_y())
        z = self.heights
        tris = []

        def add_quad(pa, pb, pc, pd):
            """pa-pb-pc-pd 순서로 둘러싼 사각형(각 (...,3) 배열)을 두 삼각형으로."""
            tris.append(np.stack([pa, pb, pc], axis=-2).reshape(-1, 3, 3))
            tris.append(np.stack([pa, pc, pd], axis=-2).reshape(-1, 3, 3))

        top_a = np.stack([gx[:-1, :-1], gy[:-1, :-1], z[:-1, :-1]], axis=-1)
        top_b = np.stack([gx[:-1, 1:], gy[:-1, 1:], z[:-1, 1:]], axis=-1)
        top_c = np.stack([gx[1:, 1:], gy[1:, 1:], z[1:, 1:]], axis=-1)
        top_d = np.stack([gx[1:, :-1], gy[1:, :-1], z[1:, :-1]], axis=-1)
        add_quad(top_a, top_b, top_c, top_d)

        zlo = self.zlo

        def wall(edge_top):
            bottom = edge_top.copy()
            bottom[..., 2] = zlo
            a = edge_top[:-1]
            b = edge_top[1:]
            c = bottom[1:]
            d = bottom[:-1]
            add_quad(a, b, c, d)

        wall(np.stack([gx[0, :], gy[0, :], z[0, :]], axis=-1))
        wall(np.stack([gx[-1, ::-1], gy[-1, ::-1], z[-1, ::-1]], axis=-1))
        wall(np.stack([gx[::-1, 0], gy[::-1, 0], z[::-1, 0]], axis=-1))
        wall(np.stack([gx[:, -1], gy[:, -1], z[:, -1]], axis=-1))

        corners_top = np.array([
            [gx[0, 0], gy[0, 0], z[0, 0]],
            [gx[0, -1], gy[0, -1], z[0, -1]],
            [gx[-1, -1], gy[-1, -1], z[-1, -1]],
            [gx[-1, 0], gy[-1, 0], z[-1, 0]],
        ])
        corners_bottom = corners_top.copy()
        corners_bottom[:, 2] = zlo
        b0, b1, b2, b3 = corners_bottom
        tris.append(np.array([[b0, b2, b1], [b0, b3, b2]]))

        triangles = np.concatenate([t.reshape(-1, 3, 3) for t in tris], axis=0)
        verts = triangles.reshape(-1, 3).astype(np.float32)
        faces = np.arange(verts.shape[0], dtype=np.int64).reshape(-1, 3)
        return verts, faces


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
        header = (b'NC Tool List v1.9.0 simulation STL' + b' ' * 80)[:80]
        f.write(header)
        f.write(struct.pack('<I', n))
        f.write(records.tobytes())
