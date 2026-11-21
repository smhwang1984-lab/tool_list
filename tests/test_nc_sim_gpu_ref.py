"""nc_sim_gpu_ref.py(GPU 절삭 셰이더의 CPU 기준 구현) 시험 — v2.8.0 G1. Qt 비의존.

기준: 셰이더 상수가 기준 구현과 같고, 연속 선분 훑기가 촘촘한 표본 탐색과 같고,
수평·수직 이동은 지금 CPU 엔진(nc_sim.ZMapStock)과 칸마다 1e-3mm 안에서 같다.
경사 이동은 CPU 엔진이 조각 크기(격자 간격 x SUB_Z)만큼 더 깊게 깎는 것이 알려진 차이다."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import nc_sim as sim
import nc_sim_gpu_ref as ref

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOUNDS = {'X': (-20.0, 20.0), 'Y': (-12.0, 12.0), 'Z': (-10.0, 0.0)}
RES = 0.2
TOL = 1e-3


def make_tool(kind):
    return {
        'flat': lambda: sim.tool_shape_from_values('FLAT E/M', 6.0),
        'ball': lambda: sim.tool_shape_from_values('BALL E/M', 6.0),
        'fillet': lambda: sim.tool_shape_from_values('FILLET E/M', 8.0, r=1.0),
        'drill': lambda: sim.tool_shape_from_values('DRILL', 6.0, sig=118.0),
        'chamfer': lambda: sim.tool_shape_from_values('CHAMFER', 8.0, pl=1.5),
    }[kind]()


TOOL_KINDS = ('flat', 'ball', 'fillet', 'drill', 'chamfer')

LEVEL_PATHS = {
    'horizontal': [((-12, -3, -4), (12, -3, -4)), ((12, 3, -4), (-12, 3, -4))],
    'vertical': [((0, 0, 0), (0, 0, -6)), ((0, 0, -6), (0, 0, 0))],
    'zigzag': [((-12, -6 + 2 * k, -3 - 0.5 * (k % 2)), (12, -6 + 2 * k, -3 - 0.5 * (k % 2)))
               for k in range(6)],
}
RAMP_PATHS = {
    'gentle': [((-12, 0, -1), (12, 0, -3))],
    'steep': [((-10, 0, -0.5), (10, 0, -7))],
    'diagonal': [((-12, -8, -1), (12, 8, -6))],
}


def cut_both(kind, segments):
    tool = make_tool(kind)
    p0 = np.array([s[0] for s in segments], dtype=np.float64)
    p1 = np.array([s[1] for s in segments], dtype=np.float64)
    n = len(segments)
    args = ([tool], np.zeros(n, dtype=int), np.zeros(n, dtype=bool), np.zeros(n, dtype=int))
    cpu = sim.ZMapStock(BOUNDS, RES)
    cpu.cut_batch(p0, p1, *args, use_numba=False)
    gpu = ref.ZMapGpuRef(BOUNDS, RES)
    gpu.cut_batch(p0, p1, *args)
    diff = gpu.heights.astype(np.float64) - cpu.heights.astype(np.float64)
    cut = (gpu.heights < gpu.ztop - 1e-6) | (cpu.heights < cpu.ztop - 1e-6)
    return cpu, gpu, diff, cut


class ShaderSourceTests(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(ROOT, 'sim_shaders', name), encoding='utf-8') as handle:
            return handle.read()

    def test_shader_constants_match_reference(self):
        frag = self._read('cut.frag')
        self.assertEqual(int(re.search(r'const int GOLD_ITER = (\d+);', frag).group(1)), ref.GOLD_ITER)
        self.assertEqual(float(re.search(r'const float INV_PHI = ([\d.]+);', frag).group(1)), ref.INV_PHI)
        self.assertEqual(float(re.search(r'const float R2_EPS = ([\d.e+-]+);', frag).group(1)), ref.R2_EPS)
        self.assertEqual(float(re.search(r'const float R2_REL_EPS = ([\d.e+-]+);', frag).group(1)),
                         ref.R2_REL_EPS)
        self.assertEqual(float(re.search(r'const float VERTICAL_LEN2 = ([\d.e+-]+);', frag).group(1)),
                         ref.VERTICAL_LEN2)

    def test_shader_files_carry_no_version_line(self):
        # 버전·정밀도 줄은 로더가 붙인다(데스크톱 330 core / 웹 300 es) — 파일 맨 앞에 두면 두 앱이 못 쓴다.
        for name in ('cut.vert', 'cut.frag'):
            for line in self._read(name).splitlines():
                self.assertFalse(line.strip().startswith(('#version', 'precision')), (name, line))

    def test_profile_kind_numbers_match_shader(self):
        # cut.frag 가 가르는 종류 번호(1 코너 R, 2 원뿔, 3 챔퍼)는 nc_sim.PROFILE_* 와 같아야 한다.
        frag = self._read('cut.frag')
        for number, const in ((1, sim.PROFILE_CORNER), (2, sim.PROFILE_CONE), (3, sim.PROFILE_CHAMFER)):
            self.assertEqual(number, const)
            self.assertIn('kind == %d' % number, frag)
        self.assertEqual(sim.PROFILE_FLAT, 0)


class ProfileParamsTests(unittest.TestCase):
    def test_profile_h_matches_cpu_tool_profile(self):
        for kind in TOOL_KINDS:
            tool = make_tool(kind)
            d = np.linspace(0.0, tool.radius, 401)
            expected = tool.height_grid(d)
            actual = ref.profile_h(d, tool.profile_params())
            np.testing.assert_allclose(actual, expected, atol=1e-12, err_msg=kind)

    def test_zero_corner_r_is_flat(self):
        tool = sim.tool_shape_from_values('FILLET E/M', 8.0, r=0.0)
        self.assertEqual(tool.profile_params()[0], sim.PROFILE_FLAT)

    def test_ball_is_corner_r_equal_to_radius(self):
        kind, flat_r, corner_r, _ = make_tool('ball').profile_params()
        self.assertEqual((kind, flat_r, corner_r), (sim.PROFILE_CORNER, 0.0, 3.0))

    def test_custom_profile_has_no_params(self):
        tool = sim.ToolShape(3.0, lambda r: r * 0.0, 20.0)
        self.assertIsNone(tool.profile_params())
        stock = ref.ZMapGpuRef(BOUNDS, RES)
        with self.assertRaises(ValueError):
            stock.cut_batch([[0, 0, -1]], [[1, 0, -1]], [tool], [0], [False], [0])


class SweepTests(unittest.TestCase):
    def test_sweep_matches_dense_sampling(self):
        """연속 최소화(황금분할 + 끝점)가 t를 4만 번 훑은 값과 같다 — 경사·볼·코너 R 모두."""
        rng = np.random.default_rng(7)
        ts = np.linspace(0.0, 1.0, 40001)
        for kind in TOOL_KINDS:
            tool = make_tool(kind)
            params = tool.profile_params()
            for _ in range(6):
                a = rng.uniform(-8, 8, 2)
                b = rng.uniform(-8, 8, 2)
                az, bz = rng.uniform(-6, 0, 2)
                cells = a + (b - a) * rng.uniform(0, 1, (40, 1)) + rng.uniform(-1.3 * tool.radius, 1.3 * tool.radius, (40, 2))
                qx, qy = cells[:, 0] - a[0], cells[:, 1] - a[1]
                got = ref.sweep_min_height(qx, qy, b[0] - a[0], b[1] - a[1], az, bz - az, tool.radius, params)
                for k in range(cells.shape[0]):
                    wx = qx[k] - ts * (b[0] - a[0])
                    wy = qy[k] - ts * (b[1] - a[1])
                    d = np.sqrt(wx * wx + wy * wy)
                    inside = d * d <= tool.radius ** 2 * (1.0 + ref.R2_REL_EPS) + ref.R2_EPS
                    if not inside.any():
                        self.assertTrue(np.isinf(got[k]), (kind, k))
                        continue
                    brute = (az + (bz - az) * ts + ref.profile_h(d, params))[inside].min()
                    # 표본보다 거의 나쁘지 않다: 챔퍼·원뿔처럼 꺾이는 형상은 황금분할 24회가 구간의
                    # 0.618^24(약 1e-5)까지만 좁혀서 최대 2r*1e-5*기울기(반지름 3~4mm에서 1e-4 미만)만큼 높다.
                    self.assertLessEqual(got[k], brute + 1e-4, (kind, k))
                    self.assertLess(brute - got[k], 2e-3, (kind, k))          # 표본 간격 안에서 같다

    def test_far_cells_are_untouched(self):
        out = ref.sweep_min_height(np.array([50.0]), np.array([0.0]), 10.0, 0.0, -1.0, 0.0, 3.0,
                                   make_tool('flat').profile_params())
        self.assertTrue(np.isinf(out[0]))


class AgainstCpuEngineTests(unittest.TestCase):
    def test_level_and_vertical_moves_match_cpu_engine_on_every_cell(self):
        """G1 완료 기준: 수평·수직 이동은 공구 가장자리 칸까지 포함해 모든 칸이 1e-3mm 안에서 같다."""
        for kind in TOOL_KINDS:
            for name, segments in LEVEL_PATHS.items():
                _, _, diff, cut = cut_both(kind, segments)
                self.assertGreater(int(cut.sum()), 500, (kind, name))
                self.assertLessEqual(float(np.abs(diff[cut]).max()), TOL, (kind, name))

    def test_cut_cells_and_colors_match_on_level_moves(self):
        for kind in TOOL_KINDS:
            cpu, gpu, _, _ = cut_both(kind, LEVEL_PATHS['zigzag'])
            np.testing.assert_array_equal(cpu.color_ids < 0, gpu.color_ids < 0, err_msg=kind)

    def test_sloped_moves_differ_only_by_cpu_piece_overcut(self):
        """경사 이동: 기준 구현이 정확하고, CPU는 조각(격자 간격 x SUB_Z)만큼 같거나 더 깊게 깎는다."""
        limit = RES * sim.SUB_Z + TOL
        for kind in TOOL_KINDS:
            for name, segments in RAMP_PATHS.items():
                _, gpu, diff, cut = cut_both(kind, segments)
                inner = cut & ~gpu.edge_mask
                edge = cut & gpu.edge_mask
                # 안쪽 칸: CPU가 기준보다 높지 않고(1e-3), 더 깊은 정도는 조각 크기(격자 간격 x SUB_Z) 이하
                self.assertGreaterEqual(float(diff[inner].min()), -TOL, (kind, name))
                self.assertLessEqual(float(diff[inner].max()), limit, (kind, name))
                # 공구 가장자리 칸: CPU의 반경 표(LUT) 보간 오차가 더해진다(볼·코너 R 끝은 가장자리 기울기가 커서
                # 수 마이크로미터~). 위쪽 한계는 같고 아래쪽만 넉넉히 둔다.
                if edge.any():
                    self.assertGreaterEqual(float(diff[edge].min()), -0.02, (kind, name))
                    self.assertLessEqual(float(diff[edge].max()), limit, (kind, name))

    def test_flat_tool_interior_is_exact_even_on_ramps(self):
        # 평바닥이 경사를 훑을 때 바깥 가장자리가 아닌 칸은 CPU도 정확하다(최솟값이 선분 끝점).
        cpu, gpu, diff, cut = cut_both('flat', RAMP_PATHS['gentle'])
        interior = cut & ~gpu.edge_mask
        self.assertGreater(int(interior.sum()), 500)
        self.assertLessEqual(float(np.abs(diff[interior]).max()), TOL)

    def test_color_id_follows_the_lowering_segment(self):
        tool = make_tool('flat')
        stock = ref.ZMapGpuRef(BOUNDS, RES)
        stock.cut_batch([[-5, 0, -2], [-5, 4, -4]], [[5, 0, -2], [5, 4, -4]], [tool], [0, 0],
                        [False, False], [3, 7])
        i = int(round((0 - stock.x0) / RES))
        self.assertEqual(int(stock.color_ids[int(round((0 - stock.y0) / RES)), i]), 3)
        self.assertEqual(int(stock.color_ids[int(round((4 - stock.y0) / RES)), i]), 7)
        self.assertEqual(int(stock.color_ids[int(round((-11 - stock.y0) / RES)), i]), -1)

    def test_rapid_cut_is_recorded_like_cpu_engine(self):
        tool = make_tool('flat')
        stock = ref.ZMapGpuRef(BOUNDS, RES)
        stock.cut_batch([[-5, 0, -2]], [[5, 0, -2]], [tool], [0], [True], [0], src_lines=[11], seqs=[4])
        self.assertEqual(stock.rapid_cut_warnings, [(11, 4)])

    def test_segment_above_stock_top_cuts_nothing(self):
        stock = ref.ZMapGpuRef(BOUNDS, RES)
        stock.cut_batch([[-5, 0, 1]], [[5, 0, 2]], [make_tool('ball')], [0], [False], [0])
        self.assertFalse(stock.any_cut())

    def test_cut_never_goes_below_stock_bottom(self):
        stock = ref.ZMapGpuRef(BOUNDS, RES)
        stock.cut_batch([[-5, 0, -30]], [[5, 0, -30]], [make_tool('flat')], [0], [False], [0])
        self.assertAlmostEqual(float(stock.heights.min()), BOUNDS['Z'][0], places=6)


if __name__ == '__main__':
    unittest.main()
