"""v2.3.6 — 속도바 위 마우스는 3D 화면(회전·줌·십자 표시)으로 넘어가지 않고, 배속은 x50(=5000/100)으로 표기."""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

try:
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    from nc_viewer_widget import MAX_PLAYBACK_SPEED, NCViewerWidget, format_playback_speed
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    IMPORT_ERROR = exc

pytestmark = pytest.mark.skipif(IMPORT_ERROR is not None, reason='뷰어 의존성 없음')

SOURCE = 'M6T1\nG43\nG00 X0 Y0 Z0\nG01 X100 Y0 Z0\nX100 Y100 Z0\nX0 Y100 Z0\nM30\n'


@pytest.fixture
def viewer():
    qapp = QApplication.instance() or QApplication([])
    view = NCViewerWidget()
    view._keep_qapp = qapp
    view.resize(1000, 700)
    view.set_source_text(SOURCE, {'T01': 'FACE MILL'})
    view.show()
    qapp.processEvents()
    yield view
    view.deleteLater()
    qapp.processEvents()


def test_speed_text_is_value_over_100():
    assert format_playback_speed(MAX_PLAYBACK_SPEED) == 'x50'
    assert format_playback_speed(1) == 'x0.01'
    assert format_playback_speed(100) == 'x1'
    assert format_playback_speed(250) == 'x2.5'
    assert format_playback_speed(200) == 'x2'


def test_speed_label_and_cap_use_new_text(viewer):
    bar = viewer.playback_bar
    bar.set_speed(MAX_PLAYBACK_SPEED)
    assert bar.speed_value_label.text() == 'x50'
    bar.set_speed_cap(200)
    assert bar.speed_value_label.text() == 'x2'
    assert 'x50' in bar.speed_value_label.toolTip()


@pytest.mark.parametrize('pg_mode', [False, True])
def test_mouse_on_bar_does_not_reach_3d_view(viewer, pg_mode):
    viewer.set_pg_match_mode(pg_mode)
    gl_view, bar = viewer.gl_view, viewer.playback_bar
    azimuth, distance = gl_view.opts['azimuth'], gl_view.opts['distance']
    spot = QPoint(4, 4)                      # 바 여백(슬라이더·버튼 밖)
    QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, spot)
    QTest.mouseMove(bar, spot + QPoint(60, 0))
    QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, spot + QPoint(60, 0))
    QTest.mousePress(bar, Qt.MiddleButton, Qt.NoModifier, spot)
    QTest.mouseRelease(bar, Qt.MiddleButton, Qt.NoModifier, spot)
    assert gl_view._orbit_pivot is None and gl_view._middle_anchor is None
    assert not gl_view.zoom_marker.isVisible()
    assert gl_view.opts['azimuth'] == azimuth and gl_view.opts['distance'] == distance
    assert bar.testAttribute(Qt.WA_NoMousePropagation)


def test_clicking_slider_track_jumps_to_that_spot(viewer):
    viewer.set_pg_match_mode(True)
    slider = viewer.playback_bar.speed_slider
    slider.setValue(1)
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(slider.width() * 3 // 4, slider.height() // 2))
    assert 0.6 * MAX_PLAYBACK_SPEED < slider.value() < 0.9 * MAX_PLAYBACK_SPEED
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(slider.width() // 4, slider.height() // 2))
    assert 0.1 * MAX_PLAYBACK_SPEED < slider.value() < 0.4 * MAX_PLAYBACK_SPEED
    assert viewer.gl_view._orbit_pivot is None
