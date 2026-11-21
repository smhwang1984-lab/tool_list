"""nc_sim_gpu_ref.py — GPU Z-map 절삭 셰이더(sim_shaders/cut.vert, cut.frag)의 CPU 기준 구현 (v2.8.0, G1).

셰이더가 화소 하나에서 하는 계산을 칸 단위로 그대로 옮긴 numpy 코드다. 두 가지 일을 한다.
  1. 셰이더의 정답표 — 실제 GPU 결과(G5)를 이 구현과 비교한다. 식·상수는 cut.frag와 같아야 한다.
  2. GPU를 못 쓰는 PC·시험에서 같은 "연속 선분 훑기" 결과를 CPU로 얻는다(느리다 — 시험·검증용).

계산(칸 중심 c, 선분 a→b, 공구 반지름 r, 팁 높이 z(t) = az + t*(bz - az)):
    f(t) = z(t) + h(|c - p(t)|)  을  p(t)가 공구 안(|c - p(t)| <= r)인 t 구간에서 최소화한다.
h는 d에 대해 볼록·증가, d(t)는 볼록 → f가 볼록이라 황금분할 탐색이 정확하다. 구간 양 끝은 따로 정확히 잰다.

지금 CPU 엔진(nc_sim.ZMapStock)과의 차이 — 의도된 것이다:
  - CPU는 경사 이동을 조각으로 쪼개 조각마다 낮은 끝 Z를 쓰고 공구 높이는 반경 표(LUT)를 선형 보간한다.
    수평·수직 이동은 정확하지만, 경사 이동(dz != 0 이면서 수평 이동이 있는 선분)은 조각 크기만큼 더 깊게
    깎는 쪽으로 오차가 있다. 이 구현은 경사에서도 정확하다 → 경사 이동의 바깥 가장자리 칸에서 CPU가 같거나 더 깊다.
  - 공구 바깥 가장자리 칸(d가 r에 가까운 칸)은 LUT 보간 때문에 CPU 값이 조금 다를 수 있다(코너 R·볼 끝에서 큼).
"""

from __future__ import annotations

import numpy as np

import nc_sim

# cut.frag 의 같은 이름 상수와 같아야 한다.
GOLD_ITER = 24
INV_PHI = 0.6180339887498949
R2_EPS = 1e-9
R2_REL_EPS = 1e-5      # float32에서 "칸 중심이 정확히 반지름 위"인 줄이 반올림으로 빠지지 않게 하는 상대 여유
VERTICAL_LEN2 = 1e-18


def profile_h(d, params):
    """cut.frag profile_h(). d: 배열, params: (kind, a, b, c)."""
    kind = int(params[0] + 0.5)
    a, b = params[1], params[2]
    d = np.asarray(d, dtype=np.float64)
    if kind == nc_sim.PROFILE_CORNER:
        dr = np.clip(d - a, 0.0, b)
        return np.where(d > a, b - np.sqrt(np.maximum(b * b - dr * dr, 0.0)), 0.0)
    if kind == nc_sim.PROFILE_CONE:
        return d * a
    if kind == nc_sim.PROFILE_CHAMFER:
        return np.maximum(d - a, 0.0)
    return np.zeros_like(d)


def sweep_min_height(qx, qy, dx, dy, az, dz, radius, params, track_argmin=False):
    """선분 하나가 칸 배열(중심이 a에서 (qx, qy)만큼 떨어진 칸들)에 만드는 새 윗면 높이.

    닿지 않는 칸은 +inf. track_argmin=True면 (높이, 최솟값이 생긴 지점의 수평 거리 d)를 돌려준다."""
    qx = np.asarray(qx, dtype=np.float64)
    qy = np.asarray(qy, dtype=np.float64)
    r2 = radius * radius * (1.0 + R2_REL_EPS) + R2_EPS
    len2 = dx * dx + dy * dy
    qq = qx * qx + qy * qy

    def f(t):
        wx = qx - t * dx
        wy = qy - t * dy
        return az + dz * t + profile_h(np.sqrt(wx * wx + wy * wy), params)

    if len2 < VERTICAL_LEN2:
        valid = qq <= r2
        lo = np.zeros_like(qq)
        hi = np.ones_like(qq)
    else:
        qd = qx * dx + qy * dy
        disc = qd * qd - len2 * (qq - r2)
        valid = disc >= 0.0
        sq = np.sqrt(np.maximum(disc, 0.0))
        lo = np.maximum((qd - sq) / len2, 0.0)
        hi = np.minimum((qd + sq) / len2, 1.0)
        valid &= lo <= hi
        lo = np.where(valid, lo, 0.0)
        hi = np.where(valid, hi, 1.0)

    f_lo = f(lo)
    f_hi = f(hi)
    use_lo = f_lo <= f_hi
    best = np.where(use_lo, f_lo, f_hi)
    best_t = np.where(use_lo, lo, hi)

    if len2 >= VERTICAL_LEN2:
        ta, tb = lo.copy(), hi.copy()
        tc = tb - (tb - ta) * INV_PHI
        td = ta + (tb - ta) * INV_PHI
        fc, fd = f(tc), f(td)
        for t_new, f_new in ((tc, fc), (td, fd)):
            better = f_new < best
            best = np.where(better, f_new, best)
            best_t = np.where(better, t_new, best_t)
        for _ in range(GOLD_ITER):
            left = fc < fd
            tb = np.where(left, td, tb)
            ta = np.where(left, ta, tc)
            t_keep = np.where(left, tc, td)          # 새 구간 안에 남는 안쪽 점
            f_keep = np.where(left, fc, fd)
            t_new = np.where(left, tb - (tb - ta) * INV_PHI, ta + (tb - ta) * INV_PHI)
            f_new = f(t_new)
            # left: (c, d) <- (new, keep)   right: (c, d) <- (keep, new)
            tc = np.where(left, t_new, t_keep)
            fc = np.where(left, f_new, f_keep)
            td = np.where(left, t_keep, t_new)
            fd = np.where(left, f_keep, f_new)
            better = f_new < best
            best = np.where(better, f_new, best)
            best_t = np.where(better, t_new, best_t)

    best = np.where(valid, best, np.inf)
    if not track_argmin:
        return best
    wx = qx - best_t * dx
    wy = qy - best_t * dy
    return best, np.sqrt(wx * wx + wy * wy)


class ZMapGpuRef(nc_sim.ZMapStock):
    """셰이더와 같은 식으로 깎는 Z-map 소재. nc_sim.ZMapStock과 같은 인터페이스(cut_batch 등)를 쓴다.

    edge_mask: 마지막으로 그 칸을 낮춘 선분에서 최솟값 지점이 공구 가장자리(d > r - EDGE_BAND_CELLS*res)였던 칸.
    CPU 엔진과 칸 단위로 비교할 때 이 칸들은 따로 본다."""

    EDGE_BAND_CELLS = 1.5

    def __init__(self, bounds, resolution):
        super().__init__(bounds, resolution)
        self.edge_mask = np.zeros((self.ny, self.nx), dtype=bool)

    def reset(self):
        super().reset()
        self.edge_mask = np.zeros((self.ny, self.nx), dtype=bool)

    def restore(self, snap):
        super().restore(snap)
        self.edge_mask = np.zeros((self.ny, self.nx), dtype=bool)

    def _cut_one(self, ax, ay, az, bx, by, bz, radius, params, color):
        """선분 하나를 칸 범위에 훑는다. 깎인 칸이 있으면 True. (cut.vert 의 칸 범위와 같다)"""
        res = self.resolution
        ix0 = max(int(np.floor((min(ax, bx) - radius - self.x0) / res)), 0)
        ix1 = min(int(np.ceil((max(ax, bx) + radius - self.x0) / res)), self.nx - 1)
        iy0 = max(int(np.floor((min(ay, by) - radius - self.y0) / res)), 0)
        iy1 = min(int(np.ceil((max(ay, by) + radius - self.y0) / res)), self.ny - 1)
        if ix0 > ix1 or iy0 > iy1:
            return False
        qx = (self._gx[ix0:ix1 + 1] - ax)[None, :]
        qy = (self._gy[iy0:iy1 + 1] - ay)[:, None]
        value, dmin = sweep_min_height(qx, qy, bx - ax, by - ay, az, bz - az, radius, params,
                                       track_argmin=True)
        zlo32 = np.float32(self.zlo)
        with np.errstate(invalid='ignore'):
            new = np.maximum(value.astype(np.float32), zlo32)
        sub = self.heights[iy0:iy1 + 1, ix0:ix1 + 1]
        low = np.isfinite(value) & (new < sub) & (value < self.ztop)
        np.copyto(sub, new, where=low)
        np.copyto(self.color_ids[iy0:iy1 + 1, ix0:ix1 + 1], np.int16(color), where=low)
        np.copyto(self.edge_mask[iy0:iy1 + 1, ix0:ix1 + 1],
                  dmin > radius - self.EDGE_BAND_CELLS * res, where=low)
        return bool(low.any())

    def cut_batch(self, P0, P1, tools, tool_idx, rapid, color, src_lines=None, seqs=None,
                  cancel=None, progress=None, chunk=nc_sim.SIM_CHUNK_SEGMENTS, use_numba=None):
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        total = P0.shape[0]
        if total == 0:
            return True
        params = []
        for tool in tools:
            if tool is None:
                params.append(None)
                continue
            p = tool.profile_params()
            if p is None:
                raise ValueError('GPU 엔진이 모르는 공구 형상입니다(%s) — CPU 엔진으로 깎아야 합니다' % tool.type_name)
            params.append(p)
        tool_idx = np.asarray(tool_idx, dtype=np.int64)
        rapid = np.asarray(rapid, dtype=bool)
        color = np.asarray(color, dtype=np.int16)
        for start in range(0, total, chunk):
            if cancel is not None and cancel():
                return False
            end = min(start + chunk, total)
            for m in range(start, end):
                t = int(tool_idx[m])
                if t < 0 or t >= len(tools) or tools[t] is None:
                    continue
                ax, ay, az = P0[m]
                bx, by, bz = P1[m]
                if min(az, bz) >= self.ztop:
                    continue
                hit = self._cut_one(ax, ay, az, bx, by, bz, tools[t].radius, params[t], color[m])
                if hit and rapid[m]:
                    src = None if src_lines is None else src_lines[m]
                    seq = None if seqs is None else seqs[m]
                    self.rapid_cut_warnings.append((None if src is None else int(src),
                                                    None if seq is None else int(seq)))
            if progress is not None:
                progress(end, total)
        return True
