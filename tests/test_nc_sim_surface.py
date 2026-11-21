"""nc_sim_surface.py(GPU 소재 표시)를 독립 OpenGL 문맥에 그려 화면 색을 확인한다 — v2.8.0 G3.
OpenGL 3.3 문맥이 없는 환경에서는 건너뛴다."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np

import nc_sim
import nc_sim_gpu
import nc_sim_surface as surf

CTX = nc_sim_gpu.create_headless_context()
BOUNDS = {'X': (-10.0, 10.0), 'Y': (-10.0, 10.0), 'Z': (-8.0, 0.0)}
RES = 0.25
SIZE = 160
LIGHT_Z = 0.8221            # 위에서 볼 때 평평한 면의 음영 = 0.5 + 0.5 * dot((0,0,1), LIGHT)
TOP_SHADE = 0.5 + 0.5 * LIGHT_Z


def ortho_top_down():
    """위에서 아래로 보는 정사영: x,y ∈ [-11, 11] → 화면, z가 클수록 가깝다."""
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = m[1, 1] = 1.0 / 11.0
    m[2, 2] = -1.0 / 20.0
    m[3, 3] = 1.0
    return np.ascontiguousarray(m.T)            # 열 우선(QMatrix4x4.data() 순서)


def tilted_view():
    """x축 둘레로 기울여 옆면이 보이게 한다(정사영)."""
    c, s = np.cos(np.radians(55)), np.sin(np.radians(55))
    rot = np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], dtype=np.float32)
    proj = np.zeros((4, 4), dtype=np.float32)
    proj[0, 0] = proj[1, 1] = 1.0 / 16.0
    proj[2, 2] = -1.0 / 40.0
    proj[3, 3] = 1.0
    return np.ascontiguousarray((proj @ rot).T), np.ascontiguousarray(rot.T)


@unittest.skipIf(CTX is None, 'OpenGL 3.3 문맥을 만들 수 없다(moderngl/드라이버 없음)')
class SurfaceRenderTests(unittest.TestCase):
    def setUp(self):
        CTX.__enter__()          # 다른 시험이 만든 임시 문맥 때문에 풀린 '현재 문맥'을 되돌린다
        self.stock = nc_sim.ZMapStock(BOUNDS, RES)
        tool = nc_sim.tool_shape_from_values('FLAT E/M', 4.0)
        # 가운데 y=0 줄을 z=-3까지 파낸다(공정 색 id 2)
        self.stock.cut_batch([[-6, 0, -3]], [[6, 0, -3]], [tool], [0], [False], [2], use_numba=False)
        self.renderer = surf.SurfaceRenderer(CTX)
        self.addCleanup(self.renderer.release)
        self.fbo = CTX.framebuffer(CTX.renderbuffer((SIZE, SIZE)), CTX.depth_renderbuffer((SIZE, SIZE)))
        self.addCleanup(self.fbo.release)
        xs, ys = self.stock.grid_x(), self.stock.grid_y()
        palette = surf.build_palette({0: (1, 0, 0, 1), 1: (0, 1, 0, 1), 2: (0.2, 0.4, 0.9, 1.0)})
        self.renderer.set_data(xs, ys, self.stock.heights, self.stock.color_ids, palette, self.stock.zlo, self.stock.ztop)

    def render(self, mvp, mv, mode):
        self.fbo.use()
        CTX.viewport = (0, 0, SIZE, SIZE)
        CTX.enable(CTX.DEPTH_TEST)
        self.fbo.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        self.renderer.draw(mvp, mv, mode)
        CTX.finish()
        img = np.frombuffer(self.fbo.read(components=3), dtype=np.uint8).reshape(SIZE, SIZE, 3) / 255.0
        return img

    def pixel(self, img, x, y):
        """월드 (x, y) → 화면 화소(위에서 본 정사영)."""
        px = int((x / 11.0 * 0.5 + 0.5) * SIZE)
        py = int((y / 11.0 * 0.5 + 0.5) * SIZE)
        return img[py, px]

    def test_tool_color_mode_paints_cut_cells_with_their_process_color(self):
        img = self.render(ortho_top_down(), np.eye(4, dtype=np.float32), surf.MODE_TOOL)
        cut = self.pixel(img, 0.0, 0.0)
        np.testing.assert_allclose(cut, np.array([0.2, 0.4, 0.9]) * TOP_SHADE, atol=0.02)
        raw = self.pixel(img, 8.0, 8.0)
        np.testing.assert_allclose(raw, np.array(nc_sim.DEFAULT_STOCK_COLOR[:3]) * TOP_SHADE, atol=0.02)

    def test_solid_mode_ignores_process_colors(self):
        img = self.render(ortho_top_down(), np.eye(4, dtype=np.float32), surf.MODE_SOLID)
        np.testing.assert_allclose(self.pixel(img, 0.0, 0.0), np.array(nc_sim.DEFAULT_STOCK_COLOR[:3]) * TOP_SHADE, atol=0.02)

    def test_depth_mode_colors_by_cut_depth(self):
        img = self.render(ortho_top_down(), np.eye(4, dtype=np.float32), surf.MODE_DEPTH)
        shallow = self.pixel(img, 8.0, 8.0)             # 안 깎임 = 깊이 0 → 첫 색(노랑)
        np.testing.assert_allclose(shallow, np.array(nc_sim.DEPTH_COLOR_STOPS[0]) * TOP_SHADE, atol=0.02)
        deep = self.pixel(img, 0.0, 0.0)                # 3mm / 8mm
        t = 3.0 / 8.0 * 2.0
        expect = np.array(nc_sim.DEPTH_COLOR_STOPS[0]) * (1 - t) + np.array(nc_sim.DEPTH_COLOR_STOPS[1]) * t
        np.testing.assert_allclose(deep, expect * TOP_SHADE, atol=0.03)

    def test_cut_floor_is_lit_like_a_flat_face_and_groove_walls_are_darker(self):
        img = self.render(ortho_top_down(), np.eye(4, dtype=np.float32), surf.MODE_SOLID)
        floor = self.pixel(img, 0.0, 0.0).mean()
        top = self.pixel(img, 8.0, 8.0).mean()
        self.assertAlmostEqual(floor, top, delta=0.03)           # 같은 기본색, 같은 평면 음영
        # 홈 벽(y = ±2 근처)은 기울어져 있어 평면과 다르게 칠해진다
        wall = img[int((2.0 / 11.0 * 0.5 + 0.5) * SIZE)]
        self.assertGreater(float(np.abs(wall.mean(axis=1) - top).max()), 0.03)

    def test_side_walls_are_drawn_when_viewed_from_an_angle(self):
        mvp, mv = tilted_view()
        img = self.render(mvp, mv, surf.MODE_SOLID)
        side_color = np.array(nc_sim.DEFAULT_STOCK_COLOR[:3]) * 0.62
        close = np.all(np.abs(img - side_color) < 0.02, axis=2)
        self.assertGreater(int(close.sum()), SIZE)               # 옆면이 한 줄 이상 보인다

    def test_nothing_is_drawn_outside_the_stock(self):
        img = self.render(ortho_top_down(), np.eye(4, dtype=np.float32), surf.MODE_TOOL)
        np.testing.assert_allclose(self.pixel(img, 10.7, 10.7), [0, 0, 0], atol=0.01)

    def test_reduced_display_grid_still_draws(self):
        xs, ys, Z, C = self.stock.display_grid(20)
        self.assertLess(len(xs), self.stock.nx)
        self.renderer.set_data(xs, ys, Z, C, surf.build_palette({2: (0.2, 0.4, 0.9, 1.0)}), self.stock.zlo, self.stock.ztop)
        img = self.render(ortho_top_down(), np.eye(4, dtype=np.float32), surf.MODE_TOOL)
        self.assertGreater(float(self.pixel(img, 0.0, 0.0).sum()), 0.1)

    def test_palette_helper(self):
        pal = surf.build_palette({0: (1, 0, 0, 1), 3: (0, 0, 1, 1)})
        self.assertEqual(pal.shape, (4, 4))
        np.testing.assert_allclose(pal[3], [0, 0, 1, 1])
        np.testing.assert_allclose(pal[1], nc_sim.DEFAULT_STOCK_COLOR)
        self.assertEqual(surf.build_palette({}).shape, (0, 4))


if __name__ == '__main__':
    unittest.main()
