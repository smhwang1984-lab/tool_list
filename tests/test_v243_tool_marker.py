import numpy as np

import nc_tool_marker as tm


def _path(points, types):
    nodes = []
    for i, (pt, t) in enumerate(zip(points, types)):
        nodes.append({'valid': True, 'pt': pt, 'type': t, 'src_line': i, 'seq': i})
    return nodes


def test_entry_point_and_direction():
    path = _path([(0, 0, 50), (10, 0, 5), (10, 0, -2), (30, 0, -2)], ['G00', 'G00', 'G01', 'G01'])
    p0, delta, src = tm.first_cut_entry(path)
    assert list(p0) == [10, 0, 5] and list(delta) == [0, 0, -7] and src == 1


def test_marker_ball_tool_tip_at_entry_and_axis():
    path = _path([(0, 0, 50), (10, 0, 5), (30, 0, 5)], ['G00', 'G00', 'G01'])
    data = tm.marker_for_process(path, {'type': 'BALL', 'D': 10, 'FL': 20}, {1: (1.0, 0.0, 0.0)})
    v = data['verts']
    # 공구 축이 +X로 기울어 있으면 팁이 진입점이고 몸통이 +X로 뻗는다
    assert np.allclose(v[0], [10, 0, 5], atol=1e-4)
    assert v[:, 0].max() > 25
    assert np.allclose(data['direction'], [1, 0, 0])
    assert data['arrow'].shape[1] == 3 and len(data['arrow']) % 2 == 0
    assert np.allclose(data['arrow'][0], [10, 0, 5])


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
    assert abs(v[:, 2].min() - 5) < 1e-4  # 팁이 진입점 높이
    assert np.allclose(data['direction'], [0, 0, -1])


# ---------------------------------------------------------------- 뷰어 연동
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_v233_live_reload import viewer, needs_viewer  # noqa: E402,F401


@needs_viewer
def test_viewer_builds_marker_per_process_and_follows_filter(viewer):
    from tests.test_v233_live_reload import SHAPES, SIM_PROGRAM, NAMES
    shapes = dict(SHAPES, T01=SHAPES['T1'], T02=SHAPES['T2'])   # 앱은 T01/T1/1 키를 모두 준다
    viewer.set_source_text(SIM_PROGRAM + ' ', NAMES, shapes)
    keys = list(viewer.plot_items)
    assert set(viewer.tool_marker_items) == set(keys) and len(keys) == 2
    viewer.set_selected_tools({keys[0]})
    assert all(i.visible() for i in viewer.tool_marker_items[keys[0]])
    assert not any(i.visible() for i in viewer.tool_marker_items[keys[1]])
    viewer.set_source_text('M30\n')
    assert viewer.tool_marker_items == {}


@needs_viewer
def test_projection_buttons_back_to_original_size(viewer):
    ov = viewer.projection_overlay
    assert ov.pick_button.iconSize().width() == 35
    for button in ov._view_buttons.values():
        assert button.iconSize().width() == 14
        assert button.sizeHint().height() < ov.pick_button.sizeHint().height()
