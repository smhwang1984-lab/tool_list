# -*- coding: utf-8 -*-
"""v2.4.1: 투영 오버레이 [위치] 버튼 = 위치 찍기 모드 토글, 속도 슬라이더는 PG 매칭 없이도 활성."""
import pytest

pytest.importorskip('PyQt5')
from PyQt5.QtWidgets import QApplication  # noqa: E402

import nc_viewer_widget as nv  # noqa: E402


def test_pick_button_toggles_pick_mode_and_stays_in_sync():
    QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    overlay = viewer.projection_overlay
    assert overlay.button_labels()[0] == 'ISO'
    assert overlay._row.itemAt(0).widget() is overlay.pick_button
    overlay.pick_button.setChecked(True)
    assert viewer.pick_mode
    viewer.set_camera_projection('XY')          # v2.4.2: 뷰를 바꿔도 위치 찍기는 유지
    assert viewer.pick_mode and overlay.pick_button.isChecked()
    viewer.set_pick_mode(False)
    assert not overlay.pick_button.isChecked()


def test_speed_slider_enabled_without_pg_match():
    QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    bar = viewer.playback_bar
    assert bar.speed_button.isEnabled()
    assert not bar.play_pause_button.isEnabled()
    viewer.set_pg_match_mode(True)
    assert bar.play_pause_button.isEnabled()


def test_projection_buttons_blue_when_active_and_cleared_on_render_keeping_pick():
    QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    overlay = viewer.projection_overlay
    overlay._view_buttons['XY'].click()
    assert overlay._view_buttons['XY'].isChecked() and not overlay._view_buttons['ISO'].isChecked()
    overlay.pick_button.setChecked(True)
    viewer.set_camera_projection('XZ')             # 뷰를 바꿔도 위치 찍기는 유지
    assert viewer.pick_mode
    viewer.set_source_text("G0 X10 Y10\nG1 X20 F100\nM30\n")
    assert not any(b.isChecked() for b in overlay._view_buttons.values())
    assert viewer.pick_mode and overlay.pick_button.isChecked()
    assert overlay.pick_button.text() == '위치 찍기'
