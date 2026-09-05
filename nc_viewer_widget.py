# -*- coding: utf-8 -*-
"""Embedded PyQt 3D NC path viewer widget."""
import json
from math import cos, radians, sin, tan
import re

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph import Vector
from PyQt5.QtCore import Qt, QPointF, QRectF, QSettings, QSignalBlocker, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QIcon, QKeySequence, QMatrix4x4, QPainter, QPainterPath, QPen, QPixmap,
    QPolygonF, QVector3D,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QSlider,
    QVBoxLayout,
    QWidget,
)


# 96 DPI(윈도우 100% 배율) 기준 1cm의 픽셀 근사값. 오버레이 여백을 "몇 cm"
# 단위로 요청받았을 때 쓴다 — 실제 배율이 다르면 다소 어긋나지만 "정도"
# 수준의 여백 지정이라 크게 문제되지 않는다.
PX_PER_CM = 96.0 / 2.54

# PG 매칭 자동 재생 최대 배속. NC_Tool_List.py의 동일 상수와 값을 맞춰서 유지한다.
MAX_PLAYBACK_SPEED = 5000

# v1.6.2: 1920x1080 실사용에서 뷰어 컨트롤(감도/큐브 바, 재생바 버튼, 다크
# 모드 아이콘)이 지나치게 크다는 피드백으로 크기를 40% 줄인다(= 0.6배).
CONTROL_SHRINK = 0.6

# 좌표/투영 오버레이를 3D 화면 왼쪽 위 모서리에서 띄우는 여백과, 그 둘
# 사이의 세로 간격(v1.6.3).
TOP_LEFT_OVERLAY_MARGIN_PX = 10
TOP_LEFT_OVERLAY_STACK_GAP_PX = 6

# 다크모드 토글 버튼/아이콘 크기(v1.6.1의 52px에서 40% 감축).
DARK_MODE_BUTTON_PX = round(52 * CONTROL_SHRINK)


def shrink(value):
    """v1.6.2 크기 감축 비율(0.6배)을 적용한 정수 픽셀 값."""
    return max(1, round(value * CONTROL_SHRINK))

TOOL_COLOR_MAPS = [
    [1.0, 0.45, 0.10], [0.0, 0.70, 1.0], [0.20, 0.90, 0.25],
    [1.0, 0.25, 0.65], [0.95, 0.85, 0.10], [0.60, 0.35, 1.0],
    [0.00, 0.85, 0.70], [1.0, 0.55, 0.00], [0.65, 0.85, 1.0],
    [0.90, 0.45, 0.95], [0.45, 1.0, 0.45], [1.0, 0.80, 0.55],
]

RAPID_MOVE_COLOR = [1.0, 0.0, 0.0]
RAPID_MOVE_ALPHA = 1.0

# G17/G18/G19 arc-plane axis mapping: (u_axis_idx, v_axis_idx, w_axis_idx, u_offset_letter, v_offset_letter)
# u/v span the arc plane, w is interpolated linearly (helical move); letters pick which of I/J/K
# supplies the plane's center offsets, following the Fanuc convention (G18 uses I/K, G19 uses J/K).
ARC_PLANE_AXES = {
    "G17": (0, 1, 2, "i", "j"),
    "G18": (2, 0, 1, "k", "i"),
    "G19": (1, 2, 0, "j", "k"),
}
ARC_CHORD_TOLERANCE_MM = 0.05
ARC_MIN_SEGMENTS = 6
ARC_MAX_SEGMENTS = 720


DEFAULT_MACHINE_SPECS = {
    "5축 밀링 (A to C)": {
        "X 행정": "800", "Y 행정": "800", "Z 행정": "600",
        "A축 범위": "-120~+30", "C축 범위": "360",
    },
    "3축 MCT (X Y Z)": {"X 행정": "1000", "Y 행정": "600", "Z 행정": "600"},
    "4축 MCT (B-Type)": {
        "X 행정": "1200", "Y 행정": "800", "Z 행정": "800", "B축 범위": "-120~+120",
    },
    "2축 선반 (X Z 평면, X 2배)": {"X 행정": "300", "Z 행정": "500", "최대 RPM": "4000"},
    "5축 밀링 (B to C)": {
        "X 행정": "600", "Y 행정": "600", "Z 행정": "500",
        "B축 범위": "-110~+110", "C축 범위": "360",
    },
}


def tool_color_for_index(index):
    return TOOL_COLOR_MAPS[index % len(TOOL_COLOR_MAPS)]


def qcolor_from_float_rgb(rgb):
    return QColor(*(max(0, min(255, int(channel * 255))) for channel in rgb))


def color_chip_icon(rgb, size=14):
    """Small solid-color square used as a per-tool legend swatch in the filter list."""
    pixmap = QPixmap(size, size)
    pixmap.fill(qcolor_from_float_rgb(rgb))
    return QIcon(pixmap)


def _make_icon(size, paint_fn):
    """Renders an icon via QPainter into a transparent pixmap and wraps it as a
    QIcon. Buttons use these (rather than image files or plain unicode glyphs)
    so they stay crisp at any DPI/theme without adding assets to the PyInstaller
    build, and read more clearly than font-dependent symbols like '◀◀'/'▶'."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    try:
        paint_fn(painter, size)
    finally:
        painter.end()
    return QIcon(pixmap)


def moon_icon(color, size=20):
    """Crescent moon (light-mode indicator: click to switch to dark)."""
    def paint(painter, s):
        r = s * 0.34
        cx = cy = s / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.drawEllipse(QPointF(cx + r * 0.55, cy - r * 0.30), r * 0.82, r * 0.82)
    return _make_icon(size, paint)


def sun_icon(color, size=20):
    """Sun with rays (dark-mode indicator: click to switch to light)."""
    def paint(painter, s):
        cx = cy = s / 2.0
        r = s * 0.20
        pen = QPen(QColor(color))
        pen.setWidthF(max(1.2, s * 0.09))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        inner = r * 1.55
        outer = s * 0.46
        for i in range(8):
            angle = radians(i * 45.0)
            x1, y1 = cx + inner * cos(angle), cy + inner * sin(angle)
            x2, y2 = cx + outer * cos(angle), cy + outer * sin(angle)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    return _make_icon(size, paint)


def play_icon(color, size=22):
    def paint(painter, s):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color)))
        m = s * 0.24
        painter.drawPolygon(QPolygonF([
            QPointF(m, m * 0.65), QPointF(m, s - m * 0.65), QPointF(s - m * 0.8, s / 2.0),
        ]))
    return _make_icon(size, paint)


def pause_icon(color, size=22):
    def paint(painter, s):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color)))
        bar_w, gap, top = s * 0.20, s * 0.16, s * 0.20
        h, cx = s - 2 * top, s / 2.0
        painter.drawRect(QRectF(cx - gap / 2.0 - bar_w, top, bar_w, h))
        painter.drawRect(QRectF(cx + gap / 2.0, top, bar_w, h))
    return _make_icon(size, paint)


def rewind_icon(color, size=22):
    """Two left-pointing triangles (⏪-style double-back)."""
    def paint(painter, s):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color)))
        top, bottom, mid = s * 0.22, s * 0.78, s / 2.0
        for cx in (s * 0.34, s * 0.70):
            painter.drawPolygon(QPolygonF([
                QPointF(cx + s * 0.16, top), QPointF(cx + s * 0.16, bottom), QPointF(cx - s * 0.16, mid),
            ]))
    return _make_icon(size, paint)


def skip_icon(color, size=22, forward=True):
    """Triangle + bar (⏭/⏮-style skip-to-next/previous), used for the prev/next-tool buttons."""
    def paint(painter, s):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color)))
        top, bottom, mid = s * 0.20, s * 0.80, s / 2.0
        if forward:
            tri = QPolygonF([QPointF(s * 0.28, top), QPointF(s * 0.28, bottom), QPointF(s * 0.70, mid)])
            bar = QRectF(s * 0.72, top, s * 0.12, bottom - top)
        else:
            tri = QPolygonF([QPointF(s * 0.72, top), QPointF(s * 0.72, bottom), QPointF(s * 0.30, mid)])
            bar = QRectF(s * 0.16, top, s * 0.12, bottom - top)
        painter.drawPolygon(tri)
        painter.drawRect(bar)
    return _make_icon(size, paint)


_AXIS_GLYPH_COLORS = {"X": "#FF3333", "Y": "#33AA33", "Z": "#4D68FF"}


def plane_icon(letters, size=16):
    """Two short perpendicular strokes colored like the two axes of a view
    plane (e.g. 'XY'), used in front of the ISO/XY/XZ/YZ projection buttons."""
    def paint(painter, s):
        cx = cy = s / 2.0
        pen_w = max(1.4, s * 0.14)
        pen1 = QPen(QColor(_AXIS_GLYPH_COLORS.get(letters[0], "#888888")))
        pen1.setWidthF(pen_w)
        pen1.setCapStyle(Qt.RoundCap)
        painter.setPen(pen1)
        painter.drawLine(QPointF(cx - s * 0.34, cy), QPointF(cx + s * 0.34, cy))
        pen2 = QPen(QColor(_AXIS_GLYPH_COLORS.get(letters[1], "#888888")))
        pen2.setWidthF(pen_w)
        pen2.setCapStyle(Qt.RoundCap)
        painter.setPen(pen2)
        painter.drawLine(QPointF(cx, cy - s * 0.34), QPointF(cx, cy + s * 0.34))
    return _make_icon(size, paint)


def iso_icon(color, size=16):
    """Small 3-axis gizmo for the ISO view button."""
    def paint(painter, s):
        cx, cy = s * 0.5, s * 0.62
        pen = QPen(QColor(color))
        pen.setWidthF(max(1.3, s * 0.12))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - s * 0.42))
        painter.drawLine(QPointF(cx, cy), QPointF(cx - s * 0.36, cy + s * 0.20))
        painter.drawLine(QPointF(cx, cy), QPointF(cx + s * 0.36, cy + s * 0.20))
    return _make_icon(size, paint)


class OrthographicGLViewWidget(gl.GLViewWidget):
    """GL viewer that keeps 3D navigation but removes perspective distortion."""

    # Fired after every mouse-drag orbit/pan, wheel zoom, or setCameraPosition() call
    # so an overlay (e.g. ViewCubeWidget) can repaint itself to match.
    camera_changed = pyqtSignal()
    # Fired on a left-button press+release that didn't drag past _CLICK_DRAG_PX —
    # so it's a genuine click, not the start/end of an orbit. Carries local
    # (logical-pixel) coordinates for NCViewerWidget.pick_source_line().
    left_clicked = pyqtSignal(float, float)
    # Fired on every right-button press, carrying local (logical-pixel)
    # coordinates — the receiver (NCViewerWidget) owns the open/close toggle
    # logic for the magnifier lens and centers it on this position.
    right_clicked = pyqtSignal(float, float)
    # Fired on every mouse move over the widget (any button state), so the
    # magnifier lens can track the cursor while open.
    mouse_moved = pyqtSignal(float, float)

    _CLICK_DRAG_PX = 4.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_orthographic_projection = True
        # Multiplies mouse-drag/wheel movement before it reaches pyqtgraph's own
        # orbit/pan/zoom handling. 1.0 = library default; lower = less sensitive.
        self.navigation_sensitivity = 1.0
        # v1.6.0: Alt+휠로 감도 바를 조정할 수 있게 하는 콜백(호스트 위젯이
        # 주입한다). Ctrl+휠(FOV 줌)은 기존 동작을 그대로 유지한다.
        self.alt_wheel_callback = None
        self.overlay_widget = None
        self.bottom_bar_widget = None
        # v1.6.2: 투영(ISO/XY/XZ/YZ) 표기부를 3D 화면 왼쪽 위에 반투명하게
        # 얹어, 별도 행이 차지하던 자리에도 공구 경로가 보이게 한다.
        # v1.6.3: "좌표" 표시도 같은 자리(왼쪽 위)로 옮겨 위→아래로 쌓으므로
        # 단일 위젯이 아니라 순서 있는 목록으로 관리한다(위쪽부터 좌표,
        # 투영 순).
        self.top_left_widgets = []
        # 렌더된 경로 전체를 감싸는 구의 반지름(원점 기준) — projectionMatrix()가
        # 깊이 클리핑 범위를 카메라 거리 대신 이 값으로 산정해, 확대해도 긴
        # 경로가 far 평면에 잘리지 않게 한다. 경로가 없으면 0(거리 기반 fallback).
        self.scene_radius = 0.0
        self._left_press_pos = None
        self._left_press_was_drag = False
        # pyqtgraph's GLViewWidget defaults to ClickFocus and steals arrow keys for
        # camera orbit (its own keyPressEvent) the moment this widget is clicked,
        # which silently breaks program-cursor arrow-key stepping. Keyboard focus
        # must always stay on the program editor.
        self.setFocusPolicy(Qt.NoFocus)

    def mousePressEvent(self, ev):
        lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
        if ev.button() == Qt.LeftButton:
            self._left_press_pos = lpos
            self._left_press_was_drag = False
        elif ev.button() == Qt.RightButton:
            self.right_clicked.emit(lpos.x(), lpos.y())
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._left_press_pos is not None:
            lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
            if not self._left_press_was_drag:
                self.left_clicked.emit(lpos.x(), lpos.y())
            self._left_press_pos = None
        super().mouseReleaseEvent(ev)

    def mouseMoveEvent(self, ev):
        lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
        if (ev.buttons() & Qt.LeftButton) and self._left_press_pos is not None:
            moved = lpos - self._left_press_pos
            if (moved.x() ** 2 + moved.y() ** 2) ** 0.5 > self._CLICK_DRAG_PX:
                self._left_press_was_drag = True
        if not hasattr(self, 'mousePos'):
            self.mousePos = lpos
        # pyqtgraph's own handler computes diff = lpos - self.mousePos and then
        # overwrites self.mousePos with the true lpos. Pulling the stored point
        # toward lpos by (1 - sensitivity) shrinks that diff without touching
        # pyqtgraph's orbit()/pan() math, so it keeps working across library versions.
        self.mousePos = lpos - (lpos - self.mousePos) * self.navigation_sensitivity
        super().mouseMoveEvent(ev)
        self.camera_changed.emit()
        self.mouse_moved.emit(lpos.x(), lpos.y())

    def wheelEvent(self, ev):
        delta = ev.angleDelta().x()
        if delta == 0:
            delta = ev.angleDelta().y()
        # v1.6.0: Alt+휠은 카메라 줌 대신 감도 바를 조정한다. Ctrl+휠(FOV 줌)은
        # 기존 동작 그대로 둔다(요청에 따라 겹치지 않게 다른 키를 사용).
        if ev.modifiers() & Qt.AltModifier and self.alt_wheel_callback is not None:
            self.alt_wheel_callback(delta)
            return
        delta *= self.navigation_sensitivity
        if ev.modifiers() & Qt.ControlModifier:
            self.opts['fov'] *= 0.999 ** delta
        else:
            self.opts['distance'] *= 0.999 ** delta
        self.update()
        self.camera_changed.emit()

    def setCameraPosition(self, *args, **kwargs):
        super().setCameraPosition(*args, **kwargs)
        self.camera_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_overlay()
        self._reposition_bottom_bar()
        self._reposition_top_left()

    # v1.6.2: 재생바 폭도 버튼 크기와 같은 비율(40% 감축)로 줄인다 — 버튼은
    # 가로로 늘어나는 위젯이라 바 폭을 그대로 두면 패딩만 줄어들고 실제
    # 버튼 크기는 그대로이기 때문이다(0.7 -> 0.42).
    _BOTTOM_BAR_WIDTH_RATIO = 0.42

    def _reposition_bottom_bar(self):
        """Keeps the playback bar centered near the bottom, 42% of the view's width,
        floating about 2cm above the very bottom edge."""
        if self.bottom_bar_widget is None:
            return
        bar = self.bottom_bar_widget
        width = max(200, round(self.width() * self._BOTTOM_BAR_WIDTH_RATIO))
        bar.setFixedWidth(width)
        height = bar.sizeHint().height()
        margin_bottom = round(2 * PX_PER_CM)
        y = self.height() - height - margin_bottom
        bar.move((self.width() - width) // 2, max(0, y))

    def _reposition_overlay(self):
        if self.overlay_widget is None:
            return
        margin = round(2 * PX_PER_CM)
        self.overlay_widget.move(
            max(0, self.width() - self.overlay_widget.width() - margin), margin
        )

    def _reposition_top_left(self):
        """좌표/투영 오버레이를 3D 화면 왼쪽 위 모서리에 위→아래로 쌓아 붙인다
        (v1.6.3: "좌표" 박스도 이 자리로 옮겨오면서 목록으로 관리)."""
        y = TOP_LEFT_OVERLAY_MARGIN_PX
        for widget in self.top_left_widgets:
            if widget is None:
                continue
            widget.move(TOP_LEFT_OVERLAY_MARGIN_PX, y)
            y += widget.height() + TOP_LEFT_OVERLAY_STACK_GAP_PX

    def projectionMatrix(self, region, viewport):
        if not self.use_orthographic_projection:
            return super().projectionMatrix(region, viewport)

        x0, y0, width, height = viewport
        width = max(float(width), 1.0)
        height = max(float(height), 1.0)
        distance = max(float(self.opts.get("distance", 200.0)), 1.0)
        fov = max(float(self.opts.get("fov", 60.0)), 1.0)
        # 깊이 클리핑 범위를 카메라 거리(distance)에만 비례시키면, 확대해서
        # distance가 작아질 때 far 평면도 함께 줄어들어 카메라에서 멀리 뻗은
        # 긴 경로가 화면 중간에서 잘려 보인다(v1.5.6에서 발견된 회귀). 실제
        # 렌더된 경로 전체 크기(scene_radius)를 하한으로 삼아, 확대 배율과
        # 무관하게 전체 경로가 항상 깊이 범위 안에 들어오게 한다.
        depth = max(distance, self.scene_radius) * 20.0 + 1000.0
        view_height = 2.0 * distance * tan(0.5 * radians(fov))
        view_width = view_height * width / height

        left = view_width * ((region[0] - x0) / width - 0.5)
        right = view_width * ((region[0] + region[2] - x0) / width - 0.5)
        bottom = view_height * ((region[1] - y0) / height - 0.5)
        top = view_height * ((region[1] + region[3] - y0) / height - 0.5)

        transform = QMatrix4x4()
        transform.ortho(left, right, bottom, top, -depth, depth)
        return transform


def _cube_face_corners(normal):
    """Return the 4 corners (as (x, y, z) tuples) of an axis-aligned unit cube's
    face whose outward normal is *normal*, walked around the perimeter so the
    result is a valid (non-self-intersecting) quad in any winding direction."""
    nx, ny, nz = normal
    if nx != 0:
        u, v = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    elif ny != 0:
        u, v = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    else:
        u, v = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    corners = []
    for su, sv in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
        corners.append(tuple(
            normal[axis] + su * u[axis] + sv * v[axis] for axis in range(3)
        ))
    return corners


class ViewCubeWidget(QWidget):
    """CAD-style orientation cube overlaid on the viewer's top-right corner.

    Drawn with QPainter rather than OpenGL — this app has a field history of
    OpenGL init failures on some plant PCs (v1.4.3→v1.4.4), so a second GL
    surface is avoided; a schematic cube from 8 projected points doesn't need one.
    Clicking a face snaps the camera to that view via face_clicked(elevation, azimuth).
    A circular ring drawn around the cube (v1.5.10) offers a second, non-snapping
    interaction: dragging inside that ring band orbits the camera live via
    gl_view.orbit(), the same way dragging the 3D viewport itself does — added
    because a plain cube-face click always snaps instantly, which made it easy to
    accidentally jump to the wrong view while only trying to nudge the angle.
    """

    face_clicked = pyqtSignal(float, float)

    # (outward normal, elevation, azimuth, label) — angles match
    # NCViewerWidget.set_camera_angles's convention (same as the ISO/XY/XZ/YZ
    # buttons) so a face click snaps to the same view those buttons produce.
    _FACES = (
        ((0.0, 0.0, 1.0), 90.0, -90.0, "XY"),
        ((0.0, 0.0, -1.0), -90.0, -90.0, "-XY"),
        ((0.0, -1.0, 0.0), 0.0, -90.0, "XZ"),
        ((0.0, 1.0, 0.0), 0.0, 90.0, "-XZ"),
        ((1.0, 0.0, 0.0), 0.0, 0.0, "YZ"),
        ((-1.0, 0.0, 0.0), 0.0, 180.0, "-YZ"),
    )

    def __init__(self, gl_view, parent=None):
        super().__init__(parent)
        self._gl_view = gl_view
        self._face_polygons = []
        # 큐브 바깥을 감싸는 고리(십자 눈금이 있는 원형 띠) 반경 — _paint()에서
        # 큐브 반경(half)에 맞춰 매 프레임 갱신된다. 고리 드래그 판정에 쓴다.
        self._ring_inner_radius = 0.0
        self._ring_outer_radius = 0.0
        self._ring_dragging = False
        self._ring_last_pos = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip('고리 드래그: 부드럽게 회전 | 큐브 면 클릭: 해당 뷰로 즉시 전환')

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter):
        opts = getattr(self._gl_view, 'opts', None)
        if opts is None:
            return
        try:
            elevation = float(opts.get('elevation', 30.0))
            azimuth = float(opts.get('azimuth', -45.0))
        except (TypeError, ValueError):
            return

        # Mirrors GLViewWidget.viewMatrix()'s rotation (translation dropped — this
        # only needs orientation) so the cube always matches the real 3D view.
        rotation = QMatrix4x4()
        rotation.rotate(elevation - 90.0, 1, 0, 0)
        rotation.rotate(azimuth + 90.0, 0, 0, -1)

        # Inset and label metrics are proportional to the widget's own half-extent
        # (not fixed pixel counts) so the cube stays legible at any configured size
        # — the 0.65/0.35 split reproduces the original 80px look (half=40-14=26).
        raw_half = min(self.width(), self.height()) / 2.0
        half = raw_half * 0.65
        if half <= 4:
            return
        cx, cy = self.width() / 2.0, self.height() / 2.0
        # 큐브 바깥 ~ 위젯 가장자리 사이 띠를 드래그용 고리로 쓴다(v1.5.10).
        self._ring_inner_radius = half
        self._ring_outer_radius = raw_half

        def project(point):
            v = rotation.map(QVector3D(*point))
            # Qt's Y grows downward; view space here has Y growing toward the camera.
            return (cx + v.x() * half, cy - v.y() * half), v.z()

        faces = []
        for normal, elevation_target, azimuth_target, label in self._FACES:
            projected = [project(corner) for corner in _cube_face_corners(normal)]
            depth = sum(z for _xy, z in projected) / 4.0
            cx_face = sum(xy[0] for xy, _z in projected) / 4.0
            cy_face = sum(xy[1] for xy, _z in projected) / 4.0
            polygon = QPolygonF([QPointF(x, y) for (x, y), _z in projected])
            faces.append((depth, polygon, cx_face, cy_face, elevation_target, azimuth_target, label))

        # Farthest first so nearer faces paint on top, like a solid object.
        faces.sort(key=lambda item: item[0])
        self._face_polygons = [
            (polygon, elevation_target, azimuth_target)
            for _depth, polygon, _cx, _cy, elevation_target, azimuth_target, _label in faces
        ]

        # Same 80px-derived ratios as `half` above, so labels scale with the cube
        # instead of shrinking (in proportion) as the widget grows.
        label_half_w = half * (18.0 / 26.0)
        label_half_h = half * (8.0 / 26.0)
        pen_width = max(1, round(half / 26.0))
        # 테두리(폴리곤 외곽선)는 그대로 두고 라벨 폰트만 0.8배로 낮춘다(v1.6.0).
        font = painter.font()
        font.setPointSizeF(max(6.0, half * (7.2 / 26.0)))
        painter.setFont(font)

        # v1.6.0: 큐브는 기본 50% 반투명으로 그리고, 고리를 드래그해 회전하는
        # 동안에는 불투명(alpha=255)으로 바뀌어 또렷하게 보이게 한다.
        face_alpha = 255 if self._ring_dragging else 128
        max_depth = max((depth for depth, *_ in faces), default=1.0) or 1.0
        for depth, polygon, cx_face, cy_face, _elev, _azim, label in faces:
            facing = depth > 0.05 * max_depth
            painter.setPen(QPen(QColor(55, 65, 80), pen_width))
            painter.setBrush(QBrush(
                QColor(120, 165, 210, face_alpha) if facing else QColor(72, 80, 94, face_alpha)
            ))
            painter.drawPolygon(polygon)
            painter.setPen(QColor(255, 255, 255) if facing else QColor(150, 155, 165))
            painter.drawText(
                QRectF(cx_face - label_half_w, cy_face - label_half_h,
                       label_half_w * 2.0, label_half_h * 2.0),
                Qt.AlignCenter, label,
            )

        self._paint_drag_ring(painter, cx, cy)

    def _paint_drag_ring(self, painter, cx, cy):
        """큐브를 감싸는 원형 고리(십자 눈금)를 그린다. 큐브 면을 직접 클릭하면
        지금처럼 그 뷰로 즉시 스냅되지만, 큐브 클릭만으로 원하는 각도를 정밀
        조준하기 어렵고 자칫 건드리면 화면이 확 튀어버린다는 피드백(v1.5.9)에
        따라, 이 고리를 드래그하면 스냅 없이 부드럽게(라이브로) 회전한다."""
        outer = self._ring_outer_radius
        inner = self._ring_inner_radius
        if outer <= inner:
            return
        ring_color = QColor(150, 200, 255, 130) if self._ring_dragging else QColor(150, 165, 185, 90)
        pen = QPen(ring_color)
        # v1.6.0: 고리가 더 두껍고 잘 보이도록 폭 계수를 키운다(0.22 -> 0.36).
        pen.setWidthF(max(1.5, (outer - inner) * 0.36))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        mid = (inner + outer) / 2.0
        painter.drawEllipse(QPointF(cx, cy), mid, mid)
        # "십자로" — 상/하/좌/우 4곳에 짧은 눈금을 그려 고리를 잡는 위치임을 암시한다.
        tick_pen = QPen(QColor(210, 225, 245, 200) if self._ring_dragging else QColor(170, 180, 195, 150))
        # v1.6.0: 눈금 두께도 고리와 같은 비율로 키운다(0.14 -> 0.22).
        tick_pen.setWidthF(max(1.2, (outer - inner) * 0.22))
        painter.setPen(tick_pen)
        for angle_deg in (0.0, 90.0, 180.0, 270.0):
            angle = radians(angle_deg)
            dx, dy = sin(angle), -cos(angle)
            painter.drawLine(
                QPointF(cx + dx * inner, cy + dy * inner),
                QPointF(cx + dx * outer, cy + dy * outer),
            )

    def _ring_hit(self, pos):
        """pos(위젯 로컬 좌표)가 드래그 고리 띠 안에 있으면 True."""
        if self._ring_outer_radius <= self._ring_inner_radius:
            return False
        dx = pos.x() - self.width() / 2.0
        dy = pos.y() - self.height() / 2.0
        dist = (dx * dx + dy * dy) ** 0.5
        return self._ring_inner_radius <= dist <= self._ring_outer_radius

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        point = QPointF(event.pos())
        # Iterate nearest-painted-first (reverse of paint order) so an overlapping
        # click resolves to whatever's visually on top.
        for polygon, elevation_target, azimuth_target in reversed(self._face_polygons):
            if polygon.containsPoint(point, Qt.OddEvenFill):
                self.face_clicked.emit(elevation_target, azimuth_target)
                return
        # 큐브 면 바깥, 고리 띠 안을 눌렀으면 스냅 대신 드래그 회전을 시작한다.
        if self._ring_hit(point):
            self._ring_dragging = True
            self._ring_last_pos = point
            self.update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._ring_dragging:
            super().mouseMoveEvent(event)
            return
        point = QPointF(event.pos())
        diff = point - self._ring_last_pos
        self._ring_last_pos = point
        sensitivity = getattr(self._gl_view, "navigation_sensitivity", 1.0)
        # pyqtgraph GLViewWidget.orbit()과 같은 부호 규약(수평 드래그 반대 방향
        # = azimuth, 수직 드래그 = elevation)을 써서 메인 뷰포트를 직접 드래그할
        # 때와 같은 방향감으로 움직인다.
        self._gl_view.orbit(-diff.x() * sensitivity, diff.y() * sensitivity)
        # orbit()은 opts만 바꾸고 camera_changed는 쏘지 않으므로, 돋보기 등
        # 카메라 변경에 반응하는 다른 오버레이도 함께 갱신되도록 직접 emit한다.
        camera_changed = getattr(self._gl_view, "camera_changed", None)
        if camera_changed is not None:
            camera_changed.emit()

    def mouseReleaseEvent(self, event):
        if self._ring_dragging and event.button() == Qt.LeftButton:
            self._ring_dragging = False
            self.update()
            return
        super().mouseReleaseEvent(event)


class MagnifierLensWidget(QWidget):
    """우클릭으로 켜고 끄는 돋보기 렌즈.

    gl_view를 grabFramebuffer()로 캡처한 정지 이미지를 원형으로 잘라 확대해
    마우스를 따라다니며 보여주는 순수 시각 보조 오버레이다. WA_Transparent-
    ForMouseEvents로 모든 마우스 이벤트를 그대로 gl_view에 흘려보내므로,
    실제 클릭 판정(pick_source_line)은 항상 gl_view가 원래(확대 전) 좌표로
    받는다 — 렌즈는 "어디를 클릭할지 정밀하게 보여주는" 역할만 한다.
    카메라가 움직이는 동안에는 보이는 그림과 실제 위치가 어긋나므로 숨긴다."""

    DIAMETER = 220
    ZOOM = 3.0

    def __init__(self, gl_view, parent=None):
        super().__init__(parent)
        self._gl_view = gl_view
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._source = None
        self._center = QPointF(0.0, 0.0)
        self.hide()

    def set_source(self, image):
        self._source = image
        self.update()

    def move_center_to(self, x, y):
        """렌즈 중심을 gl_view 좌표 (x, y) 근처로 옮긴다. 커서가 렌즈에 가리지
        않도록 살짝 위로 띄우고, gl_view 영역을 벗어나지 않게 고정한다."""
        self._center = QPointF(x, y)
        half = self.DIAMETER / 2.0
        target_x, target_y = x - half, y - half - self.DIAMETER * 0.55
        if self._gl_view is not None:
            max_x = max(0, self._gl_view.width() - self.DIAMETER)
            max_y = max(0, self._gl_view.height() - self.DIAMETER)
            target_x = max(0, min(target_x, max_x))
            target_y = max(0, min(target_y, max_y))
        self.move(int(target_x), int(target_y))
        self.update()

    def paintEvent(self, _event):
        if self._source is None or self._source.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, self.DIAMETER, self.DIAMETER)
        painter.setClipPath(path)

        # QImage.devicePixelRatio()(grabFramebuffer가 자동으로 설정)를 Qt가
        # drawImage()에서 알아서 반영하므로, src_rect는 gl_view의 논리 좌표
        # 그대로 쓰면 된다(DPI 배율을 직접 곱할 필요 없음).
        crop = self.DIAMETER / self.ZOOM
        src_rect = QRectF(
            self._center.x() - crop / 2.0, self._center.y() - crop / 2.0, crop, crop,
        )
        painter.drawImage(QRectF(0, 0, self.DIAMETER, self.DIAMETER), self._source, src_rect)

        pen = QPen(QColor(255, 255, 255, 220))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(1, 1, self.DIAMETER - 2, self.DIAMETER - 2)

        # 실제로 클릭이 판정되는 지점(원 좌표계 아래 gl_view가 그대로 받는
        # 실제 커서 위치)은 항상 렌즈 정중앙에 대응한다 — 어디를 클릭할지
        # 정확히 짚을 수 있도록 가는 십자선으로 표시한다.
        cx = cy = self.DIAMETER / 2.0
        cross = 9.0
        cross_pen = QPen(QColor(255, 60, 40, 230))
        cross_pen.setWidth(2)
        painter.setPen(cross_pen)
        painter.drawLine(QPointF(cx - cross, cy), QPointF(cx + cross, cy))
        painter.drawLine(QPointF(cx, cy - cross), QPointF(cx, cy + cross))


class ProjectionOverlayWidget(QWidget):
    """ISO/XY/XZ/YZ 투영 전환 버튼을 3D 화면 왼쪽 위에 얹는 오버레이.

    v1.6.2 요청: 기존에 뷰어 상단에 별도 행(view_bar)을 차지하던 "투영"
    라벨/버튼들을 3D 화면 안쪽으로 옮기고, 배경을 투명하게 해서 뒤에 그려진
    공구 경로가 버튼 사이로 그대로 비치게 한다.
    """

    projection_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 버튼 자체만 옅게 보이는 배경을 주고, 위젯 전체(라벨 주변 여백)는
        # 완전히 투명하게 둬 공구 경로를 가리지 않는다.
        self.setStyleSheet(
            "ProjectionOverlayWidget { background: transparent; }"
            " QLabel { background: transparent; color: white; font-size: 12px; }"
            " QPushButton { color: white; background-color: rgba(40, 44, 52, 90);"
            " border: 1px solid rgba(255, 255, 255, 70); border-radius: 5px;"
            " padding: 3px 7px; font-size: 12px; }"
            " QPushButton:hover { background-color: rgba(255, 255, 255, 65); }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        # v1.6.3: 버튼끼리 너무 붙어 있다는 피드백으로 간격을 4 -> 10px로
        # 넓힌다. "투영" 라벨과 첫 버튼 사이에는 조금 더 띄운다.
        row.setSpacing(10)
        label = QLabel("투영")
        row.addWidget(label)
        row.addSpacing(4)
        for text, view_type in (
            ("ISO", "ISO"), ("XY", "XY"), ("XZ", "XZ"), ("YZ", "YZ"),
        ):
            button = QPushButton(text)
            button.setIcon(iso_icon("#e4e8f0") if view_type == "ISO" else plane_icon(view_type))
            button.setIconSize(QSize(14, 14))
            # 방향키로 프로그램 커서를 옮기는 도중 이 버튼이 포커스를 가져가면
            # 다음 방향키가 커서 대신 버튼 포커스 이동에 쓰이므로 항상 막아둔다.
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, value=view_type: self.projection_clicked.emit(value))
            row.addWidget(button)
        self.adjustSize()


class CoordOverlayWidget(QWidget):
    """현재 좌표(X~C)를 3D 화면 왼쪽 위에 얹는 오버레이(v1.6.3).

    이전에는 QGroupBox("좌표")로 3D 화면 위 별도 행에 그려졌는데, 그 박스
    배경이 3D 화면을 가려 공구 경로가 안 보인다는 피드백으로 이 오버레이로
    바꾼다 — 박스 테두리/배경 없이 글자만 3D 화면 위에 떠 있다. 축 프리픽스
    글자(X:, Y: 등)는 항상 어두운 3D 캔버스 위에 떠 있으므로 테마와 무관하게
    흰색으로 고정한다 — 값 자체는 기존 축별 색상을 그대로 유지한다.
    """

    _AXIS_COLORS = {
        "X": "#FF3333", "Y": "#33AA33", "Z": "#4D68FF",
        "A": "#9A8500", "B": "#AA33AA", "C": "#229999",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(
            "CoordOverlayWidget { background: transparent; }"
            " QLabel { background: transparent; color: white; font-size: 14px; font-weight: bold; }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(14)
        self.value_labels = {}
        for axis in ("X", "Y", "Z", "A", "B", "C"):
            axis_label = QLabel(axis + ":")
            row.addWidget(axis_label)
            value = QLabel("0.000")
            value.setStyleSheet(
                "background: transparent; font-weight: bold; font-size: 14px; color: %s;"
                % self._AXIS_COLORS[axis]
            )
            self.value_labels[axis] = value
            row.addWidget(value)
        self.adjustSize()


class PlaybackBarWidget(QWidget):
    """PG 매칭 모드에서 프로그램을 자동으로 넘겨주는 재생 컨트롤 바.

    뷰어 하단 중앙(폭 = 뷰어 폭의 70%)에 반투명하게 떠 있다. 실제 재생 로직(타이머,
    커서 이동, M00/M01 정지)은 호스트 앱(NC_Tool_List.App)이 갖고 있고, 이 위젯은
    버튼/슬라이더 UI와 시그널만 담당한다.
    """

    play_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    rewind_clicked = pyqtSignal()
    prev_tool_clicked = pyqtSignal()
    next_tool_clicked = pyqtSignal()
    speed_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # v1.6.1: 앱 전역 테마 스타일시트의 'QWidget { background: ... }'
        # 규칙이 (Qt는 타입 선택자를 서브클래스까지 매칭하므로) 이 바의
        # 자식 QLabel/QSlider에도 적용되어, 라이트 모드에서 밝은 배경이
        # 반투명 어두운 패널 위를 불투명하게 덮어 흰 글자가 안 보이는
        # 문제가 있었다. 이 바는 항상 어두운 3D 캔버스 위에 뜨므로
        # 테마와 무관하게 항상 다크 디자인으로 고정한다.
        # v1.6.2: 1920x1080 실사용에서 너무 크다는 피드백으로 바 전체(패딩·
        # 폰트·슬라이더 두께)를 40% 줄인다 — 아래 수치는 모두 v1.6.1 값에
        # shrink()(0.6배)를 적용한 것이다.
        self.setStyleSheet(
            "PlaybackBarWidget { background-color: rgba(33, 37, 43, 190);"
            " border-radius: %(radius)dpx; }"
            " QLabel { background: transparent; color: white; font-size: %(label)dpx; }"
            " QSlider { background: transparent; }"
            " QSlider::groove:horizontal { background: rgba(255, 255, 255, 40);"
            " border-radius: %(groove_radius)dpx; height: %(groove)dpx; }"
            " QSlider::sub-page:horizontal { background: rgba(120, 170, 255, 200);"
            " border-radius: %(groove_radius)dpx; height: %(groove)dpx; }"
            " QSlider::handle:horizontal { background: #e4e8f0;"
            " border: 1px solid rgba(0, 0, 0, 80); width: %(handle)dpx; height: %(handle)dpx;"
            " margin: -%(handle_margin)dpx 0; border-radius: %(handle_radius)dpx; }"
            " QPushButton { color: white; background-color: rgba(255, 255, 255, 30);"
            " border: 1px solid rgba(255, 255, 255, 60); border-radius: %(btn_radius)dpx;"
            " padding: %(btn_pad_v)dpx %(btn_pad_h)dpx; font-size: %(btn_font)dpx;"
            " font-weight: bold; }"
            " QPushButton:hover { background-color: rgba(255, 255, 255, 55); }"
            " QPushButton:disabled { color: rgba(255, 255, 255, 90); }"
            % {
                "radius": shrink(14), "label": shrink(15),
                "groove": shrink(12), "groove_radius": shrink(6),
                "handle": shrink(22), "handle_margin": shrink(6),
                "handle_radius": shrink(11),
                "btn_radius": shrink(8), "btn_pad_v": shrink(18),
                "btn_pad_h": shrink(27), "btn_font": shrink(17),
            }
        )
        self.setEnabled(False)
        self._playing = False

        # 전체 높이(~3배)와 버튼 크기(~2.5배)를 원래(80px 큐브 시절과 같은 시기에
        # 만든 60px 높이 바) 대비로 키워 달라는 사용자 요청 반영. 슬라이더도
        # 자간을 맞춰 함께 키운다.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(shrink(26), shrink(24), shrink(26), shrink(26))
        outer.setSpacing(shrink(26))

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("속도"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, MAX_PLAYBACK_SPEED)
        self.speed_slider.setValue(1)
        # v1.6.0: 속도바 두께를 기존의 2배로 키운다(34 -> 68).
        # v1.6.2: 다른 컨트롤과 같은 비율로 40% 줄인다(68 -> 41).
        self.speed_slider.setFixedHeight(shrink(68))
        self.speed_slider.setFocusPolicy(Qt.NoFocus)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_value_label = QLabel("1x")
        # v1.6.0: 속도 값 폰트를 기존의 1.7배(15px -> 26px)로 키운다. 이 바의
        # 다른 QLabel(예: "속도")까지 함께 커지지 않도록 인스턴스 스타일시트로
        # 개별 지정한다(인스턴스 지정값이 클래스 규칙보다 우선한다).
        self.speed_value_label.setStyleSheet(
            "background: transparent; color: white; font-size: %dpx; font-weight: bold;"
            % shrink(26)
        )
        self.speed_value_label.setFixedWidth(shrink(122))
        speed_row.addWidget(self.speed_value_label)
        outer.addLayout(speed_row)

        # 유니코드 기호(◀◀/▶ 등)는 폰트마다 굵기·정렬이 들쭉날쭉해 시인성이
        # 떨어져, QPainter로 직접 그린 아이콘으로 바꾼다(_make_icon 계열).
        # 이 바는 항상 어두운 반투명 패널 위라 아이콘 색은 테마와 무관하게
        # 흰색으로 고정한다.
        icon_size = QSize(shrink(26), shrink(26))
        button_row = QHBoxLayout()
        self.prev_tool_button = QPushButton()
        self.prev_tool_button.setIcon(skip_icon("white", forward=False))
        self.prev_tool_button.setToolTip("이전 툴 (F6)")
        self.rewind_button = QPushButton()
        self.rewind_button.setIcon(rewind_icon("white"))
        self.rewind_button.setToolTip("되감기")
        self.play_pause_button = QPushButton()
        self.play_pause_button.setIcon(play_icon("white"))
        self.play_pause_button.setToolTip("재생 (F7)")
        self.next_tool_button = QPushButton()
        self.next_tool_button.setIcon(skip_icon("white", forward=True))
        self.next_tool_button.setToolTip("다음 툴 (F8)")
        for button in (
            self.prev_tool_button, self.rewind_button,
            self.play_pause_button, self.next_tool_button,
        ):
            button.setFocusPolicy(Qt.NoFocus)
            button.setIconSize(icon_size)
            button_row.addWidget(button)
        outer.addLayout(button_row)

        self.prev_tool_button.clicked.connect(self.prev_tool_clicked)
        self.next_tool_button.clicked.connect(self.next_tool_clicked)
        self.rewind_button.clicked.connect(self.rewind_clicked)
        self.play_pause_button.clicked.connect(self._on_play_pause_clicked)

    def _on_speed_changed(self, value):
        self.speed_value_label.setText("%dx" % value)
        self.speed_changed.emit(value)

    def _on_play_pause_clicked(self):
        if self._playing:
            self.pause_clicked.emit()
        else:
            self.play_clicked.emit()

    def set_playing(self, playing):
        self._playing = bool(playing)
        self.play_pause_button.setIcon(pause_icon("white") if self._playing else play_icon("white"))
        self.play_pause_button.setToolTip("일시정지" if self._playing else "재생")

    def set_speed(self, value):
        with QSignalBlocker(self.speed_slider):
            self.speed_slider.setValue(value)
        self.speed_value_label.setText("%dx" % self.speed_slider.value())


class NCViewerWidget(QWidget):
    """Viewer-only widget used inside the main tool-list application."""

    # Emitted with the source line index where a clicked process-filter entry begins,
    # so the host window can move the program editor's cursor there.
    process_activated = pyqtSignal(int)
    # Emitted when the dark-mode button (next to the view-cube size slider) is
    # clicked. The host App owns the theme and calls set_dark_mode() back once
    # it has re-themed the rest of the app, so the app-wide setting stays the
    # single source of truth rather than this widget's own QSettings group.
    dark_mode_toggled = pyqtSignal(bool)
    # Emitted with the source line index of a 3D path segment the user clicked
    # on, so the host window can move the program editor's cursor there —
    # same contract as process_activated, just picked from the drawn path
    # itself instead of the process filter list.
    line_activated = pyqtSignal(int)

    # 3D 캔버스와 돋보기 렌즈(캔버스를 그대로 캡처)는 앱 라이트/다크 테마와
    # 무관하게 항상 이 어두운 배경을 쓴다 — 경로 선 색이 밝은색 위주라
    # 흰 배경에서는 시인성이 크게 떨어지는 사용자 피드백 반영(v1.5.7).
    _VIEWER_BG = (33, 37, 43, 255)
    # 클릭 판정은 이제 돋보기가 켜져 있을 때만 동작하므로(v1.5.7), 돋보기
    # 배율(MagnifierLensWidget.ZOOM = 3x)만큼 더 정밀하게 조준할 수 있다는
    # 전제로 반경을 좁혀 "근처 다른 라인이 잘못 집히는" 문제를 줄인다.
    _PICK_RADIUS_PX = 4.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("NC Tool List", "EmbeddedViewer")
        self._dark_mode = False
        self._pick_cache_key = None
        self._pick_world_pts = np.zeros((0, 2, 3), dtype=np.float64)
        self._pick_src_lines = np.zeros((0,), dtype=np.int64)
        self._magnifier_active = False
        self.machine_specs = self._load_machine_specs()
        self.current_machine_type = self.settings.value(
            "machine_type", next(iter(self.machine_specs))
        )
        if self.current_machine_type not in self.machine_specs:
            self.current_machine_type = next(iter(self.machine_specs))

        self.tool_paths = {}
        self.plot_items = {}
        self.raw_lines = []
        self.tool_name_map = {}
        self.process_tool_map = {}
        self.tool_filter_list = None
        self.last_source_text = None
        self.last_render_signature = None
        self.line_to_coord_map = {}
        self.line_to_tool_map = {}
        self.process_first_line = {}
        self.modal_state_map = {}
        self.dynamic_trace_items = []
        self.current_cursor_line = 0
        # "PG 매칭" 모드: 정적 경로를 모두 감추고, 커서가 위치한 공정의 실시간
        # 트레이스만 남겨 프로그램 줄과 경로를 1:1로 대조할 수 있게 한다.
        # 일시적인 확인용 모드라 QSettings에 저장하지 않는다.
        self.pg_match_mode = False
        # 마우스 감도는 PC/마우스마다 맞는 값이 달라 PG 매칭과 달리 저장한다.
        self._initial_sensitivity = self._load_navigation_sensitivity()
        self._initial_cube_size = self._load_view_cube_size()

        self._build_ui()
        self.set_machine_type(self.current_machine_type, init_camera=True)

    def _load_navigation_sensitivity(self):
        raw = self.settings.value("navigation_sensitivity", 0.4)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.4
        return max(0.05, min(2.0, value))

    def _load_view_cube_size(self):
        raw = self.settings.value("view_cube_size", 160)
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = 160
        return max(60, min(240, value))

    def _load_machine_specs(self):
        raw = self.settings.value("machine_specs", "")
        if raw:
            try:
                saved = json.loads(raw)
                if isinstance(saved, dict):
                    specs = json.loads(json.dumps(DEFAULT_MACHINE_SPECS, ensure_ascii=False))
                    for machine_type, values in saved.items():
                        if isinstance(values, dict):
                            specs[machine_type] = {
                                str(key): str(value) for key, value in values.items()
                            }
                    return specs
            except (TypeError, ValueError):
                pass
        return json.loads(json.dumps(DEFAULT_MACHINE_SPECS, ensure_ascii=False))

    def _save_machine_specs(self):
        self.settings.setValue(
            "machine_specs", json.dumps(self.machine_specs, ensure_ascii=False)
        )
        self.settings.setValue("machine_type", self.current_machine_type)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        view_bar = QHBoxLayout()
        # v1.6.1: 다크모드 아이콘을 2배로 키우며 행 높이 증가를 최소화하기
        # 위해 상하 여백을 5px -> 0px로 줄였다.
        # v1.6.2: 투영 버튼(3D 화면 오버레이로 이동)과 다크모드 버튼(앱 상단
        # 바로 이동)이 이 행에서 빠져, 남은 감도/큐브 바만 오른쪽에 둔다.
        view_bar.setContentsMargins(6, 0, 6, 0)
        view_bar.addStretch()
        # "감도"/"큐브" 라벨과 슬라이더(바)는 기존(설정 안 된 기본 폰트, 폭
        # 110/90px)의 1.5배로 키웠다(v1.5.8 요청).
        # v1.6.2: "감도" 쪽만 1920x1080에서 너무 크다는 피드백으로 폰트/폭을
        # 40% 줄였다 — 당시 "큐브"는 실제 3D 오리엔테이션 큐브 자체를 손대지
        # 말라는 요청으로 그 슬라이더/라벨(UI 크롬)까지 그대로 뒀었다.
        # v1.6.3: 큐브 UI(라벨/슬라이더 바) 크기가 줄지 않았다는 재요청으로,
        # 감도와 같은 비율로 폰트·바 폭만 줄인다 — 큐브의 기본 픽셀 크기
        # (_initial_cube_size)와 범위(60~240)는 실제 3D 큐브 그래픽 크기를
        # 결정하는 값이라 여기서 손대지 않는다(요청 취지 유지).
        sensitivity_font = QFont("맑은 고딕")
        sensitivity_font.setPointSizeF(14 * CONTROL_SHRINK)
        cube_font = QFont("맑은 고딕")
        cube_font.setPointSizeF(14 * CONTROL_SHRINK)
        sensitivity_label = QLabel("감도")
        sensitivity_label.setFont(sensitivity_font)
        view_bar.addWidget(sensitivity_label)
        self.sensitivity_slider = QSlider(Qt.Horizontal)
        self.sensitivity_slider.setRange(5, 200)
        self.sensitivity_slider.setFixedWidth(shrink(165))
        self.sensitivity_slider.setValue(round(self._initial_sensitivity * 100))
        self.sensitivity_slider.setToolTip("마우스 드래그/휠 회전·확대 감도")
        self.sensitivity_slider.setFocusPolicy(Qt.NoFocus)
        self.sensitivity_slider.valueChanged.connect(self._on_sensitivity_changed)
        view_bar.addWidget(self.sensitivity_slider)
        self.sensitivity_value_label = QLabel("%d%%" % self.sensitivity_slider.value())
        self.sensitivity_value_label.setFont(sensitivity_font)
        self.sensitivity_value_label.setFixedWidth(shrink(57))
        view_bar.addWidget(self.sensitivity_value_label)
        # 감도 값 라벨과 "큐브" 라벨이 커진 폰트/바 폭 탓에 붙어 보이는(겹침)
        # 문제가 있어 그 사이에 여유 간격을 더 준다(v1.5.9 요청).
        view_bar.addSpacing(18)
        cube_label = QLabel("큐브")
        cube_label.setFont(cube_font)
        view_bar.addWidget(cube_label)
        self.view_cube_size_slider = QSlider(Qt.Horizontal)
        # 범위(60~240)와 초기값은 3D 큐브 자체의 실제 픽셀 크기를 그대로
        # 결정하므로 손대지 않는다 — 여기서 줄이는 건 이 슬라이더 바/라벨의
        # 화면 UI 크기뿐이다.
        self.view_cube_size_slider.setRange(60, 240)
        self.view_cube_size_slider.setFixedWidth(shrink(135))
        self.view_cube_size_slider.setValue(self._initial_cube_size)
        self.view_cube_size_slider.setToolTip("방향 큐브 크기")
        self.view_cube_size_slider.setFocusPolicy(Qt.NoFocus)
        self.view_cube_size_slider.valueChanged.connect(self._on_view_cube_size_changed)
        view_bar.addWidget(self.view_cube_size_slider)
        self.view_cube_size_label = QLabel("%dpx" % self.view_cube_size_slider.value())
        self.view_cube_size_label.setFont(cube_font)
        self.view_cube_size_label.setFixedWidth(shrink(57))
        view_bar.addWidget(self.view_cube_size_label)
        # v1.6.2: 다크모드 버튼은 이 행이 아니라 앱 상단 바(About/도움말/모드
        # 버튼 줄)로 옮겨 달라는 요청에 따라, 여기서는 만들어 두기만 하고
        # 레이아웃에는 넣지 않는다. 호스트(App)가 take_dark_mode_button()으로
        # 가져가 자기 상단 바에 배치한다. 가져가지 않으면 숨은 채로 남는다.
        self.dark_mode_button = QPushButton(self)
        self.dark_mode_button.setCheckable(True)
        # 다크/라이트 아이콘이 잘 안 보인다는 요청으로 버튼·아이콘 크기를
        # 키웠다(v1.5.9: 26 -> 36px, v1.6.1: 52px). v1.6.2에서 다른 컨트롤과
        # 같은 비율로 40% 줄인다(52 -> 31px) — 상단 바 버튼 줄에 맞는 높이다.
        self.dark_mode_button.setFixedSize(DARK_MODE_BUTTON_PX, DARK_MODE_BUTTON_PX)
        self.dark_mode_button.setToolTip("다크모드 전환")
        self.dark_mode_button.setFocusPolicy(Qt.NoFocus)
        self.dark_mode_button.setFlat(True)
        self.dark_mode_button.hide()
        self.dark_mode_button.clicked.connect(
            lambda: self.dark_mode_toggled.emit(self.dark_mode_button.isChecked())
        )
        self._refresh_dark_mode_button()
        # "감도 바~큐브 바" 그룹 전체를 오른쪽 끝에서 2cm 정도 안쪽(왼쪽)으로
        # 옮겨 배치한다(v1.5.9 요청) — 그룹 뒤에 고정폭 여백을 둬서 패널
        # 오른쪽 가장자리에서 살짝 띄운다.
        view_bar.addSpacing(round(2 * PX_PER_CM))
        layout.addLayout(view_bar)

        # v1.6.3: "좌표"를 별도 행(QGroupBox, 불투명 배경)이 아니라 3D 화면
        # 왼쪽 위의 반투명 오버레이로 옮긴다 — 그 박스 배경이 3D 화면을
        # 가려 공구 경로가 안 보인다는 피드백 반영. 실제 위젯은 gl_view가
        # 만들어진 뒤 _build_coord_overlay()에서 만든다(self.coord_labels는
        # 거기서 채워진다).

        self.gl_view = OrthographicGLViewWidget()
        self.gl_view.setBackgroundColor(*self._VIEWER_BG)
        self.gl_view.navigation_sensitivity = self._initial_sensitivity
        # v1.6.0: Alt+휠로 감도 슬라이더를 조정할 수 있게 콜백을 연결한다.
        self.gl_view.alt_wheel_callback = self._on_alt_wheel_sensitivity
        layout.addWidget(self.gl_view, 1)
        self._build_view_cube()
        self._build_coord_overlay()
        self._build_projection_overlay()
        self._build_playback_bar()
        self._build_magnifier()
        self.gl_view.left_clicked.connect(self._on_gl_left_clicked)
        self.gl_view.right_clicked.connect(self._on_gl_right_clicked)
        self.gl_view.mouse_moved.connect(self._on_gl_mouse_moved)
        self.gl_view.camera_changed.connect(self._on_camera_changed_for_magnifier)
        self._magnifier_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._magnifier_shortcut.setContext(Qt.ApplicationShortcut)
        self._magnifier_shortcut.activated.connect(self._close_magnifier)

        # 격자판은 넓은 프로그램에서 시야를 가려 제거했다(v1.5.6) — 방향
        # 기준은 축선(_add_axis_lines)만으로 충분하다.
        self._add_axis_lines()
        # v1.6.1: 화살표를 화면 고정 크기로 유지하려면 카메라가 움직일
        # 때마다(줌 포함) 좌표를 다시 계산해야 한다.
        self.gl_view.camera_changed.connect(self._update_axis_lines_live)

        self.cursor_sphere = gl.GLMeshItem(
            meshdata=gl.MeshData.sphere(rows=10, cols=20, radius=2.0),
            smooth=True,
            color=(1.0, 1.0, 0.0, 1.0),
            shader="shaded",
        )
        self.cursor_sphere.setVisible(False)
        self.gl_view.addItem(self.cursor_sphere)

        # 라인 클릭으로 행 이동했을 때 어느 지점이 집혔는지 잠깐 보여주는
        # 표시(자동재생 커서 표시용 cursor_sphere와는 별개 — 상태를 두고
        # 다투지 않도록 전용 구를 하나 더 둔다).
        self._pick_flash_sphere = gl.GLMeshItem(
            meshdata=gl.MeshData.sphere(rows=10, cols=20, radius=2.6),
            smooth=True,
            color=(1.0, 0.85, 0.15, 1.0),
            shader="shaded",
        )
        self._pick_flash_sphere.setVisible(False)
        self.gl_view.addItem(self._pick_flash_sphere)
        self._pick_flash_timer = QTimer(self)
        self._pick_flash_timer.setSingleShot(True)
        self._pick_flash_timer.setInterval(700)
        self._pick_flash_timer.timeout.connect(lambda: self._pick_flash_sphere.setVisible(False))

    def _build_view_cube(self):
        """Create the corner orientation cube. Any failure here is swallowed —
        losing the cube overlay beats losing the whole 3D viewer on a PC where
        this doesn't work for some reason."""
        try:
            view_cube = ViewCubeWidget(self.gl_view, parent=self.gl_view)
            view_cube.setFixedSize(self._initial_cube_size, self._initial_cube_size)
            self.gl_view.overlay_widget = view_cube
            self.gl_view._reposition_overlay()
            self.gl_view.camera_changed.connect(view_cube.update)
            view_cube.face_clicked.connect(self.set_camera_angles)
            view_cube.raise_()
        except Exception:
            self.gl_view.overlay_widget = None
            view_cube = None
        self.view_cube = view_cube

    def _build_coord_overlay(self):
        """3D 화면 왼쪽 위에 "좌표"(X~C) 오버레이를 만든다(v1.6.3).
        실패해도 뷰어 전체를 잃지 않는다."""
        try:
            coord_overlay = CoordOverlayWidget(self.gl_view)
            self.gl_view.top_left_widgets.append(coord_overlay)
            self.gl_view._reposition_top_left()
            coord_overlay.raise_()
            self.coord_labels = coord_overlay.value_labels
        except Exception:
            coord_overlay = None
            self.coord_labels = {}
        self.coord_overlay = coord_overlay

    def _build_projection_overlay(self):
        """3D 화면 왼쪽 위, 좌표 오버레이 아래에 투영(ISO/XY/XZ/YZ) 오버레이를
        만든다(v1.6.2). 실패해도 뷰어 전체를 잃지 않는다."""
        try:
            overlay = ProjectionOverlayWidget(self.gl_view)
            self.gl_view.top_left_widgets.append(overlay)
            self.gl_view._reposition_top_left()
            overlay.projection_clicked.connect(self.set_camera_projection)
            overlay.raise_()
        except Exception:
            overlay = None
        self.projection_overlay = overlay

    def _build_playback_bar(self):
        """PG 매칭 자동 재생 컨트롤 바를 만든다. 실패해도 뷰어 전체를 잃지 않는다."""
        try:
            bar = PlaybackBarWidget(self.gl_view)
            self.gl_view.bottom_bar_widget = bar
            self.gl_view._reposition_bottom_bar()
            bar.raise_()
        except Exception:
            self.gl_view.bottom_bar_widget = None
            bar = None
        self.playback_bar = bar

    def _build_magnifier(self):
        """돋보기 렌즈 오버레이를 만든다. 실패해도 뷰어 전체를 잃지 않는다."""
        try:
            lens = MagnifierLensWidget(self.gl_view, parent=self.gl_view)
        except Exception:
            lens = None
        self.magnifier = lens

    def _on_gl_right_clicked(self, x, y):
        """우클릭 위치에서 돋보기를 켠다(다시 우클릭하면 끈다) — 렌즈는 항상
        그 우클릭 지점을 중심으로 나타나야 한다는 사용자 요청 반영(v1.5.7)."""
        if self.magnifier is None:
            return
        if self._magnifier_active:
            self._close_magnifier()
        else:
            self._magnifier_active = True
            self.magnifier.move_center_to(x, y)
            self._recapture_magnifier_source()
            self.magnifier.show()
            self.magnifier.raise_()

    def _close_magnifier(self):
        if self.magnifier is None or not self._magnifier_active:
            return
        self._magnifier_active = False
        self.magnifier.hide()

    def _recapture_magnifier_source(self):
        """gl_view의 현재 프레임을 다시 캡처한다. 카메라가 움직이는 동안에는
        보이는 그림과 실제 위치가 어긋나므로, 그 사이에는 렌즈를 숨긴다."""
        if self.magnifier is None or not self._magnifier_active:
            return
        try:
            image = self.gl_view.grabFramebuffer()
        except Exception:
            return
        self.magnifier.set_source(image)

    def _on_camera_changed_for_magnifier(self):
        # 캡처 이미지가 곧바로 낡은 그림이 되므로, 재캡처 전까지는 숨겨서
        # 실제 위치와 어긋난 렌즈를 보여주지 않는다.
        if self._magnifier_active and self.magnifier is not None:
            self.magnifier.hide()
            QTimer.singleShot(0, self._reshow_magnifier_after_camera_change)

    def _reshow_magnifier_after_camera_change(self):
        if not self._magnifier_active or self.magnifier is None:
            return
        self._recapture_magnifier_source()
        self.magnifier.show()
        self.magnifier.raise_()

    def _on_gl_mouse_moved(self, x, y):
        if self._magnifier_active and self.magnifier is not None:
            self.magnifier.move_center_to(x, y)

    def _on_gl_left_clicked(self, x, y):
        # 라인 픽킹은 돋보기가 켜져 있을 때만 동작한다 — 꺼진 상태에서는
        # 순수 카메라 조작(좌클릭 드래그로 궤도 회전)만 하도록 요청받았다.
        # 돋보기 없이 화면을 찍으면 의도치 않게 근처 라인으로 커서가
        # 넘어가던 문제(v1.5.6)의 수정(v1.5.7).
        if not self._magnifier_active:
            return
        line_index = self.pick_source_line(x, y)
        if line_index is None:
            return
        self._flash_pick(line_index)
        self.line_activated.emit(line_index)

    def _flash_pick(self, line_index):
        pt = self.line_to_coord_map.get(line_index)
        if pt is None:
            return
        self._pick_flash_sphere.resetTransform()
        self._pick_flash_sphere.translate(pt[0], pt[1], pt[2])
        self._pick_flash_sphere.setVisible(True)
        self._pick_flash_timer.start()

    def _collect_pick_segments(self, path_data, segments, lines, line_limit=None):
        """path_data를 (세계좌표 선분, 도착 지점 src_line) 쌍으로 뽑아
        segments/lines에 이어붙인다. line_limit이 주어지면 그 라인을 넘는
        지점부터는 _render_segments()와 똑같이 잘라낸다 — 클릭 판정 대상이
        실제로 화면에 그려진 구간과 정확히 일치해야 하기 때문이다."""
        previous_pt = None
        for node in path_data:
            src_line = node.get("src_line", -1)
            if line_limit is not None and src_line > line_limit:
                break
            if not node.get("valid"):
                previous_pt = None
                continue
            pt = node.get("pt")
            if pt is None:
                previous_pt = None
                continue
            if previous_pt is not None:
                segments.append((previous_pt, pt))
                lines.append(int(src_line))
            previous_pt = pt

    def _pick_cache_scope_key(self):
        """현재 화면에 실제로 그려진 경로 범위를 식별하는 키. PG 매칭
        모드에서는 커서 라인이 바뀔 때마다(= 진행된 구간이 늘어날 때마다)
        픽 캐시도 함께 갱신되어야 한다."""
        if self.pg_match_mode:
            return (
                self.last_render_signature, True, self.current_cursor_line,
                frozenset(self.selected_tools()),
            )
        return (self.last_render_signature, False, frozenset(self.selected_tools()))

    def _build_pick_cache(self):
        """화면에 실제로 그려진 경로만, 클릭 판정에 쓸 (세계좌표 선분, 도착
        지점의 src_line) 목록으로 미리 뽑아 둔다. 일반 모드에서는 필터로
        선택된 공정들의 정적 경로 전체가 대상이고, PG 매칭 모드에서는
        커서가 위치한 공정의 커서 이전(진행된) 구간만 대상이다 — 그 외
        구간이나 다른 공정의 경로는 화면에 보이지 않으므로 클릭으로 집혀서도
        안 된다(v1.5.7: 진행 중인 필터와 다른 값의 공구경로가 잘못 집히던
        문제 수정). set_source_text로 새로 그리거나 필터 선택/커서 위치가
        바뀌면 pick_source_line()이 자동으로 다시 만든다."""
        segments = []
        lines = []
        if self.pg_match_mode:
            current_tool = self.line_to_tool_map.get(self.current_cursor_line)
            if current_tool and current_tool in self.tool_paths and self._tool_selected(current_tool):
                self._collect_pick_segments(
                    self.tool_paths[current_tool], segments, lines,
                    line_limit=self.current_cursor_line,
                )
        else:
            selected = self.selected_tools()
            for tool, path_data in self.tool_paths.items():
                if tool not in selected:
                    continue
                self._collect_pick_segments(path_data, segments, lines)
        if segments:
            self._pick_world_pts = np.array(segments, dtype=np.float64)
            self._pick_src_lines = np.array(lines, dtype=np.int64)
        else:
            self._pick_world_pts = np.zeros((0, 2, 3), dtype=np.float64)
            self._pick_src_lines = np.zeros((0,), dtype=np.int64)
        self._pick_cache_key = self._pick_cache_scope_key()

    def pick_source_line(self, view_x, view_y, radius_px=None):
        """gl_view 위의 논리 픽셀 좌표 (view_x, view_y)에서 radius_px 안에 있는
        가장 가까운 경로 선분을 찾아 그 도착 지점의 src_line을 반환한다.
        없으면 None."""
        radius_px = self._PICK_RADIUS_PX if radius_px is None else radius_px
        key = self._pick_cache_scope_key()
        if key != self._pick_cache_key:
            self._build_pick_cache()
        if self._pick_world_pts.shape[0] == 0:
            return None

        viewport = self.gl_view.getViewport()
        width, height = max(1, viewport[2]), max(1, viewport[3])
        mvp = self.gl_view.projectionMatrix(viewport, viewport) * self.gl_view.viewMatrix()
        # QMatrix4x4는 열(column) 우선으로 저장되므로, column(i)들을 모아
        # 전치(.T)하면 통상적인 "M @ 열벡터" 규약의 4x4 행렬이 된다.
        cols = [mvp.column(i) for i in range(4)]
        m = np.array([[c.x(), c.y(), c.z(), c.w()] for c in cols]).T

        pts = self._pick_world_pts.reshape(-1, 3)
        ones = np.ones((pts.shape[0], 1), dtype=np.float64)
        homogeneous = np.concatenate([pts, ones], axis=1)
        mapped = homogeneous @ m.T
        w = mapped[:, 3]
        w_safe = np.where(w == 0, 1.0, w)
        ndc_x = mapped[:, 0] / w_safe
        ndc_y = mapped[:, 1] / w_safe
        screen_x = (ndc_x + 1.0) / 2.0 * width
        screen_y = (1.0 - ndc_y) / 2.0 * height
        screen = np.stack([screen_x, screen_y], axis=1).reshape(-1, 2, 2)

        p0, p1 = screen[:, 0, :], screen[:, 1, :]
        d = p1 - p0
        denom = d[:, 0] ** 2 + d[:, 1] ** 2
        denom_safe = np.where(denom == 0, 1.0, denom)
        t = np.clip(
            ((view_x - p0[:, 0]) * d[:, 0] + (view_y - p0[:, 1]) * d[:, 1]) / denom_safe,
            0.0, 1.0,
        )
        closest_x = p0[:, 0] + t * d[:, 0]
        closest_y = p0[:, 1] + t * d[:, 1]
        dist = np.sqrt((closest_x - view_x) ** 2 + (closest_y - view_y) ** 2)
        point_dist = np.sqrt((p0[:, 0] - view_x) ** 2 + (p0[:, 1] - view_y) ** 2)
        dist = np.where(denom == 0, point_dist, dist)

        best = int(np.argmin(dist))
        if dist[best] <= radius_px:
            return int(self._pick_src_lines[best])
        return None

    def _on_sensitivity_changed(self, percent):
        ratio = max(0.05, min(2.0, percent / 100.0))
        self.gl_view.navigation_sensitivity = ratio
        self.sensitivity_value_label.setText("%d%%" % percent)
        self.settings.setValue("navigation_sensitivity", ratio)

    def _on_alt_wheel_sensitivity(self, delta):
        # v1.6.0: 화면에서 Alt+휠로 감도 바를 조정한다. 슬라이더 값을 바꾸면
        # valueChanged가 _on_sensitivity_changed를 호출해 실제 감도 반영/저장까지
        # 기존 로직을 그대로 재사용한다.
        step = 5 if delta > 0 else -5
        new_value = self.sensitivity_slider.value() + step
        new_value = max(self.sensitivity_slider.minimum(), min(self.sensitivity_slider.maximum(), new_value))
        self.sensitivity_slider.setValue(new_value)

    def _on_view_cube_size_changed(self, size):
        self.view_cube_size_label.setText("%dpx" % size)
        self.settings.setValue("view_cube_size", size)
        if self.view_cube is not None:
            self.view_cube.setFixedSize(size, size)
            self.gl_view._reposition_overlay()
            self.view_cube.update()
        # v1.6.0: 원점 화살표 길이를 큐브 크기에 맞춰 다시 계산한다.
        self._add_axis_lines()

    def _refresh_dark_mode_button(self):
        # v1.6.3 버그 수정: 이 버튼은 v1.6.2부터 항상 앱 상단 바(top_bar) 위에
        # 있고, 그 상단 바 배경은 테마와 무관하게 항상 어두운 남색이다
        # (App._style_header_bar, header_bg는 light/dark 테마 모두 어두운
        # 값). 그런데도 아이콘 색을 테마(_dark_mode)에 따라 밝음/어두움으로
        # 바꾸고 있어서, 라이트 테마일 때 어두운 아이콘(#1f2937)이 똑같이
        # 어두운 상단 바 위에서 사실상 안 보였다(다크 테마일 때만 우연히
        # 밝은 아이콘이라 보였음). 이제 배경이 항상 어두우므로 아이콘 색도
        # 테마와 무관하게 항상 밝게 고정한다 — 모양(해/달)만 상태를 나타낸다.
        icon_color = "#f2f5fa"
        # v1.5.9: 아이콘이 잘 안 보인다는 요청으로 26px로 확대.
        # v1.6.1: 다시 정확히 2배인 52px로 확대(소스 픽스맵도 같이 키워야
        # 확대해도 흐려지지 않는다).
        # v1.6.2: 상단 바로 옮기며 다른 컨트롤과 같은 비율로 40% 줄인다.
        size = DARK_MODE_BUTTON_PX
        icon = sun_icon(icon_color, size=size) if self._dark_mode else moon_icon(icon_color, size=size)
        self.dark_mode_button.setIcon(icon)
        self.dark_mode_button.setIconSize(QSize(size, size))
        with QSignalBlocker(self.dark_mode_button):
            self.dark_mode_button.setChecked(self._dark_mode)

    def take_dark_mode_button(self, new_parent):
        """다크모드 버튼을 앱 상단 바(new_parent)로 옮긴다(v1.6.2 요청).

        호스트 App이 자기 top_bar 레이아웃에 이 버튼을 addWidget()하기 직전에
        호출한다 — setParent() 후에도 시그널 연결과 상태는 그대로 유지된다."""
        self.dark_mode_button.setParent(new_parent)
        self.dark_mode_button.show()
        return self.dark_mode_button

    def set_dark_mode(self, enabled):
        """App(NC_Tool_List.py)이 다크모드 토글 시(또는 시작 시 저장된 값으로)
        호출한다 — 이 위젯 자체는 상태를 저장하지 않고 항상 App이 넘겨주는
        값을 그대로 반영만 한다. 3D 캔버스 배경은 테마와 무관하게 항상
        어둡게 고정되어 있으므로(v1.5.7) 여기서는 토글 버튼 아이콘만 갱신한다."""
        self._dark_mode = bool(enabled)
        self._refresh_dark_mode_button()

    # v1.6.0: 원점 표기를 원점을 관통하는 양방향 무한선 대신, +X/+Y/+Z
    # 방향으로만 뻗는 화살표로 바꾼다.
    # v1.6.1: 길이를 큐브 크기(px) 자체와 "화면상 같은 크기"로 보이도록
    # 바꾼다 — 직교 투영에서는 화면 픽셀당 월드 단위가 화면 전체에서
    # 균일하므로, 큐브 크기(px)에 그 값을 곱하면 줌 정도와 무관하게
    # 화살표가 항상 큐브와 같은 픽셀 크기로 보인다.
    _AXIS_ARROW_HEAD_RATIO = 0.12
    _AXIS_LABELS = ("X", "Y", "Z")
    _AXIS_DIRECTIONS = (
        ((1.0, 0.0, 0.0), (1.0, 0.2, 0.2, 0.9), ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))),
        ((0.0, 1.0, 0.0), (0.2, 1.0, 0.2, 0.9), ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))),
        ((0.0, 0.0, 1.0), (0.2, 0.2, 1.0, 0.9), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))),
    )

    def _screen_units_per_pixel(self):
        opts = getattr(self.gl_view, "opts", None)
        if not opts:
            return 1.0
        try:
            distance = max(float(opts.get("distance", 200.0)), 1.0)
            fov = max(float(opts.get("fov", 60.0)), 1.0)
        except (TypeError, ValueError):
            return 1.0
        height_px = max(self.gl_view.height(), 1)
        return 2.0 * distance * tan(radians(fov) / 2.0) / height_px

    def _axis_cube_size_px(self):
        slider = getattr(self, "view_cube_size_slider", None)
        return slider.value() if slider is not None else self._initial_cube_size

    def _axis_arrow_length(self):
        return self._axis_cube_size_px() * self._screen_units_per_pixel()

    def _axis_label_font(self):
        # ViewCubeWidget._paint()의 면 라벨 폰트 크기와 같은 비율(큐브
        # half-extent의 7.2/26.0배)을 써서, 원점 화살표의 축 문자가 큐브
        # 라벨과 같은 크기로 보이고 큐브 크기 조정에 함께 반응하게 한다.
        cube_px = self._axis_cube_size_px()
        half = (cube_px / 2.0) * 0.65
        point_size = max(6.0, half * (7.2 / 26.0))
        font = QFont("맑은 고딕")
        font.setPointSizeF(point_size)
        return font

    def _remove_axis_lines(self):
        for item in getattr(self, "_axis_items", []):
            self.gl_view.removeItem(item)
        self._axis_items = []
        self._axis_label_items = []

    def _add_axis_lines(self):
        self._remove_axis_lines()
        length = self._axis_arrow_length()
        head_len = length * self._AXIS_ARROW_HEAD_RATIO
        font = self._axis_label_font()
        for (direction, color, wing_axes), label in zip(self._AXIS_DIRECTIONS, self._AXIS_LABELS):
            d = np.array(direction)
            tip = d * length
            # v1.6.1: 선 굵기를 기존의 2배로 키운다(2.0 -> 4.0).
            shaft = gl.GLLinePlotItem(
                pos=np.array([[0.0, 0.0, 0.0], tip]), color=color, width=4.0, antialias=True
            )
            self.gl_view.addItem(shaft)
            self._axis_items.append(shaft)
            # 화살촉: 끝점에서 진행 방향의 반대 + 옆(대각선) 방향으로 짧은
            # 선 4개를 그려 어느 각도에서 봐도 화살표처럼 보이게 한다.
            for wing_axis in wing_axes:
                w = np.array(wing_axis)
                for sign in (1.0, -1.0):
                    wing_dir = -d + sign * w
                    norm = np.linalg.norm(wing_dir)
                    if norm > 1e-9:
                        wing_dir = wing_dir / norm
                    head = gl.GLLinePlotItem(
                        pos=np.array([tip, tip + wing_dir * head_len]),
                        color=color, width=4.0, antialias=True,
                    )
                    self.gl_view.addItem(head)
                    self._axis_items.append(head)
            # v1.6.1: 화살표 끝에 X/Y/Z 축 문자를 표기한다.
            text_color = tuple(int(max(0.0, min(1.0, c)) * 255) for c in color[:3])
            label_pos = tip + d * (length * 0.06)
            text_item = gl.GLTextItem(pos=label_pos, text=label, color=text_color, font=font)
            self.gl_view.addItem(text_item)
            self._axis_items.append(text_item)
            self._axis_label_items.append(text_item)

    def _update_axis_lines_live(self):
        """카메라가 움직일 때(줌 포함) 호출된다. 화살표를 화면 고정
        크기로 유지하려면 매 프레임 좌표를 다시 계산해야 하므로, 아이템을
        지웠다 새로 만들지 않고 기존 아이템의 좌표만 갱신해 드래그 중
        끊김 없이 갱신한다."""
        axis_items = getattr(self, "_axis_items", None)
        label_items = getattr(self, "_axis_label_items", None)
        if not axis_items or not label_items:
            return
        length = self._axis_arrow_length()
        head_len = length * self._AXIS_ARROW_HEAD_RATIO
        font = self._axis_label_font()
        index = 0
        for (direction, _color, wing_axes), label_item in zip(self._AXIS_DIRECTIONS, label_items):
            d = np.array(direction)
            tip = d * length
            axis_items[index].setData(pos=np.array([[0.0, 0.0, 0.0], tip]))
            index += 1
            for wing_axis in wing_axes:
                w = np.array(wing_axis)
                for sign in (1.0, -1.0):
                    wing_dir = -d + sign * w
                    norm = np.linalg.norm(wing_dir)
                    if norm > 1e-9:
                        wing_dir = wing_dir / norm
                    axis_items[index].setData(pos=np.array([tip, tip + wing_dir * head_len]))
                    index += 1
            label_item.setData(pos=tip + d * (length * 0.06), font=font)
            # 문자 아이템도 axis_items 안의 한 칸을 차지하므로(shaft + 4개
            # 화살촉 + 문자 = 축 하나당 6개), 다음 축으로 넘어가기 전에
            # 인덱스를 그만큼 건너뛰어야 한다.
            index += 1

    def attach_tool_filter(self, list_widget):
        if self.tool_filter_list is not None:
            try:
                self.tool_filter_list.itemSelectionChanged.disconnect(self.update_visible_paths)
            except TypeError:
                pass
            try:
                self.tool_filter_list.itemClicked.disconnect(self._on_tool_filter_item_clicked)
            except TypeError:
                pass
        self.tool_filter_list = list_widget
        self.tool_filter_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.tool_filter_list.itemSelectionChanged.connect(self.update_visible_paths)
        # A user click (not a programmatic 전체/해제 selection) also jumps the program
        # editor to where that process starts.
        self.tool_filter_list.itemClicked.connect(self._on_tool_filter_item_clicked)
        self._refresh_tool_filter()

    def _on_tool_filter_item_clicked(self, item):
        process_key = item.data(Qt.UserRole)
        line_index = self.process_first_line.get(process_key)
        if line_index is not None:
            self.process_activated.emit(line_index)

    def set_tool_name_map(self, tool_name_map):
        self.tool_name_map = dict(tool_name_map or {})
        self._refresh_tool_filter(keep_selection=True)

    def set_source_text(self, text, tool_name_map=None):
        previous_tool_name_map = dict(self.tool_name_map)
        if tool_name_map is not None:
            self.tool_name_map = dict(tool_name_map)
        text = text or ""
        signature = self._render_signature(text)
        if signature == self.last_render_signature:
            if previous_tool_name_map != self.tool_name_map:
                self._refresh_tool_filter(keep_selection=True)
            self.set_cursor_line(self.current_cursor_line)
            return False
        self.last_source_text = text
        self.raw_lines = text.splitlines()
        self.process_nc_lines(self.raw_lines)
        self.last_render_signature = signature
        self.set_cursor_line(self.current_cursor_line)
        return True

    def clear(self):
        self.last_source_text = ""
        self.last_render_signature = None
        self.raw_lines = []
        self._clear_path_items()
        self.gl_view.scene_radius = 0.0
        self.tool_paths.clear()
        self.plot_items.clear()
        self.process_tool_map.clear()
        self.line_to_coord_map.clear()
        self.line_to_tool_map.clear()
        self.process_first_line.clear()
        self.modal_state_map.clear()
        self.current_cursor_line = 0
        self._refresh_tool_filter()
        self._set_coordinate_labels(("0.000",) * 6)

    def _render_signature(self, text):
        specs = tuple(sorted(self.machine_specs.get(self.current_machine_type, {}).items()))
        return (text, self.current_machine_type, specs)

    def machine_types(self):
        return list(self.machine_specs.keys())

    def machine_spec(self, machine_type=None):
        machine_type = machine_type or self.current_machine_type
        return dict(self.machine_specs.get(machine_type, {}))

    def set_machine_type(self, machine_type, init_camera=False):
        if machine_type not in self.machine_specs:
            return
        self.current_machine_type = machine_type
        if "선반" in machine_type:
            if init_camera:
                self.set_camera_projection("XZ")
                init_camera = False
        if init_camera:
            self.set_camera_projection("XY")
        self._save_machine_specs()
        if self.last_source_text:
            self.last_render_signature = None
            self.set_source_text(self.last_source_text)

    def update_machine_spec(self, machine_type, specs):
        if machine_type not in self.machine_specs:
            self.machine_specs[machine_type] = {}
        self.machine_specs[machine_type] = {
            str(key): str(value).strip() for key, value in specs.items()
        }
        self.set_machine_type(machine_type)

    # 뷰 큐브의 6개 면과 같은 각도 규약: elevation/azimuth는
    # GLViewWidget.cameraPosition()의 구면 좌표와 동일하게 해석된다.
    _VIEW_PROJECTIONS = {
        "ISO": (30, -45),
        "XY": (90, -90),
        "XZ": (0, -90),
        "YZ": (0, 0),
    }

    def set_camera_angles(self, elevation, azimuth, distance=None, recenter=False):
        """카메라 방향만 바꾼다. distance를 안 주면 현재 줌 배율을 유지한다.

        recenter=True면 카메라 중심(pos)을 원점으로 되돌려, 그동안 드래그로
        치우쳐 있던 좌표가 화면 정중앙으로 다시 온다(v1.6.2, ISO 버튼 요청)."""
        kwargs = {"elevation": elevation, "azimuth": azimuth}
        if distance is not None:
            kwargs["distance"] = distance
        if recenter:
            kwargs["pos"] = Vector(0, 0, 0)
        self.gl_view.setCameraPosition(**kwargs)

    # v1.6.3: 투영 버튼을 누르면 경로 전체가 화면 안에 들어오도록 거리도
    # 함께 맞춘다(줌 전체 보기). 여유 배율(경로가 화면 가장자리에 딱 붙지
    # 않게) — 값이 클수록 더 축소되어 보인다.
    _ZOOM_TO_FIT_MARGIN = 1.25
    _ZOOM_TO_FIT_FALLBACK_DISTANCE = 200

    def _zoom_to_fit_distance(self):
        """현재 로드된 경로 전체(gl_view.scene_radius)가 화면 안에 다 들어오는
        카메라 거리를 계산한다. 경로가 없으면(반지름 0) None을 반환해
        호출자가 고정 기본값(200)을 쓰게 한다."""
        view = self.gl_view
        radius = getattr(view, "scene_radius", 0.0) or 0.0
        if radius <= 0.0:
            return None
        width = max(float(view.width()), 1.0)
        height = max(float(view.height()), 1.0)
        aspect = width / height
        fov = max(float(view.opts.get("fov", 60.0)), 1.0)
        half_tan = tan(radians(fov) / 2.0)
        # 세로/가로 중 더 좁은 쪽(aspect와 1 중 작은 값)에 맞춰 거리를 정해야
        # 두 방향 모두 경로가 화면 밖으로 벗어나지 않는다.
        limiting_ratio = min(1.0, aspect)
        distance = radius / (half_tan * limiting_ratio) * self._ZOOM_TO_FIT_MARGIN
        return max(distance, 10.0)

    def set_camera_projection(self, view_type):
        preset = self._VIEW_PROJECTIONS.get(view_type)
        if preset is None:
            return
        elevation, azimuth = preset
        # v1.6.3: ISO뿐 아니라 4개 투영 버튼 전부 같은 동작 — 좌표를 화면
        # 중앙으로 되돌리고(recenter), 로드된 경로 전체가 한눈에 들어오도록
        # 자동으로 줌 아웃/인 한다(경로가 없으면 기존 고정값 200을 쓴다).
        distance = self._zoom_to_fit_distance() or self._ZOOM_TO_FIT_FALLBACK_DISTANCE
        self.set_camera_angles(elevation, azimuth, distance=distance, recenter=True)

    def _clear_path_items(self):
        for item_list in self.plot_items.values():
            for item in item_list:
                self.gl_view.removeItem(item)
        self._clear_dynamic_trace_items()
        self.cursor_sphere.setVisible(False)

    def _clear_dynamic_trace_items(self):
        for item in self.dynamic_trace_items:
            self.gl_view.removeItem(item)
        self.dynamic_trace_items = []

    def _normalize_tool_no(self, value):
        try:
            return "T%02d" % int(value)
        except (TypeError, ValueError):
            return ""

    def _make_process_key(self, process_no, tool_no):
        return "P%03d_%s" % (process_no, tool_no or "T00")

    def _code_without_comments(self, line):
        code = str(line or "").split(";", 1)[0]
        return re.sub(r"\([^()]*\)", "", code)

    def _tool_display_text(self, process_key):
        tool_no = self.process_tool_map.get(process_key)
        if not tool_no:
            return "초기 구간"
        match = re.search(r"T(\d+)", tool_no, re.I)
        if not match:
            return "공정 | %s | 이름 없음" % tool_no
        number = int(match.group(1))
        normalized_tool_no = "T%02d" % number
        name = (
            self.tool_name_map.get(normalized_tool_no)
            or self.tool_name_map.get("T%d" % number)
            or self.tool_name_map.get(str(number))
            or "이름 없음"
        )
        process_match = re.match(r"P(\d+)_", process_key)
        process_label = "공정 %02d" % int(process_match.group(1)) if process_match else "공정"
        return "%s | %s | %s" % (process_label, normalized_tool_no, name)

    def _refresh_tool_filter(self, keep_selection=False):
        if self.tool_filter_list is None:
            return
        selected = set()
        if keep_selection:
            for item in self.tool_filter_list.selectedItems():
                selected.add(item.data(Qt.UserRole))
        with QSignalBlocker(self.tool_filter_list):
            self.tool_filter_list.clear()
            for idx, tool in enumerate(self.tool_paths):
                item = QListWidgetItem(color_chip_icon(tool_color_for_index(idx)), self._tool_display_text(tool))
                item.setData(Qt.UserRole, tool)
                self.tool_filter_list.addItem(item)
                if not keep_selection or tool in selected:
                    item.setSelected(True)
        self.update_visible_paths()

    def select_all_tools(self, selected=True):
        if self.tool_filter_list is None:
            return
        with QSignalBlocker(self.tool_filter_list):
            for row in range(self.tool_filter_list.count()):
                self.tool_filter_list.item(row).setSelected(selected)
        self.update_visible_paths()

    def get_rotation_matrix(self, i_deg, j_deg, k_deg):
        rad_i = np.radians(i_deg)
        rad_j = np.radians(j_deg)
        rad_k = np.radians(k_deg)
        r_i = np.array([[1, 0, 0], [0, np.cos(rad_i), -np.sin(rad_i)], [0, np.sin(rad_i), np.cos(rad_i)]])
        r_j = np.array([[np.cos(rad_j), 0, np.sin(rad_j)], [0, 1, 0], [-np.sin(rad_j), 0, np.cos(rad_j)]])
        r_k = np.array([[np.cos(rad_k), -np.sin(rad_k), 0], [np.sin(rad_k), np.cos(rad_k), 0], [0, 0, 1]])
        return r_k @ r_j @ r_i

    def get_5axis_rotation_matrix(self, machine_type, i_deg, j_deg, k_deg):
        if "5축 밀링 (A to C)" in machine_type:
            rad_a = np.radians(j_deg)
            rad_c = np.radians(i_deg)
            rad_k = np.radians(k_deg)
            r_a = np.array([[1, 0, 0], [0, np.cos(rad_a), -np.sin(rad_a)], [0, np.sin(rad_a), np.cos(rad_a)]])
            r_c = np.array([[np.cos(rad_c), -np.sin(rad_c), 0], [np.sin(rad_c), np.cos(rad_c), 0], [0, 0, 1]])
            r_k = np.array([[np.cos(rad_k), -np.sin(rad_k), 0], [np.sin(rad_k), np.cos(rad_k), 0], [0, 0, 1]])
            return r_k @ r_c @ r_a
        return self.get_rotation_matrix(i_deg, j_deg, k_deg)

    def process_nc_lines(self, lines):
        self._clear_path_items()
        self.tool_paths.clear()
        self.plot_items.clear()
        self.process_tool_map.clear()
        self.line_to_coord_map.clear()
        self.line_to_tool_map.clear()
        self.process_first_line.clear()
        self.modal_state_map.clear()

        machine_type = self.current_machine_type
        is_lathe = "선반" in machine_type
        is_4axis = "4축" in machine_type
        is_5axis_ac = "5축 밀링 (A to C)" in machine_type
        is_5axis_bc = "5축 밀링 (B to C)" in machine_type

        try:
            m_x = float(self.machine_specs[machine_type].get("X 행정", "500")) / 2.0
            m_y = float(self.machine_specs[machine_type].get("Y 행정", "500")) / 2.0
            m_z = float(self.machine_specs[machine_type].get("Z 행정", "500"))
        except (TypeError, ValueError):
            m_x, m_y, m_z = 250.0, 250.0, 300.0

        current_tool = "Initial"
        self.tool_paths[current_tool] = []
        self.process_tool_map[current_tool] = ""
        self.process_first_line[current_tool] = 0

        cx, cy, cz = 0.0, 0.0, 0.0
        cc_deg = 0.0
        cb_deg = 0.0
        modal_values = ["0.000", "0.000", "0.000", "0.000", "0.000", "0.000"]

        g43_active = False
        current_motion = "G00"
        current_plane = "G17"
        polar_interpolation = False
        g68_pending = False
        pending_i, pending_j, pending_k = 0.0, 0.0, 0.0
        active_matrix = np.eye(3)
        g98_active = False
        cycle_active = False
        detected_t = ""
        process_no = 0

        t_pattern = re.compile(r"T0*(\d+)")
        m6_pattern = re.compile(r"M0?6(?!\d)")
        x_pattern = re.compile(r"X\s*([+-]?\d*\.?\d+)")
        y_pattern = re.compile(r"Y\s*([+-]?\d*\.?\d+)")
        z_pattern = re.compile(r"Z\s*([+-]?\d*\.?\d+)")
        a_pattern = re.compile(r"A\s*([+-]?\d*\.?\d+)")
        b_pattern = re.compile(r"B\s*([+-]?\d*\.?\d+)")
        c_pattern = re.compile(r"C\s*([+-]?\d*\.?\d+)")
        g28_pattern = re.compile(r"G28")
        g91_pattern = re.compile(r"G91")
        g68_pattern = re.compile(r"G68\.2")
        g69_pattern = re.compile(r"G69")
        g53_1_pattern = re.compile(r"G53\.1")
        g12_1_pattern = re.compile(r"G12\.1|G112")
        g13_1_pattern = re.compile(r"G13\.1|G113")
        motion_pattern = re.compile(r"(G0[0-3]|G[0-3])(?![\.\d])")
        g17_pattern = re.compile(r"G17(?!\d)")
        g18_pattern = re.compile(r"G18(?!\d)")
        g19_pattern = re.compile(r"G19(?!\d)")
        i_pattern = re.compile(r"I\s*([+-]?\d*\.?\d+)")
        j_pattern = re.compile(r"J\s*([+-]?\d*\.?\d+)")
        k_pattern = re.compile(r"K\s*([+-]?\d*\.?\d+)")
        r_pattern = re.compile(r"R\s*([+-]?\d*\.?\d+)")
        g43_pattern = re.compile(r"G43")
        g49_pattern = re.compile(r"G49")
        g98_pattern = re.compile(r"G98")
        g99_pattern = re.compile(r"G99")
        cycle_pattern = re.compile(r"(G81|G83|G85|G73|G84|G80)")

        for idx, line in enumerate(lines):
            line_upper_with_comments = line.upper().replace(" ", "")
            line_upper = self._code_without_comments(line).upper().replace(" ", "")

            for pos, pattern in enumerate((x_pattern, y_pattern, z_pattern, a_pattern, b_pattern, c_pattern)):
                match = pattern.search(line_upper)
                if match:
                    modal_values[pos] = match.group(1)
            self.modal_state_map[idx] = tuple(modal_values)

            comment_t_match = t_pattern.search(line_upper_with_comments)
            if comment_t_match:
                detected_t = self._normalize_tool_no(comment_t_match.group(1))

            if not line_upper:
                self.line_to_tool_map[idx] = current_tool
                continue

            self.line_to_tool_map[idx] = current_tool

            if g17_pattern.search(line_upper):
                current_plane = "G17"
            elif g18_pattern.search(line_upper):
                current_plane = "G18"
            elif g19_pattern.search(line_upper):
                current_plane = "G19"

            if g12_1_pattern.search(line_upper):
                polar_interpolation = True
                continue
            if g13_1_pattern.search(line_upper):
                polar_interpolation = False
                continue

            if g43_pattern.search(line_upper):
                g43_active = True
            if g49_pattern.search(line_upper):
                g43_active = False
                continue

            if g98_pattern.search(line_upper):
                g98_active = True
                current_motion = "G98"
            elif g99_pattern.search(line_upper):
                g98_active = False

            cycle_match = cycle_pattern.search(line_upper)
            if cycle_match:
                cycle_code = cycle_match.group(1)
                cycle_active = cycle_code != "G80"
                current_motion = cycle_code

            t_match = t_pattern.search(line_upper)
            if t_match:
                detected_t = self._normalize_tool_no(t_match.group(1))

            if m6_pattern.search(line_upper):
                process_no += 1
                current_tool = self._make_process_key(process_no, detected_t)
                self.tool_paths[current_tool] = []
                self.process_tool_map[current_tool] = detected_t
                self.process_first_line[current_tool] = idx
                self.tool_paths[current_tool].append({
                    "pt": [cx, cy, cz], "type": current_motion, "valid": g43_active, "src_line": idx,
                })
                self.line_to_tool_map[idx] = current_tool

            motion_match = motion_pattern.search(line_upper)
            if motion_match and not cycle_active:
                mot = motion_match.group(1)
                if mot in ("G0", "G00"):
                    current_motion = "G00"
                elif mot in ("G1", "G01"):
                    current_motion = "G01"
                elif mot in ("G2", "G02"):
                    current_motion = "G02"
                elif mot in ("G3", "G03"):
                    current_motion = "G03"

            if is_5axis_ac or is_5axis_bc:
                if g69_pattern.search(line_upper):
                    active_matrix = np.eye(3)
                    g68_pending = False
                elif g68_pattern.search(line_upper):
                    g68_pending = True
                    i_m = i_pattern.search(line_upper)
                    j_m = j_pattern.search(line_upper)
                    k_m = k_pattern.search(line_upper)
                    pending_i = float(i_m.group(1)) if i_m else 0.0
                    pending_j = float(j_m.group(1)) if j_m else 0.0
                    pending_k = float(k_m.group(1)) if k_m else 0.0

                if g53_1_pattern.search(line_upper) and g68_pending:
                    active_matrix = self.get_5axis_rotation_matrix(
                        machine_type, pending_i, pending_j, pending_k
                    )
                    g68_pending = False

            if is_4axis:
                b_m = b_pattern.search(line_upper)
                if b_m:
                    cb_deg = float(b_m.group(1))
                    rad_b = np.radians(cb_deg)
                    active_matrix = np.array([
                        [np.cos(rad_b), 0, np.sin(rad_b)],
                        [0, 1, 0],
                        [-np.sin(rad_b), 0, np.cos(rad_b)],
                    ])

            if g28_pattern.search(line_upper) and g91_pattern.search(line_upper):
                if re.search(r"X\s*0", line_upper):
                    cx = m_x
                if re.search(r"Y\s*0", line_upper):
                    cy = m_y
                if re.search(r"Z\s*0", line_upper):
                    cz = m_z
                if g43_active or is_lathe:
                    final_pt = [cx, cy, cz]
                    self.tool_paths[current_tool].append({
                        "pt": final_pt, "type": "G00", "valid": True, "src_line": idx,
                    })
                    self.line_to_coord_map[idx] = final_pt
                continue

            x_match = x_pattern.search(line_upper)
            y_match = y_pattern.search(line_upper)
            z_match = z_pattern.search(line_upper)
            c_match = c_pattern.search(line_upper)
            r_cycle_match = r_pattern.search(line_upper)

            # A full-circle arc (e.g. "G02 I50 J0") carries no X/Y/Z word at all, so it needs
            # its own entry into this block. Guard against G68.2/G53.1 tilt-plane lines, which
            # reuse I/J/K for an unrelated rotation vector while current_motion is still
            # modally G02/G03 from an earlier line.
            is_arc_motion = current_motion in ("G02", "G03")
            arc_center_present = (
                is_arc_motion
                and not (g68_pattern.search(line_upper) or g53_1_pattern.search(line_upper))
                and (i_pattern.search(line_upper) or j_pattern.search(line_upper) or k_pattern.search(line_upper))
            )

            if x_match or y_match or z_match or c_match or (cycle_active and r_cycle_match) or arc_center_present:
                start_pt = [cx, cy, cz]

                if is_lathe:
                    if x_match:
                        cx = float(x_match.group(1)) * 0.5
                    if y_match:
                        cy = float(y_match.group(1))
                    if z_match:
                        cz = float(z_match.group(1))
                    if c_match:
                        cc_deg = float(c_match.group(1))

                    if polar_interpolation:
                        target_pt = [cx, cc_deg, cz]
                    elif cc_deg != 0.0:
                        rad_c = np.radians(cc_deg)
                        target_pt = [
                            cx * np.cos(rad_c) - cy * np.sin(rad_c),
                            cx * np.sin(rad_c) + cy * np.cos(rad_c),
                            cz,
                        ]
                    else:
                        target_pt = [cy, cx, cz]
                    local_target_pt = target_pt
                else:
                    if x_match:
                        cx = float(x_match.group(1))
                    if y_match:
                        cy = float(y_match.group(1))
                    if z_match:
                        cz = float(z_match.group(1))
                    # Keep the pre-rotation ("local") point around so arcs can be built in the
                    # same unrotated coordinate space as start_pt, then rotate the whole arc as
                    # a batch below — mixing an unrotated start with a rotated end (as before)
                    # produced garbled 4/5-axis arcs.
                    local_target_pt = [cx, cy, cz]
                    coord_vec = np.array(local_target_pt)
                    target_pt = (
                        active_matrix @ coord_vec
                    ).tolist() if (is_5axis_ac or is_5axis_bc or is_4axis) else list(local_target_pt)

                if cycle_active and (g43_active or is_lathe):
                    target_x = cx
                    target_y = cy
                    target_z = float(z_match.group(1)) if z_match else cz
                    r_val = float(r_cycle_match.group(1)) if r_cycle_match else start_pt[2]
                    raw_points = (
                        np.array([target_x, target_y, start_pt[2]]),
                        np.array([target_x, target_y, r_val]),
                        np.array([target_x, target_y, target_z]),
                        np.array([target_x, target_y, start_pt[2]]),
                    )
                    if is_5axis_ac or is_5axis_bc:
                        xy_approach_pt, r_point_pt, final_z_pt, return_pt = [
                            (active_matrix @ raw).tolist() for raw in raw_points
                        ]
                    else:
                        xy_approach_pt, r_point_pt, final_z_pt, return_pt = [
                            raw.tolist() for raw in raw_points
                        ]
                    self.tool_paths[current_tool].append({"pt": xy_approach_pt, "type": "G00", "valid": True, "src_line": idx})
                    self.tool_paths[current_tool].append({"pt": r_point_pt, "type": "G00", "valid": True, "src_line": idx})
                    self.tool_paths[current_tool].append({"pt": final_z_pt, "type": "G01", "valid": True, "src_line": idx})
                    if g98_active:
                        self.tool_paths[current_tool].append({"pt": return_pt, "type": "G00", "valid": True, "src_line": idx})
                    cz = target_z
                    self.line_to_coord_map[idx] = final_z_pt
                    continue

                if is_arc_motion and is_lathe:
                    # Lathe target_pt is already in the lathe's own (cylindrical/XY-style)
                    # space with no rotation matrix involved, so the original single-space
                    # arc computation is still correct here — left untouched.
                    arc_pts = self._arc_points(
                        line_upper, start_pt, target_pt, current_motion, "G17",
                        i_pattern, j_pattern, k_pattern, r_pattern,
                    )
                    for pt in arc_pts:
                        self.tool_paths[current_tool].append({
                            "pt": pt, "type": current_motion, "valid": True, "src_line": idx,
                        })
                    self.line_to_coord_map[idx] = target_pt
                elif is_arc_motion:
                    local_arc_pts = self._arc_points(
                        line_upper, start_pt, local_target_pt, current_motion, current_plane,
                        i_pattern, j_pattern, k_pattern, r_pattern,
                    )
                    point_valid = g43_active
                    last_pt = None
                    for local_pt in local_arc_pts:
                        rotated_pt = (
                            (active_matrix @ np.array(local_pt)).tolist()
                            if (is_5axis_ac or is_5axis_bc or is_4axis) else local_pt
                        )
                        self.tool_paths[current_tool].append({
                            "pt": rotated_pt, "type": current_motion, "valid": point_valid, "src_line": idx,
                        })
                        last_pt = rotated_pt
                    if point_valid:
                        self.line_to_coord_map[idx] = last_pt if last_pt is not None else target_pt
                else:
                    self.tool_paths[current_tool].append({
                        "pt": target_pt,
                        "type": current_motion,
                        "valid": True if is_lathe else g43_active,
                        "src_line": idx,
                    })
                    if g43_active or is_lathe:
                        self.line_to_coord_map[idx] = target_pt

        self.tool_paths = {key: value for key, value in self.tool_paths.items() if value}
        self.process_tool_map = {
            key: value for key, value in self.process_tool_map.items()
            if key in self.tool_paths
        }
        self._build_path_items()
        self._refresh_tool_filter()
        self.set_cursor_line(self.current_cursor_line)

    def _arc_points(self, line_upper, start_pt, target_pt, current_motion, plane,
                     i_pattern, j_pattern, k_pattern, r_pattern):
        """Interpolate a G02/G03 arc in the given plane (G17/G18/G19).

        Returns points in the SAME coordinate space as start_pt/target_pt — the caller is
        responsible for rotating the result if it needs to live in a 4/5-axis rotated frame.
        The third (out-of-plane) axis is interpolated linearly, so this also covers helical
        moves that change Z (or the plane's equivalent) while arcing.
        """
        u_idx, v_idx, w_idx, u_letter, v_letter = ARC_PLANE_AXES.get(plane, ARC_PLANE_AXES["G17"])
        offset_patterns = {"i": i_pattern, "j": j_pattern, "k": k_pattern}
        u_match = offset_patterns[u_letter].search(line_upper)
        v_match = offset_patterns[v_letter].search(line_upper)
        u_off = float(u_match.group(1)) if u_match else 0.0
        v_off = float(v_match.group(1)) if v_match else 0.0

        start_u, start_v, start_w = start_pt[u_idx], start_pt[v_idx], start_pt[w_idx]
        target_u, target_v, target_w = target_pt[u_idx], target_pt[v_idx], target_pt[w_idx]

        center_u = start_u + u_off
        center_v = start_v + v_off

        r_match = r_pattern.search(line_upper)
        if r_match:
            radius_spec = float(r_match.group(1))
            du = target_u - start_u
            dv = target_v - start_v
            dist = np.hypot(du, dv)
            if dist > 0:
                h = np.sqrt(max(0.0, radius_spec ** 2 - (dist / 2) ** 2))
                sign = 1 if (current_motion == "G03" if radius_spec > 0 else current_motion == "G02") else -1
                center_u = start_u + du / 2 - sign * h * (dv / dist)
                center_v = start_v + dv / 2 + sign * h * (du / dist)

        radius_start = np.hypot(start_u - center_u, start_v - center_v)
        radius_end = np.hypot(target_u - center_u, target_v - center_v)
        radius = (radius_start + radius_end) / 2.0
        if radius <= 1e-9:
            # Degenerate spec (I/J/K/R all resolve to zero radius) — nothing sensible to draw.
            point = [0.0, 0.0, 0.0]
            point[u_idx], point[v_idx], point[w_idx] = target_u, target_v, target_w
            return [point]

        angle_start = np.arctan2(start_v - center_v, start_u - center_u)
        angle_end = np.arctan2(target_v - center_v, target_u - center_u)
        if current_motion == "G02" and angle_end >= angle_start:
            angle_end -= 2 * np.pi
        elif current_motion == "G03" and angle_end <= angle_start:
            angle_end += 2 * np.pi
        delta_angle = angle_end - angle_start

        # Chord-error-based adaptive resolution: bigger arcs get finer angular steps so the
        # rendered chord never strays far from the true circle, small arcs get coarser steps
        # (clamped by ARC_MIN_SEGMENTS below) so point count stays bounded either way.
        if radius > ARC_CHORD_TOLERANCE_MM:
            max_step = 2 * np.arccos(max(-1.0, 1.0 - ARC_CHORD_TOLERANCE_MM / radius))
        else:
            max_step = np.pi / 6
        segments = int(np.ceil(abs(delta_angle) / max_step)) + 1 if max_step > 0 else ARC_MIN_SEGMENTS
        segments = max(ARC_MIN_SEGMENTS, min(ARC_MAX_SEGMENTS, segments))

        angles = np.linspace(angle_start, angle_end, segments)
        points = []
        last_index = segments - 1
        for step, angle in enumerate(angles[1:], start=1):
            ratio = step / last_index
            point = [0.0, 0.0, 0.0]
            if step == last_index:
                # Snap the final point to the commanded target exactly, rather than the
                # parametric circle formula, so small I/J rounding never leaves a visible gap
                # to the next segment.
                point[u_idx], point[v_idx] = target_u, target_v
            else:
                point[u_idx] = center_u + np.cos(angle) * radius
                point[v_idx] = center_v + np.sin(angle) * radius
            point[w_idx] = start_w + (target_w - start_w) * ratio
            points.append(point)
        return points

    def _build_path_items(self):
        self.gl_view.scene_radius = self._compute_scene_radius()
        for idx, (tool, path_data) in enumerate(self.tool_paths.items()):
            base_color = tool_color_for_index(idx)
            self.plot_items[tool] = []
            for motion_type, pts_list in self._render_segment_buckets(path_data).items():
                self.create_segment_item(tool, pts_list, motion_type, base_color)

    def _compute_scene_radius(self):
        """모든 경로 점을 감싸는 구의 반지름(원점 기준). 경로가 없으면 0을
        반환해 projectionMatrix()가 거리 기반 기본값으로 되돌아가게 한다."""
        max_sq = 0.0
        for path_data in self.tool_paths.values():
            for node in path_data:
                if not node.get("valid"):
                    continue
                pt = node.get("pt")
                if pt is None:
                    continue
                sq = float(pt[0]) ** 2 + float(pt[1]) ** 2 + float(pt[2]) ** 2
                if sq > max_sq:
                    max_sq = sq
        return max_sq ** 0.5

    def create_segment_item(self, tool, pts_list, motion_type, base_color):
        if len(pts_list) < 2:
            return
        pts = np.array(pts_list, dtype=np.float32)
        if motion_type == "G00":
            color = RAPID_MOVE_COLOR + [RAPID_MOVE_ALPHA]
            width = 1.5
        else:
            color = [base_color[0], base_color[1], base_color[2], 1.0]
            width = 2.5
        line_item = gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True, mode="lines")
        self.gl_view.addItem(line_item)
        self.plot_items[tool].append(line_item)

    def _render_segments(self, path_data, line_limit=None):
        current_seg = []
        current_type = None
        previous_node = None
        for node in path_data:
            if line_limit is not None and node.get("src_line", -1) > line_limit:
                break
            if not node["valid"]:
                if current_seg:
                    yield current_seg, current_type
                current_seg = []
                current_type = None
                previous_node = None
                continue
            if previous_node is None:
                previous_node = node
                continue

            motion_type = node["type"]
            if current_type is not None and motion_type == current_type:
                current_seg.append(node["pt"])
            else:
                if current_seg:
                    yield current_seg, current_type
                current_seg = [previous_node["pt"], node["pt"]]
                current_type = motion_type
            previous_node = node
        if current_seg:
            yield current_seg, current_type

    def _render_segment_buckets(self, path_data, line_limit=None):
        buckets = {"G00": [], "CUT": []}
        for pts_list, motion_type in self._render_segments(path_data, line_limit):
            if len(pts_list) < 2:
                continue
            key = "G00" if motion_type == "G00" else "CUT"
            for index in range(1, len(pts_list)):
                buckets[key].append(pts_list[index - 1])
                buckets[key].append(pts_list[index])
        return buckets

    def selected_tools(self):
        if self.tool_filter_list is None:
            return set(self.plot_items)
        return {item.data(Qt.UserRole) for item in self.tool_filter_list.selectedItems()}

    def _tool_selected(self, tool):
        return tool in self.selected_tools()

    def set_pg_match_mode(self, enabled):
        """정적 경로를 숨기고 커서 공정의 실시간 트레이스만 남기는 모드를 토글한다."""
        self.pg_match_mode = bool(enabled)
        if self.playback_bar is not None:
            self.playback_bar.setEnabled(self.pg_match_mode)
        # update_visible_paths()가 끝에서 set_cursor_line()을 부르므로 트레이스도 함께 갱신된다.
        self.update_visible_paths()

    def update_visible_paths(self):
        selected_items = self.selected_tools()
        for tool, plot_item_list in self.plot_items.items():
            visible = (not self.pg_match_mode) and (tool in selected_items)
            for item in plot_item_list:
                item.setVisible(visible)
        self.set_cursor_line(self.current_cursor_line)

    def update_trace_item(self, index, pts_list, motion_type, base_color):
        if len(pts_list) < 2:
            return False
        pts = np.array(pts_list, dtype=np.float32)
        if motion_type == "G00":
            color = RAPID_MOVE_COLOR + [RAPID_MOVE_ALPHA]
            width = 1.5
        else:
            color = [base_color[0], base_color[1], base_color[2], 1.0]
            width = 3.5
        if index < len(self.dynamic_trace_items):
            item = self.dynamic_trace_items[index]
            item.setData(pos=pts, color=color, width=width)
            item.setVisible(True)
        else:
            item = gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True, mode="lines")
            self.gl_view.addItem(item)
            self.dynamic_trace_items.append(item)
        return True

    def _hide_dynamic_trace_from(self, start_index=0):
        empty = np.empty((0, 3), dtype=np.float32)
        for item in self.dynamic_trace_items[start_index:]:
            item.setData(pos=empty)
            item.setVisible(False)

    def set_cursor_line(self, line_index):
        try:
            line_index = max(0, int(line_index))
        except (TypeError, ValueError):
            line_index = 0
        self.current_cursor_line = line_index

        modal_values = self.modal_state_map.get(line_index)
        if modal_values:
            self._set_coordinate_labels(modal_values)

        current_tool = self.line_to_tool_map.get(line_index)
        current_pt = self.line_to_coord_map.get(line_index)
        if current_tool and current_pt is not None and self._tool_selected(current_tool):
            self.cursor_sphere.resetTransform()
            self.cursor_sphere.translate(current_pt[0], current_pt[1], current_pt[2])
            self.cursor_sphere.setVisible(True)
        else:
            self.cursor_sphere.setVisible(False)

        if not current_tool or current_tool not in self.tool_paths or not self._tool_selected(current_tool):
            self._hide_dynamic_trace_from(0)
            return

        try:
            tool_index = list(self.tool_paths.keys()).index(current_tool)
        except ValueError:
            tool_index = 0
        base_color = tool_color_for_index(tool_index)
        trace_index = 0
        for motion_type, pts_list in self._render_segment_buckets(
            self.tool_paths[current_tool], line_index
        ).items():
            if self.update_trace_item(trace_index, pts_list, motion_type, base_color):
                trace_index += 1
        self._hide_dynamic_trace_from(trace_index)

    def _set_coordinate_labels(self, values):
        for axis, value in zip(("X", "Y", "Z", "A", "B", "C"), values):
            label = self.coord_labels.get(axis)
            if label is not None:
                label.setText(str(value))
