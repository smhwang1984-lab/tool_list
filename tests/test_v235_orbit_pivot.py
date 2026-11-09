"""v2.3.5 — 좌드래그 회전이 원점(카메라 중심)이 아니라 클릭한 위치를 기준으로 돈다."""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

try:
    from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QVector3D
    from PyQt5.QtWidgets import QApplication
    from nc_viewer_widget import NCViewerWidget
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
    view.resize(800, 600)
    view.set_source_text(SOURCE, {'T01': 'FACE MILL'})
    view.set_camera_projection('ISO')
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


def project(gl_view, world):
    viewport = gl_view.getViewport()
    vec = (gl_view.projectionMatrix(viewport, viewport) * gl_view.viewMatrix()).map(QVector3D(*world))
    return ((vec.x() + 1.0) / 2.0 * viewport[2], (1.0 - vec.y()) / 2.0 * viewport[3])


def drag(gl_view, start, steps, modifiers=None):
    left = Qt.LeftButton
    mouse(gl_view, 'press', start, left, left, modifiers)
    pos = start
    for step in steps:
        pos = pos + step
        mouse(gl_view, 'move', pos, Qt.NoButton, left, modifiers)
    mouse(gl_view, 'release', pos, left, Qt.NoButton, modifiers)


@pytest.mark.parametrize('view', ['ISO', 'XY'])
@pytest.mark.parametrize('world', [(100.0, 0.0, 0.0), (100.0, 100.0, 0.0), (0.0, 100.0, 0.0)])
def test_left_drag_rotates_about_clicked_path_point(viewer, view, world):
    assert viewer.orbit_pivot_at(*project(viewer.gl_view, world)) is not None
    """경로 위를 눌러 돌리면 그 지점이 화면에서 제자리에 남는다(회전 중심)."""
    gl_view = viewer.gl_view
    viewer.set_camera_projection(view)
    sx, sy = project(gl_view, world)
    start = QPoint(int(round(sx)), int(round(sy)))
    azimuth, elevation = gl_view.opts['azimuth'], gl_view.opts['elevation']
    drag(gl_view, start, [QPoint(30, 0), QPoint(30, -20), QPoint(-10, 25)])
    assert gl_view.opts['azimuth'] != azimuth or gl_view.opts['elevation'] != elevation
    px, py = project(gl_view, world)
    assert abs(px - start.x()) < 1.5 and abs(py - start.y()) < 1.5


def test_left_drag_on_empty_area_keeps_that_screen_point(viewer):
    """경로가 없는 곳을 눌러도 회전 중심은 원점이 아니라 누른 화면 위치다."""
    gl_view = viewer.gl_view
    start = QPoint(60, 60)
    assert viewer.orbit_pivot_at(start.x(), start.y()) is None
    pivot = gl_view._screen_point_at_center_depth(start.x(), start.y())
    drag(gl_view, start, [QPoint(40, 0), QPoint(0, 30)])
    px, py = project(gl_view, tuple(pivot))
    assert abs(px - start.x()) < 1.0 and abs(py - start.y()) < 1.0


def test_pivot_marker_shows_while_rotating_and_pivot_clears_on_release(viewer):
    gl_view = viewer.gl_view
    sx, sy = project(gl_view, (100.0, 0.0, 0.0))
    start = QPoint(int(round(sx)), int(round(sy)))
    left = Qt.LeftButton
    mouse(gl_view, 'press', start, left, left)
    mouse(gl_view, 'move', start + QPoint(40, 0), Qt.NoButton, left)
    assert gl_view.zoom_marker.isVisible() and not gl_view._zoom_marker_timer.isActive()
    geo = gl_view.zoom_marker.geometry()
    assert abs(geo.center().x() - start.x()) <= 1 and abs(geo.center().y() - start.y()) <= 1
    mouse(gl_view, 'release', start + QPoint(40, 0), left, Qt.NoButton)
    assert gl_view._orbit_pivot is None
    assert gl_view._zoom_marker_timer.isActive()


def test_click_without_drag_does_not_move_camera(viewer):
    gl_view = viewer.gl_view
    before = QVector3D(gl_view.opts['center'])
    left = Qt.LeftButton
    mouse(gl_view, 'press', QPoint(200, 200), left, left)
    mouse(gl_view, 'release', QPoint(200, 200), left, Qt.NoButton)
    assert (QVector3D(gl_view.opts['center']) - before).length() < 1e-9


def test_ctrl_drag_still_pans_and_view_cube_orbit_uses_camera_center(viewer):
    gl_view = viewer.gl_view
    azimuth = gl_view.opts['azimuth']
    before = QVector3D(gl_view.opts['center'])
    drag(gl_view, QPoint(300, 300), [QPoint(60, 30)], Qt.ControlModifier)
    assert gl_view.opts['azimuth'] == azimuth
    assert (QVector3D(gl_view.opts['center']) - before).length() > 1e-6
    # 마우스를 누르지 않은 상태의 orbit()(뷰 큐브 링)은 예전처럼 중심 기준이다.
    center = QVector3D(gl_view.opts['center'])
    gl_view.orbit(15.0, 5.0)
    assert (QVector3D(gl_view.opts['center']) - center).length() < 1e-9


def test_lathe_plane_lock_still_pans(viewer):
    gl_view = viewer.gl_view
    gl_view.orbit_locked = True
    azimuth, elevation = gl_view.opts['azimuth'], gl_view.opts['elevation']
    drag(gl_view, QPoint(300, 300), [QPoint(50, 20)])
    assert gl_view.opts['azimuth'] == azimuth and gl_view.opts['elevation'] == elevation
    assert gl_view._orbit_pivot is None
