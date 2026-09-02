import os
import re
import tempfile
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


if __name__ == '__main__':
    unittest.main()
