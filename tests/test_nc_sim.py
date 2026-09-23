"""nc_sim.py(밀링 3축 형상 시뮬레이션 엔진) 단위 테스트. Qt 비의존."""
import math
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import nc_sim as sim


class ToolShapeTests(unittest.TestCase):
    def test_flat_endmill_profile_is_zero_everywhere_inside_radius(self):
        tool = sim.tool_shape_from_values('FLAT E/M', d=12.0, fl=30.0)
        self.assertEqual(tool.radius, 6.0)
        self.assertEqual(tool.height_at(0.0), 0.0)
        self.assertEqual(tool.height_at(5.9), 0.0)
        self.assertIsNone(tool.height_at(6.1))

    def test_fillet_corner_r_matches_circle_geometry(self):
        # D12 R2 -> flat_r = 4; r=5 지점 높이 = R - sqrt(R^2 - (r-flat_r)^2)
        tool = sim.tool_shape_from_values('FILLET E/M', d=12.0, r=2.0)
        expected = 2.0 - math.sqrt(2.0 ** 2 - 1.0 ** 2)
        self.assertAlmostEqual(tool.height_at(5.0), expected, places=6)
        self.assertAlmostEqual(tool.height_at(4.0), 0.0, places=6)
        self.assertAlmostEqual(tool.height_at(6.0), 2.0, places=6)

    def test_fillet_without_r_behaves_like_flat(self):
        tool = sim.tool_shape_from_values('FILLET E/M', d=12.0, r=None)
        self.assertEqual(tool.height_at(5.9), 0.0)

    def test_face_mill_and_cutter_use_fillet_family(self):
        # D50 R1 -> flat_r = 24; r=24.5 지점 dr=0.5 -> R - sqrt(R^2 - dr^2)
        expected = 1.0 - math.sqrt(1.0 ** 2 - 0.5 ** 2)
        for type_name in ('FACE MILL', 'CUTTER'):
            tool = sim.tool_shape_from_values(type_name, d=50.0, r=1.0)
            self.assertAlmostEqual(tool.height_at(24.5), expected, places=5)

    def test_ball_endmill_is_hemisphere(self):
        tool = sim.tool_shape_from_values('BALL E/M', d=10.0)
        r_val = 5.0
        # 반구: height(r) = R - sqrt(R^2 - r^2)
        self.assertAlmostEqual(tool.height_at(3.0), r_val - math.sqrt(r_val ** 2 - 9.0), places=6)
        self.assertAlmostEqual(tool.height_at(5.0), 5.0, places=6)  # 적도에서 팁 대비 반지름만큼 높음
        self.assertAlmostEqual(tool.height_at(0.0), 0.0, places=6)  # 팁 = 가장 아래 점

    def test_drill_cone_uses_sig_angle(self):
        tool = sim.tool_shape_from_values('DRILL', d=10.0, sig=120.0)
        half = math.radians(60.0)
        expected = 5.0 / math.tan(half)
        self.assertAlmostEqual(tool.height_at(5.0), expected, places=6)

    def test_drill_defaults_to_118_degrees_when_sig_missing(self):
        with_default = sim.tool_shape_from_values('DRILL', d=10.0, sig=None)
        explicit = sim.tool_shape_from_values('DRILL', d=10.0, sig=118.0)
        self.assertAlmostEqual(with_default.height_at(4.0), explicit.height_at(4.0), places=6)

    def test_pl_tool_gets_45_degree_chamfer_u_shape(self):
        # D20, PL3 -> 중심 반경 7까지 평평, 7~10 구간은 45도(1:1)로 올라감
        tool = sim.tool_shape_from_values('CHAMF MILL', d=20.0, pl=3.0)
        self.assertAlmostEqual(tool.height_at(6.0), 0.0, places=6)
        self.assertAlmostEqual(tool.height_at(8.0), 1.0, places=6)
        self.assertAlmostEqual(tool.height_at(10.0), 3.0, places=6)

    def test_tool_without_pl_or_known_type_falls_back_to_flat_cylinder(self):
        tool = sim.tool_shape_from_values('TAP', d=8.0)
        self.assertEqual(tool.height_at(3.9), 0.0)

    def test_missing_diameter_returns_none(self):
        self.assertIsNone(sim.tool_shape_from_values('FLAT E/M', d=None))
        self.assertIsNone(sim.tool_shape_from_values('FLAT E/M', d=0))


class StockSpecTests(unittest.TestCase):
    def test_default_reference_is_top_z_and_center_xy(self):
        spec = sim.StockSpec(
            dims={'T': 50.0, 'W': 100.0, 'L': 150.0},
            axis_of={'T': 'Z', 'W': 'Y', 'L': 'X'},
        )
        bounds = spec.bounds()
        self.assertEqual(bounds['X'], (-75.0, 75.0))
        self.assertEqual(bounds['Y'], (-50.0, 50.0))
        self.assertEqual(bounds['Z'], (-50.0, 0.0))

    def test_axis_swap_example_from_user_twy_wz_lx(self):
        spec = sim.StockSpec(
            dims={'T': 50.0, 'W': 100.0, 'L': 150.0},
            axis_of={'T': 'Y', 'W': 'Z', 'L': 'X'},
        )
        bounds = spec.bounds()
        self.assertEqual(bounds['X'], (-75.0, 75.0))
        self.assertEqual(bounds['Y'], (-25.0, 25.0))   # T=50 -> Y 중심
        self.assertEqual(bounds['Z'], (-100.0, 0.0))   # W=100 -> Z 윗면=0

    def test_invalid_axis_assignment_raises(self):
        with self.assertRaises(ValueError):
            sim.StockSpec(dims={'T': 1, 'W': 1, 'L': 1}, axis_of={'T': 'X', 'W': 'X', 'L': 'Y'})

    def test_reference_neg_and_pos_edges(self):
        spec = sim.StockSpec(
            dims={'T': 10.0, 'W': 10.0, 'L': 10.0},
            axis_of={'T': 'Z', 'W': 'Y', 'L': 'X'},
            reference={'X': 'neg', 'Y': 'pos'},
        )
        bounds = spec.bounds()
        self.assertEqual(bounds['X'], (0.0, 10.0))
        self.assertEqual(bounds['Y'], (-10.0, 0.0))

    def test_offset_shifts_in_positive_direction(self):
        spec = sim.StockSpec(
            dims={'T': 10.0, 'W': 10.0, 'L': 10.0},
            axis_of={'T': 'Z', 'W': 'Y', 'L': 'X'},
            offset={'X': 5.0, 'Z': -2.0},
        )
        bounds = spec.bounds()
        self.assertEqual(bounds['X'], (0.0, 10.0))
        self.assertEqual(bounds['Z'], (-12.0, -2.0))


class ZMapStockTests(unittest.TestCase):
    def _make_stock(self, resolution=0.5):
        bounds = {'X': (-20.0, 20.0), 'Y': (-20.0, 20.0), 'Z': (-30.0, 0.0)}
        return sim.ZMapStock(bounds, resolution)

    def test_initial_heights_equal_top(self):
        stock = self._make_stock()
        self.assertTrue(np.all(stock.heights == 0.0))

    def test_flat_endmill_straight_slot_depth_and_width(self):
        stock = self._make_stock(resolution=0.25)
        tool = sim.tool_shape_from_values('FLAT E/M', d=10.0, fl=30.0, so=30.0)
        stock.cut_segment([-10.0, 0.0, -5.0], [10.0, 0.0, -5.0], tool)
        heights = stock.heights
        gy = stock.grid_y()
        gx = stock.grid_x()
        center_row = np.argmin(np.abs(gy - 0.0))
        mid_col = np.argmin(np.abs(gx - 0.0))
        self.assertAlmostEqual(heights[center_row, mid_col], -5.0, places=2)
        # 이동 방향은 X이므로 폭은 Y 방향(半径5)으로 확인해야 한다 — 그
        # 밖(y=8)은 원래 표면(0)이어야 한다
        far_row = np.argmin(np.abs(gy - 8.0))
        self.assertAlmostEqual(heights[far_row, mid_col], 0.0, places=2)
        # 폭이 대략 10mm(半径5) 인지 격자 간격 오차 안에서 확인
        cut_mask = heights[:, mid_col] < -0.01
        cut_width = cut_mask.sum() * stock.resolution
        self.assertAlmostEqual(cut_width, 10.0, delta=1.0)

    def test_stock_never_cuts_below_bottom(self):
        stock = self._make_stock(resolution=0.5)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_point([0.0, 0.0, -999.0], tool)
        self.assertTrue(np.all(stock.heights >= stock.zlo))

    def test_drill_cone_hole_depth(self):
        stock = self._make_stock(resolution=0.2)
        tool = sim.tool_shape_from_values('DRILL', d=6.0, sig=118.0)
        # 팁이 z=-10까지 내려간 상태로 정지
        stock.cut_point([0.0, 0.0, -10.0], tool)
        gy = stock.grid_y()
        gx = stock.grid_x()
        row = np.argmin(np.abs(gy - 0.0))
        col = np.argmin(np.abs(gx - 0.0))
        self.assertAlmostEqual(stock.heights[row, col], -10.0, delta=0.05)

    def test_rapid_move_cutting_material_is_flagged(self):
        stock = self._make_stock(resolution=0.5)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_segment([0.0, 0.0, -5.0], [5.0, 0.0, -5.0], tool, rapid=True, src_line=42, seq=7)
        self.assertEqual(stock.rapid_cut_warnings, [(42, 7)])

    def test_rapid_move_in_air_is_not_flagged(self):
        stock = self._make_stock(resolution=0.5)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_segment([0.0, 0.0, 50.0], [5.0, 0.0, 50.0], tool, rapid=True, src_line=1, seq=1)
        self.assertEqual(stock.rapid_cut_warnings, [])

    def test_snapshot_restore_roundtrip(self):
        stock = self._make_stock(resolution=0.5)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        snap = stock.snapshot()
        stock.cut_point([0.0, 0.0, -5.0], tool)
        self.assertFalse(np.all(stock.heights == snap))
        stock.restore(snap)
        self.assertTrue(np.all(stock.heights == snap))

    def test_incremental_cut_matches_single_pass(self):
        tool = sim.tool_shape_from_values('FLAT E/M', d=8.0)
        pts = [[-10.0, 0.0, -3.0], [0.0, 0.0, -3.0], [0.0, 10.0, -3.0]]

        stock_full = self._make_stock(resolution=0.4)
        for a, b in zip(pts[:-1], pts[1:]):
            stock_full.cut_segment(a, b, tool)

        stock_inc = self._make_stock(resolution=0.4)
        stock_inc.cut_segment(pts[0], pts[1], tool)
        snap = stock_inc.snapshot()
        stock_inc.restore(snap)
        stock_inc.cut_segment(pts[1], pts[2], tool)

        self.assertTrue(np.allclose(stock_full.heights, stock_inc.heights))

    def test_to_mesh_produces_closed_triangle_soup(self):
        stock = self._make_stock(resolution=2.0)
        verts, faces = stock.to_mesh()
        self.assertEqual(verts.shape[1], 3)
        self.assertEqual(faces.shape[1], 3)
        self.assertEqual(verts.shape[0], faces.shape[0] * 3)
        # 모든 정점이 소재 bounds 안에 있어야 한다
        self.assertTrue(np.all(verts[:, 2] <= stock.ztop + 1e-6))
        self.assertTrue(np.all(verts[:, 2] >= stock.zlo - 1e-6))


class AutoResolutionTests(unittest.TestCase):
    def test_resolution_within_bounds(self):
        bounds = {'X': (-100.0, 100.0), 'Y': (-100.0, 100.0), 'Z': (-50.0, 0.0)}
        res = sim.auto_resolution(bounds)
        self.assertGreaterEqual(res, 0.05)
        self.assertLessEqual(res, 0.5)

    def test_safe_mode_yields_coarser_resolution(self):
        bounds = {'X': (-100.0, 100.0), 'Y': (-100.0, 100.0), 'Z': (-50.0, 0.0)}
        normal = sim.auto_resolution(bounds, safe_mode=False)
        safe = sim.auto_resolution(bounds, safe_mode=True)
        self.assertGreaterEqual(safe, normal)


class StlExportTests(unittest.TestCase):
    def test_binary_stl_header_and_triangle_count(self):
        stock = sim.ZMapStock({'X': (-5.0, 5.0), 'Y': (-5.0, 5.0), 'Z': (-10.0, 0.0)}, 2.0)
        verts, faces = stock.to_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.stl')
            sim.write_stl_binary(path, verts, faces)
            with open(path, 'rb') as f:
                data = f.read()
            self.assertEqual(len(data), 80 + 4 + faces.shape[0] * 50)
            count = struct.unpack('<I', data[80:84])[0]
            self.assertEqual(count, faces.shape[0])


if __name__ == '__main__':
    unittest.main()
