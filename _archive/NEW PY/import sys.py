import sys
import re
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QTextEdit, QPushButton, QListWidget, 
                             QLabel, QSplitter)
from PyQt5.QtCore import Qt
import pyqtgraph.opengl as gl

class NCViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NC Code 3D Path Viewer")
        self.setGeometry(100, 100, 1200, 800)
        
        # 데이터 저장 구조
        self.tool_paths = {}  # { 'T01': [ [x,y,z], [x,y,z]... ], 'T02': ... }
        self.plot_items = {}  # 3D 라인 객체 저장
        
        self.init_ui()

    def init_ui(self):
        # 메인 윈도우의 중앙 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # 화면 분할을 위한 스플리터 (좌우 조절 가능)
        splitter = QSplitter(Qt.Horizontal)
        
        # --- [좌측 레일: 제어부 (25%)] ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # NC 데이터 입력창
        left_layout.addWidget(QLabel("1. NC 데이터 입력 (G-Code):"))
        self.nc_input = QTextEdit()
        self.nc_input.setPlaceholderText("G01 X10. Y20. Z-5.\n... 형식으로 입력하세요.")
        left_layout.addWidget(self.nc_input)
        
        # 파싱/로드 버튼
        self.btn_load = QPushButton("NC 데이터 로드 및 파싱")
        self.btn_load.setFixedHeight(40)
        self.btn_load.clicked.connect(self.parse_nc_data)
        left_layout.addWidget(self.btn_load)
        
        # 공구(Tool) 선택 리스트창
        left_layout.addWidget(QLabel("2. 공구별 경로 필터 선택:"))
        self.tool_list = QListWidget()
        self.tool_list.setSelectionMode(QListWidget.MultiSelection) # 여러 공구 동시 선택 가능
        self.tool_list.itemSelectionChanged.connect(self.update_visible_paths)
        left_layout.addWidget(self.tool_list)
        
        # --- [우측 레일: 3D 뷰어 (75%)] ---
        self.gl_view = gl.GLViewWidget()
        # 배경색 및 카메라 기본 설정 (현장 장비 시뮬레이터 느낌의 어두운 톤)
        self.gl_view.setBackgroundColor(33, 37, 43, 255) 
        self.gl_view.setCameraPosition(distance=150, elevation=30, azimuth=-45)
        
        # 그리드(Grid) 추가 (가이드라인)
        grid = gl.GLGridItem()
        grid.setSize(200, 200, 1)
        grid.setSpacing(10, 10, 1)
        self.gl_view.addItem(grid)
        
        # 축(Axis) 표시 (X:적색, Y:녹색, Z:청색)
        axis = gl.GLAxisItem()
        axis.setSize(50, 50, 50)
        self.gl_view.addItem(axis)
        
        # 스플리터에 장착 및 비율 조절 (1:3 비율로 분할 -> 세로 4등분 효과)
        splitter.addWidget(left_widget)
        splitter.addWidget(self.gl_view)
        splitter.setSizes([300, 900])
        
        # 메인 레이아웃에 스플리터 추가
        main_layout = QHBoxLayout(main_widget)
        main_layout.addWidget(splitter)

    def parse_nc_data(self):
        """ 입력된 G코드를 파싱하여 공구 교환(T) 기준으로 경로를 쪼갭니다. """
        raw_text = self.nc_input.toPlainText().upper()
        lines = raw_text.split('\n')
        
        # 기존 데이터 및 뷰어 초기화
        for item in self.plot_items.values():
            self.gl_view.removeItem(item)
        self.tool_paths.clear()
        self.plot_items.clear()
        self.tool_list.clear()
        
        current_tool = "Default_Tool"
        self.tool_paths[current_tool] = []
        
        # 모달 상태 저장을 위한 현재 좌표 변수
        cx, cy, cz = 0.0, 0.0, 0.0
        
        # 정규식 패턴 (T번호, X, Y, Z 추출)
        t_pattern = re.compile(r'T(\d+)')
        x_pattern = re.compile(r'X\s*([+-]?\d*\.?\d+)')
        y_pattern = re.compile(r'Y\s*([+-]?\d*\.?\d+)')
        z_pattern = re.compile(r'Z\s*([+-]?\d*\.?\d+)')
        
        for line in lines:
            # 주석 제외
            if '(' in line or ';' in line:
                continue
                
            # 공구 변경 감지 (예: T01 M06 또는 T1)
            t_match = t_pattern.search(line)
            if t_match:
                current_tool = f"Tool T{t_match.group(1)}"
                if current_tool not in self.tool_paths:
                    self.tool_paths[current_tool] = []
                    # 공구 변경 직후에는 이전 최종 좌표에서 시작하도록 연결해 주면 흐름이 자연스럽습니다.
                    if [cx, cy, cz] != [0.0, 0.0, 0.0]:
                        self.tool_paths[current_tool].append([cx, cy, cz])
            
            # X, Y, Z 좌표 파싱
            x_match = x_pattern.search(line)
            y_match = y_pattern.search(line)
            z_match = z_pattern.search(line)
            
            if x_match or y_match or z_match:
                if x_match: cx = float(x_match.group(1))
                if y_match: cy = float(y_match.group(1))
                if z_match: cz = float(z_match.group(1))
                
                self.tool_paths[current_tool].append([cx, cy, cz])

        # 비어있는 공구 그룹 제거
        self.tool_paths = {k: v for k, v in self.tool_paths.items() if len(v) > 1}
        
        # 리스트 위젯에 생성된 공구 목록 표기 및 3D 객체 생성
        color_maps = [
            [1.0, 0.5, 0.0, 1.0], # 주황
            [0.0, 0.8, 1.0, 1.0], # 하늘
            [0.2, 1.0, 0.2, 1.0], # 연두
            [1.0, 0.3, 0.3, 1.0]  # 분홍
        ]
        
        for idx, (tool, path) in enumerate(self.tool_paths.items()):
            self.tool_list.addItem(tool)
            
            # 3D 라인 생성 (공구별로 다른 색상 지정)
            pts = np.array(path)
            color = color_maps[idx % len(color_maps)]
            
            # pyqtgraph의 GLLinePlotItem 사용
            line_item = gl.GLLinePlotItem(pos=pts, color=color, width=2, antialias=True)
            self.gl_view.addItem(line_item)
            self.plot_items[tool] = line_item
            
        # 초기 상태는 모든 공구 리스트 선택 및 뷰어 표시
        for i in range(self.tool_list.count()):
            self.tool_list.item(i).setSelected(True)

    def update_visible_paths(self):
        """ 선택 창에서 체크(선택)된 공구의 경로만 렌더링 뷰어에 보여줍니다. """
        selected_items = [item.text() for item in self.tool_list.selectedItems()]
        
        for tool, plot_item in self.plot_items.items():
            if tool in selected_items:
                plot_item.setVisible(True)
            else:
                plot_item.setVisible(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = NCViewerApp()
    viewer.show()
    sys.exit(app.exec_())