"""nc_sim_numba.py — nc_sim의 절삭 커널(Numba 가속판, v1.9.2).

nc_sim.py가 처음 절삭할 때만 지연 import 한다. numba가 없으면(예: 배포 exe)
ImportError가 나고 nc_sim은 순수 numpy 경로로 대신 계산한다. 두 경로는 같은
산식(nc_sim._stamp_numpy 와 순서까지 같다)이라 결과가 같아야 한다 —
tests/test_nc_sim.py 가 비교한다.

방식: 선분 하나를 격자의 각 칸에서 "선분까지의 수평 거리 d"로 본다. 칸 높이는
min(현재, 공구 팁 Z + h(d))로 갱신한다(h = 공구 프로파일, 반경 밖은 닿지 않음).
샘플 위치를 격자에 맞춰 커널을 찍는 방식(v1.9.1)보다 연산이 적고 맞춤 오차가 없다.
Z가 변하는 선분은 Z 변화가 격자 간격의 SUB_Z 이하가 되도록 잘게 나눠 각 조각을
같은 Z(조각 양끝 중 낮은 쪽)로 처리한다.
"""

import math

import numpy as np
from numba import njit

SUB_Z = 0.25          # 조각당 최대 Z 변화 = 격자 간격 x SUB_Z (nc_sim.SUB_Z와 같아야 함)
MAX_SUB = 400


@njit(cache=True, nogil=True)
def _stamp(heights, color_ids, x0, y0, res, zlo32, ax, ay, bx, by, z,
           lut, base, radius, inv_step, color):
    """수평 선분 (ax,ay)->(bx,by)를 팁 높이 z로 훑는다. 깎인 칸이 있으면 True."""
    ny = heights.shape[0]
    nx = heights.shape[1]
    dx = bx - ax
    dy = by - ay
    len2 = dx * dx + dy * dy
    r2 = radius * radius + 1e-9
    ix0 = max(np.int64(math.floor((min(ax, bx) - radius - x0) / res)), 0)
    ix1 = min(np.int64(math.ceil((max(ax, bx) + radius - x0) / res)), nx - 1)
    iy0 = max(np.int64(math.floor((min(ay, by) - radius - y0) / res)), 0)
    iy1 = min(np.int64(math.ceil((max(ay, by) + radius - y0) / res)), ny - 1)
    if ix0 > ix1 or iy0 > iy1:
        return False
    lowered = False
    for yy in range(iy0, iy1 + 1):
        py = (y0 + yy * res) - ay
        for xx in range(ix0, ix1 + 1):
            px = (x0 + xx * res) - ax
            if len2 > 0.0:
                t = (px * dx + py * dy) / len2
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                qx = px - t * dx
                qy = py - t * dy
            else:
                qx = px
                qy = py
            d2 = qx * qx + qy * qy
            if d2 > r2:
                continue
            pos = math.sqrt(d2) * inv_step
            k = np.int64(pos)
            frac = pos - k
            h = lut[base + k] * (1.0 - frac) + lut[base + k + 1] * frac
            v = np.float32(z + h)
            if v < zlo32:
                v = zlo32
            # 이미 낮아진 칸은 쓰지 않는다(겹치는 조각이 많아 대부분 읽기만 함)
            if v < heights[yy, xx]:
                heights[yy, xx] = v
                color_ids[yy, xx] = color
                lowered = True
    return lowered


@njit(cache=True, nogil=True)
def cut_chunk(heights, color_ids, x0, y0, res, zlo, ztop, P0, P1, tool_idx, color,
              lut, loff, lrad, linv, hit):
    """선분 묶음(P0[m] -> P1[m])을 순서대로 깎는다. hit[m]은 그 선분이 실제로
    소재를 깎았는지."""
    zlo32 = np.float32(zlo)
    for m in range(P0.shape[0]):
        t = tool_idx[m]
        if t < 0:
            continue
        ax = P0[m, 0]
        ay = P0[m, 1]
        az = P0[m, 2]
        bx = P1[m, 0]
        by = P1[m, 1]
        bz = P1[m, 2]
        if min(az, bz) >= ztop:
            continue  # 소재 윗면보다 위 — 깎을 것이 없다
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        if dx * dx + dy * dy < 1e-18:
            n_sub = 1                     # 수직 이동 — 낮은 끝점 한 번이면 된다
        else:
            n_sub = min(max(1, np.int64(math.ceil(abs(dz) / (res * SUB_Z)))), MAX_SUB)
        c = color[m]
        base = loff[t]
        radius = lrad[t]
        inv_step = linv[t]
        any_low = False
        for k in range(n_sub):
            ta = k / n_sub
            tb = (k + 1) / n_sub
            z = min(az + dz * ta, az + dz * tb)
            if z >= ztop:
                continue
            if _stamp(heights, color_ids, x0, y0, res, zlo32,
                      ax + dx * ta, ay + dy * ta, ax + dx * tb, ay + dy * tb, z,
                      lut, base, radius, inv_step, c):
                any_low = True
        hit[m] = any_low


# ==========================================================================
# v1.10.0 — 3D 소재(복셀) 절삭 커널 (nc_sim3d.VoxelStock). 산식·순서는
# nc_sim3d._stamp3d_numpy 와 같다 — 결과가 같아야 한다(tests/test_nc_sim3d.py).
# ==========================================================================

ANGLE_STEP_DEG = 2.0       # nc_sim3d.SIM3D_ANGLE_STEP_DEG 와 같아야 함
SUB_AXIAL = 0.25           # nc_sim3d.SIM3D_SUB_AXIAL 와 같아야 함
MAX_SUB_3D = 400           # nc_sim3d.SIM3D_MAX_SUB 와 같아야 함


@njit(cache=True, nogil=True)
def _clip01(v):
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


@njit(cache=True, nogil=True)
def _feasible3(u, wp2, dot, dp2, s0, dpar, r2, length, lut, base, inv_step, kmax):
    """이동 비율 u에서 이 복셀이 공구 안인가(반경 이내, s <= 날장, s >= h(d))."""
    dd2 = wp2 - 2.0 * u * dot + u * u * dp2
    if dd2 < 0.0:
        dd2 = 0.0
    if dd2 > r2:
        return False
    s = s0 - u * dpar
    if s > length:
        return False
    pos = math.sqrt(dd2) * inv_step
    k = np.int64(pos)
    if k > kmax:
        k = kmax
    frac = pos - k
    h = lut[base + k] * (1.0 - frac) + lut[base + k + 1] * frac
    return s >= h


@njit(cache=True, nogil=True)
def _stamp3d(occ, col, x0, y0, z0, rx, ry, rz, ax, ay, az, bx, by, bz, ux, uy, uz,
             lut, base, kmax, radius, inv_step, length, color):
    """이동 조각(A→B, 공구 축 u 고정)으로 소재를 깎는다. 깎은 복셀 수를 돌려준다."""
    nx = occ.shape[0]
    ny = occ.shape[1]
    nz = occ.shape[2]
    ext = radius + 1e-9
    tx = length * ux
    ty = length * uy
    tz = length * uz
    lo_x = min(min(ax, bx), min(ax + tx, bx + tx)) - ext
    hi_x = max(max(ax, bx), max(ax + tx, bx + tx)) + ext
    lo_y = min(min(ay, by), min(ay + ty, by + ty)) - ext
    hi_y = max(max(ay, by), max(ay + ty, by + ty)) + ext
    lo_z = min(min(az, bz), min(az + tz, bz + tz)) - ext
    hi_z = max(max(az, bz), max(az + tz, bz + tz)) + ext
    i0 = max(np.int64(math.floor((lo_x - x0) / rx)), 0)
    i1 = min(np.int64(math.ceil((hi_x - x0) / rx)), nx - 1)
    j0 = max(np.int64(math.floor((lo_y - y0) / ry)), 0)
    j1 = min(np.int64(math.ceil((hi_y - y0) / ry)), ny - 1)
    k0 = max(np.int64(math.floor((lo_z - z0) / rz)), 0)
    k1 = min(np.int64(math.ceil((hi_z - z0) / rz)), nz - 1)
    if i0 > i1 or j0 > j1 or k0 > k1:
        return 0
    dx = bx - ax
    dy = by - ay
    dz = bz - az
    dpar = dx * ux + dy * uy + dz * uz
    dpx = dx - dpar * ux
    dpy = dy - dpar * uy
    dpz = dz - dpar * uz
    dp2 = dpx * dpx + dpy * dpy + dpz * dpz
    r2 = radius * radius + 1e-9
    removed = 0
    for i in range(i0, i1 + 1):
        wx = x0 + (i + 0.5) * rx - ax
        for j in range(j0, j1 + 1):
            wy = y0 + (j + 0.5) * ry - ay
            for k in range(k0, k1 + 1):
                if occ[i, j, k] == 0:
                    continue
                wz = z0 + (k + 0.5) * rz - az
                s0 = wx * ux + wy * uy + wz * uz
                wpx = wx - s0 * ux
                wpy = wy - s0 * uy
                wpz = wz - s0 * uz
                wp2 = wpx * wpx + wpy * wpy + wpz * wpz
                dot = wpx * dpx + wpy * dpy + wpz * dpz
                if dp2 > 0.0:
                    t = _clip01(dot / dp2)
                else:
                    t = 0.0
                dd2 = wp2 - 2.0 * t * dot + t * t * dp2
                if dd2 > r2:
                    continue
                ok = _feasible3(t, wp2, dot, dp2, s0, dpar, r2, length, lut, base, inv_step, kmax)
                if not ok and abs(dpar) > 1e-12:
                    ok = _feasible3(_clip01((s0 - length) / dpar), wp2, dot, dp2, s0, dpar, r2,
                                    length, lut, base, inv_step, kmax)
                    if not ok:
                        ok = _feasible3(_clip01(s0 / dpar), wp2, dot, dp2, s0, dpar, r2,
                                        length, lut, base, inv_step, kmax)
                if not ok and dp2 > 0.0:
                    disc = dot * dot - dp2 * (wp2 - r2)
                    if disc < 0.0:
                        disc = 0.0
                    sq = math.sqrt(disc)
                    ok = _feasible3(_clip01((dot - sq) / dp2), wp2, dot, dp2, s0, dpar, r2,
                                    length, lut, base, inv_step, kmax)
                    if not ok:
                        ok = _feasible3(_clip01((dot + sq) / dp2), wp2, dot, dp2, s0, dpar, r2,
                                        length, lut, base, inv_step, kmax)
                if ok:
                    occ[i, j, k] = 0
                    col[i, j, k] = color
                    removed += 1
    return removed


@njit(cache=True, nogil=True)
def cut_chunk3d(occ, col, x0, y0, z0, rx, ry, rz, P0, P1, A0, A1, tool_idx, color,
                lut, loff, lrad, linv, llen, hit, res_min):
    """선분 묶음(P0[m]->P1[m], 공구 축 A0[m]->A1[m])을 순서대로 깎는다."""
    nx = occ.shape[0]
    ny = occ.shape[1]
    nz = occ.shape[2]
    x1 = x0 + nx * rx
    y1 = y0 + ny * ry
    z1 = z0 + nz * rz
    for m in range(P0.shape[0]):
        t = tool_idx[m]
        if t < 0:
            continue
        ax = P0[m, 0]
        ay = P0[m, 1]
        az = P0[m, 2]
        bx = P1[m, 0]
        by = P1[m, 1]
        bz = P1[m, 2]
        radius = lrad[t]
        length = llen[t]
        reach = radius + length
        if (max(ax, bx) + reach < x0 or min(ax, bx) - reach > x1
                or max(ay, by) + reach < y0 or min(ay, by) - reach > y1
                or max(az, bz) + reach < z0 or min(az, bz) - reach > z1):
            continue
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        a0x = A0[m, 0]
        a0y = A0[m, 1]
        a0z = A0[m, 2]
        a1x = A1[m, 0]
        a1y = A1[m, 1]
        a1z = A1[m, 2]
        # 조각 수 — nc_sim3d._piece_count 와 같은 식
        n_ang = np.int64(1)
        cosang = a0x * a1x + a0y * a1y + a0z * a1z
        if cosang > 1.0:
            cosang = 1.0
        elif cosang < -1.0:
            cosang = -1.0
        ang = math.degrees(math.acos(cosang))
        if ang > 1e-9:
            n_ang = np.int64(math.ceil(ang / ANGLE_STEP_DEG))
        amx = a0x + a1x
        amy = a0y + a1y
        amz = a0z + a1z
        nm = math.sqrt(amx * amx + amy * amy + amz * amz)
        if nm > 1e-12:
            amx = amx / nm
            amy = amy / nm
            amz = amz / nm
        else:
            amx = a0x
            amy = a0y
            amz = a0z
        dpar = dx * amx + dy * amy + dz * amz
        ppx = dx - dpar * amx
        ppy = dy - dpar * amy
        ppz = dz - dpar * amz
        dperp = math.sqrt(ppx * ppx + ppy * ppy + ppz * ppz)
        n_ax = np.int64(math.ceil(min(abs(dpar), dperp) / (SUB_AXIAL * res_min)))
        n_sub = min(max(max(np.int64(1), n_ang), n_ax), np.int64(MAX_SUB_3D))
        c = color[m]
        base = loff[t]
        if t + 1 < loff.shape[0]:
            lsize = loff[t + 1] - base
        else:
            lsize = lut.shape[0] - base
        kmax = lsize - 2
        inv_step = linv[t]
        removed = 0
        for k in range(n_sub):
            ta = k / n_sub
            tb = (k + 1) / n_sub
            mid = (k + 0.5) / n_sub
            ux = a0x + (a1x - a0x) * mid
            uy = a0y + (a1y - a0y) * mid
            uz = a0z + (a1z - a0z) * mid
            nu = math.sqrt(ux * ux + uy * uy + uz * uz)
            if nu > 1e-12:
                ux = ux / nu
                uy = uy / nu
                uz = uz / nu
            else:
                ux = a0x
                uy = a0y
                uz = a0z
            removed += _stamp3d(occ, col, x0, y0, z0, rx, ry, rz,
                                ax + dx * ta, ay + dy * ta, az + dz * ta,
                                ax + dx * tb, ay + dy * tb, az + dz * tb,
                                ux, uy, uz, lut, base, kmax, radius, inv_step, length, c)
        hit[m] = removed > 0


# --------------------------------------------------------------------------
# v2.2.0 — 선반 축대칭 소재(nc_lathe_sim.LatheStock) 절삭 커널
# 공구 = (z, r) 단면의 볼록 다각형. 선분 하나가 쓸고 지나간 영역은 다각형을 시작점/끝점에
# 놓은 두 복사본의 볼록 껍질이다. 껍질을 스캔라인(열 단위)으로 채워 격자 칸을 지운다.
# 산식은 nc_lathe_sim._cut_chunk_numpy 와 같아야 한다(tests/test_nc_lathe_sim.py 가 비교).
# --------------------------------------------------------------------------

@njit(cache=True, nogil=True)
def _cross(ax, ay, bx, by, cx, cy):
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


@njit(cache=True, nogil=True)
def _convex_hull(zs, rs, n, hz, hr):
    """Andrew monotone chain. 점 n개 -> 반시계 껍질 꼭짓점 수. hz/hr 크기는 2n 이상."""
    idx = np.arange(n)
    for i in range(1, n):
        key = idx[i]
        j = i - 1
        while j >= 0 and (zs[idx[j]] > zs[key] or (zs[idx[j]] == zs[key] and rs[idx[j]] > rs[key])):
            idx[j + 1] = idx[j]
            j -= 1
        idx[j + 1] = key
    k = 0
    for ii in range(n):
        i = idx[ii]
        while k >= 2 and _cross(hz[k - 2], hr[k - 2], hz[k - 1], hr[k - 1], zs[i], rs[i]) <= 0.0:
            k -= 1
        hz[k] = zs[i]
        hr[k] = rs[i]
        k += 1
    t = k + 1
    for ii in range(n - 2, -1, -1):
        i = idx[ii]
        while k >= t and _cross(hz[k - 2], hr[k - 2], hz[k - 1], hr[k - 1], zs[i], rs[i]) <= 0.0:
            k -= 1
        hz[k] = zs[i]
        hr[k] = rs[i]
        k += 1
    return k - 1 if k > 1 else k


@njit(cache=True, nogil=True)
def _fill_hull(occ, col, z0, dz, dr, hz, hr, h, color, cut):
    """껍질(꼭짓점 h개) 안에 중심이 든 소재 칸을 센다. cut이 1이면 지우고 색을 남긴다."""
    nz = occ.shape[0]
    nr = occ.shape[1]
    if h < 1:
        return 0
    zmin = hz[0]
    zmax = hz[0]
    for i in range(1, h):
        if hz[i] < zmin:
            zmin = hz[i]
        if hz[i] > zmax:
            zmax = hz[i]
    iz0 = int(math.ceil((zmin - z0) / dz - 0.5))
    iz1 = int(math.floor((zmax - z0) / dz - 0.5))
    if iz0 < 0:
        iz0 = 0
    if iz1 > nz - 1:
        iz1 = nz - 1
    removed = 0
    for iz in range(iz0, iz1 + 1):
        zc = z0 + (iz + 0.5) * dz
        lo = 1e300
        hi = -1e300
        for i in range(h):
            j = i + 1 if i + 1 < h else 0
            za = hz[i]
            zb = hz[j]
            ra = hr[i]
            rb = hr[j]
            if za == zb:
                if za == zc:
                    if ra < lo:
                        lo = ra
                    if rb < lo:
                        lo = rb
                    if ra > hi:
                        hi = ra
                    if rb > hi:
                        hi = rb
                continue
            if (za <= zc and zc <= zb) or (zb <= zc and zc <= za):
                r = ra + (zc - za) / (zb - za) * (rb - ra)
                if r < lo:
                    lo = r
                if r > hi:
                    hi = r
        if hi < lo:
            continue
        ir0 = int(math.ceil(lo / dr - 0.5))
        ir1 = int(math.floor(hi / dr - 0.5))
        if ir0 < 0:
            ir0 = 0
        if ir1 > nr - 1:
            ir1 = nr - 1
        for ir in range(ir0, ir1 + 1):
            if occ[iz, ir]:
                removed += 1
                if cut:
                    occ[iz, ir] = 0
                    col[iz, ir] = color
    return removed


@njit(cache=True, nogil=True)
def cut_chunk_lathe(occ, col, z0, dz, dr, p0z, p0r, p1z, p1r, tool_idx, color, rapid,
                    poly_z, poly_r, poff, pcnt, hit):
    """선분 묶음을 순서대로 깎는다. rapid 선분은 깎지 않고 닿는 소재 칸 수만 hit에 남긴다."""
    total = p0z.shape[0]
    maxk = 1
    for t in range(pcnt.shape[0]):
        if pcnt[t] > maxk:
            maxk = pcnt[t]
    zs = np.empty(2 * maxk)
    rs = np.empty(2 * maxk)
    hz = np.empty(4 * maxk + 4)
    hr = np.empty(4 * maxk + 4)
    for m in range(total):
        t = tool_idx[m]
        if t < 0:
            hit[m] = 0
            continue
        n = pcnt[t]
        base = poff[t]
        for k in range(n):
            zs[k] = poly_z[base + k] + p0z[m]
            rs[k] = poly_r[base + k] + p0r[m]
            zs[n + k] = poly_z[base + k] + p1z[m]
            rs[n + k] = poly_r[base + k] + p1r[m]
        h = _convex_hull(zs, rs, 2 * n, hz, hr)
        if rapid[m]:
            hit[m] = _fill_hull(occ, col, z0, dz, dr, hz, hr, h, color[m], 0)
        else:
            hit[m] = _fill_hull(occ, col, z0, dz, dr, hz, hr, h, color[m], 1)
