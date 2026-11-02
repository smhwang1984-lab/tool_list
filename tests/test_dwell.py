"""v2.2.5: G4(G04) 휴즈 — 지령 해석, 경로 불변, 가공시간, 자동 재생 정지."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'

import NC_Tool_List as app

MILL = '3축 MCT (X Y Z)'


@unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
class ParseDwellTest(unittest.TestCase):
    def test_requested_durations(self):
        from nc_viewer_widget import parse_dwell

        self.assertAlmostEqual(parse_dwell('G4X1.0')[0], 1.0)
        self.assertAlmostEqual(parse_dwell('G4P1000')[0], 1.0)
        self.assertAlmostEqual(parse_dwell('G4P500')[0], 0.5)
        self.assertAlmostEqual(parse_dwell('G04X1.0')[0], 1.0)
        self.assertAlmostEqual(parse_dwell('N10G04P500')[0], 0.5)

    def test_fanuc_units(self):
        from nc_viewer_widget import parse_dwell

        self.assertAlmostEqual(parse_dwell('G4X1000')[0], 1.0)   # 소수점 없는 X = ms
        self.assertAlmostEqual(parse_dwell('G4X.5')[0], 0.5)
        self.assertAlmostEqual(parse_dwell('G04U1.5')[0], 1.5)   # 선반 U
        self.assertAlmostEqual(parse_dwell('G4')[0], 0.0)

    def test_strips_time_words(self):
        from nc_viewer_widget import parse_dwell

        self.assertEqual(parse_dwell('N10G04X1.0'), (1.0, 'N10'))
        self.assertEqual(parse_dwell('G4P500M8'), (0.5, 'M8'))

    def test_trailing_decimal_point_is_seconds(self):
        from nc_viewer_widget import parse_dwell

        self.assertEqual(parse_dwell('G04X1.'), (1.0, ''))
        self.assertEqual(parse_dwell('N5G4U2.M8'), (2.0, 'N5M8'))

    def test_only_the_time_word_is_removed(self):
        from nc_viewer_widget import parse_dwell

        self.assertEqual(parse_dwell('G4P500M98P1000'), (0.5, 'M98P1000'))

    def test_f_word_is_seconds_not_feed(self):
        from nc_viewer_widget import parse_dwell

        self.assertEqual(parse_dwell('G4F2.5'), (2.5, ''))

    def test_other_g_codes_are_not_dwell(self):
        from nc_viewer_widget import parse_dwell

        for code in ('G40X10.', 'G41D1X5.', 'G43H1Z50.', 'G43.4H1', 'G49', 'G54X0',
                     'G94F100', 'G01X4.', 'G0X1.0'):
            self.assertEqual(parse_dwell(code), (None, code), code)


@unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
class ViewerDwellTest(unittest.TestCase):
    SOURCE = """M6T1
G43
G00 X0 Y0 Z0
G01 X100 Y0 Z0 F1000
G04 X1.0
G4 P1000
G4 P500
G01 X200 Y0 Z0
"""

    def _viewer(self, source, machine_type=None):
        from nc_viewer_widget import NCViewerWidget

        self.qapp = app.QApplication.instance() or app.QApplication([])
        viewer = NCViewerWidget()
        self.addCleanup(self.qapp.processEvents)
        self.addCleanup(viewer.deleteLater)
        # 장비 종류는 설정에 저장되므로 테스트마다 명시하고 밀링으로 되돌린다.
        self.addCleanup(viewer.set_machine_type, MILL)
        viewer.set_machine_type(machine_type or MILL)
        self.assertTrue(viewer.set_source_text(source, {'T01': 'END MILL'}))
        return viewer

    def test_dwell_x_word_does_not_move_tool(self):
        viewer = self._viewer(self.SOURCE)
        key = list(viewer.tool_paths)[0]
        xs = [round(p['pt'][0], 6) for p in viewer.tool_paths[key]]
        self.assertNotIn(1.0, xs)
        self.assertEqual(xs[-1], 200.0)
        # 좌표 표시도 휴즈 시간을 X로 보여 주지 않는다.
        self.assertEqual(viewer.modal_state_map[4][0], viewer.modal_state_map[3][0])

    def test_dwell_adds_to_machining_time(self):
        viewer = self._viewer(self.SOURCE)
        # 절삭 100mm/1000 = 6초 x 2 + 휴즈 1 + 1 + 0.5초
        self.assertAlmostEqual(viewer.total_time_sec, 14.5, places=3)
        key = list(viewer.tool_paths)[0]
        self.assertAlmostEqual(viewer.process_time_sec[key], 14.5, places=3)
        self.assertAlmostEqual(viewer.elapsed_seconds_at_line(3), 6.0, places=3)
        self.assertAlmostEqual(viewer.elapsed_seconds_at_line(4), 7.0, places=3)
        self.assertAlmostEqual(viewer.elapsed_seconds_at_line(6), 8.5, places=3)
        self.assertAlmostEqual(viewer.elapsed_seconds_at_line(7), 14.5, places=3)
        self.assertAlmostEqual(viewer.dwell_seconds_at_seq(4), 1.0)
        self.assertAlmostEqual(viewer.dwell_seconds_at_seq(6), 0.5)
        self.assertEqual(viewer.dwell_seconds_at_seq(3), 0.0)

    def test_lathe_dwell_x_is_not_a_diameter(self):
        from nc_viewer_widget import MACHINE_LATHE

        body = """T0100
G97 S1000 M3
G00 X50. Z2.
G01 Z-10. F0.1
%sG00 X60.
"""
        def path(viewer):
            return [tuple(round(v, 6) for v in p['pt'])
                    for pts in viewer.tool_paths.values() for p in pts]

        plain = self._viewer(body % '', MACHINE_LATHE)
        expected, plain_time = path(plain), plain.total_time_sec
        dwell = self._viewer(body % 'G04 X1.0\n', MACHINE_LATHE)
        self.assertEqual(path(dwell), expected)  # X1.0(지름 1)로 가지 않는다
        self.assertAlmostEqual(dwell.total_time_sec, plain_time + 1.0, places=3)

    def test_lathe_dwell_outside_process_keeps_timeline(self):
        from nc_viewer_widget import MACHINE_LATHE

        viewer = self._viewer("""N1 T0100
G97 S1000 M3
G00 X50. Z2.
G01 Z-10. F0.1
G00 X60.
M01
G04 U1.
N2 T0200
G97 S1000 M3
G00 X40. Z2.
G01 Z-5. F0.1
G00 X60.
M30
""", MACHINE_LATHE)
        self.assertAlmostEqual(sum(viewer.process_time_sec.values()), viewer.total_time_sec, places=6)
        last_seq = viewer.sequence_length() - 1
        self.assertAlmostEqual(viewer.elapsed_seconds_at_seq(last_seq), viewer.total_time_sec, places=6)

    def test_trailing_dwell_counts(self):
        viewer = self._viewer("""M6T1
G43
G00 X0 Y0 Z0
G01 X100 Y0 Z0 F1000
G4 P500
M30
""")
        self.assertAlmostEqual(viewer.total_time_sec, 6.5, places=3)


@unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
class PlaybackDwellTest(unittest.TestCase):
    def test_playback_holds_on_dwell_line(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        lines = ['%', 'O2000']
        lines += ['N%d G01 X%d Y0 F100' % (i, i) for i in range(10)]
        lines.append('G4 P500')
        lines += ['N%d G01 X%d Y0' % (10 + i, 10 + i) for i in range(10)]
        lines.append('M30')
        dwell_line = lines.index('G4 P500')
        window = app.App(_root=settings_dir.name)
        try:
            window.src.setPlainText('\n'.join(lines))
            window.set_mode('viewer')
            window.pg_match_check.setChecked(True)
            window.jump_to_process_line(0)
            window.set_playback_speed(200)  # 틱당 10줄 -> 휴즈 줄을 건너뛸 배속
            window.start_playback()
            for _ in range(5):
                window._playback_tick()
                if window.src.textCursor().blockNumber() == dwell_line:
                    break
            self.assertEqual(window.src.textCursor().blockNumber(), dwell_line)
            self.assertAlmostEqual(window._dwell_remaining, 0.5)
            # 0.5초 = 50ms 틱 10번 동안 그 줄에 머문다.
            for _ in range(10):
                window._playback_tick()
                self.assertEqual(window.src.textCursor().blockNumber(), dwell_line)
            self.assertEqual(window._dwell_remaining, 0.0)
            self.assertTrue(window.play_timer.isActive())
            window._playback_tick()
            self.assertGreater(window.src.textCursor().blockNumber(), dwell_line)
            window.pause_playback()
        finally:
            window.deleteLater()
            qapp.processEvents()


if __name__ == '__main__':
    unittest.main()
