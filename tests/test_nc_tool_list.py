import math
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import NC_Tool_List as app


REAL_NC_SAMPLE = """%
 O1017
(PART NO. : K10M41017)
(OPERATION : OP10)
(PROGRAM : O1017)
(RUN TIME : 160)
(DATE : 2026-08-25)
N1(#1: Tool Change)
 (T11 // D13 DR [SO 140] // T11 BT50 DMG32-105 )
M6 T11
N2(#2: Tool Change)
 (T3 // D16.8 FLAT EM [SO 80] // T3 BT50 SLN16-90 )
M6 T3
N3(#3: Tool Change)
 (T1 // FACE MILL [SO 200] // T1 BT50 FMH-60 )
M6 T1
N4(#4: Tool Change)
 (T12 // D7 DR [SO 120] // T12 BT50 DMG32-105 )
M6 T12
N5(#5: Tool Change)
 (T4 // D6 REAMER [SO 70] // T4 BT50 SLN06-90 )
M6 T4
N6(#6: Tool Change)
 (T16 // D13 DR [SO 30] // T16 BT50 NPU-90 )
M6 T16
N7(#7: Tool Change)
 (T3 // D16.8 FLAT EM [SO 80] // T3 BT50 SLN16-90 )
M6 T3
"""


class NcToolListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = REAL_NC_SAMPLE
        cls.rows = app.parse_program(cls.source)

    def test_real_nc_metadata(self):
        self.assertEqual(
            app.parse_program_metadata(self.source),
            {
                'part_no': 'K10M41017',
                'operation': 'OP10',
                'program': 'O1017',
                'runtime': '160',
                'date': '2026-08-25',
            },
        )

    def test_real_nc_tool_slots_and_repeated_tool_remarks(self):
        self.assertEqual(len(self.rows), 16)
        self.assertEqual(self.rows[0]['NO'], 'T01')
        self.assertEqual(self.rows[0]['TYPE'], 'FACE MILL')
        self.assertEqual(self.rows[2]['REMARK'], 'N2, N7')
        self.assertEqual(self.rows[10]['NO'], 'T11')
        self.assertEqual(self.rows[15]['HOLDER'], 'BT50 NPU-90')

    def test_parser_accepts_m6t_without_space(self):
        source = """N1(#1: Tool Change)
 (T7 // D5 DR [SO 40] // T7 BT50 HOLDER )
M6T7
"""
        rows = app.parse_program(source)
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[6]['NO'], 'T07')
        self.assertEqual(rows[6]['TYPE'], 'DRILL')
        self.assertEqual(rows[6]['REMARK'], 'N1')

    def test_next_tool_change_search_supports_spacing_and_wraps(self):
        source = 'M6 T1\nG0 X0\nM06T12\nM6T3'
        self.assertEqual(app.find_next_tool_change_span(source, 0), (0, 5, False))
        self.assertEqual(app.find_next_tool_change_span(source, 6), (12, 18, False))
        self.assertEqual(app.find_next_tool_change_span('M06T01', 0), (0, 6, False))
        self.assertEqual(app.find_next_tool_change_span(source, len(source)), (0, 5, True))

    def test_literal_search_is_case_insensitive_and_wraps(self):
        source = 'FACE MILL\nflat em\nDRILL'
        self.assertEqual(app.find_next_literal_span(source, 'FLAT', 1), (10, 14, False))
        self.assertEqual(app.find_next_literal_span(source, 'face', len(source)), (0, 4, True))
        self.assertIsNone(app.find_next_literal_span(source, 'tap', 0))

    def test_open_file_with_default_app_uses_os_startfile(self):
        opened = []
        original = getattr(app.os, 'startfile', None)
        app.os.startfile = lambda path: opened.append(path)
        try:
            self.assertEqual(app.open_file_with_default_app(Path('tool-list.pdf')), '')
        finally:
            if original is None:
                delattr(app.os, 'startfile')
            else:
                app.os.startfile = original
        self.assertEqual(opened, ['tool-list.pdf'])

    def test_legacy_metadata_derives_part_and_operation(self):
        metadata = app.parse_program_metadata(
            '( PGM NO : OP10_SSTR4171 )\n( COMPLETE TIME : 11:15:01 )'
        )
        self.assertEqual(metadata['program'], 'OP10_SSTR4171')
        self.assertEqual(metadata['operation'], 'OP10')
        self.assertEqual(metadata['part_no'], 'SSTR4171')
        self.assertEqual(metadata['runtime'], '11:15:01')

    def test_pdf_export_uses_a4_table_and_paginates(self):
        metadata = app.parse_program_metadata(self.source)
        rows = self.rows + self.rows
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'tool-list.pdf'
            app.export_tool_list_pdf(output, rows, metadata)
            content = output.read_bytes()
        self.assertTrue(content.startswith(b'%PDF-'))
        self.assertGreater(len(content), 10_000)
        self.assertEqual(len(re.findall(rb'/Type\s*/Page\b', content)), 2)

    def test_tool_name_map_supports_viewer_filter_labels(self):
        rows = [
            {'NO': 'T02', 'NAME': 'D10 F.EM'},
            {'NO': 'T3', 'NAME': 'D6 B.EM'},
            {'NO': '', 'NAME': ''},
        ]
        mapping = app.tool_name_map_from_rows(rows)
        self.assertEqual(mapping['T02'], 'D10 F.EM')
        self.assertEqual(mapping['2'], 'D10 F.EM')
        self.assertEqual(mapping['T3'], 'D6 B.EM')
        self.assertEqual(mapping['T03'], 'D6 B.EM')


    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_viewer_process_filter_separates_repeated_normalized_m6_tools(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        source = """M6T1
G43
G00 X0 Y0 Z0
G01 X10 Y0 Z0
M06T01
G43
G00 X20 Y0 Z0
G01 X30 Y0 Z0
"""
        viewer = NCViewerWidget()
        try:
            self.assertTrue(viewer.set_source_text(source, {'T01': 'FACE MILL'}))
            keys = list(viewer.tool_paths)
            self.assertEqual(keys, ['P001_T01', 'P002_T01'])
            self.assertEqual([viewer.process_tool_map[key] for key in keys], ['T01', 'T01'])
            self.assertEqual(viewer._tool_display_text(keys[0]), '공정 01 | T01 | FACE MILL')
            self.assertEqual(viewer._tool_display_text(keys[1]), '공정 02 | T01 | FACE MILL')
            self.assertLessEqual(sum(len(items) for items in viewer.plot_items.values()), 4)
            self.assertFalse(viewer.set_source_text(source, {'T01': 'FACE MILL'}))
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_viewer_rapid_modal_red_until_cut_or_g98(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget, RAPID_MOVE_ALPHA, RAPID_MOVE_COLOR

        source = """M6T1
G43
G00 X0 Y0 Z0
X10 Y0 Z0
Y10
G01 X20 Y10 Z0
G00 X30 Y10 Z0
X40
G98 X50 Y10 Z0
X60 Y10 Z0
"""
        viewer = NCViewerWidget()
        try:
            viewer.set_machine_type('3축 MCT (X Y Z)', init_camera=True)
            self.assertTrue(viewer.set_source_text(source, {'T01': 'FACE MILL'}))
            path_data = viewer.tool_paths['P001_T01']
            buckets = viewer._render_segment_buckets(path_data)
            self.assertEqual(
                buckets['G00'],
                [
                    [0.0, 0.0, 0.0], [10.0, 0.0, 0.0],
                    [10.0, 0.0, 0.0], [10.0, 10.0, 0.0],
                    [20.0, 10.0, 0.0], [30.0, 10.0, 0.0],
                    [30.0, 10.0, 0.0], [40.0, 10.0, 0.0],
                ],
            )
            self.assertEqual(
                buckets['CUT'],
                [
                    [10.0, 10.0, 0.0], [20.0, 10.0, 0.0],
                    [40.0, 10.0, 0.0], [50.0, 10.0, 0.0],
                    [50.0, 10.0, 0.0], [60.0, 10.0, 0.0],
                ],
            )
            viewer.plot_items['probe'] = []
            viewer.create_segment_item('probe', [[0, 0, 0], [1, 0, 0]], 'G00', [0.2, 0.3, 0.4])
            rapid_item = viewer.plot_items['probe'][-1]
            self.assertEqual(rapid_item.color, RAPID_MOVE_COLOR + [RAPID_MOVE_ALPHA])
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_viewer_default_milling_camera_is_vertical_orthographic(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget, OrthographicGLViewWidget

        viewer = NCViewerWidget()
        try:
            viewer.set_machine_type('3축 MCT (X Y Z)', init_camera=True)
            self.assertIsInstance(viewer.gl_view, OrthographicGLViewWidget)
            self.assertTrue(viewer.gl_view.use_orthographic_projection)
            self.assertEqual(viewer.gl_view.opts['elevation'], 90)
            self.assertEqual(viewer.gl_view.opts['azimuth'], -90)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_main_splitter_keeps_program_panel_minimum_width(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            self.assertEqual(window.program_panel.minimumWidth(), app.PROGRAM_PANE_MIN_WIDTH)
            self.assertEqual(app.MAIN_SPLITTER_INITIAL_SIZES[0], app.PROGRAM_PANE_MIN_WIDTH)
            window.main_splitter.setSizes([120, 1000])
            qapp.processEvents()
            self.assertGreaterEqual(window.main_splitter.sizes()[0], app.PROGRAM_PANE_MIN_WIDTH)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_v142_ui_layout_defaults_and_machine_settings_panel(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            self.assertEqual(app.MAIN_SPLITTER_INITIAL_SIZES, [app.PROGRAM_PANE_MIN_WIDTH, 1125])
            self.assertEqual(app.INPUT_SPLITTER_INITIAL_SIZES, [480, 208])
            self.assertEqual(window.btn_machine_settings.text(), '장비 설정')
            self.assertEqual(window.machine_settings_panel.title(), '')
            panel_labels = [label.text() for label in window.machine_settings_panel.findChildren(app.QLabel)]
            self.assertIn('장비 타입 및 스펙 설정', panel_labels)
            self.assertTrue(window.machine_settings_panel.isHidden())
            window.set_mode('viewer')
            self.assertFalse(window.machine_settings_panel.isHidden())
            self.assertGreater(window.machine_type_combo.count(), 0)
            self.assertGreater(window.machine_spec_form.rowCount(), 0)

            program_layout = window.program_panel.layout()
            row1 = program_layout.itemAt(1).layout()
            row2 = program_layout.itemAt(2).layout()

            def button_texts(layout):
                texts = []
                for index in range(layout.count()):
                    widget = layout.itemAt(index).widget()
                    if isinstance(widget, app.QPushButton):
                        texts.append(widget.text())
                return texts

            self.assertEqual(button_texts(row1), ['지우기', '예제', '파일 열기'])
            self.assertEqual(button_texts(row2), ['프로그램 추가', '공구 리스트 생성'])
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_v142_splitter_size_settings_normalize_and_save(self):
        self.assertEqual(
            app.App._normalized_splitter_sizes(['500', '1000'], [430, 1125], 2),
            [500, 1000],
        )
        self.assertEqual(
            app.App._normalized_splitter_sizes('480,208', [480, 208], 2),
            [480, 208],
        )
        self.assertEqual(
            app.App._normalized_splitter_sizes([480, 0], [480, 208], 2),
            [480, 208],
        )

        class FakeSettings:
            store = {}

            def __init__(self, *_args):
                pass

            def value(self, key, default=None):
                return self.store.get(key, default)

            def setValue(self, key, value):
                self.store[key] = value

            def sync(self):
                pass

        FakeSettings.store = {}
        original_qsettings = app.QSettings
        app.QSettings = FakeSettings
        qapp = app.QApplication.instance() or app.QApplication([])
        window = app.App()
        try:
            window.main_splitter.setSizes([520, 900])
            window.set_mode('viewer')
            window.input_splitter.setSizes([480, 208])
            window.save_layout_settings()
            self.assertIn('window_geometry', FakeSettings.store)
            self.assertIn('window_state', FakeSettings.store)
            self.assertGreater(sum(FakeSettings.store['main_splitter_sizes']), 0)
            self.assertGreater(sum(FakeSettings.store['input_splitter_sizes']), 0)
        finally:
            window.deleteLater()
            app.QSettings = original_qsettings
            qapp.processEvents()

    def test_startup_never_forces_software_opengl_and_logs(self):
        # Forcing software OpenGL gives Qt an opengl32sw context while PyOpenGL keeps
        # calling system opengl32, so every GL call fails and the viewer renders black.
        source = Path('NC_Tool_List.py').read_text(encoding='utf-8-sig')
        self.assertNotIn('AA_UseSoftwareOpenGL', source)
        self.assertNotIn("'QT_OPENGL'", source)
        self.assertNotEqual(os.environ.get('QT_OPENGL'), 'software')
        self.assertTrue(callable(app.write_startup_log))
        self.assertIn('NC_Tool_List', str(app.startup_log_path()))

    def test_spec_keeps_opengl_collection_and_security_hardening(self):
        spec = Path('NC_Tool_List.spec').read_text(encoding='utf-8-sig')
        # PyOpenGL resolves its submodules dynamically, so the frozen build needs them all.
        self.assertIn("collect_submodules('OpenGL')", spec)
        self.assertNotIn("'OpenGL.raw.GLX'", spec)
        self.assertIn("'OpenGL.GLUT'", spec)
        self.assertIn('excluded_binary_fragments', spec)
        self.assertIn('freeglut', spec)
        self.assertIn('upx=False', spec)
    def test_installer_uses_c_drive_onedir_package_without_direct_taskkill(self):
        iss = Path('NC_Tool_List.iss').read_text(encoding='utf-8-sig')
        # 설치 스크립트와 EXE 버전 리소스는 앱 버전과 항상 같아야 한다
        # (버전을 올릴 때 한쪽만 고치는 동기화 누락을 막는다).
        self.assertIn('#define MyAppVersion "%s"' % app.APP_VERSION, iss)
        version_resource = Path('version_info.txt').read_text(encoding='utf-8-sig')
        major, minor, patch = app.current_version_tuple()
        self.assertIn('filevers=(%d, %d, %d, 0)' % (major, minor, patch), version_resource)
        self.assertIn('prodvers=(%d, %d, %d, 0)' % (major, minor, patch), version_resource)
        self.assertIn("u'FileVersion', u'%s.0'" % app.APP_VERSION, version_resource)
        self.assertIn("u'ProductVersion', u'%s.0'" % app.APP_VERSION, version_resource)
        self.assertIn('DefaultDirName=C:\\NC_Tool_List', iss)
        self.assertIn('UsePreviousAppDir=no', iss)
        self.assertIn('PrivilegesRequired=admin', iss)
        self.assertIn('CloseApplications=force', iss)
        self.assertIn('RestartApplications=no', iss)
        self.assertIn('Source: "dist\\NC_Tool_List\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs', iss)
        self.assertNotIn('taskkill.exe', iss)
        self.assertNotIn('/F /T /IM "{#MyAppExeName}"', iss)

    def test_installer_registers_nc_mpf_tap_file_associations(self):
        # v1.5.0 요청 사항 2: 설치 시 .nc/.mpf/.tap을 이 앱의 기본 프로그램으로 자동 등록.
        iss = Path('NC_Tool_List.iss').read_text(encoding='utf-8-sig')
        self.assertIn('ChangesAssociations=yes', iss)
        self.assertIn('[Registry]', iss)
        for ext in ('.nc', '.mpf', '.tap'):
            self.assertIn('Subkey: "%s"; ValueType: string; ValueName: ""; ValueData: "NCToolList.NCProgram"' % ext, iss)
        self.assertIn('Subkey: "NCToolList.NCProgram\\shell\\open\\command"', iss)
        self.assertEqual(app.FILE_ASSOCIATION_PROG_ID, 'NCToolList.NCProgram')
        self.assertEqual(app.FILE_ASSOCIATION_EXTENSIONS, ('.nc', '.mpf', '.tap'))
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_5axis_ac_and_bc_machine_settings_apply_different_g68_rotations(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        source = """M6T1
G43
G00 X0 Y0 Z0
G68.2 I90 J0 K0
G53.1
G01 X10 Y0 Z0
"""
        viewer = NCViewerWidget()
        try:
            viewer._save_machine_specs = lambda: None

            viewer.set_machine_type('5축 밀링 (A to C)')
            self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
            ac_pt = viewer.line_to_coord_map[5]

            viewer.set_machine_type('5축 밀링 (B to C)')
            bc_pt = viewer.line_to_coord_map[5]

            self.assertAlmostEqual(ac_pt[0], 0.0, places=6)
            self.assertAlmostEqual(ac_pt[1], 10.0, places=6)
            self.assertAlmostEqual(ac_pt[2], 0.0, places=6)
            self.assertAlmostEqual(bc_pt[0], 10.0, places=6)
            self.assertAlmostEqual(bc_pt[1], 0.0, places=6)
            self.assertAlmostEqual(bc_pt[2], 0.0, places=6)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_g02_g03_quarter_arc_traces_a_circle_in_opposite_directions(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        def arc_points(motion):
            source = """M6T1
G43
G00 X10 Y0 Z0
%s X-10 Y0 I-10 J0
""" % motion
            viewer = NCViewerWidget()
            viewer._save_machine_specs = lambda: None
            viewer.set_machine_type('3축 MCT (X Y Z)')
            self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
            pts = [n['pt'] for n in viewer.tool_paths['P001_T01'] if n['valid']]
            viewer.deleteLater()
            return pts

        qapp.processEvents()
        g02_pts = arc_points('G02')
        g03_pts = arc_points('G03')
        qapp.processEvents()

        for pts in (g02_pts, g03_pts):
            self.assertGreaterEqual(len(pts), 6)
            for x, y, _z in pts:
                self.assertAlmostEqual(math.hypot(x, y), 10.0, places=2)
            self.assertAlmostEqual(pts[-1][0], -10.0, places=6)
            self.assertAlmostEqual(pts[-1][1], 0.0, places=6)

        # G02 (clockwise) and G03 (counter-clockwise) must take opposite sides of the chord.
        g02_mid_y = g02_pts[len(g02_pts) // 2][1]
        g03_mid_y = g03_pts[len(g03_pts) // 2][1]
        self.assertTrue((g02_mid_y > 0) != (g03_mid_y > 0))

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_short_arc_is_not_collapsed_into_a_straight_line(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        radius = 50.0
        angle = math.radians(10)
        start = (radius, 0.0)
        end = (radius * math.cos(angle), radius * math.sin(angle))
        source = """M6T1
G43
G00 X%s Y%s Z0
G03 X%s Y%s I%s J0
""" % (start[0], start[1], end[0], end[1], -radius)

        viewer = NCViewerWidget()
        try:
            viewer._save_machine_specs = lambda: None
            viewer.set_machine_type('3축 MCT (X Y Z)')
            self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
            pts = [n['pt'] for n in viewer.tool_paths['P001_T01'] if n['valid']]
            # A 2-point result would mean the short arc degenerated into a straight chord.
            self.assertGreaterEqual(len(pts), 6)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_full_circle_arc_without_axis_words_is_drawn(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        source = """M6T1
G43
G00 X10 Y0 Z0
G02 I-10 J0
"""
        viewer = NCViewerWidget()
        try:
            viewer._save_machine_specs = lambda: None
            viewer.set_machine_type('3축 MCT (X Y Z)')
            self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
            pts = [n['pt'] for n in viewer.tool_paths['P001_T01'] if n['valid']]
            self.assertGreater(len(pts), 10)
            for x, y, _z in pts:
                self.assertAlmostEqual(math.hypot(x, y), 10.0, places=2)
            # The circle must close back near its starting point.
            self.assertAlmostEqual(pts[-1][0], 10.0, places=1)
            self.assertAlmostEqual(pts[-1][1], 0.0, places=1)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_g18_and_g19_plane_arcs_use_the_correct_axis_pair(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        g18_source = """M6T1
G43
G18
G00 X10 Y0 Z0
G02 X0 Z10 I-10 K0
"""
        g19_source = """M6T1
G43
G19
G00 X0 Y10 Z0
G02 Y0 Z10 J-10 K0
"""
        for source, plane_axes in ((g18_source, (0, 2)), (g19_source, (1, 2))):
            viewer = NCViewerWidget()
            try:
                viewer._save_machine_specs = lambda: None
                viewer.set_machine_type('3축 MCT (X Y Z)')
                self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
                pts = [n['pt'] for n in viewer.tool_paths['P001_T01'] if n['valid']]
                self.assertGreaterEqual(len(pts), 6)
                a_idx, b_idx = plane_axes
                for pt in pts:
                    self.assertAlmostEqual(math.hypot(pt[a_idx], pt[b_idx]), 10.0, places=2)
            finally:
                viewer.deleteLater()
                qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_helical_arc_interpolates_z_monotonically(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        source = """M6T1
G43
G00 X10 Y0 Z0
G02 X0 Y10 Z-5 I-10 J0
"""
        viewer = NCViewerWidget()
        try:
            viewer._save_machine_specs = lambda: None
            viewer.set_machine_type('3축 MCT (X Y Z)')
            self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
            pts = [n['pt'] for n in viewer.tool_paths['P001_T01'] if n['valid']]
            z_values = [pt[2] for pt in pts]
            self.assertTrue(all(z_values[i] >= z_values[i + 1] - 1e-9 for i in range(len(z_values) - 1)))
            self.assertAlmostEqual(z_values[-1], -5.0, places=6)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_5axis_arc_rotates_with_the_same_matrix_as_straight_moves(self):
        # Regression test for the v1.4.3-era bug where an arc's start point (pre-rotation)
        # and end point (already rotated) were mixed into one coordinate space, producing a
        # large jump instead of a continuous path once a G68.2/G53.1 tilt was active.
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        source = """M6T1
G43
G68.2 I0 J0 K90
G53.1
G00 X10 Y0 Z0
G02 X0 Y10 I-10 J0
"""
        viewer = NCViewerWidget()
        try:
            viewer._save_machine_specs = lambda: None
            viewer.set_machine_type('5축 밀링 (A to C)')
            self.assertTrue(viewer.set_source_text(source, {'T01': 'BALL EM'}))
            nodes = [n for n in viewer.tool_paths['P001_T01'] if n['valid']]
            rapid_end = nodes[0]['pt']
            first_arc_pt = nodes[1]['pt']
            jump = math.dist(rapid_end, first_arc_pt)
            # A correctly rotated arc continues from the rapid move with a small step; the
            # pre-fix bug produced a jump of roughly 14 units here.
            self.assertLess(jump, 3.0)
            last_arc_pt = nodes[-1]['pt']
            self.assertAlmostEqual(last_arc_pt[0], -10.0, places=6)
            self.assertAlmostEqual(last_arc_pt[1], 0.0, places=5)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    def test_append_nc_programs_adds_programs_below_m30_percent_tail(self):
        base = '%\nO1001\nM30\n%\n'
        extra = ' %\nO1002\nM30\n%\n '
        self.assertEqual(
            app.append_nc_programs(base, [extra, '']),
            '%\nO1001\nM30\n%\n\n%\nO1002\nM30\n%',
        )

    def test_startup_file_argument_returns_first_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / 'missing.nc')
            existing = Path(directory) / 'part.nc'
            existing.write_text('M30\n%', encoding='utf-8')
            self.assertEqual(
                app.startup_file_argument(['NC_Tool_List.exe', missing, str(existing)]),
                str(existing),
            )

    def test_default_pdf_filename(self):
        metadata = app.parse_program_metadata(self.source)
        self.assertEqual(
            app.default_pdf_filename(metadata),
            'K10M41017_OP10_O1017_TOOL_LIST.pdf',
        )

    # ---- v1.5.0: 업데이트 경로 지정 / 수동 업데이트 ----
    def test_app_settings_and_update_root_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            original = os.environ.get('APPDATA')
            os.environ['APPDATA'] = directory
            try:
                self.assertEqual(app.update_root_setting(), app.DEFAULT_UPDATE_ROOT)
                app.save_update_root_setting(r'D:\Custom\Update_Files')
                self.assertEqual(app.update_root_setting(), r'D:\Custom\Update_Files')
                # 빈 값으로 저장하면 기본 경로로 폴백
                app.save_update_root_setting('   ')
                self.assertEqual(app.update_root_setting(), app.DEFAULT_UPDATE_ROOT)
            finally:
                if original is None:
                    os.environ.pop('APPDATA', None)
                else:
                    os.environ['APPDATA'] = original

    def test_parse_installer_version_matches_expected_filename_pattern(self):
        self.assertEqual(app.parse_installer_version('NC_Tool_List_Setup_v1.5.1.exe'), (1, 5, 1))
        self.assertEqual(app.parse_installer_version('nc_tool_list_setup_v2.0.0.exe'), (2, 0, 0))
        self.assertIsNone(app.parse_installer_version('NC_Tool_List_Portable_v1.5.1.zip'))
        self.assertIsNone(app.parse_installer_version('random.exe'))
        self.assertIsNone(app.parse_installer_version(''))

    def test_find_latest_installer_selects_highest_version_and_ignores_others(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            for name in (
                'NC_Tool_List_Setup_v1.4.5.exe',
                'NC_Tool_List_Setup_v1.5.1.exe',
                'NC_Tool_List_Setup_v1.5.0.exe',
                'NC_Tool_List_Portable_v1.5.1.zip',
                'readme.txt',
            ):
                (directory_path / name).write_text('x', encoding='utf-8')
            result = app.find_latest_installer(directory)
            self.assertIsNotNone(result)
            path, version = result
            self.assertEqual(path.name, 'NC_Tool_List_Setup_v1.5.1.exe')
            self.assertEqual(version, (1, 5, 1))

    def test_find_latest_installer_returns_none_for_missing_or_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / 'does_not_exist')
            self.assertIsNone(app.find_latest_installer(missing))
            self.assertIsNone(app.find_latest_installer(directory))

    def test_current_version_tuple_matches_app_version(self):
        self.assertEqual(
            app.current_version_tuple(),
            tuple(int(part) for part in app.APP_VERSION.split('.')),
        )
        self.assertEqual(app.current_version_tuple('1.4.9'), (1, 4, 9))
        self.assertGreater(app.current_version_tuple('1.5.1'), app.current_version_tuple('1.5.0'))

    def test_copy_installer_to_temp_copies_file_into_temp_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'NC_Tool_List_Setup_v1.5.1.exe'
            source.write_text('installer bytes', encoding='utf-8')
            destination = app.copy_installer_to_temp(source)
            try:
                self.assertTrue(destination.exists())
                self.assertEqual(destination.name, source.name)
                self.assertEqual(destination.read_text(encoding='utf-8'), 'installer bytes')
            finally:
                destination.unlink(missing_ok=True)

    # ---- v1.5.0: 확장자 기본 프로그램 등록 ----
    def test_file_association_constants_and_command_string(self):
        self.assertEqual(app.FILE_ASSOCIATION_EXTENSIONS, ('.nc', '.mpf', '.tap'))
        self.assertEqual(app.FILE_ASSOCIATION_PROG_ID, 'NCToolList.NCProgram')
        command = app.file_association_command()
        self.assertIn(sys.executable, command)
        self.assertTrue(command.strip().endswith('"%1"'))

    @unittest.skipUnless(os.name == 'nt', 'file association registry only applies on Windows')
    def test_register_and_unregister_file_associations_round_trip(self):
        try:
            registered = app.register_file_associations()
        except OSError as error:
            self.skipTest('레지스트리에 접근할 수 없습니다: %s' % error)
            return
        try:
            self.assertTrue(registered)
            self.assertTrue(app.file_associations_status())
        finally:
            app.unregister_file_associations()
        self.assertFalse(app.file_associations_status())

    # ---- v1.5.0: 공정별 경로 필터 클릭 시 프로그램 위치 자동 이동 ----
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_viewer_process_filter_click_emits_first_line_of_that_process(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QListWidget
        from nc_viewer_widget import NCViewerWidget

        source = (
            "G00 X0 Y0 Z0\n"
            "M6T1\n"
            "G43\n"
            "G00 X10 Y0 Z0\n"
            "G01 X20 Y0 Z0\n"
            "M6T2\n"
            "G43\n"
            "G00 X30 Y0 Z0\n"
        )
        viewer = NCViewerWidget()
        list_widget = QListWidget()
        viewer.attach_tool_filter(list_widget)
        try:
            viewer.set_source_text(source, {'T01': 'FACE MILL', 'T02': 'DRILL'})
            keys = list(viewer.tool_paths)
            self.assertEqual(keys, ['Initial', 'P001_T01', 'P002_T02'])
            self.assertEqual(viewer.process_first_line['Initial'], 0)
            self.assertEqual(viewer.process_first_line['P001_T01'], 1)
            self.assertEqual(viewer.process_first_line['P002_T02'], 5)

            received = []
            viewer.process_activated.connect(received.append)
            second_process_item = list_widget.item(2)
            self.assertEqual(second_process_item.data(Qt.UserRole), 'P002_T02')
            list_widget.itemClicked.emit(second_process_item)
            self.assertEqual(received, [5])
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_app_process_filter_click_moves_program_cursor_to_process_start(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        source = (
            "G00 X0 Y0 Z0\n"
            "M6T1\n"
            "G43\n"
            "G00 X10 Y0 Z0\n"
            "G01 X20 Y0 Z0\n"
            "M6T2\n"
            "G43\n"
            "G00 X30 Y0 Z0\n"
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                nc_path = Path(directory) / 'sample.nc'
                nc_path.write_text(source, encoding='utf-8')
                window.load_file(str(nc_path))
                window.set_mode('viewer')
                qapp.processEvents()

                second_item = window.tool_filter.item(2)
                self.assertEqual(second_item.data(app.Qt.UserRole), 'P002_T02')
                window.tool_filter.itemClicked.emit(second_item)
                qapp.processEvents()

                self.assertEqual(window.src.textCursor().blockNumber(), 5)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    # ---- v1.5.1: PG 매칭 모드 (정적 경로를 지우고 커서 공정만 실시간 추적) ----
    PG_MATCH_SOURCE = (
        "G00 X0 Y0 Z0\n"
        "M6T1\n"
        "G43\n"
        "G00 X10 Y0 Z0\n"
        "G01 X20 Y0 Z0\n"
        "G01 X20 Y10 Z0\n"
        "G01 X20 Y20 Z0\n"
        "M6T2\n"
        "G43\n"
        "G00 X30 Y0 Z0\n"
        "G01 X40 Y0 Z0\n"
    )

    def _pg_match_viewer(self):
        from PyQt5.QtWidgets import QListWidget
        from nc_viewer_widget import NCViewerWidget

        viewer = NCViewerWidget()
        viewer.attach_tool_filter(QListWidget())
        viewer.set_source_text(self.PG_MATCH_SOURCE, {'T01': 'FACE MILL', 'T02': 'DRILL'})
        return viewer

    def _visible_trace_point_count(self, viewer):
        total = 0
        for item in viewer.dynamic_trace_items:
            if not item.visible():
                continue
            pos = getattr(item, 'pos', None)
            if pos is not None:
                total += len(pos)
        return total

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_pg_match_mode_hides_static_paths(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = self._pg_match_viewer()
        try:
            self.assertFalse(viewer.pg_match_mode)
            self.assertTrue(
                any(item.visible() for items in viewer.plot_items.values() for item in items)
            )

            viewer.set_pg_match_mode(True)
            self.assertTrue(viewer.pg_match_mode)
            for items in viewer.plot_items.values():
                for item in items:
                    self.assertFalse(item.visible())

            viewer.set_pg_match_mode(False)
            self.assertTrue(
                any(item.visible() for items in viewer.plot_items.values() for item in items)
            )
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_pg_match_mode_traces_only_cursor_process(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = self._pg_match_viewer()
        try:
            viewer.set_pg_match_mode(True)

            # 공정 2(P002_T02) 마지막 줄에 커서를 두면 그 공정만 추적된다.
            viewer.set_cursor_line(10)
            self.assertEqual(viewer.line_to_tool_map[10], 'P002_T02')
            second_points = self._visible_trace_point_count(viewer)
            self.assertGreater(second_points, 0)

            # 공정 1(P001_T01)로 커서를 올리면 트레이스가 그 공정 기준으로 다시 구성된다.
            viewer.set_cursor_line(6)
            self.assertEqual(viewer.line_to_tool_map[6], 'P001_T01')
            first_points = self._visible_trace_point_count(viewer)
            self.assertGreater(first_points, 0)
            self.assertNotEqual(first_points, second_points)

            # 커서 공정을 필터에서 해제하면 아무것도 그려지지 않는다.
            viewer.select_all_tools(False)
            self.assertEqual(self._visible_trace_point_count(viewer), 0)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_pg_match_mode_trace_grows_and_shrinks_with_cursor(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = self._pg_match_viewer()
        try:
            viewer.set_pg_match_mode(True)

            # 같은 공정 안에서 커서를 내리면 라인이 자라고, 올리면 지워진다.
            viewer.set_cursor_line(4)
            short_trace = self._visible_trace_point_count(viewer)
            viewer.set_cursor_line(6)
            long_trace = self._visible_trace_point_count(viewer)
            viewer.set_cursor_line(4)
            back_trace = self._visible_trace_point_count(viewer)

            self.assertGreater(long_trace, short_trace)
            self.assertEqual(back_trace, short_trace)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_app_pg_match_checkbox_toggles_viewer_mode(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            with tempfile.TemporaryDirectory() as directory:
                nc_path = Path(directory) / 'sample.nc'
                nc_path.write_text(self.PG_MATCH_SOURCE, encoding='utf-8')
                window.load_file(str(nc_path))
                window.set_mode('viewer')
                qapp.processEvents()

                # 앱을 새로 띄우면 항상 해제 상태로 시작한다.
                self.assertFalse(window.pg_match_check.isChecked())
                self.assertFalse(window.viewer.pg_match_mode)

                window.pg_match_check.setChecked(True)
                qapp.processEvents()
                self.assertTrue(window.viewer.pg_match_mode)
                for items in window.viewer.plot_items.values():
                    for item in items:
                        self.assertFalse(item.visible())

                window.pg_match_check.setChecked(False)
                qapp.processEvents()
                self.assertFalse(window.viewer.pg_match_mode)
                self.assertTrue(
                    any(
                        item.visible()
                        for items in window.viewer.plot_items.values()
                        for item in items
                    )
                )
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    # ---- v1.5.2: 읽기전용 편집기의 키보드 커서 + 행 강조 ----
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_readonly_program_editor_keeps_keyboard_cursor(self):
        # Qt의 setReadOnly(True)는 상호작용 플래그를 TextSelectableByMouse 하나로
        # 덮어써서 키보드 커서를 없애버린다. ProgramTextEdit는 이를 복원해야 한다.
        qapp = app.QApplication.instance() or app.QApplication([])
        editor = app.ProgramTextEdit()
        editor.setReadOnly(True)
        flags = editor.textInteractionFlags()
        self.assertTrue(bool(flags & app.Qt.TextSelectableByKeyboard))
        self.assertTrue(bool(flags & app.Qt.TextSelectableByMouse))
        self.assertTrue(editor.isReadOnly())
        editor.deleteLater()
        qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_app_arrow_and_pagedown_keys_move_program_cursor(self):
        from PyQt5.QtTest import QTest

        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            with tempfile.TemporaryDirectory() as directory:
                nc_path = Path(directory) / 'sample.nc'
                nc_path.write_text(REAL_NC_SAMPLE, encoding='utf-8')
                window.load_file(str(nc_path))
                window.set_mode('viewer')
                qapp.processEvents()

                window.src.setFocus()
                before = window.src.textCursor().blockNumber()
                QTest.keyClick(window.src, app.Qt.Key_Down)
                QTest.keyClick(window.src, app.Qt.Key_Down)
                qapp.processEvents()
                after_down = window.src.textCursor().blockNumber()
                self.assertGreater(after_down, before)

                QTest.keyClick(window.src, app.Qt.Key_PageDown)
                qapp.processEvents()
                after_pagedown = window.src.textCursor().blockNumber()
                self.assertGreater(after_pagedown, after_down)

                QTest.keyClick(window.src, app.Qt.Key_Up)
                qapp.processEvents()
                after_up = window.src.textCursor().blockNumber()
                self.assertLess(after_up, after_pagedown)

                # 뷰어 모드에서 방향키 이동이 3D 커서 라인도 그대로 따라간다.
                self.assertEqual(window.viewer.current_cursor_line, after_up)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_app_current_line_is_highlighted_as_full_width_block(self):
        from PyQt5.QtGui import QTextFormat

        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            with tempfile.TemporaryDirectory() as directory:
                nc_path = Path(directory) / 'sample.nc'
                nc_path.write_text(REAL_NC_SAMPLE, encoding='utf-8')
                window.load_file(str(nc_path))
                qapp.processEvents()

                selections = window.src.extraSelections()
                self.assertEqual(len(selections), 1)
                self.assertTrue(
                    selections[0].format.boolProperty(QTextFormat.FullWidthSelection)
                )
                self.assertEqual(selections[0].cursor.blockNumber(), 0)

                window.jump_to_process_line(5)
                qapp.processEvents()
                moved = window.src.extraSelections()
                self.assertEqual(len(moved), 1)
                self.assertEqual(moved[0].cursor.blockNumber(), 5)
                # jump_to_process_line은 앵커 선택을 만들지 않는다 — 강조가 그 역할을 한다.
                self.assertFalse(window.src.textCursor().hasSelection())
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    # ---- v1.5.2: 3D 뷰 마우스 감도 조정 ----
    def _fresh_gl_view(self):
        from nc_viewer_widget import OrthographicGLViewWidget
        gl_view = OrthographicGLViewWidget()
        gl_view.opts['azimuth'] = 45.0
        gl_view.opts['elevation'] = 30.0
        gl_view.opts['distance'] = 200.0
        return gl_view

    def _fire_mouse_move(self, gl_view, dx, dy=0.0):
        from PyQt5.QtCore import QPointF
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QMouseEvent
        gl_view.mousePos = QPointF(0.0, 0.0)
        event = QMouseEvent(
            QEvent.MouseMove, QPointF(dx, dy),
            app.Qt.NoButton, app.Qt.LeftButton, app.Qt.NoModifier,
        )
        gl_view.mouseMoveEvent(event)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_navigation_sensitivity_scales_mouse_drag_rotation(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        full = self._fresh_gl_view()
        reduced = self._fresh_gl_view()
        reduced.navigation_sensitivity = 0.4
        try:
            self._fire_mouse_move(full, 100.0)
            self._fire_mouse_move(reduced, 100.0)
            full_delta = full.opts['azimuth'] - 45.0
            reduced_delta = reduced.opts['azimuth'] - 45.0
            self.assertNotEqual(full_delta, 0.0)
            self.assertAlmostEqual(reduced_delta, full_delta * 0.4, places=5)
        finally:
            full.deleteLater()
            reduced.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_navigation_sensitivity_scales_wheel_zoom(self):
        from PyQt5.QtCore import QPoint

        class FakeWheelEvent:
            def __init__(self, dy):
                self._dy = dy

            def angleDelta(self):
                return QPoint(0, self._dy)

            def modifiers(self):
                return app.Qt.NoModifier

        qapp = app.QApplication.instance() or app.QApplication([])
        full = self._fresh_gl_view()
        reduced = self._fresh_gl_view()
        reduced.navigation_sensitivity = 0.4
        try:
            full.wheelEvent(FakeWheelEvent(240))
            reduced.wheelEvent(FakeWheelEvent(240))
            # 0.999**delta 형태라 배율이 아닌 지수이므로, log 비교로 감도가 실제로
            # delta에 곱해졌는지 확인한다 (delta=0이면 배율은 항상 1이 되어 버림).
            full_ratio = math.log(full.opts['distance'] / 200.0)
            reduced_ratio = math.log(reduced.opts['distance'] / 200.0)
            self.assertNotEqual(full_ratio, 0.0)
            self.assertAlmostEqual(reduced_ratio, full_ratio * 0.4, places=5)
        finally:
            full.deleteLater()
            reduced.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_navigation_sensitivity_persists_via_settings(self):
        import nc_viewer_widget as viewer_module

        class FakeSettings:
            store = {}

            def __init__(self, *_args):
                pass

            def value(self, key, default=None):
                return self.store.get(key, default)

            def setValue(self, key, value):
                self.store[key] = value

            def sync(self):
                pass

        FakeSettings.store = {}
        original_qsettings = viewer_module.QSettings
        viewer_module.QSettings = FakeSettings
        qapp = app.QApplication.instance() or app.QApplication([])
        try:
            first = viewer_module.NCViewerWidget()
            first.sensitivity_slider.setValue(70)
            self.assertAlmostEqual(FakeSettings.store['navigation_sensitivity'], 0.70, places=5)

            second = viewer_module.NCViewerWidget()
            self.assertEqual(second.sensitivity_slider.value(), 70)
            self.assertAlmostEqual(second.gl_view.navigation_sensitivity, 0.70, places=5)
            first.deleteLater()
            second.deleteLater()
            qapp.processEvents()
        finally:
            viewer_module.QSettings = original_qsettings

    # ---- v1.5.2: 3D 뷰 방향 큐브 ----
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_view_cube_face_click_sets_expected_camera_angles(self):
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertIsNotNone(viewer.view_cube)
            viewer.view_cube.resize(80, 80)

            viewer.view_cube.face_clicked.emit(90.0, -90.0)  # 윗면 -> XY
            self.assertEqual(viewer.gl_view.opts['elevation'], 90.0)
            self.assertEqual(viewer.gl_view.opts['azimuth'], -90.0)

            viewer.view_cube.face_clicked.emit(0.0, -90.0)  # 앞면 -> XZ
            self.assertEqual(viewer.gl_view.opts['elevation'], 0.0)
            self.assertEqual(viewer.gl_view.opts['azimuth'], -90.0)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_view_cube_paints_and_hit_tests_without_raising(self):
        from PyQt5.QtGui import QPixmap
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            cube = viewer.view_cube
            self.assertIsNotNone(cube)
            cube.resize(80, 80)
            pixmap = QPixmap(80, 80)
            cube.render(pixmap)
            self.assertGreater(len(cube._face_polygons), 0)
            # 큐브 중앙을 클릭해도 예외 없이 처리된다(어떤 면이든 맞을 수도, 안 맞을 수도 있음).
            from PyQt5.QtCore import QPoint
            from PyQt5.QtGui import QMouseEvent
            from PyQt5.QtCore import QEvent, QPointF
            click = QMouseEvent(
                QEvent.MouseButtonPress, QPointF(40, 40),
                app.Qt.LeftButton, app.Qt.LeftButton, app.Qt.NoModifier,
            )
            cube.mousePressEvent(click)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    # ---- v1.5.3: 대용량 파일 로드 시 행 강조가 사실상 멈추던 회귀 수정 ----
    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    @unittest.skipUnless(Path('ncdata.nc').exists(), 'ncdata.nc sample not present')
    def test_loading_large_real_program_does_not_hang(self):
        # v1.5.2에서 도입한 현재 행 강조(_highlight_current_line)가 QTextEdit +
        # NoWrap + 3만 줄대 문서 + 스플리터 내장이라는 조합에서 setExtraSelections()를
        # 사실상 멈춘 것처럼 보일 만큼 느리게 만들었다(현장 리포트: "파일 불러오기중
        # 멈춤"). 아주 작은 REAL_NC_SAMPLE로는 이 문제가 재현되지 않으므로, 실제
        # 대용량 샘플(ncdata.nc, 3만 줄 이상)로 명시적인 시간 제한을 두고 검증한다.
        # ProgramTextEdit을 QPlainTextEdit 기반으로 바꾼 것이 이 회귀의 수정이다.
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            started = time.time()
            window.load_file('ncdata.nc')
            elapsed = time.time() - started
            # 정상 동작이면 1초 안팎, 회귀 상태면 setExtraSelections() 한 줄에서
            # 20초 이상(사실상 무한정) 멈춘다 — 넉넉히 잡아도 5초는 이 둘을 가른다.
            self.assertLess(elapsed, 5.0)
            self.assertTrue(window.src.toPlainText())
            selections = window.src.extraSelections()
            self.assertEqual(len(selections), 1)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_program_editor_is_plain_text_edit_not_rich_text_edit(self):
        # QTextEdit(리치 텍스트)로 되돌아가면 위 성능 회귀가 다시 생긴다 — 기반
        # 클래스가 QPlainTextEdit인지를 직접 고정해 둔다.
        self.assertTrue(issubclass(app.ProgramTextEdit, app.QPlainTextEdit))


if __name__ == '__main__':
    unittest.main()
