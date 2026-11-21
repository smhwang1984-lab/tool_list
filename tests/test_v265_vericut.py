"""v2.6.5: VERICUT(fan30im · 화천 M2/M4/D2/VESTA) 비교 — 장비 기본값, 급속 속도, G91 증분, G28/G30, 사이클 해제."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nc_modal  # noqa: E402


def _timeline(text, lathe=False):
    return nc_modal.ModalTimeline(list(enumerate(text.splitlines())), lathe=lathe)


def test_motion_code_cancels_cycle_in_modal_panel():
    tl = _timeline("G0 G90 X0 Y0\nG81 X0 Y0 Z-5. R2. F100\nX10.\nG0 X20. Y20.")
    assert tl.at(2)[0]["groups"]["09"] == "G81"
    state, changed = tl.at(3)
    assert state["groups"]["09"] == "G80" and "09" in changed
    assert nc_modal.summary_text(state, False) == "F100 · G00"


def test_cycle_code_with_motion_on_same_line_stays_cycle():
    tl = _timeline("G0 X0 Y0\nG0 G81 X0 Y0 Z-5. R2. F100")
    assert tl.at(1)[0]["groups"]["09"] == "G81"


def test_reference_return_cancels_length_offset_in_modal_panel():
    tl = _timeline("G43 Z50. H2\nG0 X0\nG28 G91 Z0.\nG43 Z50. H3\nG30 G91 X0.")
    assert tl.at(1)[0]["groups"]["08"] == "G43 H02"
    assert tl.at(2)[0]["groups"]["08"] == "G49"
    assert tl.at(3)[0]["groups"]["08"] == "G43 H03"
    assert tl.at(4)[0]["groups"]["08"] == "G49"


def test_lathe_motion_cancels_drill_cycle_and_g28_keeps_groups():
    tl = _timeline("G83 Z-10. F0.1\nG0 X50.\nG28 U0.", lathe=True)
    assert tl.at(1)[0]["groups"]["10"] == "G80"
    assert "08" not in tl.at(2)[0]["groups"]


# ---------------------------------------------------------------- 뷰어
try:
    from PyQt5.QtWidgets import QApplication
    import nc_viewer_widget as nvw
    HAVE_QT = True
except Exception:  # pragma: no cover
    HAVE_QT = False


def test_add_incremental_word():
    if not HAVE_QT:
        pytest.skip("Qt viewer not available")
    assert nvw.add_incremental_word("-90", "-5.") == "-95"
    assert nvw.add_incremental_word("0.000", "-5.0") == "-5"
    assert nvw.add_incremental_word("10", "-10.") == "0"
    assert nvw.add_incremental_word("1.5", "0.25") == "1.75"


def test_machine_rapid_feed_and_effective_feed():
    if not HAVE_QT:
        pytest.skip("Qt viewer not available")
    assert nvw.machine_rapid_feed({nvw.SPEC_RAPID: "30000"}) == 30000.0
    assert nvw.machine_rapid_feed({nvw.SPEC_RAPID: "30,000"}) == 30000.0
    assert nvw.machine_rapid_feed({}) == nvw.RAPID_FEED_MM_PER_MIN
    assert nvw.machine_rapid_feed({nvw.SPEC_RAPID: "abc"}) == nvw.RAPID_FEED_MM_PER_MIN
    assert nvw.machine_rapid_feed({nvw.SPEC_RAPID: "0"}) == nvw.RAPID_FEED_MM_PER_MIN
    assert nvw.effective_feed_mm_per_min("G00", 100, 10, 30000.0) == 30000.0
    assert nvw.effective_feed_mm_per_min("G00", 100, 10) == nvw.RAPID_FEED_MM_PER_MIN


def test_real_machines_in_defaults_keep_machine_kind():
    if not HAVE_QT:
        pytest.skip("Qt viewer not available")
    specs = nvw.DEFAULT_MACHINE_SPECS
    m2 = specs["5축 MCT (A to C) 화천 M2"]
    assert (m2["X 행정"], m2["Y 행정"], m2["Z 행정"], m2["A축 범위"]) == ("750", "650", "500", "-120~+30")
    assert specs["5축 MCT (A to C) 화천 M4"]["A축 범위"] == "-120~+120"
    d2 = specs["5축 MCT (B to C) 화천 D2"]
    assert d2["B축 범위"] == "-30~+110" and d2[nvw.SPEC_RAPID] == "24000"
    assert nvw.MACHINE_5AXIS_AC in "5축 MCT (A to C) 화천 M2"
    assert nvw.MACHINE_5AXIS_BC in "5축 MCT (B to C) 화천 D2"
    vesta = "3축 MCT 화천 VESTA-2000"
    assert vesta in specs and "4축" not in vesta and not nvw.is_lathe_machine(vesta)
    assert all(nvw.SPEC_RAPID in spec for spec in specs.values())


@pytest.fixture
def viewer():
    if not HAVE_QT:
        pytest.skip("Qt viewer not available")
    app = QApplication.instance() or QApplication([])
    widget = nvw.NCViewerWidget()
    yield widget
    widget.deleteLater()
    app.processEvents()


def test_saved_specs_get_new_keys_from_defaults(viewer):
    viewer.settings.setValue("machine_specs", '{"3축 MCT (X Y Z)": {"X 행정": "1234"}}')
    specs = viewer._load_machine_specs()
    assert specs["3축 MCT (X Y Z)"]["X 행정"] == "1234"
    assert specs["3축 MCT (X Y Z)"][nvw.SPEC_RAPID] == "24000"
    assert "5축 MCT (B to C) 화천 D2" in specs


def _run(viewer, machine, text):
    viewer.set_machine_type(machine)
    lines = text.splitlines()
    viewer.process_nc_lines(lines)
    return lines


def test_g91_rotary_increment_and_reference_return_display(viewer):
    _run(viewer, nvw.MACHINE_5AXIS_AC, "G0 G90 A-90. C-90.\nG91 G0 C-5.\nG28 G91 Y0. A0. C0.\nG30 G91 X0.\nG90 G0 X1.")
    state = viewer.modal_state_map
    assert state[1][3:] == ("-90", "0.000", "-95")
    assert state[2][3:] == ("0", "0.000", "0")
    assert state[4][0] == "1"                     # G90으로 돌아오면 절대값


def test_g91_linear_moves_are_incremental(viewer):
    _run(viewer, "3축 MCT (X Y Z)", "G43 Z50. H1\nG0 G90 X0. Y0.\nG91 X10.\nX10. Y5.\nG90 X0.")
    coords = viewer.line_to_coord_map
    assert coords[2][:2] == [10.0, 0.0]
    assert coords[3][:2] == [20.0, 5.0]
    assert coords[4][:2] == [0.0, 5.0]


def test_g30_goes_home_like_g28(viewer):
    _run(viewer, "3축 MCT (X Y Z)", "G43 Z50. H1\nG0 G90 X10. Y10.\nG30 G91 X0.")
    assert viewer.line_to_coord_map[2][0] == pytest.approx(500.0)   # X 행정 1000의 반(G28과 같은 원점)


def test_motion_code_cancels_mill_cycle_path(viewer):
    _run(viewer, "3축 MCT (X Y Z)",
         "G43 Z50. H1\nG0 G90 X0. Y0.\nG81 X0. Y0. Z-5. R2. F100\nX10.\nG0 X20. Y20.")
    points = [p for pts in viewer.tool_paths.values() for p in pts if p["src_line"] == 4]
    assert len(points) == 1 and points[0]["type"] == "G00"      # 사이클 4점 전개가 아니라 급속 한 번
    assert points[0]["pt"] == [20.0, 20.0, 50.0]                # 사이클이 G98 초기점(Z50)으로 복귀한 높이 그대로


def test_machine_display_names_and_units():
    import NC_Tool_List as ntl
    assert ntl.machine_display_name(nvw.MACHINE_5AXIS_BC + " 화천 D2") == "화천 D2 · 5축 B→C"
    assert ntl.machine_display_name(nvw.MACHINE_5AXIS_AC + " 화천 M4") == "화천 M4 · 5축 A→C"
    assert ntl.machine_display_name("3축 MCT 화천 VESTA-2000") == "화천 VESTA-2000 · 3축"
    assert ntl.machine_display_name(nvw.MACHINE_5AXIS_AC) == nvw.MACHINE_5AXIS_AC
    assert [ntl.machine_spec_unit(k) for k in ("X 행정", "C축 범위", "최대 RPM", nvw.SPEC_RAPID, "기타")] == \
        ["mm", "°", "rpm", "mm/min", ""]


def test_rotary_speed_default_and_clamp():
    assert nvw.ROTARY_SPEED_DEFAULT == 30                           # v2.6.7: 기본 30°/초
    assert [nvw.clamp_rotary_speed(v) for v in (0, 32, 999, "x")] == [5, 30, 180, 30]


def test_g0_index_rotation_stops_playback_and_waits(viewer):
    _run(viewer, nvw.MACHINE_5AXIS_AC,
         "G43.4 H1\nG0 G90 A0. C0.\nG0 A-30. C90.\nG1 X10. F500\nG1 X20. A-20. C100. F500")
    viewer.set_pg_match_mode(True)
    idx = viewer.line_to_seq[2]
    assert viewer.table_rotation_changes_at(idx) is True            # G0 인덱스 줄은 재생이 한 번 멈춘다
    assert viewer.table_rotation_changes_at(viewer.line_to_seq[3]) is False
    assert viewer.table_rotation_changes_at(viewer.line_to_seq[4]) is False   # G43.4 동시 5축은 재생을 따른다
    viewer.table_anim_speed = 100
    viewer.set_cursor_seq(idx)
    assert viewer.table_anim_active()                               # 도는 동안 재생은 다음 줄로 가지 않는다
    viewer.table_anim_finish()
    assert not viewer.table_anim_active() and viewer._table_disp == viewer._table_goal


def test_simultaneous_5axis_moves_follow_playback(viewer):
    _run(viewer, nvw.MACHINE_5AXIS_AC,
         "G0 G90 A0. C0.\nG0 A-30. C90.\nG43.4 H1\nG1 X10. A-20. C100. F500\nG1 X20.\nG49\nG1 A-10.")
    follow = {viewer.seq_to_line[s] for s in viewer.seq_table_follow}
    assert follow == {3}          # G43.4 중 회전축이 든 절삭 이동만(인덱스 G0, 직선만, G49 뒤는 제외)


def test_first_rotation_starts_from_origin_at_same_speed(viewer):
    _run(viewer, nvw.MACHINE_5AXIS_AC,
         "G0 G90 X0. Y0.\nG43.4 H1\nG0 A-30. C90.\nG1 X10. F500")
    viewer.set_pg_match_mode(True)
    idx = viewer.line_to_seq[2]                      # 처음 나타나는 회전(원점 A0 C0에서 출발)
    assert viewer.table_rotation_changes_at(idx) is True      # 재생은 여기서 한 번 멈춘다
    viewer.table_anim_speed = 100
    viewer.set_cursor_seq(viewer.line_to_seq[1])     # 회전이 아직 없는 줄
    viewer.set_cursor_seq(idx)
    assert viewer.table_anim_active()                # 바로 튀지 않고 같은 속도로 돈다
    assert viewer._table_anim_start[1:] == (0.0, 0.0, 0.0)
    biggest = max(abs(d) for d in viewer._table_anim_delta)
    assert abs(viewer._table_anim_duration - biggest / viewer.rotary_speed) < 1e-6
    viewer.table_anim_finish()
