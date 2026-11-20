"""v2.6.4: 재생 바 [모달 정보] — 주축 · 이송 · G코드 그룹 · M코드 묶음, 이전/다음 공구 버튼."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nc_modal  # noqa: E402

MILL = """%
O1000
N1 (FACE)
T2 M6
G0 G90 G54 X-20. Y0. S10000 M3
G43.4 Z50. H2 M8
G68.2 X0 Y0 Z0 I0 J-90 K0
G53.1
G1 Z-1. F3600
X20.
G69
M1
N2
T3 M6
G0 G90 G54 X0. Y0. S3800 M3
G43 Z50. H3 M8
G83 G98 Z-12. R2. Q2. F152
X15.
G80
M30
%"""


def _timeline(text, lathe=False):
    return nc_modal.ModalTimeline(list(enumerate(text.splitlines())), lathe=lathe)


def test_mill_groups_follow_last_command():
    tl = _timeline(MILL)
    state, changed = tl.at(8)                      # G1 Z-1. F3600
    assert state["S"] == "10000" and state["F"] == "3600"
    assert state["m"]["spindle"] == "M03" and state["m"]["coolant"] == "M08"
    g = state["groups"]
    assert g["01"] == "G01" and g["03"] == "G90" and g["14"] == "G54"
    assert g["08"] == "G43.4 H02" and g["16"] == "G68.2"
    assert changed == {"01", "F"}
    assert nc_modal.summary_text(state, False) == "S10000 M03 · F3600 · G01 G68.2"
    assert nc_modal.feed_unit(state, False) == "mm/min"


def test_unchanged_line_keeps_state_and_reports_no_change():
    tl = _timeline(MILL)
    state, changed = tl.at(9)                      # X20. — 모달 그대로
    assert state["groups"]["01"] == "G01" and changed == frozenset()


def test_cycle_and_cancel_and_stop_codes():
    tl = _timeline(MILL)
    state, _ = tl.at(16)                           # G83 G98 ...
    assert state["groups"]["09"] == "G83" and state["groups"]["10"] == "G98"
    assert state["groups"]["16"] == "G69"          # G69로 해제됨
    assert state["groups"]["08"] == "G43 H03"
    assert state["m"]["stop"] == "M01"
    assert nc_modal.summary_text(state, False) == "S3800 M03 · F152 · G00 G83"
    state, _ = tl.at(18)                           # G80
    assert state["groups"]["09"] == "G80"
    assert nc_modal.summary_text(state, False) == "S3800 M03 · F152 · G00"


def test_before_any_command_is_empty():
    tl = _timeline(MILL)
    state, changed = tl.at(0)
    assert state["S"] is None and state["groups"] == {} and changed == frozenset()
    assert nc_modal.summary_text(state, False) == "지령 전"


def test_comments_and_m98_are_ignored():
    tl = _timeline("G0 (G1 S500 M8) X1.\nM98 P1000\nG1 X2. F100 ; M9")
    state, _ = tl.at(2)
    assert state["groups"]["01"] == "G01" and state["S"] is None
    assert "coolant" not in state["m"] and "other" not in state["m"]


def test_lathe_g50_s_is_max_rpm_not_spindle_and_feed_is_per_rev():
    tl = _timeline("G50 S3000\nG96 S180 M3\nG99 G1 X10. F0.15", lathe=True)
    state, _ = tl.at(2)
    assert state["S"] == "180" and state["groups"]["02"] == "G96"
    assert state["F"] == "0.15" and nc_modal.feed_unit(state, True) == "mm/rev"


def test_lathe_g71_is_one_shot_and_block_delete_runs():
    tl = _timeline("\n".join(["G0 X50. Z2.", "G71 U1. R0.5", "G83 Z-10. F0.1", "/M8"]), lathe=True)
    assert "10" not in tl.at(1)[0]["groups"]
    assert tl.at(2)[0]["groups"]["10"] == "G83"
    assert tl.at(3)[0]["m"]["coolant"] == "M08"


def test_normalize_code():
    assert nc_modal.normalize_code("G", "1") == "G01"
    assert nc_modal.normalize_code("G", "43.4") == "G43.4"
    assert nc_modal.normalize_code("G", "68.20") == "G68.2"
    assert nc_modal.normalize_code("M", "3") == "M03"


# ---------------------------------------------------------------- UI
try:
    from PyQt5.QtWidgets import QApplication
    import nc_viewer_widget  # noqa: F401
    HAVE_QT = True
except Exception:  # pragma: no cover
    HAVE_QT = False


@pytest.fixture
def viewer():
    if not HAVE_QT:
        pytest.skip("Qt viewer not available")
    app = QApplication.instance() or QApplication([])
    from nc_viewer_widget import NCViewerWidget
    widget = NCViewerWidget()
    yield widget
    widget.deleteLater()
    app.processEvents()


def test_bar_has_labeled_tool_buttons_and_collapsed_modal(viewer):
    bar = viewer.playback_bar
    assert bar.prev_tool_button.text() == "이전 공구" and bar.next_tool_button.text() == "다음 공구"
    bar.set_modal_expanded(False)
    assert not bar.modal_toggle.isChecked() and bar.modal_panel.isHidden()
    assert viewer.coord_overlay.parent() is bar


def test_cursor_updates_modal_panel(viewer):
    viewer.set_machine_type("밀링 3축") if hasattr(viewer, "set_machine_type") else None
    viewer.process_nc_lines(MILL.splitlines())
    bar = viewer.playback_bar
    bar.set_modal_expanded(True)
    try:
        viewer.set_cursor_seq(8)
        assert bar.modal_peek.text() == "S10000 M03 · F3600 · G01 G68.2"
        assert bar._group_cells["16"].text() == "G68.2"
        assert bar._kv_values["F"].text() == "F3600"
        assert bar.tool_label.text().startswith("T02")
    finally:
        bar.set_modal_expanded(False)
