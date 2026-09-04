# -*- coding: utf-8 -*-
"""Embedded PyQt 3D NC path viewer widget."""
import json
from math import radians, tan
import re

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtCore import Qt, QPointF, QRectF, QSettings, QSignalBlocker, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QColor, QIcon, QMatrix4x4, QPainter, QPen, QPixmap, QPolygonF, QVector3D,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


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


class OrthographicGLViewWidget(gl.GLViewWidget):
    """GL viewer that keeps 3D navigation but removes perspective distortion."""

    # Fired after every mouse-drag orbit/pan, wheel zoom, or setCameraPosition() call
    # so an overlay (e.g. ViewCubeWidget) can repaint itself to match.
    camera_changed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_orthographic_projection = True
        # Multiplies mouse-drag/wheel movement before it reaches pyqtgraph's own
        # orbit/pan/zoom handling. 1.0 = library default; lower = less sensitive.
        self.navigation_sensitivity = 1.0
        self.overlay_widget = None
        self.bottom_bar_widget = None
        # pyqtgraph's GLViewWidget defaults to ClickFocus and steals arrow keys for
        # camera orbit (its own keyPressEvent) the moment this widget is clicked,
        # which silently breaks program-cursor arrow-key stepping. Keyboard focus
        # must always stay on the program editor.
        self.setFocusPolicy(Qt.NoFocus)

    def mouseMoveEvent(self, ev):
        lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
        if not hasattr(self, 'mousePos'):
            self.mousePos = lpos
        # pyqtgraph's own handler computes diff = lpos - self.mousePos and then
        # overwrites self.mousePos with the true lpos. Pulling the stored point
        # toward lpos by (1 - sensitivity) shrinks that diff without touching
        # pyqtgraph's orbit()/pan() math, so it keeps working across library versions.
        self.mousePos = lpos - (lpos - self.mousePos) * self.navigation_sensitivity
        super().mouseMoveEvent(ev)
        self.camera_changed.emit()

    def wheelEvent(self, ev):
        delta = ev.angleDelta().x()
        if delta == 0:
            delta = ev.angleDelta().y()
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

    def _reposition_bottom_bar(self):
        """Keeps the playback bar centered near the bottom, 70% of the view's width."""
        if self.bottom_bar_widget is None:
            return
        bar = self.bottom_bar_widget
        width = max(200, round(self.width() * 0.7))
        bar.setFixedWidth(width)
        height = bar.sizeHint().height()
        margin_bottom = 16
        # Anchored between the view's vertical center and its bottom edge.
        y = round(self.height() * 0.5 + (self.height() * 0.5 - height) / 2)
        y = min(y, self.height() - height - margin_bottom)
        bar.move((self.width() - width) // 2, max(0, y))

    def _reposition_overlay(self):
        if self.overlay_widget is None:
            return
        margin = 10
        self.overlay_widget.move(
            max(0, self.width() - self.overlay_widget.width() - margin), margin
        )

    def projectionMatrix(self, region, viewport):
        if not self.use_orthographic_projection:
            return super().projectionMatrix(region, viewport)

        x0, y0, width, height = viewport
        width = max(float(width), 1.0)
        height = max(float(height), 1.0)
        distance = max(float(self.opts.get("distance", 200.0)), 1.0)
        fov = max(float(self.opts.get("fov", 60.0)), 1.0)
        near_clip = distance * 0.001
        far_clip = distance * 1000.0
        view_height = 2.0 * distance * tan(0.5 * radians(fov))
        view_width = view_height * width / height

        left = view_width * ((region[0] - x0) / width - 0.5)
        right = view_width * ((region[0] + region[2] - x0) / width - 0.5)
        bottom = view_height * ((region[1] - y0) / height - 0.5)
        top = view_height * ((region[1] + region[3] - y0) / height - 0.5)

        transform = QMatrix4x4()
        transform.ortho(left, right, bottom, top, near_clip, far_clip)
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
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip('드래그: 회전 | 면 클릭: 해당 뷰로 전환')

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
        font = painter.font()
        font.setPointSizeF(max(6.0, half * (9.0 / 26.0)))
        painter.setFont(font)

        max_depth = max((depth for depth, *_ in faces), default=1.0) or 1.0
        for depth, polygon, cx_face, cy_face, _elev, _azim, label in faces:
            facing = depth > 0.05 * max_depth
            painter.setPen(QPen(QColor(55, 65, 80), pen_width))
            painter.setBrush(QBrush(QColor(120, 165, 210) if facing else QColor(72, 80, 94)))
            painter.drawPolygon(polygon)
            painter.setPen(QColor(255, 255, 255) if facing else QColor(150, 155, 165))
            painter.drawText(
                QRectF(cx_face - label_half_w, cy_face - label_half_h,
                       label_half_w * 2.0, label_half_h * 2.0),
                Qt.AlignCenter, label,
            )

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
        super().mousePressEvent(event)


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
        self.setStyleSheet(
            "PlaybackBarWidget { background-color: rgba(33, 37, 43, 190);"
            " border-radius: 8px; }"
            " QLabel { color: white; }"
            " QPushButton { color: white; background-color: rgba(255, 255, 255, 30);"
            " border: 1px solid rgba(255, 255, 255, 60); border-radius: 4px;"
            " padding: 3px 10px; }"
            " QPushButton:hover { background-color: rgba(255, 255, 255, 55); }"
            " QPushButton:disabled { color: rgba(255, 255, 255, 90); }"
        )
        self.setEnabled(False)
        self._playing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(4)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("속도"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 200)
        self.speed_slider.setValue(1)
        self.speed_slider.setFocusPolicy(Qt.NoFocus)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_value_label = QLabel("1x")
        self.speed_value_label.setFixedWidth(42)
        speed_row.addWidget(self.speed_value_label)
        outer.addLayout(speed_row)

        button_row = QHBoxLayout()
        self.prev_tool_button = QPushButton("◀툴")
        self.rewind_button = QPushButton("◀◀")
        self.play_pause_button = QPushButton("▶")
        self.next_tool_button = QPushButton("툴▶")
        for button in (
            self.prev_tool_button, self.rewind_button,
            self.play_pause_button, self.next_tool_button,
        ):
            button.setFocusPolicy(Qt.NoFocus)
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
        self.play_pause_button.setText("❚❚" if self._playing else "▶")

    def set_speed(self, value):
        with QSignalBlocker(self.speed_slider):
            self.speed_slider.setValue(value)
        self.speed_value_label.setText("%dx" % self.speed_slider.value())


class NCViewerWidget(QWidget):
    """Viewer-only widget used inside the main tool-list application."""

    # Emitted with the source line index where a clicked process-filter entry begins,
    # so the host window can move the program editor's cursor there.
    process_activated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("NC Tool List", "EmbeddedViewer")
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
        view_bar.setContentsMargins(6, 5, 6, 5)
        view_bar.addWidget(QLabel("투영"))
        for label, view_type in (
            ("ISO", "ISO"), ("XY", "XY"), ("XZ", "XZ"), ("YZ", "YZ"),
        ):
            button = QPushButton(label)
            # 방향키로 프로그램 커서를 옮기는 도중 이 버튼이 포커스를 가져가면
            # 다음 방향키가 커서 대신 버튼 포커스 이동에 쓰이므로 항상 막아둔다.
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, value=view_type: self.set_camera_projection(value))
            view_bar.addWidget(button)
        view_bar.addStretch()
        view_bar.addWidget(QLabel("감도"))
        self.sensitivity_slider = QSlider(Qt.Horizontal)
        self.sensitivity_slider.setRange(5, 200)
        self.sensitivity_slider.setFixedWidth(110)
        self.sensitivity_slider.setValue(round(self._initial_sensitivity * 100))
        self.sensitivity_slider.setToolTip("마우스 드래그/휠 회전·확대 감도")
        self.sensitivity_slider.setFocusPolicy(Qt.NoFocus)
        self.sensitivity_slider.valueChanged.connect(self._on_sensitivity_changed)
        view_bar.addWidget(self.sensitivity_slider)
        self.sensitivity_value_label = QLabel("%d%%" % self.sensitivity_slider.value())
        self.sensitivity_value_label.setFixedWidth(38)
        view_bar.addWidget(self.sensitivity_value_label)
        view_bar.addWidget(QLabel("큐브"))
        self.view_cube_size_slider = QSlider(Qt.Horizontal)
        self.view_cube_size_slider.setRange(60, 240)
        self.view_cube_size_slider.setFixedWidth(90)
        self.view_cube_size_slider.setValue(self._initial_cube_size)
        self.view_cube_size_slider.setToolTip("방향 큐브 크기")
        self.view_cube_size_slider.setFocusPolicy(Qt.NoFocus)
        self.view_cube_size_slider.valueChanged.connect(self._on_view_cube_size_changed)
        view_bar.addWidget(self.view_cube_size_slider)
        self.view_cube_size_label = QLabel("%dpx" % self.view_cube_size_slider.value())
        self.view_cube_size_label.setFixedWidth(38)
        view_bar.addWidget(self.view_cube_size_label)
        layout.addLayout(view_bar)

        coord_group = QGroupBox("좌표")
        coord_group.setFixedHeight(54)
        coord_layout = QHBoxLayout(coord_group)
        coord_layout.setContentsMargins(12, 2, 12, 2)
        coord_layout.setSpacing(16)
        self.coord_labels = {}
        colors = {
            "X": "#FF3333", "Y": "#33AA33", "Z": "#4D68FF",
            "A": "#9A8500", "B": "#AA33AA", "C": "#229999",
        }
        for axis in ("X", "Y", "Z", "A", "B", "C"):
            coord_layout.addWidget(QLabel(axis + ":"))
            value = QLabel("0.000")
            value.setStyleSheet("font-weight: bold; color: %s;" % colors[axis])
            self.coord_labels[axis] = value
            coord_layout.addWidget(value)
        coord_layout.addStretch()
        layout.addWidget(coord_group)

        self.gl_view = OrthographicGLViewWidget()
        self.gl_view.setBackgroundColor(33, 37, 43, 255)
        self.gl_view.navigation_sensitivity = self._initial_sensitivity
        layout.addWidget(self.gl_view, 1)
        self._build_view_cube()
        self._build_playback_bar()

        self.grid = gl.GLGridItem()
        self.grid.setSize(400, 400, 1)
        self.grid.setSpacing(20, 20, 1)
        self.gl_view.addItem(self.grid)
        self._add_axis_lines()

        self.cursor_sphere = gl.GLMeshItem(
            meshdata=gl.MeshData.sphere(rows=10, cols=20, radius=2.0),
            smooth=True,
            color=(1.0, 1.0, 0.0, 1.0),
            shader="shaded",
        )
        self.cursor_sphere.setVisible(False)
        self.gl_view.addItem(self.cursor_sphere)

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

    def _on_sensitivity_changed(self, percent):
        ratio = max(0.05, min(2.0, percent / 100.0))
        self.gl_view.navigation_sensitivity = ratio
        self.sensitivity_value_label.setText("%d%%" % percent)
        self.settings.setValue("navigation_sensitivity", ratio)

    def _on_view_cube_size_changed(self, size):
        self.view_cube_size_label.setText("%dpx" % size)
        self.settings.setValue("view_cube_size", size)
        if self.view_cube is not None:
            self.view_cube.setFixedSize(size, size)
            self.gl_view._reposition_overlay()
            self.view_cube.update()

    def _add_axis_lines(self):
        infinite_val = 99999.0
        axis_lines = (
            ([[-infinite_val, 0, 0], [infinite_val, 0, 0]], (1.0, 0.2, 0.2, 0.8)),
            ([[0, -infinite_val, 0], [0, infinite_val, 0]], (0.2, 1.0, 0.2, 0.8)),
            ([[0, 0, -infinite_val], [0, 0, infinite_val]], (0.2, 0.2, 1.0, 0.8)),
        )
        for points, color in axis_lines:
            self.gl_view.addItem(
                gl.GLLinePlotItem(
                    pos=np.array(points), color=color, width=1.5, antialias=True
                )
            )

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
            self.grid.setSize(400, 400, 1)
            if init_camera:
                self.set_camera_projection("XZ")
                init_camera = False
        else:
            self.grid.setSize(400, 400, 1)
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

    def set_camera_angles(self, elevation, azimuth, distance=None):
        """카메라 방향만 바꾼다. distance를 안 주면 현재 줌 배율을 유지한다."""
        kwargs = {"elevation": elevation, "azimuth": azimuth}
        if distance is not None:
            kwargs["distance"] = distance
        self.gl_view.setCameraPosition(**kwargs)

    def set_camera_projection(self, view_type):
        preset = self._VIEW_PROJECTIONS.get(view_type)
        if preset is not None:
            elevation, azimuth = preset
            self.set_camera_angles(elevation, azimuth, distance=200)

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
        for idx, (tool, path_data) in enumerate(self.tool_paths.items()):
            base_color = tool_color_for_index(idx)
            self.plot_items[tool] = []
            for motion_type, pts_list in self._render_segment_buckets(path_data).items():
                self.create_segment_item(tool, pts_list, motion_type, base_color)

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
            self.coord_labels[axis].setText(str(value))
