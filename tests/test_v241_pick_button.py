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
    viewer.set_camera_projection('XY')          # 뷰를 바꾸면 위치 찍기는 끝난다
    assert not viewer.pick_mode
    assert not overlay.pick_button.isChecked()


def test_speed_slider_enabled_without_pg_match():
    QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    bar = viewer.playback_bar
    assert bar.speed_slider.isEnabled()
    assert not bar.play_pause_button.isEnabled()
    viewer.set_pg_match_mode(True)
    assert bar.play_pause_button.isEnabled()
