"""nc_lathe_sim.py(선반 축대칭 시뮬레이션 엔진, v2.2.0 M1) 단위 테스트. Qt 비의존."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import lathe_insert_spec as spec
import nc_lathe_sim as lathe
import nc_sim


def make_geometry(**overrides):
    row = {'INSERT': 'CNMG 120408', 'HOLDER': 'PCLNR 2525M 12', 'KIND': '외경', 'DIR': 'R', 'TIP': '3',
           'R': '0.8'}
    row.update(overrides)
    return spec.geometry_from_row(row)


def turning_tool(**overrides):
    poly, _tip = lathe.insert_polygon(make_geometry(**overrides))
    return lathe.LatheTool(poly, kind='외경')


def groove_tool(width='3', tip='3', kind='외경홈', corner='0.4'):
    geometry = spec.geometry_from_row({'INSERT': 'GRV', 'HOLDER': '', 'KIND': kind, 'TIP': tip,
                                       'R': corner, 'T': width})
    poly, _tip = lathe.groove_polygon(geometry)
    return lathe.LatheTool(poly, kind=kind)


def make_stock(diameter=50.0, length=40.0, front=0.0, bore=0.0, res=0.05):
    return lathe.LatheStock(lathe.LatheStockSpec(diameter, length, front, bore).bounds(), res)


def path(*points):
    """(z, r) 점열 -> P0, P1 (월드 좌표 (z, 0, r))."""
    pts = np.array([[z, 0.0, r] for z, r in points], dtype=np.float64)
    return pts[:-1], pts[1:]


def cut(stock, tools, points, tool=0, rapid=False, color=0, **kwargs):
    p0, p1 = path(*points)
    n = len(p0)
    stock.cut_batch(p0, p1, tools, [tool] * n, [rapid] * n, [color] * n, **kwargs)


def outer_radius(stock, z):
    iz = int((z - stock.z0) / stock.dz)
    filled = np.nonzero(stock.occ[iz])[0]
    return (filled.max() + 1) * stock.dr if filled.size else 0.0


def inner_radius(stock, z):
    iz = int((z - stock.z0) / stock.dz)
    filled = np.nonzero(stock.occ[iz])[0]
    return filled.min() * stock.dr if filled.size else 0.0


class ToolPolygonTests(unittest.TestCase):
    def test_virtual_tip_touches_the_origin_and_area_matches_the_rhombus(self):
        poly, tip = lathe.insert_polygon(make_geometry())
        self.assertEqual(tip, '3')
        # 가상 인선 = 노즈 원의 X·Z 접선 교점 → 원점에서 다각형은 +z, +r 쪽으로만 뻗고 최소 z·r ≈ 0
        self.assertAlmostEqual(float(poly[:, 0].min()), 0.0, delta=0.02)
        self.assertAlmostEqual(float(poly[:, 1].min()), 0.0, delta=0.02)
        self.assertGreater(lathe._signed_area(poly), 0)                       # 반시계
        side = spec.parse_insert('CNMG120408')['edge_length']                 # 12.9
        self.assertAlmostEqual(lathe._signed_area(poly), side * side * math.sin(math.radians(80)),
                               delta=3.0)                                    # 노즈 R로 조금 깎임

    def test_tip_numbers_mirror_the_tool(self):
        base, _ = lathe.insert_polygon(make_geometry())                        # 인선 3 = 기준
        base_z = (float(base[:, 0].min()), float(base[:, 0].max()))
        base_r = (float(base[:, 1].min()), float(base[:, 1].max()))
        for tip, (mirror_z, mirror_r) in {'2': (True, False), '4': (False, True), '1': (True, True)}.items():
            poly, used = lathe.insert_polygon(make_geometry(TIP=tip))
            self.assertEqual(used, tip)
            self.assertGreater(lathe._signed_area(poly), 0)                    # 뒤집어도 반시계 유지
            want_z = (-base_z[1], -base_z[0]) if mirror_z else base_z
            want_r = (-base_r[1], -base_r[0]) if mirror_r else base_r
            self.assertAlmostEqual(float(poly[:, 0].min()), want_z[0], delta=1e-6)
            self.assertAlmostEqual(float(poly[:, 0].max()), want_z[1], delta=1e-6)
            self.assertAlmostEqual(float(poly[:, 1].min()), want_r[0], delta=1e-6)
            self.assertAlmostEqual(float(poly[:, 1].max()), want_r[1], delta=1e-6)
        # 인선을 비우면 종류로 정한다 — 외경 3, 내경 4
        self.assertEqual(lathe.insert_polygon(make_geometry(TIP=''))[1], '3')
        self.assertEqual(lathe.insert_polygon(make_geometry(TIP='', KIND='내경'))[1], '4')

    def test_all_iso_shapes_build_convex_polygons(self):
        for insert, holder in (('CNMG 120408', 'PCLNR 2525M 12'), ('DNMG 150404', 'PDJNR 2525M 15'),
                               ('TNMG 160404', 'MTJNR 2525M 16'), ('VNMG 160408', 'SVJCR 2525 M16'),
                               ('WNMG 080408', 'PWLNR 2525M 08'), ('SNMG 120408', 'PSKNR 2525M 12'),
                               ('RCMT 1204MO', 'SRDCN 2525M12')):
            poly, _ = lathe.insert_polygon(make_geometry(INSERT=insert, HOLDER=holder, R='0.8'))
            self.assertGreater(lathe._signed_area(poly), 5.0, insert)
            edges = np.roll(poly, -1, axis=0) - poly
            cross = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
            self.assertTrue(np.all(cross >= -1e-9), '볼록이어야 함: ' + insert)

    def test_unknown_or_incomplete_inserts_are_refused_with_a_reason(self):
        with self.assertRaises(lathe.ToolShapeError) as ctx:
            lathe.insert_polygon(make_geometry(INSERT='MINTR07-140015D050', HOLDER='MINSL 16-4-7'))
        self.assertIn('INSERT', str(ctx.exception))
        with self.assertRaises(lathe.ToolShapeError):
            lathe.groove_polygon(spec.geometry_from_row({'INSERT': 'X', 'KIND': '외경홈', 'T': ''}))

    def test_groove_polygons_by_kind_and_reference_corner(self):
        # 외경홈 인선 3: 왼쪽(-z) 모서리 기준, 폭이 z 방향, 홀더는 +r쪽
        poly = groove_tool('3', '3').poly
        self.assertAlmostEqual(poly[:, 0].min(), 0.0)
        self.assertAlmostEqual(poly[:, 0].max(), 3.0)
        self.assertAlmostEqual(poly[:, 1].min(), 0.0)
        self.assertGreater(poly[:, 1].max(), 10.0)
        # 인선 2 = 오른쪽 모서리, 9 = 중심
        self.assertAlmostEqual(groove_tool('3', '2').poly[:, 0].max(), 0.0)
        self.assertAlmostEqual(groove_tool('3', '9').poly[:, 0].min(), -1.5)
        # 정면홈 인선 4 = 바깥(+r) 모서리, 폭이 r 방향, 홀더는 +z쪽
        face = groove_tool('3.18', '4', kind='정면홈').poly
        self.assertAlmostEqual(face[:, 1].min(), -3.18)
        self.assertAlmostEqual(face[:, 1].max(), 0.0)
        self.assertAlmostEqual(face[:, 0].min(), 0.0)
        self.assertGreater(face[:, 0].max(), 10.0)
        # 내경홈은 홀더가 -r쪽
        internal = groove_tool('3', '4', kind='내경홈').poly
        self.assertLess(internal[:, 1].min(), -10.0)
        self.assertAlmostEqual(internal[:, 1].max(), 0.0)

    def test_center_tool_uses_so_as_the_max_flute_length(self):
        geometry = spec.geometry_from_row({'INSERT': 'D12 CARBIDE DRILL', 'KIND': '드릴', 'D': '12', 'SO': '40'})
        tool = lathe.tool_from_geometry(geometry)
        self.assertAlmostEqual(tool.poly[:, 1].max(), 6.0, places=3)         # 반경 D/2
        self.assertAlmostEqual(tool.poly[:, 0].max(), 40.0, places=3)       # SO = 날장 최대(결정 J)
        self.assertEqual(tool.notes, ())
        unlimited = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': 'D12 CARBIDE DRILL', 'KIND': '드릴', 'D': '12', 'SO': ''}))
        self.assertGreaterEqual(unlimited.poly[:, 0].max(), 999.0)
        self.assertIn('SO', unlimited.notes[0])                               # 무제한 안내
        # 118° 선단: 반경 6에서 높이 6/tan(59°)
        at_radius = tool.poly[tool.poly[:, 1] >= 6.0 - 1e-9, 0]              # 반경 6인 꼭짓점들(원뿔 끝 + 날 끝)
        self.assertAlmostEqual(float(at_radius.min()), 6.0 / math.tan(math.radians(59.0)), places=2)

    def test_tool_from_geometry_kinds_and_refusals(self):
        self.assertEqual(lathe.tool_from_geometry(make_geometry()).kind, '외경')
        thread = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': '16ER 1.5 ISO', 'HOLDER': 'SER 2525M16', 'KIND': '외경나사'}))
        self.assertEqual((thread.kind, thread.thread_angle, thread.internal), ('외경나사', 60.0, False))
        self.assertTrue(lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': '16IR 1.5 ISO', 'HOLDER': 'SIR 0016 M16', 'KIND': '내경나사'})).internal)
        for kind, text in (('비절삭', '비절삭'), ('', '종류를 모름')):
            with self.assertRaises(lathe.ToolShapeError) as ctx:
                lathe.tool_from_geometry(spec.geometry_from_row({'INSERT': 'D10 X', 'KIND': kind, 'D': '10'}))
            self.assertIn(text, str(ctx.exception))
        # 페이스커터: 선삭 단면은 없고(축대칭으로 쓰지 않음) 턴밀 형상만 있다
        face = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': 'D50. FACE CUTTER', 'KIND': '페이스커터', 'D': '50', 'SO': '40'}))
        self.assertIsNone(face.poly)
        self.assertAlmostEqual(face.mill_shape.radius, 25.0)
        self.assertAlmostEqual(face.mill_shape.cut_length, 40.0)                 # SO = 날장 최대
        # 드릴·엔드밀: 선삭 단면(중심 드릴) + 턴밀 형상 둘 다
        drill = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': 'D6 CARBIDE DRILL', 'KIND': '드릴', 'D': '6'}))
        self.assertIsNotNone(drill.poly)
        self.assertAlmostEqual(drill.mill_shape.radius, 3.0)
        self.assertGreaterEqual(drill.mill_shape.cut_length, 999.0)             # SO 없음 → 무제한
        # 선삭 공구에는 턴밀 형상이 없다
        self.assertIsNone(lathe.tool_from_geometry(make_geometry()).mill_shape)
        with self.assertRaises(lathe.ToolShapeError):                          # 지름 없음
            lathe.tool_from_geometry(spec.geometry_from_row({'INSERT': 'DRILL', 'KIND': '드릴'}))


class StockAndCuttingTests(unittest.TestCase):
    def test_stock_grid_and_bore(self):
        stock = make_stock(50.0, 40.0, front=0.0, bore=10.0, res=0.1)
        self.assertAlmostEqual(stock.z0, -40.0)
        self.assertEqual((stock.nz, stock.nr), (400, 250))
        self.assertAlmostEqual(outer_radius(stock, -20.0), 25.0, places=6)
        self.assertAlmostEqual(inner_radius(stock, -20.0), 5.0, delta=0.11)   # 내경 Ø10
        self.assertFalse(stock.any_cut())
        self.assertEqual(stock.removed_fraction(), 0.0)

    def test_auto_resolution_is_clamped(self):
        res = lathe.auto_resolution(lathe.LatheStockSpec(100.0, 60.0).bounds())
        self.assertAlmostEqual(res, math.sqrt(60.0 * 50.0 / 4_000_000), delta=0.001)
        self.assertEqual(lathe.auto_resolution(lathe.LatheStockSpec(2.0, 2.0).bounds()), lathe.LATHE_MIN_RES)
        self.assertEqual(lathe.auto_resolution(lathe.LatheStockSpec(2000.0, 3000.0).bounds()), lathe.LATHE_MAX_RES)
        safe = lathe.auto_resolution(lathe.LatheStockSpec(100.0, 60.0).bounds(), safe_mode=True)
        self.assertGreater(safe, res)

    def test_external_turning_leaves_the_programmed_diameter(self):
        stock = make_stock()
        cut(stock, [turning_tool()], [(2.0, 20.0), (-30.0, 20.0)])           # 지름 40, 척 쪽(-Z)으로
        for z in (-1.0, -10.0, -29.0):
            self.assertAlmostEqual(outer_radius(stock, z), 20.0, delta=0.05)
        self.assertAlmostEqual(outer_radius(stock, -35.0), 25.0, delta=0.05)  # 이송 끝 뒤는 그대로
        self.assertTrue(stock.any_cut())
        # 제거 체적: 부피 비율 = (25² − 20²) * 30 / (25² * 40)
        self.assertAlmostEqual(stock.removed_fraction(), (25 ** 2 - 20 ** 2) * 30 / (25 ** 2 * 40), delta=0.01)

    def test_roughing_removes_material_above_the_tip_line_not_only_a_thin_band(self):
        stock = make_stock()
        cut(stock, [turning_tool()], [(2.0, 21.0), (-30.0, 21.0)])
        # 팁이 r=21이면 인서트 몸체 높이(≈10mm)만큼 위 소재도 함께 사라진다(원 하나만 쓰던 모델의 결함 방지)
        self.assertAlmostEqual(outer_radius(stock, -10.0), 21.0, delta=0.05)

    def test_facing_to_the_axis_and_past_it(self):
        stock = make_stock()
        # 앞면 정삭: 팁이 z=-1 평면을 따라 r=30 → -0.5(축 지나침)로 이동
        cut(stock, [turning_tool()], [(-1.0, 30.0), (-1.0, -0.5)])
        iz_front = int((-0.4 - stock.z0) / stock.dz)
        self.assertEqual(int(stock.occ[iz_front].sum()), 0)                   # z > -1 쪽은 비었다
        iz_behind = int((-1.6 - stock.z0) / stock.dz)
        self.assertEqual(int(stock.occ[iz_behind].sum()), stock.nr)           # z < -1 쪽은 그대로

    def test_left_hand_tool_cuts_toward_the_tailstock(self):
        stock = make_stock()
        cut(stock, [turning_tool(DIR='L', TIP='2')], [(-30.0, 20.0), (-1.0, 20.0)])
        self.assertAlmostEqual(outer_radius(stock, -15.0), 20.0, delta=0.05)

    def test_internal_boring_leaves_the_programmed_bore(self):
        stock = make_stock(50.0, 40.0, bore=10.0)
        tool = turning_tool(INSERT='DNMG 150404', HOLDER='S25T-PCLNR 12', KIND='내경', TIP='4', R='0.4')
        cut(stock, [tool], [(2.0, 10.0), (-30.0, 10.0)])                     # 내경 Ø20 (팁 r=10, 몸체는 -r쪽)
        self.assertAlmostEqual(inner_radius(stock, -15.0), 10.0, delta=0.06)
        self.assertAlmostEqual(outer_radius(stock, -15.0), 25.0, delta=0.05)

    def test_turning_points_with_a_leftover_c_rotation_use_their_true_radius(self):
        """M35 뒤 C가 남은 채 선삭하면 점이 회전돼 온다(y = r, z ≈ 0) — 반경은 hypot(y, z)여야 한다."""
        a, b = make_stock(), make_stock()
        cut(a, [turning_tool()], [(2.0, 20.0), (-30.0, 20.0)])
        p0 = np.array([[2.0, 20.0, 0.0]])                                     # C90으로 돌아간 같은 점
        p1 = np.array([[-30.0, 20.0, 0.0]])
        b.cut_batch(p0, p1, [turning_tool()], [0], [False], [0])
        self.assertTrue(np.array_equal(a.occ, b.occ))

    def test_od_groove_width_and_depth(self):
        stock = make_stock()
        tool = groove_tool('3', '3')                                          # 인선 3: 왼쪽(-z) 모서리 기준
        cut(stock, [tool], [(-10.0, 30.0), (-10.0, 20.0), (-10.0, 30.0)])   # 팁 z=-10에서 r=20까지 플런지
        row = int(20.5 / stock.dr)
        empty = np.nonzero(stock.occ[:, row] == 0)[0]
        width = (empty.max() - empty.min() + 1) * stock.dz
        self.assertAlmostEqual(width, 3.0, delta=0.1)
        self.assertAlmostEqual(stock.z0 + empty.min() * stock.dz, -10.0, delta=0.06)   # 왼쪽 모서리 = 프로그램 z
        self.assertAlmostEqual(outer_radius(stock, -8.5), 20.0, delta=0.05)  # 홈 안(z -10~-7)은 r 20
        self.assertAlmostEqual(outer_radius(stock, -12.0), 25.0, delta=0.05)  # 홈 밖은 그대로
        self.assertAlmostEqual(outer_radius(stock, -5.0), 25.0, delta=0.05)

    def test_face_groove_reference_is_the_outer_corner(self):
        stock = make_stock()
        tool = groove_tool('3', '4', kind='정면홈')
        # 인선 4 = 바깥 모서리: 팁 r=20에서 z=-15까지 플런지 → 홈은 r 16.9~20
        cut(stock, [tool], [(2.0, 20.0), (-15.0, 20.0), (2.0, 20.0)])
        iz = int(-14.0 / stock.dz - stock.z0 / stock.dz)
        cells = np.nonzero(stock.occ[iz] == 0)[0]
        self.assertAlmostEqual((cells.max() + 1) * stock.dr, 20.0, delta=0.06)
        self.assertAlmostEqual(cells.min() * stock.dr, 17.0, delta=0.06)

    def test_center_drill_makes_a_hole_with_a_conical_bottom(self):
        stock = make_stock(50.0, 40.0)
        geometry = spec.geometry_from_row({'INSERT': 'D10 CARBIDE DRILL', 'KIND': '드릴', 'D': '10', 'SO': '60'})
        tool = lathe.tool_from_geometry(geometry)
        cut(stock, [tool], [(2.0, 0.0), (-20.0, 0.0), (2.0, 0.0)])          # 팁 z=-20까지
        self.assertAlmostEqual(inner_radius(stock, -10.0), 5.0, delta=0.06)  # 구멍 반경 5
        cone_h = 5.0 / math.tan(math.radians(59.0))                          # ≈ 3.0
        self.assertAlmostEqual(inner_radius(stock, -20.0 + cone_h * 0.5), 2.5, delta=0.15)   # 원뿔 중간
        self.assertAlmostEqual(outer_radius(stock, -10.0), 25.0, delta=0.05)

    def test_color_ids_record_the_last_cutting_process(self):
        stock = make_stock()
        tool = turning_tool()
        cut(stock, [tool], [(2.0, 22.0), (-30.0, 22.0)], color=1)          # 팁 r=22: r 22 위(몸체 포함)를 깎음
        cut(stock, [tool], [(2.0, 20.0), (-30.0, 20.0)], color=2)          # 팁 r=20: 남은 r 20~22를 깎음
        iz = int((-10.0 - stock.z0) / stock.dz)
        self.assertEqual(int(stock.col[iz, int(24.0 / stock.dr)]), 1)         # 처음 깎은 곳은 공정 1
        self.assertEqual(int(stock.col[iz, int(21.0 / stock.dr)]), 2)         # 나중에 깎은 곳은 공정 2
        self.assertEqual(int(stock.col[iz, int(10.0 / stock.dr)]), lathe.UNCUT_COLOR)   # 소재 안쪽은 미절삭

    def test_tools_without_a_shape_are_skipped(self):
        stock = make_stock()
        p0, p1 = path((2.0, 20.0), (-30.0, 20.0))
        stock.cut_batch(p0, p1, [None], [0], [False], [0])
        self.assertFalse(stock.any_cut())
        stock.cut_batch(p0, p1, [turning_tool()], [-1], [False], [0])
        self.assertFalse(stock.any_cut())

    def test_rapid_moves_through_material_are_warned_not_cut(self):
        stock = make_stock()
        tool = turning_tool()
        p0, p1 = path((2.0, 40.0), (2.0, 10.0), (-30.0, 10.0), (-30.0, 40.0))
        n = len(p0)
        stock.cut_batch(p0, p1, [tool], [0] * n, [True] * n, [0] * n,
                        src_lines=[11, 12, 13], seqs=[1, 2, 3])
        self.assertFalse(stock.any_cut())                                     # 급속은 깎지 않는다
        lines = {line for line, _seq in stock.rapid_cut_warnings}
        self.assertEqual(lines, {12, 13})       # 소재 속을 지나는 두 이동만(공중 접근 11번은 아님)

    def test_grazing_contact_below_the_area_threshold_is_not_warned(self):
        stock = make_stock(50.0, 40.0, res=0.05)
        tool = turning_tool()
        cut(stock, [tool], [(2.0, 22.0), (-30.0, 22.0)])                       # 반경 22로 선삭
        # 팁 r=22 표면 위를 따라 급속 후퇴(닿기만 함) → 경고 없음
        p0, p1 = path((-10.0, 22.0), (10.0, 22.0))
        stock.cut_batch(p0, p1, [tool], [0], [True], [0], src_lines=[3], seqs=[3])
        self.assertEqual(stock.rapid_cut_warnings, [])
        # 표면(22)보다 0.6mm 아래(r 21.4)로 파고드는 급속은 겹친 면적이 기준(0.5mm²) 이상이라 경고
        p0, p1 = path((-10.0, 21.4), (10.0, 21.4))
        before = stock.occ.copy()
        stock.cut_batch(p0, p1, [tool], [0], [True], [0], src_lines=[4], seqs=[4])
        self.assertEqual([line for line, _seq in stock.rapid_cut_warnings], [4])
        self.assertTrue(np.array_equal(before, stock.occ))                      # 경고만 하고 깎지는 않는다
        # 기준 미만의 스침: 표면 0.005mm 아래(겹친 면적 ≈ 0.005 x 길이 < 0.5mm²)는 무시
        fresh = make_stock(50.0, 40.0, res=0.05)
        cut(fresh, [tool], [(2.0, 22.0), (-30.0, 22.0)])
        p0, p1 = path((-10.0, 21.995), (-9.0, 21.995))
        fresh.cut_batch(p0, p1, [tool], [0], [True], [0], src_lines=[5], seqs=[5])
        self.assertEqual(fresh.rapid_cut_warnings, [])

    def test_thread_carves_v_grooves_at_the_pitch_and_is_not_a_rapid_warning(self):
        stock = make_stock(20.0, 30.0, res=0.02)
        tool = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': '16ER 1.5 ISO', 'HOLDER': 'SER 2525M16', 'KIND': '외경나사'}))
        # G76 둘째 줄: 시작 (z 3, r 15) → 끝 (z -10, r 9.2), 피치 1.5, 나사산 높이 0.8
        stock.cut_batch(np.array([[3.0, 0.0, 15.0]]), np.array([[-10.0, 0.0, 9.2]]), [tool], [0], [True], [1],
                        src_lines=[5], seqs=[5], thread_pitch=[1.5], thread_height=[0.8], use_numba=False)
        self.assertEqual(stock.rapid_cut_warnings, [])                        # 급속 사선이 아니라 나사 구간
        self.assertEqual(stock.thread_cut_count, 1)
        zs = np.arange(-9.5, -0.5, stock.dz)
        profile = np.array([outer_radius(stock, z) for z in zs])
        self.assertAlmostEqual(profile.max(), 10.0, delta=0.03)              # 산 = 원래 외경
        self.assertAlmostEqual(profile.min(), 9.2, delta=0.03)               # 골 = 프로그램 끝 X
        valleys = ((profile[1:] < 9.6) & (profile[:-1] >= 9.6)).sum()
        self.assertIn(int(valleys), (5, 6))                                   # z -9.5~-0.5에 피치 1.5 홈이 6개 안팎
        # 골 간격 = 피치
        centers = zs[profile < 9.3]
        gaps = np.diff(centers[np.diff(centers, prepend=-99) > 0.3])
        self.assertAlmostEqual(float(np.median(gaps)), 1.5, delta=0.05)

    def test_thread_does_not_eat_the_shoulder_beyond_its_end_but_clears_slightly_oversize_stock(self):
        tool = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': '16ER 1.5 ISO', 'HOLDER': 'SER 2525M16', 'KIND': '외경나사'}))
        # 소재 반경 20(어깨) 중 z -12 앞쪽만 반경 9.5로 선삭돼 있다고 하고, 나사(끝 z -12)를 판다
        # (한 번에 깎는 깊이 10.5mm는 인서트 날 길이 안이다)
        stock = make_stock(40.0, 40.0, res=0.02)
        cut(stock, [turning_tool()], [(2.0, 9.5), (-12.0, 9.5)])
        stock.cut_batch(np.array([[5.0, 0.0, 12.0]]), np.array([[-12.0, 0.0, 8.56]]), [tool], [0], [True], [1],
                        thread_pitch=[1.5], thread_height=[0.914], use_numba=False)
        self.assertAlmostEqual(outer_radius(stock, -20.0), 20.0, delta=0.05)  # 나사 끝 뒤 어깨는 그대로
        zs = np.arange(-11.0, -1.0, stock.dz)
        profile = np.array([outer_radius(stock, z) for z in zs])
        self.assertAlmostEqual(float(profile.min()), 8.56, delta=0.03)
        # 큰 지름(8.56 + 0.914 = 9.474)보다 0.03 큰 소재라도 골 위에 막이 남지 않는다
        self.assertLess(float(np.sort(profile)[len(profile) // 2]), 9.5)

    def test_internal_thread_carves_outward_from_the_bore(self):
        stock = make_stock(30.0, 30.0, bore=16.0, res=0.02)
        tool = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': '16IR 1.5 ISO', 'HOLDER': 'SIR 0016 M16', 'KIND': '내경나사'}))
        # 내경 나사: 끝 r = 큰 지름(골) 8.8, 나사산 높이 0.8 → 안쪽 8.0에서 8.8까지
        stock.cut_batch(np.array([[3.0, 0.0, 7.0]]), np.array([[-10.0, 0.0, 8.8]]), [tool], [0], [True], [1],
                        thread_pitch=[1.5], thread_height=[0.8], use_numba=False)
        zs = np.arange(-9.5, -0.5, stock.dz)
        bore = np.array([inner_radius(stock, z) for z in zs])
        self.assertAlmostEqual(bore.min(), 8.0, delta=0.03)                  # 보어 Ø16 그대로(산)
        self.assertAlmostEqual(bore.max(), 8.8, delta=0.03)                  # 골

    def test_numba_and_numpy_paths_agree(self):
        if not nc_sim.numba_available():
            self.skipTest('numba 없음')
        rng = np.random.default_rng(5)
        n = 300
        z = np.cumsum(rng.uniform(-1.5, 0.3, n)) - 2.0
        r = np.clip(20 + np.cumsum(rng.uniform(-0.6, 0.6, n)), 8, 30)
        pts = np.zeros((n + 1, 3))
        pts[1:, 0], pts[1:, 2] = z, r
        pts[0] = (2.0, 0.0, 30.0)
        tools = [turning_tool(), groove_tool('3', '3')]
        idx = rng.integers(0, 2, n)
        rapid = rng.random(n) < 0.15
        color = rng.integers(0, 4, n)
        results = []
        for use_numba in (False, True):
            stock = make_stock(60.0, 60.0, res=0.1)
            stock.cut_batch(pts[:-1], pts[1:], tools, idx, rapid, color, src_lines=np.arange(n),
                            seqs=np.arange(n), use_numba=use_numba)
            results.append(stock)
        self.assertTrue(np.array_equal(results[0].occ, results[1].occ))
        self.assertTrue(np.array_equal(results[0].col, results[1].col))
        self.assertEqual(results[0].rapid_cut_warnings, results[1].rapid_cut_warnings)
        self.assertGreater(results[0].removed_fraction(), 0.1)

    def test_chunking_progress_and_cancel(self):
        stock = make_stock()
        pts = [(2.0 - i * 0.5, 20.0) for i in range(40)]
        p0, p1 = path(*pts)
        seen = []
        finished = stock.cut_batch(p0, p1, [turning_tool()], [0] * 39, [False] * 39, [0] * 39,
                                   chunk=10, progress=lambda done, total: seen.append((done, total)),
                                   use_numba=False)
        self.assertTrue(finished)
        self.assertEqual(seen[-1], (39, 39))
        other = make_stock()
        calls = {'n': 0}

        def cancel():
            calls['n'] += 1
            return calls['n'] > 2

        self.assertFalse(other.cut_batch(p0, p1, [turning_tool()], [0] * 39, [False] * 39, [0] * 39,
                                         chunk=10, cancel=cancel, use_numba=False))
        self.assertLess(other.removed_fraction(), stock.removed_fraction())

    def test_snapshot_restore_clone_reset(self):
        stock = make_stock()
        cut(stock, [turning_tool()], [(2.0, 22.0), (-30.0, 22.0)])
        snap = stock.snapshot()
        clone = stock.clone()
        cut(stock, [turning_tool()], [(2.0, 20.0), (-30.0, 20.0)], color=3)
        self.assertLess(outer_radius(stock, -10.0), outer_radius(clone, -10.0))   # 복사본은 그대로
        stock.restore(snap)
        self.assertAlmostEqual(outer_radius(stock, -10.0), 22.0, delta=0.05)
        self.assertTrue(np.array_equal(stock.occ, clone.occ))
        self.assertLess(lathe.LatheStock.snapshot_bytes(snap), stock.occ.nbytes)   # 압축
        stock.reset()
        self.assertFalse(stock.any_cut())
        self.assertEqual(stock.rapid_cut_warnings, [])


class EntryAxisTests(unittest.TestCase):
    """턴밀 공구 축 = 가공 묶음 진입 벡터의 반대 방향(사용자 결정 I)."""

    def test_face_drilling_plunge_gives_plus_x(self):
        p0 = [[5, 0, 8], [1, 0, 8], [-6, 0, 8]]
        p1 = [[1, 0, 8], [-6, 0, 8], [5, 0, 8]]
        axes, corrected = lathe.entry_axes(p0, p1, [True, False, True], [True, False, False], ['G17'] * 3)
        np.testing.assert_allclose(axes, [[1, 0, 0]] * 3)
        self.assertEqual(corrected, 0)

    def test_radial_drilling_gives_the_outward_radial_axis_at_the_c_angle(self):
        c = math.radians(60.0)
        out = np.array([0.0, math.sin(c), math.cos(c)])
        start, bottom = 30.0 * out + [-10, 0, 0], 10.0 * out + [-10, 0, 0]
        axes, corrected = lathe.entry_axes([start, start], [bottom, start + 0.0 * out], [False, True],
                                           [True, False], ['G19', 'G19'])
        np.testing.assert_allclose(axes[0], out, atol=1e-9)
        np.testing.assert_allclose(axes[1], out, atol=1e-9)                    # 급속은 앞 묶음 축
        self.assertEqual(corrected, 0)

    def test_g19_side_face_milling_with_y_offset_keeps_the_machine_x_axis(self):
        """O4811 T12(D50 페이스커터, G19, Y-34.273 옆면 가공) 실측 — 진입(기계 -X)이 맞는데 공구 위치의 반경 방향을
        법선으로 쓰면 비스듬한 축으로 잘못 보정됐다. G19 법선은 C 각도의 기계 X 방향이다."""
        p0 = [[-27.0, -34.3, 17.2], [-27.0, -34.3, 14.2]]
        p1 = [[-27.0, -34.3, 14.2], [-27.0, -6.8, 14.2]]
        axes, corrected = lathe.entry_axes(p0, p1, [False, False], [True, False], ['G19', 'G19'], [0.0, 0.0])
        np.testing.assert_allclose(axes, [[0, 0, 1], [0, 0, 1]], atol=1e-9)
        self.assertEqual(corrected, 0)
        # C 90°면 기계 X 방향 = 월드 (0, 1, 0)
        np.testing.assert_allclose(lathe.plane_normal('G19', (0, 5, 5), 90.0), [0, 1, 0], atol=1e-12)
        np.testing.assert_allclose(lathe.plane_normal('G19', (0, 3, 4), None), [0, 0.6, 0.8])   # C를 모를 때

    def test_side_entry_is_corrected_to_the_plane_normal_and_counted(self):
        # G17(축방향) 평면인데 진입이 옆(y 방향)으로 들어온다 → 평면 법선(+X)로 보정
        axes, corrected = lathe.entry_axes([[-2, 20, 5]], [[-2, 10, 5]], [False], [True], ['G17'])
        np.testing.assert_allclose(axes[0], [1, 0, 0])
        self.assertEqual(corrected, 1)
        # 평면을 모르면(G18 등) 진입 벡터 그대로
        axes, corrected = lathe.entry_axes([[-2, 20, 5]], [[-2, 10, 5]], [False], [True], ['G18'])
        np.testing.assert_allclose(axes[0], [0, 1, 0])
        self.assertEqual(corrected, 0)

    def test_each_bundle_after_a_rapid_gets_its_own_axis_and_breaks_split_bundles(self):
        # 묶음 1: -x로 플런지(축 +x) 뒤 옆으로 이동 → 급속 후퇴 → 급속 이동 → 급속 접근 → 묶음 2: -z로 플런지(축 +z)
        p0 = [[0, 0, 8], [-3, 0, 8], [-3, 4, 8], [10, 4, 8], [-10, 0, 40], [-10, 0, 30], [-10, 0, 20]]
        p1 = [[-3, 0, 8], [-3, 4, 8], [10, 4, 8], [-10, 0, 40], [-10, 0, 30], [-10, 0, 20], [-10, 0, 40]]
        rapid = [False, False, True, True, True, False, True]
        axes, _c = lathe.entry_axes(p0, p1, rapid, [True] + [False] * 6, [None] * 7)
        np.testing.assert_allclose(axes[0], [1, 0, 0])
        np.testing.assert_allclose(axes[1], [1, 0, 0])                         # 같은 묶음은 같은 축
        np.testing.assert_allclose(axes[2], [1, 0, 0])                         # 후퇴 = 앞 묶음 자세
        np.testing.assert_allclose(axes[3], [1, 0, 0])                         # 중간 급속 = 앞 묶음
        np.testing.assert_allclose(axes[4], [0, 0, 1])                         # 마지막 접근 = 뒤 묶음
        np.testing.assert_allclose(axes[5], [0, 0, 1])
        np.testing.assert_allclose(axes[6], [0, 0, 1])                         # 마지막 후퇴 = 앞(묶음 2)
        # 두 묶음 사이 급속이 하나뿐이면 후퇴로 본다(앞 묶음 축)
        axes, _c = lathe.entry_axes([[0, 0, 8], [-3, 0, 8], [-10, 0, 30]], [[-3, 0, 8], [-10, 0, 30], [-10, 0, 20]],
                                    [False, True, False], [True, False, False], [None] * 3)
        np.testing.assert_allclose(axes[1], [1, 0, 0])
        # breaks(공정 경계)는 급속이 없어도 묶음을 나눈다
        axes, _c = lathe.entry_axes([[0, 0, 8], [-10, 0, 30]], [[-3, 0, 8], [-10, 0, 20]], [False, False],
                                    [True, True], [None, None])
        np.testing.assert_allclose(axes[1], [0, 0, 1])


class TurnMillStockTests(unittest.TestCase):
    def setUp(self):
        self.spec = lathe.LatheStockSpec(40.0, 30.0, 0.0)
        bounds = self.spec.bounds()
        self.vres = 0.25
        self.stock = lathe.TurnMillStock(bounds, 0.05, self.vres)
        self.turn = turning_tool()
        self.drill = lathe.tool_from_geometry(spec.geometry_from_row(
            {'INSERT': 'D6 CARBIDE DRILL', 'KIND': '드릴', 'D': '6', 'SO': '30'}))

    def voxel(self, stock, x, y, z):
        v = stock.voxel
        return bool(v.occ[int((x - v.x0) / v.step[0]), int((y - v.y0) / v.step[1]), int((z - v.z0) / v.step[2])])

    def program(self):
        # 선삭(반경 15, z 2 → -20) + 정면 드릴 2개(C0: 월드 (x, 0, 8), C90: (x, 8, 0)), 깊이 z -6
        moves = [((2, 0, 15.0), (-20, 0, 15.0), 0, False, False)]
        for y, z in ((0.0, 8.0), (8.0, 0.0)):
            moves += [((5, y, z), (1, y, z), 1, True, True), ((1, y, z), (-6, y, z), 1, False, True),
                      ((-6, y, z), (5, y, z), 1, True, True)]
        p0 = np.array([m[0] for m in moves], float)
        p1 = np.array([m[1] for m in moves], float)
        idx = np.array([m[2] for m in moves])
        rapid = np.array([m[3] for m in moves])
        mill = np.array([m[4] for m in moves])
        color = np.where(mill, 1, 0)
        axes, _c = lathe.entry_axes(p0, p1, rapid, np.r_[True, np.zeros(len(moves) - 1, bool)], ['G17'] * len(moves))
        return p0, p1, idx, rapid, mill, color, axes

    def test_initial_voxels_form_the_cylinder(self):
        v = self.stock.voxel
        expected = math.pi * 20 * 20 * 30 / self.vres ** 3
        self.assertAlmostEqual(int(v.occ.sum()) / expected, 1.0, delta=0.02)
        self.assertTrue(self.voxel(self.stock, -10, 0, 19.5))
        self.assertFalse(self.voxel(self.stock, -10, 14.5, 14.5))            # 반경 20.5 밖(모서리)
        self.assertFalse(self.stock.any_cut())

    def test_turning_and_axial_drilling_combine(self):
        p0, p1, idx, rapid, mill, color, axes = self.program()
        self.stock.cut_batch(p0, p1, [self.turn, self.drill], idx, rapid, color, axes0=axes, axes1=axes,
                             mill=mill, use_numba=False)
        st = self.stock
        st.sync()
        self.assertTrue(st.any_cut() and st.milled)
        self.assertFalse(self.voxel(st, -3, 0, 8))                             # C0 구멍
        self.assertFalse(self.voxel(st, -3, 8, 0))                             # C90 구멍
        self.assertTrue(self.voxel(st, -3, -8, 0))                             # 구멍 없는 C270
        self.assertTrue(self.voxel(st, -8, 0, 8))                              # 구멍 바닥(z -6) 아래
        self.assertFalse(self.voxel(st, -5, 0, 17))                            # 선삭으로 사라진 바깥
        self.assertTrue(self.voxel(st, -25, 0, 17))                            # 선삭 범위 밖 어깨
        self.assertEqual(st.rapid_cut_warnings, [])
        # 구멍 벽의 색 = 턴밀 공정(1), 선삭 면의 색 = 공정 0
        v = st.voxel
        i = int((-3 - v.x0) / v.step[0])
        j = int((0 - v.y0) / v.step[1])
        k = int((8 - v.z0) / v.step[2])
        self.assertEqual(int(v.col[i, j, k]), 1)
        k2 = int((17 - v.z0) / v.step[2])
        self.assertEqual(int(v.col[int((-5 - v.x0) / v.step[0]), j, k2]), 0)

    def test_order_does_not_matter(self):
        p0, p1, idx, rapid, mill, color, axes = self.program()
        self.stock.cut_batch(p0, p1, [self.turn, self.drill], idx, rapid, color, axes0=axes, axes1=axes,
                             mill=mill, use_numba=False)
        other = lathe.TurnMillStock(self.spec.bounds(), 0.05, self.vres)
        order = list(range(1, len(p0))) + [0]                                 # 드릴 먼저, 선삭 나중
        other.cut_batch(p0[order], p1[order], [self.turn, self.drill], idx[order], rapid[order], color[order],
                        axes0=axes[order], axes1=axes[order], mill=mill[order], use_numba=False)
        self.stock.sync()
        other.sync()
        self.assertTrue(np.array_equal(self.stock.voxel.occ, other.voxel.occ))

    def test_rapid_into_material_during_turnmill_is_warned(self):
        p0 = np.array([[5.0, 0.0, 8.0], [5.0, 0.0, 8.0]])
        p1 = np.array([[-6.0, 0.0, 8.0], [5.0, 0.0, 8.0]])
        axes = np.tile([1.0, 0.0, 0.0], (2, 1))
        self.stock.cut_batch(p0, p1, [self.turn, self.drill], [1, 1], [True, True], [1, 1],
                             src_lines=[40, 41], seqs=[40, 41], axes0=axes, axes1=axes, mill=[True, True],
                             use_numba=False)
        self.assertIn(40, [line for line, _seq in self.stock.rapid_cut_warnings])

    def test_snapshot_restore_clone_reset(self):
        p0, p1, idx, rapid, mill, color, axes = self.program()
        snap0 = self.stock.snapshot()
        self.stock.cut_batch(p0, p1, [self.turn, self.drill], idx, rapid, color, axes0=axes, axes1=axes,
                             mill=mill, use_numba=False)
        after = self.stock.clone()
        snap1 = self.stock.snapshot()
        self.assertGreater(lathe.TurnMillStock.snapshot_bytes(snap1), 0)
        self.stock.restore(snap0)
        self.assertFalse(self.stock.any_cut())
        self.stock.restore(snap1)
        self.assertTrue(np.array_equal(self.stock.voxel.occ, after.voxel.occ))
        self.assertTrue(np.array_equal(self.stock.lathe.occ, after.lathe.occ))
        self.assertTrue(self.stock.milled)
        self.stock.reset()
        self.assertFalse(self.stock.any_cut())
        self.assertFalse(self.stock.milled)

    def test_display_sections_and_depth_colors(self):
        p0, p1, idx, rapid, mill, color, axes = self.program()
        self.stock.cut_batch(p0, p1, [self.turn, self.drill], idx, rapid, color, axes0=axes, axes1=axes,
                             mill=mill, use_numba=False)
        cmap = {0: (1.0, 0.0, 0.0, 1.0), 1: (0.0, 1.0, 0.0, 1.0)}
        v3, f3, c3, _e = self.stock.display_mesh(color_map=cmap, section='3q')
        self.assertFalse(((v3[:, 1] < -self.vres) & (v3[:, 2] > self.vres)).any())
        vh, _f, _c, _e = self.stock.display_mesh(section='half')
        self.assertFalse((vh[:, 1] < -self.vres).any())
        vf, ff, cf, _e = self.stock.display_mesh(color_map=cmap, section='full')
        self.assertTrue((vf[:, 1] < -5).any())
        self.assertLess(int(ff.max()), len(vf))
        has = lambda colors, c: bool((np.abs(colors - np.array(c, np.float32)).max(axis=1) < 1e-6).any())
        self.assertTrue(has(cf, cmap[0]) and has(cf, cmap[1]))
        _v, _f, depth, _e = self.stock.display_mesh(mode='depth', section='full')
        self.assertGreater(len({tuple(np.round(c, 3)) for c in depth}), 2)

    def test_voxel_resolution_targets_twenty_million(self):
        bounds = lathe.LatheStockSpec(100.0, 60.0).bounds()
        res = lathe.turnmill_voxel_resolution(bounds)
        voxels = (60.0 / res) * (100.0 / res) ** 2
        self.assertAlmostEqual(voxels / 20_000_000, 1.0, delta=0.1)
        self.assertGreater(lathe.turnmill_voxel_resolution(bounds, numba_ok=False), res)


class DisplayMeshTests(unittest.TestCase):
    def cut_stock(self):
        stock = make_stock(50.0, 40.0, res=0.1)
        cut(stock, [turning_tool()], [(2.0, 22.0), (-30.0, 22.0)], color=0)
        cut(stock, [groove_tool('3', '3')], [(-10.0, 30.0), (-10.0, 15.0), (-10.0, 30.0)], color=1)
        return stock

    def test_sections_have_expected_extents_and_valid_indices(self):
        stock = self.cut_stock()
        for section in ('3q', 'half', 'full'):
            verts, faces, colors, edges = stock.display_mesh(600, section=section)
            self.assertEqual(verts.dtype, np.float32)
            self.assertEqual((colors.shape[0], colors.shape[1]), (verts.shape[0], 4))
            self.assertGreater(len(faces), 100)
            self.assertLess(int(faces.max()), len(verts))
            self.assertLessEqual(float(np.hypot(verts[:, 1], verts[:, 2]).max()), 25.0 + 1e-3)
        v3, _f, _c, _e = stock.display_mesh(600, section='3q')
        self.assertFalse(((v3[:, 1] < -1e-4) & (v3[:, 2] > 1e-4)).any())      # 앞쪽 위 사분면(y<0, z>0)이 잘림
        vh, _f, _c, _e = stock.display_mesh(600, section='half')
        self.assertFalse((vh[:, 1] < -1e-4).any())                            # 앞쪽 반이 잘림
        vf, _f, _c, ef = stock.display_mesh(600, section='full')
        self.assertTrue((vf[:, 1] < -1).any() and (vf[:, 1] > 1).any())      # 전체는 양쪽 모두

    def test_full_view_has_no_caps_and_section_views_do(self):
        stock = self.cut_stock()
        cap = np.array(lathe.CAP_COLOR, dtype=np.float32)
        for section, has_caps in (('3q', True), ('half', True), ('full', False)):
            _v, _f, colors, _e = stock.display_mesh(600, section=section)
            found = bool((np.abs(colors - cap).max(axis=1) < 1e-6).any())
            self.assertEqual(found, has_caps, section)

    def test_process_colors_and_color_modes(self):
        stock = self.cut_stock()
        cmap = {0: (1.0, 0.0, 0.0, 1.0), 1: (0.0, 1.0, 0.0, 1.0)}
        _v, _f, tool_colors, _e = stock.display_mesh(600, color_map=cmap, mode='tool', section='full')
        has = lambda c: bool((np.abs(tool_colors - np.array(c, dtype=np.float32)).max(axis=1) < 1e-6).any())
        self.assertTrue(has(cmap[0]) and has(cmap[1]))                        # 두 공정 색이 모두 있다
        self.assertTrue(has(nc_sim.DEFAULT_STOCK_COLOR))                       # 미절삭 면(앞·뒤 끝면 등)
        _v, _f, solid, _e = stock.display_mesh(600, color_map=cmap, mode='solid', section='full')
        self.assertTrue(np.allclose(solid, np.array(nc_sim.DEFAULT_STOCK_COLOR, dtype=np.float32)))
        _v, _f, depth, _e = stock.display_mesh(600, mode='depth', section='full')
        self.assertGreater(len({tuple(np.round(c, 3)) for c in depth}), 2)

    def test_uncut_stock_is_a_plain_cylinder(self):
        stock = make_stock(50.0, 40.0, res=0.1)
        verts, faces, _c, edges = stock.display_mesh(600, section='full')
        radii = np.hypot(verts[:, 1], verts[:, 2])
        self.assertAlmostEqual(float(radii.max()), 25.0, places=3)
        self.assertAlmostEqual(float(verts[:, 0].min()), -40.0, places=3)
        self.assertAlmostEqual(float(verts[:, 0].max()), 0.0, places=3)

    def test_bore_surface_appears_and_display_is_capped_in_size(self):
        stock = make_stock(50.0, 40.0, bore=20.0, res=0.02)                   # 큰 격자 -> 표시용으로 합친다
        verts, faces, _c, _e = stock.display_mesh(300, section='3q')
        radii = np.hypot(verts[:, 1], verts[:, 2])
        self.assertLess(float(radii[radii > 1e-3].min()), 10.5)              # 내경(반경 10) 면이 있다
        self.assertLess(len(faces), 200_000)

    def test_theta_steps_scale_with_radius_and_span(self):
        self.assertGreaterEqual(lathe._theta_steps(100.0, 270.0), lathe._theta_steps(10.0, 270.0))
        self.assertLess(lathe._theta_steps(50.0, 180.0), lathe._theta_steps(50.0, 360.0))


if __name__ == '__main__':
    unittest.main()
