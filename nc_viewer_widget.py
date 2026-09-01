# -*- coding: utf-8 -*-
"""Embedded PyQt 3D NC path viewer widget."""
import json
import re

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtCore import Qt, QSettings, QSignalBlocker
from PyQt5.QtGui import QColor
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


class NCViewerWidget(QWidget):
    """Viewer-only widget used inside the main tool-list application."""

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
        self.tool_filter_list = None
        self.last_source_text = None
        self.line_to_coord_map = {}
        self.line_to_tool_map = {}
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

        self.gl_view = gl.GLViewWidget()
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
        self.tool_filter_list = list_widget
        self.tool_filter_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.tool_filter_list.itemSelectionChanged.connect(self.update_visible_paths)
        self._refresh_tool_filter()

    def set_tool_name_map(self, tool_name_map):
        self.tool_name_map = dict(tool_name_map or {})
        self._refresh_tool_filter(keep_selection=True)

    def set_source_text(self, text, tool_name_map=None):
        if tool_name_map is not None:
            self.tool_name_map = dict(tool_name_map)
        text = text or ""
        self.last_source_text = text
        self.raw_lines = text.splitlines()
        self.process_nc_lines(self.raw_lines)
        self.set_cursor_line(self.current_cursor_line)

    def clear(self):
        self.last_source_text = ""
        self.raw_lines = []
        self._clear_path_items()
        self.tool_paths.clear()
        self.plot_items.clear()
        self.line_to_coord_map.clear()
        self.line_to_tool_map.clear()
        self.modal_state_map.clear()
        self.current_cursor_line = 0
        self._refresh_tool_filter()
        self._set_coordinate_labels(("0.000",) * 6)

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
            self.set_camera_projection("ISO")
        self._save_machine_specs()
        if self.last_source_text:
            self.process_nc_lines(self.raw_lines)

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

    def _tool_display_text(self, tool):
        match = re.search(r"T(\d+)", tool, re.I)
        if not match:
            return "%s | 이름 없음" % tool
        number = int(match.group(1))
        tool_no = "T%02d" % number
        name = (
            self.tool_name_map.get(tool_no)
            or self.tool_name_map.get("T%d" % number)
            or self.tool_name_map.get(str(number))
            or "이름 없음"
        )
        return "%s | %s" % (tool_no, name)

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
                item = QListWidgetItem(self._tool_display_text(tool))
                item.setData(Qt.UserRole, tool)
                item.setForeground(qcolor_from_float_rgb(tool_color_for_index(idx)))
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

    def process_nc_lines(self, lines):
        self._clear_path_items()
        self.tool_paths.clear()
        self.plot_items.clear()
        self.line_to_coord_map.clear()
        self.line_to_tool_map.clear()
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

        current_tool = "Default_Tool"
        self.tool_paths[current_tool] = []

        cx, cy, cz = 0.0, 0.0, 0.0
        cc_deg = 0.0
        cb_deg = 0.0
        modal_values = ["0.000", "0.000", "0.000", "0.000", "0.000", "0.000"]

        g43_active = False
        current_motion = "G00"
        polar_interpolation = False
        g68_pending = False
        pending_i, pending_j, pending_k = 0.0, 0.0, 0.0
        active_matrix = np.eye(3)
        g98_active = False
        cycle_active = False
        detected_t = "Default_Tool"

        t_pattern = re.compile(r"T(\d+)")
        m6_pattern = re.compile(r"M0?6")
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
            line_upper = line.upper().replace(" ", "")

            for pos, pattern in enumerate((x_pattern, y_pattern, z_pattern, a_pattern, b_pattern, c_pattern)):
                match = pattern.search(line_upper)
                if match:
                    modal_values[pos] = match.group(1)
            self.modal_state_map[idx] = tuple(modal_values)

            comment_t_match = t_pattern.search(line_upper)
            if comment_t_match:
                detected_t = "Tool T%s" % comment_t_match.group(1)

            if "(" in line_upper or ";" in line_upper:
                self.line_to_tool_map[idx] = current_tool
                continue

            self.line_to_tool_map[idx] = current_tool

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
            elif g99_pattern.search(line_upper):
                g98_active = False

            cycle_match = cycle_pattern.search(line_upper)
            if cycle_match:
                cycle_active = cycle_match.group(1) != "G80"

            t_match = t_pattern.search(line_upper)
            if t_match:
                detected_t = "Tool T%s" % t_match.group(1)

            if m6_pattern.search(line_upper):
                current_tool = detected_t
                if current_tool not in self.tool_paths:
                    self.tool_paths[current_tool] = []
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
                    if is_5axis_bc:
                        active_matrix = self.get_rotation_matrix(pending_i, pending_j, pending_k)
                    elif is_5axis_ac:
                        rad_a = np.radians(pending_j)
                        rad_c = np.radians(pending_i)
                        rad_k = np.radians(pending_k)
                        r_a = np.array([[1, 0, 0], [0, np.cos(rad_a), -np.sin(rad_a)], [0, np.sin(rad_a), np.cos(rad_a)]])
                        r_c = np.array([[np.cos(rad_c), -np.sin(rad_c), 0], [np.sin(rad_c), np.cos(rad_c), 0], [0, 0, 1]])
                        r_k = np.array([[np.cos(rad_k), -np.sin(rad_k), 0], [np.sin(rad_k), np.cos(rad_k), 0], [0, 0, 1]])
                        active_matrix = r_k @ r_c @ r_a
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

            if x_match or y_match or z_match or c_match or (cycle_active and r_cycle_match):
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
                else:
                    if x_match:
                        cx = float(x_match.group(1))
                    if y_match:
                        cy = float(y_match.group(1))
                    if z_match:
                        cz = float(z_match.group(1))
                    coord_vec = np.array([cx, cy, cz])
                    target_pt = (
                        active_matrix @ coord_vec
                    ).tolist() if (is_5axis_ac or is_5axis_bc or is_4axis) else [cx, cy, cz]

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

                if current_motion in ("G02", "G03") and (g43_active or is_lathe):
                    arc_pts = self._arc_points(
                        line_upper, start_pt, target_pt, current_motion,
                        i_pattern, j_pattern, r_pattern,
                    )
                    for pt in arc_pts:
                        self.tool_paths[current_tool].append({
                            "pt": pt, "type": current_motion, "valid": True, "src_line": idx,
                        })
                    self.line_to_coord_map[idx] = target_pt
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
        self._build_path_items()
        self._refresh_tool_filter()
        self.set_cursor_line(self.current_cursor_line)

    def _arc_points(self, line_upper, start_pt, target_pt, current_motion, i_pattern, j_pattern, r_pattern):
        i_val = float(i_pattern.search(line_upper).group(1)) if i_pattern.search(line_upper) else 0.0
        j_val = float(j_pattern.search(line_upper).group(1)) if j_pattern.search(line_upper) else 0.0
        center_x = start_pt[0] + i_val
        center_y = start_pt[1] + j_val
        r_match = r_pattern.search(line_upper)
        if r_match:
            radius = float(r_match.group(1))
            dx = target_pt[0] - start_pt[0]
            dy = target_pt[1] - start_pt[1]
            dist = np.hypot(dx, dy)
            if dist > 0:
                h = np.sqrt(max(0.0, radius ** 2 - (dist / 2) ** 2))
                sign = 1 if (current_motion == "G03" if radius > 0 else current_motion == "G02") else -1
                center_x = start_pt[0] + dx / 2 - sign * h * (dy / dist)
                center_y = start_pt[1] + dy / 2 + sign * h * (dx / dist)

        angle_start = np.arctan2(start_pt[1] - center_y, start_pt[0] - center_x)
        angle_end = np.arctan2(target_pt[1] - center_y, target_pt[0] - center_x)
        if current_motion == "G02" and angle_end >= angle_start:
            angle_end -= 2 * np.pi
        elif current_motion == "G03" and angle_end <= angle_start:
            angle_end += 2 * np.pi
        segments = max(2, int(abs(angle_end - angle_start) * 10))
        angles = np.linspace(angle_start, angle_end, segments)
        points = []
        for angle in angles[1:]:
            ratio = (angle - angle_start) / (angle_end - angle_start)
            points.append([
                center_x + np.cos(angle) * np.hypot(start_pt[0] - center_x, start_pt[1] - center_y),
                center_y + np.sin(angle) * np.hypot(start_pt[0] - center_x, start_pt[1] - center_y),
                start_pt[2] + (target_pt[2] - start_pt[2]) * ratio,
            ])
        return points

    def _build_path_items(self):
        for idx, (tool, path_data) in enumerate(self.tool_paths.items()):
            base_color = tool_color_for_index(idx)
            self.plot_items[tool] = []
            current_seg = []
            prev_type = None

            for node in path_data:
                if not node["valid"]:
                    if current_seg:
                        self.create_segment_item(tool, current_seg, prev_type, base_color)
                        current_seg = []
                    continue
                if prev_type is not None and node["type"] != prev_type:
                    if current_seg:
                        current_seg.append(node["pt"])
                        self.create_segment_item(tool, current_seg, prev_type, base_color)
                        current_seg = [node["pt"]]
                else:
                    current_seg.append(node["pt"])
                prev_type = node["type"]

            if current_seg:
                self.create_segment_item(tool, current_seg, prev_type, base_color)

    def create_segment_item(self, tool, pts_list, motion_type, base_color):
        if len(pts_list) < 2:
            return
        pts = np.array(pts_list, dtype=np.float32)
        if motion_type == "G00":
            color = [base_color[0], base_color[1], base_color[2], 0.45]
            width = 1.5
        else:
            color = [base_color[0], base_color[1], base_color[2], 1.0]
            width = 2.5
        line_item = gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True)
        self.gl_view.addItem(line_item)
        self.plot_items[tool].append(line_item)

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
            color = [base_color[0], base_color[1], base_color[2], 0.45]
            width = 1.5
        else:
            color = [base_color[0], base_color[1], base_color[2], 1.0]
            width = 3.5
        if index < len(self.dynamic_trace_items):
            item = self.dynamic_trace_items[index]
            item.setData(pos=pts, color=color, width=width)
            item.setVisible(True)
        else:
            item = gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True)
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
        current_seg = []
        prev_type = None
        trace_index = 0

        for node in self.tool_paths[current_tool]:
            if node.get("src_line", -1) > line_index:
                break
            if not node["valid"]:
                if self.update_trace_item(trace_index, current_seg, prev_type, base_color):
                    trace_index += 1
                current_seg = []
                prev_type = None
                continue
            if prev_type is not None and node["type"] != prev_type:
                if current_seg:
                    current_seg.append(node["pt"])
                    if self.update_trace_item(trace_index, current_seg, prev_type, base_color):
                        trace_index += 1
                    current_seg = [node["pt"]]
            else:
                current_seg.append(node["pt"])
            prev_type = node["type"]

        if self.update_trace_item(trace_index, current_seg, prev_type, base_color):
            trace_index += 1
        self._hide_dynamic_trace_from(trace_index)

    def _set_coordinate_labels(self, values):
        for axis, value in zip(("X", "Y", "Z", "A", "B", "C"), values):
            self.coord_labels[axis].setText(str(value))
