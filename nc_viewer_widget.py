# -*- coding: utf-8 -*-
"""Embedded PyQt 3D NC path viewer widget."""
import bisect
import json
from math import cos, radians, sin, tan
import re

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph import Vector
from PyQt5.QtCore import (
    Qt, QEvent, QPointF, QRect, QRectF, QSettings, QSignalBlocker, QSize, QTimer, pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QIcon, QKeySequence, QMatrix4x4, QPainter, QPainterPath, QPen, QPixmap,
    QPolygonF, QVector3D,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QRubberBand,
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

# v1.6.5: 선반 뷰에서는 좌표 오버레이를 화면 하단(재생 속도바 바로 위)으로
# 옮긴다 — 그 사이 세로 간격.
BOTTOM_COORD_OVERLAY_GAP_PX = 8

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
    # 선반 전용 평면(v1.6.4). 밀링의 G17/G18/G19 항목은 손대지 않고 새 키만
    # 추가한다 — 선반 좌표는 월드 X = 기계 Z(수평), 월드 Z = 기계 X 반경(수직)로
    # 스왑해서 올리므로, 원호 평면의 u축은 월드 X(중심 오프셋 K), v축은
    # 월드 Z(중심 오프셋 I)가 되고 남는 월드 Y가 선형 보간 축이 된다.
    # 이 (u=오른쪽, v=위) 배치에서 각도가 줄어드는 방향이 화면상 시계 방향이라
    # 기존 보간 루틴의 G02 규약이 선반 뷰에서도 그대로 시계 방향이 된다.
    "LATHE": (0, 2, 1, "k", "i"),
    # v1.6.6: M35(구동공구) 턴밀 전용 평면 — lathe_local_point()의 로컬
    # (월드 X=기계Z, 월드 Y=기계Y, 월드 Z=반경) 좌표계에서 계산한 뒤
    # lathe_rotate_c()로 C만큼 통째로 회전시킨다(밀링 4/5축 원호와 같은
    # "로컬로 그리고 배치로 회전" 방식, v1.4.5). G17(기계 X-Y 평면)은
    # 반경(I)-Y(J), G19(기계 Y-Z 평면)는 Y(J)-기계Z(K).
    "LATHE_G17": (2, 1, 0, "i", "j"),
    "LATHE_G19": (1, 0, 2, "j", "k"),
}
ARC_CHORD_TOLERANCE_MM = 0.05
ARC_MIN_SEGMENTS = 6
ARC_MAX_SEGMENTS = 720


# v1.6.7: 장비 명칭 변경 — "5축 밀링" -> "5축 MCT", "2축 선반 ..." ->
# "CNC 선반 (턴밀 포함)". A to C / B to C 구분은 설정이 서로 달라 유지한다.
MACHINE_5AXIS_AC = "5축 MCT (A to C)"
MACHINE_5AXIS_BC = "5축 MCT (B to C)"
MACHINE_LATHE = "CNC 선반 (턴밀 포함)"

# 이전 버전 이름으로 저장된 QSettings를 새 이름으로 읽어 들이기 위한 표.
# 이게 없으면 업데이트 직후 사용자가 고른 장비와 입력해 둔 행정값이
# 통째로 초기화된다.
RENAMED_MACHINE_TYPES = {
    "5축 밀링 (A to C)": MACHINE_5AXIS_AC,
    "5축 밀링 (B to C)": MACHINE_5AXIS_BC,
    "2축 선반 (X Z 평면, X 2배)": MACHINE_LATHE,
}


def migrate_machine_type_name(machine_type):
    """이전 버전의 장비 이름을 v1.6.7 이름으로 바꿔 준다(모르는 이름은 그대로)."""
    return RENAMED_MACHINE_TYPES.get(str(machine_type or ""), machine_type)


DEFAULT_MACHINE_SPECS = {
    MACHINE_5AXIS_AC: {
        "X 행정": "800", "Y 행정": "800", "Z 행정": "600",
        "A축 범위": "-120~+30", "C축 범위": "360",
    },
    "3축 MCT (X Y Z)": {"X 행정": "1000", "Y 행정": "600", "Z 행정": "600"},
    "4축 MCT (B-Type)": {
        "X 행정": "1200", "Y 행정": "800", "Z 행정": "800", "B축 범위": "-120~+120",
    },
    MACHINE_LATHE: {"X 행정": "300", "Z 행정": "500", "최대 RPM": "4000"},
    MACHINE_5AXIS_BC: {
        "X 행정": "600", "Y 행정": "600", "Z 행정": "500",
        "B축 범위": "-110~+110", "C축 범위": "360",
    },
}


# --------------------------------------------------------------------------
# 선반(Lathe) 전용 헬퍼 (v1.6.4) — LATHE_MODE_GUIDELINES.md 참고.
# 선반은 밀링과 완전히 별개로 취급한다. 여기 있는 함수는 선반 분기에서만
# 호출되며, 밀링 경로 계산에는 절대 끼어들지 않는다.
# --------------------------------------------------------------------------

LATHE_MACHINE_KEYWORD = "선반"


def is_lathe_machine(machine_type):
    """장비 이름으로 선반 여부를 판정한다(밀링 판정에는 쓰지 않는다)."""
    return LATHE_MACHINE_KEYWORD in str(machine_type or "")


def lathe_local_point(z_value, x_diameter, y_value=0.0):
    """선반 기계 좌표를 C 회전을 걸기 전의 "로컬" 월드 좌표로 바꾼다
    (v1.6.6, M35 구동공구 밀링). 기계 Z -> 월드 X, 기계 X(지름) -> 월드
    Z(반경 = X/2), 기계 Y(구동공구 밀링) -> 월드 Y. C 회전은
    lathe_rotate_c()가 따로 건다 — 밀링의 4/5축 원호가 로컬 좌표로 그린
    뒤 한꺼번에 회전시키는 것과 같은 방식(v1.4.5)으로, 원호 I/J/K
    오프셋이 회전 전 로컬 좌표계 기준이기 때문이다."""
    return [float(z_value), float(y_value or 0.0), float(x_diameter) / 2.0]


def lathe_rotate_c(point, c_deg):
    """로컬 선반 좌표(lathe_local_point)를 주축(월드 X) 둘레로 C도 만큼
    돌린다(v1.6.6)."""
    c_deg = float(c_deg or 0.0)
    if not c_deg:
        return list(point)
    rad = np.radians(c_deg)
    y, z = point[1], point[2]
    return [point[0], y * np.cos(rad) + z * np.sin(rad), -y * np.sin(rad) + z * np.cos(rad)]


def lathe_world_point(z_value, x_diameter, c_deg=0.0, y_value=0.0):
    """선반 기계 좌표를 3D 월드 좌표로 바꾼다.

    - 기계 Z(주축 방향)  -> 월드 X (화면 수평)
    - 기계 X(지름 지령)  -> 월드 Z (화면 수직). **X는 지름이므로 반경 = X / 2.**
    - 기계 C(주축 회전)  -> 반경(+Y, v1.6.6)을 주축(월드 X) 둘레로 돌린 성분.
    - 기계 Y(v1.6.6, M35 구동공구 밀링) -> 회전 전 로컬 좌표의 월드 Y.
      y_value=0이면 기존(v1.6.4) 결과와 완전히 동일하다.

    C가 0이면 선반 평면(월드 XZ) 위에 그대로 놓인다.
    """
    return lathe_rotate_c(lathe_local_point(z_value, x_diameter, y_value), c_deg)


# --------------------------------------------------------------------------
# 가공시간 계산 (v1.6.7) — v1.6.7.md 2항의 규칙을 그대로 옮긴 것.
#
# MCT(밀링)와 선반이 F를 다르게 읽는다는 점만 빼면 계산은 같다:
#   세그먼트 시간 = 이동거리(mm) / 유효 이송속도(mm/min).
# 유효 이송속도만 아래 두 함수가 정하고, 거리는 이미 계산된 툴패스에서
# 그대로 잰다(경로 계산 로직에는 손대지 않는다).
# --------------------------------------------------------------------------

# G00은 프로그램의 F와 무관하게 항상 이 속도로 움직이는 것으로 본다.
RAPID_FEED_MM_PER_MIN = 7000.0
# 이 이하 간격의 미세 이동은 가감속 때문에 지령 속도가 다 안 나온다.
SHORT_SEGMENT_MM = 0.5
# 원호(G02/G03)와 위 미세 이동에 적용하는 실효 비율.
SLOW_FEED_RATIO = 0.7


def effective_feed_mm_per_min(motion, feed_mm_per_min, distance_mm):
    """세그먼트 하나에 실제로 적용할 이송속도(mm/min)를 돌려준다.

    - G00: F를 무시하고 항상 RAPID_FEED_MM_PER_MIN.
    - G02/G03: F의 70% (원호는 지령 속도가 다 나오지 않는다).
    - G01: 이동량이 SHORT_SEGMENT_MM 이하면 70%, 그보다 크면 100%.
    F가 아직 한 번도 안 나온 절삭 이동은 0을 돌려준다 — 호출부가
    시간 0으로 넘긴다(추정으로 시간을 부풀리지 않는다).
    """
    if motion == "G00":
        return RAPID_FEED_MM_PER_MIN
    try:
        feed = float(feed_mm_per_min or 0.0)
    except (TypeError, ValueError):
        feed = 0.0
    if feed <= 0.0:
        return 0.0
    if motion in ("G02", "G03") or float(distance_mm) <= SHORT_SEGMENT_MM:
        return feed * SLOW_FEED_RATIO
    return feed


def lathe_spindle_rpm(spindle_mode, spindle_value, diameter_mm, max_rpm):
    """선반 주축 회전수(rev/min)를 돌려준다(v1.6.7).

    - G97(정회전): S가 곧 회전수다.
    - G96(정속절삭): S는 절삭속도 V(m/min)이고 V = D x 3.14 x N / 1000
      이므로 N = V x 1000 / (pi x D). 지름 D가 0에 가까우면(센터 근처)
      회전수가 발산하므로 G50 상한으로 잘린다.
    어느 모드든 G50에 걸린 최대 회전수를 넘지 못한다.
    """
    try:
        spindle_value = float(spindle_value or 0.0)
    except (TypeError, ValueError):
        spindle_value = 0.0
    try:
        max_rpm = float(max_rpm or 0.0)
    except (TypeError, ValueError):
        max_rpm = 0.0
    if spindle_value <= 0.0:
        return 0.0
    if str(spindle_mode).upper() == "G96":
        diameter_mm = abs(float(diameter_mm or 0.0))
        if diameter_mm <= 1e-6:
            rpm = max_rpm
        else:
            rpm = spindle_value * 1000.0 / (np.pi * diameter_mm)
    else:
        rpm = spindle_value
    if max_rpm > 0.0:
        rpm = min(rpm, max_rpm)
    return rpm


# 좌표 오버레이의 "진행중 / 전체" 시간이 아직 없을 때 보여줄 값.
TIME_OVERLAY_PLACEHOLDER = "00:00 / 00:00"


def format_elapsed_over_total(elapsed_sec, total_sec):
    """좌표 오버레이 끝에 붙는 "진행중인 시간 / 전체 시간" 문자열(v1.6.7)."""
    return "%s / %s" % (format_duration(elapsed_sec), format_duration(total_sec))


def format_duration(seconds):
    """초를 화면 표기용 문자열로 바꾼다 — 1시간 미만은 MM:SS,
    1시간 이상은 H:MM:SS (v1.6.7)."""
    try:
        total = int(round(float(seconds or 0.0)))
    except (TypeError, ValueError):
        total = 0
    total = max(0, total)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%02d:%02d" % (minutes, secs)


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
    # v1.6.5: 드래그줌 토글이 내부적으로(사각형 확정 후 자동 해제 포함)
    # 바뀔 때마다 쏜다 — 오버레이의 체크 버튼을 실제 상태와 맞추는 데 쓴다.
    drag_zoom_state_changed = pyqtSignal(bool)

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
        # v1.6.5: 선반 뷰에서는 좌표 오버레이가 top_left_widgets 목록을
        # 떠나 이 위젯으로 옮겨온다(화면 하단, 재생 속도바 바로 위).
        # v1.6.8: 이제 밀링/선반 공통으로 항상 하단이고, 투영 오버레이도
        # 같은 줄의 왼쪽에 나란히 붙는다(top_left_widgets는 더 이상 쓰지
        # 않는다 — 사용자 확정).
        self.bottom_coord_widget = None
        self.bottom_projection_widget = None
        # 렌더된 경로 전체를 감싸는 구의 반지름(원점 기준) — projectionMatrix()가
        # 깊이 클리핑 범위를 카메라 거리 대신 이 값으로 산정해, 확대해도 긴
        # 경로가 far 평면에 잘리지 않게 한다. 경로가 없으면 0(거리 기반 fallback).
        self.scene_radius = 0.0
        self._left_press_pos = None
        self._left_press_was_drag = False
        # v1.6.5: 선반 평면 뷰("선반" 투영)에서는 좌드래그가 화면을 돌리지
        # 않고 상하좌우로만 움직이게 잠근다(지침 3항 — 회전하면 Z-수평/
        # X-수직 평면이 깨진다). ISO나 밀링에서는 항상 False(자유 회전).
        self.orbit_locked = False
        # v1.6.5: 선반 전용 "드래그줌" 버튼이 켜져 있는 동안 좌드래그는
        # 화면에 사각형을 그리는 데만 쓰이고, 손을 떼면 그 영역이 화면에
        # 꽉 차도록 한 번 확대한 뒤 자동으로 꺼진다.
        self.drag_zoom_active = False
        self._drag_zoom_rubber_band = None
        self._drag_zoom_origin = None
        # pyqtgraph's GLViewWidget defaults to ClickFocus and steals arrow keys for
        # camera orbit (its own keyPressEvent) the moment this widget is clicked,
        # which silently breaks program-cursor arrow-key stepping. Keyboard focus
        # must always stay on the program editor.
        self.setFocusPolicy(Qt.NoFocus)

    def set_drag_zoom_active(self, active):
        """드래그줌 모드를 켜고 끈다. 진행 중인 드래그가 있으면 취소한다."""
        active = bool(active)
        if active == self.drag_zoom_active:
            return
        self.drag_zoom_active = active
        if not active:
            self._drag_zoom_origin = None
            if self._drag_zoom_rubber_band is not None:
                self._drag_zoom_rubber_band.hide()
        self.drag_zoom_state_changed.emit(active)

    def _ensure_drag_zoom_band(self):
        if self._drag_zoom_rubber_band is None:
            self._drag_zoom_rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        return self._drag_zoom_rubber_band

    def _apply_drag_zoom(self, rect):
        """드래그한 사각형이 화면에 꽉 차도록 카메라를 이동·확대한다(v1.6.5).
        직교 투영이라 화면 픽셀과 카메라 거리가 선형 관계라 정확히 맞출 수
        있다 — 원근 투영이었다면 사각형 중심의 실제 3D 위치가 거리마다
        달라져 이렇게 간단히 계산할 수 없다."""
        width = max(float(self.width()), 1.0)
        height = max(float(self.height()), 1.0)
        rect_w = max(float(rect.width()), 4.0)
        rect_h = max(float(rect.height()), 4.0)
        center = rect.center()
        # 사각형 중심을 화면 정중앙으로 가져온다. pan(dx, dy, 0, 'view')는
        # "내용이 드래그를 따라간다"는 규약이므로(Ctrl+드래그 팬과 동일),
        # 중심을 화면 가운데로 되돌리려면 그 반대 방향(-오프셋)만큼 이동한다.
        offset_x = center.x() - width / 2.0
        offset_y = center.y() - height / 2.0
        if offset_x or offset_y:
            self.pan(-offset_x, -offset_y, 0, relative='view')
        scale = max(rect_w / width, rect_h / height)
        scale = min(max(scale, 0.02), 1.0)
        self.opts['distance'] = max(float(self.opts.get('distance', 200.0)) * scale, 1.0)
        self.update()
        self.camera_changed.emit()
        self.set_drag_zoom_active(False)

    def mousePressEvent(self, ev):
        lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
        if ev.button() == Qt.LeftButton:
            if self.drag_zoom_active:
                self._drag_zoom_origin = lpos
                self._ensure_drag_zoom_band().setGeometry(QRect(lpos.toPoint(), QSize()))
                self._drag_zoom_rubber_band.show()
                return
            self._left_press_pos = lpos
            self._left_press_was_drag = False
        elif ev.button() == Qt.RightButton:
            self.right_clicked.emit(lpos.x(), lpos.y())
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.drag_zoom_active and self._drag_zoom_origin is not None:
            lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
            rect = QRect(self._drag_zoom_origin.toPoint(), lpos.toPoint()).normalized()
            self._drag_zoom_origin = None
            if self._drag_zoom_rubber_band is not None:
                self._drag_zoom_rubber_band.hide()
            self._apply_drag_zoom(rect)
            return
        if ev.button() == Qt.LeftButton and self._left_press_pos is not None:
            lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
            if not self._left_press_was_drag:
                self.left_clicked.emit(lpos.x(), lpos.y())
            self._left_press_pos = None
        super().mouseReleaseEvent(ev)

    def mouseMoveEvent(self, ev):
        lpos = ev.position() if hasattr(ev, 'position') else ev.localPos()
        if self.drag_zoom_active and (ev.buttons() & Qt.LeftButton) and self._drag_zoom_origin is not None:
            rect = QRect(self._drag_zoom_origin.toPoint(), lpos.toPoint()).normalized()
            self._ensure_drag_zoom_band().setGeometry(rect)
            return
        if (ev.buttons() & Qt.LeftButton) and self._left_press_pos is not None:
            moved = lpos - self._left_press_pos
            if (moved.x() ** 2 + moved.y() ** 2) ** 0.5 > self._CLICK_DRAG_PX:
                self._left_press_was_drag = True
        if not hasattr(self, 'mousePos'):
            self.mousePos = lpos
        prev_pos = self.mousePos
        # pyqtgraph's own handler computes diff = lpos - self.mousePos and then
        # overwrites self.mousePos with the true lpos. Pulling the stored point
        # toward lpos by (1 - sensitivity) shrinks that diff without touching
        # pyqtgraph's orbit()/pan() math, so it keeps working across library versions.
        self.mousePos = lpos - (lpos - self.mousePos) * self.navigation_sensitivity
        if self.orbit_locked and ev.buttons() == Qt.LeftButton and not (ev.modifiers() & Qt.ControlModifier):
            # v1.6.5: 선반 평면 뷰는 좌드래그를 orbit 대신 pan으로 바꿔치기
            # 한다 — 기존 Ctrl+좌드래그 팬(pyqtgraph 기본 동작)과 같은 호출.
            diff = lpos - prev_pos
            self.pan(diff.x() * self.navigation_sensitivity, diff.y() * self.navigation_sensitivity, 0, relative='view')
            self.camera_changed.emit()
            self.mouse_moved.emit(lpos.x(), lpos.y())
            return
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
            # v1.6.7: 화면 중앙이 아니라 **마우스 커서 위치**를 기준으로
            # 확대/축소한다. 픽셀당 월드 거리가 distance에 정비례하므로
            # (projectionMatrix의 view_height = 2*distance*tan(fov/2)),
            # 커서가 중앙에서 px 픽셀 떨어져 있으면 거리가 f배로 바뀔 때
            # 그 지점은 px/f로 밀린다. 되돌리려면 화면 내용을 px*(1 - 1/f)
            # 만큼 옮기면 된다 — pan(dx, dy, 0, 'view')가 드래그 팬과 같은
            # "내용이 따라온다" 규약이라 그 값을 그대로 넘긴다.
            # distance를 바꾼 **뒤에** 불러야 픽셀 규약이 1:1로 맞는다.
            factor = 0.999 ** delta
            old_distance = max(float(self.opts.get('distance', 200.0)), 1e-9)
            self.opts['distance'] = old_distance * factor
            applied = max(float(self.opts['distance']), 1e-9) / old_distance
            self._zoom_toward_cursor(ev, applied)
        self.update()
        self.camera_changed.emit()

    def _zoom_toward_cursor(self, ev, factor):
        """휠 줌 뒤 커서 아래 지점이 같은 화면 위치에 남도록 팬 보정한다
        (v1.6.7). 보정에 실패해도 줌 자체는 살아 있어야 하므로 조용히
        넘어간다 — 최악이라도 기존(화면 중앙 기준) 줌으로 되돌아간다."""
        if not factor or factor <= 0.0:
            return
        try:
            pos = ev.position() if hasattr(ev, 'position') else ev.posF()
            offset_x = float(pos.x()) - self.width() / 2.0
            offset_y = float(pos.y()) - self.height() / 2.0
            shift = 1.0 - 1.0 / factor
            if offset_x or offset_y:
                self.pan(offset_x * shift, offset_y * shift, 0, relative='view')
        except Exception:
            pass

    def setCameraPosition(self, *args, **kwargs):
        super().setCameraPosition(*args, **kwargs)
        self.camera_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_overlay()
        self._reposition_bottom_bar()
        self._reposition_top_left()
        self._reposition_bottom_coord()

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

    def _reposition_bottom_coord(self):
        """v1.6.8: 좌표 오버레이는 이제 밀링/선반 공통으로 항상 화면 하단,
        재생 속도바 바로 위에 뜬다(이전엔 선반일 때만). 투영 오버레이가
        있으면 그 왼쪽에 나란히 붙는다(투영이 왼쪽, 좌표가 오른쪽 —
        사용자 확정, 2026-09-06). 두 위젯을 하나의 묶음으로 보고 가로
        중앙에 맞추며, 각자 자기 높이만큼만 속도바 위로 띄워 높이가
        달라도 바닥선이 맞게 정렬한다."""
        widget = self.bottom_coord_widget
        projection = self.bottom_projection_widget
        if widget is None and projection is None:
            return
        bar = self.bottom_bar_widget
        bar_top_y = bar.y() if bar is not None else self.height() - round(2 * PX_PER_CM)

        total_width = 0
        if projection is not None:
            total_width += projection.width()
        if widget is not None:
            if projection is not None:
                total_width += BOTTOM_COORD_OVERLAY_GAP_PX
            total_width += widget.width()
        cursor_x = max(0, (self.width() - total_width) // 2)

        if projection is not None:
            proj_y = bar_top_y - projection.height() - BOTTOM_COORD_OVERLAY_GAP_PX
            projection.move(cursor_x, max(0, proj_y))
            cursor_x += projection.width() + BOTTOM_COORD_OVERLAY_GAP_PX
        if widget is not None:
            coord_y = bar_top_y - widget.height() - BOTTOM_COORD_OVERLAY_GAP_PX
            widget.move(cursor_x, max(0, coord_y))

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
    # v1.6.5: 선반 전용 "드래그줌" 토글 버튼의 체크 상태가 바뀔 때(사용자
    # 클릭이든, 드래그 확정 후 자동 해제든) 쏜다.
    drag_zoom_toggled = pyqtSignal(bool)

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
        self._row = row
        # 라벨 + 여백 2칸은 고정이고, 그 뒤 버튼만 모드에 따라 갈아 끼운다.
        self._fixed_item_count = row.count()
        self._lathe_mode = False
        self.drag_zoom_button = None
        self._rebuild_buttons(self.MILL_BUTTONS)

    # 밀링과 선반은 축 개념 자체가 달라 투영 버튼 구성을 다르게 쓴다(v1.6.4).
    # 선반은 XY/XZ/YZ가 의미가 없으므로 ISO(축이 바뀐 상태)와 선반 평면 뷰만 둔다.
    MILL_BUTTONS = (("ISO", "ISO"), ("XY", "XY"), ("XZ", "XZ"), ("YZ", "YZ"))
    LATHE_BUTTONS = (("ISO", "ISO"), ("선반", "LATHE"))

    def _rebuild_buttons(self, buttons):
        row = self._row
        while row.count() > self._fixed_item_count:
            item = row.takeAt(self._fixed_item_count)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for text, view_type in buttons:
            button = QPushButton(text)
            if view_type == "ISO":
                button.setIcon(iso_icon("#e4e8f0"))
            elif view_type == "LATHE":
                button.setIcon(plane_icon("ZX"))
            else:
                button.setIcon(plane_icon(view_type))
            button.setIconSize(QSize(14, 14))
            # 방향키로 프로그램 커서를 옮기는 도중 이 버튼이 포커스를 가져가면
            # 다음 방향키가 커서 대신 버튼 포커스 이동에 쓰이므로 항상 막아둔다.
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, value=view_type: self.projection_clicked.emit(value))
            # 스타일시트(폰트/패딩)가 적용되기 전에는 버튼의 sizeHint가 거의
            # 0이라, 지금 바로 크기를 재면 오버레이가 찌그러진다. 새 버튼을
            # 즉시 polish 해서 제대로 된 hint를 갖게 한다.
            button.ensurePolished()
            row.addWidget(button)
            # 이미 화면에 떠 있는 오버레이에 나중에 끼워 넣는 위젯은 숨김
            # 상태로 들어와, 그대로 두면 레이아웃 크기 계산에서 아예 빠진다
            # (그래서 선반 전환 시 오버레이가 라벨 폭까지만 줄어들었다).
            if self.isVisible():
                button.show()
        self.drag_zoom_button = None
        if buttons is self.LATHE_BUTTONS:
            # v1.6.5: 선반 뷰 전용 — 드래그로 그린 사각형만큼 한 번에
            # 확대하는 토글 버튼(밀링에는 없음, 기존 오빗/휠줌 그대로).
            drag_zoom_button = QPushButton("드래그줌")
            drag_zoom_button.setCheckable(True)
            drag_zoom_button.setFocusPolicy(Qt.NoFocus)
            drag_zoom_button.toggled.connect(self.drag_zoom_toggled.emit)
            drag_zoom_button.ensurePolished()
            row.addWidget(drag_zoom_button)
            if self.isVisible():
                drag_zoom_button.show()
            self.drag_zoom_button = drag_zoom_button
        self._fit_to_contents()

    def _fit_to_contents(self):
        """버튼 구성이 바뀐 뒤 오버레이 크기를 다시 잡는다.

        버튼을 갈아 끼운 직후에는 레이아웃이 들고 있는 sizeHint 캐시가 아직
        옛 구성 기준이라, 그대로 adjustSize()를 부르면 오버레이가 40x20으로
        찌그러져 버튼이 2px 폭으로 잘려 보인다(선반 전환 시 실제 앱에서 재현).
        캐시는 LayoutRequest 이벤트가 배달돼야 갱신되므로, 이벤트 루프를
        기다리지 않고 그 이벤트를 동기로 흘려보낸 뒤 크기를 잡는다."""
        self._row.invalidate()
        self.updateGeometry()
        QApplication.sendPostedEvents(self, QEvent.LayoutRequest)
        self._row.activate()
        self.adjustSize()
        # 크기가 바뀌었으니 부모(3D 화면) 안에서의 위치도 다시 잡아준다.
        parent = self.parent()
        reposition = getattr(parent, "_reposition_top_left", None)
        if callable(reposition):
            reposition()

    def set_lathe_mode(self, enabled):
        """선반 모드에서는 투영 버튼을 ISO/선반 2개로 바꾼다(v1.6.4)."""
        enabled = bool(enabled)
        if enabled == self._lathe_mode:
            return
        self._lathe_mode = enabled
        self._rebuild_buttons(self.LATHE_BUTTONS if enabled else self.MILL_BUTTONS)

    def button_labels(self):
        """현재 노출 중인 투영 버튼 텍스트(테스트/디버그용). 드래그줌
        토글은 투영 버튼이 아니므로 제외한다."""
        return [
            self._row.itemAt(index).widget().text()
            for index in range(self._fixed_item_count, self._row.count())
            if self._row.itemAt(index).widget() is not None
            and self._row.itemAt(index).widget() is not self.drag_zoom_button
        ]

    def set_drag_zoom_checked(self, checked):
        """gl_view의 실제 drag_zoom_active 상태에 버튼 체크를 맞춘다(v1.6.5).
        버튼이 없는(밀링) 상태에서 호출돼도 안전하다."""
        if self.drag_zoom_button is not None:
            with QSignalBlocker(self.drag_zoom_button):
                self.drag_zoom_button.setChecked(bool(checked))


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
        # v1.6.7: 좌표 끝에 "진행중인 시간 / 전체 시간"을 붙인다. 축 값들과
        # 구분되게 옅은 회색으로 두고, 계산된 시간이 없으면 0으로 보인다.
        row.addSpacing(6)
        self.time_label = QLabel(TIME_OVERLAY_PLACEHOLDER)
        self.time_label.setStyleSheet(
            "background: transparent; font-weight: bold; font-size: 14px; color: #DDDDDD;"
        )
        row.addWidget(self.time_label)
        self.adjustSize()

    def set_time_text(self, text):
        self.time_label.setText(text)
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
        self.current_machine_type = migrate_machine_type_name(
            self.settings.value("machine_type", next(iter(self.machine_specs)))
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
        # v1.6.6: 선반 C축 회전 시뮬레이션 — 줄마다 "그 시점에 유효한 C
        # 회전각"(lathe_rotate_c에 넘긴 cc_deg)을 들고 있는다. is_lathe가
        # 아니면 항상 채워지지 않고(get() 기본값 0), 밀링 재생에는 쓰이지
        # 않는다.
        self.line_to_c_rot = {}
        # v1.6.7 가공시간. line_feed_state는 줄마다 "그 줄에서 유효한 이송
        # 상태"(F, 선반 G99 여부, G96/G97 모드, S, G50 상한)를 들고 있고,
        # 나머지 셋은 파싱이 끝난 뒤 _compute_machining_times()가 채운다.
        self.line_feed_state = {}
        self.line_to_elapsed_sec = {}
        self._elapsed_line_keys = []
        self.process_time_sec = {}
        self.total_time_sec = 0.0
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
                            # v1.6.7: 예전 이름으로 저장된 항목은 새 이름으로
                            # 옮겨 받는다(사용자가 고쳐 둔 행정값 보존).
                            specs[migrate_machine_type_name(machine_type)] = {
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
            # v1.6.5: 선반 전용 "드래그줌" 버튼 <-> gl_view의 실제 상태를
            # 양방향으로 맞춘다(버튼 클릭 -> gl_view 활성화, 드래그 확정 후
            # 자동 해제 -> 버튼 체크 해제).
            overlay.drag_zoom_toggled.connect(self.gl_view.set_drag_zoom_active)
            self.gl_view.drag_zoom_state_changed.connect(overlay.set_drag_zoom_checked)
            overlay.raise_()
        except Exception:
            overlay = None
        self.projection_overlay = overlay
        # 저장된 장비가 이미 선반이면 처음부터 선반용 버튼으로 띄운다(v1.6.4).
        if overlay is not None:
            try:
                overlay.set_lathe_mode(self.is_lathe_mode())
            except Exception:
                pass

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
    # 선반은 축을 스왑해서 그리므로(월드 X = 기계 Z, 월드 Z = 기계 X) 화살표
    # 문자도 그에 맞춰 바꾼다. 남는 월드 Y는 주축 회전 C축이다(v1.6.4).
    _LATHE_AXIS_LABELS = ("Z", "C", "X")
    # 문자를 바꾸면 색도 같이 따라가야 한다 — 좌표 오버레이가 X를 빨강, Z를
    # 파랑, C를 청록으로 쓰므로 화살표도 "글자에 맞는 색"이 되도록 맞춘다.
    # (그러지 않으면 수평 화살표가 "Z"인데 빨강이라 밀링과 헷갈린다.)
    _LATHE_AXIS_COLORS = (
        (0.2, 0.2, 1.0, 0.9),    # 월드 X = 기계 Z -> 파랑
        (0.13, 0.6, 0.6, 0.9),   # 월드 Y = 주축 회전 C -> 청록
        (1.0, 0.2, 0.2, 0.9),    # 월드 Z = 기계 X(지름) -> 빨강
    )
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

    def is_lathe_mode(self):
        """현재 선택된 장비가 선반인가(v1.6.4)."""
        return is_lathe_machine(getattr(self, "current_machine_type", ""))

    def current_axis_labels(self):
        return self._LATHE_AXIS_LABELS if self.is_lathe_mode() else self._AXIS_LABELS

    def current_axis_colors(self):
        if self.is_lathe_mode():
            return self._LATHE_AXIS_COLORS
        return tuple(color for _direction, color, _wings in self._AXIS_DIRECTIONS)

    def _add_axis_lines(self):
        self._remove_axis_lines()
        length = self._axis_arrow_length()
        head_len = length * self._AXIS_ARROW_HEAD_RATIO
        font = self._axis_label_font()
        for (direction, _default_color, wing_axes), color, label in zip(
            self._AXIS_DIRECTIONS, self.current_axis_colors(), self.current_axis_labels()
        ):
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
        self.line_to_c_rot.clear()
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
        # v1.6.4: 선반은 축 배치가 달라 투영 버튼 구성과 축 화살표 문자를
        # 함께 갈아 끼운다. 밀링으로 되돌아오면 원래대로 복구된다.
        self._apply_lathe_mode_ui()
        if is_lathe_machine(machine_type):
            if init_camera:
                self.set_camera_projection("LATHE")
                init_camera = False
        if init_camera:
            self.set_camera_projection("XY")
        self._save_machine_specs()
        if self.last_source_text:
            self.last_render_signature = None
            self.set_source_text(self.last_source_text)

    def _apply_lathe_mode_ui(self):
        """선반/밀링 전환에 따라 투영 버튼과 축 화살표 문자를 갱신한다(v1.6.4).

        오버레이가 만들어지지 않았거나(생성 실패) 축이 아직 없을 수도 있으므로
        어느 쪽이 실패해도 뷰어 전체를 잃지 않게 감싼다."""
        lathe = self.is_lathe_mode()
        overlay = getattr(self, "projection_overlay", None)
        if overlay is not None:
            try:
                overlay.set_lathe_mode(lathe)
                self.gl_view._reposition_top_left()
            except Exception:
                pass
        if not lathe:
            # v1.6.5: 밀링으로 돌아오면 선반 뷰에서 걸어 둔 회전 잠금/
            # 드래그줌이 남아있지 않게 확실히 되돌린다(콤보에서 장비만
            # 바꾸고 투영 버튼은 안 눌렀을 수도 있으므로 여기서도 정리).
            gl_view = getattr(self, "gl_view", None)
            if gl_view is not None:
                gl_view.orbit_locked = False
                try:
                    gl_view.set_drag_zoom_active(False)
                except Exception:
                    pass
            view_cube = getattr(self, "view_cube", None)
            if view_cube is not None:
                try:
                    view_cube.setVisible(True)
                except Exception:
                    pass
        try:
            self._place_coord_overlay(lathe)
        except Exception:
            pass
        try:
            if getattr(self, "_axis_items", None):
                self._add_axis_lines()
        except Exception:
            pass

    def _place_coord_overlay(self, lathe):
        """v1.6.8: 좌표 오버레이와 투영 오버레이 모두 화면 하단(재생
        속도바 바로 위)에 나란히 뜬다 — 밀링/선반 공통(사용자 확정,
        2026-09-06). 이전에는 선반일 때만 좌표가 하단으로 내려가고
        밀링은 좌상단에 남았지만, 이제 lathe 인자는 배치에 더 이상
        쓰이지 않는다(호출부 호환을 위해 시그니처만 유지). 투영 버튼
        세트(ISO/XY/XZ/YZ vs ISO/선반) 자체는 set_lathe_mode()가
        그대로 갈아 끼운다 — 손대지 않는다."""
        gl_view = getattr(self, "gl_view", None)
        if gl_view is None:
            return
        coord_overlay = getattr(self, "coord_overlay", None)
        if coord_overlay is not None:
            if coord_overlay in gl_view.top_left_widgets:
                gl_view.top_left_widgets.remove(coord_overlay)
            gl_view.bottom_coord_widget = coord_overlay
        projection_overlay = getattr(self, "projection_overlay", None)
        if projection_overlay is not None:
            if projection_overlay in gl_view.top_left_widgets:
                gl_view.top_left_widgets.remove(projection_overlay)
            gl_view.bottom_projection_widget = projection_overlay
        gl_view._reposition_top_left()
        gl_view._reposition_bottom_coord()

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
        # 선반 평면 뷰(v1.6.4). 월드 XZ 평면을 정면에서 보므로 화면에서
        # 기계 Z가 수평(오른쪽 +), 기계 X(지름)가 수직(위 +)으로 보인다.
        "LATHE": (0, -90),
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

    def _distance_for_radius(self, radius):
        """반지름 radius인 구가 화면 안에 다 들어오는 카메라 거리. radius가
        없거나 0 이하면 None(호출자가 고정 기본값을 쓰게 한다)."""
        if not radius or radius <= 0.0:
            return None
        view = self.gl_view
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

    def _zoom_to_fit_distance(self):
        """현재 로드된 경로 전체(gl_view.scene_radius, 원점 기준)가 화면
        안에 다 들어오는 카메라 거리. 경로가 없으면(반지름 0) None."""
        radius = getattr(self.gl_view, "scene_radius", 0.0) or 0.0
        return self._distance_for_radius(radius)

    def _lathe_path_center_and_radius(self):
        """선반 경로 전체를 감싸는 바운딩박스의 중심과, 그 중심에서 화면에
        다 들어오는 데 필요한 반지름(대각선의 절반)을 반환한다(v1.6.5).

        선반은 X(지름)가 반경으로 변환되어 항상 화면 절반(월드 Z>=0)에만
        그려지므로, 원점 기준 scene_radius/recenter(0,0,0)를 그대로 쓰면
        경로가 화면 위쪽에 쏠려 보인다(v1.6.4에서 보고된 문제). 밀링 경로는
        건드리지 않도록 이 메서드는 선반 투영에서만 호출한다."""
        min_pt = None
        max_pt = None
        for path_data in self.tool_paths.values():
            for node in path_data:
                if not node.get("valid"):
                    continue
                pt = node.get("pt")
                if pt is None:
                    continue
                if min_pt is None:
                    min_pt = [float(v) for v in pt]
                    max_pt = [float(v) for v in pt]
                else:
                    for axis in range(3):
                        value = float(pt[axis])
                        if value < min_pt[axis]:
                            min_pt[axis] = value
                        if value > max_pt[axis]:
                            max_pt[axis] = value
        if min_pt is None:
            return None, None
        center = [(min_pt[axis] + max_pt[axis]) / 2.0 for axis in range(3)]
        half_diagonal = sum(((max_pt[axis] - min_pt[axis]) / 2.0) ** 2 for axis in range(3)) ** 0.5
        return center, max(half_diagonal, 1.0)

    def set_camera_projection(self, view_type):
        preset = self._VIEW_PROJECTIONS.get(view_type)
        if preset is None:
            return
        elevation, azimuth = preset
        lathe = self.is_lathe_mode()
        # v1.6.5: 다른 투영으로 바꾸면 드래그줌 사각형 진행 상태가 애매해
        # 지므로 취소한다. 선반 평면 뷰("선반" 버튼)에서만 좌드래그를 회전
        # 대신 팬으로 잠근다(지침 3항 — 회전하면 Z-수평/X-수직 평면이 깨짐).
        self.gl_view.set_drag_zoom_active(False)
        self.gl_view.orbit_locked = lathe and view_type == "LATHE"
        view_cube = getattr(self, "view_cube", None)
        if view_cube is not None:
            # v1.6.6: 선반 ISO에서도 뷰 큐브를 숨긴다 — orbit_locked는
            # "선반" 평면 뷰에서만 켜지므로, ISO에서는 뷰 큐브가 그대로
            # 보이고 클릭돼 임의 각도로 돌아갈 수 있었다(항목6: 선반
            # 시뮬레이션은 ISO/선반 두 각도로만 봐야 한다). 밀링은
            # lathe가 항상 False라 기존 동작(뷰 큐브 항상 보임) 그대로다.
            view_cube.setVisible(not (lathe or self.gl_view.orbit_locked))
        if lathe:
            # v1.6.5: 원점이 아니라 경로 바운딩박스 중심으로 맞춰야 지름이
            # 반경으로 변환된 경로가 화면 정중앙에 온다(밀링은 원래대로
            # 원점 recenter를 그대로 쓴다 — 아래 else 분기, 동작 불변).
            center, radius = self._lathe_path_center_and_radius()
            distance = self._distance_for_radius(radius) or self._ZOOM_TO_FIT_FALLBACK_DISTANCE
            self.set_camera_angles(elevation, azimuth, distance=distance, recenter=False)
            self.gl_view.setCameraPosition(pos=Vector(*center) if center is not None else Vector(0, 0, 0))
        else:
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

    _M30_RE = re.compile(r"M30(?!\d)")
    _M98_RE = re.compile(r"M98(?!\d)")
    _M98_P_RE = re.compile(r"P0*(\d+)(?!\d)")
    _M98_L_RE = re.compile(r"L0*(\d+)(?!\d)")
    _SUBPROGRAM_HEADER_RE = re.compile(r"^\s*O0*(\d+)\b")
    _LATHE_SUBPROGRAM_MAX_DEPTH = 10

    def _expand_lathe_subprograms(self, lines):
        """v1.6.6: 선반 M98 P<번호> [L<반복>] 서브프로그램 호출을 그 자리에
        펼친다. Fanuc 표준(사용자 확인): M30 뒤에 O<번호> 헤더로 시작하는
        서브프로그램이 붙고, 본문은 다음 O헤더(또는 파일 끝)까지다.

        반환값은 (원본 줄번호, 줄 텍스트) 쌍의 리스트다 — 서브프로그램
        본문은 같은 원본 줄번호로 여러 번 나올 수 있는데(반복 호출), 원본
        줄번호를 그대로 들고 있어야 src_line 기반 커서/공정 동기화가
        깨지지 않는다(에디터에서 그 줄을 클릭하면 그 줄이 '마지막으로
        실행된' 위치로 맞춰진다).

        정의되지 않은 P번호나 10단계를 넘는 재귀 호출은 조용히 무시한다
        (파싱이 죽지 않게) — 이번 단계는 M98/M99/M30만 다루고, U/W 증분
        지령이나 G90/G92/G94 선반 고정 사이클은 그대로 미구현으로 둔다
        (LATHE_MODE_GUIDELINES.md §8, 승인 후 별도 단계)."""
        m30_idx = None
        for i, raw in enumerate(lines):
            if self._M30_RE.search(self._code_without_comments(raw).upper()):
                m30_idx = i
                break

        subprograms = {}
        if m30_idx is not None:
            headers = []
            for i in range(m30_idx + 1, len(lines)):
                header_match = self._SUBPROGRAM_HEADER_RE.match(self._code_without_comments(lines[i]))
                if header_match:
                    headers.append((int(header_match.group(1)), i))
            for pos, (prog_no, start) in enumerate(headers):
                end = headers[pos + 1][1] if pos + 1 < len(headers) else len(lines)
                subprograms.setdefault(prog_no, (start + 1, end))

        main_end = m30_idx + 1 if m30_idx is not None else len(lines)

        def expand(index_range, depth):
            for i in index_range:
                raw = lines[i]
                code = self._code_without_comments(raw).upper()
                yield i, raw
                if depth >= self._LATHE_SUBPROGRAM_MAX_DEPTH or not self._M98_RE.search(code):
                    continue
                p_match = self._M98_P_RE.search(code)
                if not p_match:
                    continue
                body = subprograms.get(int(p_match.group(1)))
                if body is None:
                    continue
                l_match = self._M98_L_RE.search(code)
                repeat = max(1, int(l_match.group(1))) if l_match else 1
                for _ in range(repeat):
                    yield from expand(range(body[0], body[1]), depth + 1)

        return list(expand(range(0, main_end), 0))

    def _process_time_suffix(self, process_key):
        """v1.6.7: 공정별 경로 필터 항목 끝에 붙일 " | MM:SS" 조각.

        시간이 0초인 공정도 "00:00"으로 함께 적는다 — 공정마다 시간이
        붙었다 말았다 하면 목록을 훑을 때 오히려 헷갈린다. 아직 시간을
        계산하지 않았을 때(경로 파싱 전)만 빈 문자열이다."""
        if not self.process_time_sec:
            return ""
        seconds = self.process_time_sec.get(process_key)
        if seconds is None:
            return ""
        return " | %s" % format_duration(seconds)

    def _tool_display_text(self, process_key):
        tool_no = self.process_tool_map.get(process_key)
        if not tool_no:
            return "초기 구간"
        match = re.search(r"T(\d+)", tool_no, re.I)
        if not match:
            return "공정 | %s | 이름 없음%s" % (tool_no, self._process_time_suffix(process_key))
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
        return "%s | %s | %s%s" % (
            process_label, normalized_tool_no, name, self._process_time_suffix(process_key)
        )

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
        if MACHINE_5AXIS_AC in machine_type:
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
        self.line_to_c_rot.clear()
        self.line_feed_state.clear()
        self.line_to_elapsed_sec.clear()
        self._elapsed_line_keys = []
        self.process_time_sec.clear()
        self.total_time_sec = 0.0

        machine_type = self.current_machine_type
        is_lathe = is_lathe_machine(machine_type)
        is_4axis = "4축" in machine_type
        is_5axis_ac = MACHINE_5AXIS_AC in machine_type
        is_5axis_bc = MACHINE_5AXIS_BC in machine_type

        try:
            m_x = float(self.machine_specs[machine_type].get("X 행정", "500")) / 2.0
            m_y = float(self.machine_specs[machine_type].get("Y 행정", "500")) / 2.0
            m_z = float(self.machine_specs[machine_type].get("Z 행정", "500"))
        except (TypeError, ValueError):
            m_x, m_y, m_z = 250.0, 250.0, 300.0

        # v1.6.7 가공시간: 선반 G96/G97 회전수는 장비의 "최대 RPM"을 넘지
        # 못한다. 프로그램에 G50 S___가 나오면 그 값으로 다시 좁혀진다.
        try:
            spec_max_rpm = float(self.machine_specs[machine_type].get("최대 RPM", "0") or 0.0)
        except (TypeError, ValueError, KeyError):
            spec_max_rpm = 0.0

        current_tool = "Initial"
        self.tool_paths[current_tool] = []
        self.process_tool_map[current_tool] = ""
        self.process_first_line[current_tool] = 0

        cx, cy, cz = 0.0, 0.0, 0.0
        cc_deg = 0.0
        cb_deg = 0.0
        # v1.6.6: M35(구동공구) 턴밀 중 실제 기계 Y 워드(또는 G12.1 극좌표
        # 보간 중의 C 워드, 아래 참고)가 들어갈 자리. 선삭(M35 이전/M34
        # 이후)에는 항상 0으로 유지되어 v1.6.4 동작과 완전히 같다.
        cy_lathe = 0.0
        modal_values = ["0.000", "0.000", "0.000", "0.000", "0.000", "0.000"]

        g43_active = False
        current_motion = "G00"
        current_plane = "G17"
        polar_interpolation = False
        # v1.6.6: M35(구동공구 ON, 밀링 가공) ~ M34(선삭 복귀) 사이 상태.
        # is_lathe 분기 안에서만 세팅되며, 밀링 경로는 이 값을 전혀 읽지 않는다.
        lathe_milling_active = False
        g68_pending = False
        pending_i, pending_j, pending_k = 0.0, 0.0, 0.0
        active_matrix = np.eye(3)
        g98_active = False
        cycle_active = False
        detected_t = ""
        process_no = 0

        # v1.6.8: 선반 고정 사이클 전용 모달 상태. G81~G89/G73/G74/G76 중
        # 어느 것이든 활성화된 동안(G80까지) 유지된다. 밀링은 이 변수들을
        # 전혀 읽지 않는다(가이드라인 0항).
        lathe_cycle_axis = None      # "Z"(주축 방향, G17) 또는 "X"(지름 방향, G19)
        lathe_cycle_ref = None       # 사이클 진입 직전 위치 — Z축은 mm, X축은 반경(mm)
        lathe_cycle_r = 0.0          # 마지막 R 워드(반경 공간 증분값, 모달)
        lathe_cycle_depth = 0.0      # 마지막 깊이 워드(Z축=Z워드, X축=X워드=반경 증분, 모달)
        # 이 프로그램에서 G17/G18/G19가 한 번이라도 명시됐는가 — 명시됐다면
        # 사이클 방향 판정에서 평면이 워드 판정보다 우선한다(사용자 확정).
        lathe_plane_explicit = False

        # v1.6.7 가공시간용 모달 상태. F는 한 번 나오면 계속 유지되고
        # (G00 구간만 F를 무시하고 급속으로 본다), 선반은 여기에 더해
        # 이송 단위(G98 mm/min vs G99 mm/rev)와 회전 모드(G96/G97)를 든다.
        current_feed = 0.0
        lathe_feed_per_rev = True   # 선반 기본은 G99(mm/rev).
        # v1.6.7: 지금 진행 중인 선반 공정의 공구 번호(옵셋 취소용 Tnn00을
        # 새 공정으로 오인하지 않기 위한 기억). 밀링에서는 쓰이지 않는다.
        active_lathe_tool = None
        spindle_mode = "G97"
        spindle_value = 0.0
        max_rpm = spec_max_rpm

        t_pattern = re.compile(r"T0*(\d+)")
        m6_pattern = re.compile(r"M0?6(?!\d)")
        # 선반 툴체인지 기준은 Tnn00 (앞 두 자리 = 공구 번호, 뒤 두 자리 =
        # 옵셋 번호). 옵셋 00인 블록만 교체 지점이고, T0101처럼 옵셋이 살아
        # 있는 블록은 교체가 아니다. T0000은 옵셋 취소라 제외한다(v1.6.4).
        lathe_tool_change_pattern = re.compile(r"T(?!0000)(\d{2})00(?!\d)")
        # v1.6.6: M35 = 구동공구 ON(밀링 가공 진입), M34 = 선삭 복귀.
        # is_lathe 분기에서만 읽는다 — 밀링에는 애초에 이 코드가 없다.
        m35_pattern = re.compile(r"M35(?!\d)")
        m34_pattern = re.compile(r"M34(?!\d)")
        # v1.6.7: 선반 공정의 끝을 알리는 코드(M00/M01 옵셔널 스톱, M30 종료).
        # 여기서 "지금 물고 있는 공구" 기억을 지워, 같은 공구를 연속된 두
        # 공정에 다시 써도 각각 따로 잡히게 한다.
        lathe_process_end_pattern = re.compile(r"M(?:0?[01]|30)(?!\d)")
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
        # v1.6.8: 드릴링 계열 고정 사이클을 전부 인식한다. 밀링은 코드별
        # 동작을 구분하지 않고 전부 동일한 4점(접근/R점/깊이/복귀) 전개다
        # (Q 펙·P 드웰·G76/G87의 I/J 시프트는 이번 범위 밖, 사용자 확정).
        # G76은 여기서 밀링 파인보링과 같은 단순 드릴 계열로만 다룬다 —
        # 선반의 실제 다중 패스 나사가공 G76(G70~G76 복합 선삭)은 여전히
        # LATHE_MODE_GUIDELINES.md §8의 별도 승인 대상으로 남는다.
        cycle_pattern = re.compile(
            r"(G73|G74|G76|G81|G82|G83|G84|G85|G86|G87|G88|G89|G80)"
        )
        # v1.6.7 가공시간. G50S___(최대 회전수)는 먼저 떼어내고 나서 S를
        # 찾아야 "G50S2500G96S180" 같은 줄에서 상한을 절삭속도로 오인하지
        # 않는다.
        f_pattern = re.compile(r"F\s*([+-]?\d*\.?\d+)")
        s_pattern = re.compile(r"S\s*(\d*\.?\d+)")
        g50_s_pattern = re.compile(r"G50\s*S\s*(\d*\.?\d+)")
        g96_pattern = re.compile(r"G96(?!\d)")
        g97_pattern = re.compile(r"G97(?!\d)")

        # v1.6.6: 선반만 M98 서브프로그램 호출을 그 자리에 펼친 시퀀스를
        # 돈다 — 밀링은 항상 원래 enumerate(lines) 그대로라 동작이
        # 전혀 바뀌지 않는다(가이드라인 0항).
        line_sequence = self._expand_lathe_subprograms(lines) if is_lathe else enumerate(lines)
        for idx, line in line_sequence:
            line_upper_with_comments = line.upper().replace(" ", "")
            line_upper = self._code_without_comments(line).upper().replace(" ", "")

            for pos, pattern in enumerate((x_pattern, y_pattern, z_pattern, a_pattern, b_pattern, c_pattern)):
                match = pattern.search(line_upper)
                if match:
                    modal_values[pos] = match.group(1)
            self.modal_state_map[idx] = tuple(modal_values)
            # v1.6.6: 이 줄 시작 시점의 C 회전각으로 우선 채워 두고, 이 줄에서
            # 실제로 C가 갱신되면(아래 is_lathe 모션 블록) 그 값으로 덮어쓴다
            # — G12.1 극좌표 중에는 cc_deg가 그대로라 자연히 이전 값이 유지된다.
            self.line_to_c_rot[idx] = cc_deg

            comment_t_match = t_pattern.search(line_upper_with_comments)
            if comment_t_match:
                detected_t = self._normalize_tool_no(comment_t_match.group(1))

            if not line_upper:
                self.line_to_tool_map[idx] = current_tool
                continue

            self.line_to_tool_map[idx] = current_tool

            # v1.6.7 가공시간: 이 줄에서 유효한 이송/회전 상태를 갱신해
            # 둔다. 경로 계산에는 전혀 관여하지 않고, 파싱이 끝난 뒤
            # _compute_machining_times()가 src_line으로 되읽는다.
            f_match = f_pattern.search(line_upper)
            if f_match:
                try:
                    feed_value = float(f_match.group(1))
                except ValueError:
                    feed_value = 0.0
                if feed_value > 0.0:
                    current_feed = feed_value
            if is_lathe:
                # 선반만 이송 단위와 회전 모드를 읽는다 — 밀링의 G98/G99는
                # 고정 사이클 복귀 레벨이라 뜻이 다르다(가이드라인 0항).
                if g99_pattern.search(line_upper):
                    lathe_feed_per_rev = True
                elif g98_pattern.search(line_upper):
                    lathe_feed_per_rev = False
                spindle_scan = line_upper
                g50_s_match = g50_s_pattern.search(spindle_scan)
                if g50_s_match:
                    try:
                        max_rpm = float(g50_s_match.group(1))
                    except ValueError:
                        pass
                    spindle_scan = (
                        spindle_scan[:g50_s_match.start()] + spindle_scan[g50_s_match.end():]
                    )
                if g96_pattern.search(spindle_scan):
                    spindle_mode = "G96"
                elif g97_pattern.search(spindle_scan):
                    spindle_mode = "G97"
                s_match = s_pattern.search(spindle_scan)
                if s_match:
                    try:
                        spindle_value = float(s_match.group(1))
                    except ValueError:
                        pass
                self.line_feed_state[idx] = (
                    current_feed, lathe_feed_per_rev, spindle_mode, spindle_value, max_rpm
                )
            else:
                self.line_feed_state[idx] = (current_feed, False, "", 0.0, 0.0)

            if g17_pattern.search(line_upper):
                current_plane = "G17"
                plane_seen_this_line = True
            elif g18_pattern.search(line_upper):
                current_plane = "G18"
                plane_seen_this_line = True
            elif g19_pattern.search(line_upper):
                current_plane = "G19"
                plane_seen_this_line = True
            else:
                plane_seen_this_line = False
            if is_lathe and plane_seen_this_line:
                # v1.6.8: 선반 고정 사이클의 방향(Z축/X축) 판정에만 쓰인다 —
                # 평면 자체의 의미나 밀링 원호 처리는 손대지 않는다.
                lathe_plane_explicit = True

            # v1.6.6: M35(구동공구 ON) ~ M34(선삭 복귀) — is_lathe 분기에서만.
            if is_lathe:
                if m35_pattern.search(line_upper):
                    lathe_milling_active = True
                elif m34_pattern.search(line_upper):
                    lathe_milling_active = False
                    cy_lathe = 0.0

            if g12_1_pattern.search(line_upper):
                polar_interpolation = True
                # v1.6.6: 선반 M35 구간의 G12.1은 같은 블록에 모션 워드가
                # 붙을 수 있어(예: "G1X0.C0.F5000.") 그냥 넘기면 안 된다.
                # 그 외(밀링, 선반이라도 구동공구 밀링 밖)는 기존처럼 스킵.
                if not (is_lathe and lathe_milling_active):
                    continue
            if g13_1_pattern.search(line_upper):
                polar_interpolation = False
                if not (is_lathe and lathe_milling_active):
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
                if is_lathe and cycle_code == "G80":
                    # v1.6.8: 취소 시 사이클 모달 상태를 전부 비운다 — 다음
                    # 사이클이 R/깊이를 빠뜨린 기형 프로그램이어도 이전
                    # 사이클의 값이 새지 않도록.
                    lathe_cycle_axis = None
                    lathe_cycle_ref = None
                    lathe_cycle_r = 0.0
                    lathe_cycle_depth = 0.0

            # 공구 교체 판정 — 밀링/MCT는 M6 Tnn, 선반은 Tnn00 (v1.6.4).
            # 두 갈래를 완전히 분리해 밀링 경로에는 선반 규칙이 끼어들지 않는다.
            if is_lathe:
                lathe_tool_change = lathe_tool_change_pattern.search(line_upper)
                tool_changed = lathe_tool_change is not None
                if tool_changed:
                    detected_t = self._normalize_tool_no(lathe_tool_change.group(1))
                    # v1.6.7: 선반 공정은 T0100으로 시작해 옵셋 취소용
                    # T0100으로 끝난다 — 같은 공구 번호의 Tnn00이 다시
                    # 나온 것은 공정의 끝이지 새 공정이 아니므로 필터에
                    # 두 번 올리지 않는다. M00/M01/M30을 지난 뒤라면
                    # 기억이 지워져 있어 같은 공구라도 새 공정이 된다.
                    if detected_t == active_lathe_tool:
                        tool_changed = False
                    else:
                        active_lathe_tool = detected_t
                if lathe_process_end_pattern.search(line_upper):
                    active_lathe_tool = None
            else:
                t_match = t_pattern.search(line_upper)
                if t_match:
                    detected_t = self._normalize_tool_no(t_match.group(1))
                tool_changed = m6_pattern.search(line_upper) is not None

            if tool_changed:
                process_no += 1
                current_tool = self._make_process_key(process_no, detected_t)
                self.tool_paths[current_tool] = []
                self.process_tool_map[current_tool] = detected_t
                self.process_first_line[current_tool] = idx
                start_point = (
                    lathe_world_point(cz, cx, cc_deg) if is_lathe else [cx, cy, cz]
                )
                self.tool_paths[current_tool].append({
                    "pt": start_point, "type": current_motion,
                    "valid": True if is_lathe else g43_active, "src_line": idx,
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
                if is_lathe:
                    # v1.6.4: 선반의 원점 복귀. cx는 지름 값을 들고 있으므로
                    # 반쪽(m_x)이 아니라 X 행정 전체를 지름으로 넣어야 반경이
                    # 행정의 절반이 된다.
                    if re.search(r"X\s*0", line_upper):
                        cx = m_x * 2.0
                    if re.search(r"Z\s*0", line_upper):
                        cz = m_z
                    final_pt = lathe_world_point(cz, cx, cc_deg)
                    self.tool_paths[current_tool].append({
                        "pt": final_pt, "type": "G00", "valid": True, "src_line": idx,
                    })
                    self.line_to_coord_map[idx] = final_pt
                    continue
                if re.search(r"X\s*0", line_upper):
                    cx = m_x
                if re.search(r"Y\s*0", line_upper):
                    cy = m_y
                if re.search(r"Z\s*0", line_upper):
                    cz = m_z
                if g43_active:
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
                    # v1.6.4 선반 모드: cx는 프로그램에 적힌 **지름** 값을 그대로
                    # 들고 있고, 월드 좌표로 내릴 때만 반경(X/2)으로 환산한다
                    # (lathe_local_point). 축도 여기서 스왑된다 — 기계 Z가 월드
                    # X(수평), 기계 X 반경이 월드 Z(수직).
                    # v1.6.6: M35(구동공구) 중에는 로컬(회전 전) 좌표도 같이
                    # 들고 있는다 — 원호를 로컬 평면에서 그린 뒤 C만큼 통째로
                    # 회전시키기 위해서다(4/5축 밀링과 같은 방식, v1.4.5).
                    start_local = lathe_local_point(cz, cx, cy_lathe)
                    start_pt = lathe_rotate_c(start_local, cc_deg)
                    if x_match:
                        cx = float(x_match.group(1))
                    if z_match:
                        cz = float(z_match.group(1))
                    if is_lathe and lathe_milling_active and polar_interpolation:
                        # G12.1 극좌표 보간: C 워드는 각도가 아니라 Y(직선,
                        # mm)로 해석한다(회전각 cc_deg는 그대로 유지) —
                        # O4006.nc:107 "X-.076Z-11.C-.067R.077"처럼 R.077짜리
                        # 원호에 C가 mm 단위로 붙는 것이 근거.
                        if c_match:
                            cy_lathe = float(c_match.group(1))
                    else:
                        if c_match:
                            cc_deg = float(c_match.group(1))
                            self.line_to_c_rot[idx] = cc_deg
                        if lathe_milling_active and y_match:
                            # M35 구동공구 밀링의 실제 기계 Y워드(예: O1699.nc
                            # "C270.Y0." 이후 구간) — C는 고정 인덱스 각도로
                            # 유지되고 Y만 갱신된다.
                            cy_lathe = float(y_match.group(1))
                    target_local = lathe_local_point(cz, cx, cy_lathe)
                    target_pt = lathe_rotate_c(target_local, cc_deg)
                    local_target_pt = target_local
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

                if cycle_active and is_lathe:
                    # v1.6.8 재작성: 선반 사이클의 R/깊이 워드는 밀링과 달리
                    # 사이클 진입 직전 위치에서의 **증분**이다(사용자 확정,
                    # 2026-09-06). 방향은 평면이 한 번이라도 명시됐으면
                    # G19=X축(지름 방향)/그 외=Z축(주축 방향)을 그대로
                    # 따르고, 평면이 전혀 없었으면 이 사이클 블록에 Z 워드가
                    # 있는지로 자동 판정한다(Z 있으면 Z축, X만 있으면 X축).
                    # start_local은 이 줄의 X/Z 갱신 **이전** 위치라 기준점으로
                    # 그대로 쓸 수 있다.
                    is_cycle_def_line = cycle_match is not None
                    if lathe_plane_explicit:
                        axis = "X" if current_plane == "G19" else "Z"
                    elif is_cycle_def_line:
                        axis = "Z" if z_match else "X"
                    else:
                        axis = lathe_cycle_axis or "Z"

                    if is_cycle_def_line or lathe_cycle_axis != axis or lathe_cycle_ref is None:
                        lathe_cycle_axis = axis
                        lathe_cycle_ref = start_local[0] if axis == "Z" else start_local[2]

                    if r_cycle_match:
                        lathe_cycle_r = float(r_cycle_match.group(1))
                    if axis == "Z" and z_match:
                        lathe_cycle_depth = float(z_match.group(1))
                    elif axis == "X" and x_match:
                        lathe_cycle_depth = float(x_match.group(1))

                    # R과 깊이 모두 반경 공간(X축) 또는 Z 길이(Z축) 증분값 —
                    # 절반으로 나누지 않고 기준점에 그대로 더한다
                    # (LATHE_MODE_GUIDELINES.md §2의 I/R 반경값 규약과 동일).
                    r_target = lathe_cycle_ref + lathe_cycle_r
                    depth_target = lathe_cycle_ref + lathe_cycle_depth

                    if axis == "Z":
                        # 반대축(X, 지름)은 보통의 절대 위치 — 이 줄에서 이미
                        # 갱신된 cx를 그대로 쓴다.
                        approach_pt = lathe_world_point(start_local[0], cx, cc_deg)
                        r_point_pt = lathe_world_point(r_target, cx, cc_deg)
                        final_pt = lathe_world_point(depth_target, cx, cc_deg)
                        cz = start_local[0]  # 사이클은 항상 초기점으로 복귀(아래)
                    else:
                        # 반대축(Z)은 보통의 절대 위치 — 이 줄에서 이미 갱신된
                        # cz를 그대로 쓴다. r_target/depth_target은 반경값이라
                        # lathe_world_point(지름 인자)에 넘기려면 x2 한다.
                        approach_pt = lathe_world_point(cz, start_local[2] * 2.0, cc_deg)
                        r_point_pt = lathe_world_point(cz, r_target * 2.0, cc_deg)
                        final_pt = lathe_world_point(cz, depth_target * 2.0, cc_deg)
                        cx = start_local[2] * 2.0  # 사이클은 항상 초기점으로 복귀(아래)

                    self.tool_paths[current_tool].append({"pt": approach_pt, "type": "G00", "valid": True, "src_line": idx})
                    self.tool_paths[current_tool].append({"pt": r_point_pt, "type": "G00", "valid": True, "src_line": idx})
                    self.tool_paths[current_tool].append({"pt": final_pt, "type": "G01", "valid": True, "src_line": idx})
                    # v1.6.8: 선반은 g98_active(=이송 단위 G98/G99와 같은
                    # 변수) 상태와 무관하게 항상 초기점으로 복귀한다 — 기존
                    # 코드가 G99(선반 기본)에서 복귀 경로를 그리지 않던
                    # 문제를 바로잡는다.
                    self.tool_paths[current_tool].append({"pt": approach_pt, "type": "G00", "valid": True, "src_line": idx})
                    self.line_to_coord_map[idx] = final_pt
                    continue

                if cycle_active and g43_active:
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
                    if lathe_milling_active and not polar_interpolation and current_plane in ("G17", "G19"):
                        # v1.6.6: M35(구동공구) 중 G17/G19 평면 원호 — I/J/K가
                        # 회전 전 로컬 좌표계 기준이므로, 로컬(start_local/
                        # target_local) 평면에서 보간한 뒤 4/5축 밀링과 같은
                        # 방식으로 결과 전체를 C만큼 통째로 회전시킨다.
                        # G17=기계 X-Y(반경-Y), G19=기계 Y-Z(Y-기계Z) 평면.
                        plane_key = "LATHE_G17" if current_plane == "G17" else "LATHE_G19"
                        local_arc_pts = self._arc_points(
                            line_upper, start_local, target_local, current_motion, plane_key,
                            i_pattern, j_pattern, k_pattern, r_pattern,
                        )
                        for local_pt in local_arc_pts:
                            self.tool_paths[current_tool].append({
                                "pt": lathe_rotate_c(local_pt, cc_deg), "type": current_motion,
                                "valid": True, "src_line": idx,
                            })
                    else:
                        # v1.6.4: 선삭(또는 G12.1 극좌표) 원호는 전용 "LATHE"
                        # 평면으로 보간한다. start_pt/target_pt가 이미 반경
                        # 공간(월드 Z = X/2)이라 지름 개념이 원호에도 그대로
                        # 반영되고, 중심 오프셋 I(X방향)와 R은 선반 관례대로
                        # 반경 값이므로 다시 나누지 않는다. 회전행렬이
                        # 개입하지 않으므로 밀링 경로와는 무관하다.
                        arc_pts = self._arc_points(
                            line_upper, start_pt, target_pt, current_motion, "LATHE",
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
        self._compute_machining_times(is_lathe)
        self._build_path_items()
        self._refresh_tool_filter()
        self.set_cursor_line(self.current_cursor_line)

    def _compute_machining_times(self, is_lathe):
        """v1.6.7: 다 만들어진 tool_paths를 훑어 공정별/줄별 가공시간을 낸다.

        경로 계산에는 일절 손대지 않고 결과 좌표만 읽는다 — 세그먼트
        거리는 이미 그려진 점 사이 거리이고, 이송 상태는 점에 붙어 있는
        src_line으로 line_feed_state에서 되읽는다. 선반은 여기에 더해
        G99(mm/rev)를 그 순간의 회전수로 mm/min으로 환산한다.
        """
        self.line_to_elapsed_sec.clear()
        self.process_time_sec.clear()
        self.total_time_sec = 0.0

        elapsed = 0.0
        for process_key, points in self.tool_paths.items():
            process_start = elapsed
            prev_pt = None
            for point in points:
                pt = point.get("pt")
                if pt is None or len(pt) < 3:
                    continue
                src_line = point.get("src_line")
                if prev_pt is not None:
                    distance = float(np.linalg.norm(np.array(pt, dtype=float) - prev_pt))
                    if distance > 0.0:
                        feed_state = self.line_feed_state.get(src_line)
                        if feed_state is None:
                            feed = 0.0
                        elif is_lathe:
                            feed, per_rev, mode, spindle_value, max_rpm = feed_state
                            if per_rev:
                                # G99: F는 1회전당 이송량이라 회전수를 곱해야
                                # mm/min이 된다. G96 정속절삭이면 회전수가
                                # 지름에 따라 달라지므로 세그먼트 양 끝
                                # 지름의 평균으로 잡는다(선반 월드 좌표에서
                                # 반경 = hypot(Y, Z), 지름은 그 2배).
                                mean_diameter = (
                                    float(np.hypot(prev_pt[1], prev_pt[2]))
                                    + float(np.hypot(pt[1], pt[2]))
                                )
                                rpm = lathe_spindle_rpm(
                                    mode, spindle_value, mean_diameter, max_rpm
                                )
                                feed = feed * rpm
                        else:
                            feed = feed_state[0]
                        speed = effective_feed_mm_per_min(
                            point.get("type"), feed, distance
                        )
                        if speed > 0.0:
                            elapsed += distance / speed * 60.0
                if src_line is not None:
                    self.line_to_elapsed_sec[src_line] = elapsed
                prev_pt = np.array(pt, dtype=float)
            self.process_time_sec[process_key] = elapsed - process_start
        self.total_time_sec = elapsed
        self._elapsed_line_keys = sorted(self.line_to_elapsed_sec)

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

    def _rotate_gl_items(self, items, c_rot):
        """v1.6.6: GLLinePlotItem들을 주축(월드 X) 둘레로 c_rot도 만큼
        회전시킨다 — QMatrix4x4.rotate(angle, 1,0,0)은 lathe_rotate_c(pt, θ)의
        "표준 회전 by -θ"와 반대 부호라, θ=c_rot을 그대로 넘기면 그 점을
        만들 때 baked된 C 회전이 정확히 상쇄된다(선반 C축 시뮬레이션 —
        공구는 +X 센터에 고정되고 축(소재/경로)이 도는 것처럼 보이게).
        정적 전체 경로(plot_items)는 손대지 않는다 — 항목5 "툴패스를 볼 시에는
        지금과 같이 표현" 요구대로 항상 현재(v1.6.4~5) 모습 그대로 두고,
        회전은 시뮬레이션 커서를 따라 움직이는 동적 트레이스/커서 구에만 건다."""
        for item in items:
            item.resetTransform()
            if c_rot:
                item.rotate(c_rot, 1, 0, 0)

    def set_cursor_line(self, line_index):
        try:
            line_index = max(0, int(line_index))
        except (TypeError, ValueError):
            line_index = 0
        self.current_cursor_line = line_index

        modal_values = self.modal_state_map.get(line_index)
        if modal_values:
            self._set_coordinate_labels(modal_values)
        self._update_time_overlay(line_index)

        # v1.6.6: 선반 C축 회전 시뮬레이션. 밀링에서는 항상 0(변화 없음) —
        # is_lathe_mode()가 아니면 line_to_c_rot 자체가 채워지지 않는다.
        c_rot = self.line_to_c_rot.get(line_index, 0.0) if self.is_lathe_mode() else 0.0

        current_tool = self.line_to_tool_map.get(line_index)
        current_pt = self.line_to_coord_map.get(line_index)
        if current_tool and current_pt is not None and self._tool_selected(current_tool):
            self.cursor_sphere.resetTransform()
            # 커서 구는 회전 성분을 뺀 위치에 둔다 — 화면상 항상 +X 센터
            # (주축 수직 위, M35 Y밀링이면 거기서 Y만큼 오프셋)에 고정된다.
            sphere_pt = lathe_rotate_c(current_pt, -c_rot) if c_rot else current_pt
            self.cursor_sphere.translate(sphere_pt[0], sphere_pt[1], sphere_pt[2])
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
        # v1.6.6: 새로 만들어진 동적 트레이스 아이템은 항등 변환으로
        # 시작하므로, 매 틱마다 커서 구와 같은 C 역회전을 걸어준다 —
        # 시뮬레이션 진행 중에만 보이는 트레이스라 정적 경로(plot_items)와
        # 달리 항목4의 "공구 고정" 요구가 그대로 적용된다.
        self._rotate_gl_items(self.dynamic_trace_items, c_rot)

    def elapsed_seconds_at_line(self, line_index):
        """v1.6.7: 그 줄까지의 누적 가공시간(초). 경로 점이 없는 줄(주석,
        공구 교체 블록 등)은 그보다 앞선 줄 중 가장 가까운 값을 쓴다 —
        커서를 그런 줄에 올려도 시간이 0으로 튀지 않게 한다."""
        if not self.line_to_elapsed_sec:
            return 0.0
        value = self.line_to_elapsed_sec.get(line_index)
        if value is not None:
            return value
        # 재생 중 매 틱마다 불리므로 미리 정렬해 둔 키에 이분 탐색을 건다.
        position = bisect.bisect_right(self._elapsed_line_keys, line_index)
        if position == 0:
            return 0.0
        return self.line_to_elapsed_sec[self._elapsed_line_keys[position - 1]]

    def _update_time_overlay(self, line_index):
        """좌표 오버레이 끝의 "진행중인 시간 / 전체 시간"을 갱신한다(v1.6.7)."""
        overlay = getattr(self, "coord_overlay", None)
        if overlay is None:
            return
        try:
            overlay.set_time_text(
                format_elapsed_over_total(
                    self.elapsed_seconds_at_line(line_index), self.total_time_sec
                )
            )
        except Exception:
            pass

    def _set_coordinate_labels(self, values):
        for axis, value in zip(("X", "Y", "Z", "A", "B", "C"), values):
            label = self.coord_labels.get(axis)
            if label is not None:
                label.setText(str(value))
