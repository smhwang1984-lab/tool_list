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
        snap_heights, snap_colors = stock.snapshot()
        stock.cut_point([0.0, 0.0, -5.0], tool, color_id=2)
        self.assertFalse(np.all(stock.heights == snap_heights))
        self.assertFalse(np.all(stock.color_ids == snap_colors))
        stock.restore((snap_heights, snap_colors))
        self.assertTrue(np.all(stock.heights == snap_heights))
        self.assertTrue(np.all(stock.color_ids == snap_colors))

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

    def test_to_mesh_is_closed_indexed_mesh_with_outward_normals(self):
        stock = self._make_stock(resolution=2.0)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_segment([-8.0, 0.0, -5.0], [8.0, 0.0, -5.0], tool)
        verts, faces, colors = stock.to_mesh()
        self.assertEqual(verts.shape[1], 3)
        self.assertEqual(faces.shape[1], 3)
        self.assertEqual(colors.shape, (verts.shape[0], 4))
        # 정점을 공유하는 인덱스 메쉬 — 정점 수가 삼각형×3보다 훨씬 적다
        self.assertLess(verts.shape[0], faces.shape[0] * 3 // 2)
        # 모든 정점이 소재 bounds 안에 있어야 한다
        self.assertTrue(np.all(verts[:, 2] <= stock.ztop + 1e-6))
        self.assertTrue(np.all(verts[:, 2] >= stock.zlo - 1e-6))
        # 닫힌 메쉬: 모든 변이 정확히 두 삼각형에 공유된다
        edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        edges.sort(axis=1)
        _unique, counts = np.unique(edges, axis=0, return_counts=True)
        self.assertTrue(np.all(counts == 2))
        # 법선이 바깥쪽: 부호 있는 부피가 양수이고 소재 상자 부피보다 작다
        tri = verts[faces].astype(np.float64)
        volume = np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
        bx = stock.grid_x()
        by = stock.grid_y()
        box = (bx[-1] - bx[0]) * (by[-1] - by[0]) * (stock.ztop - stock.zlo)
        self.assertGreater(volume, 0.0)
        self.assertLess(volume, box)

    def test_to_mesh_without_color_map_is_uniform_default_color(self):
        stock = self._make_stock(resolution=2.0)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_point([0.0, 0.0, -5.0], tool, color_id=3)
        default_color = (0.5, 0.5, 0.5, 1.0)
        _verts, _faces, colors = stock.to_mesh(default_color=default_color)
        self.assertTrue(np.allclose(colors, np.array(default_color)))

    def test_to_mesh_colors_cut_area_by_tool_color_map(self):
        stock = self._make_stock(resolution=0.5)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_point([0.0, 0.0, -5.0], tool, color_id=1)
        color_map = {0: (1.0, 0.0, 0.0, 1.0), 1: (0.0, 1.0, 0.0, 1.0)}
        default_color = (0.5, 0.5, 0.5, 1.0)
        verts, _faces, colors = stock.to_mesh(color_map=color_map, default_color=default_color)
        # 팁 바로 위 정점(잘려나간 지점)은 초록(공구 색 1), 멀리 떨어진
        # 안 깎인 지점은 회색(기본색)이어야 한다.
        near = np.argmin(np.linalg.norm(verts[:, :2], axis=1))
        self.assertTrue(np.allclose(colors[near], (0.0, 1.0, 0.0, 1.0), atol=1e-5))
        far_mask = np.linalg.norm(verts[:, :2], axis=1) > 15.0
        self.assertTrue(np.all(np.isclose(colors[far_mask], default_color).all(axis=1)))

    def test_color_ids_survive_snapshot_and_restore(self):
        stock = self._make_stock(resolution=0.5)
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_point([0.0, 0.0, -5.0], tool, color_id=1)
        snap = stock.snapshot()
        stock.cut_point([5.0, 5.0, -5.0], tool, color_id=2)
        self.assertTrue(np.any(stock.color_ids == 2))
        stock.restore(snap)
        self.assertFalse(np.any(stock.color_ids == 2))
        self.assertTrue(np.any(stock.color_ids == 1))


class RadialLutTests(unittest.TestCase):
    """v1.9.2 — 격자 간격에 맞춘 반경 방향 높이표."""

    SHAPES = (
        ('FLAT', lambda: sim.tool_shape_from_values('FLAT E/M', d=10.0)),
        ('FILLET', lambda: sim.tool_shape_from_values('FILLET E/M', d=10.0, r=2.0)),
        ('BALL', lambda: sim.tool_shape_from_values('BALL E/M', d=10.0)),
        ('DRILL', lambda: sim.tool_shape_from_values('DRILL', d=10.0, sig=118.0)),
        ('CHAMFER', lambda: sim.tool_shape_from_values('T-CUTTER', d=10.0, pl=1.5)),
    )

    def test_lut_nodes_match_profile_and_end_at_radius(self):
        for name, make in self.SHAPES:
            shape = make()
            lut, inv_step = shape.radial_lut(0.25)
            step = 1.0 / inv_step
            n = lut.size - 2
            self.assertAlmostEqual(n * step, shape.radius, places=9, msg=name)
            r = np.minimum(np.arange(lut.size) * step, shape.radius)
            self.assertTrue(np.allclose(lut, shape.height_grid(r), atol=1e-12), name)

    def test_interpolated_height_stays_close_to_exact_profile(self):
        for name, make in self.SHAPES:
            shape = make()
            lut, inv_step = shape.radial_lut(0.25)
            d = np.linspace(0.0, shape.radius, 997)
            pos = d * inv_step
            k = np.minimum(pos.astype(int), lut.size - 2)
            frac = pos - k
            approx = lut[k] * (1 - frac) + lut[k + 1] * frac
            self.assertLess(float(np.abs(approx - shape.height_grid(d)).max()), 0.08, name)

    def test_lut_is_cached_per_resolution(self):
        shape = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        self.assertIs(shape.radial_lut(0.5), shape.radial_lut(0.5))
        self.assertIsNot(shape.radial_lut(0.5), shape.radial_lut(0.25))


def _random_segments(rng, count):
    """소재 안팎을 섞은 무작위 선분(수직 이동 포함)."""
    p0 = np.column_stack([rng.uniform(-30, 30, count), rng.uniform(-30, 30, count),
                          rng.uniform(-12, 4, count)])
    p1 = p0 + np.column_stack([rng.uniform(-12, 12, count), rng.uniform(-12, 12, count),
                               rng.uniform(-6, 6, count)])
    vertical = rng.random(count) < 0.15
    p1[vertical, :2] = p0[vertical, :2]
    return p0, p1


class BatchCutTests(unittest.TestCase):
    COUNT = 300

    def _stock(self, res=0.5):
        return sim.ZMapStock({'X': (-20.0, 20.0), 'Y': (-20.0, 20.0), 'Z': (-15.0, 0.0)}, res)

    def _tools(self):
        return [
            sim.tool_shape_from_values('FLAT E/M', d=6.0),
            sim.tool_shape_from_values('BALL E/M', d=8.0),
            sim.tool_shape_from_values('DRILL', d=5.0, sig=118.0),
            None,  # D 값 없는 공구 — 건너뛴다
        ]

    def _inputs(self):
        rng = np.random.default_rng(7)
        p0, p1 = _random_segments(rng, self.COUNT)
        return (p0, p1, rng.integers(0, 4, self.COUNT), rng.random(self.COUNT) < 0.3,
                rng.integers(0, 5, self.COUNT))

    def _run(self, use_numba, chunk=sim.SIM_CHUNK_SEGMENTS):
        p0, p1, tool_idx, rapid, color = self._inputs()
        stock = self._stock()
        done = stock.cut_batch(p0, p1, self._tools(), tool_idx, rapid, color,
                               src_lines=np.arange(self.COUNT), seqs=np.arange(self.COUNT) * 2,
                               use_numba=use_numba, chunk=chunk)
        self.assertTrue(done)
        return stock

    def test_batch_equals_one_by_one(self):
        p0, p1, tool_idx, rapid, color = self._inputs()
        tools = self._tools()
        one = self._stock()
        for m in range(self.COUNT):
            if tools[tool_idx[m]] is None:
                continue
            one.cut_segment(p0[m], p1[m], tools[tool_idx[m]], rapid=bool(rapid[m]),
                            src_line=m, seq=m * 2, color_id=int(color[m]))
        batch = self._run(use_numba=False)
        self.assertTrue(np.array_equal(one.heights, batch.heights))
        self.assertTrue(np.array_equal(one.color_ids, batch.color_ids))
        self.assertEqual(one.rapid_cut_warnings, batch.rapid_cut_warnings)

    def test_chunked_equals_unchunked(self):
        a = self._run(use_numba=False)
        b = self._run(use_numba=False, chunk=37)
        self.assertTrue(np.array_equal(a.heights, b.heights))
        self.assertTrue(np.array_equal(a.color_ids, b.color_ids))

    def test_numba_path_equals_numpy_path(self):
        if not sim.numba_available():
            self.skipTest('numba 없음')
        a = self._run(use_numba=False)
        b = self._run(use_numba=True)
        self.assertTrue(np.array_equal(a.heights, b.heights))
        self.assertTrue(np.array_equal(a.color_ids, b.color_ids))
        self.assertEqual(a.rapid_cut_warnings, b.rapid_cut_warnings)

    def test_segments_above_stock_change_nothing(self):
        stock = self._stock()
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_segment([-30.0, 0.0, 5.0], [30.0, 0.0, 0.0], tool, rapid=True, src_line=1, seq=1)
        self.assertTrue(np.all(stock.heights == stock.ztop))
        self.assertEqual(stock.rapid_cut_warnings, [])

    def test_segments_outside_stock_are_ignored(self):
        stock = self._stock()
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        stock.cut_segment([100.0, 100.0, -5.0], [120.0, 100.0, -5.0], tool)
        self.assertTrue(np.all(stock.heights == stock.ztop))

    def test_tool_none_segments_are_skipped(self):
        stock = self._stock()
        stock.cut_batch(np.array([[0.0, 0.0, -5.0]]), np.array([[5.0, 0.0, -5.0]]),
                        [None], [0], [False], [0])
        self.assertTrue(np.all(stock.heights == stock.ztop))

    def test_cancel_stops_between_chunks_and_clone_keeps_original(self):
        stock = self._stock()
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        work = stock.clone()
        calls = {'n': 0}

        def cancel():
            calls['n'] += 1
            return calls['n'] > 1

        p0 = np.tile([-10.0, 0.0, -3.0], (10, 1))
        p1 = np.tile([10.0, 0.0, -3.0], (10, 1))
        done = work.cut_batch(p0, p1, [tool], np.zeros(10, int), np.zeros(10, bool),
                              np.zeros(10, int), cancel=cancel, chunk=4, use_numba=False)
        self.assertFalse(done)
        self.assertTrue(np.all(stock.heights == stock.ztop))   # 원본은 그대로
        self.assertTrue(np.any(work.heights < work.ztop))

    def test_progress_callback_reports_chunks(self):
        stock = self._stock()
        tool = sim.tool_shape_from_values('FLAT E/M', d=6.0)
        seen = []
        stock.cut_batch(np.zeros((10, 3)), np.ones((10, 3)) * -1, [tool], np.zeros(10, int),
                        np.zeros(10, bool), np.zeros(10, int), chunk=4,
                        progress=lambda done, total: seen.append((done, total)), use_numba=False)
        self.assertEqual(seen, [(4, 10), (8, 10), (10, 10)])

    def test_heights_are_float32_and_color_ids_int16(self):
        stock = self._stock()
        self.assertEqual(stock.heights.dtype, np.float32)
        self.assertEqual(stock.color_ids.dtype, np.int16)
        self.assertLessEqual(stock.snapshot_nbytes(), stock.cell_count() * 6)


class DisplayMeshTests(unittest.TestCase):
    def _slot_stock(self):
        stock = sim.ZMapStock({'X': (-50.0, 50.0), 'Y': (-50.0, 50.0), 'Z': (-20.0, 0.0)}, 0.1)
        tool = sim.tool_shape_from_values('FLAT E/M', d=0.3)   # 폭 0.3mm 좁은 홈
        stock.cut_segment([-40.0, 0.0, -5.0], [40.0, 0.0, -5.0], tool, color_id=1)
        return stock

    def test_display_grid_is_capped(self):
        stock = self._slot_stock()
        xs, ys, Z, C = stock.display_grid(200)
        self.assertLessEqual(len(xs), 201)
        self.assertLessEqual(len(ys), 201)
        self.assertEqual(Z.shape, (len(ys), len(xs)))
        self.assertEqual(C.shape, Z.shape)
        self.assertAlmostEqual(float(xs[0]), -50.0, places=4)
        self.assertAlmostEqual(float(xs[-1]), 50.0, places=4)

    def test_narrow_slot_does_not_disappear_when_downsampled(self):
        stock = self._slot_stock()
        _xs, _ys, Z, C = stock.display_grid(100)
        self.assertLess(float(Z.min()), -4.9)         # 홈 깊이 5가 표시 격자에도 남는다
        self.assertTrue(np.any(C == 1))

    def test_small_stock_uses_full_grid(self):
        stock = sim.ZMapStock({'X': (0.0, 5.0), 'Y': (0.0, 5.0), 'Z': (-5.0, 0.0)}, 0.5)
        _xs, _ys, Z, _C = stock.display_grid(600)
        self.assertEqual(Z.shape, (stock.ny, stock.nx))
        self.assertTrue(np.array_equal(Z, stock.heights))

    def test_display_mesh_vertex_count_is_small(self):
        stock = self._slot_stock()             # 계산 격자 1001 x 1001
        verts, faces, colors, edges = stock.display_mesh(300)
        self.assertLess(verts.shape[0], 300 * 300 + 2000)
        self.assertEqual(colors.shape, (verts.shape[0], 4))
        self.assertEqual(int(faces.max()) + 1, verts.shape[0])
        self.assertEqual(edges.shape[1], 3)
        self.assertEqual(edges.shape[0] % 2, 0)

    def test_topology_cache_is_reused(self):
        first = sim._topology(20, 30)
        second = sim._topology(20, 30)
        self.assertIs(first[0], second[0])

    def test_edges_include_block_outline_and_slot_step(self):
        stock = self._slot_stock()
        _v, _f, _c, edges = stock.display_mesh(300)
        segs = edges.reshape(-1, 2, 3)
        self.assertGreater(segs.shape[0], 12 + 10)    # 외곽 + 홈 단차 선
        self.assertTrue(np.any(np.isclose(segs[:, :, 2], -5.0, atol=0.01)))

    def test_flat_stock_has_only_outline_edges(self):
        stock = sim.ZMapStock({'X': (-5.0, 5.0), 'Y': (-5.0, 5.0), 'Z': (-5.0, 0.0)}, 1.0)
        _v, _f, _c, edges = stock.display_mesh(600)
        segs = edges.reshape(-1, 2, 3)
        self.assertEqual(segs.shape[0], (2 * stock.nx + 2 * stock.ny - 4) + 4 + 4)

    def test_edge_limit_thins_out_step_segments(self):
        xs = np.arange(40, dtype=np.float32)
        Z = np.zeros((40, 40), dtype=np.float32)
        Z[:, ::2] = -5.0                               # 세로 줄무늬 — 단차가 아주 많다
        edges = sim.edge_lines(xs, xs, Z, -10.0, 1.0, limit=50)
        outline = (2 * 40 + 2 * 40 - 4) + 4 + 4
        self.assertLessEqual(edges.shape[0] // 2, outline + 50)

    def test_color_modes(self):
        stock = self._slot_stock()
        cmap = {1: (1.0, 0.0, 0.0, 1.0)}
        _v, _f, tool_colors, _e = stock.display_mesh(300, color_map=cmap, mode='tool')
        _v, _f, solid_colors, _e = stock.display_mesh(300, mode='solid')
        _v, _f, depth_colors, _e = stock.display_mesh(300, mode='depth')
        self.assertTrue(np.any(np.all(np.isclose(tool_colors, (1.0, 0.0, 0.0, 1.0)), axis=1)))
        self.assertTrue(np.allclose(solid_colors, np.array(sim.DEFAULT_STOCK_COLOR)))
        self.assertGreater(len({tuple(np.round(c, 3)) for c in depth_colors}), 1)
        # 밝은 계통 — 깊이 모드 색의 평균 밝기가 충분히 높다
        self.assertGreater(float(depth_colors[:, :3].mean()), 0.6)


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
        verts, faces, _colors = stock.to_mesh()
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
