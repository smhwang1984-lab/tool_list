"""bench_nc_sim_gpu.py — G6 성능 측정(pytest 대상 아님). 작업 현장 PC(GTX 1060)에서 돌려 결과를 PLAN 7장에 적는다.

    python tests/bench_nc_sim_gpu.py [선분수=13000] [칸수=4096] [짧은 선분 걸음 mm, 없으면 무작위 긴 선분]

목표: 13k 선분 · 4096 칸 전체 계산 1초 이내. 그래픽 이름·OpenGL 버전·문맥 생성·계산·읽기 시간을 출력한다."""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nc_sim_gpu  # noqa: E402
import nc_sim  # noqa: E402


def make_segments(count, step=None):
    rng = np.random.default_rng(7)
    if step:
        # 실제 가공처럼 짧은 선분(걸음 step mm 이하)이 이어지는 경로
        walk = np.cumsum(rng.uniform(-step, step, size=(count + 1, 2)), axis=0)
        walk = (walk - walk.mean(axis=0)) / max(np.abs(walk).max(), 1e-9) * 45.0
        pts = np.column_stack([walk, rng.uniform(-8, -1, size=count + 1)])
        return pts[:-1], pts[1:]
    xy = rng.uniform(-45, 45, size=(count + 1, 2))
    z = rng.uniform(-8, -1, size=count + 1)
    pts = np.column_stack([xy, z])
    return pts[:-1], pts[1:]


def main(argv):
    count = int(argv[1]) if len(argv) > 1 else 13000
    cells = int(argv[2]) if len(argv) > 2 else 4096
    step = float(argv[3]) if len(argv) > 3 else None
    probe = nc_sim_gpu.gpu_probe(refresh=True)
    print('그래픽:', probe.get('renderer') or '-', '/ 사용 가능:', probe['ok'], probe.get('reason', ''))
    if not probe['ok']:
        return 1
    bounds = {'X': (-50.0, 50.0), 'Y': (-50.0, 50.0), 'Z': (-10.0, 0.0)}
    res = nc_sim_gpu.resolution_for_cells(bounds, cells)
    tool = nc_sim.tool_shape_from_values('FLAT E/M', 6.0)
    p0, p1 = make_segments(count, step)
    slot = np.zeros(count, dtype=np.int32)
    rapid = np.zeros(count, dtype=bool)
    color = np.zeros(count, dtype=np.int16)
    t0 = time.perf_counter()
    stock = nc_sim_gpu.GpuZMapStock(bounds, res)
    t1 = time.perf_counter()
    stock.cut_batch(p0, p1, [tool], slot, rapid, color)
    t2 = time.perf_counter()
    print('격자 %d x %d (셀 %.4f mm), 선분 %d' % (stock.nx, stock.ny, res, count))
    print('소재 만들기 %.2f초 / 전체 절삭 %.2f초 (GPU 사용: %s)' % (t1 - t0, t2 - t1, getattr(stock, 'last_cut_used_gpu', '?')))
    print('목표 1초 이내:', 'OK' if t2 - t1 <= 1.0 else '못 미침')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
