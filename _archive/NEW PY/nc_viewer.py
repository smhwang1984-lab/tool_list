import sys
import re
import os
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QTextEdit, QPushButton, QListWidget, 
                             QLabel, QSplitter, QFileDialog, QComboBox, QLineEdit, 
                             QFormLayout, QSlider, QGroupBox)
from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextDocument, QKeyEvent
import pyqtgraph.opengl as gl

TOOL_COLOR_MAPS = [
    [1.0, 0.45, 0.10], [0.0, 0.70, 1.0], [0.20, 0.90, 0.25],
    [1.0, 0.25, 0.65], [0.95, 0.85, 0.10], [0.60, 0.35, 1.0],
    [0.00, 0.85, 0.70], [1.0, 0.55, 0.00], [0.65, 0.85, 1.0],
    [0.90, 0.45, 0.95], [0.45, 1.0, 0.45], [1.0, 0.80, 0.55],
]


def tool_color_for_index(index):
    return TOOL_COLOR_MAPS[index % len(TOOL_COLOR_MAPS)]


def qcolor_from_float_rgb(rgb):
    return QColor(*(max(0, min(255, int(channel * 255))) for channel in rgb))

# --- NC 코드 색상 관리를 위한 하이라이터 클래스 ---
class NCCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # G0, G00 (급속 이송) - 빨간색
        g0_format = QTextCharFormat()
        g0_format.setForeground(QColor("#FF3333"))
        g0_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((re.compile(r'\bG0*0\b'), g0_format))

        # G1, G01 (직선 절삭) - 녹색
        g1_format = QTextCharFormat()
        g1_format.setForeground(QColor("#33CC33"))
        g1_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((re.compile(r'\bG0*1\b'), g1_format))

        # G2, G02, G3, G03 (원호 절삭) - 하늘색
        arc_format = QTextCharFormat()
        arc_format.setForeground(QColor("#00CCFF"))
        arc_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((re.compile(r'\bG0*[23]\b'), arc_format))

        # G98, G99 (고정 사이클 복귀 모드) - 보라색
        g98_format = QTextCharFormat()
        g98_format.setForeground(QColor("#CC66FF"))
        g98_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((re.compile(r'\bG9[89]\b'), g98_format))

        # 고정 사이클 기능어 (G73, G81, G83, G84, G85 등) - 주황색
        cycle_format = QTextCharFormat()
        cycle_format.setForeground(QColor("#FF9933"))
        cycle_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((re.compile(r'\bG(73|81|83|84|85|80)\b'), cycle_format))

        # T코드 및 M코드 - 분홍색 계열
        tm_format = QTextCharFormat()
        tm_format.setForeground(QColor("#FF66CC"))
        self.highlighting_rules.append((re.compile(r'\b[TM]\d+\b'), tm_format))

        # 주석문 (괄호 안) - 회색 처리
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#888888"))
        comment_format.setFontItalic(True)
        self.highlighting_rules.append((re.compile(r'\(.*?\)|;.*'), comment_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            expression = pattern.finditer(text)
            for match in expression:
                start, end = match.span()
                self.setFormat(start, end - start, format)


class NCPageKeyTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewer_app = None

    def set_viewer_app(self, app_instance):
        self.viewer_app = app_instance

    def keyPressEvent(self, event: QKeyEvent):
        super().keyPressEvent(event)
        if event.key() in [Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_PageUp, Qt.Key_PageDown]:
            if self.viewer_app:
                self.viewer_app.track_cursor_position()


class NCViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NC Code 3D Path Viewer (M6 공구 분할 및 G28 기계 원점 대응)")
        self.setGeometry(100, 100, 1500, 950)
        
        self.setAcceptDrops(True)
        self.settings = QSettings("MyCompany", "NCViewerApp")
        
        self.tool_paths = {}  
        self.plot_items = {}  
        self.raw_lines = []   
        self.line_to_coord_map = {} 
        self.line_to_tool_map = {} 
        
        # 시뮬레이션 상태 변수
        self.sim_timer = QTimer()
        self.sim_timer.timeout.connect(self.play_next_step)
        self.current_sim_index = 0
        self.all_parsed_points = [] 
        self.sim_point_tools = []        # 각 포인트별 공구 매핑 리스트 추가[cite: 1]
        self.stop_at_next_tool = False    # 공구 단위 정지 재생 플래그 추가[cite: 1]
        self.target_tool_change_index = -1 # 다음 정지 대상 인덱스[cite: 1]
        
        # 실시간 트레이스(경로보기) 세그먼트 아이템들을 저장할 리스트
        self.dynamic_trace_items = []
        
        self.machine_specs = {
            "5축 밀링 (A to C)": {"X 행정": "800", "Y 행정": "800", "Z 행정": "600", "A축 범위": "-120~+30", "C축 범위": "360"},
            "3축 MCT (X Y 지)": {"X 행정": "1000", "Y 행정": "600", "Z 행정": "600"},
            "4축 MCT (B-Type)": {"X 행정": "1200", "Y 행정": "800", "Z 행정": "800", "B축 범위": "-120~+120"},
            "2축 선반 (X Z 평면, X 2배)": {"X 행정": "300", "Z 행정": "500", "최대 RPM": "4000"},
            "5축 밀링 (B to C)": {"X 행정": "600", "Y 행정": "600", "Z 행정": "500", "B축 범위": "-110~+110", "C축 범위": "360"}
        }
        
        self.init_ui()
        self.change_machine_type(init_camera=True)
        # self.showMaximized() <- 창 크기 최대화 기능 제거하여 본래 상태 복구[cite: 1]

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        splitter = QSplitter(Qt.Horizontal)
        
        # --- [좌측 제어부] ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        left_layout.addWidget(QLabel("⚙️ [장비 타입 및 스펙 설정]"))
        self.combo_machine = QComboBox()
        self.combo_machine.addItems(list(self.machine_specs.keys()))
        self.combo_machine.currentIndexChanged.connect(lambda: self.change_machine_type(init_camera=False))
        left_layout.addWidget(self.combo_machine)
        
        self.spec_form_widget = QWidget()
        self.spec_form_layout = QFormLayout(self.spec_form_widget)
        self.spec_form_layout.setContentsMargins(0, 5, 0, 5)
        left_layout.addWidget(self.spec_form_widget)
        
        btn_save_spec = QPushButton("💾 현재 장비 스펙 기록/저장")
        btn_save_spec.setStyleSheet("background-color: #555555; color: white; font-size: 11px;")
        btn_save_spec.clicked.connect(self.save_current_spec)
        left_layout.addWidget(btn_save_spec)
        
        left_layout.addWidget(QLabel("<hr>"))
        
        left_layout.addWidget(QLabel("1. NC 파일 로드 (드래그 앤 드ロップ 가능):"))
        self.btn_open_file = QPushButton("📁 NC 파일 원본 열기 (.nc / .txt / .tap)")
        self.btn_open_file.setFixedHeight(40)
        self.btn_open_file.setStyleSheet("background-color: #2b579a; color: white; font-weight: bold; border-radius: 4px;")
        self.btn_open_file.clicked.connect(self.open_nc_file)
        left_layout.addWidget(self.btn_open_file)
        
        self.lbl_file_status = QLabel("선택된 파일 없음 (여기에 파일을 끌어다 놓으세요)")
        self.lbl_file_status.setStyleSheet("color: #888888; font-size: 11px; margin-bottom: 5px;")
        left_layout.addWidget(self.lbl_file_status)
        
        # --- [시뮬레이션 제어부] ---
        sim_group = QGroupBox("▶️ 가공 경로 재생 플레이어 (M6 공구 분할 순차 처리)")
        sim_layout = QVBoxLayout()
        btn_box = QHBoxLayout()
        
        self.btn_play = QPushButton("재생 (Play)")
        self.btn_tool_play = QPushButton("공구단위 재생") #[cite: 1]
        self.btn_pause = QPushButton("일시정지")
        self.btn_stop = QPushButton("정지 (Reset)")
        
        # 버튼 디자인 통일성 강화 (공구단위 재생은 포인트 색상 부여)[cite: 1]
        self.btn_tool_play.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold;")
        
        self.btn_play.clicked.connect(self.start_simulation)
        self.btn_tool_play.clicked.connect(self.start_tool_simulation) #[cite: 1]
        self.btn_pause.clicked.connect(self.pause_simulation)
        self.btn_stop.clicked.connect(self.stop_simulation)
        
        btn_box.addWidget(self.btn_play)
        btn_box.addWidget(self.btn_tool_play) #[cite: 1]
        btn_box.addWidget(self.btn_pause)
        btn_box.addWidget(self.btn_stop)
        sim_layout.addLayout(btn_box)
        
        speed_box = QHBoxLayout()
        speed_box.addWidget(QLabel("재생 속도 (가속 배속):"))
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(1, 100)
        self.slider_speed.setValue(15) 
        speed_box.addWidget(self.slider_speed)
        sim_layout.addLayout(speed_box)
        
        sim_group.setLayout(sim_layout)
        left_layout.addWidget(sim_group)
        
        # --- [T, S, M, G 코드 이력 창] ---
        self.history_box = QTextEdit()
        self.history_box.setReadOnly(True)
        self.history_box.setFixedHeight(110)
        self.history_box.setStyleSheet("background-color: #1e1e1e; color: #a6e22e; font-family: Consolas, monospace; font-size: 11px;")
        self.history_box.setPlaceholderText("T, S, M, G 코드 이력 실시간 기록...")
        left_layout.addWidget(QLabel("📜 코드 이력 (T, S, M, G):"))
        left_layout.addWidget(self.history_box)
        
        left_layout.addWidget(QLabel("2. NC 데이터 편집/확인 (M6 이후 실시간 추적):"))
        
        self.nc_input = NCPageKeyTextEdit()
        self.nc_input.set_viewer_app(self)
        self.nc_input.setPlaceholderText("NC 코드가 표시됩니다. 줄 클릭 시 해당 공구 패스 위치가 3D 동기화됩니다.")
        self.nc_input.setReadOnly(True)
        self.nc_input.cursorPositionChanged.connect(self.track_cursor_position)
        
        self.highlighter = NCCodeHighlighter(self.nc_input.document())
        left_layout.addWidget(self.nc_input)

        self.btn_toggle_readonly = QPushButton("🔒 NC 코드 편집 모드 (Read-Only 해제)")
        self.btn_toggle_readonly.setCheckable(True)
        self.btn_toggle_readonly.setStyleSheet("background-color: #555555; color: white; padding: 4px;")
        self.btn_toggle_readonly.clicked.connect(self.toggle_readonly_mode)
        left_layout.addWidget(self.btn_toggle_readonly)
        
        search_layout = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 프로그램 내 코드 검색...")
        self.txt_search.returnPressed.connect(self.search_nc_text)
        btn_search = QPushButton("찾기")
        btn_search.clicked.connect(self.search_nc_text)
        search_layout.addWidget(self.txt_search)
        search_layout.addWidget(btn_search)
        left_layout.addLayout(search_layout)
        
        # --- [RESET 버튼 추가] ---
        self.btn_reset_cursor = QPushButton("🔄 RESET (선두행 이동)")
        self.btn_reset_cursor.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; min-height: 28px;")
        self.btn_reset_cursor.clicked.connect(self.reset_cursor_to_top)
        left_layout.addWidget(self.btn_reset_cursor)
        
        trace_nav_layout = QVBoxLayout()
        
        self.btn_toggle_trace = QPushButton("👁️ 경로보기 (비활성)")
        self.btn_toggle_trace.setCheckable(True)
        self.btn_toggle_trace.setStyleSheet("background-color: #444444; color: white; font-weight: bold; min-height: 32px; font-size: 12px;")
        self.btn_toggle_trace.clicked.connect(self.toggle_trace_mode)
        
        jump_row1_layout = QHBoxLayout()
        btn_m300 = QPushButton("-300")
        btn_m200 = QPushButton("-200")
        btn_m100 = QPushButton("-100")
        btn_m50 = QPushButton("-50")
        btn_m10 = QPushButton("-10")
        
        jump_row2_layout = QHBoxLayout()
        btn_p10 = QPushButton("+10")
        btn_p50 = QPushButton("+50")
        btn_p100 = QPushButton("+100")
        btn_p200 = QPushButton("+200")
        btn_p300 = QPushButton("+300")
        
        for btn in [btn_m300, btn_m200, btn_m100, btn_m50, btn_m10, btn_p10, btn_p50, btn_p100, btn_p200, btn_p300]:
            btn.setStyleSheet("font-size: 11px; font-weight: bold; padding: 6px 3px; background-color: #e1e1e1; border: 1px solid #ababab; border-radius: 3px;")
            btn.setFixedWidth(56)
            btn.setFixedHeight(30)
            
        btn_m300.clicked.connect(lambda: self.jump_cursor_lines(-300))
        btn_m200.clicked.connect(lambda: self.jump_cursor_lines(-200))
        btn_m100.clicked.connect(lambda: self.jump_cursor_lines(-100))
        btn_m50.clicked.connect(lambda: self.jump_cursor_lines(-50))
        btn_m10.clicked.connect(lambda: self.jump_cursor_lines(-10))
        btn_p10.clicked.connect(lambda: self.jump_cursor_lines(10))
        btn_p50.clicked.connect(lambda: self.jump_cursor_lines(50))
        btn_p100.clicked.connect(lambda: self.jump_cursor_lines(100))
        btn_p200.clicked.connect(lambda: self.jump_cursor_lines(200))
        btn_p300.clicked.connect(lambda: self.jump_cursor_lines(300))
        
        jump_row1_layout.addWidget(btn_m300)
        jump_row1_layout.addWidget(btn_m200)
        jump_row1_layout.addWidget(btn_m100)
        jump_row1_layout.addWidget(btn_m50)
        jump_row1_layout.addWidget(btn_m10)
        
        jump_row2_layout.addWidget(btn_p10)
        jump_row2_layout.addWidget(btn_p50)
        jump_row2_layout.addWidget(btn_p100)
        jump_row2_layout.addWidget(btn_p200)
        jump_row2_layout.addWidget(btn_p300)
        
        trace_nav_layout.addWidget(self.btn_toggle_trace)
        trace_nav_layout.addLayout(jump_row1_layout)
        trace_nav_layout.addLayout(jump_row2_layout)
        left_layout.addLayout(trace_nav_layout)
        
        self.btn_load = QPushButton("입력창 데이터 재파싱")
        self.btn_load.setFixedHeight(30)
        self.btn_load.clicked.connect(self.parse_from_textedit)
        left_layout.addWidget(self.btn_load)
        
        left_layout.addWidget(QLabel("3. 공구별 경로 필터 선택:"))
        
        tool_ctrl_layout = QHBoxLayout()
        self.btn_prev_tool = QPushButton("<< 이전 공구 (M6)")
        self.btn_next_tool = QPushButton("다음 공구 (M6) >>")
        self.btn_prev_tool.clicked.connect(self.select_prev_tool)
        self.btn_next_tool.clicked.connect(self.select_next_tool)
        tool_ctrl_layout.addWidget(self.btn_prev_tool)
        tool_ctrl_layout.addWidget(self.btn_next_tool)
        left_layout.addLayout(tool_ctrl_layout)
        
        self.tool_list = QListWidget()
        self.tool_list.setSelectionMode(QListWidget.MultiSelection)
        self.tool_list.itemSelectionChanged.connect(self.update_visible_paths)
        left_layout.addWidget(self.tool_list)
        
        # --- [우측 3D 뷰어 컴포지션] ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        view_bar_layout = QHBoxLayout()
        view_bar_layout.setContentsMargins(5, 5, 5, 5)
        view_bar_layout.addWidget(QLabel("📐 투영 뷰 옵션:"))
        
        btn_view_iso = QPushButton("ISO (입체)")
        btn_view_xy = QPushButton("XY (평면)")
        btn_view_xz = QPushButton("XZ (정면)")
        btn_view_yz = QPushButton("YZ (측면)")
        
        btn_view_iso.clicked.connect(lambda: self.set_camera_projection("ISO"))
        btn_view_xy.clicked.connect(lambda: self.set_camera_projection("XY"))
        btn_view_xz.clicked.connect(lambda: self.set_camera_projection("XZ"))
        btn_view_yz.clicked.connect(lambda: self.set_camera_projection("YZ"))
        
        view_bar_layout.addWidget(btn_view_iso)
        view_bar_layout.addWidget(btn_view_xy)
        view_bar_layout.addWidget(btn_view_xz)
        view_bar_layout.addWidget(btn_view_yz)
        view_bar_layout.addStretch()
        right_layout.addLayout(view_bar_layout)
        
        # --- [실시간 좌표 표시부 (유지)] ---[cite: 1]
        coord_group = QGroupBox("📌 실시간 좌표 창 (Current Coordinates)")
        coord_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 11px; margin: 2px; padding-top: 10px; } QLabel { font-size: 14px; font-weight: bold; }")
        coord_group.setFixedHeight(52)  
        
        coord_layout = QHBoxLayout(coord_group)
        coord_layout.setContentsMargins(15, 2, 15, 2)
        coord_layout.setSpacing(25)     
        
        lbl_t_x = QLabel("X:"); self.lbl_x = QLabel("0.000"); self.lbl_x.setStyleSheet("color: #FF3333;")
        lbl_t_y = QLabel("Y:"); self.lbl_y = QLabel("0.000"); self.lbl_y.setStyleSheet("color: #33CC33;")
        lbl_t_z = QLabel("Z:"); self.lbl_z = QLabel("0.000"); self.lbl_z.setStyleSheet("color: #5555FF;")
        lbl_t_a = QLabel("A:"); self.lbl_a = QLabel("0.000"); self.lbl_a.setStyleSheet("color: #CCCC00;")
        lbl_t_b = QLabel("B:"); self.lbl_b = QLabel("0.000"); self.lbl_b.setStyleSheet("color: #CC33CC;")
        lbl_t_c = QLabel("C:"); self.lbl_c = QLabel("0.000"); self.lbl_c.setStyleSheet("color: #33CCCC;")
        
        coord_layout.addWidget(lbl_t_x); coord_layout.addWidget(self.lbl_x)
        coord_layout.addWidget(lbl_t_y); coord_layout.addWidget(self.lbl_y)
        coord_layout.addWidget(lbl_t_z); coord_layout.addWidget(self.lbl_z)
        coord_layout.addWidget(lbl_t_a); coord_layout.addWidget(self.lbl_a)
        coord_layout.addWidget(lbl_t_b); coord_layout.addWidget(self.lbl_b)
        coord_layout.addWidget(lbl_t_c); coord_layout.addWidget(self.lbl_c)
        coord_layout.addStretch() 
        
        right_layout.addWidget(coord_group)
        
        # --- [3D 시뮬레이션 창 (유지)] ---[cite: 1]
        self.gl_view = gl.GLViewWidget()
        self.gl_view.setBackgroundColor(33, 37, 43, 255) 
        right_layout.addWidget(self.gl_view)
        
        self.grid = gl.GLGridItem()
        self.grid.setSize(400, 400, 1)
        self.grid.setSpacing(20, 20, 1)
        self.gl_view.addItem(self.grid)
        
        # 기본 내장축(AxisItem) 대신 무한 크기의 십자선(Crosshair) 구조 생성 및 배치
        infinite_val = 99999.0
        x_line = gl.GLLinePlotItem(pos=np.array([[-infinite_val, 0, 0], [infinite_val, 0, 0]]), color=(1.0, 0.2, 0.2, 0.8), width=1.5, antialias=True)
        y_line = gl.GLLinePlotItem(pos=np.array([[0, -infinite_val, 0], [0, infinite_val, 0]]), color=(0.2, 1.0, 0.2, 0.8), width=1.5, antialias=True)
        z_line = gl.GLLinePlotItem(pos=np.array([[0, 0, -infinite_val], [0, 0, infinite_val]]), color=(0.2, 0.2, 1.0, 0.8), width=1.5, antialias=True)
        self.gl_view.addItem(x_line)
        self.gl_view.addItem(y_line)
        self.gl_view.addItem(z_line)
        
        self.cursor_sphere = gl.GLMeshItem(
            meshdata=gl.MeshData.sphere(rows=10, cols=20, radius=2.0),
            smooth=True, color=(1.0, 1.0, 0.0, 1.0), shader='shaded'
        )
        self.cursor_sphere.setVisible(False)
        self.gl_view.addItem(self.cursor_sphere)
        
        self.sim_line_item = gl.GLLinePlotItem(color=(1.0, 1.0, 1.0, 0.9), width=3, antialias=True)
        self.gl_view.addItem(self.sim_line_item)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_container)
        splitter.setSizes([450, 1050])
        
        main_layout = QHBoxLayout(main_widget)
        main_layout.addWidget(splitter)

    def toggle_readonly_mode(self):
        if self.btn_toggle_readonly.isChecked():
            self.nc_input.setReadOnly(False)
            self.btn_toggle_readonly.setText("🔓 NC 코드 편집 모드 (입력 가능)")
            self.btn_toggle_readonly.setStyleSheet("background-color: #5cb85c; color: white; padding: 4px; font-weight: bold;")
        else:
            self.nc_input.setReadOnly(True)
            self.btn_toggle_readonly.setText("🔒 NC 코드 편집 모드 (Read-Only 해제)")
            self.btn_toggle_readonly.setStyleSheet("background-color: #555555; color: white; padding: 4px;")

    def set_camera_projection(self, view_type):
        if view_type == "ISO":
            self.gl_view.setCameraPosition(distance=200, elevation=30, azimuth=-45)
        elif view_type == "XY":
            self.gl_view.setCameraPosition(distance=200, elevation=90, azimuth=-90)
        elif view_type == "XZ":
            self.gl_view.setCameraPosition(distance=200, elevation=0, azimuth=-90)
        elif view_type == "YZ":
            self.gl_view.setCameraPosition(distance=200, elevation=0, azimuth=0)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.load_nc_from_path(file_path)
                break

    def change_machine_type(self, init_camera=False):
        while self.spec_form_layout.count():
            child = self.spec_form_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
                
        machine_type = self.combo_machine.currentText()
        specs = self.machine_specs[machine_type]
        
        self.spec_inputs = {}
        for key, value in specs.items():
            line_edit = QLineEdit(value)
            self.spec_form_layout.addRow(QLabel(f"• {key}:"), line_edit)
            self.spec_inputs[key] = line_edit
            
        if "선반" in machine_type: 
            self.grid.setSize(400, 400, 1) 
            if init_camera:
                self.set_camera_projection("XZ") 
                init_camera = False
        else: 
            self.grid.setSize(400, 400, 1)
            
        if init_camera:
            self.set_camera_projection("ISO")

        if self.raw_lines: self.process_nc_lines(self.raw_lines)

    def save_current_spec(self):
        machine_type = self.combo_machine.currentText()
        for key, line_edit in self.spec_inputs.items():
            self.machine_specs[machine_type][key] = line_edit.text()
        self.lbl_file_status.setText("⚙️ 장비 스펙 설정이 내부 기록되었습니다.")

    def open_nc_file(self):
        last_path = self.settings.value("last_nc_path", os.getcwd())
        file_path, _ = QFileDialog.getOpenFileName(
            self, "NC 파일 원본 열기", last_path, "NC Files (*.nc *.txt *.tap *.gcode);;All Files (*)"
        )
        if file_path:
            self.settings.setValue("last_nc_path", os.path.dirname(file_path))
            self.load_nc_from_path(file_path)

    def load_nc_from_path(self, file_path):
        filename = os.path.basename(file_path)
        self.lbl_file_status.setText(f"📄 로드됨: {filename}")
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            self.raw_lines = f.readlines()
        
        self.nc_input.setPlainText("".join(self.raw_lines))
        self.process_nc_lines(self.raw_lines)

    def parse_from_textedit(self):
        raw_text = self.nc_input.toPlainText()
        self.raw_lines = raw_text.split('\n')
        self.process_nc_lines(self.raw_lines)

    def search_nc_text(self):
        query = self.txt_search.text()
        if not query: return
        doc = self.nc_input.document()
        cursor = self.nc_input.textCursor()
        found_cursor = doc.find(query, cursor)
        
        if found_cursor.isNull():
            cursor.movePosition(cursor.Start)
            found_cursor = doc.find(query, cursor)
            
        if not found_cursor.isNull():
            self.nc_input.setTextCursor(found_cursor)
            self.nc_input.ensureCursorVisible()

    def reset_cursor_to_top(self):
        cursor = self.nc_input.textCursor()
        cursor.movePosition(cursor.Start)
        self.nc_input.setTextCursor(cursor)
        self.nc_input.ensureCursorVisible()
        self.track_cursor_position()

    def clear_dynamic_trace(self):
        for item in self.dynamic_trace_items:
            self.gl_view.removeItem(item)
        self.dynamic_trace_items.clear()

    def toggle_trace_mode(self):
        if self.btn_toggle_trace.isChecked():
            self.btn_toggle_trace.setText("👁️ 경로보기 (★활성)")
            self.btn_toggle_trace.setStyleSheet("background-color: #0078d7; color: white; font-weight: bold; min-height: 32px; font-size: 12px;")
            self.tool_list.clearSelection()
        else:
            self.btn_toggle_trace.setText("👁️ 경로보기 (비활성)")
            self.btn_toggle_trace.setStyleSheet("background-color: #444444; color: white; font-weight: bold; min-height: 32px; font-size: 12px;")
            for item in self.dynamic_trace_items:
                item.setData(pos=np.empty((0,3), dtype=np.float32))
        self.track_cursor_position()

    def jump_cursor_lines(self, count):
        cursor = self.nc_input.textCursor()
        if count > 0:
            for _ in range(count):
                cursor.movePosition(cursor.Down)
        else:
            for _ in range(abs(count)):
                cursor.movePosition(cursor.Up)
        self.nc_input.setTextCursor(cursor)
        self.nc_input.ensureCursorVisible()
        self.track_cursor_position()

    def select_prev_tool(self):
        cursor = self.nc_input.textCursor()
        current_block = cursor.blockNumber()
        lines = self.nc_input.toPlainText().split('\n')
        
        target_line = -1
        for idx in range(current_block - 1, -1, -1):
            if idx < len(lines) and re.search(r'M0?6', lines[idx].upper()):
                target_line = idx
                break
        
        if target_line == -1:
            for idx in range(len(lines) - 1, current_block, -1):
                if re.search(r'M0?6', lines[idx].upper()):
                    target_line = idx
                    break
                    
        if target_line != -1:
            new_cursor = self.nc_input.textCursor()
            new_cursor.movePosition(new_cursor.Start)
            for _ in range(target_line):
                new_cursor.movePosition(new_cursor.Down)
            self.nc_input.setTextCursor(new_cursor)
            self.nc_input.ensureCursorVisible()
            self.track_cursor_position()

    def select_next_tool(self):
        cursor = self.nc_input.textCursor()
        current_block = cursor.blockNumber()
        lines = self.nc_input.toPlainText().split('\n')
        
        target_line = -1
        for idx in range(current_block + 1, len(lines)):
            if re.search(r'M0?6', lines[idx].upper()):
                target_line = idx
                break
                
        if target_line == -1:
            for idx in range(0, current_block):
                if re.search(r'M0?6', lines[idx].upper()):
                    target_line = idx
                    break
                    
        if target_line != -1:
            new_cursor = self.nc_input.textCursor()
            new_cursor.movePosition(new_cursor.Start)
            for _ in range(target_line):
                new_cursor.movePosition(new_cursor.Down)
            self.nc_input.setTextCursor(new_cursor)
            self.nc_input.ensureCursorVisible()
            self.track_cursor_position()

    def get_rotation_matrix(self, i_deg, j_deg, k_deg):
        rad_i = np.radians(i_deg)
        rad_j = np.radians(j_deg)
        rad_k = np.radians(k_deg)
        R_I = np.array([[1,0,0],[0,np.cos(rad_i), -np.sin(rad_i)],[0,np.sin(rad_i), np.cos(rad_i)]])
        R_J = np.array([[np.cos(rad_j), 0, np.sin(rad_j)],[0,1,0],[-np.sin(rad_j), 0, np.cos(rad_j)]])
        R_K = np.array([[np.cos(rad_k), -np.sin(rad_k), 0],[np.sin(rad_k), np.cos(rad_k), 0],[0,0,1]])
        return R_K @ R_J @ R_I

    def process_nc_lines(self, lines):
        self.stop_simulation() 
        
        for item_list in self.plot_items.values():
            for item in item_list:
                self.gl_view.removeItem(item)
        self.clear_dynamic_trace()
        self.tool_paths.clear()
        self.plot_items.clear()
        self.tool_list.clear()
        self.line_to_coord_map.clear()
        self.line_to_tool_map.clear()
        self.all_parsed_points = []
        self.sim_point_tools = [] #[cite: 1]
        
        self.modal_state_map = {}
        self.code_lines = []
        
        machine_type = self.combo_machine.currentText()
        is_lathe = "선반" in machine_type
        is_4axis = "4축" in machine_type
        is_5axis_ac = "5축 밀링 (A to C)" in machine_type
        is_5axis_bc = "5축 밀링 (B to C)" in machine_type
        
        try:
            m_x = float(self.machine_specs[machine_type].get("X 행정", "500")) / 2.0
            m_y = float(self.machine_specs[machine_type].get("Y 행정", "500")) / 2.0
            m_z = float(self.machine_specs[machine_type].get("Z 행정", "500")) 
        except:
            m_x, m_y, m_z = 250.0, 250.0, 300.0

        current_tool = "Default_Tool"
        self.tool_paths[current_tool] = []
        
        cx, cy, cz = 0.0, 0.0, 0.0
        cc_deg = 0.0 
        cb_deg = 0.0 
        
        m_x_val, m_y_val, m_z_val = "0.000", "0.000", "0.000"
        m_a_val, m_b_val, m_c_val = "0.000", "0.000", "0.000"
        
        g43_active = False  
        current_motion = "G00"  
        
        polar_interpolation = False
        
        g68_pending = False
        pending_I, pending_J, pending_K = 0.0, 0.0, 0.0
        active_matrix = np.eye(3)
        
        t_pattern = re.compile(r'T(\d+)')
        m6_pattern = re.compile(r'M0?6')
        
        x_pattern = re.compile(r'X\s*([+-]?\d*\.?\d+)')
        y_pattern = re.compile(r'Y\s*([+-]?\d*\.?\d+)')
        z_pattern = re.compile(r'Z\s*([+-]?\d*\.?\d+)')
        a_pattern = re.compile(r'A\s*([+-]?\d*\.?\d+)')
        c_pattern_turn = re.compile(r'C\s*([+-]?\d*\.?\d+)')
        b_pattern_4ax = re.compile(r'B\s*([+-]?\d*\.?\d+)')
        
        g28_pattern = re.compile(r'G28')
        g91_pattern = re.compile(r'G91')
        g68_pattern = re.compile(r'G68\.2')
        g69_pattern = re.compile(r'G69')
        g53_1_pattern = re.compile(r'G53\.1')
        
        g12_1_pattern = re.compile(r'G12\.1|G112')
        g13_1_pattern = re.compile(r'G13\.1|G113')
        
        motion_pattern = re.compile(r'(G0[0-3]|G[0-3])(?![\.\d])')
        
        i_pattern = re.compile(r'I\s*([+-]?\d*\.?\d+)')
        j_pattern = re.compile(r'J\s*([+-]?\d*\.?\d+)')
        k_pattern = re.compile(r'K\s*([+-]?\d*\.?\d+)')
        r_pattern = re.compile(r'R\s*([+-]?\d*\.?\d+)')
        
        g43_pattern = re.compile(r'G43')
        g49_pattern = re.compile(r'G49')

        g98_active = False
        cycle_active = False
        g98_pattern = re.compile(r'G98')
        g99_pattern = re.compile(r'G99')
        cycle_pattern = re.compile(r'(G81|G83|G85|G73|G84|G80)')

        detected_t = "Default_Tool"

        for idx, line in enumerate(lines):
            line_upper = line.upper().replace(" ", "")
            
            codes = re.findall(r'[GSTM]\d+\.?\d*', line.upper())
            if codes:
                self.code_lines.append((idx, f"N{idx+1:04d}: " + " ".join(codes)))
                
            x_m = x_pattern.search(line_upper)
            y_m = y_pattern.search(line_upper)
            z_m = z_pattern.search(line_upper)
            a_m = a_pattern.search(line_upper)
            b_m = b_pattern_4ax.search(line_upper)
            c_m = c_pattern_turn.search(line_upper)
            
            if x_m: m_x_val = x_m.group(1)
            if y_m: m_y_val = y_m.group(1)
            if z_m: m_z_val = z_m.group(1)
            if a_m: m_a_val = a_m.group(1)
            if b_m: m_b_val = b_m.group(1)
            if c_m: m_c_val = c_m.group(1)
            
            self.modal_state_map[idx] = (m_x_val, m_y_val, m_z_val, m_a_val, m_b_val, m_c_val)
            
            comment_t_match = t_pattern.search(line_upper)
            if comment_t_match:
                detected_t = f"Tool T{comment_t_match.group(1)}"
            
            if '(' in line_upper or ';' in line_upper: 
                self.line_to_tool_map[idx] = current_tool
                continue
                
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
                cyc = cycle_match.group(1)
                if cyc == "G80":
                    cycle_active = False
                else:
                    cycle_active = True

            t_match = t_pattern.search(line_upper)
            if t_match:
                detected_t = f"Tool T{t_match.group(1)}"
            
            if m6_pattern.search(line_upper):
                current_tool = detected_t
                if current_tool not in self.tool_paths:
                    self.tool_paths[current_tool] = []
                    self.tool_paths[current_tool].append({'pt': [cx, cy, cz], 'type': current_motion, 'valid': g43_active})
            
            self.line_to_tool_map[idx] = current_tool
            
            motion_match = motion_pattern.search(line_upper)
            if motion_match and not cycle_active: 
                mot = motion_match.group(1)
                if mot in ["G0", "G00"]: current_motion = "G00"
                elif mot in ["G1", "G01"]: current_motion = "G01"
                elif mot in ["G2", "G02"]: current_motion = "G02"
                elif mot in ["G3", "G03"]: current_motion = "G03"

            if is_5axis_ac or is_5axis_bc:
                if g69_pattern.search(line_upper):
                    active_matrix = np.eye(3)
                    g68_pending = False
                elif g68_pattern.search(line_upper):
                    g68_pending = True
                    i_m = i_pattern.search(line_upper)
                    j_m = j_pattern.search(line_upper)
                    k_m = k_pattern.search(line_upper)
                    pending_I = float(i_m.group(1)) if i_m else 0.0
                    pending_J = float(j_m.group(1)) if j_m else 0.0
                    pending_K = float(k_m.group(1)) if k_m else 0.0
                
                if g53_1_pattern.search(line_upper) and g68_pending:
                    if is_5axis_bc:
                        rad_i = np.radians(pending_I)
                        rad_j = np.radians(pending_J)
                        rad_k = np.radians(pending_K)
                        
                        R_I = np.array([[1, 0, 0],
                                        [0, np.cos(rad_i), -np.sin(rad_i)],
                                        [0, np.sin(rad_i), np.cos(rad_i)]])
                        R_J = np.array([[np.cos(rad_j), 0, np.sin(rad_j)],
                                        [0, 1, 0],
                                        [-np.sin(rad_j), 0, np.cos(rad_j)]])
                        R_K = np.array([[np.cos(rad_k), -np.sin(rad_k), 0],
                                        [np.sin(rad_k), np.cos(rad_k), 0],
                                        [0, 0, 1]])
                        
                        active_matrix = R_K @ R_J @ R_I
                    elif is_5axis_ac:
                        rad_a = np.radians(pending_J)  
                        rad_c = np.radians(pending_I)  
                        rad_k = np.radians(pending_K)  
                        
                        R_A = np.array([[1, 0, 0],
                                        [0, np.cos(rad_a), -np.sin(rad_a)],
                                        [0, np.sin(rad_a), np.cos(rad_a)]])
                        R_C = np.array([[np.cos(rad_c), -np.sin(rad_c), 0],
                                        [np.sin(rad_c), np.cos(rad_c), 0],
                                        [0, 0, 1]])
                        R_K = np.array([[np.cos(rad_k), -np.sin(rad_k), 0],
                                        [np.sin(rad_k), np.cos(rad_k), 0],
                                        [0, 0, 1]])
                        
                        active_matrix = R_K @ R_C @ R_A
                    else:
                        active_matrix = self.get_rotation_matrix(pending_I, pending_J, pending_K)
                    g68_pending = False
            
            if is_4axis:
                b_m = b_pattern_4ax.search(line_upper)
                if b_m:
                    cb_deg = float(b_m.group(1))
                    rad_b = np.radians(cb_deg)
                    active_matrix = np.array([[np.cos(rad_b), 0, np.sin(rad_b)],[0,1,0],[-np.sin(rad_b), 0, np.cos(rad_b)]])

            if g28_pattern.search(line_upper) and g91_pattern.search(line_upper):
                has_x0 = bool(re.search(r'X\s*0', line_upper))
                has_y0 = bool(re.search(r'Y\s*0', line_upper))
                has_z0 = bool(re.search(r'Z\s*0', line_upper))
                
                if has_x0: cx = m_x
                if has_y0: cy = m_y
                if has_z0: cz = m_z
                
                final_pt = [cx, cy, cz]
                if g43_active or is_lathe:
                    self.tool_paths[current_tool].append({'pt': final_pt, 'type': 'G00', 'valid': True, 'src_line': idx})
                    self.all_parsed_points.append(final_pt)
                    self.sim_point_tools.append(current_tool) #[cite: 1]
                    self.line_to_coord_map[idx] = final_pt
                continue

            x_match = x_pattern.search(line_upper)
            y_match = y_pattern.search(line_upper)
            z_match = z_pattern.search(line_upper)
            c_match = c_pattern_turn.search(line_upper)
            r_cycle_match = r_pattern.search(line_upper)
            
            if x_match or y_match or z_match or c_match or (cycle_active and r_cycle_match):
                start_pt = [cx, cy, cz] 
                
                if is_lathe:
                    if x_match: cx = float(x_match.group(1)) * 0.5 
                    if y_match: cy = float(y_match.group(1))
                    if z_match: cz = float(z_match.group(1))
                    if c_match: cc_deg = float(c_match.group(1))
                    
                    if polar_interpolation:
                        virtual_y = cc_deg 
                        target_pt = [cx, virtual_y, cz]
                    else:
                        if cc_deg != 0.0:
                            rad_c = np.radians(cc_deg)
                            rx = cx * np.cos(rad_c) - cy * np.sin(rad_c)
                            ry = cx * np.sin(rad_c) + cy * np.cos(rad_c)
                            target_pt = [rx, ry, cz]
                        else:
                            target_pt = [cy, cx, cz]
                else:
                    if x_match: cx = float(x_match.group(1))
                    if y_match: cy = float(y_match.group(1))
                    if z_match: cz = float(z_match.group(1))
                    
                    coord_vec = np.array([cx, cy, cz])
                    if is_5axis_ac or is_5axis_bc or is_4axis:
                        target_pt = (active_matrix @ coord_vec).tolist()
                    else:
                        target_pt = [cx, cy, cz]

                if cycle_active and (g43_active or is_lathe):
                    target_x = cx
                    target_y = cy
                    target_z = float(z_match.group(1)) if z_match else cz
                    r_val = float(r_cycle_match.group(1)) if r_cycle_match else start_pt[2]

                    if is_5axis_ac or is_5axis_bc:
                        xy_approach_raw = np.array([target_x, target_y, start_pt[2]])
                        r_point_raw = np.array([target_x, target_y, r_val])
                        final_z_raw = np.array([target_x, target_y, target_z])
                        return_raw = np.array([target_x, target_y, start_pt[2]])

                        xy_approach_pt = (active_matrix @ xy_approach_raw).tolist()
                        r_point_pt = (active_matrix @ r_point_raw).tolist()
                        final_z_pt = (active_matrix @ final_z_raw).tolist()
                        return_pt = (active_matrix @ return_raw).tolist()
                    else:
                        xy_approach_pt = [target_x, target_y, start_pt[2]]
                        r_point_pt = [target_x, target_y, r_val]
                        final_z_pt = [target_x, target_y, target_z]
                        return_pt = [target_x, target_y, start_pt[2]]

                    self.tool_paths[current_tool].append({'pt': xy_approach_pt, 'type': 'G00', 'valid': True, 'src_line': idx})
                    self.all_parsed_points.append(xy_approach_pt)
                    self.sim_point_tools.append(current_tool) #[cite: 1]

                    self.tool_paths[current_tool].append({'pt': r_point_pt, 'type': 'G00', 'valid': True, 'src_line': idx})
                    self.all_parsed_points.append(r_point_pt)
                    self.sim_point_tools.append(current_tool) #[cite: 1]

                    self.tool_paths[current_tool].append({'pt': final_z_pt, 'type': 'G01', 'valid': True, 'src_line': idx})
                    self.all_parsed_points.append(final_z_pt)
                    self.sim_point_tools.append(current_tool) #[cite: 1]
                    
                    if g98_active:
                        self.tool_paths[current_tool].append({'pt': return_pt, 'type': 'G00', 'valid': True, 'src_line': idx})
                        self.all_parsed_points.append(return_pt)
                        self.sim_point_tools.append(current_tool) #[cite: 1]

                    cz = target_z 
                    self.line_to_coord_map[idx] = final_z_pt
                    continue

                if current_motion in ["G02", "G03"] and (g43_active or is_lathe):
                    arc_pts = []
                    i_val = float(i_pattern.search(line_upper).group(1)) if i_pattern.search(line_upper) else 0.0
                    j_val = float(j_pattern.search(line_upper).group(1)) if j_pattern.search(line_upper) else 0.0
                    r_match = r_pattern.search(line_upper)
                    
                    center_x = start_pt[0] + i_val
                    center_y = start_pt[1] + j_val
                    
                    if r_match:
                        radius = float(r_match.group(1))
                        dx = target_pt[0] - start_pt[0]
                        dy = target_pt[1] - start_pt[1]
                        dist = np.hypot(dx, dy)
                        if dist > 0:
                            h = np.sqrt(max(0.0, radius**2 - (dist/2)**2))
                            sign = 1 if (current_motion == "G03" if radius > 0 else current_motion == "G02") else -1
                            center_x = start_pt[0] + dx/2 - sign * h * (dy/dist)
                            center_y = start_pt[1] + dy/2 + sign * h * (dx/dist)
                    
                    angle_start = np.arctan2(start_pt[1] - center_y, start_pt[0] - center_x)
                    angle_end = np.arctan2(target_pt[1] - center_y, target_pt[0] - center_x)
                    
                    if current_motion == "G02" and angle_end >= angle_start: angle_end -= 2 * np.pi
                    elif current_motion == "G03" and angle_end <= angle_start: angle_end += 2 * np.pi
                    
                    segments = max(2, int(abs(angle_end - angle_start) * 10)) 
                    angles = np.linspace(angle_start, angle_end, segments)
                    
                    for a in angles[1:]:
                        z_interp = start_pt[2] + (target_pt[2] - start_pt[2]) * ((a - angle_start) / (angle_end - angle_start))
                        arc_pts.append([center_x + np.cos(a) * np.hypot(start_pt[0]-center_x, start_pt[1]-center_y), center_y + np.sin(a) * np.hypot(start_pt[0]-center_x, start_pt[1]-center_y), z_interp])
                    
                    for pt in arc_pts:
                        self.tool_paths[current_tool].append({'pt': pt, 'type': current_motion, 'valid': True, 'src_line': idx})
                        self.all_parsed_points.append(pt)
                        self.sim_point_tools.append(current_tool) #[cite: 1]
                    self.line_to_coord_map[idx] = target_pt
                else:
                    self.tool_paths[current_tool].append({'pt': target_pt, 'type': current_motion, 'valid': True if is_lathe else g43_active, 'src_line': idx})
                    if g43_active or is_lathe:
                        self.all_parsed_points.append(target_pt)
                        self.sim_point_tools.append(current_tool) #[cite: 1]
                        self.line_to_coord_map[idx] = target_pt

        self.tool_paths = {k: v for k, v in self.tool_paths.items() if len(v) > 0}
        
        for idx, (tool, path_data) in enumerate(self.tool_paths.items()):
            base_color = tool_color_for_index(idx)
            self.tool_list.addItem(tool)
            self.tool_list.item(self.tool_list.count() - 1).setForeground(qcolor_from_float_rgb(base_color))
            self.plot_items[tool] = []
            
            current_seg = []
            prev_type = None
            
            for node in path_data:
                if not node['valid']: 
                    if current_seg:
                        self.create_segment_item(tool, current_seg, prev_type, base_color)
                        current_seg = []
                    continue
                
                if prev_type is not None and node['type'] != prev_type:
                    if current_seg:
                        current_seg.append(node['pt'])
                        self.create_segment_item(tool, current_seg, prev_type, base_color)
                        current_seg = [node['pt']]
                else:
                    current_seg.append(node['pt'])
                prev_type = node['type']
                
            if current_seg:
                self.create_segment_item(tool, current_seg, prev_type, base_color)
            
        for i in range(self.tool_list.count()):
            self.tool_list.item(i).setSelected(True)

    def create_segment_item(self, tool, pts_list, motion_type, base_color):
        if len(pts_list) < 2: return
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

    def update_visible_paths(self):
        selected_items = [item.text() for item in self.tool_list.selectedItems()]
        for tool, plot_item_list in self.plot_items.items():
            for item in plot_item_list:
                item.setVisible(tool in selected_items)

    def update_trace_item(self, idx, pts_list, motion_type, base_color):
        if len(pts_list) < 2: return
        pts = np.array(pts_list, dtype=np.float32)
        if motion_type == "G00":
            color = [base_color[0], base_color[1], base_color[2], 0.45]
            width = 1.5
        else:
            color = [base_color[0], base_color[1], base_color[2], 1.0]
            width = 3.5 
            
        if idx < len(self.dynamic_trace_items):
            item = self.dynamic_trace_items[idx]
            item.setData(pos=pts, color=color, width=width)
        else:
            item = gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True)
            self.gl_view.addItem(item)
            self.dynamic_trace_items.append(item)

    def track_cursor_position(self):
        cursor = self.nc_input.textCursor()
        line_idx = cursor.blockNumber()
        
        if hasattr(self, 'modal_state_map') and line_idx in self.modal_state_map:
            mx, my, mz, ma, mb, mc = self.modal_state_map[line_idx]
            self.lbl_x.setText(mx)
            self.lbl_y.setText(my)
            self.lbl_z.setText(mz)
            self.lbl_a.setText(ma)
            self.lbl_b.setText(mb)
            self.lbl_c.setText(mc)

        if hasattr(self, 'code_lines'):
            history_str = []
            for l_idx, codes_str in self.code_lines:
                if l_idx > line_idx:
                    break
                history_str.append(codes_str)
            self.history_box.setPlainText("\n".join(history_str[-100:]))
            self.history_box.verticalScrollBar().setValue(self.history_box.verticalScrollBar().maximum())

        if line_idx in self.line_to_coord_map:
            pt = self.line_to_coord_map[line_idx]
            self.cursor_sphere.resetTransform()
            self.cursor_sphere.translate(pt[0], pt[1], pt[2])
            self.cursor_sphere.setVisible(True)
        else:
            self.cursor_sphere.setVisible(False)
            
        if not self.btn_toggle_trace.isChecked():
            for item in self.dynamic_trace_items:
                item.setData(pos=np.empty((0,3), dtype=np.float32))
            return

        current_tool = self.line_to_tool_map.get(line_idx, None)
        if current_tool and current_tool in self.tool_paths:
            try:
                tool_index = list(self.tool_paths.keys()).index(current_tool)
                base_color = tool_color_for_index(tool_index)
            except ValueError:
                base_color = tool_color_for_index(0)
                
            current_seg = []
            prev_type = None
            trace_idx = 0
            
            for node in self.tool_paths[current_tool]:
                if node.get('src_line', -1) > line_idx:
                    break
                if not node['valid']:
                    if current_seg:
                        self.update_trace_item(trace_idx, current_seg, prev_type, base_color)
                        trace_idx += 1
                        current_seg = []
                    continue
                
                if prev_type is not None and node['type'] != prev_type:
                    if current_seg:
                        current_seg.append(node['pt'])
                        self.update_trace_item(trace_idx, current_seg, prev_type, base_color)
                        trace_idx += 1
                        current_seg = [node['pt']]
                else:
                    current_seg.append(node['pt'])
                prev_type = node['type']
                
            if current_seg:
                self.update_trace_item(trace_idx, current_seg, prev_type, base_color)
                trace_idx += 1
                
            for i in range(trace_idx, len(self.dynamic_trace_items)):
                self.dynamic_trace_items[i].setData(pos=np.empty((0,3), dtype=np.float32))
        else:
            for item in self.dynamic_trace_items:
                item.setData(pos=np.empty((0,3), dtype=np.float32))

    def start_simulation(self):
        if not self.all_parsed_points: return
        self.stop_at_next_tool = False #[cite: 1]
        if self.current_sim_index >= len(self.all_parsed_points):
            self.current_sim_index = 0
        self.sim_timer.start(10)

    def start_tool_simulation(self): #[cite: 1]
        if not self.all_parsed_points: return
        if self.current_sim_index >= len(self.all_parsed_points):
            self.current_sim_index = 0
            
        # 현재 위치의 공구 이름 확인
        current_tool = self.sim_point_tools[self.current_sim_index] if self.current_sim_index < len(self.sim_point_tools) else None
        
        # 다음 공구(M06)로 바뀔 때의 첫 인덱스 검색
        self.target_tool_change_index = len(self.all_parsed_points)
        for i in range(self.current_sim_index, len(self.all_parsed_points)):
            if self.sim_point_tools[i] != current_tool:
                self.target_tool_change_index = i
                break
                
        self.stop_at_next_tool = True
        self.sim_timer.start(10)

    def pause_simulation(self):
        self.sim_timer.stop()

    def stop_simulation(self):
        self.sim_timer.stop()
        self.current_sim_index = 0
        self.stop_at_next_tool = False
        self.sim_line_item.setData(pos=None)
        self.clear_dynamic_trace()
        self.cursor_sphere.setVisible(False)

    def play_next_step(self):
        if self.current_sim_index < len(self.all_parsed_points):
            step_size = self.slider_speed.value() * 2
            next_index = self.current_sim_index + step_size
            
            # 공구 단위 정지가 활성화되어 있고 다음 스텝이 타겟 공구 경계를 넘을 때 조기 정지[cite: 1]
            if self.stop_at_next_tool and next_index >= self.target_tool_change_index:
                next_index = self.target_tool_change_index
                self.current_sim_index = next_index
                
                pts_slice = np.array(self.all_parsed_points[:self.current_sim_index], dtype=np.float32)
                self.sim_line_item.setData(pos=pts_slice)
                
                if self.current_sim_index > 0:
                    current_pt = self.all_parsed_points[self.current_sim_index - 1]
                    self.cursor_sphere.resetTransform()
                    self.cursor_sphere.translate(current_pt[0], current_pt[1], current_pt[2])
                    self.cursor_sphere.setVisible(True)
                    
                self.sim_timer.stop()
                self.stop_at_next_tool = False
                return
                
            self.current_sim_index = next_index
            if self.current_sim_index > len(self.all_parsed_points):
                self.current_sim_index = len(self.all_parsed_points)
                
            pts_slice = np.array(self.all_parsed_points[:self.current_sim_index], dtype=np.float32)
            self.sim_line_item.setData(pos=pts_slice)
            
            current_pt = self.all_parsed_points[self.current_sim_index - 1]
            self.cursor_sphere.resetTransform()
            self.cursor_sphere.translate(current_pt[0], current_pt[1], current_pt[2])
            self.cursor_sphere.setVisible(True)
        else:
            self.sim_timer.stop()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = NCViewerApp()
    if len(sys.argv) > 1:
        viewer.load_nc_from_path(sys.argv[1])
    viewer.show()
    sys.exit(app.exec_())

