"""v2.6.6: 공정 시작 N 줄(이전/다음 공구 이동 목표)과 주석."""
import nc_process_marker as pm
from NC_Tool_List import pick_relative_marker

PROG = [
    "O0001",                                   # 0
    "N1 (T01 FACE MILL)",                      # 1
    "(ROUGH FACE)",                            # 2
    "T1 M6",                                   # 3
    "G0 X0. Y0.",                              # 4
    "G1 Z-1. F300",                            # 5
    "G0 Z50.",                                 # 6  앞 공정의 마지막 이동
    "M5",                                      # 7
    "G91 G28 Z0.",                             # 8
    "M01",                                     # 9
    "N2 (T05 D10 ENDMILL)",                    # 10
    "(SIDE ROUGH) (EXTRA)",                    # 11
    "G91 G28 Z0.",                             # 12
    "T5 M6",                                   # 13
    "G0 X5. Y5.",                              # 14
]


def test_marker_is_first_n_line_after_previous_motion():
    assert pm.find_process_marker(PROG, 13, floor_seq=3) == (10, ["T05 D10 ENDMILL", "SIDE ROUGH"])


def test_first_process_and_two_comments_max():
    seq, comments = pm.find_process_marker(PROG, 3, floor_seq=-1)
    assert seq == 1 and comments == ["T01 FACE MILL", "ROUGH FACE"]


def test_no_n_line_falls_back_to_tool_change_line():
    lines = ["G0 X1. Y1.", "G0 Z50.", "T7 M6 (DRILL)", "G0 X2."]
    assert pm.find_process_marker(lines, 2, floor_seq=-1) == (2, ["DRILL"])


def test_n_on_tool_change_line_itself():
    lines = ["G1 X1. Y1. F100", "N20 T3 M6 (TAP)", "G0 X2."]
    assert pm.find_process_marker(lines, 1, floor_seq=-1) == (1, ["TAP"])


def test_pick_relative_marker():
    marks = [1, 10, 30]
    assert pick_relative_marker(marks, 1, 1) == 10         # 시작 N 줄에서 다음 = 다음 공정
    assert pick_relative_marker(marks, 12, 1) == 30
    assert pick_relative_marker(marks, 40, 1) == 30        # 마지막이면 그대로
    assert pick_relative_marker(marks, 12, -1) == 10       # 공정 중간에서 이전 = 그 공정 시작
    assert pick_relative_marker(marks, 10, -1) == 1        # 시작 줄에서 이전 = 앞 공정
    assert pick_relative_marker(marks, 1, -1) == 1


def test_stock_apply_turns_on_pg_match_and_live_shape():
    import tempfile
    import NC_Tool_List as app
    if app.QT_IMPORT_ERROR is not None:
        import pytest
        pytest.skip("viewer dependencies are not available")
    from tests.test_v246_shape_button import _spec
    qapp = app.QApplication.instance() or app.QApplication([])
    with tempfile.TemporaryDirectory() as root:
        window = app.App(_root=root)
        try:
            window.set_mode('viewer')
            window.pg_match_check.setChecked(False)
            window.sim_live_check.setChecked(False)
            window.viewer.apply_stock_spec(_spec(), 0.5, True)
            qapp.processEvents()
            assert window.pg_match_check.isChecked() and window.sim_live_check.isChecked()
            assert window.viewer._sim_instant is False
        finally:
            window.deleteLater()
            qapp.processEvents()
