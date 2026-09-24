"""nc_sim3d.py — 3D 소재(복셀) 형상 가공 시뮬레이션 엔진 (v1.10.0).

Z-map(nc_sim.ZMapStock)은 공구 축이 항상 +Z라서 G68.2(3+2 경사면)나 G43.4(공구
중심점 제어, 동시 5축)처럼 공구가 기우는 가공을 표현할 수 없다. 이 모듈은 소재를
3D 점유 격자(복셀)로 들고, 이동마다 그 시점의 **공구 축 방향**으로 공구 회전체를
빼서 어느 방향에서 진입한 가공이든 깎는다. Qt에 의존하지 않는 순수 numpy 모듈이며,
nc_sim_numba가 있으면 절삭 커널을 가속한다(결과는 같다).

절삭 판정(복셀 중심 p, 이동 조각 A→B, 공구 축 a, 반경 R, 날장 길이 L, 공구 형상 h(d)):
  s = (p-A)·a          축 방향 높이(공구 끝에서 위로)
  d = 축에 수직한 평면에서 p와 이동 선분 사이의 거리
  h(d) <= s <= L 이고 d <= R 인 u(이동 비율)가 있으면 그 복셀을 뺀다.
후보 u는 {반경상 가장 가까운 점, 축 방향 범위 양끝, 반경 경계 양끝}이다. 축 방향과
수직 방향 이동이 함께 큰 선분은 조각으로 나눠 오차를 격자 간격/4 이하로 둔다.
"""

from __future__ import annotations

import zlib

import numpy as np

import nc_sim
from nc_sim import (DEFAULT_STOCK_COLOR, DEPTH_COLOR_STOPS, EDGE_COLOR,  # noqa: F401
                    SIM_CHUNK_SEGMENTS, SIM_EDGE_SEGMENT_LIMIT, _load_numba, depth_colors)

# --------------------------------------------------------------------------
# 성능 상수 (튜닝은 여기서만)
# --------------------------------------------------------------------------

SIM3D_TARGET_VOXELS = 20_000_000     # 자동 해상도가 노리는 전체 복셀 수
SIM3D_MAX_VOXELS = 60_000_000        # 수동 해상도여도 넘지 않는다(점유+색 = 복셀당 2바이트)
SIM3D_MIN_RES = 0.1
SIM3D_MAX_RES = 2.0
SIM3D_ANGLE_STEP_DEG = 2.0           # 동시 5축: 한 조각 안에서 공구 축이 돌 수 있는 최대 각도
SIM3D_SUB_AXIAL = 0.25               # 축·수직 이동이 함께 클 때 조각당 (작은 쪽) 이동 = 격자 x 이 값
SIM3D_MAX_SUB = 400
SIM3D_NUMBA_MIN_SEGMENTS = 16
SIM3D_DISPLAY_QUADS_MAX = 700_000    # 화면 메쉬 사각형 상한 — 넘으면 표시 격자를 거칠게
SIM3D_CREASE_DEG = 40.0              # 이웃 면의 법선이 이 각도 넘게 꺾이면 "모서리"
UNCUT_COLOR = 255                    # 색 평면: 한 번도 안 깎인 곳


def auto_resolution_3d(bounds, target_voxels=SIM3D_TARGET_VOXELS):
    """소재 전체 복셀이 대략 target_voxels가 되는 해상도(mm)."""
    lengths = [max(bounds[a][1] - bounds[a][0], 1e-6) for a in 'XYZ']
    volume = lengths[0] * lengths[1] * lengths[2]
    res = (volume / max(target_voxels, 1)) ** (1.0 / 3.0)
    res = min(max(res, SIM3D_MIN_RES), SIM3D_MAX_RES)
    return round(res, 3)


def clamp_resolution_3d(bounds, resolution):
    """수동 해상도가 너무 촘촘해 복셀이 SIM3D_MAX_VOXELS를 넘으면 거칠게 조정한다."""
    lengths = [max(bounds[a][1] - bounds[a][0], 1e-6) for a in 'XYZ']
    res = float(resolution)
    while (lengths[0] / res) * (lengths[1] / res) * (lengths[2] / res) > SIM3D_MAX_VOXELS:
        res *= 1.05
    return round(res, 3)


def normalize_axes(axes):
    axes = np.asarray(axes, dtype=np.float64).reshape(-1, 3)
    norm = np.linalg.norm(axes, axis=1)
    norm = np.where(norm < 1e-12, 1.0, norm)
    return axes / norm[:, None]


# --------------------------------------------------------------------------
# 절삭 조각 계산 (numba 커널과 같은 산식)
# --------------------------------------------------------------------------

def _piece_count(d, a0, a1, res_min):
    """선분 하나를 몇 조각으로 나눌지 — nc_sim_numba.piece_count와 같은 식."""
    n_ang = 1
    cosang = float(np.clip(np.dot(a0, a1), -1.0, 1.0))
    ang = np.degrees(np.arccos(cosang))
    if ang > 1e-9:
        n_ang = int(np.ceil(ang / SIM3D_ANGLE_STEP_DEG))
    am = a0 + a1
    nm = float(np.linalg.norm(am))
    am = am / nm if nm > 1e-12 else a0
    dpar = float(np.dot(d, am))
    dperp = float(np.linalg.norm(d - dpar * am))
    n_ax = int(np.ceil(min(abs(dpar), dperp) / (SIM3D_SUB_AXIAL * res_min)))
    return min(max(1, n_ang, n_ax), SIM3D_MAX_SUB)


def _stamp3d_numpy(stock, ax, ay, az, bx, by, bz, u, lut, radius, inv_step, length, color):
    """이동 조각(A→B, 공구 축 u 고정)으로 소재를 깎는다. 깎은 복셀 수를 돌려준다."""
    nx, ny, nz = stock.occ.shape
    rx, ry, rz = stock.step
    ext = radius + 1e-9
    tx, ty, tz = length * u[0], length * u[1], length * u[2]
    lo_x = min(min(ax, bx), min(ax + tx, bx + tx)) - ext
    hi_x = max(max(ax, bx), max(ax + tx, bx + tx)) + ext
    lo_y = min(min(ay, by), min(ay + ty, by + ty)) - ext
    hi_y = max(max(ay, by), max(ay + ty, by + ty)) + ext
    lo_z = min(min(az, bz), min(az + tz, bz + tz)) - ext
    hi_z = max(max(az, bz), max(az + tz, bz + tz)) + ext
    i0 = max(int(np.floor((lo_x - stock.x0) / rx)), 0)
    i1 = min(int(np.ceil((hi_x - stock.x0) / rx)), nx - 1)
    j0 = max(int(np.floor((lo_y - stock.y0) / ry)), 0)
    j1 = min(int(np.ceil((hi_y - stock.y0) / ry)), ny - 1)
    k0 = max(int(np.floor((lo_z - stock.z0) / rz)), 0)
    k1 = min(int(np.ceil((hi_z - stock.z0) / rz)), nz - 1)
    if i0 > i1 or j0 > j1 or k0 > k1:
        return 0
    sub = stock.occ[i0:i1 + 1, j0:j1 + 1, k0:k1 + 1]
    ii, jj, kk = np.nonzero(sub)
    if ii.size == 0:
        return 0
    ux, uy, uz = float(u[0]), float(u[1]), float(u[2])
    wx = stock.x0 + (ii + i0 + 0.5) * rx - ax
    wy = stock.y0 + (jj + j0 + 0.5) * ry - ay
    wz = stock.z0 + (kk + k0 + 0.5) * rz - az
    dx, dy, dz = bx - ax, by - ay, bz - az
    dpar = dx * ux + dy * uy + dz * uz
    dpx, dpy, dpz = dx - dpar * ux, dy - dpar * uy, dz - dpar * uz
    dp2 = dpx * dpx + dpy * dpy + dpz * dpz
    r2 = radius * radius + 1e-9
    s0 = wx * ux + wy * uy + wz * uz
    wpx, wpy, wpz = wx - s0 * ux, wy - s0 * uy, wz - s0 * uz
    wp2 = wpx * wpx + wpy * wpy + wpz * wpz
    dot = wpx * dpx + wpy * dpy + wpz * dpz
    if dp2 > 0.0:
        t = np.clip(dot / dp2, 0.0, 1.0)
    else:
        t = np.zeros_like(wp2)
    dd2 = wp2 - 2.0 * t * dot + t * t * dp2
    near = dd2 <= r2
    if not near.any():
        return 0
    sel = np.nonzero(near)[0]
    s0, wp2, dot, t = s0[sel], wp2[sel], dot[sel], t[sel]

    def feasible(uu):
        dd2u = np.maximum(wp2 - 2.0 * uu * dot + uu * uu * dp2, 0.0)
        s = s0 - uu * dpar
        pos = np.sqrt(dd2u) * inv_step
        kidx = np.minimum(pos.astype(np.int64), lut.size - 2)
        frac = pos - kidx
        h = lut[kidx] * (1.0 - frac) + lut[kidx + 1] * frac
        return (dd2u <= r2) & (s <= length) & (s >= h)

    ok = feasible(t)
    todo = ~ok
    if todo.any():
        cand = []
        if abs(dpar) > 1e-12:
            cand.append(np.clip((s0 - length) / dpar, 0.0, 1.0))
            cand.append(np.clip(s0 / dpar, 0.0, 1.0))
        if dp2 > 0.0:
            disc = dot * dot - dp2 * (wp2 - r2)
            sq = np.sqrt(np.maximum(disc, 0.0))
            cand.append(np.clip((dot - sq) / dp2, 0.0, 1.0))
            cand.append(np.clip((dot + sq) / dp2, 0.0, 1.0))
        for uu in cand:
            idx = np.nonzero(todo)[0]
            if idx.size == 0:
                break
            hit = np.zeros_like(ok)
            dd2u = np.maximum(wp2[idx] - 2.0 * uu[idx] * dot[idx] + uu[idx] * uu[idx] * dp2, 0.0)
            s = s0[idx] - uu[idx] * dpar
            pos = np.sqrt(dd2u) * inv_step
            kidx = np.minimum(pos.astype(np.int64), lut.size - 2)
            frac = pos - kidx
            h = lut[kidx] * (1.0 - frac) + lut[kidx + 1] * frac
            good = (dd2u <= r2) & (s <= length) & (s >= h)
            hit[idx[good]] = True
            ok |= hit
            todo &= ~hit
    if not ok.any():
        return 0
    rem = sel[ok]
    stock.occ[ii[rem] + i0, jj[rem] + j0, kk[rem] + k0] = 0
    stock.col[ii[rem] + i0, jj[rem] + j0, kk[rem] + k0] = color
    return int(rem.size)


# --------------------------------------------------------------------------
# 3D 소재(VoxelStock)
# --------------------------------------------------------------------------

class VoxelStock:
    """소재를 격자 점유(1 = 소재)로 들고 있는 3D 소재. 복셀 (i, j, k)의 중심은
    (x0 + (i+.5)*rx, y0 + (j+.5)*ry, z0 + (k+.5)*rz) — 격자 간격은 축마다
    (소재 길이 / 복셀 수)라서 소재 범위에 정확히 맞는다."""

    is_voxel = True

    def __init__(self, bounds, resolution):
        self.resolution = float(resolution)
        xlo, xhi = bounds['X']
        ylo, yhi = bounds['Y']
        zlo, zhi = bounds['Z']
        lengths = (max(xhi - xlo, 1e-6), max(yhi - ylo, 1e-6), max(zhi - zlo, 1e-6))
        self.nx, self.ny, self.nz = (max(2, int(round(length / self.resolution)))
                                     for length in lengths)
        self.step = (lengths[0] / self.nx, lengths[1] / self.ny, lengths[2] / self.nz)
        self.x0, self.y0, self.z0 = float(xlo), float(ylo), float(zlo)
        self.zlo, self.ztop = float(zlo), float(zhi)
        self.occ = np.ones((self.nx, self.ny, self.nz), dtype=np.uint8)
        self.col = np.full((self.nx, self.ny, self.nz), UNCUT_COLOR, dtype=np.uint8)
        self.rapid_cut_warnings = []
        self._version = 0
        self._mesh_cache = None

    # -- 정보 -------------------------------------------------------------
    def cell_count(self):
        return self.nx * self.ny * self.nz

    def any_cut(self):
        return not bool(self.occ.all())

    def extent(self):
        return ((self.x0, self.x0 + self.nx * self.step[0]),
                (self.y0, self.y0 + self.ny * self.step[1]))

    def removed_fraction(self):
        return 1.0 - float(self.occ.mean())

    # -- 절삭 ---------------------------------------------------------------
    def cut_batch(self, P0, P1, tools, tool_idx, rapid, color, src_lines=None, seqs=None,
                  cancel=None, progress=None, chunk=SIM_CHUNK_SEGMENTS, use_numba=None,
                  axes0=None, axes1=None):
        """선분 묶음을 순서대로 깎는다(ZMapStock.cut_batch와 같은 규약 + 공구 축).

        axes0/axes1 : (M, 3) 선분 시작/끝에서의 공구 축(단위벡터). None이면 +Z.
        돌려줌: 끝까지 했으면 True, 취소로 멈췄으면 False."""
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        total = P0.shape[0]
        if total == 0:
            return True
        default_axes = np.tile([0.0, 0.0, 1.0], (total, 1))
        axes0 = default_axes if axes0 is None else normalize_axes(axes0)
        axes1 = axes0 if axes1 is None else normalize_axes(axes1)
        axes0 = np.ascontiguousarray(axes0)
        axes1 = np.ascontiguousarray(axes1)
        res_min = min(self.step)
        luts = [tool.radial_lut(res_min) if tool is not None else None for tool in tools]
        tool_idx = np.asarray(tool_idx, dtype=np.int64).copy()
        invalid = np.array([entry is None for entry in luts] + [True], dtype=bool)
        tool_idx[(tool_idx < 0) | invalid[np.minimum(tool_idx, len(luts))]] = -1
        rapid = np.asarray(rapid, dtype=bool)
        color = np.clip(np.asarray(color, dtype=np.int64), 0, UNCUT_COLOR - 1).astype(np.uint8)
        radii = np.array([0.0 if t is None else t.radius for t in tools], dtype=np.float64)
        lengths = np.array([0.0 if t is None else t.cut_length for t in tools], dtype=np.float64)

        numba_mod = None
        if use_numba is None:
            use_numba = total >= SIM3D_NUMBA_MIN_SEGMENTS
        if use_numba:
            numba_mod = _load_numba()
            if numba_mod is not None and not hasattr(numba_mod, 'cut_chunk3d'):
                numba_mod = None
        if numba_mod is not None:
            sizes = [0 if entry is None else entry[0].size for entry in luts]
            loff = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int64)
            linv = np.array([0.0 if entry is None else entry[1] for entry in luts],
                            dtype=np.float64)
            parts = [entry[0] for entry in luts if entry is not None]
            lut_flat = np.concatenate(parts) if parts else np.zeros(2, dtype=np.float64)
            tool_idx32 = tool_idx.astype(np.int32)

        rx, ry, rz = self.step
        for start in range(0, total, chunk):
            if cancel is not None and cancel():
                return False
            end = min(start + chunk, total)
            hit = np.zeros(end - start, dtype=bool)
            self._version += 1
            if numba_mod is not None:
                numba_mod.cut_chunk3d(
                    self.occ, self.col, self.x0, self.y0, self.z0, rx, ry, rz,
                    P0[start:end], P1[start:end], axes0[start:end], axes1[start:end],
                    tool_idx32[start:end], color[start:end],
                    lut_flat, loff, radii, linv, lengths, hit, res_min,
                )
            else:
                self._cut_chunk_numpy(P0[start:end], P1[start:end], axes0[start:end],
                                      axes1[start:end], luts, radii, lengths,
                                      tool_idx[start:end], color[start:end], hit, res_min)
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

    def _cut_chunk_numpy(self, P0, P1, A0, A1, luts, radii, lengths, tool_idx, color, hit,
                         res_min):
        # 소재 AABB 밖 선분은 건너뛴다(공구 반경·날장 길이만큼 여유)
        x1 = self.x0 + self.nx * self.step[0]
        y1 = self.y0 + self.ny * self.step[1]
        z1 = self.z0 + self.nz * self.step[2]
        for m in range(P0.shape[0]):
            t = int(tool_idx[m])
            if t < 0:
                continue
            a, b = P0[m], P1[m]
            reach = radii[t] + lengths[t]
            if (max(a[0], b[0]) + reach < self.x0 or min(a[0], b[0]) - reach > x1
                    or max(a[1], b[1]) + reach < self.y0 or min(a[1], b[1]) - reach > y1
                    or max(a[2], b[2]) + reach < self.z0 or min(a[2], b[2]) - reach > z1):
                continue
            d = b - a
            n_sub = _piece_count(d, A0[m], A1[m], res_min)
            lut, inv_step = luts[t]
            radius = float(radii[t])
            length = float(lengths[t])
            c = color[m]
            removed = 0
            for k in range(n_sub):
                ta = k / n_sub
                tb = (k + 1) / n_sub
                mid = (k + 0.5) / n_sub
                u = A0[m] + (A1[m] - A0[m]) * mid
                nu = float(np.linalg.norm(u))
                u = u / nu if nu > 1e-12 else A0[m]
                removed += _stamp3d_numpy(
                    self, a[0] + d[0] * ta, a[1] + d[1] * ta, a[2] + d[2] * ta,
                    a[0] + d[0] * tb, a[1] + d[1] * tb, a[2] + d[2] * tb,
                    u, lut, radius, inv_step, length, c)
            hit[m] = removed > 0

    def cut_segment(self, p0, p1, tool, rapid=False, src_line=None, seq=None, color_id=None,
                    axis0=(0.0, 0.0, 1.0), axis1=None):
        self.cut_batch(
            np.asarray(p0, dtype=np.float64).reshape(1, 3),
            np.asarray(p1, dtype=np.float64).reshape(1, 3),
            [tool], [0], [rapid], [0 if color_id is None else color_id],
            src_lines=[src_line], seqs=[seq], use_numba=False,
            axes0=np.asarray(axis0, dtype=np.float64).reshape(1, 3),
            axes1=None if axis1 is None else np.asarray(axis1, dtype=np.float64).reshape(1, 3),
        )

    def cut_point(self, pt, tool, color_id=None, axis=(0.0, 0.0, 1.0)):
        self.cut_segment(pt, pt, tool, color_id=color_id, axis0=axis)

    # -- 스냅샷(압축) -------------------------------------------------------------
    def snapshot(self):
        """점유·색 평면을 zlib으로 압축해 돌려준다(2,000만 복셀도 수 MB)."""
        return (zlib.compress(self.occ.tobytes(), 1), zlib.compress(self.col.tobytes(), 1))

    @staticmethod
    def snapshot_bytes(snap):
        return len(snap[0]) + len(snap[1])

    def restore(self, snap):
        shape = (self.nx, self.ny, self.nz)
        self.occ = np.frombuffer(zlib.decompress(snap[0]), dtype=np.uint8).reshape(shape).copy()
        self.col = np.frombuffer(zlib.decompress(snap[1]), dtype=np.uint8).reshape(shape).copy()
        self._version += 1

    def reset(self):
        self.occ = np.ones((self.nx, self.ny, self.nz), dtype=np.uint8)
        self.col = np.full((self.nx, self.ny, self.nz), UNCUT_COLOR, dtype=np.uint8)
        self.rapid_cut_warnings = []
        self._version += 1

    def clone(self):
        other = VoxelStock.__new__(VoxelStock)
        other.__dict__.update(self.__dict__)
        other.occ = self.occ.copy()
        other.col = self.col.copy()
        other.rapid_cut_warnings = list(self.rapid_cut_warnings)
        other._mesh_cache = None
        return other

    # -- 표면 메쉬 ---------------------------------------------------------------
    def _color_lookup(self, color_map, mode, default_color, verts, cell_col):
        """정점 색(N x 4). mode: 'tool'(공구 색) / 'depth'(깎인 깊이) / 'solid'(단색)."""
        default_rgba = np.array(default_color, dtype=np.float32)
        count = verts.shape[0]
        if mode == 'solid':
            return np.tile(default_rgba, (count, 1))
        if mode == 'depth':
            return depth_colors(verts[:, 2], self.ztop, self.zlo, default_rgba[3])
        if not color_map:
            return np.tile(default_rgba, (count, 1))
        max_id = max(color_map)
        palette = np.tile(default_rgba, (max(max_id + 1, UNCUT_COLOR + 1), 1))
        for cid, rgba in color_map.items():
            if 0 <= cid < UNCUT_COLOR:
                palette[cid] = np.asarray(rgba, dtype=np.float32)
        return palette[cell_col.astype(np.int64)]

    def _surface(self, factor=1):
        """(verts, faces, cell_col, quads) — 점유 격자(factor배 거칠게)의 표면 넷 메쉬."""
        occ, col, step = self.occ, self.col, self.step
        if factor > 1:
            occ, col = _coarsen(occ, col, factor)
            step = tuple(s * factor for s in step)
        return surface_nets(occ, col, (self.x0, self.y0, self.z0), step)

    def _estimate_quads(self, occ=None):
        occ = self.occ if occ is None else occ
        count = 0
        for axis in range(3):
            a = [slice(None)] * 3
            b = [slice(None)] * 3
            a[axis] = slice(0, -1)
            b[axis] = slice(1, None)
            count += int(np.count_nonzero(occ[tuple(a)] != occ[tuple(b)]))
        # 소재 바깥(경계)과의 면
        for axis in range(3):
            for edge in (0, -1):
                sl = [slice(None)] * 3
                sl[axis] = edge
                count += int(np.count_nonzero(occ[tuple(sl)]))
        return count

    def to_mesh(self, color_map=None, default_color=DEFAULT_STOCK_COLOR, mode='tool'):
        """전체 해상도의 닫힌 삼각형 메쉬(STL 내보내기용): (verts, faces, colors)."""
        verts, faces, cell_col, _quads = self._surface(1)
        colors = self._color_lookup(color_map, mode, default_color, verts, cell_col)
        return verts, faces, colors

    def _box_mesh(self, color_map, mode, default_color, edges):
        """아직 안 깎인 소재 — 큰 격자에서 표면을 뽑지 않고 상자 하나로 즉시 만든다."""
        x1 = self.x0 + self.nx * self.step[0]
        y1 = self.y0 + self.ny * self.step[1]
        z1 = self.z0 + self.nz * self.step[2]
        verts = np.array([[x, y, z] for z in (self.z0, z1) for y in (self.y0, y1)
                          for x in (self.x0, x1)], dtype=np.float32)
        quads = np.array([[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3],
                          [0, 4, 6, 2], [1, 3, 7, 5]], dtype=np.int32)     # 바깥쪽 법선
        faces = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]]).astype(np.int32)
        cell_col = np.full(verts.shape[0], UNCUT_COLOR, dtype=np.uint8)
        colors = self._color_lookup(color_map, mode, default_color, verts, cell_col)
        if edges:
            pairs = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4),
                     (0, 4), (1, 5), (2, 6), (3, 7)]
            edge_verts = np.array([verts[i] for pair in pairs for i in pair], dtype=np.float32)
        else:
            edge_verts = np.zeros((0, 3), dtype=np.float32)
        return verts, faces, colors, edge_verts

    def display_mesh(self, max_n=None, color_map=None, mode='tool',
                     default_color=DEFAULT_STOCK_COLOR, edges=True):
        """화면용 메쉬: (verts, faces, colors, edge_verts). 표면 사각형이 상한을 넘으면
        복셀을 2배씩 합쳐 거칠게 뽑는다. edge_verts는 꺾인 모서리 + 소재 외곽 선."""
        if self.occ.all():
            return self._box_mesh(color_map, mode, default_color, edges)
        key = (self._version, SIM3D_DISPLAY_QUADS_MAX)
        cache = self._mesh_cache
        if cache is None or cache['key'] != key:
            factor = 1
            quads = self._estimate_quads()
            while quads / (factor * factor) > SIM3D_DISPLAY_QUADS_MAX and factor < 16:
                factor *= 2
            verts, faces, cell_col, quad_idx = self._surface(factor)
            cache = {'key': key, 'verts': verts, 'faces': faces, 'cell_col': cell_col,
                     'quads': quad_idx, 'edges': None}
            self._mesh_cache = cache
        verts, faces = cache['verts'], cache['faces']
        colors = self._color_lookup(color_map, mode, default_color, verts, cache['cell_col'])
        if edges:
            if cache['edges'] is None:
                cache['edges'] = crease_edges(verts, cache['quads'], SIM3D_CREASE_DEG)
            edge_verts = cache['edges']
        else:
            edge_verts = np.zeros((0, 3), dtype=np.float32)
        return verts, faces, colors, edge_verts


# --------------------------------------------------------------------------
# 격자 → 표면 메쉬 (surface nets, 순수 numpy)
# --------------------------------------------------------------------------

def _coarsen(occ, col, factor):
    """복셀 factor^3개를 하나로 합친다 — 절반 이상 차 있으면 소재, 색은 대표 복셀의 것."""
    nx, ny, nz = occ.shape
    mx, my, mz = (-(-n // factor) for n in (nx, ny, nz))
    padded = np.zeros((mx * factor, my * factor, mz * factor), dtype=np.uint8)
    padded[:nx, :ny, :nz] = occ
    pad_col = np.full(padded.shape, UNCUT_COLOR, dtype=np.uint8)
    pad_col[:nx, :ny, :nz] = col
    blocks = padded.reshape(mx, factor, my, factor, mz, factor).sum(axis=(1, 3, 5), dtype=np.int32)
    coarse = (blocks * 2 >= factor ** 3).astype(np.uint8)
    # 색: 블록 안에서 안 깎인 값(255)이 아닌 것 중 가장 작은 id
    cols = pad_col.reshape(mx, factor, my, factor, mz, factor).min(axis=(1, 3, 5))
    return coarse, cols


def surface_nets(occ, col, origin, step):
    """이진 점유 격자의 표면을 surface nets로 뽑는다.

    돌려줌: (verts float32 N×3, faces int32 M×3, vert_col uint8 N, quads int32 Q×4).
    소재 바깥은 빈 칸으로 채워 닫힌 메쉬가 되며 법선은 소재 바깥쪽을 향한다. 정점 색은
    그 칸 주변의 **빈 쪽** 복셀 색(= 그 면을 만든 공구)이다."""
    g = np.pad(occ.astype(np.uint8), 1)
    gc = np.pad(col, 1, constant_values=UNCUT_COLOR)
    nx, ny, nz = g.shape
    x0, y0, z0 = origin
    rx, ry, rz = step

    csum = np.zeros((nx - 1, ny - 1, nz - 1), dtype=np.uint8)
    for di in (0, 1):
        for dj in (0, 1):
            for dk in (0, 1):
                csum += g[di:nx - 1 + di, dj:ny - 1 + dj, dk:nz - 1 + dk]
    ci, cj, ck = np.nonzero((csum > 0) & (csum < 8))
    del csum
    n_cells = ci.size
    if n_cells == 0:
        empty = np.zeros((0, 3), dtype=np.float32)
        return empty, np.zeros((0, 3), dtype=np.int32), np.zeros(0, dtype=np.uint8), \
            np.zeros((0, 4), dtype=np.int32)

    corners = [(di, dj, dk) for di in (0, 1) for dj in (0, 1) for dk in (0, 1)]
    cv = [g[ci + di, cj + dj, ck + dk] for di, dj, dk in corners]
    total = np.zeros((n_cells, 3), dtype=np.float32)
    count = np.zeros(n_cells, dtype=np.float32)
    for a in range(8):
        for b in range(a + 1, 8):
            da = np.array(corners[a])
            db = np.array(corners[b])
            if int(np.abs(da - db).sum()) != 1:
                continue                      # 큐브 모서리(변)만
            cross = cv[a] != cv[b]
            total += cross[:, None] * ((da + db) * 0.5).astype(np.float32)
            count += cross
    local = total / np.maximum(count, 1.0)[:, None]
    vpos = np.stack([ci, cj, ck], axis=1).astype(np.float32) + local     # 복셀 중심 좌표계(패딩 포함)
    verts = np.empty((n_cells, 3), dtype=np.float32)
    verts[:, 0] = x0 + (vpos[:, 0] - 1.0 + 0.5) * rx
    verts[:, 1] = y0 + (vpos[:, 1] - 1.0 + 0.5) * ry
    verts[:, 2] = z0 + (vpos[:, 2] - 1.0 + 0.5) * rz

    vert_col = np.full(n_cells, UNCUT_COLOR, dtype=np.uint8)
    for idx, (di, dj, dk) in enumerate(corners):
        cc = gc[ci + di, cj + dj, ck + dk]
        take = (cv[idx] == 0) & (cc != UNCUT_COLOR) & (vert_col == UNCUT_COLOR)
        vert_col[take] = cc[take]
    del cv

    lin = (ci.astype(np.int64) * (ny - 1) + cj) * (nz - 1) + ck      # 오름차순

    def vid(i, j, k):
        q = (i.astype(np.int64) * (ny - 1) + j) * (nz - 1) + k
        return np.searchsorted(lin, q).astype(np.int32)

    quads = []
    # x 방향 변: (i,j,k)-(i+1,j,k)가 서로 다르면 사각형 하나
    diff = g[:-1] != g[1:]
    ei, ej, ek = np.nonzero(diff)
    lower = g[ei, ej, ek] == 1
    q = np.stack([vid(ei, ej - 1, ek - 1), vid(ei, ej, ek - 1), vid(ei, ej, ek), vid(ei, ej - 1, ek)], axis=1)
    quads.append(np.where(lower[:, None], q, q[:, ::-1]))
    diff = g[:, :-1] != g[:, 1:]
    ei, ej, ek = np.nonzero(diff)
    lower = g[ei, ej, ek] == 1
    q = np.stack([vid(ei - 1, ej, ek - 1), vid(ei - 1, ej, ek), vid(ei, ej, ek), vid(ei, ej, ek - 1)], axis=1)
    quads.append(np.where(lower[:, None], q, q[:, ::-1]))
    diff = g[:, :, :-1] != g[:, :, 1:]
    ei, ej, ek = np.nonzero(diff)
    lower = g[ei, ej, ek] == 1
    q = np.stack([vid(ei - 1, ej - 1, ek), vid(ei, ej - 1, ek), vid(ei, ej, ek), vid(ei - 1, ej, ek)], axis=1)
    quads.append(np.where(lower[:, None], q, q[:, ::-1]))
    quad_idx = np.concatenate(quads).astype(np.int32)
    faces = np.concatenate([quad_idx[:, [0, 1, 2]], quad_idx[:, [0, 2, 3]]]).astype(np.int32)
    return verts, faces, vert_col, quad_idx


def crease_edges(verts, quads, angle_deg):
    """이웃한 두 사각형의 법선이 angle_deg 넘게 꺾이는 변 — (2M, 3) float32('lines')."""
    if quads.shape[0] == 0:
        return np.zeros((0, 3), dtype=np.float32)
    v = verts.astype(np.float64)
    normal = np.cross(v[quads[:, 2]] - v[quads[:, 0]], v[quads[:, 3]] - v[quads[:, 1]])
    length = np.linalg.norm(normal, axis=1)
    normal /= np.where(length < 1e-12, 1.0, length)[:, None]
    a = np.concatenate([quads[:, 0], quads[:, 1], quads[:, 2], quads[:, 3]]).astype(np.int64)
    b = np.concatenate([quads[:, 1], quads[:, 2], quads[:, 3], quads[:, 0]]).astype(np.int64)
    owner = np.tile(np.arange(quads.shape[0]), 4)
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    key = lo * (verts.shape[0] + 1) + hi
    order = np.argsort(key, kind='stable')
    key_s = key[order]
    same = key_s[1:] == key_s[:-1]
    first = order[:-1][same]
    second = order[1:][same]
    cosang = np.einsum('ij,ij->i', normal[owner[first]], normal[owner[second]])
    sharp = cosang < np.cos(np.radians(angle_deg))
    e_lo = lo[first][sharp]
    e_hi = hi[first][sharp]
    if e_lo.size > SIM_EDGE_SEGMENT_LIMIT:
        keep = np.linspace(0, e_lo.size - 1, SIM_EDGE_SEGMENT_LIMIT).astype(np.int64)
        e_lo, e_hi = e_lo[keep], e_hi[keep]
    pts = np.stack([verts[e_lo], verts[e_hi]], axis=1).reshape(-1, 3)
    return np.ascontiguousarray(pts, dtype=np.float32)
