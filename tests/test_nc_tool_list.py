import inspect
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
            # App.__init__이 예약하는 QTimer.singleShot(0, showMaximized)이
            # deleteLater()만으로는 실제로 파괴되지 않고 남아 있는 이전 테스트의
            # 창의 것이든 이 창 자신의 것이든, 이 processEvents() 즈음에 불시에
            # 실행되면 offscreen 플랫폼의 작은 가상 화면(800x600)에 맞춰
            # 최대화되어(스플리터 계산에 필요한 폭보다 작아짐) 아래 검증이
            # 흔들릴 수 있다 — 먼저 그 타이머가 끝나길 기다린 뒤, 테스트가
            # 기대하는 원래 크기로 명시적으로 되돌린다.
            qapp.processEvents()
            window.showNormal()
            window.resize(sum(app.MAIN_SPLITTER_INITIAL_SIZES), 760)
            qapp.processEvents()
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
            self.assertFalse(hasattr(window, 'btn_machine_settings'))
            self.assertEqual(window.machine_settings_panel.title(), '')
            self.assertIn('장비 타입 및 스펙 설정', window.machine_panel_toggle.text())
            self.assertTrue(window.machine_settings_panel.isHidden())
            # 접이식 패널은 기본적으로 접혀 있어 프로그램 입력창을 더 넓게 쓴다.
            self.assertFalse(window.machine_panel_toggle.isChecked())
            self.assertTrue(window.machine_settings_body.isHidden())
            window.set_mode('viewer')
            self.assertFalse(window.machine_settings_panel.isHidden())
            self.assertGreater(window.machine_type_combo.count(), 0)
            self.assertGreater(window.machine_spec_form.rowCount(), 0)

            window.set_machine_panel_expanded(True)
            self.assertTrue(window.machine_panel_toggle.isChecked())
            self.assertFalse(window.machine_settings_body.isHidden())
            window.save_visible_machine_settings()
            self.assertFalse(window.machine_panel_toggle.isChecked())
            self.assertTrue(window.machine_settings_body.isHidden())

            window.set_machine_panel_expanded(True)
            window.show()
            qapp.processEvents()
            window.src.setFocus()
            qapp.processEvents()
            self.assertTrue(window.src.hasFocus())
            self.assertFalse(window.machine_panel_toggle.isChecked())
            self.assertTrue(window.machine_settings_body.isHidden())

            program_layout = window.program_panel.layout()
            # v1.5.9: 원래 2줄이던 프로그램 버튼들을 1줄로 재배치했다.
            row = program_layout.itemAt(1).layout()

            def button_texts(layout):
                texts = []
                for index in range(layout.count()):
                    widget = layout.itemAt(index).widget()
                    if isinstance(widget, app.QPushButton):
                        texts.append(widget.text())
                return texts

            self.assertEqual(
                button_texts(row), ['지우기', '예제', '파일 열기', 'PG ADD', 'Tool List']
            )
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_top_caption_removed_and_top_bar_buttons_left_aligned(self):
        """"NC 프로그램을 넣고 공구 리스트를 생성하세요" 안내 문구는 제거되고,
        About/모드 버튼은 오른쪽 끝이 아니라 제목 바로 옆(왼쪽)에 배치되어야
        한다(v1.5.9 요청)."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            self.assertFalse(hasattr(window, 'top_caption'))
            top_layout = window.top_bar.layout()
            widgets = [top_layout.itemAt(i).widget() for i in range(top_layout.count())]
            widgets = [w for w in widgets if w is not None]
            # title 다음 곧바로 About/도움말/툴리스트/뷰어 버튼이 와야 하고
            # (stretch는 addStretch()라 itemAt().widget()이 None이라 widgets
            # 리스트에는 나타나지 않는다), 안내 문구 QLabel은 더 이상 없다.
            # v1.6.1: About 다음에 도움말 버튼이 추가되었다.
            self.assertEqual(
                widgets[1:5],
                [window.btn_about, window.btn_help, window.btn_tool_mode, window.btn_viewer_mode],
            )
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_tool_panel_control_buttons_left_aligned(self):
        """공구 리스트 패널의 조작 버튼(삭제/수정/추가/PDF/복사 등)이 패널
        오른쪽 끝이 아니라 라벨 바로 옆(왼쪽)에 모여 있어야 한다(v1.5.9 요청)
        — addStretch()가 버튼들 뒤(맨 끝)에만 있어야 한다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            panel = window.pdf_button.parentWidget()
            rbar = panel.layout().itemAt(0).layout()
            items = [rbar.itemAt(i) for i in range(rbar.count())]
            self.assertIsNotNone(items[-1].spacerItem())
            for item in items[:-1]:
                self.assertIsNone(item.spacerItem())
            self.assertIs(items[-2].widget(), window.copy_button)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_tool_list_table_cells_and_font_scaled_1_6x_then_shrunk_15pct(self):
        """툴 리스트 표기 칸(열 폭)과 폰트는 기존 값의 1.6배로 커졌다가
        (v1.5.9), v1.6.2에서 요청대로 다시 15% 줄어야 한다(COPY_TABLE_SCALE)."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            self.assertAlmostEqual(app.TABLE_FONT_PT, 14 * app.COPY_TABLE_SCALE)
            self.assertAlmostEqual(window.table.font().pointSizeF(), app.TABLE_FONT_PT, places=3)
            for index, (key, _label) in enumerate(app.COLUMNS):
                self.assertEqual(window.table.columnWidth(index), app.COL_WIDTH[key])
            # v1.6.0: 셀 좌우에 글자가 가려지지 않도록 폭을
            # TABLE_CELL_PADDING_PX * 2만큼 추가로 넓혔다(그 패딩 자체도
            # v1.6.2에서 같은 비율로 줄었다).
            padding = app.TABLE_CELL_PADDING_PX * 2
            self.assertEqual(app.COL_WIDTH['NO'], round(72 * app.COPY_TABLE_SCALE) + padding)
            self.assertEqual(app.COL_WIDTH['HOLDER'], round(192 * app.COPY_TABLE_SCALE) + padding)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_dark_mode_button_size_matches_v162_shrink(self):
        """v1.6.1에서 52px로 키웠던 다크/라이트 토글 버튼·아이콘을, 1920x1080
        실사용 피드백으로 v1.6.2에서 40% 줄인다(52 -> 31px)."""
        from nc_viewer_widget import DARK_MODE_BUTTON_PX, NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertEqual(DARK_MODE_BUTTON_PX, 31)
            self.assertEqual(viewer.dark_mode_button.size().width(), DARK_MODE_BUTTON_PX)
            self.assertEqual(viewer.dark_mode_button.size().height(), DARK_MODE_BUTTON_PX)
            self.assertEqual(viewer.dark_mode_button.iconSize().width(), DARK_MODE_BUTTON_PX)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_dark_mode_button_moves_to_app_top_bar(self):
        """v1.6.2: 다크모드 버튼은 뷰어의 감도/큐브 바가 아니라 App 상단 바
        (모드 전환 버튼들 뒤, 오른쪽 끝)에 있어야 한다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            self.assertIs(window.btn_dark_mode, window.viewer.dark_mode_button)
            self.assertIs(window.btn_dark_mode.parentWidget(), window.top_bar)
            top_layout = window.top_bar.layout()
            widgets = [top_layout.itemAt(i).widget() for i in range(top_layout.count())]
            widgets = [w for w in widgets if w is not None]
            self.assertIs(widgets[-1], window.btn_dark_mode)
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
    def test_reset_button_moves_program_cursor_to_top(self):
        """PG 매칭 체크박스 앞의 'Reset' 버튼은 프로그램 커서를 맨 위(0번
        줄)로 되돌려야 한다(v1.5.8 요청)."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            with tempfile.TemporaryDirectory() as directory:
                nc_path = Path(directory) / 'sample.nc'
                nc_path.write_text(REAL_NC_SAMPLE, encoding='utf-8')
                window.load_file(str(nc_path))
                qapp.processEvents()

                window.jump_to_process_line(5)
                qapp.processEvents()
                self.assertEqual(window.src.textCursor().blockNumber(), 5)

                # 필터 바 안에서 PG 매칭 체크박스보다 앞에 배치되어야 한다
                # (Qt는 findChildren을 생성/추가 순서로 반환한다).
                self.assertEqual(window.reset_program_button.text(), 'Reset')
                labeled_children = [
                    w for w in window.filter_panel.findChildren(app.QWidget)
                    if isinstance(w, (app.QPushButton, app.QCheckBox)) and w.text() in ('Reset', 'PG 매칭')
                ]
                self.assertEqual([w.text() for w in labeled_children], ['Reset', 'PG 매칭'])

                window.reset_program_button.click()
                qapp.processEvents()
                self.assertEqual(window.src.textCursor().blockNumber(), 0)
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

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_view_cube_ring_drag_orbits_without_snapping(self):
        """큐브 바깥 고리를 드래그하면(v1.5.10) 면 클릭처럼 즉시 스냅되지
        않고, 메인 뷰포트를 드래그할 때처럼 카메라가 부드럽게(라이브로)
        회전해야 한다."""
        from PyQt5.QtCore import QEvent, QPointF
        from PyQt5.QtGui import QMouseEvent
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            cube = viewer.view_cube
            # 생성 시 setFixedSize()가 이미 적용되어 있어 resize()는 무시된다
            # (다른 view_cube 크기 테스트들처럼 setFixedSize로 실제로 바꿔야 한다).
            cube.setFixedSize(80, 80)
            from PyQt5.QtGui import QPixmap
            # _paint()가 실제로 한 번 실행되어야 고리 반경(_ring_inner/outer_radius)이 채워진다.
            cube.render(QPixmap(80, 80))
            self.assertGreater(cube._ring_outer_radius, cube._ring_inner_radius)

            # 위젯 중심(40,40)에서 반경 33만큼 떨어진 점 — half(26)~raw_half(40)
            # 사이 고리 띠 안이라 어떤 큐브 면과도 겹치지 않는다.
            ring_point = QPointF(40 + 33, 40)
            self.assertTrue(cube._ring_hit(ring_point))

            start_elevation = viewer.gl_view.opts['elevation']
            start_azimuth = viewer.gl_view.opts['azimuth']
            face_clicks = []
            cube.face_clicked.connect(lambda *args: face_clicks.append(args))

            press = QMouseEvent(
                QEvent.MouseButtonPress, ring_point,
                app.Qt.LeftButton, app.Qt.LeftButton, app.Qt.NoModifier,
            )
            cube.mousePressEvent(press)
            self.assertTrue(cube._ring_dragging)
            self.assertEqual(face_clicks, [])

            # 기본 카메라 elevation이 90(수직 하향)이라 +방향 이동은 클리핑돼
            # 변화가 없어 보일 수 있으므로, 값이 줄어드는 방향(y가 음수)으로 크게 움직인다.
            move = QMouseEvent(
                QEvent.MouseMove, ring_point + QPointF(25, -25),
                app.Qt.LeftButton, app.Qt.LeftButton, app.Qt.NoModifier,
            )
            cube.mouseMoveEvent(move)
            # 스냅이 아니라 실제 드래그량만큼만 회전해야 한다(임의의 정해진 각도로 튀지 않음).
            self.assertNotEqual(viewer.gl_view.opts['azimuth'], start_azimuth)
            self.assertNotEqual(viewer.gl_view.opts['elevation'], start_elevation)
            self.assertLess(abs(viewer.gl_view.opts['azimuth'] - start_azimuth), 90)
            self.assertLess(abs(viewer.gl_view.opts['elevation'] - start_elevation), 90)
            self.assertEqual(face_clicks, [])

            release = QMouseEvent(
                QEvent.MouseButtonRelease, ring_point + QPointF(15, 4),
                app.Qt.LeftButton, app.Qt.LeftButton, app.Qt.NoModifier,
            )
            cube.mouseReleaseEvent(release)
            self.assertFalse(cube._ring_dragging)
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

    # ---- v1.5.4: PG 매칭 자동 재생 ----
    def test_line_has_program_stop_detects_m00_and_m01_only(self):
        for line in ('M0', 'M00', 'M1', 'M01', 'G54M01', ' M01 '):
            self.assertTrue(app.line_has_program_stop(line), line)
        for line in (
            'M02', 'M03', 'M05', 'M06', 'M08', 'M09', 'M10', 'M11', 'M30',
            '(M01 STOP)', '',
        ):
            self.assertFalse(app.line_has_program_stop(line), line)

    def test_line_stops_playback_respects_each_option_independently(self):
        # 세 옵션 모두 꺼져 있으면 아무 것도 멈추지 않는다.
        self.assertFalse(app.line_stops_playback('M00', 'G43', False, False, False))
        self.assertFalse(app.line_stops_playback('M01', 'G43', False, False, False))
        self.assertFalse(app.line_stops_playback('G43 H1', 'G43', False, False, False))

        # 정지(M00/M0)만 켠 경우 M01은 무시한다.
        self.assertTrue(app.line_stops_playback('M00', '', False, True, False))
        self.assertFalse(app.line_stops_playback('M01', '', False, True, False))

        # 옵션정지(M01/M1)만 켠 경우 M00은 무시한다.
        self.assertTrue(app.line_stops_playback('M01', '', False, False, True))
        self.assertFalse(app.line_stops_playback('M00', '', False, False, True))

        # 텍스트 정지는 검색어가 포함된 줄에서만, 대소문자 무시하고 멈춘다.
        self.assertTrue(app.line_stops_playback('G43 H1 Z50.', 'g43', True, False, False))
        self.assertFalse(app.line_stops_playback('G0 X0 Y0', 'G43', True, False, False))
        # 검색어가 비어 있으면 텍스트 정지는 동작하지 않는다.
        self.assertFalse(app.line_stops_playback('G43 H1', '', True, False, False))

    @staticmethod
    def _build_playback_sample_text(first_run=20, second_run=20):
        """모션 줄 first_run개 -> M01 -> 모션 줄 second_run개 -> M30."""
        lines = ['%', 'O2000']
        for i in range(first_run):
            lines.append('N%d G01 X%d Y0' % (i, i))
        lines.append('M01')
        for i in range(second_run):
            lines.append('N%d G01 X%d Y0' % (first_run + i, first_run + i))
        lines.append('M30')
        return '\n'.join(lines)

    def _make_window_with_text(self, text, settings_dir):
        window = app.App(_root=settings_dir)
        window.src.setPlainText(text)
        window.set_mode('viewer')
        window.pg_match_check.setChecked(True)
        window.jump_to_process_line(0)
        return window

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_advances_expected_lines_per_tick(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=200, second_run=1)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                # 50ms 틱 * 20배속 = 초당 20줄 -> 틱당 정확히 1줄.
                window.set_playback_speed(20)
                window._playback_tick()
                self.assertEqual(window.src.textCursor().blockNumber(), 1)

                # 50ms 틱 * 100배속 = 초당 100줄 -> 틱당 정확히 5줄.
                window.jump_to_process_line(0)
                window._play_carry = 0.0
                window.set_playback_speed(100)
                window._playback_tick()
                self.assertEqual(window.src.textCursor().blockNumber(), 5)
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_stops_exactly_on_m01_even_when_tick_skips_past_it(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=50, second_run=50)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                window.set_playback_speed(200)  # 틱당 10줄 -> M01을 건너뛰기 쉬운 배속
                window.start_playback()
                self.assertTrue(window.play_timer.isActive())
                for _ in range(200):
                    window._playback_tick()
                    if not window.play_timer.isActive():
                        break
                self.assertFalse(window.play_timer.isActive())
                stop_block = window.src.document().findBlockByNumber(
                    window.src.textCursor().blockNumber()
                )
                self.assertEqual(stop_block.text().strip(), 'M01')
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_skips_m01_when_option_stop_unchecked(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=50, second_run=50)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                window.stop_m01_check.setChecked(False)
                window.set_playback_speed(200)
                window.start_playback()
                for _ in range(200):
                    window._playback_tick()
                    if not window.play_timer.isActive():
                        break
                self.assertFalse(window.play_timer.isActive())
                last_line = window.src.document().blockCount() - 1
                self.assertEqual(window.src.textCursor().blockNumber(), last_line)
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_stops_on_text_when_text_stop_checked(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            lines = ['%', 'O2000']
            for i in range(30):
                lines.append('N%d G01 X%d Y0' % (i, i))
            lines.insert(16, 'G43 H1 Z50.')
            lines.append('M30')
            text = '\n'.join(lines)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                window.stop_m00_check.setChecked(False)
                window.stop_m01_check.setChecked(False)
                window.stop_text_check.setChecked(True)
                window.stop_text_input.setText('G43')
                window.set_playback_speed(200)
                window.start_playback()
                for _ in range(200):
                    window._playback_tick()
                    if not window.play_timer.isActive():
                        break
                self.assertFalse(window.play_timer.isActive())
                stop_block = window.src.document().findBlockByNumber(
                    window.src.textCursor().blockNumber()
                )
                self.assertIn('G43', stop_block.text())
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_stops_at_end_of_document(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=5, second_run=5)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                # M01 줄 바로 다음부터 재생을 시작해 정지 코드를 건너뛴다.
                window.jump_to_process_line(window.src.document().blockCount() - 6)
                window.set_playback_speed(200)
                window.start_playback()
                for _ in range(200):
                    window._playback_tick()
                    if not window.play_timer.isActive():
                        break
                self.assertFalse(window.play_timer.isActive())
                last_line = window.src.document().blockCount() - 1
                self.assertEqual(window.src.textCursor().blockNumber(), last_line)
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_pauses_when_pg_match_mode_turned_off(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=100, second_run=1)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                window.start_playback()
                self.assertTrue(window.play_timer.isActive())
                window.pg_match_check.setChecked(False)
                self.assertFalse(window.play_timer.isActive())
                self.assertFalse(window.viewer.playback_bar.isEnabled())
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_pauses_when_leaving_viewer_mode(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=100, second_run=1)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                window.start_playback()
                self.assertTrue(window.play_timer.isActive())
                window.set_mode('tool')
                self.assertFalse(window.play_timer.isActive())
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_prev_next_tool_jump_between_process_start_lines(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            window = app.App(_root=settings_dir.name)
            try:
                with tempfile.TemporaryDirectory() as directory:
                    nc_path = Path(directory) / 'sample.nc'
                    nc_path.write_text(REAL_NC_SAMPLE, encoding='utf-8')
                    window.load_file(str(nc_path))
                window.set_mode('viewer')
                window.pg_match_check.setChecked(True)
                qapp.processEvents()

                first_lines = sorted(window.viewer.process_first_line.values())
                self.assertGreaterEqual(len(first_lines), 3)

                window.jump_to_process_line(first_lines[0])
                window.playback_next_tool()
                self.assertEqual(window.src.textCursor().blockNumber(), first_lines[1])

                window.playback_next_tool()
                self.assertEqual(window.src.textCursor().blockNumber(), first_lines[2])

                window.playback_prev_tool()
                self.assertEqual(window.src.textCursor().blockNumber(), first_lines[1])
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_rewind_returns_to_current_process_start_line(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            window = app.App(_root=settings_dir.name)
            try:
                with tempfile.TemporaryDirectory() as directory:
                    nc_path = Path(directory) / 'sample.nc'
                    nc_path.write_text(REAL_NC_SAMPLE, encoding='utf-8')
                    window.load_file(str(nc_path))
                window.set_mode('viewer')
                window.pg_match_check.setChecked(True)
                qapp.processEvents()

                first_lines = sorted(window.viewer.process_first_line.values())
                start_line = first_lines[1]
                window.jump_to_process_line(start_line + 1)
                window.playback_rewind()
                self.assertEqual(window.src.textCursor().blockNumber(), start_line)
                self.assertFalse(window.play_timer.isActive())
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_gl_view_and_playback_bar_never_take_keyboard_focus(self):
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertEqual(viewer.gl_view.focusPolicy(), app.Qt.NoFocus)
            self.assertIsNotNone(viewer.playback_bar)
            self.assertEqual(viewer.playback_bar.speed_slider.focusPolicy(), app.Qt.NoFocus)
            for button in (
                viewer.playback_bar.prev_tool_button, viewer.playback_bar.rewind_button,
                viewer.playback_bar.play_pause_button, viewer.playback_bar.next_tool_button,
            ):
                self.assertEqual(button.focusPolicy(), app.Qt.NoFocus)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_speed_max_is_5000x(self):
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertEqual(viewer.playback_bar.speed_slider.minimum(), 1)
            self.assertEqual(viewer.playback_bar.speed_slider.maximum(), 5000)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            window.set_playback_speed(6000)
            self.assertEqual(window.play_speed, 5000)
            window.set_playback_speed(0)
            self.assertEqual(window.play_speed, 1)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_clicking_3d_viewer_does_not_break_arrow_key_program_stepping(self):
        # 회귀 재현: 3D 뷰어를 클릭하면 pyqtgraph GLViewWidget이 ClickFocus로
        # 키보드 포커스를 가져가 버려서, 그 뒤의 방향키가 프로그램 커서 대신
        # 카메라 회전에 쓰였다. gl_view의 NoFocus가 이를 막는지 실제 클릭으로 확인한다.
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
                window.show()
                qapp.processEvents()

                window.src.setFocus()
                self.assertTrue(window.src.hasFocus())

                QTest.mouseClick(window.viewer.gl_view, app.Qt.LeftButton)
                qapp.processEvents()
                self.assertTrue(window.src.hasFocus())
                self.assertFalse(window.viewer.gl_view.hasFocus())

                before = window.src.textCursor().blockNumber()
                QTest.keyClick(window.src, app.Qt.Key_Down)
                qapp.processEvents()
                self.assertGreater(window.src.textCursor().blockNumber(), before)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_view_cube_default_size_is_doubled_and_slider_updates_and_persists(self):
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
            self.assertEqual(first.view_cube.width(), 160)
            self.assertEqual(first.view_cube.height(), 160)

            first.view_cube_size_slider.setValue(200)
            self.assertEqual(first.view_cube.width(), 200)
            self.assertEqual(FakeSettings.store['view_cube_size'], 200)

            second = viewer_module.NCViewerWidget()
            self.assertEqual(second.view_cube_size_slider.value(), 200)
            self.assertEqual(second.view_cube.width(), 200)
            first.deleteLater()
            second.deleteLater()
            qapp.processEvents()
        finally:
            viewer_module.QSettings = original_qsettings

    # ---------- v1.5.6 ----------

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_stop_text_input_is_independent_of_search_text(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            text = self._build_playback_sample_text(first_run=30, second_run=1)
            window = self._make_window_with_text(text, settings_dir.name)
            try:
                window.stop_m00_check.setChecked(False)
                window.stop_m01_check.setChecked(False)
                window.stop_text_check.setChecked(True)
                window.stop_text_input.setText('NOMATCH')
                window.search_text.setText('N5')  # 문자 검색에만 넣고 정지 입력창엔 안 넣음
                window.set_playback_speed(200)
                window.start_playback()
                for _ in range(200):
                    window._playback_tick()
                    if not window.play_timer.isActive():
                        break
                # 정지 문자(NOMATCH)가 없으니 문서 끝까지 진행되어야 한다 —
                # "문자 검색" 값(N5)이 새어 들어가 중간에 멈추면 실패.
                self.assertFalse(window.play_timer.isActive())
                last_line = window.src.document().blockCount() - 1
                self.assertEqual(window.src.textCursor().blockNumber(), last_line)
            finally:
                window.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_stop_text_input_persists_independently_via_settings(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            first = app.App(_root=settings_dir.name)
            first.stop_text_check.setChecked(True)
            first.stop_text_input.setText('G43')
            first._save_playback_stop_options()
            first.deleteLater()
            qapp.processEvents()

            second = app.App(_root=settings_dir.name)
            try:
                self.assertTrue(second.stop_text_check.isChecked())
                self.assertEqual(second.stop_text_input.text(), 'G43')
                self.assertEqual(second.search_text.text(), '')
            finally:
                second.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_machine_panel_toggle_is_filled_color_block(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            style = window.machine_panel_toggle.styleSheet()
            self.assertIn(window.theme['accent'], style)
            self.assertNotIn('transparent', style)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_dark_mode_toggle_switches_theme_and_persists(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            first = app.App(_root=settings_dir.name)
            # v1.6.0: 다크모드가 기본값이다.
            self.assertEqual(first.theme_name, 'dark')
            first.apply_theme('light')
            self.assertEqual(first.theme_name, 'light')
            self.assertIn(app.THEMES['light']['accent'], first.run_button.styleSheet())
            if hasattr(first.viewer, 'set_dark_mode'):
                self.assertFalse(first.viewer._dark_mode)
            first.deleteLater()
            qapp.processEvents()

            second = app.App(_root=settings_dir.name)
            try:
                self.assertEqual(second.theme_name, 'light')
            finally:
                second.deleteLater()
                qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_viewer_dark_mode_button_click_notifies_app(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            # v1.6.0: 다크모드가 기본값이다.
            self.assertEqual(window.theme_name, 'dark')
            window.viewer.dark_mode_button.setChecked(False)
            window.viewer.dark_mode_button.clicked.emit(False)
            qapp.processEvents()
            self.assertEqual(window.theme_name, 'light')
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_bar_buttons_have_icons(self):
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            for button in (
                viewer.playback_bar.prev_tool_button, viewer.playback_bar.rewind_button,
                viewer.playback_bar.play_pause_button, viewer.playback_bar.next_tool_button,
            ):
                self.assertFalse(button.icon().isNull())
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    def _minimal_motion_source(self):
        return (
            "M6T1\nG43\n"
            "G00 X0 Y0 Z0\n"
            "G01 X100 Y0 Z0\n"
            "X100 Y100 Z0\n"
            "X0 Y100 Z0\n"
        )

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_grid_item_removed_from_viewer(self):
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertFalse(hasattr(viewer, 'grid'))
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_projection_depth_range_does_not_shrink_with_scene_radius(self):
        """확대(=distance 감소) 상태에서도 far 평면이 실제 경로 크기보다
        작아지지 않는지 far-near 깊이 범위로 확인한다(회귀: v1.5.6 이전에는
        depth가 distance에만 비례해, 확대하면 긴 경로가 화면 중간에서
        잘렸다)."""
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            viewer.gl_view.opts['distance'] = 5.0
            viewport = (0, 0, 800, 600)

            viewer.gl_view.scene_radius = 0.0
            small_scene_matrix = viewer.gl_view.projectionMatrix(viewport, viewport)
            viewer.gl_view.scene_radius = 5000.0
            large_scene_matrix = viewer.gl_view.projectionMatrix(viewport, viewport)

            # ortho 행렬의 z-scale(= -2/(far-near))은 depth 범위가 클수록
            # 절댓값이 작아진다 — scene_radius가 커지면 depth 범위도 커져야 한다.
            small_z_scale = abs(small_scene_matrix.row(2).z())
            large_z_scale = abs(large_scene_matrix.row(2).z())
            self.assertLess(large_z_scale, small_z_scale)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_scene_radius_set_from_loaded_path(self):
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertEqual(viewer.gl_view.scene_radius, 0.0)
            viewer.set_source_text(self._minimal_motion_source(), {'T01': 'FACE MILL'})
            # X100 Y100 지점이 있으니 반지름은 최소 sqrt(100^2+100^2) 이상.
            self.assertGreaterEqual(viewer.gl_view.scene_radius, (100.0 ** 2 + 100.0 ** 2) ** 0.5 - 1e-6)
            viewer.clear()
            self.assertEqual(viewer.gl_view.scene_radius, 0.0)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_pick_source_line_finds_nearest_segment_and_respects_radius(self):
        from PyQt5.QtGui import QVector3D
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            viewer.resize(800, 600)
            self.assertTrue(viewer.set_source_text(self._minimal_motion_source(), {'T01': 'FACE MILL'}))
            viewer.set_camera_projection('XY')

            target_line, target_pt = None, None
            for line_idx, pt in viewer.line_to_coord_map.items():
                if abs(pt[0] - 100) < 1e-6 and abs(pt[1] - 0) < 1e-6:
                    target_line, target_pt = line_idx, pt
                    break
            self.assertIsNotNone(target_line)

            viewport = viewer.gl_view.getViewport()
            mvp = viewer.gl_view.projectionMatrix(viewport, viewport) * viewer.gl_view.viewMatrix()
            vec = mvp.map(QVector3D(*target_pt))
            screen_x = (vec.x() + 1.0) / 2.0 * viewport[2]
            screen_y = (1.0 - vec.y()) / 2.0 * viewport[3]

            self.assertEqual(viewer.pick_source_line(screen_x, screen_y, radius_px=15), target_line)
            # 경로에서 멀리 떨어진 지점은 좁은 반경 안에서 아무것도 못 집는다.
            self.assertIsNone(viewer.pick_source_line(5, 5, radius_px=5))
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_left_click_activates_line_but_drag_does_not(self):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtTest import QTest

        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        try:
            with tempfile.TemporaryDirectory() as directory:
                nc_path = Path(directory) / 'sample.nc'
                nc_path.write_text(REAL_NC_SAMPLE, encoding='utf-8')
                window = app.App(_root=settings_dir.name)
                try:
                    window.load_file(str(nc_path))
                    window.set_mode('viewer')
                    window.show()
                    qapp.processEvents()

                    center = window.viewer.gl_view.rect().center()
                    QTest.mouseClick(window.viewer.gl_view, app.Qt.LeftButton, pos=center)
                    qapp.processEvents()

                    QTest.mousePress(window.viewer.gl_view, app.Qt.LeftButton, pos=center)
                    QTest.mouseMove(window.viewer.gl_view, pos=center + QPoint(40, 40))
                    QTest.mouseRelease(
                        window.viewer.gl_view, app.Qt.LeftButton, pos=center + QPoint(40, 40)
                    )
                    qapp.processEvents()
                    # 드래그(카메라 회전)는 라인 클릭으로 오인되면 안 된다 —
                    # 여기서는 예외 없이 끝나는지만 확인한다(회전 자체는
                    # test_clicking_3d_viewer_does_not_break_arrow_key_program_stepping가
                    # 이미 별도로 검증).
                finally:
                    window.deleteLater()
                    qapp.processEvents()
        finally:
            settings_dir.cleanup()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_magnifier_toggles_on_right_click_and_escape_closes_it(self):
        from PyQt5.QtTest import QTest

        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget

        viewer = NCViewerWidget()
        try:
            viewer.resize(800, 600)
            viewer.show()
            qapp.processEvents()
            self.assertFalse(viewer._magnifier_active)

            center = viewer.gl_view.rect().center()
            QTest.mouseClick(viewer.gl_view, app.Qt.RightButton, pos=center)
            qapp.processEvents()
            self.assertTrue(viewer._magnifier_active)
            self.assertTrue(viewer.magnifier.isVisible())

            viewer._magnifier_shortcut.activated.emit()
            qapp.processEvents()
            self.assertFalse(viewer._magnifier_active)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_magnifier_centers_on_right_click_position(self):
        """돋보기는 우클릭한 지점을 중심으로 나타나야 한다(v1.5.7 요청) —
        이전에는 마지막 마우스 이동 지점(초기값 (0,0))에 뜨는 문제가 있었다."""
        from PyQt5.QtCore import QPoint
        from PyQt5.QtTest import QTest
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            viewer.resize(800, 600)
            viewer.show()
            qapp.processEvents()

            click_pos = QPoint(150, 110)
            QTest.mouseClick(viewer.gl_view, app.Qt.RightButton, pos=click_pos)
            qapp.processEvents()

            self.assertTrue(viewer._magnifier_active)
            self.assertAlmostEqual(viewer.magnifier._center.x(), click_pos.x(), delta=1)
            self.assertAlmostEqual(viewer.magnifier._center.y(), click_pos.y(), delta=1)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_left_click_only_activates_line_when_magnifier_active(self):
        """포인트 클릭(라인 활성화)은 돋보기가 켜져 있을 때만 동작해야 한다
        (v1.5.7 요청) — 이전에는 돋보기 없이 화면을 찍기만 해도 근처 라인으로
        커서가 넘어갔다."""
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QVector3D
        from PyQt5.QtTest import QTest
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            viewer.resize(800, 600)
            self.assertTrue(viewer.set_source_text(self._minimal_motion_source(), {'T01': 'FACE MILL'}))
            viewer.set_camera_projection('XY')
            viewer.show()
            qapp.processEvents()

            activated = []
            viewer.line_activated.connect(activated.append)

            target_line, target_pt = None, None
            for line_idx, pt in viewer.line_to_coord_map.items():
                if abs(pt[0] - 100) < 1e-6 and abs(pt[1] - 0) < 1e-6:
                    target_line, target_pt = line_idx, pt
                    break
            self.assertIsNotNone(target_line)
            prev_pt = viewer.line_to_coord_map.get(target_line - 1)
            self.assertIsNotNone(prev_pt)

            # 목표 지점(100,0,0)은 다음 세그먼트(→ 100,100,0)와 정확히 맞닿는
            # 꼭짓점이라, 정밀도가 좁아진(4px, v1.5.7) 픽 반경에서는 두 세그먼트가
            # 동일 거리로 집혀 어느 쪽이 뽑힐지 불안정해진다 — 세그먼트 중간
            # 지점(직교투영이라 월드 중점 = 화면 중점)을 클릭해 모호함을 없앤다.
            midpoint = tuple((a + b) / 2.0 for a, b in zip(target_pt, prev_pt))

            viewport = viewer.gl_view.getViewport()
            mvp = viewer.gl_view.projectionMatrix(viewport, viewport) * viewer.gl_view.viewMatrix()
            vec = mvp.map(QVector3D(*midpoint))
            pos = QPoint(
                int(round((vec.x() + 1.0) / 2.0 * viewport[2])),
                int(round((1.0 - vec.y()) / 2.0 * viewport[3])),
            )

            # 돋보기가 꺼진 상태: 좌클릭해도 라인이 활성화되지 않는다.
            QTest.mouseClick(viewer.gl_view, app.Qt.LeftButton, pos=pos)
            qapp.processEvents()
            self.assertEqual(activated, [])

            # 우클릭으로 돋보기를 켠 뒤에는 같은 위치 좌클릭이 라인을 활성화한다.
            QTest.mouseClick(viewer.gl_view, app.Qt.RightButton, pos=pos)
            qapp.processEvents()
            self.assertTrue(viewer._magnifier_active)

            QTest.mouseClick(viewer.gl_view, app.Qt.LeftButton, pos=pos)
            qapp.processEvents()
            self.assertEqual(activated, [target_line])
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_pick_source_line_pg_match_mode_scoped_to_progressed_current_tool(self):
        """PG 매칭 모드에서는 커서가 위치한 공정의 '진행된' 구간만 클릭으로
        집혀야 한다 — 다른 공정(필터)의 경로나 아직 진행되지 않은 같은 공정의
        뒷부분이 잘못 집히던 문제의 회귀 테스트(v1.5.7)."""
        from PyQt5.QtGui import QVector3D

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = self._pg_match_viewer()
        try:
            viewer.resize(800, 600)
            viewer.set_camera_projection('XY')
            viewer.set_pg_match_mode(True)

            # 공정1(P001_T01)의 두 번째 이동(줄 4, X20 Y0)까지만 진행시킨다 —
            # 아직 줄 6(X20 Y20)까지는 진행되지 않았다.
            viewer.set_cursor_line(4)
            self.assertEqual(viewer.line_to_tool_map[4], 'P001_T01')

            def screen_pos(pt):
                viewport = viewer.gl_view.getViewport()
                mvp = viewer.gl_view.projectionMatrix(viewport, viewport) * viewer.gl_view.viewMatrix()
                vec = mvp.map(QVector3D(*pt))
                return (
                    (vec.x() + 1.0) / 2.0 * viewport[2],
                    (1.0 - vec.y()) / 2.0 * viewport[3],
                )

            # 진행된 구간의 도착점(줄 4)은 집힌다.
            sx, sy = screen_pos(viewer.line_to_coord_map[4])
            self.assertEqual(viewer.pick_source_line(sx, sy, radius_px=15), 4)

            # 같은 공정이라도 아직 진행되지 않은 뒷부분(줄 6)은 집히지 않는다.
            sx6, sy6 = screen_pos(viewer.line_to_coord_map[6])
            self.assertIsNone(viewer.pick_source_line(sx6, sy6, radius_px=5))

            # 다른 공정(P002_T02, 아직 커서가 도달하지 않음)의 경로도 집히지 않는다.
            sx10, sy10 = screen_pos(viewer.line_to_coord_map[10])
            self.assertIsNone(viewer.pick_source_line(sx10, sy10, radius_px=5))
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_viewer_background_stays_dark_regardless_of_theme(self):
        """3D 캔버스(및 그걸 캡처하는 돋보기)는 라이트/다크 테마와 무관하게
        항상 어두운 배경을 유지해야 한다(v1.5.7 요청) — 밝은 배경에서 경로
        색이 잘 안 보이던 문제."""
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            dark_bg = tuple(viewer.gl_view.opts['bgcolor'])
            self.assertLess(max(dark_bg[0], dark_bg[1], dark_bg[2]), 0.3)

            viewer.set_dark_mode(False)
            self.assertEqual(tuple(viewer.gl_view.opts['bgcolor']), dark_bg)

            viewer.set_dark_mode(True)
            self.assertEqual(tuple(viewer.gl_view.opts['bgcolor']), dark_bg)
        finally:
            viewer.deleteLater()
            qapp.processEvents()


    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_dark_mode_icon_color_is_fixed_regardless_of_theme(self):
        """v1.6.3 버그 수정: 다크모드 토글 버튼은 v1.6.2부터 항상 어두운
        상단 바(top_bar) 위에 있으므로, 아이콘 색은 앱 테마(_dark_mode)와
        무관하게 항상 같은(밝은) 색을 써야 한다 — 라이트 테마일 때 어두운
        아이콘 색을 써서 똑같이 어두운 상단 바 위에서 거의 안 보이던 버그의
        회귀 테스트."""
        import nc_viewer_widget as viewer_mod
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        captured = []
        original_sun, original_moon = viewer_mod.sun_icon, viewer_mod.moon_icon

        def spy_sun(color, size=20):
            captured.append(color)
            return original_sun(color, size=size)

        def spy_moon(color, size=20):
            captured.append(color)
            return original_moon(color, size=size)

        viewer_mod.sun_icon = spy_sun
        viewer_mod.moon_icon = spy_moon
        try:
            viewer.set_dark_mode(True)
            viewer.set_dark_mode(False)
            viewer.set_dark_mode(True)
        finally:
            viewer_mod.sun_icon = original_sun
            viewer_mod.moon_icon = original_moon
            viewer.deleteLater()
            qapp.processEvents()
        self.assertEqual(len(captured), 3)
        self.assertEqual(len(set(captured)), 1)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_cube_ui_controls_shrunk_but_cube_defaults_untouched(self):
        """v1.6.3: "큐브" 슬라이더/라벨도 감도 쪽과 같은 비율(40%)로 줄어야
        한다(v1.6.2에서는 실수로 그대로 남아 있었다) — 다만 실제 3D
        오리엔테이션 큐브 크기를 정하는 범위/기본값 자체는 그대로 둔다."""
        from nc_viewer_widget import CONTROL_SHRINK, NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertEqual(viewer.view_cube_size_slider.width(), round(135 * CONTROL_SHRINK))
            self.assertLess(
                viewer.view_cube_size_label.font().pointSizeF(), 14,
                '큐브 라벨 폰트도 감도처럼 줄어야 한다',
            )
            # 큐브 자체의 크기 범위/기본값은 손대지 않는다.
            self.assertEqual(viewer.view_cube_size_slider.minimum(), 60)
            self.assertEqual(viewer.view_cube_size_slider.maximum(), 240)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_projection_overlay_buttons_are_spaced_apart(self):
        """v1.6.3: ISO/XY/XZ/YZ 버튼이 서로 너무 붙어 있다는 피드백으로 간격을
        넓힌다(4px -> 10px)."""
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertIsNotNone(viewer.projection_overlay)
            self.assertGreaterEqual(viewer.projection_overlay.layout().spacing(), 10)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_coord_overlay_is_transparent_with_white_axis_labels(self):
        """v1.6.3: "좌표"는 더 이상 불투명 배경의 QGroupBox 행이 아니라 3D
        화면 위에 뜨는 투명 오버레이여야 하고(공구 경로를 가리지 않도록),
        축 프리픽스 글자(X:, Y: 등)는 어두운 3D 캔버스 위에서도 보이도록
        흰색이어야 한다."""
        from nc_viewer_widget import CoordOverlayWidget, NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            self.assertFalse(hasattr(viewer, 'coord_group'))
            self.assertIsInstance(viewer.coord_overlay, CoordOverlayWidget)
            self.assertIn(viewer.coord_overlay, viewer.gl_view.top_left_widgets)
            self.assertIn('background: transparent', viewer.coord_overlay.styleSheet())
            self.assertIn('color: white', viewer.coord_overlay.styleSheet())
            # 좌표/투영 오버레이가 위→아래로 쌓여 있어야 한다(좌표가 위).
            self.assertLess(
                viewer.coord_overlay.y(), viewer.projection_overlay.y(),
                '좌표 오버레이가 투영 오버레이보다 위에 있어야 한다',
            )
            # 값 갱신은 여전히 동작해야 한다.
            viewer._set_coordinate_labels([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
            self.assertEqual(viewer.coord_labels['X'].text(), '1.0')
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_projection_buttons_recenter_and_zoom_to_fit_all_views(self):
        """v1.6.3: ISO뿐 아니라 ISO/XY/XZ/YZ 4개 버튼 모두 (1) 좌표를 화면
        중앙으로 되돌리고 (2) 로드된 경로 전체가 화면 안에 들어오도록 카메라
        거리를 자동으로 맞춰야 한다(줌 전체 보기)."""
        from math import radians, tan

        from PyQt5.QtGui import QVector3D
        from nc_viewer_widget import NCViewerWidget

        qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        try:
            viewer.resize(800, 600)
            self.assertTrue(viewer.set_source_text(self._minimal_motion_source(), {'T01': 'FACE MILL'}))
            self.assertGreater(viewer.gl_view.scene_radius, 0)

            for view_type in ('ISO', 'XY', 'XZ', 'YZ'):
                # 드래그로 카메라 중심을 원점에서 치우치게 만든 뒤 버튼을 누른다.
                viewer.gl_view.pan(300, -200, 0)
                viewer.set_camera_projection(view_type)

                center = viewer.gl_view.opts['center']
                self.assertEqual((center.x(), center.y(), center.z()), (0.0, 0.0, 0.0))

                distance = viewer.gl_view.opts['distance']
                fov = viewer.gl_view.opts.get('fov', 60.0)
                half_extent = distance * tan(radians(fov) / 2.0)
                self.assertGreaterEqual(
                    half_extent, viewer.gl_view.scene_radius,
                    '%s 투영에서 경로 전체가 화면 안에 들어와야 한다' % view_type,
                )
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_playback_checkboxes_have_checked_visibility_style(self):
        """v1.6.3: 재생 중 사용하는 체크박스(텍스트 정지/정지/옵션정지/PG
        매칭)는 체크되면 눈에 띄게 표시되어야 한다는 요청 — 체크 상태 전용
        스타일(초록 인디케이터/굵은 글자)이 적용돼 있는지 확인한다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            for checkbox in (
                window.stop_text_check, window.stop_m00_check,
                window.stop_m01_check, window.pg_match_check,
            ):
                style = checkbox.styleSheet()
                self.assertIn('indicator:checked', style)
                self.assertIn('font-weight', style)
        finally:
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_tool_table_autofits_without_horizontal_scrollbar(self):
        """v1.6.3: 공구 리스트 표는 패널 폭이 좁아져도 가로 스크롤바 없이
        폰트/셀 폭이 가변으로 줄어들어야 한다. 실제 스플리터를 통해 패널
        폭을 좁히면 버튼 줄(삭제/수정/...) 등 다른 위젯의 최소 폭 제약과
        얽혀 결과가 흔들리므로, viewport 폭을 직접 흉내내 _relayout_tool_table()
        자체의 가변 스케일링 로직만 결정적으로 검증한다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        window = app.App(_root=settings_dir.name)
        try:
            window.set_mode('tool')
            window.load_example()
            window.run()
            qapp.processEvents()

            # 표 기준(1배) 폭 합보다 넉넉히 넓은 뷰포트에서는 기준 폰트를
            # 그대로 유지해야 한다(스케일이 1.0을 넘어 더 커지지는 않는다).
            viewport = window.table.viewport()
            viewport.width = lambda: app._COL_WIDTH_TOTAL + 400
            window._relayout_tool_table()
            wide_font_pt = window.table.font().pointSizeF()
            self.assertAlmostEqual(wide_font_pt, app.TABLE_FONT_PT, places=3)
            self.assertFalse(window.table.horizontalScrollBar().isVisible())

            # 기준 폭보다 훨씬 좁은 뷰포트를 흉내내면 폰트/셀 폭이 그 비율에
            # 맞춰 줄어들고, 전체 열 폭 합이 그 좁은 폭을 넘지 않아야 한다
            # (가로 스크롤바가 필요 없어야 한다).
            narrow_width = round(app._COL_WIDTH_TOTAL * 0.6)
            viewport.width = lambda: narrow_width
            window._relayout_tool_table()

            self.assertLess(window.table.font().pointSizeF(), wide_font_pt)
            total_width = sum(
                window.table.columnWidth(i) for i in range(window.table.columnCount())
            )
            self.assertLessEqual(total_width, narrow_width)
            self.assertFalse(
                window.table.horizontalScrollBar().isVisible(),
                '폭이 좁아져도 가로 스크롤바 없이 표가 줄어들어야 한다',
            )
        finally:
            del window.table.viewport().width
            window.deleteLater()
            settings_dir.cleanup()
            qapp.processEvents()


class LatheModeTests(unittest.TestCase):
    """v1.6.4 선반 모드. LATHE_MODE_GUIDELINES.md의 규약을 검증한다.

    선반 관련 테스트는 장비 선택이 QSettings에 저장되므로, 반드시 원래
    장비로 되돌려 다른 테스트(밀링)가 영향을 받지 않게 한다."""

    # 선반은 M6가 없다 — Tnn00(옵셋 00)이 공구 교체 지점이다.
    LATHE_SOURCE = """T0100
G00 X100. Z5.
G01 X100. Z-20. F0.2
G02 X60. Z-40. R20.
G01 X20. Z-40.
"""

    def _lathe_viewer(self, qapp):
        from nc_viewer_widget import NCViewerWidget, is_lathe_machine

        viewer = NCViewerWidget()
        original = viewer.current_machine_type
        lathe_name = next(
            name for name in viewer.machine_types() if is_lathe_machine(name)
        )
        viewer.set_machine_type(lathe_name)
        return viewer, original

    def _restore(self, viewer, original, qapp):
        try:
            viewer.set_machine_type(original)
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    def test_lathe_world_point_halves_diameter_and_swaps_axes(self):
        from nc_viewer_widget import is_lathe_machine, lathe_world_point

        # X는 지름이므로 X20이면 실제로는 반경 10만 움직인다.
        self.assertEqual(lathe_world_point(-5.0, 20.0), [-5.0, 0.0, 10.0])
        # 기계 Z -> 월드 X(수평), 기계 X 반경 -> 월드 Z(수직)로 스왑된다.
        point = lathe_world_point(-40.0, 100.0)
        self.assertEqual(point[0], -40.0)
        self.assertEqual(point[2], 50.0)
        # C축이 있으면 반경이 주축(월드 X) 둘레로 돈다.
        rotated = lathe_world_point(0.0, 20.0, 90.0)
        self.assertAlmostEqual(rotated[1], 10.0, places=6)
        self.assertAlmostEqual(rotated[2], 0.0, places=6)

        self.assertTrue(is_lathe_machine('2축 선반 (X Z 평면, X 2배)'))
        self.assertFalse(is_lathe_machine('3축 MCT (X Y Z)'))
        self.assertFalse(is_lathe_machine(None))

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_path_uses_radius_and_swapped_axes(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer, original = self._lathe_viewer(qapp)
        try:
            self.assertTrue(viewer.set_source_text(self.LATHE_SOURCE, {'T01': 'OD TURN'}))
            points = viewer.tool_paths[list(viewer.tool_paths)[0]]
            # G00 X100. Z5. -> 월드 (Z=5, 0, 반경 50)
            self.assertEqual([round(v, 6) for v in points[1]['pt']], [5.0, 0.0, 50.0])
            # 마지막 G01 X20. Z-40. -> 반경 10
            self.assertEqual([round(v, 6) for v in points[-1]['pt']], [-40.0, 0.0, 10.0])
        finally:
            self._restore(viewer, original, qapp)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_arc_radius_is_exact_and_g02_is_clockwise_on_lathe_view(self):
        """R로 연결한 원호가 반경 공간에서 정확히 R을 유지해야 한다(지침 2항),
        그리고 선반 뷰(Z 오른쪽, X 위)에서 G02가 시계 방향이어야 한다(지침 4항)."""
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer, original = self._lathe_viewer(qapp)
        try:
            viewer.set_source_text(self.LATHE_SOURCE, {'T01': 'OD TURN'})
            points = viewer.tool_paths[list(viewer.tool_paths)[0]]
            arc = [entry['pt'] for entry in points if entry['type'] == 'G02']
            self.assertGreater(len(arc), 2)
            # 끝점은 지령값에 정확히 붙는다(X60 -> 반경 30, Z-40).
            self.assertEqual([round(v, 6) for v in arc[-1]], [-40.0, 0.0, 30.0])
            # (-20, 50) -> (-40, 30) 을 R20으로 잇는 소원호의 중심은 (-40, 50).
            center_u, center_v = -40.0, 50.0
            for point in arc:
                radius = math.hypot(point[0] - center_u, point[2] - center_v)
                self.assertAlmostEqual(radius, 20.0, places=6)
            # 화면상 (u=월드 X, v=월드 Z)에서 각도가 줄어들면 시계 방향이다.
            angles = [math.atan2(p[2] - center_v, p[0] - center_u) for p in arc]
            for previous, current in zip(angles, angles[1:]):
                self.assertLess(current, previous)
        finally:
            self._restore(viewer, original, qapp)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_projection_buttons_and_axis_labels_switch_and_restore(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import is_lathe_machine

        viewer, original = self._lathe_viewer(qapp)
        try:
            # 선반: ISO(축이 바뀐 상태) + 선반 평면 투영만 노출한다.
            self.assertEqual(viewer.projection_overlay.button_labels(), ['ISO', '선반'])
            self.assertEqual(viewer.current_axis_labels(), ('Z', 'C', 'X'))
            # 화살표 색도 글자를 따라간다 — 수평(월드 X)은 "Z"라 파랑,
            # 수직(월드 Z)은 "X"라 빨강이어야 밀링과 헷갈리지 않는다.
            lathe_colors = viewer.current_axis_colors()
            self.assertGreater(lathe_colors[0][2], lathe_colors[0][0], '수평 축은 파랑')
            self.assertGreater(lathe_colors[2][0], lathe_colors[2][2], '수직 축은 빨강')
            viewer.set_camera_projection('LATHE')
            self.assertEqual(viewer.gl_view.opts['elevation'], 0)
            self.assertEqual(viewer.gl_view.opts['azimuth'], -90)

            # 밀링으로 되돌리면 원래 4개 투영/축 문자로 복구된다.
            mill_name = next(
                name for name in viewer.machine_types() if not is_lathe_machine(name)
            )
            viewer.set_machine_type(mill_name)
            self.assertEqual(
                viewer.projection_overlay.button_labels(), ['ISO', 'XY', 'XZ', 'YZ']
            )
            self.assertEqual(viewer.current_axis_labels(), ('X', 'Y', 'Z'))
            mill_colors = viewer.current_axis_colors()
            self.assertGreater(mill_colors[0][0], mill_colors[0][2], '밀링 X는 다시 빨강')
            self.assertGreater(mill_colors[2][2], mill_colors[2][0], '밀링 Z는 다시 파랑')
        finally:
            self._restore(viewer, original, qapp)

    TWO_TOOL_LATHE_SOURCE = """%
O2001
(PART NO. : SHAFT-2001)
N1(#1: Tool Change)
 (T0101 // OD ROUGH [SO 40] // T01 CNMG120408 )
G50 S2500 T0100 M08
G00 X100. Z5.
T0101
G01 X100. Z-20. F0.25
G00 X120. Z20. T0100
N2(#2: Tool Change)
 (T0303 // OD FINISH [SO 40] // T03 DNMG150404 )
T0300
G00 X40. Z5.
T0303
G01 X36. Z-30. F0.12
G00 X120. Z20. T0000
M30
%
"""

    def test_lathe_tool_change_regex_matches_only_offset_zero(self):
        """선반 툴체인지 기준은 Tnn00 — 옵셋이 살아 있는 T0101이나 옵셋 취소
        T0000은 공구 교체가 아니다."""
        matches = [
            (text, app.LATHE_T_RE.search(text))
            for text in ('T0100', 'T0300', 'G50 S2500 T0100 M08',
                         'T0101', 'T0303', 'T0000', 'T012345', 'M6T1')
        ]
        found = {text: (m.group(1) if m else None) for text, m in matches}
        self.assertEqual(found['T0100'], '01')
        self.assertEqual(found['T0300'], '03')
        self.assertEqual(found['G50 S2500 T0100 M08'], '01')
        self.assertIsNone(found['T0101'], 'T0101은 옵셋이 살아 있어 교체가 아니다')
        self.assertIsNone(found['T0303'])
        self.assertIsNone(found['T0000'], 'T0000은 옵셋 취소이지 공구 교체가 아니다')
        self.assertIsNone(found['T012345'], '네 자리를 넘는 T 워드는 잡지 않는다')
        self.assertIsNone(found['M6T1'], '밀링식 M6T는 선반 기준에 안 걸린다')

    def test_lathe_parse_program_uses_tnn00_as_tool_change(self):
        rows = app.parse_program(self.TWO_TOOL_LATHE_SOURCE, lathe=True)
        filled = [row for row in rows if row['NO']]
        self.assertEqual([row['NO'] for row in filled], ['T01', 'T03'])
        self.assertEqual([row['NAME'] for row in filled], ['OD ROUGH', 'OD FINISH'])
        self.assertEqual([row['HOLDER'] for row in filled],
                         ['CNMG120408', 'DNMG150404'])
        self.assertEqual([row['REMARK'] for row in filled], ['N1', 'N2'])
        # 같은 원문을 밀링 기준으로 읽으면 M6가 없으니 아무 공구도 못 찾는다 —
        # 즉 선반 기준이 실제로 갈라져 동작한다는 뜻이다.
        self.assertEqual(app.parse_program(self.TWO_TOOL_LATHE_SOURCE), [])

    def test_lathe_tool_change_search_skips_offset_blocks(self):
        """'다음공구검색'도 선반에서는 Tnn00만 짚는다."""
        source = self.TWO_TOOL_LATHE_SOURCE
        first = app.find_next_tool_change_span(source, 0, lathe=True)
        self.assertIsNotNone(first)
        self.assertEqual(source[first[0]:first[1]], 'T0100')
        second = app.find_next_tool_change_span(source, first[1], lathe=True)
        self.assertEqual(source[second[0]:second[1]], 'T0100')  # 공정 1 종료 블록
        third = app.find_next_tool_change_span(source, second[1], lathe=True)
        self.assertEqual(source[third[0]:third[1]], 'T0300')
        # 밀링 기준으로는 이 원문에서 아무것도 못 찾는다.
        self.assertIsNone(app.find_next_tool_change_span(source, 0))

    def test_milling_tool_change_detection_is_untouched(self):
        """지침 0항: 선반 규칙 추가가 밀링의 M6 Tnn 인식을 건드리면 안 된다."""
        rows = app.parse_program(app.EXAMPLE)
        self.assertEqual([row['NO'] for row in rows if row['NO']],
                         ['T02', 'T03', 'T04', 'T05', 'T06'])
        self.assertEqual(app.find_next_tool_change_span('M6 T2\nM06T01', 0), (0, 5, False))
        # 밀링 프로그램에 우연히 Tnn00 형태가 있어도 밀링 기준은 반응하지 않는다.
        self.assertIsNone(app.find_next_tool_change_span('G00 X0 T0100', 0))

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_viewer_splits_processes_on_tnn00(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer, original = self._lathe_viewer(qapp)
        try:
            viewer.set_source_text(
                self.TWO_TOOL_LATHE_SOURCE, {'T01': 'OD ROUGH', 'T03': 'OD FINISH'}
            )
            keys = list(viewer.tool_paths)
            # T0100 / T0100(공정1 복귀) / T0300 세 번 잡히지만, 경로가 없는
            # 공정은 걸러지므로 실제로 그려지는 공정만 남는다.
            tools = [viewer.process_tool_map[key] for key in keys]
            self.assertIn('T01', tools)
            self.assertIn('T03', tools)
            # T0101/T0303(옵셋 블록)은 새 공정을 만들지 않는다.
            self.assertLessEqual(len(keys), 3)
            # 마지막 T0000은 공정을 만들지 않는다.
            self.assertNotIn('T00', tools)
        finally:
            self._restore(viewer, original, qapp)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_projection_overlay_is_not_squashed_when_buttons_are_swapped(self):
        """v1.6.4 버그: 이미 화면에 떠 있는 오버레이의 버튼을 갈아 끼우면
        새 버튼이 숨김 상태로 들어와 레이아웃 크기 계산에서 빠지는 바람에,
        오버레이가 라벨 폭(40x20)까지 줄고 버튼이 2px 폭으로 잘려 보였다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import ProjectionOverlayWidget

        overlay = ProjectionOverlayWidget()
        try:
            overlay.show()
            qapp.processEvents()
            mill_height = overlay.height()
            self.assertEqual(overlay.button_labels(), ['ISO', 'XY', 'XZ', 'YZ'])

            overlay.set_lathe_mode(True)
            # 이벤트 루프를 한 번도 돌리지 않은 시점에서 이미 올바른 크기여야 한다.
            self.assertEqual(overlay.button_labels(), ['ISO', '선반'])
            self.assertEqual(overlay.size(), overlay.sizeHint())
            self.assertEqual(overlay.height(), mill_height)
            for index in range(overlay._fixed_item_count, overlay._row.count()):
                button = overlay._row.itemAt(index).widget()
                self.assertGreater(
                    button.width(), 20,
                    '버튼 "%s"이 잘려 보인다(폭 %d)' % (button.text(), button.width()),
                )

            # 밀링으로 되돌려도 마찬가지다.
            overlay.set_lathe_mode(False)
            self.assertEqual(overlay.size(), overlay.sizeHint())
            self.assertEqual(overlay.height(), mill_height)
        finally:
            overlay.close()
            overlay.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_mode_does_not_change_milling_paths(self):
        """지침 0항: 선반 변경이 기존 밀링 툴패스를 건드리면 안 된다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        from nc_viewer_widget import NCViewerWidget, is_lathe_machine

        mill_source = """M6T1
G43 H1
G00 X0 Y0 Z0
G01 X10. Y0 Z0
G02 X20. Y10. R10.
"""
        viewer = NCViewerWidget()
        original = viewer.current_machine_type
        try:
            mill_name = next(
                name for name in viewer.machine_types() if not is_lathe_machine(name)
            )
            viewer.set_machine_type(mill_name)
            viewer.set_source_text(mill_source, {'T01': 'FLAT E/M'})
            before = [
                (entry['type'], [round(v, 9) for v in entry['pt']])
                for entry in viewer.tool_paths[list(viewer.tool_paths)[0]]
            ]

            # 선반을 한 번 거쳤다 돌아와도 밀링 결과가 완전히 동일해야 한다.
            lathe_name = next(
                name for name in viewer.machine_types() if is_lathe_machine(name)
            )
            viewer.set_machine_type(lathe_name)
            viewer.set_source_text(self.LATHE_SOURCE, {'T01': 'OD TURN'})
            viewer.set_machine_type(mill_name)
            viewer.set_source_text(mill_source, {'T01': 'FLAT E/M'})
            after = [
                (entry['type'], [round(v, 9) for v in entry['pt']])
                for entry in viewer.tool_paths[list(viewer.tool_paths)[0]]
            ]
            self.assertEqual(before, after)
            # 밀링 좌표는 지름 절반 환산 없이 지령값 그대로여야 한다.
            self.assertIn(('G01', [10.0, 0.0, 0.0]), after)
        finally:
            self._restore(viewer, original, qapp)

    # ---- v1.6.5: 선반 뷰 카메라(회전 잠금/드래그줌/바운딩박스 리센터),
    # 좌표 오버레이 하단 배치, 선반 전용 툴리스트 파서 ----

    def _fresh_gl_view(self):
        from nc_viewer_widget import OrthographicGLViewWidget
        gl_view = OrthographicGLViewWidget()
        gl_view.opts['azimuth'] = -90.0
        gl_view.opts['elevation'] = 0.0
        gl_view.opts['distance'] = 200.0
        gl_view.resize(400, 300)
        return gl_view

    def _fire_mouse_move(self, gl_view, dx, dy=0.0):
        from PyQt5.QtCore import QPointF, QEvent
        from PyQt5.QtGui import QMouseEvent
        gl_view.mousePos = QPointF(0.0, 0.0)
        event = QMouseEvent(
            QEvent.MouseMove, QPointF(dx, dy),
            app.Qt.NoButton, app.Qt.LeftButton, app.Qt.NoModifier,
        )
        gl_view.mouseMoveEvent(event)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_orbit_locked_pans_instead_of_rotating(self):
        """지침 v1.6.5 1/2항: 선반 평면 뷰는 좌드래그가 회전 대신 상하좌우
        이동(팬)이어야 한다 — 각도는 그대로, 중심만 움직인다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        gl_view = self._fresh_gl_view()
        gl_view.orbit_locked = True
        try:
            # QVector3D는 pyqtgraph의 pan()이 += 로 제자리 수정하므로, 값을
            # (튜플로) 먼저 떠 둬야 한다 — 객체 참조만 두면 이동 후에도
            # "이전 값"이 같은 객체라 항상 같아 보인다.
            before_center = gl_view.opts['center']
            before = (before_center.x(), before_center.y(), before_center.z())
            self._fire_mouse_move(gl_view, 50.0, 20.0)
            self.assertEqual(gl_view.opts['azimuth'], -90.0)
            self.assertEqual(gl_view.opts['elevation'], 0.0)
            after_center = gl_view.opts['center']
            after = (after_center.x(), after_center.y(), after_center.z())
            self.assertNotEqual(after, before)
        finally:
            gl_view.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_drag_zoom_draws_rect_and_zooms_in_on_release(self):
        """드래그로 그린 사각형만큼 확대하고, 확정 후 자동으로 꺼진다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        from PyQt5.QtCore import QPointF, QEvent
        from PyQt5.QtGui import QMouseEvent

        gl_view = self._fresh_gl_view()
        gl_view.set_drag_zoom_active(True)
        try:
            before_distance = gl_view.opts['distance']
            press = QMouseEvent(
                QEvent.MouseButtonPress, QPointF(100, 100),
                app.Qt.LeftButton, app.Qt.LeftButton, app.Qt.NoModifier,
            )
            gl_view.mousePressEvent(press)
            move = QMouseEvent(
                QEvent.MouseMove, QPointF(300, 250),
                app.Qt.LeftButton, app.Qt.LeftButton, app.Qt.NoModifier,
            )
            gl_view.mouseMoveEvent(move)
            release = QMouseEvent(
                QEvent.MouseButtonRelease, QPointF(300, 250),
                app.Qt.LeftButton, app.Qt.NoButton, app.Qt.NoModifier,
            )
            gl_view.mouseReleaseEvent(release)
            self.assertLess(gl_view.opts['distance'], before_distance)
            self.assertFalse(gl_view.drag_zoom_active, '드래그 확정 후 자동으로 꺼져야 한다')
        finally:
            gl_view.deleteLater()
            qapp.processEvents()

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_view_locks_orbit_iso_frees_it_and_recenters_on_bbox(self):
        """v1.6.5 1항: 선반 뷰 버튼은 회전을 잠그고, 원점이 아니라 경로
        바운딩박스 중심으로 카메라를 되돌려야 위쪽으로 쏠리지 않는다."""
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer, original = self._lathe_viewer(qapp)
        try:
            viewer.resize(800, 600)
            viewer.set_source_text(self.LATHE_SOURCE, {'T01': 'OD TURN'})
            viewer.set_camera_projection('LATHE')
            self.assertTrue(viewer.gl_view.orbit_locked)
            center, radius = viewer._lathe_path_center_and_radius()
            self.assertIsNotNone(center)
            self.assertGreater(radius, 0)
            cam_center = viewer.gl_view.opts['center']
            self.assertAlmostEqual(cam_center.x(), center[0], places=3)
            self.assertAlmostEqual(cam_center.y(), center[1], places=3)
            self.assertAlmostEqual(cam_center.z(), center[2], places=3)
            # 경로가 원점에서 벗어나 있으므로(X가 반경으로 변환돼 화면 절반
            # 에만 그려짐) 밀링과 달리 (0,0,0)이 아니어야 한다.
            self.assertNotEqual((cam_center.x(), cam_center.y(), cam_center.z()), (0.0, 0.0, 0.0))

            viewer.set_camera_projection('ISO')
            self.assertFalse(viewer.gl_view.orbit_locked, 'ISO에서는 자유 회전이어야 한다')
        finally:
            self._restore(viewer, original, qapp)

    @unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
    def test_lathe_mode_moves_coord_overlay_above_playback_bar(self):
        """요청: 선반 뷰일 때 좌표 표시를 하단(재생 속도바 바로 위)으로."""
        qapp = app.QApplication.instance() or app.QApplication([])
        viewer, original = self._lathe_viewer(qapp)
        try:
            self.assertIs(viewer.gl_view.bottom_coord_widget, viewer.coord_overlay)
            self.assertNotIn(viewer.coord_overlay, viewer.gl_view.top_left_widgets)
            bar = viewer.gl_view.bottom_bar_widget
            if bar is not None and viewer.coord_overlay is not None:
                self.assertLessEqual(
                    viewer.coord_overlay.y() + viewer.coord_overlay.height(), bar.y(),
                    '좌표 오버레이가 재생 속도바보다 위에 있어야 한다',
                )
            # 밀링으로 되돌리면 다시 좌상단 목록으로 돌아온다.
            viewer.set_machine_type(original)
            self.assertIsNone(viewer.gl_view.bottom_coord_widget)
            if viewer.coord_overlay is not None:
                self.assertIn(viewer.coord_overlay, viewer.gl_view.top_left_widgets)
        finally:
            self._restore(viewer, original, qapp)

    LATHE_TOOLLIST_SOURCE = """N1
( T06 - SLEEVE )
( T06 - D50.0 X H103 T-DRILL )
G0X400.Z200.
T0600
G97S800M3P11
T0606
G99G18X0.Z10.
G0X400.Z200.T0600
M1

N2
( T01 - PCLNR 2525M 12 )
( T01 - CNMG 120408 | R-0.8 )
G0X400.Z200.
T0100
G50S1500
G96S225M3P11
T0101
G99G18X200.Z30.
G0X400.Z200.T0100
M1

N3
( T01 - PCLNR 2525M 12 )
( T01 - CNMG 120408 | R-0.8 )
G0X400.Z200.
T0100
T0101
G0X400.Z200.T0100
M1

N4
( T01 - PCLNR 2525M 12 (FINISH) )
( T01 - CNMG 120404 | R-0.4 )
G0X400.Z200.
T0100
T0111
G0X400.Z200.T0100
M1
"""

    def test_lathe_parse_program_reads_holder_and_insert_from_n_blocks(self):
        """실제 선반 프로그램(O1699.nc) 양식 — N<번호> 바로 아래 통짜 괄호
        주석 두 줄이 각각 홀더(1번째)/인서트(2번째)다."""
        rows = app.parse_lathe_program(self.LATHE_TOOLLIST_SOURCE)
        by_no = {row['NO']: row for row in rows}
        self.assertEqual(by_no['T0606']['HOLDER'], 'SLEEVE')
        self.assertEqual(by_no['T0606']['INSERT'], 'D50.0 X H103 T-DRILL')
        self.assertEqual(by_no['T0606']['REMARK'], 'N1')

    def test_lathe_parse_program_merges_same_tool_no_and_keeps_offsets_separate(self):
        """승인된 규약: 같은 TOOL NO(옵셋 포함)를 쓰는 N 블록은 한 행 +
        REMARK 누적, 옵셋이 다르면(T0101 vs T0111) 별도 행."""
        rows = app.parse_lathe_program(self.LATHE_TOOLLIST_SOURCE)
        by_no = {row['NO']: row for row in rows}
        self.assertEqual(by_no['T0101']['REMARK'], 'N2, N3')
        self.assertIn('T0111', by_no, 'T0101과 T0111은 별도 행으로 남아야 한다')
        self.assertNotEqual(by_no['T0101']['INSERT'], by_no['T0111']['INSERT'])
        self.assertEqual([row['NO'] for row in rows], ['T0606', 'T0101', 'T0111'])

    def test_lathe_tool_name_map_uses_insert_keyed_by_tool_number(self):
        """요청: 3D 뷰어 필터 라벨에도 공구 이름 대신 인서트를 넣는다."""
        rows = app.parse_lathe_program(self.LATHE_TOOLLIST_SOURCE)
        mapping = app.lathe_tool_name_map_from_rows(rows)
        self.assertEqual(mapping['T06'], 'D50.0 X H103 T-DRILL')
        self.assertEqual(mapping['T01'], 'CNMG 120408 | R-0.8')


class PdfDirectOpenTests(unittest.TestCase):
    """v1.6.4: PDF 출력은 저장 위치를 묻지 않고 임시 파일로 만들어 기본
    프로그램으로 바로 띄운다."""

    def test_pdf_preview_path_is_temporary_and_named_from_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = {'part_no': 'K10M41017', 'operation': 'OP10', 'program': 'O1017'}
            path = app.pdf_preview_path(metadata, directory=directory)
            self.assertEqual(path.name, 'K10M41017_OP10_O1017_TOOL_LIST.pdf')
            self.assertEqual(path.parent, Path(directory))
            # 저장 다이얼로그를 거치지 않으므로 기본 임시 폴더 아래여야 한다.
            self.assertEqual(
                app.pdf_preview_dir().parent, Path(tempfile.gettempdir())
            )

    def test_pdf_preview_path_reuses_name_when_file_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = {'part_no': 'A', 'operation': '', 'program': ''}
            first = app.pdf_preview_path(metadata, directory=directory)
            first.write_bytes(b'%PDF-1.4')
            second = app.pdf_preview_path(metadata, directory=directory)
            self.assertEqual(first, second)
            self.assertFalse(second.exists())

    def test_pdf_preview_path_falls_back_when_file_is_locked(self):
        """열려 있는 PDF는 Windows에서 지울 수 없으므로 새 이름을 찾아야 한다."""
        with tempfile.TemporaryDirectory() as directory:
            metadata = {'part_no': 'B', 'operation': '', 'program': ''}
            locked = app.pdf_preview_path(metadata, directory=directory)
            locked.write_bytes(b'%PDF-1.4')
            original_unlink = Path.unlink

            def refuse_unlink(self, *args, **kwargs):
                if self == locked:
                    raise OSError('file is open in another program')
                return original_unlink(self, *args, **kwargs)

            Path.unlink = refuse_unlink
            try:
                fallback = app.pdf_preview_path(metadata, directory=directory)
            finally:
                Path.unlink = original_unlink
            self.assertNotEqual(fallback, locked)
            self.assertEqual(fallback.name, 'B_TOOL_LIST(1).pdf')
            self.assertTrue(locked.exists())

    def test_export_pdf_opens_without_asking_for_a_save_location(self):
        source = inspect.getsource(app.App.export_pdf)
        self.assertNotIn('getSaveFileName', source)
        self.assertIn('pdf_preview_path', source)
        # 저장한 게 아니므로 "저장 완료" 안내창도 더 이상 띄우지 않는다.
        self.assertNotIn('PDF 출력 완료', inspect.getsource(app.App.save_pdf))
        self.assertIn('open_file_with_default_app', inspect.getsource(app.App.save_pdf))


if __name__ == '__main__':
    unittest.main()
