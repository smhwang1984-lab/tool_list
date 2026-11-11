# -*- coding: utf-8 -*-
"""P6 마무리: 원본 LatheStock / TurnMillStock 절삭 결과를 골든으로 남긴다.

선반 NC 마다 가상 공구 형상(공구 번호로 종류를 정함)·고정 소재(지름 100, 길이 120)를 주고
tests/golden/lathe/<파일>.json(+ .bin.gz: 선삭 격자 occ(uint8)+col(uint8), 턴밀이면 복셀 occ+col)에 쓴다.
원본은 고치지 않는다.

실행: nc_build_venv 의 python 으로 tools/golden/export_lathe.py ../tool_list
"""
import gzip
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / 'tests' / 'golden' / 'lathe'
FIXTURES = ROOT / 'tests' / 'fixtures'
MAX_LINES = 900
RES = 0.25
VOXEL_RES = 1.0
LATHE = 'CNC 선반 (턴밀 포함)'
FILES = ['O1699.nc', 'O2222.nc', 'O3210_excerpt.nc', 'O4006.nc', 'O4811.nc', 'O4812.nc', 'TurnMill_Test.nc', 'sub_pg_test.nc']
SPEC = {'diameter': 100.0, 'length': 120.0, 'front_z': 5.0, 'bore': 0.0}


def fake_geometry():
    """T1~T99 → 가상 선반 공구 형상 (tests/latheGolden.test.ts 와 같은 식)."""
    out = {}
    for n in range(1, 100):
        base = {'kind': '', 'hand': 'R', 'tip': 3, 'diameter': None, 'so': None, 'mill_type': None, 'chamfer_angle': None,
                'nose_r': 0.4, 'width': None, 'pitch': None, 'shape': 'C', 'tip_angle': 80.0, 'clearance_angle': None,
                'ic': 12.7, 'edge_length': 12.0, 'thickness': 4.76, 'thread_angle': None, 'approach_angle': 95.0, 'shank': None}
        k = n % 7
        if k == 0:
            base.update(kind='외경')
        elif k == 1:
            base.update(kind='내경', tip=4)
        elif k == 2:
            base.update(kind='외경홈', width=3.0, nose_r=0.2, shape=None, tip_angle=None)
        elif k == 3:
            base.update(kind='외경나사', thread_angle=60.0, pitch=1.5, shape='T', tip_angle=60.0, nose_r=0.1)
        elif k == 4:
            base.update(kind='드릴', diameter=8.0, so=40.0, mill_type='DRILL', shape=None)
        elif k == 5:
            base.update(kind='엔드밀', diameter=10.0, so=30.0, mill_type='FLAT E/M', shape=None, nose_r=None)
        else:
            base.update(kind='외경', tip=3, nose_r=0.8)
        for key in ('T%02d' % n, 'T%d' % n, str(n)):
            out[key] = base
    return out


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
    import nc_lathe_sim
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
        viewer.current_machine_type = LATHE
        viewer.last_render_signature = None
        viewer.process_nc_lines(lines)
        viewer.tool_shape_map = fake_geometry()
        viewer._rebuild_sim_nodes()
        seg = viewer.sim_seg
        if seg is None:
            print('경로 없음', name)
            continue
        spec = nc_lathe_sim.LatheStockSpec(**SPEC)
        bounds = spec.bounds()
        turnmill = viewer.sim_engine == 'lathe3d'
        stock = nc_lathe_sim.TurnMillStock(bounds, RES, VOXEL_RES) if turnmill else nc_lathe_sim.LatheStock(bounds, RES)
        extra = {'thread_pitch': seg['thread_pitch'], 'thread_height': seg['thread_height']}
        if turnmill:
            extra.update(mill=seg['mill'], axes0=seg['axis0'], axes1=seg['axis1'])
        stock.cut_batch(seg['p0'], seg['p1'], viewer._sim_tools, seg['slot'], seg['rapid'], seg['color'],
                        src_lines=seg['src'], seqs=seg['seq1'], use_numba=False, **extra)
        lat = stock.lathe if turnmill else stock
        meta = {'file': name, 'engine': viewer.sim_engine, 'spec': SPEC, 'resolution': RES, 'voxel_resolution': VOXEL_RES,
                'nz': lat.nz, 'nr': lat.nr, 'segments': int(len(seg['seq1'])), 'thread_cut_count': int(lat.thread_cut_count),
                'rapid_warnings': [[int(a), int(b)] for a, b in stock.rapid_cut_warnings],
                'removed': int((lat._occ0 != lat.occ).sum()), 'turnmill': turnmill}
        payload = lat.occ.tobytes() + lat.col.tobytes()
        if turnmill:
            stock.sync() if hasattr(stock, 'sync') else None
            vox = stock.voxel
            meta['voxel_shape'] = [vox.nx, vox.ny, vox.nz]
            meta['voxel_removed'] = int(vox.occ.size - int(vox.occ.sum()))
            payload += vox.occ.tobytes() + vox.col.tobytes()
        stem = Path(name).stem
        (OUT / (stem + '.json')).write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        with gzip.open(OUT / (stem + '.bin.gz'), 'wb', compresslevel=9) as f:
            f.write(payload)
        print(name, meta['engine'], 'segs', meta['segments'], 'removed', meta['removed'], 'thread', meta['thread_cut_count'],
              'vox', meta.get('voxel_removed'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
