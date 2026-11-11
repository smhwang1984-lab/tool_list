import numpy as np

import nc_tool_marker as tm


def _path(points, types):
    nodes = []
    for i, (pt, t) in enumerate(zip(points, types)):
        nodes.append({'valid': True, 'pt': pt, 'type': t, 'src_line': i, 'seq': i})
    return nodes


def test_group_starts_at_first_cut_after_approach():
    path = _path([(0, 0, 50), (10, 0, 5), (10, 0, -2), (30, 0, -2)], ['G00', 'G00', 'G01', 'G01'])
    g = tm.cut_groups(path)
    assert len(g) == 1
    assert list(g[0]['entry']) == [10, 0, 5] and np.allclose(g[0]['direction'], [0, 0, -1])
    assert g[0]['start_seq'] == 2 and g[0]['end_seq'] is None


def test_axis_rotation_ends_group_and_new_entry():
    # 라인 0~2: +Z 축 가공, 라인 3~5: 축 회전(+X) 뒤 새 축 가공
    pts = [(0, 0, 5), (10, 0, 5), (20, 0, 5), (20, 0, 5), (0, 0, 0), (0, 10, 0)]
    types = ['G00', 'G01', 'G01', 'G00', 'G00', 'G01']
    path = _path(pts, types)
    axes = {3: (1.0, 0, 0), 4: (1.0, 0, 0), 5: (1.0, 0, 0)}
    g = tm.cut_groups(path, axes)
    assert len(g) == 2
    assert g[0]['end_seq'] == 3 and g[1]['start_seq'] == 5
    assert np.allclose(g[1]['direction'], [0, 1, 0])
    assert tm.group_at(g, 1) is g[0] and tm.group_at(g, 2) is g[0]
    assert tm.group_at(g, 3) is None and tm.group_at(g, 4) is None   # 회전 후 새 절삭 전엔 지움
    assert tm.group_at(g, 5) is g[1]
    assert tm.group_at(g, 0) is None                                  # 진입 전엔 없음


def test_marker_ball_mesh_at_origin_and_placement():
    path = _path([(0, 0, 50), (10, 0, 5), (30, 0, 5)], ['G00', 'G00', 'G01'])
    data = tm.marker_for_process(path, {'type': 'BALL', 'D': 10, 'FL': 20})
    v = data['verts']
    assert np.allclose(v[0], [0, 0, 0], atol=1e-4)       # 원점 팁, +Z 몸통
    assert v[:, 2].max() >= 20 - 1e-4
    assert np.allclose(data['groups'][0]['entry'], [10, 0, 5])
    assert np.allclose(data['groups'][0]['direction'], [1, 0, 0])
    m = np.array(tm.placement_matrix((10, 0, 5), (1.0, 0.0, 0.0))).reshape(4, 4)
    moved = (m[:3, :3] @ v[-1].astype(float)) + m[:3, 3]   # 몸통 윗면 중심이 +X로 뻗는다
    assert moved[0] > 25 and abs(moved[2] - 5) < 1e-3


def test_entry_arrow_length():
    arrow = tm.build_entry_arrow((0, 0, 0), (1, 0, 0), 12.0)
    assert np.allclose(arrow[1], [12, 0, 0]) and len(arrow) % 2 == 0


def test_marker_none_without_tool_or_cut():
    path = _path([(0, 0, 50), (10, 0, 5)], ['G00', 'G00'])
    assert tm.marker_for_process(path, {'type': 'FLAT', 'D': 10}) is None
    cut = _path([(0, 0, 5), (10, 0, 5)], ['G00', 'G01'])
    assert tm.marker_for_process(cut, None) is None
    assert tm.marker_for_process(cut, {'type': 'FLAT'}) is None


def test_drill_tip_is_cone():
    path = _path([(0, 0, 5), (0, 0, -5)], ['G00', 'G01'])
    data = tm.marker_for_process(path, {'type': 'DRILL', 'D': 8, 'FL': 30})
    v = data['verts']
    assert abs(v[:, 2].min()) < 1e-4  # 팁이 원점
    assert np.allclose(data['groups'][0]['direction'], [0, 0, -1])


# ---------------------------------------------------------------- 뷰어 연동
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_v233_live_reload import viewer, needs_viewer  # noqa: E402,F401


@needs_viewer
def test_markers_only_in_pg_match_playback(viewer):
    from tests.test_v233_live_reload import SHAPES, SIM_PROGRAM, NAMES
    shapes = dict(SHAPES, T01=SHAPES['T1'], T02=SHAPES['T2'])
    viewer.set_source_text(SIM_PROGRAM + ' ', NAMES, shapes)
    keys = list(viewer.plot_items)
    assert set(viewer.tool_marker_items) == set(keys) and len(keys) == 2
    # 단순 툴패스 보기: 공구 모양은 보이지 않는다
    viewer.set_pg_match_mode(False)
    viewer.set_cursor_seq(5)
    assert not any(i.visible() for items in viewer.tool_marker_items.values() for i in items)
    # PG 매칭 재생: 현재 공정의 공구 모양 + 진입 화살표
    viewer.set_pg_match_mode(True)
    viewer.set_cursor_seq(5)
    cur = viewer.seq_to_tool_map[5]
    assert all(i.visible() for i in viewer.tool_marker_items[cur])
    other = [k for k in keys if k != cur][0]
    assert not any(i.visible() for i in viewer.tool_marker_items[other])
    # 화살표 길이 = 원점 표기 길이의 50%
    arrow = viewer.tool_marker_items[cur][1]
    pos = np.asarray(arrow.pos)
    length = float(np.linalg.norm(pos[1] - pos[0]))
    assert abs(length - viewer._axis_arrow_length() * 0.5) < 1e-3
    viewer.set_pg_match_mode(False)
    assert not any(i.visible() for items in viewer.tool_marker_items.values() for i in items)
    viewer.set_source_text('M30')
    assert viewer.tool_marker_items == {}


@needs_viewer
def test_all_projection_buttons_original_size(viewer):
    ov = viewer.projection_overlay
    assert ov.pick_button.iconSize().width() == 14
    for button in ov._view_buttons.values():
        assert button.iconSize().width() == 14
    assert abs(ov.pick_button.sizeHint().height() - next(iter(ov._view_buttons.values())).sizeHint().height()) <= 4
