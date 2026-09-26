"""형상 시뮬레이션의 뷰어 통합 테스트(v1.9.2): 선분 배열, 백그라운드 계산, 스냅샷
되돌리기, 취소, 표시 메쉬·모서리 선, 색상 모드.

실제 사용자 QSettings를 건드리지 않는다 — 장비 종류는 속성만 바꾸고(저장하지
않음), 소재 팝업의 [적용]/저장 경로는 호출하지 않는다."""
import os
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

try:
    from PyQt5.QtWidgets import QApplication
    import nc_sim
    from nc_viewer_widget import NCViewerWidget, tool_color_for_index
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    IMPORT_ERROR = exc

MILLING = '3축 MCT (X Y Z)'
LATHE = 'CNC 선반 (턴밀 포함)'
SHAPES = {
    'T01': {'type': 'FLAT E/M', 'D': 6.0, 'FL': 20.0, 'R': None, 'SIG': None, 'PL': None, 'SO': 30.0},
    'T1': {'type': 'FLAT E/M', 'D': 6.0, 'FL': 20.0, 'R': None, 'SIG': None, 'PL': None, 'SO': 30.0},
    'T02': {'type': 'BALL E/M', 'D': 4.0, 'FL': 10.0, 'R': None, 'SIG': None, 'PL': None, 'SO': 20.0},
    'T2': {'type': 'BALL E/M', 'D': 4.0, 'FL': 10.0, 'R': None, 'SIG': None, 'PL': None, 'SO': 20.0},
}
NAMES = {'T01': 'D6 F.EM', 'T1': 'D6 F.EM', 'T02': 'D4 B.EM', 'T2': 'D4 B.EM'}

PROGRAM = """M6T1
G43 H1 Z10.
G00 X-20. Y-20.
G00 Z2.
G01 Z-2. F500
G01 X20.
G01 Y-10.
G01 X-20.
G01 Y0.
G01 X20.
G00 Z10.
M6T2
G43 H2 Z10.
G00 X0. Y10.
G01 Z-3. F300
G01 X15. Y15.
G01 X-15. Y5.
G00 Z10.
M30
"""


def make_spec():
    return nc_sim.StockSpec({'T': 8.0, 'W': 60.0, 'L': 60.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'})


@unittest.skipIf(IMPORT_ERROR is not None, 'viewer dependencies are not available')
class SimViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def make_viewer(self, machine=MILLING, program=PROGRAM):
        viewer = NCViewerWidget()
        viewer.current_machine_type = machine        # 저장 없이 속성만
        viewer.set_source_text(program, NAMES, SHAPES)
        self.addCleanup(viewer.deleteLater)
        return viewer

    def compute(self, viewer, seq, sync=True):
        viewer._sim_sync = sync
        viewer._sim_advance_to_seq(seq)
        self.assertTrue(viewer.sim_wait())
        return viewer.sim_stock.heights.copy(), viewer.sim_stock.color_ids.copy()

    # -- 선분 배열 ---------------------------------------------------------------
    def test_segment_arrays_are_built_with_tool_slots_and_colors(self):
        viewer = self.make_viewer()
        seg = viewer.sim_seg
        self.assertIsNotNone(seg)
        count = len(seg['seq1'])
        for key in ('p0', 'p1', 'seq0', 'seq1', 'src', 'rapid', 'tilt', 'slot', 'color'):
            self.assertEqual(len(seg[key]), count, key)
        self.assertTrue(np.all(np.diff(seg['seq1']) >= 0))
        self.assertEqual(len(viewer._sim_tools), 2)              # T1(평), T2(볼)
        self.assertEqual(set(seg['slot'].tolist()), {0, 1})
        self.assertEqual(seg['color'].dtype, np.int16)
        self.assertGreater(int(seg['rapid'].sum()), 0)
        self.assertEqual(int(seg['tilt'].sum()), 0)

    def test_lathe_mode_uses_its_own_engine_never_the_milling_ones(self):
        """v2.2.0: 선반도 시뮬레이션이 있지만 밀링 엔진(zmap/3d)과는 완전히 분리된다(지침 §0).
        밀링 소재 사양(StockSpec)을 선반 뷰어에 넣어도 밀링 소재가 만들어지면 안 된다."""
        viewer = self.make_viewer(machine=LATHE)
        self.assertTrue(viewer.is_sim_available())
        self.assertEqual(viewer.sim_engine, 'lathe')
        self.assertNotEqual(viewer.sim_engine, 'zmap')
        self.assertNotEqual(viewer.sim_engine, '3d')
        self.assertFalse(getattr(viewer.sim_stock, 'is_voxel', False))
        # 선반 뷰어에서는 선반 소재 사양만 소재가 된다
        import nc_lathe_sim
        viewer.apply_stock_spec(nc_lathe_sim.LatheStockSpec(40.0, 30.0), 0.2, True)
        self.assertTrue(viewer.sim_stock.is_lathe)
        self.assertNotIsInstance(viewer.sim_stock, nc_sim.ZMapStock)

    def test_tool_without_diameter_is_excluded_and_reported(self):
        viewer = NCViewerWidget()
        viewer.current_machine_type = MILLING
        shapes = dict(SHAPES)
        shapes['T02'] = dict(SHAPES['T02'], D=None)
        shapes['T2'] = dict(SHAPES['T2'], D=None)
        viewer.set_source_text(PROGRAM, NAMES, shapes)
        self.addCleanup(viewer.deleteLater)
        self.assertEqual(len(viewer._sim_tools), 1)
        self.assertIn('T02', viewer.sim_status_text)

    # -- 계산 ---------------------------------------------------------------
    def test_sync_computation_cuts_stock_and_records_progress(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        stock = viewer.sim_stock
        self.assertEqual(viewer.sim_last_seq, viewer._sim_target_seq_for_selection())
        self.assertLess(float(stock.heights.min()), -1.9)         # T1이 Z-2까지 깎음
        self.assertTrue(np.any(stock.color_ids == 0))
        self.assertTrue(np.any(stock.color_ids == 1))            # 공정 2(T2)의 색

    def test_async_job_matches_sync_result(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        target = viewer.sim_last_seq
        expected, expected_colors = viewer.sim_stock.heights.copy(), viewer.sim_stock.color_ids.copy()

        viewer._SIM_SYNC_SEGMENTS = 0            # 짧아도 백그라운드 스레드로
        viewer._sim_sync = False
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        self.assertEqual(viewer.sim_last_seq, target)
        self.assertTrue(np.array_equal(viewer.sim_stock.heights, expected))
        self.assertTrue(np.array_equal(viewer.sim_stock.color_ids, expected_colors))

    def test_random_seeks_equal_fresh_computation(self):
        """무작위로 앞뒤 이동한 결과는 처음부터 한 번에 계산한 결과와 같아야 한다."""
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        seqs = np.unique(viewer.sim_seg['seq1'])
        rng = np.random.default_rng(11)
        for target in rng.choice(seqs, size=20):
            got, got_colors = self.compute(viewer, int(target))
            fresh = self.make_viewer()
            fresh.apply_stock_spec(make_spec(), 0.5, True)
            fresh.sim_wait()
            want, want_colors = self.compute(fresh, int(target))
            self.assertTrue(np.array_equal(got, want), 'seq %d' % target)
            self.assertTrue(np.array_equal(got_colors, want_colors), 'seq %d' % target)

    def test_new_request_cancels_running_job_and_final_result_is_correct(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        seqs = np.unique(viewer.sim_seg['seq1'])
        early, late = int(seqs[len(seqs) // 3]), int(seqs[-1])

        viewer._SIM_SYNC_SEGMENTS = 0
        viewer._sim_sync = False
        viewer._sim_advance_to_seq(late)
        viewer._sim_advance_to_seq(early)        # 진행 중일 수 있는 계산을 취소하고 다시 요청
        self.assertTrue(viewer.sim_wait())
        got = viewer.sim_stock.heights.copy()
        self.assertEqual(viewer.sim_last_seq, early)

        fresh = self.make_viewer()
        fresh.apply_stock_spec(make_spec(), 0.5, True)
        fresh.sim_wait()
        want, _colors = self.compute(fresh, early)
        self.assertTrue(np.array_equal(got, want))

    def test_rapid_fire_requests_during_long_job_end_in_correct_state(self):
        """긴 프로그램을 스레드로 계산하는 도중 목표를 계속 바꿔도(취소가 실제로
        일어나도) 마지막 요청의 결과가 처음부터 계산한 것과 같아야 한다."""
        lines = ['M6T1', 'G43 H1 Z10.', 'G00 X-25. Y-25.', 'G00 Z2.']
        y = -25.0
        while len(lines) < 5000:
            lines += ['G01 Z-2. F800', 'G01 X25.', 'G01 Y%.2f' % (y + 0.4), 'G01 X-25.',
                      'G01 Y%.2f' % (y + 0.8)]
            y += 0.8
            if y > 24:
                y = -25.0
        lines += ['G00 Z10.', 'M30']
        program = '\n'.join(lines)
        viewer = self.make_viewer(program=program)
        spec = make_spec()
        viewer.apply_stock_spec(spec, 0.1, True)
        self.assertTrue(viewer.sim_wait(120000))
        seqs = np.unique(viewer.sim_seg['seq1'])
        viewer._SIM_SYNC_SEGMENTS = 0
        viewer._sim_sync = False
        rng = np.random.default_rng(5)
        targets = [int(seqs[int(i)]) for i in rng.integers(0, len(seqs), size=8)]
        for target in targets:
            viewer._sim_advance_to_seq(target)
            self.qapp.processEvents()
        self.assertTrue(viewer.sim_wait(120000))
        self.assertEqual(viewer.sim_last_seq, targets[-1])
        got = viewer.sim_stock.heights.copy()

        fresh = self.make_viewer(program=program)
        fresh.apply_stock_spec(spec, 0.1, True)
        fresh.sim_wait(120000)
        want, _colors = self.compute(fresh, targets[-1])
        self.assertTrue(np.array_equal(got, want))

    def test_stale_generation_result_is_discarded(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        before = viewer.sim_stock.heights.copy()
        job = nc_sim_job_for(viewer, generation=viewer._sim_generation - 1)
        job.run(use_numba=False)
        self.assertFalse(viewer._sim_adopt(job))
        self.assertTrue(np.array_equal(viewer.sim_stock.heights, before))

    def test_snapshots_are_taken_at_process_starts_and_bounded_by_memory(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        self.assertGreaterEqual(len(viewer._sim_snapshots), 1)
        (snap, warn_count) = next(iter(viewer._sim_snapshots.values()))
        self.assertEqual(snap[0].dtype, np.float32)
        self.assertEqual(warn_count, 0)
        original = nc_sim.SIM_SNAPSHOT_MEMORY_MB
        try:
            nc_sim.SIM_SNAPSHOT_MEMORY_MB = 0
            viewer._sim_trim_snapshots()
            self.assertEqual(len(viewer._sim_snapshots), 1)      # 가장 앞의 것만 남는다
        finally:
            nc_sim.SIM_SNAPSHOT_MEMORY_MB = original

    def test_rapid_cut_lines_are_reported_once_even_after_rewind(self):
        program = """M6T1
G43 H1 Z10.
G00 X0. Y0.
G00 Z-3.
G00 X10.
G01 Z5. F500
G00 Z10.
M30
"""
        viewer = self.make_viewer(program=program)
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        lines = viewer.rapid_cut_warning_lines()
        self.assertTrue(lines)
        count = viewer.rapid_cut_warning_count()
        last = viewer.sim_last_seq
        self.compute(viewer, 0)                                 # 되감기
        self.compute(viewer, last)                              # 다시 끝까지
        self.assertEqual(viewer.rapid_cut_warning_count(), count)   # 중복으로 쌓이지 않는다
        self.assertEqual(viewer.rapid_cut_warning_lines(), lines)

    # -- 표시 ---------------------------------------------------------------
    def test_display_meshes_are_unlit_with_edges(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        viewer._sim_do_mesh_refresh()
        mesh, edges = viewer.sim_mesh_item, viewer.sim_edge_item
        self.assertIsNotNone(mesh)
        self.assertIsNotNone(edges)
        self.assertIsNone(mesh.opts['shader'])                  # 셰이더/조명 없음
        self.assertFalse(mesh.opts['computeNormals'])
        self.assertTrue(mesh.visible())
        self.assertTrue(edges.visible())
        self.assertGreater(len(edges.pos), 24)                  # 외곽 + 절삭 단차
        viewer.set_sim_enabled(False)
        self.assertFalse(mesh.visible())
        self.assertFalse(edges.visible())

    def test_color_mode_changes_colors_without_recomputing(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        heights = viewer.sim_stock.heights.copy()
        last = viewer.sim_last_seq

        def mesh_colors():
            return np.array(viewer.sim_mesh_item.opts['meshdata'].vertexColors())

        viewer.set_sim_color_mode('solid')
        solid = mesh_colors()
        viewer.set_sim_color_mode('depth')
        depth = mesh_colors()
        viewer.set_sim_color_mode('tool')
        tool = mesh_colors()
        self.assertTrue(np.allclose(solid, np.array(nc_sim.DEFAULT_STOCK_COLOR)))
        self.assertGreater(len(np.unique(depth.round(3), axis=0)), 1)
        self.assertGreater(len(np.unique(tool.round(3), axis=0)), 1)
        # v2.0.2: 공정 색은 색이 섞이는 면의 정점을 복제하므로 깊이 모드와 정점 수가 다를 수 있다
        self.assertFalse(depth.shape == tool.shape and np.allclose(depth, tool))
        self.assertTrue(np.array_equal(viewer.sim_stock.heights, heights))   # 재계산 없음
        self.assertEqual(viewer.sim_last_seq, last)
        viewer.set_sim_color_mode('없는 모드')
        self.assertEqual(viewer.sim_color_mode, 'tool')

    def test_sim_colors_match_process_list(self):
        viewer = self.make_viewer()
        color_map = viewer._sim_color_map()
        self.assertEqual(set(color_map), set(range(len(viewer.tool_paths))))
        for idx, rgba in color_map.items():
            self.assertEqual(tuple(rgba[:3]), tuple(float(c) for c in tool_color_for_index(idx)))
            self.assertEqual(rgba[3], 1.0)

    def test_stl_export_uses_full_resolution_mesh(self):
        import tempfile
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        self.assertTrue(viewer.sim_wait())
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'out.stl')
            viewer.export_stock_stl(path)
            size = os.path.getsize(path)
        stock = viewer.sim_stock
        self.assertGreater(size, 80 + 4 + stock.cell_count() * 2 * 50 // 2)

    # -- 소재는 사용자가 정한 값 (v1.9.3) ----------------------------------------
    def _isolated_dialog(self, viewer):
        import tempfile
        from PyQt5.QtCore import QSettings
        from nc_viewer_widget import StockDialog
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        viewer.settings = QSettings(os.path.join(directory.name, 'iso.ini'), QSettings.IniFormat)
        dialog = StockDialog(viewer)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_dialog_does_not_auto_fit_stock_to_toolpath(self):
        """소재 팝업은 처음 열어도 툴패스 범위로 자동 확장하지 않는다 — 기본 소재로 시작하고
        [툴패스 범위에 맞추기]를 눌러야만 맞춘다."""
        viewer = self.make_viewer()
        dialog = self._isolated_dialog(viewer)
        dims = {key: dialog.dim_spins[key].value() for key in 'TWL'}
        self.assertEqual(dims, {'T': 50.0, 'W': 100.0, 'L': 100.0})
        self.assertEqual([dialog.offset_spins[a].value() for a in 'XYZ'], [0.0, 0.0, 0.0])
        self.assertEqual(dialog.ref_combos['Z'].currentData(), 'top')
        self.assertEqual(dialog._build_spec().bounds()['Z'], (-50.0, 0.0))
        dialog._fit_to_toolpath()                       # 버튼을 눌렀을 때만 맞춘다
        self.assertNotEqual(dialog.dim_spins['L'].value(), 100.0)

    def test_user_stock_is_used_exactly_as_entered(self):
        viewer = self.make_viewer()
        dialog = self._isolated_dialog(viewer)
        dialog.dim_spins['L'].setValue(37.0)
        dialog.dim_spins['W'].setValue(29.0)
        dialog.dim_spins['T'].setValue(11.0)
        dialog.enable_check.setChecked(True)
        dialog._apply()
        viewer.sim_wait()
        self.assertEqual(viewer.sim_stock_spec.bounds(),
                         {'X': (-18.5, 18.5), 'Y': (-14.5, 14.5), 'Z': (-11.0, 0.0)})
        stock = viewer.sim_stock
        self.assertAlmostEqual(stock.x0, -18.5)
        self.assertAlmostEqual(stock.zlo, -11.0)
        self.assertAlmostEqual(stock.ztop, 0.0)

    # -- 저장된 색상 모드 마이그레이션 (v2.0.1) ------------------------------------
    def _dialog_with_saved_mode(self, mode, migrated=False):
        import tempfile
        from PyQt5.QtCore import QSettings
        from nc_viewer_widget import StockDialog
        viewer = self.make_viewer()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = QSettings(os.path.join(directory.name, 'iso.ini'), QSettings.IniFormat)
        settings.setValue('stock/color_mode', mode)
        if migrated:
            settings.setValue('stock/color_mode_migrated_v2', True)
        viewer.settings = settings
        dialog = StockDialog(viewer)
        self.addCleanup(dialog.deleteLater)
        return viewer, dialog, settings

    def test_saved_solid_or_depth_mode_is_reset_to_tool_once(self):
        for mode in ('solid', 'depth'):
            viewer, dialog, settings = self._dialog_with_saved_mode(mode)
            self.assertEqual(dialog.color_mode_combo.currentData(), 'tool', mode)
            self.assertEqual(viewer.sim_color_mode, 'tool', mode)
            self.assertEqual(settings.value('stock/color_mode'), 'tool', mode)
            self.assertTrue(settings.value('stock/color_mode_migrated_v2', False, type=bool))

    def test_color_mode_chosen_after_migration_is_kept(self):
        viewer, dialog, settings = self._dialog_with_saved_mode('solid')
        dialog.color_mode_combo.setCurrentIndex(dialog.color_mode_combo.findData('solid'))
        from nc_viewer_widget import StockDialog
        reopened = StockDialog(viewer)                 # 같은 설정으로 다시 연다
        self.addCleanup(reopened.deleteLater)
        self.assertEqual(reopened.color_mode_combo.currentData(), 'solid')
        self.assertEqual(viewer.sim_color_mode, 'solid')

    def test_already_migrated_settings_are_left_alone(self):
        viewer, dialog, settings = self._dialog_with_saved_mode('depth', migrated=True)
        self.assertEqual(dialog.color_mode_combo.currentData(), 'depth')
        self.assertEqual(settings.value('stock/color_mode'), 'depth')

    # -- 깎이지 않은 이유 진단 (v1.9.3) -------------------------------------------
    def _apply_and_diagnose(self, viewer, spec):
        viewer.apply_stock_spec(spec, 0.5, True)
        viewer.sim_wait()
        return viewer.sim_diagnosis()

    def test_diagnosis_is_empty_when_stock_is_cut(self):
        viewer = self.make_viewer()
        self.assertEqual(self._apply_and_diagnose(viewer, make_spec()), '')
        self.assertEqual(viewer.sim_notice_text, '')

    def test_diagnosis_toolpath_above_stock(self):
        viewer = self.make_viewer()
        spec = nc_sim.StockSpec({'T': 8.0, 'W': 60.0, 'L': 60.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                offset={'Z': -20.0})           # 소재 Z -28 ~ -20, 툴패스는 -3
        text = self._apply_and_diagnose(viewer, spec)
        self.assertIn('Z', text)
        self.assertIn('위입니다', text)
        self.assertEqual(viewer.sim_notice_text, text)          # 화면 경고 표시
        self.assertFalse(viewer.sim_progress_label.isHidden())

    def test_diagnosis_toolpath_outside_stock_xy(self):
        viewer = self.make_viewer()
        spec = nc_sim.StockSpec({'T': 8.0, 'W': 60.0, 'L': 60.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                offset={'X': 500.0})
        text = self._apply_and_diagnose(viewer, spec)
        self.assertIn('겹치지 않습니다', text)

    def test_diagnosis_moves_without_tool_number(self):
        program = """G00 X-20. Y-20.
G43 H1 Z10.
G01 Z-2. F500
G01 X20.
G01 Y-10.
M30
"""
        viewer = self.make_viewer(program=program)
        self.assertGreater(viewer._sim_no_tool_moves, 0)
        text = self._apply_and_diagnose(viewer, make_spec())
        self.assertIn('공구 번호', text)
        self.assertIn('공구 번호', viewer.sim_status_text)

    def test_diagnosis_tool_without_diameter(self):
        viewer = NCViewerWidget()
        viewer.current_machine_type = MILLING
        shapes = {key: dict(value, D=None) for key, value in SHAPES.items()}
        viewer.set_source_text(PROGRAM, NAMES, shapes)
        self.addCleanup(viewer.deleteLater)
        text = self._apply_and_diagnose(viewer, make_spec())
        self.assertIn('지름', text)

    def test_dialog_status_shows_progress_and_rapid_button(self):
        viewer = self.make_viewer()
        viewer.apply_stock_spec(make_spec(), 0.5, True)
        viewer.sim_wait()
        dialog = self._isolated_dialog(viewer)       # 실제 QSettings를 건드리지 않는다
        viewer.sim_progress_text = '형상 계산 중… 42%'
        dialog.refresh_status()
        self.assertIn('42%', dialog.status_label.text())
        self.assertEqual([dialog.color_mode_combo.itemData(i) for i in range(3)],
                         ['tool', 'depth', 'solid'])


AC_MACHINE = '5축 MCT (A to C)'
BC_MACHINE = '5축 MCT (B to C)'
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SHAPES_T6 = {key: {'type': 'FLAT E/M', 'D': 6.0, 'FL': 20.0, 'R': None, 'SIG': None, 'PL': None,
                   'SO': 30.0} for key in ('T06', 'T6', '6')}


def load_viewer(test, program, machine, shapes=None):
    viewer = NCViewerWidget()
    viewer.current_machine_type = machine        # 저장 없이 속성만
    viewer.set_source_text(program, {}, SHAPES if shapes is None else shapes)
    test.addCleanup(viewer.deleteLater)
    return viewer


@unittest.skipIf(IMPORT_ERROR is not None, 'viewer dependencies are not available')
class RotaryAxisParserTests(unittest.TestCase):
    """공구 축 기록(G68.2 경사면, G43.4 회전축 값), G68.2 원점."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def test_tool_axis_formulas(self):
        f = NCViewerWidget.tool_axis_from_rotary
        self.assertTrue(np.allclose(f(True, -90.0, 0.0, 0.0), (0.0, 1.0, 0.0), atol=1e-9))      # A→C
        self.assertTrue(np.allclose(f(True, 0.0, 0.0, 33.0), (0.0, 0.0, 1.0), atol=1e-9))
        self.assertTrue(np.allclose(f(False, 0.0, 30.0, 90.0), (0.0, 0.5, np.sqrt(0.75)), atol=1e-9))  # B→C
        self.assertTrue(np.allclose(f(False, 0.0, 30.0, 0.0), (0.5, 0.0, np.sqrt(0.75)), atol=1e-9))

    def test_g68_g69_then_g43_4_sequence(self):
        """프로그램 기본 G68.2 → G69로 취소 → G43.4 보정: G43.4 구간에서만 회전축으로 축이 정해진다."""
        program = """M6 T1
G0 G90 G54
G68.2 P1 X+0. Y+0. Z+0. I+0. J+0. K+0.
G53.1
G49
G69
G0 G90 X0. Y0. B0. C0.
G43.4 Z100. H1
G0 X10. Y0. Z50. B30. C90.
G1 X20.
G49
G0 X30. B0. C0.
"""
        viewer = load_viewer(self, program, BC_MACHINE)
        axes = viewer.line_axis_map
        lines = program.splitlines()
        idx = {text: i for i, text in enumerate(lines)}
        self.assertNotIn(idx['G0 G90 X0. Y0. B0. C0.'], axes)                   # G43.4 이전
        self.assertNotIn(idx['G43.4 Z100. H1'], axes)                          # B0 C0 → 축 +Z
        want = np.array((np.sin(np.radians(30)) * np.cos(np.radians(90)),
                         np.sin(np.radians(30)) * np.sin(np.radians(90)), np.cos(np.radians(30))))
        self.assertTrue(np.allclose(axes[idx['G0 X10. Y0. Z50. B30. C90.']], want, atol=1e-9))
        self.assertTrue(np.allclose(axes[idx['G1 X20.']], want, atol=1e-9))     # 모달 유지
        self.assertNotIn(idx['G0 X30. B0. C0.'], axes)                          # G49 이후

    def test_plain_g43_cancels_tcp(self):
        program = """M6 T1
G43.4 Z100. H1
G0 X10. B30. C0.
G43 Z100. H1
G0 X20. B30. C0.
"""
        viewer = load_viewer(self, program, BC_MACHINE)
        lines = program.splitlines()
        self.assertIn(lines.index('G0 X10. B30. C0.'), viewer.line_axis_map)
        self.assertNotIn(lines.index('G0 X20. B30. C0.'), viewer.line_axis_map)

    def test_g68_2_axis_matches_rotary_words_for_ac_machine(self):
        program = """M6 T1
A-90. C20.
G68.2 X0. Y0. Z0. I20. J-90. K0.
G53.1
G43 Z50. H1
G1 X5. Y6. Z7.
G69
G1 X1.
"""
        viewer = load_viewer(self, program, AC_MACHINE)
        lines = program.splitlines()
        axis = viewer.line_axis_map[lines.index('G1 X5. Y6. Z7.')]
        self.assertTrue(np.allclose(axis, NCViewerWidget.tool_axis_from_rotary(True, -90.0, 0.0, 20.0)))
        self.assertNotIn(lines.index('G1 X1.'), viewer.line_axis_map)         # G69 이후

    def test_g68_2_feature_origin_is_applied(self):
        program = """M6 T1
G68.2 X10. Y20. Z30. I0. J0. K0.
G53.1
G43 Z5. H1
G1 X1. Y2. Z3.
G69
G1 X1. Y2. Z3.
"""
        viewer = load_viewer(self, program, AC_MACHINE)
        nodes = [n for path in viewer.tool_paths.values() for n in path if n.get('valid')]
        lines = program.splitlines()
        in_frame = [n for n in nodes if n['src_line'] == lines.index('G1 X1. Y2. Z3.')]
        self.assertTrue(np.allclose(in_frame[0]['pt'], (11.0, 22.0, 33.0)))       # 원점 + 로컬
        after_cancel = [n for n in nodes if n['src_line'] == 6]
        self.assertTrue(np.allclose(after_cancel[0]['pt'], (1.0, 2.0, 3.0)))      # G69 이후 원점 해제

    def test_real_program_vector_entry_moves_along_minus_tool_axis(self):
        """O3210.NC(B→C, G43.4)의 진입 이동은 -공구축 방향이다 — 회전 규칙의 근거."""
        text = open(os.path.join(DATA_DIR, 'O3210_excerpt.nc'), encoding='utf-8').read()
        viewer = load_viewer(self, text, BC_MACHINE, SHAPES_T6)
        lines = text.splitlines()
        first_move = next(i for i, l in enumerate(lines) if l.startswith('G0 X-114.977'))
        entry = first_move + 1
        nodes = {n['src_line']: n for path in viewer.tool_paths.values() for n in path if n.get('valid')}
        d = np.array(nodes[entry]['pt']) - np.array(nodes[first_move]['pt'])
        unit = d / np.linalg.norm(d)
        axis = np.array(viewer.line_axis_map[first_move])
        self.assertAlmostEqual(float(np.linalg.norm(d)), 100.0, places=2)
        self.assertLess(np.degrees(np.arccos(np.clip(unit @ -axis, -1, 1))), 0.01)


@unittest.skipIf(IMPORT_ERROR is not None, 'viewer dependencies are not available')
class Sim3DViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _apply(self, viewer, spec, res=1.0):
        viewer.apply_stock_spec(spec, res, True)
        self.assertTrue(viewer.sim_wait(120000))
        return viewer.sim_stock

    def test_plain_three_axis_program_keeps_the_zmap_engine(self):
        viewer = load_viewer(self, PROGRAM, MILLING)
        self.assertEqual(viewer.sim_engine, 'zmap')
        stock = self._apply(viewer, make_spec(), 0.5)
        self.assertFalse(stock.is_voxel)

    def test_tilted_plane_program_is_cut_by_the_3d_engine(self):
        """G68.2 J-90: 공구 축이 월드 +Y — 로컬 Z=-5 는 월드 Y=-5 이므로 Y ≥ -5 쪽 소재가 파인다."""
        program = """M6 T1
A-90. C0.
G68.2 X0. Y0. Z0. I0. J-90. K0.
G53.1
G43 Z50. H1
G00 X-20. Y0.
G01 Z-5. F500
G01 X20.
G69
M30
"""
        viewer = load_viewer(self, program, AC_MACHINE)
        self.assertEqual(viewer.sim_engine, '3d')
        self.assertGreater(int(viewer.sim_seg['tilt'].sum()), 0)
        self.assertIn('3D 소재 방식', viewer.sim_status_text)
        spec = nc_sim.StockSpec({'T': 40.0, 'W': 40.0, 'L': 60.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                reference={'Z': 'center'})
        stock = self._apply(viewer, spec)
        self.assertTrue(stock.is_voxel)
        self.assertTrue(stock.any_cut())
        gx = stock.x0 + (np.arange(stock.nx) + 0.5) * stock.step[0]
        gy = stock.y0 + (np.arange(stock.ny) + 0.5) * stock.step[1]
        gz = stock.z0 + (np.arange(stock.nz) + 0.5) * stock.step[2]

        def removed_at(x, y, z):
            i = int(np.argmin(np.abs(gx - x)))
            j = int(np.argmin(np.abs(gy - y)))
            k = int(np.argmin(np.abs(gz - z)))
            return stock.occ[i, j, k] == 0

        self.assertTrue(removed_at(0.0, 5.0, 0.0))        # 공구 몸통(팁 Y=-5 에서 +Y 방향) 안
        self.assertTrue(removed_at(10.0, 10.0, 0.0))
        self.assertFalse(removed_at(0.0, -10.0, 0.0))     # 팁보다 -Y 쪽은 그대로
        self.assertFalse(removed_at(0.0, 5.0, 12.0))      # 반경(3) 밖은 그대로

    def test_g43_4_program_from_real_bc_file_is_cut_along_the_vector(self):
        text = open(os.path.join(DATA_DIR, 'O3210_excerpt.nc'), encoding='utf-8').read()
        viewer = load_viewer(self, text, BC_MACHINE, SHAPES_T6)
        self.assertEqual(viewer.sim_engine, '3d')
        spec = nc_sim.StockSpec({'T': 50.0, 'W': 80.0, 'L': 80.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                reference={'X': 'center', 'Y': 'center', 'Z': 'bottom'},
                                offset={'X': -140.0, 'Y': 10.0, 'Z': -5.0})
        stock = self._apply(viewer, spec)
        self.assertTrue(stock.is_voxel)
        self.assertTrue(stock.any_cut())
        self.assertEqual(viewer.sim_diagnosis(), '')
        self.assertGreater(stock.removed_fraction(), 0.0005)

    def test_3d_engine_seek_equals_fresh_computation(self):
        program = """M6 T1
A-90. C0.
G68.2 X0. Y0. Z0. I0. J-90. K0.
G53.1
G43 Z50. H1
G00 X-20. Y0.
G01 Z-5. F500
G01 X20.
G01 Y3.
G01 X-20.
G01 Y6.
G01 X20.
G69
M6 T2
G68.2 X0. Y0. Z0. I30. J-60. K0.
G53.1
G43 Z50. H2
G01 X-10. Y0. Z-2.
G01 X10.
G69
M30
"""
        spec = nc_sim.StockSpec({'T': 40.0, 'W': 40.0, 'L': 60.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                reference={'Z': 'center'})
        viewer = load_viewer(self, program, AC_MACHINE)
        self._apply(viewer, spec)
        seqs = np.unique(viewer.sim_seg['seq1'])
        rng = np.random.default_rng(2)
        for target in rng.choice(seqs, size=6):
            viewer._sim_sync = True
            viewer._sim_advance_to_seq(int(target))
            self.assertTrue(viewer.sim_wait())
            got = viewer.sim_stock.occ.copy()
            fresh = load_viewer(self, program, AC_MACHINE)
            self._apply(fresh, spec)
            fresh._sim_sync = True
            fresh._sim_advance_to_seq(int(target))
            self.assertTrue(fresh.sim_wait())
            self.assertTrue(np.array_equal(got, fresh.sim_stock.occ), 'seq %d' % target)

    def test_3d_engine_snapshots_and_display_mesh(self):
        text = open(os.path.join(DATA_DIR, 'O3210_excerpt.nc'), encoding='utf-8').read()
        viewer = load_viewer(self, text, BC_MACHINE, SHAPES_T6)
        spec = nc_sim.StockSpec({'T': 50.0, 'W': 80.0, 'L': 80.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                reference={'X': 'center', 'Y': 'center', 'Z': 'bottom'},
                                offset={'X': -140.0, 'Y': 10.0, 'Z': -5.0})
        self._apply(viewer, spec)
        viewer._sim_do_mesh_refresh()
        self.assertIsNotNone(viewer.sim_mesh_item)
        self.assertIsNone(viewer.sim_mesh_item.opts['shader'])
        self.assertGreater(len(viewer.sim_edge_item.pos), 24)
        for mode in ('solid', 'depth', 'tool'):
            viewer.set_sim_color_mode(mode)
        for value in viewer._sim_snapshots.values():
            self.assertIsInstance(value[0][0], bytes)                 # 압축된 스냅샷

    def test_snapshots_are_taken_at_each_process_even_when_moves_precede_g43(self):
        """M6 뒤 G43 이전 이동이 끼어 있어도(실제 프로그램 형태) 공정마다 스냅샷이 잡힌다."""
        program = """M6 T1
G00 X0. Y0.
G43 H1 Z10.
G01 Z-1. F100
G01 X10.
M6 T2
G00 X0. Y0.
G43 H2 Z10.
G01 Z-1. F100
G01 X10.
M30
"""
        viewer = load_viewer(self, program, MILLING)
        self._apply(viewer, make_spec(), 0.5)
        self.assertEqual(len(viewer._sim_snap_positions), 2)
        self.assertEqual(len(viewer._sim_snapshots), 2)

    def test_3d_diagnosis_when_stock_is_far_from_the_toolpath(self):
        program = """M6 T1
A-90. C0.
G68.2 X0. Y0. Z0. I0. J-90. K0.
G53.1
G43 Z50. H1
G01 X-20. Y0. Z-5. F500
G01 X20.
G69
M30
"""
        viewer = load_viewer(self, program, AC_MACHINE)
        spec = nc_sim.StockSpec({'T': 20.0, 'W': 20.0, 'L': 20.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'},
                                offset={'X': 900.0})
        stock = self._apply(viewer, spec)
        self.assertFalse(stock.any_cut())
        self.assertIn('겹치지 않습니다', viewer.sim_diagnosis())


def nc_sim_job_for(viewer, generation):
    """테스트용: 현재 상태에서 한 번 더 도는 작업(세대만 지정)."""
    from nc_viewer_widget import _SimJob
    return _SimJob(generation, viewer.sim_stock.clone(), viewer.sim_seg, viewer._sim_tools,
                   0, len(viewer.sim_seg['seq1']), viewer._sim_snap_positions, set(),
                   viewer.sim_last_seq, viewer._sim_bridge)


if __name__ == '__main__':
    unittest.main()
