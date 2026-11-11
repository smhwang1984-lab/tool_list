"""v2.3.3 — 파일 변경 감지·새로고침 / PG 매칭 실시간 형상 / 공정 필터 선택 시 경로선 표시.

실제 사용자 QSettings를 건드리지 않는다(App은 _root 임시 폴더, 뷰어는 장비 속성만 바꾼다)."""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

import NC_Tool_List as app

try:
    from PyQt5.QtWidgets import QApplication, QListWidget
    import nc_sim
    import nc_sim3d
    from nc_viewer_widget import NCViewerWidget
    VIEWER_ERROR = None
except Exception as exc:  # noqa: BLE001
    VIEWER_ERROR = exc

needs_qt = pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt 없음')
needs_viewer = pytest.mark.skipif(VIEWER_ERROR is not None, reason='뷰어 의존성 없음')

MILLING = '3축 MCT (X Y Z)'
SHAPES = {
    'T1': {'type': 'FLAT E/M', 'D': 6.0, 'FL': 20.0, 'R': None, 'SIG': None, 'PL': None, 'SO': 30.0},
    'T2': {'type': 'BALL E/M', 'D': 4.0, 'FL': 10.0, 'R': None, 'SIG': None, 'PL': None, 'SO': 20.0},
}
NAMES = {'T1': 'D6 F.EM', 'T2': 'D4 B.EM'}
SIM_PROGRAM = """M6T1
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
PROGRAM = (
    'N1(#1: Tool Change)\n'
    ' (T1 // D50 F.MIL [SO 90] // T1 BT40-FMC22-90)\n'
    ' (SO    90.000000 GL   115.000000 PL )\n'
    'M6 T1\nG0 X0 Y0\nG1 X10 F300\nM30\n'
)


# ---------------------------------------------------------------- 내용 이어 붙이기
def test_compose_matches_load_then_add():
    assert app.compose_program_texts(['A\n'], True) == 'A\n'
    assert app.compose_program_texts(['A\n', '  B\n', '\n', 'C'], True) == 'A\n\n\nB\n\nC'
    # 빈 문서에 [추가]로 시작했으면 첫 파일도 공백을 떼고 붙인다
    assert app.compose_program_texts([' A \n', 'B\n'], False) == 'A\n\nB'
    assert app.compose_program_texts([], True) == ''


# ---------------------------------------------------------------- 파일 변경 감지
@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    return tmp_path


@pytest.fixture
def window(appdata):
    qapp = QApplication.instance() or QApplication([])
    win = app.App(_root=str(appdata / 'root'))
    asked = []

    def ask(names, modified):
        asked.append((list(names), modified))
        return win._test_answer

    win._test_answer = True
    win._asked = asked
    win._ask_reload_changed_files = ask
    qapp.processEvents()
    yield win
    win.deleteLater()
    qapp.processEvents()


def _write(path, text):
    path.write_bytes(text.encode('utf-8'))
    # 같은 초에 두 번 써도 수정 시각이 달라지도록 앞으로 민다
    stamp = os.stat(path).st_mtime_ns + 2_000_000_000
    os.utime(path, ns=(stamp, stamp))


@needs_qt
def test_changed_file_asks_and_reloads_keeping_cursor(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    assert window.file_watcher.files()
    window.jump_to_process_line(4)
    _write(path, PROGRAM.replace('X10', 'X25'))
    window.check_file_sources_changed()
    assert window._asked == [(['p.nc'], False)]
    assert 'X25' in window.src.toPlainText()
    assert window.src.textCursor().blockNumber() == 4
    assert not window.src.document().isModified()
    # 다시 확인해도 같은 내용이면 묻지 않는다
    window.check_file_sources_changed()
    assert len(window._asked) == 1


@needs_qt
def test_ignore_is_remembered_until_next_change(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    window._test_answer = False
    _write(path, PROGRAM.replace('X10', 'X25'))
    window.check_file_sources_changed()
    assert len(window._asked) == 1 and 'X10' in window.src.toPlainText()
    window.check_file_sources_changed()
    assert len(window._asked) == 1                 # [무시]한 내용은 다시 묻지 않는다
    _write(path, PROGRAM.replace('X10', 'X30'))
    window.check_file_sources_changed()
    assert len(window._asked) == 2                 # 또 바뀌면 다시 묻는다


@needs_qt
def test_touch_without_content_change_does_not_ask(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    _write(path, PROGRAM)
    window._check_file_stamps()
    assert window.file_change_timer.isActive()     # 수정 시각이 바뀌어 확인은 한다
    window.check_file_sources_changed()
    assert window._asked == []


@needs_qt
def test_own_save_does_not_ask(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    window._set_edit_mode(True)
    window.src.selectAll()
    window.src.insertPlainText(PROGRAM.replace('X10', 'X12'))
    assert window.save_edit()
    window.check_file_sources_changed()
    assert window._asked == []


@needs_qt
def test_unsaved_edit_is_reported_in_question(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    window._set_edit_mode(True)
    window.src.selectAll()
    window.src.insertPlainText(PROGRAM.replace('X10', 'X12'))
    _write(path, PROGRAM.replace('X10', 'X25'))
    window.check_file_sources_changed()
    assert window._asked == [(['p.nc'], True)]
    assert 'X25' in window.src.toPlainText() and not window.src.document().isModified()


@needs_qt
def test_deleted_file_only_shows_status(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    path.unlink()
    window.check_file_sources_changed()
    assert window._asked == []
    assert 'p.nc' in window.search_status.text()
    # 같은 이름으로 다시 생기면 다시 지켜보고 묻는다
    _write(path, PROGRAM.replace('X10', 'X25'))
    window.check_file_sources_changed()
    assert len(window._asked) == 1 and 'X25' in window.src.toPlainText()
    assert str(path) in window.file_watcher.files()


@needs_qt
def test_merged_files_reload_in_same_order(window, appdata):
    first, second = appdata / 'a.nc', appdata / 'b.nc'
    _write(first, PROGRAM)
    _write(second, '\nO2000\nG0 X1\nM30\n')
    window.drop_file([str(first), str(second)])
    before = window.src.toPlainText()
    assert window._file_sources == [str(first), str(second)]
    _write(second, '\nO2000\nG0 X7\nM30\n')
    window.check_file_sources_changed()
    assert window.src.toPlainText() == before.replace('G0 X1', 'G0 X7')


@needs_qt
def test_example_text_is_not_watched(window, appdata):
    path = appdata / 'p.nc'
    _write(path, PROGRAM)
    window.load_file(str(path))
    window.load_example()
    assert window._file_sources == [] and window.file_watcher.files() == []


# ---------------------------------------------------------------- 뷰어 공통
@pytest.fixture
def viewer():
    qapp = QApplication.instance() or QApplication([])   # 참조를 들고 있어야 한다
    view = NCViewerWidget()
    view._keep_qapp = qapp
    view.current_machine_type = MILLING          # 저장 없이 속성만
    filt = QListWidget()
    view.attach_tool_filter(filt)
    view.set_source_text(SIM_PROGRAM, NAMES, SHAPES)
    view._sim_sync = True
    view._keep_filter = filt
    yield view
    view.deleteLater()


def _spec():
    return nc_sim.StockSpec({'T': 8.0, 'W': 60.0, 'L': 60.0}, {'T': 'Z', 'W': 'Y', 'L': 'X'})


def _fresh_heights(seq):
    view = NCViewerWidget()
    view.current_machine_type = MILLING
    view.set_source_text(SIM_PROGRAM, NAMES, SHAPES)
    view._sim_sync = True
    view.apply_stock_spec(_spec(), 0.5, True)
    view._sim_advance_to_seq(seq)
    assert view.sim_wait()
    heights = view.sim_stock.heights.copy()
    view.deleteLater()
    return heights


# ---------------------------------------------------------------- 경로선 표시 규칙
@needs_viewer
def test_partial_filter_selection_shows_lines_even_when_option_off(viewer):
    viewer.set_toolpath_visible(False)
    keys = list(viewer.plot_items)
    assert len(keys) == 2
    assert not viewer.toolpath_lines_visible()                      # 전체 선택 — 옵션대로
    assert not any(item.visible() for item in viewer.plot_items[keys[0]])
    viewer.set_selected_tools({keys[0]})
    assert viewer.toolpath_lines_visible()
    assert all(item.visible() for item in viewer.plot_items[keys[0]])
    assert not any(item.visible() for item in viewer.plot_items[keys[1]])
    viewer.select_all_tools(True)
    assert not any(item.visible() for items in viewer.plot_items.values() for item in items)
    viewer.set_toolpath_visible(True)
    assert all(item.visible() for items in viewer.plot_items.values() for item in items)


@needs_viewer
def test_pg_match_trace_follows_same_rule(viewer):
    viewer.set_toolpath_visible(False)
    viewer.set_pg_match_mode(True)
    viewer.set_cursor_seq(8)
    assert not any(item.visible() for item in viewer.dynamic_trace_items)
    first = list(viewer.plot_items)[0]
    viewer.set_selected_tools({first})
    viewer.set_cursor_seq(8)
    assert any(item.visible() for item in viewer.dynamic_trace_items)


# ---------------------------------------------------------------- 실시간 형상
@needs_viewer
def test_live_shape_cuts_to_cursor_and_matches_fresh_result(viewer):
    viewer.apply_stock_spec(_spec(), 0.5, True)
    end = viewer._sim_target_seq_for_selection()
    viewer.set_pg_match_mode(True)
    viewer.set_sim_live_enabled(True)
    assert viewer.sim_live_active()
    for seq in (5, 7, 9, 15, 16):                                   # 앞으로
        viewer.set_cursor_seq(seq)
        assert viewer.sim_wait()
        assert viewer.sim_last_seq == seq
        np.testing.assert_array_equal(viewer.sim_stock.heights, _fresh_heights(seq))
    for seq in (14, 6, 3):                                          # 뒤로(스냅샷)
        viewer.set_cursor_seq(seq)
        assert viewer.sim_wait()
        np.testing.assert_array_equal(viewer.sim_stock.heights, _fresh_heights(seq))
    viewer.set_sim_live_enabled(False)                               # 끄면 공정 필터 기준
    assert viewer.sim_wait()
    assert viewer.sim_last_seq == end
    np.testing.assert_array_equal(viewer.sim_stock.heights, _fresh_heights(end))


@needs_viewer
def test_live_shape_needs_pg_match_and_stock(viewer):
    viewer.set_sim_live_enabled(True)
    assert not viewer.sim_live_active() and viewer.sim_live_speed_cap() is None
    viewer.apply_stock_spec(_spec(), 0.5, True)
    assert not viewer.sim_live_active()
    viewer.set_pg_match_mode(True)
    assert viewer.sim_live_active()
    assert viewer.sim_live_speed_cap() is None      # v2.5.2: 배속 상한 없음
    viewer.set_pg_match_mode(False)
    assert viewer.sim_live_speed_cap() is None
    assert viewer.sim_last_seq == viewer._sim_target_seq_for_selection()


@needs_viewer
def test_live_mesh_refresh_is_throttled(viewer, monkeypatch):
    viewer.apply_stock_spec(_spec(), 0.5, True)
    viewer.set_pg_match_mode(True)
    viewer.set_sim_live_enabled(True)
    delays = []
    monkeypatch.setattr('nc_viewer_widget.QTimer.singleShot',
                        lambda delay, fn: delays.append(delay))
    viewer._sim_mesh_refresh_pending = False
    viewer._sim_mesh_last_cost = 0.0
    viewer._sim_mesh_last_time = __import__('time').monotonic()
    viewer._sim_request_mesh_refresh()
    assert delays and 100 < delays[-1] <= NCViewerWidget.SIM_LIVE_MESH_INTERVAL_MS
    viewer._sim_request_mesh_refresh()                               # 이미 예약됨 — 또 예약하지 않는다
    assert len(delays) == 1
    viewer._sim_mesh_refresh_pending = False
    viewer._sim_mesh_last_cost = 1.0                                 # 지난 갱신 1초 → 2초 쉰다
    viewer._sim_request_mesh_refresh()
    assert delays[-1] > 1500


@needs_viewer
def test_voxel_display_mesh_quads_max_coarsens():
    bounds = {'X': (-10.0, 10.0), 'Y': (-10.0, 10.0), 'Z': (-10.0, 0.0)}
    stock = nc_sim3d.VoxelStock(bounds, 0.25)
    stock.occ[20:60, 20:60, 30:] = 0                                 # 홈을 파서 표면을 만든다
    stock._version += 1
    _v, full_faces, _c, _e = stock.display_mesh()
    _v, coarse_faces, _c, _e = stock.display_mesh(quads_max=500)
    assert 0 < len(coarse_faces) < len(full_faces)


# ---------------------------------------------------------------- 재생 상한·대기
@needs_qt
@needs_viewer
def test_playback_speed_is_capped_and_waits_for_live_shape(window, appdata):
    path = appdata / 'p.nc'
    _write(path, SIM_PROGRAM)
    window.load_file(str(path))
    window.set_mode('viewer')
    viewer = window.viewer
    window.set_playback_speed(1000)
    assert window.effective_playback_speed() == 1000
    viewer.sim_live_speed_cap = lambda: 200
    assert window.effective_playback_speed() == 200
    window.pg_match_check.setChecked(True)
    window.playback_seq = 0
    viewer.sim_live_busy = lambda: True
    window._play_carry = 0.0
    window._playback_tick()
    assert window.playback_seq == 0 and window._play_carry == 0.0  # 계산이 끝날 때까지 기다린다
    viewer.sim_live_busy = lambda: False
    window._playback_tick()
    assert window.playback_seq == 10                                # 200줄/초 x 0.05초


@needs_qt
@needs_viewer
def test_live_checkbox_enabled_only_with_stock(window, appdata):
    path = appdata / 'p.nc'
    _write(path, SIM_PROGRAM)
    window.load_file(str(path))
    window.set_mode('viewer')
    window.viewer.current_machine_type = MILLING        # 이 PC의 저장 장비와 무관하게(저장 안 함)
    window.viewer.last_render_signature = None
    window.sync_viewer_from_source()
    assert not window.sim_live_check.isEnabled()
    window.viewer.apply_stock_spec(_spec(), 0.5, True)
    assert window.sim_live_check.isEnabled()
    window.sim_live_check.setChecked(True)
    assert window.viewer.sim_live_enabled
    assert window.layout_settings.value('sim_live_shape') in (True, 'true')
