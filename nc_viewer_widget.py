# -*- coding: utf-8 -*-
"""Embedded PyQt 3D NC path viewer widget."""
import json
from math import radians, tan
import re

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtCore import Qt, QSettings, QSignalBlocker, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QMatrix4x4, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_orthographic_projection = True

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

        self._build_ui()
        self.set_machine_type(self.current_machine_type, init_camera=True)

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
            button.clicked.connect(lambda _checked=False, value=view_type: self.set_camera_projection(value))
            view_bar.addWidget(button)
        view_bar.addStretch()
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
        layout.addWidget(self.gl_view, 1)

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

    def set_camera_projection(self, view_type):
        if view_type == "ISO":
            self.gl_view.setCameraPosition(distance=200, elevation=30, azimuth=-45)
        elif view_type == "XY":
            self.gl_view.setCameraPosition(distance=200, elevation=90, azimuth=-90)
        elif view_type == "XZ":
            self.gl_view.setCameraPosition(distance=200, elevation=0, azimuth=-90)
        elif view_type == "YZ":
            self.gl_view.setCameraPosition(distance=200, elevation=0, azimuth=0)

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

    def update_visible_paths(self):
        selected_items = self.selected_tools()
        for tool, plot_item_list in self.plot_items.items():
            for item in plot_item_list:
                item.setVisible(tool in selected_items)
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
