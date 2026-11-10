"""v2.3.4 — 휠 줌 중심 표시, 휠 누르고 끌기 줌, 좌드래그 회전·Ctrl 이동 회귀.

우클릭 드래그 줌·위치 찍기 모드는 tests/test_nc_tool_list.py(돋보기 테스트를 바꾼 것)에 있다."""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

try:
    from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QVector3D, QWheelEvent
    from PyQt5.QtWidgets import QApplication
    import nc_viewer_widget
    from nc_viewer_widget import NCViewerWidget
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    IMPORT_ERROR = exc

pytestmark = pytest.mark.skipif(IMPORT_ERROR is not None, reason='뷰어 의존성 없음')

SOURCE = 'M6T1\nG0 X0 Y0 Z10\nG1 X100 Y0 Z0 F500\nG1 X100 Y100\nG1 X0 Y100\nM30\n'


@pytest.fixture
def viewer():
    qapp = QApplication.instance() or QApplication([])
    view = NCViewerWidget()
    view._keep_qapp = qapp
    view.resize(800, 600)
    view.set_source_text(SOURCE, {'T1': 'D10 F.EM'})
    view.set_camera_projection('XY')
    view.show()
    qapp.processEvents()
    yield view
    view.deleteLater()
    qapp.processEvents()


def mouse(widget, kind, pos, button, buttons, modifiers=None):
    types = {'press': QEvent.MouseButtonPress, 'move': QEvent.MouseMove,
             'release': QEvent.MouseButtonRelease}
    event = QMouseEvent(types[kind], QPointF(pos), button, buttons,
                        Qt.NoModifier if modifiers is None else modifiers)
    QApplication.sendEvent(widget, event)


def wheel(widget, pos, delta):
    event = QWheelEvent(QPointF(pos), QPointF(widget.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, delta),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def project(gl_view, world):
    viewport = gl_view.getViewport()
    vec = (gl_view.projectionMatrix(viewport, viewport) * gl_view.viewMatrix()).map(QVector3D(*world))
    return ((vec.x() + 1.0) / 2.0 * viewport[2], (1.0 - vec.y()) / 2.0 * viewport[3])


def marker_center(gl_view):
    geo = gl_view.zoom_marker.geometry()
    return geo.center().x(), geo.center().y()


# ---------------------------------------------------------------- 휠 줌 중심 표시
def test_wheel_zoom_shows_center_marker_then_hides(viewer):
    gl_view = viewer.gl_view
    distance = gl_view.opts['distance']
    wheel(gl_view, QPoint(250, 180), 120)
    assert gl_view.opts['distance'] < distance
    assert gl_view.zoom_marker.isVisible()
    cx, cy = marker_center(gl_view)
    assert abs(cx - 250) <= 1 and abs(cy - 180) <= 1
    assert gl_view._zoom_marker_timer.isActive()
    assert gl_view._zoom_marker_timer.interval() == nc_viewer_widget.ZOOM_MARKER_HIDE_MS
    gl_view._zoom_marker_timer.timeout.emit()
    assert not gl_view.zoom_marker.isVisible()


def test_marker_does_not_take_mouse_events(viewer):
    assert viewer.gl_view.zoom_marker.testAttribute(Qt.WA_TransparentForMouseEvents)


# ---------------------------------------------------------------- 휠 누르고 끌기 = 이동(v2.3.7)
def test_middle_drag_pans_without_zoom(viewer):
    gl_view = viewer.gl_view
    center = QPoint(gl_view.width() // 2, gl_view.height() // 2)
    before = QVector3D(gl_view.opts['center'])
    distance = gl_view.opts['distance']
    mid = Qt.MiddleButton
    mouse(gl_view, 'press', center, mid, mid)
    mouse(gl_view, 'move', center + QPoint(80, -50), Qt.NoButton, mid)
    mouse(gl_view, 'release', center + QPoint(80, -50), mid, Qt.NoButton)
    assert gl_view.opts['distance'] == pytest.approx(distance)
    assert (QVector3D(gl_view.opts['center']) - before).length() > 1e-3
    assert gl_view._middle_anchor is None


# ---------------------------------------------------------------- 회귀
def test_left_drag_still_orbits_and_ctrl_left_drag_pans(viewer):
    gl_view = viewer.gl_view
    left = Qt.LeftButton
    azimuth = gl_view.opts['azimuth']
    mouse(gl_view, 'press', QPoint(300, 300), left, left)
    mouse(gl_view, 'move', QPoint(360, 300), Qt.NoButton, left)
    mouse(gl_view, 'release', QPoint(360, 300), left, Qt.NoButton)
    assert gl_view.opts['azimuth'] != azimuth
    assert not viewer.pick_mode

    before = QVector3D(gl_view.opts['center'])
    mouse(gl_view, 'press', QPoint(300, 300), left, left, Qt.ControlModifier)
    mouse(gl_view, 'move', QPoint(360, 330), Qt.NoButton, left, Qt.ControlModifier)
    mouse(gl_view, 'release', QPoint(360, 330), left, Qt.NoButton, Qt.ControlModifier)
    assert (QVector3D(gl_view.opts['center']) - before).length() > 1e-6


def test_lathe_drag_zoom_button_still_works_and_does_not_start_pick_mode(viewer):
    gl_view = viewer.gl_view
    gl_view.set_drag_zoom_active(True)
    distance = gl_view.opts['distance']
    left = Qt.LeftButton
    mouse(gl_view, 'press', QPoint(100, 100), left, left)
    mouse(gl_view, 'move', QPoint(300, 250), Qt.NoButton, left)
    mouse(gl_view, 'release', QPoint(300, 250), left, Qt.NoButton)
    assert gl_view.opts['distance'] < distance
    assert not gl_view.drag_zoom_active
    assert not viewer.pick_mode


# ---------------------------------------------------------------- 줌 기준점 정확도(v2.3.4 수정)
@pytest.mark.parametrize('view', ['XY', 'ISO'])
@pytest.mark.parametrize('world', [(100.0, 0.0, 0.0), (0.0, 100.0, 0.0), (-50.0, 80.0, 10.0)])
def test_wheel_zoom_keeps_point_under_cursor(viewer, view, world):
    """pyqtgraph pan()은 화면 폭 기준 픽셀 크기를 쓰는데 직교 투영은 높이 기준이라, v2.3.3까지는
    휠 줌 때 커서 아래 지점이 바깥으로 밀렸다(800x600에서 약 17px)."""
    gl_view = viewer.gl_view
    viewer.set_camera_projection(view)
    sx, sy = project(gl_view, world)
    wheel(gl_view, QPoint(int(round(sx)), int(round(sy))), 360)
    px, py = project(gl_view, world)
    assert abs(px - round(sx)) < 1.0 and abs(py - round(sy)) < 1.0


def test_right_drag_rectangle_center_comes_to_screen_center(viewer):
    gl_view = viewer.gl_view
    world = (100.0, 100.0, 0.0)
    sx, sy = project(gl_view, world)
    right = Qt.RightButton
    start = QPoint(int(round(sx)) - 60, int(round(sy)) - 40)
    end = QPoint(int(round(sx)) + 60, int(round(sy)) + 40)
    mouse(gl_view, 'press', start, right, right)
    mouse(gl_view, 'move', end, Qt.NoButton, right)
    mouse(gl_view, 'release', end, right, Qt.NoButton)
    px, py = project(gl_view, world)
    assert abs(px - gl_view.width() / 2.0) < 1.5 and abs(py - gl_view.height() / 2.0) < 1.5
    assert viewer.pick_mode
