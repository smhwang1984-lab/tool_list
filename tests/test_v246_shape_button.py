import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import nc_sim
from tests.test_v233_live_reload import viewer, needs_viewer, _spec  # noqa: F401


@needs_viewer
def test_shape_button_next_to_projection_and_green_when_on(viewer):
    ov = viewer.projection_overlay
    assert ov.shape_button.text() == '가공형상즉시보기'
    row = ov._row
    last = row.itemAt(row.count() - 1).widget()
    assert last is ov.shape_button                      # 투영 버튼들 맨 끝(옆)
    assert 'shapeButton:checked' in ov.styleSheet() and '#2ea043' in ov.styleSheet()
    # 렌더 후 투영 버튼을 갈아 끼워도 버튼은 남는다
    ov.set_lathe_mode(True)
    ov.set_lathe_mode(False)
    assert ov.shape_button.parent() is ov and row.indexOf(ov.shape_button) == row.count() - 1


@needs_viewer
def test_shape_button_toggles_simulation_and_syncs(viewer):
    ov = viewer.projection_overlay
    viewer.apply_stock_spec(_spec(), 0.5, False)           # 소재는 있고 시뮬레이션은 꺼진 상태
    assert not viewer.sim_enabled and not ov.shape_button.isChecked()
    ov.shape_button.setChecked(True)
    assert viewer.sim_enabled
    ov.shape_button.setChecked(False)
    assert not viewer.sim_enabled
    viewer.set_sim_enabled(True)
    assert ov.shape_button.isChecked()                      # 다른 경로로 켜져도 버튼이 따라간다


@needs_viewer
def test_clear_stock(viewer):
    viewer._sim_sync = True
    viewer.apply_stock_spec(_spec(), 0.5, True)
    assert viewer.sim_enabled and viewer.sim_stock is not None
    viewer.clear_stock()
    assert viewer.sim_stock is None and not viewer.sim_enabled
    assert viewer.sim_mesh_item is None
    assert not viewer.projection_overlay.shape_button.isChecked()


@needs_viewer
def test_center_progress_percent_font_equals_cube_size(viewer):
    viewer._sim_set_progress('형상 계산 중… 42%')
    label = viewer.sim_progress_label
    assert label.text() == '42%' and not label.isHidden()
    assert 'font-size: %dpx' % viewer._axis_cube_size_px() in label.styleSheet()
    assert viewer.gl_view.center_widget is label
    cx = label.x() + label.width() / 2
    assert abs(cx - viewer.gl_view.width() / 2) <= 2
    viewer._sim_set_progress('')
    assert label.isHidden()


@needs_viewer
def test_stock_dialog_apply_asks_then_switches_to_simulation(viewer, monkeypatch):
    from nc_viewer_widget import StockDialog
    viewer._sim_sync = True
    dialog = StockDialog(viewer)
    assert dialog.enable_check.isHidden()                   # 화면에는 체크가 없다
    asked = []
    monkeypatch.setattr(StockDialog, '_ask_run_simulation', lambda self: asked.append(1) or True)
    dialog.refresh_from_viewer()
    dialog._apply()
    assert asked == [1] and viewer.sim_enabled              # 확인 뒤 가공 시뮬레이션으로 전환
    dialog._apply()
    assert asked == [1]                                     # 이미 켜져 있으면 다시 묻지 않는다
    viewer.set_sim_enabled(False)
    dialog.refresh_from_viewer()
    monkeypatch.setattr(StockDialog, '_ask_run_simulation', lambda self: False)
    dialog._apply()
    assert viewer.sim_stock is not None and not viewer.sim_enabled   # 아니오: 소재만 적용
