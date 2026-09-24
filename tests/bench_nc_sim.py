"""bench_nc_sim.py — 형상 시뮬레이션 속도 측정(pytest 대상 아님).

    python tests/bench_nc_sim.py [선분수]

소재 150x100mm(약 100만 셀), D10 평엔드밀 지그재그 경로로 절삭·메쉬 생성 시간을
출력한다. v1.9.1 기준값(같은 조건 1,919선분): 절삭 10.9초, 메쉬 정점 608만 개 / 0.57초.
"""

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nc_sim  # noqa: E402


def zigzag(count):
    """1mm 선분 지그재그(가로 120mm 줄을 5mm 간격으로) — 최대 count개."""
    pts = []
    for y in np.arange(-40, 40, 5.0):
        for x in np.arange(-60, 60, 1.0):
            pts.append((x, y, -3.0))
    pts = np.array(pts, dtype=np.float64)
    reps = int(np.ceil((count + 1) / len(pts)))
    depth = np.repeat(-3.0 - np.arange(reps) * 0.5, len(pts))[:count + 1]
    pts = np.tile(pts, (reps, 1))[:count + 1]
    pts[:, 2] = depth
    return pts[:-1], pts[1:]


def timed(label, func):
    t0 = time.perf_counter()
    result = func()
    print('%-34s %8.3f 초' % (label, time.perf_counter() - t0))
    return result


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1919
    diameter = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    bounds = {'X': (-75, 75), 'Y': (-50, 50), 'Z': (-30, 0)}
    res = nc_sim.auto_resolution(bounds)
    tool = nc_sim.tool_shape_from_values('FLAT E/M', diameter)
    p0, p1 = zigzag(count)
    zeros = np.zeros(count, dtype=int)
    print('선분 %d개, 공구 D%g, 해상도 %.3f mm, numba %s'
          % (count, diameter, res, '있음' if nc_sim.numba_available() else '없음'))

    for label, use_numba in (('절삭 numpy', False), ('절삭 numba(컴파일/캐시 포함)', True),
                             ('절삭 numba(재실행)', True)):
        if use_numba and not nc_sim.numba_available():
            continue
        stock = nc_sim.ZMapStock(bounds, res)
        timed(label, lambda: stock.cut_batch(p0, p1, [tool], zeros, zeros.astype(bool), zeros,
                                             use_numba=use_numba))
    print('셀 수 %d, 스냅샷 1개 %.1f MB' % (stock.cell_count(), stock.snapshot_nbytes() / 1e6))

    verts, faces, colors, edges = timed('화면 메쉬(600) 생성', lambda: stock.display_mesh(600))
    print('  정점 %d, 삼각형 %d, 모서리 선 %d' % (len(verts), len(faces), len(edges) // 2))
    verts, faces, colors, edges = timed('화면 메쉬(300, 안전 모드)', lambda: stock.display_mesh(300))
    print('  정점 %d, 삼각형 %d, 모서리 선 %d' % (len(verts), len(faces), len(edges) // 2))
    verts, faces, _c = timed('STL용 전체 해상도 메쉬', stock.to_mesh)
    print('  정점 %d, 삼각형 %d' % (len(verts), len(faces)))


if __name__ == '__main__':
    main()
