# -*- coding: utf-8 -*-
"""P6-T2: 원본 ZMapStock 절삭 결과(높이맵·색 id)를 골든으로 남긴다.

NC 파일마다 가상의 공구표(공구 번호로 종류·지름을 정함)를 주고, 툴패스 범위 + 여유 2mm 의 소재를
해상도 0.5mm 로 깎아 tests/golden/zmap/<파일>.json(+ .bin.gz: float32 높이 + int16 색)에 쓴다.
경사 공구축 구간은 3D 소재(P6-T3) 몫이라 뺀다. 원본은 고치지 않는다.

실행: ..\\..\\nc_build_venv\\Scripts\\python.exe tools\\golden\\export_zmap.py ..  (tool_list_android 폴더에서 실행, 원본 = 상위 폴더 tool_list)
"""
import gzip
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / 'tests' / 'golden' / 'zmap'
FIXTURES = ROOT / 'tests' / 'fixtures'
MAX_LINES = 700
RES = 0.5
MARGIN = 2.0
M3 = '3축 MCT (X Y Z)'
FILES = ['zmap3_plain.nc', '5ax_A_To_C.nc', 'O3210_excerpt.nc', 'ncdata.nc', 'sub_pg_test.nc', 'O4811.nc', 'O4812.nc', 'O1699.nc']
TYPES = ['FLAT E/M', 'BALL E/M', 'FILLET E/M', 'DRILL', 'CHAMFER MILL']


def fake_shape_map():
    """T1~T99 → 가상 공구 값 (tests/zmap.test.ts 와 같은 식)."""
    out = {}
    for n in range(1, 100):
        values = {'type': TYPES[n % 5], 'D': float(6 + n % 5), 'FL': float(20 + n % 7), 'R': 1.0 if n % 5 == 2 else None,
                  'SIG': 118.0 if n % 5 == 3 else None, 'PL': 0.5 if n % 5 == 4 else None, 'SO': None}
        for key in ('T%02d' % n, 'T%d' % n, str(n)):
            out[key] = values
    return out


def nc_sim_clean(value):
    import json as _j
    return _j.loads(_j.dumps(value, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o)))


def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if len(argv) < 2:
        print(__doc__)
        return 2
    source = Path(argv[1]).resolve()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
    sys.path.insert(0, str(source))
    os.chdir(source)
    import numpy as np
    from PyQt5.QtWidgets import QApplication
    import nc_sim
    import nc_viewer_widget as nv
    app = QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('*'):
        old.unlink()
    for name in FILES:
        raw = (FIXTURES / name).read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp949', errors='replace')
        lines = text.splitlines()[:MAX_LINES]
        viewer.current_machine_type = M3
        viewer.last_render_signature = None
        viewer.process_nc_lines(lines)
        viewer.tool_shape_map = fake_shape_map()
        viewer._rebuild_sim_nodes()
        seg = viewer.sim_seg
        if seg is None:
            print('경로 없음', name)
            continue
        # v2.5.9: 3축 설정이어도 G43.4/G68.2 + 회전축이 있으면 5축으로 읽어 3D 엔진을 쓴다 — Z-map 골든은 Z-map 엔진 파일만
        if viewer.sim_engine != 'zmap':
            print('3D 엔진 — Z-map 골든 제외', name)
            continue
        bounds = viewer.toolpath_bounds(margin=MARGIN)
        keep = ~seg['tilt']
        stock = nc_sim.ZMapStock(bounds, RES)
        stock.cut_batch(seg['p0'][keep], seg['p1'][keep], viewer._sim_tools, seg['slot'][keep], seg['rapid'][keep],
                        seg['color'][keep], src_lines=seg['src'][keep], seqs=seg['seq1'][keep], use_numba=False)
        meta = {
            'file': name, 'bounds': {k: list(v) for k, v in bounds.items()}, 'resolution': RES,
            'nx': stock.nx, 'ny': stock.ny, 'segments': int(keep.sum()), 'tilted': int((~keep).sum()),
            'cut': bool(stock.any_cut()), 'rapid_warnings': [[a, b] for a, b in stock.rapid_cut_warnings],
        }
        stem = Path(name).stem
        (OUT / (stem + '.json')).write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        with gzip.open(OUT / (stem + '.bin.gz'), 'wb', compresslevel=9) as f:
            f.write(stock.heights.astype('<f4').tobytes())
            f.write(stock.color_ids.astype('<i2').tobytes())
        print(name, 'cells', stock.nx * stock.ny, 'segs', meta['segments'], 'tilted', meta['tilted'], 'cut', meta['cut'])
    # ---- P6-T3: 3D 복셀 (공구 축이 기운 이동) ----
    import nc_sim3d
    M5A = '5축 MCT (A to C)'
    for name, machine, limit, vres in [('5ax_A_To_C.nc', M5A, 100000, 0.5)]:
        raw = (FIXTURES / name).read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp949', errors='replace')
        lines = text.splitlines()[:MAX_LINES]
        viewer.current_machine_type = machine
        viewer.last_render_signature = None
        viewer.process_nc_lines(lines)
        viewer.tool_shape_map = fake_shape_map()
        viewer._rebuild_sim_nodes()
        seg = viewer.sim_seg
        bounds = viewer.toolpath_bounds(margin=MARGIN)
        n = min(limit, len(seg['seq1']))
        stock = nc_sim3d.VoxelStock(bounds, vres)
        stock.cut_batch(seg['p0'][:n], seg['p1'][:n], viewer._sim_tools, seg['slot'][:n], seg['rapid'][:n],
                        seg['color'][:n], src_lines=seg['src'][:n], seqs=seg['seq1'][:n], use_numba=False,
                        axes0=seg['axis0'][:n], axes1=seg['axis1'][:n])
        meta = {'file': name, 'machine': machine, 'specs': nc_sim_clean(viewer.machine_specs.get(machine, {})),
                'bounds': {k: list(v) for k, v in bounds.items()}, 'resolution': vres, 'limit': n,
                'shape': [stock.nx, stock.ny, stock.nz], 'engine': viewer.sim_engine,
                'removed': int(stock.occ.size - int(stock.occ.sum())), 'rapid_warnings': [[a, b] for a, b in stock.rapid_cut_warnings]}
        stem = Path(name).stem + '__voxel'
        (OUT / (stem + '.json')).write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        with gzip.open(OUT / (stem + '.bin.gz'), 'wb', compresslevel=9) as f:
            f.write(stock.occ.tobytes())
            f.write(stock.col.tobytes())
        print(name, 'voxel', meta['shape'], 'removed', meta['removed'], 'engine', meta['engine'])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
