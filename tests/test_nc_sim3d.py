"""nc_sim3d.py(3D 복셀 소재 엔진, 경사 공구 축) 단위 테스트. Qt 비의존."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import nc_sim
import nc_sim3d as s3

Z_AXIS = (0.0, 0.0, 1.0)


def make_stock(res=0.5, x=(-20.0, 20.0), y=(-20.0, 20.0), z=(-20.0, 0.0)):
    return s3.VoxelStock({'X': x, 'Y': y, 'Z': z}, res)


def voxel_centers(stock):
    xs = stock.x0 + (np.arange(stock.nx) + 0.5) * stock.step[0]
    ys = stock.y0 + (np.arange(stock.ny) + 0.5) * stock.step[1]
    zs = stock.z0 + (np.arange(stock.nz) + 0.5) * stock.step[2]
    return np.meshgrid(xs, ys, zs, indexing='ij')


def flat(d=10.0, fl=15.0):
    return nc_sim.tool_shape_from_values('FLAT E/M', d=d, fl=fl, so=fl)


class GridTests(unittest.TestCase):
    def test_grid_matches_bounds_exactly_with_per_axis_step(self):
        stock = make_stock(res=0.5, x=(-10.0, 10.3), y=(0.0, 7.0), z=(-5.0, 0.0))
        self.assertAlmostEqual(stock.x0 + stock.nx * stock.step[0], 10.3)
        self.assertAlmostEqual(stock.y0 + stock.ny * stock.step[1], 7.0)
        self.assertAlmostEqual(stock.z0 + stock.nz * stock.step[2], 0.0)
        self.assertTrue(np.all(stock.occ == 1))
        self.assertFalse(stock.any_cut())

    def test_auto_and_clamped_resolution(self):
        bounds = {'X': (-50.0, 50.0), 'Y': (-50.0, 50.0), 'Z': (-50.0, 0.0)}
        res = s3.auto_resolution_3d(bounds)
        voxels = (100 / res) * (100 / res) * (50 / res)
        self.assertLess(abs(voxels - s3.SIM3D_TARGET_VOXELS) / s3.SIM3D_TARGET_VOXELS, 0.1)
        fine = s3.clamp_resolution_3d(bounds, 0.05)
        self.assertLessEqual((100 / fine) * (100 / fine) * (50 / fine), s3.SIM3D_MAX_VOXELS * 1.01)

    def test_tool_cut_length_prefers_flute_then_stickout(self):
        tool = nc_sim.tool_shape_from_values('FLAT E/M', d=10.0, fl=26.0, so=40.0)
        self.assertEqual(tool.cut_length, 26.0)
        self.assertEqual(tool.length, 40.0)
        self.assertEqual(nc_sim.tool_shape_from_values('FLAT E/M', d=10.0, so=40.0).cut_length, 40.0)


class CuttingGeometryTests(unittest.TestCase):
    def test_vertical_axis_matches_zmap_heights(self):
        tool = flat(10.0, 15.0)
        p0 = np.array([[-12.0, -3.0, -6.0], [10.0, 8.0, -3.0]])
        p1 = np.array([[12.0, 4.0, -6.0], [-9.0, -10.0, -9.0]])
        vox = make_stock(res=0.4)
        vox.cut_batch(p0, p1, [tool], [0, 0], [False, False], [0, 0], use_numba=False)
        zmap = nc_sim.ZMapStock({'X': (-20.0, 20.0), 'Y': (-20.0, 20.0), 'Z': (-20.0, 0.0)}, 0.4)
        zmap.cut_batch(p0, p1, [tool], [0, 0], [False, False], [0, 0], use_numba=False)
        # 각 (x, y) 기둥에서 남은 소재의 가장 높은 z (복셀) 와 Z-map 높이 비교
        gx, gy, gz = voxel_centers(vox)
        top = np.where(vox.occ.astype(bool), gz, -np.inf).max(axis=2)
        # 두 격자의 셀 위치가 다르므로 복셀 기둥 중심에서 Z-map을 보간해 비교
        zx = zmap.grid_x()
        zy = zmap.grid_y()
        checked = 0
        worst = 0.0
        for i in range(0, vox.nx, 7):
            for j in range(0, vox.ny, 7):
                x = gx[i, j, 0]
                y = gy[i, j, 0]
                ii = int(np.clip(np.round((x - zx[0]) / zmap.resolution), 0, zmap.nx - 1))
                jj = int(np.clip(np.round((y - zy[0]) / zmap.resolution), 0, zmap.ny - 1))
                ref = float(zmap.heights[jj, ii])
                got = top[i, j]
                # 복셀은 중심 기준이라 높이가 최대 한 칸(step z) 어긋난다. 벽 경계 칸은 제외
                patch = zmap.heights[max(jj - 2, 0):jj + 3, max(ii - 2, 0):ii + 3]
                if np.any(np.abs(patch - ref) > 0.5):
                    continue
                worst = max(worst, abs(min(ref, vox.ztop) - min(got + vox.step[2] / 2, vox.ztop)))
                checked += 1
        self.assertGreater(checked, 50)
        self.assertLess(worst, vox.step[2] * 1.01)

    def test_horizontal_axis_cuts_a_side_slot_analytically(self):
        """공구 축이 +X(수평), 끝이 x=-10: 이동은 Y 방향 → x∈[-10, 5], 반경 5 띠가 파인다."""
        stock = make_stock(res=0.5, x=(-20.0, 20.0), y=(-20.0, 20.0), z=(-10.0, 10.0))
        tool = flat(10.0, 15.0)
        stock.cut_segment([-10.0, -12.0, 0.0], [-10.0, 12.0, 0.0], tool, axis0=(1.0, 0.0, 0.0))
        gx, gy, gz = voxel_centers(stock)
        expected = (gx >= -10.0) & (gx <= 5.0) & (np.abs(gz) <= 5.0) & (np.abs(gy) <= 17.0)
        removed = stock.occ == 0
        margin = 1.1 * max(stock.step)
        core = (gx > -10.0 + margin) & (gx < 5.0 - margin) & (np.abs(gz) < 5.0 - margin) & (np.abs(gy) < 12.0)
        outside = ~((gx >= -10.0 - margin) & (gx <= 5.0 + margin) & (np.abs(gz) <= 5.0 + margin)
                    & (np.abs(gy) <= 17.0 + margin))
        self.assertTrue(np.all(removed[core]))                 # 확실히 안쪽 → 모두 제거
        self.assertFalse(np.any(removed[outside]))             # 확실히 바깥 → 하나도 안 깎임
        self.assertGreater(int(removed.sum()), 0.9 * int(expected.sum()) * 0.9)

    def test_tilted_ball_end_plunge_along_its_axis(self):
        stock = make_stock(res=0.4, x=(-20.0, 20.0), y=(-20.0, 20.0), z=(-20.0, 0.0))
        ball = nc_sim.tool_shape_from_values('BALL E/M', d=8.0, fl=12.0, so=12.0)
        a = np.array([0.5, 0.0, np.sqrt(0.75)])              # 수직에서 30도 기울임
        tip_start = np.array([-3.0, 0.0, 6.0])
        tip_end = np.array([0.0, 0.0, -4.0])
        stock.cut_segment(tip_start, tip_end, ball, axis0=a)
        gx, gy, gz = voxel_centers(stock)
        pts = np.stack([gx, gy, gz], axis=-1) - tip_end
        s = pts @ a
        q = np.linalg.norm(pts - s[..., None] * a, axis=-1)
        # 끝점 자세의 볼 중심(팁에서 축 방향 R)과의 거리
        centre = np.linalg.norm(pts - 4.0 * a, axis=-1)
        step = max(stock.step)
        removed = stock.occ == 0
        self.assertTrue(np.all(removed[(centre < 4.0 - 1.5 * step)]))          # 볼 안쪽은 전부 제거
        below_tip = (s < -1.5 * step) & (q < 1.0)
        self.assertFalse(np.any(removed[below_tip & (np.abs(gz - tip_end[2]) < 3)]))   # 팁 아래는 안 깎임

    def test_axial_entry_removes_a_cylinder_along_the_vector(self):
        """벡터 방향 진입: 이동 방향이 공구 축과 같으면 축을 따라 원기둥이 파인다."""
        stock = make_stock(res=0.5, x=(-25.0, 25.0), y=(-25.0, 25.0), z=(-25.0, 0.0))
        tool = flat(6.0, 10.0)
        a = np.array([0.36, 0.0, np.sqrt(1 - 0.36 ** 2)])
        start = np.array([-10.0, 0.0, 15.0]) + 40 * a * 0            # 소재 위쪽 진입 시작
        end = start - 30.0 * a                                        # 축 반대 방향(-a)으로 진입
        stock.cut_segment(start, end, tool, axis0=a)
        gx, gy, gz = voxel_centers(stock)
        pts = np.stack([gx, gy, gz], axis=-1) - end
        s = pts @ a
        q = np.linalg.norm(pts - s[..., None] * a, axis=-1)
        removed = stock.occ == 0
        step = max(stock.step)
        inside = (q < 3.0 - 1.2 * step) & (s > 1.2 * step) & (s < 10.0 + 25.0)        # 이동 구간+날장
        inside &= np.abs(gx) < 24
        self.assertTrue(np.all(removed[inside]))
        beyond_tip = (s < -1.5 * step) & (q < 3.0)
        self.assertFalse(np.any(removed[beyond_tip]))

    def test_tool_cut_length_limits_how_far_up_the_shank_cuts(self):
        stock = make_stock(res=0.5, x=(-10.0, 10.0), y=(-10.0, 10.0), z=(-2.0, 30.0))
        tool = nc_sim.tool_shape_from_values('FLAT E/M', d=6.0, fl=10.0, so=40.0)
        stock.cut_point([0.0, 0.0, 0.0], tool, axis=Z_AXIS)
        gx, gy, gz = voxel_centers(stock)
        removed = stock.occ == 0
        near_axis = np.hypot(gx, gy) < 2.5
        self.assertTrue(np.all(removed[near_axis & (gz > 0.5) & (gz < 9.5)]))
        self.assertFalse(np.any(removed[near_axis & (gz > 10.8)]))          # 날장(10) 위는 안 깎임
        self.assertFalse(np.any(removed[near_axis & (gz < -0.5)]))

    def test_segment_outside_stock_or_missing_tool_changes_nothing(self):
        stock = make_stock()
        stock.cut_segment([100.0, 100.0, 100.0], [120.0, 100.0, 100.0], flat())
        stock.cut_batch(np.zeros((1, 3)), np.ones((1, 3)), [None], [0], [False], [0])
        self.assertFalse(stock.any_cut())

    def test_rapid_move_through_material_is_flagged_once_per_segment(self):
        stock = make_stock()
        stock.cut_segment([-10.0, 0.0, -5.0], [10.0, 0.0, -5.0], flat(), rapid=True,
                          src_line=42, seq=7, axis0=Z_AXIS)
        self.assertEqual(stock.rapid_cut_warnings, [(42, 7)])
        air = make_stock()
        air.cut_segment([-10.0, 0.0, 40.0], [10.0, 0.0, 40.0], flat(), rapid=True,
                        src_line=1, seq=1, axis0=Z_AXIS)
        self.assertEqual(air.rapid_cut_warnings, [])

    def test_changing_axis_along_a_segment_sweeps_between_orientations(self):
        """동시 5축: 끝점 사이에서 공구 축이 돌면 두 자세 사이가 이어서 깎인다."""
        stock = make_stock(res=0.5, x=(-25.0, 25.0), y=(-25.0, 25.0), z=(-25.0, 25.0))
        tool = flat(6.0, 12.0)
        a0 = np.array([0.0, 0.0, 1.0])
        a1 = np.array([np.sin(np.radians(30)), 0.0, np.cos(np.radians(30))])
        stock.cut_segment([0.0, 0.0, 0.0], [0.0, 10.0, 0.0], tool, axis0=a0, axis1=a1)
        only_start = make_stock(res=0.5, x=(-25.0, 25.0), y=(-25.0, 25.0), z=(-25.0, 25.0))
        only_start.cut_segment([0.0, 0.0, 0.0], [0.0, 10.0, 0.0], tool, axis0=a0)
        self.assertGreater(int((stock.occ == 0).sum()), int((only_start.occ == 0).sum()))


class ConsistencyTests(unittest.TestCase):
    def _batch(self, seed=3, count=60):
        rng = np.random.default_rng(seed)
        p0 = np.column_stack([rng.uniform(-14, 14, count), rng.uniform(-14, 14, count),
                              rng.uniform(-14, 4, count)])
        p1 = p0 + np.column_stack([rng.uniform(-10, 10, count), rng.uniform(-10, 10, count),
                                   rng.uniform(-8, 8, count)])
        ang = rng.uniform(0, np.radians(70), count)
        az = rng.uniform(0, 2 * np.pi, count)
        a0 = np.stack([np.sin(ang) * np.cos(az), np.sin(ang) * np.sin(az), np.cos(ang)], axis=1)
        ang1 = ang + rng.uniform(-0.2, 0.2, count)
        a1 = np.stack([np.sin(ang1) * np.cos(az), np.sin(ang1) * np.sin(az), np.cos(ang1)], axis=1)
        tools = [flat(6.0, 12.0),
                 nc_sim.tool_shape_from_values('BALL E/M', d=8.0, fl=14.0, so=14.0),
                 nc_sim.tool_shape_from_values('DRILL', d=5.0, sig=118.0, fl=12.0, so=12.0),
                 None]
        return p0, p1, a0, a1, tools, rng.integers(0, 4, count), rng.random(count) < 0.3, \
            rng.integers(0, 6, count)

    def _run(self, use_numba, chunk=s3.SIM_CHUNK_SEGMENTS):
        p0, p1, a0, a1, tools, idx, rapid, color = self._batch()
        stock = make_stock(res=0.7)
        done = stock.cut_batch(p0, p1, tools, idx, rapid, color, src_lines=np.arange(60),
                               seqs=np.arange(60) * 2, use_numba=use_numba, chunk=chunk,
                               axes0=a0, axes1=a1)
        self.assertTrue(done)
        return stock

    def test_numba_path_equals_numpy_path(self):
        if not nc_sim.numba_available():
            self.skipTest('numba 없음')
        a = self._run(False)
        b = self._run(True)
        different = int((a.occ != b.occ).sum())
        self.assertLessEqual(different, max(2, int(1e-6 * a.occ.size)))
        self.assertTrue(np.array_equal(a.occ == 0, b.occ == 0) or different <= 2)
        self.assertEqual(len(a.rapid_cut_warnings) > 0, len(b.rapid_cut_warnings) > 0)

    def test_chunked_equals_unchunked(self):
        a = self._run(False)
        b = self._run(False, chunk=7)
        self.assertTrue(np.array_equal(a.occ, b.occ))
        self.assertTrue(np.array_equal(a.col, b.col))

    def test_batch_equals_one_by_one(self):
        p0, p1, a0, a1, tools, idx, rapid, color = self._batch(count=12)
        one = make_stock(res=0.7)
        for m in range(12):
            if tools[idx[m]] is None:
                continue
            one.cut_segment(p0[m], p1[m], tools[idx[m]], rapid=bool(rapid[m]), src_line=m,
                            seq=m * 2, color_id=int(color[m]), axis0=a0[m], axis1=a1[m])
        batch = make_stock(res=0.7)
        batch.cut_batch(p0, p1, tools, idx, rapid, color, src_lines=np.arange(12),
                        seqs=np.arange(12) * 2, use_numba=False, axes0=a0, axes1=a1)
        self.assertTrue(np.array_equal(one.occ, batch.occ))
        self.assertTrue(np.array_equal(one.col, batch.col))
        self.assertEqual(one.rapid_cut_warnings, batch.rapid_cut_warnings)

    def test_cancel_stops_between_chunks_and_clone_is_independent(self):
        stock = make_stock()
        work = stock.clone()
        calls = {'n': 0}

        def cancel():
            calls['n'] += 1
            return calls['n'] > 1

        p0 = np.tile([-10.0, 0.0, -3.0], (10, 1))
        p1 = np.tile([10.0, 0.0, -3.0], (10, 1))
        done = work.cut_batch(p0, p1, [flat()], np.zeros(10, int), np.zeros(10, bool),
                              np.zeros(10, int), cancel=cancel, chunk=4, use_numba=False)
        self.assertFalse(done)
        self.assertFalse(stock.any_cut())
        self.assertTrue(work.any_cut())

    def test_snapshot_is_compressed_and_restores_exactly(self):
        stock = make_stock(res=0.5)
        stock.cut_segment([-10.0, 0.0, -5.0], [10.0, 0.0, -5.0], flat(), color_id=3, axis0=Z_AXIS)
        snap = stock.snapshot()
        raw = stock.occ.nbytes + stock.col.nbytes
        self.assertLess(stock.snapshot_bytes(snap), raw / 4)
        occ, col = stock.occ.copy(), stock.col.copy()
        stock.cut_segment([-10.0, 5.0, -8.0], [10.0, 5.0, -8.0], flat(), color_id=4, axis0=Z_AXIS)
        self.assertFalse(np.array_equal(stock.occ, occ))
        stock.restore(snap)
        self.assertTrue(np.array_equal(stock.occ, occ))
        self.assertTrue(np.array_equal(stock.col, col))
        stock.reset()
        self.assertFalse(stock.any_cut())

    def test_removed_voxels_carry_the_cutting_tool_color(self):
        stock = make_stock(res=0.5)
        stock.cut_segment([-10.0, 0.0, -5.0], [10.0, 0.0, -5.0], flat(), color_id=3, axis0=Z_AXIS)
        self.assertTrue(np.all(stock.col[stock.occ == 0] == 3))
        self.assertTrue(np.all(stock.col[stock.occ == 1] == s3.UNCUT_COLOR))


class SurfaceMeshTests(unittest.TestCase):
    def _cut_stock(self):
        stock = make_stock(res=1.0, x=(-10.0, 10.0), y=(-10.0, 10.0), z=(-8.0, 0.0))
        stock.cut_segment([-6.0, 0.0, -4.0], [6.0, 0.0, -4.0], flat(6.0, 10.0), color_id=2,
                          axis0=Z_AXIS)
        return stock

    def test_box_mesh_is_closed_outward_and_has_twelve_creases(self):
        stock = make_stock(res=1.0, x=(-4.0, 4.0), y=(-4.0, 4.0), z=(-4.0, 4.0))
        verts, faces, _col, quads = s3.surface_nets(stock.occ, stock.col, (stock.x0, stock.y0, stock.z0),
                                                    stock.step)
        edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        edges.sort(axis=1)
        _u, counts = np.unique(edges, axis=0, return_counts=True)
        self.assertTrue(np.all(counts == 2))                     # 닫힌 메쉬
        tri = verts[faces].astype(np.float64)
        volume = np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
        self.assertGreater(volume, 0.0)                          # 법선이 바깥쪽
        self.assertLess(abs(volume - 8.0 ** 3) / 8.0 ** 3, 0.35)
        self.assertLessEqual(verts[:, 0].max(), 4.0 + 1e-3)
        self.assertGreaterEqual(verts[:, 0].min(), -4.0 - 1e-3)
        creases = s3.crease_edges(verts, quads, 40.0)
        self.assertGreater(creases.shape[0] // 2, 8)

    def test_cut_stock_mesh_is_closed_and_colored_by_tool(self):
        stock = self._cut_stock()
        verts, faces, colors, edges = stock.display_mesh(color_map={2: (1.0, 0.0, 0.0, 1.0)})
        self.assertEqual(colors.shape, (verts.shape[0], 4))
        self.assertTrue(np.any(np.all(np.isclose(colors, (1.0, 0.0, 0.0, 1.0)), axis=1)))
        self.assertTrue(np.any(np.all(np.isclose(colors, nc_sim.DEFAULT_STOCK_COLOR, atol=1e-5), axis=1)))
        # v2.0.2: 색이 섞이는 면은 정점을 복제하므로 닫힘 여부는 위치가 같은 정점을 합쳐서 본다
        _u, weld = np.unique(verts, axis=0, return_inverse=True)
        faces = weld.reshape(-1)[faces]
        edge_set = faces[:, [0, 1]].tolist() + faces[:, [1, 2]].tolist() + faces[:, [2, 0]].tolist()
        keys = np.sort(np.array(edge_set), axis=1)
        _u, counts = np.unique(keys, axis=0, return_counts=True)
        self.assertTrue(np.all(counts == 2))
        self.assertEqual(edges.shape[1], 3)
        self.assertGreater(edges.shape[0], 24)

    def test_tool_color_edges_are_sharp_not_gradients(self):
        """v2.0.2: 공정 색 모드에서는 한 삼각형 안에서 색이 섞이지 않고(선명), 늘어나는 정점은 적다."""
        stock = self._cut_stock()
        cmap = {2: (1.0, 0.0, 0.0, 1.0)}
        verts, faces, colors, _e = stock.display_mesh(color_map=cmap, mode='tool')
        rgb = colors[faces][:, :, :3]                       # (F, 3, 3)
        self.assertTrue(np.all(rgb[:, 0] == rgb[:, 1]))
        self.assertTrue(np.all(rgb[:, 0] == rgb[:, 2]))
        base_verts, _f, _c, _e = stock.display_mesh(color_map=cmap, mode='solid')
        self.assertLess(verts.shape[0], base_verts.shape[0] * 1.2)
        # 기본색(미절삭) 면과 공정 색 면이 모두 있다
        self.assertTrue(np.any(np.all(np.isclose(rgb[:, 0], (1.0, 0.0, 0.0)), axis=1)))
        self.assertTrue(np.any(np.all(np.isclose(rgb[:, 0], nc_sim.DEFAULT_STOCK_COLOR[:3], atol=1e-5), axis=1)))
        # 깎인 깊이 모드는 원래대로 연속 그라데이션(정점 수 그대로)
        depth_verts, _f, _c, _e = stock.display_mesh(mode='depth')
        self.assertEqual(depth_verts.shape[0], base_verts.shape[0])

    def test_color_modes_and_stl_full_resolution(self):
        stock = self._cut_stock()
        _v, _f, solid, _e = stock.display_mesh(mode='solid')
        _v, _f, depth, _e = stock.display_mesh(mode='depth')
        self.assertTrue(np.allclose(solid, np.array(nc_sim.DEFAULT_STOCK_COLOR)))
        self.assertGreater(len({tuple(np.round(c, 3)) for c in depth}), 1)
        verts, faces, colors = stock.to_mesh()
        self.assertEqual(colors.shape, (verts.shape[0], 4))
        self.assertGreater(faces.shape[0], 0)

    def test_display_mesh_coarsens_when_over_the_quad_limit(self):
        stock = make_stock(res=0.5, x=(-20.0, 20.0), y=(-20.0, 20.0), z=(-10.0, 0.0))
        stock.cut_segment([-15.0, 0.0, -4.0], [15.0, 0.0, -4.0], flat(8.0, 10.0), axis0=Z_AXIS)
        fine, _f, _c, _e = stock.display_mesh()
        original = s3.SIM3D_DISPLAY_QUADS_MAX
        try:
            s3.SIM3D_DISPLAY_QUADS_MAX = 2000
            coarse, _f, _c, _e = stock.display_mesh()
        finally:
            s3.SIM3D_DISPLAY_QUADS_MAX = original
        self.assertLess(coarse.shape[0], fine.shape[0])

    def test_uncut_stock_uses_a_fast_closed_box_mesh(self):
        stock = make_stock(res=0.5, x=(-10.0, 10.0), y=(-5.0, 5.0), z=(-4.0, 0.0))
        verts, faces, colors, edges = stock.display_mesh()
        self.assertEqual(verts.shape[0], 8)
        self.assertEqual(faces.shape[0], 12)
        self.assertEqual(edges.shape[0], 24)                       # 12 모서리
        tri = verts[faces].astype(np.float64)
        volume = np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
        self.assertAlmostEqual(volume, 20.0 * 10.0 * 4.0, places=3)     # 법선이 바깥쪽
        keys = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
        _u, counts = np.unique(keys, axis=0, return_counts=True)
        self.assertTrue(np.all(counts == 2))
        self.assertEqual(colors.shape, (8, 4))

    def test_surface_mesh_is_cached_until_the_stock_changes(self):
        stock = self._cut_stock()
        first = stock.display_mesh()[0]
        second = stock.display_mesh(mode='depth')[0]
        self.assertIs(first, second)                                # 색상 모드만 바꾸면 재추출 안 함
        stock.cut_segment([-6.0, 3.0, -4.0], [6.0, 3.0, -4.0], flat(6.0, 10.0), axis0=Z_AXIS)
        self.assertIsNot(first, stock.display_mesh()[0])

    def test_empty_stock_meshes_to_a_box(self):
        stock = make_stock(res=2.0)
        verts, faces, _c, _e = stock.display_mesh()
        self.assertGreater(faces.shape[0], 0)
        self.assertEqual(stock.removed_fraction(), 0.0)


if __name__ == '__main__':
    unittest.main()
