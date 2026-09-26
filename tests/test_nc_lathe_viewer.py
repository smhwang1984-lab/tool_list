"""선반 형상 시뮬레이션의 뷰어 통합 테스트(v2.2.0 M1): 줄 정보(M35·G76), 선분 배열, 백그라운드 계산,
스냅샷 되돌리기, 진단, 표시 메쉬, 소재 창. 실제 사용자 QSettings/장비 설정은 건드리지 않는다
(장비는 속성만 바꾸고 저장하지 않으며, 소재 창은 임시 ini 설정을 쓴다)."""
import os
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

try:
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QApplication
    import lathe_insert_spec as spec
    import nc_lathe_sim
    from nc_viewer_widget import LatheStockDialog, NCViewerWidget
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    IMPORT_ERROR = exc

LATHE = 'CNC 선반 (턴밀 포함)'
MILLING = '3축 MCT (X Y Z)'

# 공정 1: 외경 선삭(지름 19까지 Z-15), 공정 2: G76 나사(골 지름 17.12, 나사산 높이 0.914 → 큰 지름 ≈ 18.95, Z-12, 리드 1.5)
PROGRAM = """O0001
N1
( T01 - PCLNR 2525M 12 )
( T01 - CNMG 120408 | R-0.8 )
G0X400.Z200.
G28V0.
T0100
G50S1500
G96S225M3P11
T0101
G99G18X60.Z5.
G1Z2.F.2
G0X19.Z2.
G1Z-15.F.2
X41.
G0X400.Z200.T0100
M1

N2
( T05 - SER 2525 M16 )
( T05 - 16ER 1.5 ISO )
G0X400.Z200.
T0500
G97S800M3P11
T0505
G99G18X24.Z5.
G76P020060Q30R.02
G76X17.12Z-12.P914Q120R0.F1.5
G0X400.Z200.T0500
M1
M30
%
"""

ROWS = (
    {'NO': 'T0101', 'INSERT': 'CNMG 120408 | R-0.8', 'HOLDER': 'PCLNR 2525M 12'},
    {'NO': 'T0505', 'INSERT': '16ER 1.5 ISO', 'HOLDER': 'SER 2525 M16'},
)


def geometry_map(rows=ROWS):
    filled = []
    for row in rows:
        values, _sources = spec.resolve_fields(row['INSERT'], row['HOLDER'])
        filled.append(dict(row, **values))
    return spec.geometry_map_from_rows(filled)


def make_spec(diameter=40.0, length=40.0, front=0.0, bore=0.0):
    # 지름 40 = 반경 20: 한 번에 깎는 깊이(20 → 9.5 = 10.5mm)가 인서트 날 길이(≈13.9mm) 안에 든다
    return nc_lathe_sim.LatheStockSpec(diameter, length, front, bore)


def outer_radius(stock, z):
    iz = int((z - stock.z0) / stock.dz)
    filled = np.nonzero(stock.occ[iz])[0]
    return (filled.max() + 1) * stock.dr if filled.size else 0.0


@unittest.skipIf(IMPORT_ERROR is not None, 'viewer dependencies are not available')
class LatheViewerTests(unittest.TestCase):
    """뷰어 창은 무겁다 — 클래스당 하나를 공유하고 테스트마다 프로그램을 다시 읽힌다."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])
        cls.viewer = NCViewerWidget()
        cls.viewer.current_machine_type = LATHE                         # 저장 없이 속성만

    @classmethod
    def tearDownClass(cls):
        cls.viewer.deleteLater()
        cls.qapp.processEvents()

    def setUp(self):
        self.viewer._lathe_stock_dialog = None                             # 이전 테스트의 창은 이미 파괴됐다

    def load(self, program=PROGRAM, rows=ROWS):
        viewer = self.viewer
        viewer.current_machine_type = LATHE
        viewer.set_source_text(program, {}, geometry_map(rows))
        return viewer

    def apply(self, viewer, stock_spec=None, resolution=0.05):
        viewer._sim_sync = True
        viewer.apply_stock_spec(stock_spec or make_spec(), resolution, True)
        self.assertTrue(viewer.sim_wait())
        return viewer.sim_stock

    # -- 줄 정보와 선분 배열 -----------------------------------------------------
    def test_lathe_is_now_available_and_uses_the_lathe_engine(self):
        viewer = self.load()
        self.assertTrue(viewer.is_sim_available())
        self.assertEqual(viewer.sim_engine, 'lathe')
        self.assertEqual(len(viewer._sim_tools), 2)
        self.assertEqual(viewer._sim_lathe_excluded, {})
        seg = viewer.sim_seg
        for key in ('p0', 'p1', 'seq0', 'seq1', 'src', 'rapid', 'slot', 'color', 'thread_pitch', 'thread_height'):
            self.assertEqual(len(seg[key]), len(seg['seq1']), key)
        self.assertTrue(np.all(np.diff(seg['seq1']) >= 0))

    def test_line_info_marks_the_g76_second_line_only(self):
        viewer = self.load()
        threads = {line: info for line, info in viewer.line_lathe_map.items() if info[2]}
        self.assertEqual(len(threads), 1)
        (line, info), = threads.items()
        self.assertEqual(PROGRAM.splitlines()[line].strip(), 'G76X17.12Z-12.P914Q120R0.F1.5')
        self.assertEqual(info[2], (1.5, 0.914))                       # 리드 F, 나사산 높이 P(µm) → mm
        self.assertFalse(info[0])                                     # M35 구간 아님

    def test_virtual_origin_start_is_not_a_segment(self):
        viewer = self.load()
        seg = viewer.sim_seg
        self.assertFalse(np.any(np.all(seg['p0'] == 0.0, axis=1)))    # (0,0,0) 시작점에서 출발하는 선분이 없다

    def test_thread_segment_carries_pitch_and_height(self):
        viewer = self.load()
        seg = viewer.sim_seg
        idx = np.nonzero(seg['thread_pitch'] > 0)[0]
        self.assertEqual(len(idx), 1)
        m = int(idx[0])
        self.assertEqual((float(seg['thread_pitch'][m]), float(seg['thread_height'][m])), (1.5, 0.914))
        self.assertAlmostEqual(float(seg['p1'][m][2]), 8.56)          # 골 반경 = 끝 X 17.12 / 2
        self.assertAlmostEqual(float(seg['p1'][m][0]), -12.0)

    # -- 계산 ------------------------------------------------------------------------
    def test_turning_and_thread_cut_the_stock(self):
        viewer = self.load()
        stock = self.apply(viewer)
        self.assertTrue(stock.any_cut())
        self.assertAlmostEqual(outer_radius(stock, -14.0), 9.5, delta=0.06)     # 외경 Ø19(나사 구간 밖)
        self.assertAlmostEqual(outer_radius(stock, -20.0), 20.0, delta=0.06)   # 선삭 구간 밖(소재 반경)
        zs = np.arange(-11.5, -0.5, stock.dz)
        profile = np.array([outer_radius(stock, z) for z in zs])
        self.assertAlmostEqual(float(profile.min()), 8.56, delta=0.04)          # 나사 골(끝 X 17.12)
        self.assertAlmostEqual(float(profile.max()), 9.5, delta=0.06)           # 산 = 선삭한 외경
        self.assertEqual(stock.thread_cut_count, 1)
        self.assertEqual(stock.rapid_cut_warnings, [])                         # 급속 사선(G76)은 경고가 아니다
        self.assertEqual(viewer.sim_last_seq, viewer._sim_target_seq_for_selection())

    def test_after_a_g76_cycle_the_next_move_starts_from_the_cycle_start_point(self):
        """G76은 끝나면 시작점으로 복귀한다 — 그 뒤 급속 후퇴가 나사 끝점에서 나사산 위로 지나가는
        것으로 오인되면 급속 절삭 경고가 잘못 뜬다."""
        viewer = self.load()
        seg = viewer.sim_seg
        m = int(np.nonzero(seg['thread_pitch'] > 0)[0][0])
        self.assertLess(m + 1, len(seg['seq1']))
        np.testing.assert_allclose(seg['p0'][m + 1], seg['p0'][m])            # 다음 이동의 시작 = 나사 시작점
        self.assertFalse(np.allclose(seg['p0'][m + 1], seg['p1'][m]))

    def test_snapshots_are_taken_per_process_and_backward_seek_matches_a_fresh_run(self):
        viewer = self.load()
        self.apply(viewer)
        self.assertEqual(len(viewer._sim_snapshots), 2)
        seg = viewer.sim_seg
        first_end = int(seg['seq1'][seg['color'] == 0].max())
        viewer._sim_sync = True
        viewer._sim_advance_to_seq(first_end)                                  # 뒤로 — 공정 1까지만
        self.assertTrue(viewer.sim_wait())
        back = viewer.sim_stock.occ.copy()
        self.assertEqual(viewer.sim_stock.thread_cut_count, 0)                 # 나사는 아직 안 깎임
        fresh = self.load()
        fresh_stock = self.apply(fresh)
        fresh._sim_advance_to_seq(first_end)
        self.assertTrue(fresh.sim_wait())
        self.assertTrue(np.array_equal(back, fresh.sim_stock.occ))

    def test_excluded_tools_are_reported_with_a_reason_and_diagnosed(self):
        rows = (dict(ROWS[0], INSERT='MINTR07-140015D050', HOLDER='MINSL 16-4-7'),
                dict(ROWS[1], INSERT='16ER 1.5 ISO'))
        viewer = self.load(rows=rows)
        self.assertIn('T01', viewer._sim_lathe_excluded)
        self.assertIn('종류', viewer._sim_lathe_excluded['T01'])                # 규격 문구를 못 읽어 종류도 모름
        self.assertIn('T01', viewer.sim_status_text)
        stock = self.apply(viewer)
        self.assertEqual(stock.thread_cut_count, 1)                            # 나사 공구는 그대로 돈다
        viewer2 = self.load(rows=())
        self.assertEqual(len(viewer2._sim_lathe_excluded), 2)                  # 공구 정보 자체가 없다
        stock2 = self.apply(viewer2)
        self.assertFalse(stock2.any_cut())
        self.assertIn('깎을 수 있는 공구가 없습니다', viewer2.sim_diagnosis())

    def test_diagnosis_when_the_stock_is_away_from_the_toolpath(self):
        viewer = self.load()
        stock = self.apply(viewer, make_spec(50.0, 10.0, front=-100.0))        # 툴패스(Z -15~5)와 안 겹침
        self.assertFalse(stock.any_cut())
        self.assertIn('겹치지 않습니다', viewer.sim_diagnosis())
        viewer._sim_set_progress(viewer.sim_diagnosis(), warn=True)
        self.assertIn('겹치지', viewer.sim_notice_text)

    def test_turnmill_moves_are_counted_not_cut(self):
        program = PROGRAM.replace('M30\n%', """N3
( T06 - MILL TOOL CHECK )
( T06 - D10 X 90 NC DRILL )
G0X400.Z200.
M35
T0600
T0606
G98G17X200.Z10.
C0.Y0.
G97S800M3P12
G0X130.C90.
G83Z-4.95R-9.2P500F60.M89
C60.
G80
M34
G0X400.Z200.
M30
%""")
        rows = ROWS + ({'NO': 'T0606', 'INSERT': 'D10 X 90 NC DRILL', 'HOLDER': 'MILL TOOL CHECK'},)
        viewer = self.load(program, rows)
        self.assertGreater(viewer._sim_turnmill_moves, 0)
        self.assertIn('턴밀', viewer.sim_status_text)
        milled = [info for info in viewer.line_lathe_map.values() if info[0]]
        self.assertGreater(len(milled), 3)                                     # M35 구간 줄 표시
        lines = program.splitlines()
        m35 = lines.index('M35')
        self.assertFalse(viewer.line_lathe_map[m35 - 1][0])                    # M35 앞 줄은 선삭
        self.assertTrue(viewer.line_lathe_map[m35 + 3][0])                     # M35 뒤는 밀링 구간
        stock = self.apply(viewer)
        self.assertTrue(stock.any_cut())                                       # 선삭은 그대로 깎임
        self.assertAlmostEqual(outer_radius(stock, -14.0), 9.5, delta=0.06)

    def test_g41_note_and_thread_note_in_status(self):
        viewer = self.load(PROGRAM.replace('G1Z-15.F.2', 'G41G1Z-15.F.2'))
        self.assertIn('G41/G42', viewer.sim_status_text)
        self.assertIn('G76', viewer.sim_status_text)

    # -- 표시 -------------------------------------------------------------------------
    def test_mesh_refresh_draws_process_colors_and_sections(self):
        viewer = self.load()
        self.apply(viewer)
        viewer._sim_do_mesh_refresh()
        self.assertIsNotNone(viewer.sim_mesh_item)
        self.assertIsNone(viewer.sim_mesh_item.opts['shader'])
        self.assertGreater(len(viewer.sim_edge_item.pos), 24)
        colors = np.array(viewer.sim_mesh_item.opts['meshdata'].vertexColors())
        cmap = viewer._sim_color_map()
        for idx in (0, 1):
            self.assertTrue((np.abs(colors[:, :3] - np.array(cmap[idx][:3])).max(axis=1) < 1e-4).any(), idx)
        self.assertEqual(viewer.sim_section_mode, '3q')
        n3q = len(viewer.sim_mesh_item.opts['meshdata'].vertexes())
        viewer.set_sim_section_mode('full')
        self.assertGreater(len(viewer.sim_mesh_item.opts['meshdata'].vertexes()), n3q)   # 전체가 더 크다
        viewer.set_sim_section_mode('없는 모드')
        self.assertEqual(viewer.sim_section_mode, 'full')
        viewer.set_sim_section_mode('3q')
        for mode in ('solid', 'depth', 'tool'):
            viewer.set_sim_color_mode(mode)
        viewer.set_sim_enabled(False)
        self.assertFalse(viewer.sim_mesh_item.visible())

    def test_a_destroyed_dialog_reference_does_not_break_progress_updates(self):
        viewer = self.load()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        viewer.settings = QSettings(os.path.join(directory.name, 'iso.ini'), QSettings.IniFormat)
        viewer._lathe_stock_dialog = None
        dialog = viewer.open_stock_dialog()
        from PyQt5 import sip
        sip.delete(dialog)                                                     # C++ 창을 즉시 파괴(참조는 남는다)
        viewer._sim_set_progress('형상 계산 중… 10%')                            # 파괴된 창을 참조하고 있어도 죽지 않는다
        viewer._sim_set_progress('')
        self.assertIsNone(viewer._lathe_stock_dialog)

    def test_lathe_stl_export_is_refused(self):
        viewer = self.load()
        self.apply(viewer)
        with self.assertRaises(ValueError):
            viewer.export_stock_stl(os.path.join(tempfile.gettempdir(), 'never.stl'))

    def test_toolpath_bounds_for_fitting_the_stock(self):
        viewer = self.load()
        bounds = viewer.lathe_toolpath_bounds(margin=2.0)
        self.assertAlmostEqual(bounds['front_z'], 5.0)                          # 절삭 이송의 최대 Z(접근 Z5)
        self.assertGreater(bounds['diameter'], 60.0)                             # 접근 X60(반경 30) + 여유
        self.assertGreater(bounds['length'], 15.0)

    # -- 소재 창 ----------------------------------------------------------------------
    def isolated_dialog(self, viewer):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        viewer.settings = QSettings(os.path.join(directory.name, 'iso.ini'), QSettings.IniFormat)
        viewer._lathe_stock_dialog = None
        dialog = viewer.open_stock_dialog()
        self.addCleanup(setattr, viewer, '_lathe_stock_dialog', None)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_stock_button_opens_the_lathe_dialog_in_lathe_mode(self):
        viewer = self.load()
        dialog = self.isolated_dialog(viewer)
        self.assertIsInstance(dialog, LatheStockDialog)
        self.assertEqual(dialog.dim_spins['diameter'].value(), 100.0)           # 기본 소재
        self.assertEqual([dialog.section_combo.itemData(i) for i in range(3)], ['3q', 'half', 'full'])

    def test_dialog_apply_fit_and_settings_round_trip(self):
        viewer = self.load()
        dialog = self.isolated_dialog(viewer)
        dialog.dim_spins['diameter'].setValue(50.0)
        dialog.dim_spins['length'].setValue(40.0)
        dialog.dim_spins['front_z'].setValue(0.0)
        dialog.enable_check.setChecked(True)
        dialog.resolution_combo.setCurrentText('0.1')
        viewer._sim_sync = True
        dialog._apply()
        self.assertTrue(viewer.sim_wait())
        self.assertTrue(viewer.sim_stock.is_lathe)
        self.assertTrue(viewer.sim_stock.any_cut())
        self.assertAlmostEqual(viewer.sim_resolution, 0.1)
        # [툴패스 범위에 맞추기]는 버튼을 눌렀을 때만 바꾼다
        self.assertEqual(dialog.dim_spins['diameter'].value(), 50.0)
        dialog._fit_to_toolpath()
        self.assertGreater(dialog.dim_spins['diameter'].value(), 50.0)
        # 저장/불러오기(밀링 소재 설정과 다른 그룹)
        dialog.section_combo.setCurrentIndex(dialog.section_combo.findData('half'))
        self.assertEqual(viewer.sim_section_mode, 'half')
        reopened = LatheStockDialog(viewer)
        self.addCleanup(reopened.deleteLater)
        self.assertEqual(reopened.dim_spins['length'].value(), dialog.dim_spins['length'].value())
        self.assertEqual(reopened.section_combo.currentData(), 'half')
        self.assertIn('lathe_stock/diameter', viewer.settings.allKeys())
        self.assertFalse([k for k in viewer.settings.allKeys() if k.startswith('stock/')])

    def test_dialog_rejects_bore_not_smaller_than_diameter(self):
        viewer = self.load()
        dialog = self.isolated_dialog(viewer)
        dialog.dim_spins['diameter'].setValue(20.0)
        dialog.dim_spins['bore'].setValue(30.0)
        self.assertIn('내경', dialog.bounds_label.text())
        from unittest import mock
        with mock.patch('nc_viewer_widget.QMessageBox.warning') as warning:
            dialog._apply()
        self.assertTrue(warning.called)

    def test_switching_to_milling_drops_the_lathe_stock(self):
        viewer = self.load()
        self.apply(viewer)
        self.assertTrue(viewer.sim_stock.is_lathe)
        viewer.current_machine_type = MILLING
        viewer.set_source_text(PROGRAM, {}, {})
        self.assertIsNone(viewer.sim_stock)
        self.assertFalse(viewer.sim_enabled)
        self.assertIsNone(viewer.sim_mesh_item)
        viewer.current_machine_type = LATHE                                   # 되돌아와도 새로 시작
        viewer.set_source_text(PROGRAM, {}, geometry_map())
        self.assertEqual(viewer.sim_engine, 'lathe')


if __name__ == '__main__':
    unittest.main()
