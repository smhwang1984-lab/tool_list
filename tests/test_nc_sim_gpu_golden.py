"""G5: GPU 기준 구현 골든 — 안드로이드 `tool_list_android/tests/golden/zmap/*__gpuref.*` 와 비교한다.

골든은 `tools/golden/export_zmap.py` 가 이 앱의 `nc_sim_gpu_ref.ZMapGpuRef` 로 뽑는다. 같은 NC 파일을 같은 경로로
읽어 (1) 기준 구현이 골든과 같고, (2) OpenGL 3.3 문맥이 있으면 실제 셰이더(`GpuZMapStock`)도 골든과 가깝다.
안드로이드 쪽 `tests/zmapGpuRef.test.ts` 가 같은 골든을 TypeScript 기준 구현과 비교하므로, 두 앱이 같은 결과를 낸다."""
import gzip
import json
import os
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np

GOLD = os.path.join(ROOT, 'tool_list_android', 'tests', 'golden', 'zmap')
FIXTURES = os.path.join(ROOT, 'tool_list_android', 'tests', 'fixtures')
M3 = '3축 MCT (X Y Z)'
TYPES = ['FLAT E/M', 'BALL E/M', 'FILLET E/M', 'DRILL', 'CHAMFER MILL']

try:
    from PyQt5.QtWidgets import QApplication
    import nc_sim
    import nc_sim_gpu
    import nc_sim_gpu_ref
    import nc_viewer_widget as nv
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    IMPORT_ERROR = exc

GOLDENS = sorted(f for f in os.listdir(GOLD) if f.endswith('__gpuref.json')) if os.path.isdir(GOLD) else []


def fake_shape_map():
    out = {}
    for n in range(1, 100):
        values = {'type': TYPES[n % 5], 'D': float(6 + n % 5), 'FL': float(20 + n % 7), 'R': 1.0 if n % 5 == 2 else None,
                  'SIG': 118.0 if n % 5 == 3 else None, 'PL': 0.5 if n % 5 == 4 else None, 'SO': None}
        for key in ('T%02d' % n, 'T%d' % n, str(n)):
            out[key] = values
    return out


def load_case(json_name):
    meta = json.load(open(os.path.join(GOLD, json_name), encoding='utf-8'))
    raw = gzip.open(os.path.join(GOLD, json_name.replace('.json', '.bin.gz'))).read()
    cells = meta['nx'] * meta['ny']
    heights = np.frombuffer(raw, '<f4', cells).reshape(meta['ny'], meta['nx'])
    colors = np.frombuffer(raw, '<i2', cells, cells * 4).reshape(meta['ny'], meta['nx'])
    edge = np.frombuffer(raw, 'u1', cells, cells * 6).reshape(meta['ny'], meta['nx']).astype(bool)
    return meta, heights, colors, edge


@unittest.skipIf(IMPORT_ERROR is not None, 'PyQt5/모듈을 불러올 수 없다: %s' % (IMPORT_ERROR,))
@unittest.skipUnless(GOLDENS, '__gpuref 골든이 없다(export_zmap.py 를 먼저 실행)')
class GpuGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.viewer = nv.NCViewerWidget()

    def segments(self, meta):
        raw = open(os.path.join(FIXTURES, meta['file']), 'rb').read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp949', errors='replace')
        v = self.viewer
        v.current_machine_type = M3
        v.last_render_signature = None
        v.process_nc_lines(text.splitlines()[:700])
        v.tool_shape_map = fake_shape_map()
        v._rebuild_sim_nodes()
        seg = v.sim_seg
        self.assertEqual(v.sim_engine, 'zmap')
        keep = ~seg['tilt']
        bounds = v.toolpath_bounds(margin=2.0)
        args = (seg['p0'][keep], seg['p1'][keep], v._sim_tools, seg['slot'][keep], seg['rapid'][keep], seg['color'][keep])
        kw = dict(src_lines=seg['src'][keep], seqs=seg['seq1'][keep])
        return bounds, args, kw

    def test_reference_matches_golden(self):
        """Python 기준 구현이 골든(같은 식으로 뽑은 값)과 칸마다 같다."""
        for name in GOLDENS:
            with self.subTest(name):
                meta, gh, gc, ge = load_case(name)
                bounds, args, kw = self.segments(meta)
                stock = nc_sim_gpu_ref.ZMapGpuRef(bounds, meta['resolution'])
                self.assertEqual((stock.nx, stock.ny), (meta['nx'], meta['ny']))
                stock.cut_batch(*args, **kw)
                self.assertLessEqual(float(np.abs(stock.heights - gh).max()), 1e-6)
                self.assertTrue(np.array_equal(stock.color_ids, gc))
                self.assertTrue(np.array_equal(stock.edge_mask, ge))
                self.assertEqual([list(w) for w in stock.rapid_cut_warnings], meta['rapid_warnings'])
                self.assertEqual(bool(stock.any_cut()), meta['cut'])

    def test_real_shader_close_to_golden(self):
        """실제 셰이더(ModernGL)가 골든과 가깝다 — 안쪽 칸 1e-3mm, 공구 가장자리 칸 5e-3mm, 깎인 칸·색 id 거의 같음."""
        ctx = nc_sim_gpu.create_headless_context()
        if ctx is None:
            self.skipTest('OpenGL 3.3 문맥을 만들 수 없다')
        ctx.release()
        for name in GOLDENS:
            with self.subTest(name):
                meta, gh, gc, ge = load_case(name)
                bounds, args, kw = self.segments(meta)
                stock = nc_sim_gpu.GpuZMapStock(bounds, meta['resolution'])
                stock.cut_batch(*args, **kw)
                top = np.float32(stock.ztop)
                cut = (gh < top - 1e-6) | (stock.heights < top - 1e-6)
                diff = np.abs(stock.heights.astype(np.float64) - gh)
                self.assertLessEqual(float(diff[cut & ~ge].max(initial=0)), 1e-3)
                # 칸 중심이 공구 반지름 위에 정확히 놓인 칸(정수 격자에서 흔함)은 float64 기준 구현과 float32 셰이더가
                # 깎음/안 깎음으로 갈릴 수 있다 — 가장자리 칸의 2% 이하만 허용하고, 나머지 가장자리 칸은 5e-3mm 안
                edge_cut = cut & ge
                tie = edge_cut & (diff > 5e-3)
                self.assertLessEqual(int(tie.sum()), max(2, int(edge_cut.sum() * 0.02)))
                both = cut & ~ge & ~tie
                self.assertLessEqual(int((stock.color_ids[both] != gc[both]).sum()), max(2, int(both.sum() * 2e-3)))


if __name__ == '__main__':
    unittest.main()
