"""nc_sim_gpu.py(GPU 절삭 실행기)가 실제 셰이더로 낸 결과를 CPU 기준 구현과 비교한다 — v2.8.0 G1·G2.

OpenGL 3.3 문맥을 만들 수 없는 환경(moderngl 없음, 드라이버 없음)에서는 건너뛴다.
기준: 칸마다 높이가 공구 가장자리가 아닌 칸은 1e-3mm, 가장자리 칸은 5e-3mm 안에서 같고
(GPU는 float32라 볼·코너 R 끝처럼 가장자리 기울기가 큰 곳에서 반올림이 커진다), 깎인 칸·색 id가 거의 같다."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import numpy as np

import nc_sim
import nc_sim_gpu
import nc_sim_gpu_ref as ref
from test_nc_sim_gpu_ref import BOUNDS, LEVEL_PATHS, RAMP_PATHS, RES, TOOL_KINDS, make_tool

CTX = nc_sim_gpu.create_headless_context()


def arrays(segments):
    p0 = np.array([s[0] for s in segments], dtype=np.float64)
    p1 = np.array([s[1] for s in segments], dtype=np.float64)
    return p0, p1, len(segments)


@unittest.skipIf(CTX is None, 'OpenGL 3.3 문맥을 만들 수 없다(moderngl/드라이버 없음)')
class GpuShaderTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        pass

    def run_both(self, kind, segments, colors=None):
        tool = make_tool(kind)
        p0, p1, n = arrays(segments)
        color = np.arange(n) % 5 if colors is None else np.asarray(colors)
        gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
        self.addCleanup(gpu.release)
        gpu.cut_batch(p0, p1, [tool], np.zeros(n, dtype=int), color)
        cpu_ref = ref.ZMapGpuRef(BOUNDS, RES)
        cpu_ref.cut_batch(p0, p1, [tool], np.zeros(n, dtype=int), np.zeros(n, dtype=bool), color)
        return gpu, cpu_ref

    def test_shaders_compile_and_context_is_gl33(self):
        self.assertTrue(nc_sim_gpu.gpu_available(CTX))

    def test_untouched_stock_is_at_top_with_no_color(self):
        gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
        self.addCleanup(gpu.release)
        np.testing.assert_array_equal(gpu.heights(), np.full((gpu.ny, gpu.nx), np.float32(gpu.ztop)))
        self.assertTrue((gpu.color_ids() == -1).all())

    def test_matches_reference_on_every_tool_and_path(self):
        for kind in TOOL_KINDS:
            for table in (LEVEL_PATHS, RAMP_PATHS):
                for name, segments in table.items():
                    # 내려갔다 올라오는 수직 이동은 같은 공정(같은 색)이다. 두 선분이 같은 높이를 만들어
                    # 어느 쪽이 남는지가 float 반올림에 달려 있어, 색을 다르게 주면 비교가 의미 없다.
                    colors = [2] * len(segments) if name == 'vertical' else None
                    gpu, cref = self.run_both(kind, segments, colors)
                    h = gpu.heights().astype(np.float64)
                    diff = h - cref.heights.astype(np.float64)
                    cut = (cref.heights < cref.ztop - 1e-6) | (h < cref.ztop - 1e-6)
                    inner = cut & ~cref.edge_mask
                    edge = cut & cref.edge_mask
                    label = '%s %s' % (kind, name)
                    self.assertLessEqual(float(np.abs(diff[inner]).max()), 1e-3, label)
                    if edge.any():
                        self.assertLessEqual(float(np.abs(diff[edge]).max()), 5e-3, label)
                    # 색 id: 깎인 칸이 거의 같고(경계의 반올림 몇 칸), 같은 칸이면 같은 선분의 색
                    gc, rc = gpu.color_ids(), cref.color_ids
                    self.assertLessEqual(int(((gc >= 0) != (rc >= 0)).sum()), max(8, int(cut.sum() * 0.001)), label)
                    both = (gc >= 0) & (rc >= 0) & ~cref.edge_mask
                    self.assertLessEqual(int((gc[both] != rc[both]).sum()), max(8, int(both.sum() * 0.001)), label)

    def test_level_moves_match_cpu_engine(self):
        """수평·수직 이동은 실제 CPU 엔진(nc_sim.ZMapStock)과도 가장자리 칸 5e-3, 나머지 1e-3 안에서 같다."""
        for kind in TOOL_KINDS:
            for name, segments in LEVEL_PATHS.items():
                tool = make_tool(kind)
                p0, p1, n = arrays(segments)
                cpu = nc_sim.ZMapStock(BOUNDS, RES)
                cpu.cut_batch(p0, p1, [tool], np.zeros(n, dtype=int), np.zeros(n, dtype=bool),
                              np.zeros(n, dtype=int), use_numba=False)
                gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
                self.addCleanup(gpu.release)
                gpu.cut_batch(p0, p1, [tool], np.zeros(n, dtype=int), np.zeros(n, dtype=int))
                diff = np.abs(gpu.heights().astype(np.float64) - cpu.heights.astype(np.float64))
                self.assertLessEqual(float(diff.max()), 5e-3, '%s %s' % (kind, name))
                self.assertLessEqual(float(np.percentile(diff[diff > 0], 99)) if (diff > 0).any() else 0.0,
                                     1e-3, '%s %s' % (kind, name))

    def test_reset_restores_untouched_stock(self):
        gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
        self.addCleanup(gpu.release)
        gpu.cut_batch([[-5, 0, -2]], [[5, 0, -2]], [make_tool('flat')], [0], [4])
        self.assertLess(float(gpu.heights().min()), gpu.ztop - 1.0)
        self.assertTrue((gpu.color_ids() == 4).any())
        gpu.reset()
        self.assertEqual(float(gpu.heights().min()), gpu.ztop)
        self.assertTrue((gpu.color_ids() == -1).all())

    def test_segments_above_top_or_outside_grid_cut_nothing(self):
        gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
        self.addCleanup(gpu.release)
        gpu.cut_batch([[-5, 0, 1], [100, 100, -3]], [[5, 0, 2], [110, 100, -3]], [make_tool('ball')], [0, 0], [0, 0])
        self.assertEqual(float(gpu.heights().min()), gpu.ztop)

    def test_cut_never_goes_below_stock_bottom(self):
        gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
        self.addCleanup(gpu.release)
        gpu.cut_batch([[-5, 0, -30]], [[5, 0, -30]], [make_tool('flat')], [0], [0])
        self.assertAlmostEqual(float(gpu.heights().min()), BOUNDS['Z'][0], places=5)

    def test_unknown_tool_profile_is_refused(self):
        gpu = nc_sim_gpu.GpuCutter(CTX, BOUNDS, RES)
        self.addCleanup(gpu.release)
        custom = nc_sim.ToolShape(3.0, lambda r: r * 0.0, 20.0)
        with self.assertRaises(ValueError):
            gpu.cut_batch([[0, 0, -1]], [[1, 0, -1]], [custom], [0], [0])

    def test_many_segments_split_into_draws(self):
        """한 번에 보내는 선분 수 상한을 넘겨도 나눠 그려 같은 결과가 나온다."""
        old = nc_sim_gpu.MAX_SEGMENTS_PER_DRAW
        nc_sim_gpu.MAX_SEGMENTS_PER_DRAW = 3
        try:
            gpu, cref = self.run_both('flat', LEVEL_PATHS['zigzag'])
        finally:
            nc_sim_gpu.MAX_SEGMENTS_PER_DRAW = old
        diff = np.abs(gpu.heights().astype(np.float64) - cref.heights.astype(np.float64))
        self.assertLessEqual(float(diff.max()), 1e-3)


class GpuHelpersTests(unittest.TestCase):
    def test_shader_dir_holds_the_shaders(self):
        for name in ('cut.vert', 'cut.frag'):
            self.assertTrue(os.path.exists(os.path.join(nc_sim_gpu.shader_dir(), name)), name)
        self.assertTrue(nc_sim_gpu.shader_source('cut.frag').startswith('#version 330 core'))

    def test_gpu_available_is_false_without_a_context(self):
        self.assertFalse(nc_sim_gpu.gpu_available(None))


if __name__ == '__main__':
    unittest.main()
