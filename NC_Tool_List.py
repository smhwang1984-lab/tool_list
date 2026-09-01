# -*- coding: utf-8 -*-
"""
NC 공구 리스트 생성기
- 왼쪽: NC 프로그램(G코드) 입력
- 오른쪽: 공구 리스트 산출 화면과 3D Viewer 화면을 같은 창 안에서 교환
"""
import json
import importlib.util
import os
import re
import sys
from datetime import date
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle


APP_VERSION = '1.3.3'
APP_NAME = 'NC 공구 리스트 생성기'

# ---------- 파싱 로직 ----------
TOOL_RE = re.compile(r'\(\s*T(\d+)\s*//\s*(.*?)\s*\[SO\s*([\d.]+)\]\s*//\s*T\d+\s*([^)]*?)\s*\)', re.I)
N_RE    = re.compile(r'^\s*N(\d+)\s*\(\s*#\d+\s*:\s*Tool\s*Change', re.I)
M6_RE   = re.compile(r'^\s*M0?6\s*T(\d+)\b', re.I)
M6_SEARCH_RE = re.compile(r'^\s*M0?6\s*T\d+\b', re.I | re.M)
# 키 뒤 숫자만 추출(값이 없으면 매칭 안 됨). 긴 키를 앞에 둬서 FL이 F로 잘못 잡히지 않게 함
KV_RE   = re.compile(r'\b(LCF|SPINDL|FEED|FL|GL|DC|RE|SIG|PL|F)\s+(-?\d+(?:\.\d+)?)', re.I)
COMMENT_RE = re.compile(r'\(([^()]*)\)', re.S)
PROGRAM_NO_RE = re.compile(r'^\s*(O\d+)\b', re.I | re.M)
OPERATION_FROM_PROGRAM_RE = re.compile(
    r'(?<![A-Z0-9])(OP(?:ERATION)?\s*[-_ ]?\d+[A-Z]?)(?=$|[^A-Z0-9])', re.I,
)

METADATA_ALIASES = {
    'part_no': {'PARTNO', 'PARTNUMBER', 'PART'},
    'operation': {'OPERATION', 'OPERATIONNO', 'OPER', 'OP'},
    'program': {'PROGRAM', 'PROGRAMNO', 'PGM', 'PGMNO'},
    'runtime': {'RUNTIME', 'COMPLETETIME', 'CYCLETIME', 'MACHININGTIME', 'TOTALTIME'},
    'date': {'DATE', 'PROGRAMDATE', 'CREATEDATE', 'CREATIONDATE'},
}

# (내부키, 표시라벨) — 엑셀 A~P 순서와 동일
COLUMNS = [
    ('NO', 'NO'), ('TYPE', 'TYPE'), ('NAME', 'NAME'), ('D', 'D'),
    ('FL', 'FL'), ('LCF', 'LCF'), ('F', 'F'), ('R', 'R'),
    ('SIG', 'SIG'), ('PL', 'PL'), ('SO', 'SO'), ('GL', 'GL'),
    ('HOLDER', '홀더'), ('SPINDL', 'SPINDL'), ('FEED', 'FEED'), ('REMARK', 'REMARK'),
]
COL_WIDTH = {
    'NO': 45, 'TYPE': 80, 'NAME': 95, 'D': 45, 'FL': 45, 'LCF': 50, 'F': 35,
    'R': 45, 'SIG': 45, 'PL': 55, 'SO': 45, 'GL': 50, 'HOLDER': 120,
    'SPINDL': 60, 'FEED': 55, 'REMARK': 110,
}

# TOOL_LIST_PG.xlsx의 A:P 열 폭 비율
PDF_COLUMN_WEIGHTS = [48, 100, 150, 40, 40, 40, 40, 40, 40, 40, 40, 60, 140, 70, 70, 88]
PDF_ROWS_PER_PAGE = 28
PDF_INFO_BLUE = colors.HexColor('#BDDDEE')
PDF_HEADER_GRAY = colors.HexColor('#BFBFBF')
PDF_ALT_GRAY = colors.HexColor('#D9D9D9')
PDF_FONT_BLUE = colors.HexColor('#002F60')
PDF_GRID_GRAY = colors.HexColor('#9A9A9A')
PDF_FONT_REGULAR = 'NCMalgun'
PDF_FONT_BOLD = 'NCMalgunBold'
PDF_METADATA_FIELDS = [
    (0, 'PART NO', 'part_no'), (3, 'OPERATION', 'operation'),
    (7, 'PROGRAM', 'program'), (11, 'RUN TIME', 'runtime'), (13, 'DATE', 'date'),
]


def normalize_metadata_key(value):
    return re.sub(r'[^A-Z0-9]', '', value.upper())


def parse_program_metadata(text):
    """NC 헤더 주석에서 PDF 정보행에 들어갈 값을 추출한다."""
    metadata = {key: '' for key in METADATA_ALIASES}
    for comment in COMMENT_RE.findall(text or ''):
        match = re.match(r'^\s*([^:=]+?)\s*[:=]\s*(.*?)\s*$', comment, re.S)
        if not match:
            continue
        source_key = normalize_metadata_key(match.group(1))
        value = ' '.join(match.group(2).split())
        if not value:
            continue
        for target, aliases in METADATA_ALIASES.items():
            if source_key in aliases and not metadata[target]:
                metadata[target] = value
                break

    program_match = PROGRAM_NO_RE.search(text or '')
    if not metadata['program'] and program_match:
        metadata['program'] = program_match.group(1).upper()
    program = metadata['program']
    operation_match = OPERATION_FROM_PROGRAM_RE.search(program)
    if operation_match and not metadata['operation']:
        operation = normalize_metadata_key(operation_match.group(1))
        metadata['operation'] = operation.replace('OPERATION', 'OP')
    if operation_match and not metadata['part_no']:
        remainder = program[:operation_match.start()] + program[operation_match.end():]
        metadata['part_no'] = remainder.strip(' _-/')
    return metadata


def register_pdf_fonts():
    registered = set(pdfmetrics.getRegisteredFontNames())
    if PDF_FONT_REGULAR in registered and PDF_FONT_BOLD in registered:
        return PDF_FONT_REGULAR, PDF_FONT_BOLD
    font_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    regular_path = font_dir / 'malgun.ttf'
    bold_path = font_dir / 'malgunbd.ttf'
    if regular_path.exists() and bold_path.exists():
        pdfmetrics.registerFont(TTFont(PDF_FONT_REGULAR, str(regular_path)))
        pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD, str(bold_path)))
        return PDF_FONT_REGULAR, PDF_FONT_BOLD
    fallback = 'HYSMyeongJo-Medium'
    if fallback not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(fallback))
    return fallback, fallback


def normalized_pdf_metadata(metadata):
    values = {key: str((metadata or {}).get(key, '')).strip() for key in METADATA_ALIASES}
    if not values['date']:
        values['date'] = date.today().isoformat()
    return values


def make_pdf_metadata_row(metadata, font_name):
    style = ParagraphStyle(
        'PdfInfo', fontName=font_name, fontSize=7.5, leading=9,
        textColor=colors.black, leftIndent=0, rightIndent=0,
    )
    row = [''] * len(COLUMNS)
    for column, label, key in PDF_METADATA_FIELDS:
        value = escape(str(metadata.get(key, '')))
        row[column] = Paragraph('%s : %s' % (label, value), style)
    return row


def pdf_column_widths(available_width):
    total = float(sum(PDF_COLUMN_WEIGHTS))
    return [available_width * weight / total for weight in PDF_COLUMN_WEIGHTS]


def make_pdf_table(rows, metadata, available_width, fonts):
    regular_font, bold_font = fonts
    page_rows = list(rows)
    blank_row = {key: None for key, _label in COLUMNS}
    while len(page_rows) < PDF_ROWS_PER_PAGE:
        page_rows.append(blank_row)
    data = [make_pdf_metadata_row(metadata, regular_font)]
    data.append([label for _key, label in COLUMNS])
    data.extend([[row.get(key) for key, _label in COLUMNS] for row in page_rows])
    return style_pdf_table(data, available_width, regular_font, bold_font)


def style_pdf_table(data, available_width, regular_font, bold_font):
    heights = [16, 20] + [15.5] * PDF_ROWS_PER_PAGE
    table = Table(data, colWidths=pdf_column_widths(available_width), rowHeights=heights)
    commands = base_pdf_table_style(regular_font, bold_font)
    commands.extend(pdf_table_spans())
    commands.extend(pdf_table_row_backgrounds())
    table.setStyle(TableStyle(commands))
    return table


def base_pdf_table_style(regular_font, bold_font):
    return [
        ('GRID', (0, 0), (-1, -1), 0.35, PDF_GRID_GRAY),
        ('BACKGROUND', (0, 0), (-1, 0), PDF_INFO_BLUE),
        ('BACKGROUND', (0, 1), (-1, 1), PDF_HEADER_GRAY),
        ('FONTNAME', (0, 0), (-1, 0), regular_font),
        ('FONTNAME', (0, 1), (-1, -1), bold_font),
        ('TEXTCOLOR', (0, 1), (-1, -1), PDF_FONT_BLUE),
        ('FONTSIZE', (0, 1), (-1, 1), 7.2),
        ('FONTSIZE', (0, 2), (-1, -1), 6.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('ALIGN', (0, 1), (2, -1), 'LEFT'),
        ('ALIGN', (12, 2), (12, -1), 'LEFT'),
        ('ALIGN', (15, 2), (15, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2.5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2.5),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]


def pdf_table_spans():
    return [
        ('SPAN', (0, 0), (2, 0)),
        ('SPAN', (3, 0), (6, 0)),
        ('SPAN', (7, 0), (10, 0)),
        ('SPAN', (11, 0), (12, 0)),
        ('SPAN', (13, 0), (15, 0)),
    ]


def pdf_table_row_backgrounds():
    commands = []
    for table_row in range(3, PDF_ROWS_PER_PAGE + 2, 2):
        commands.append(('BACKGROUND', (0, table_row), (-1, table_row), PDF_ALT_GRAY))
    return commands


def export_tool_list_pdf(path, rows, metadata):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fonts = register_pdf_fonts()
    document = make_pdf_document(output_path)
    metadata = normalized_pdf_metadata(metadata)
    document.build(make_pdf_story(rows, metadata, document.width, fonts))
    return output_path


def make_pdf_document(output_path):
    return SimpleDocTemplate(
        str(output_path), pagesize=landscape(A4),
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=19 * mm, bottomMargin=19 * mm,
    )


def make_pdf_story(rows, metadata, available_width, fonts):
    source_rows = list(rows)
    chunks = [source_rows[index:index + PDF_ROWS_PER_PAGE]
              for index in range(0, len(source_rows), PDF_ROWS_PER_PAGE)]
    if not chunks:
        chunks = [[]]
    story = []
    for index, chunk in enumerate(chunks):
        story.append(make_pdf_table(chunk, metadata, available_width, fonts))
        if index < len(chunks) - 1:
            story.append(PageBreak())
    return story


def default_pdf_filename(metadata):
    parts = [metadata.get(key) for key in ('part_no', 'operation', 'program')]
    stem = '_'.join(str(value).strip() for value in parts if value)
    stem = re.sub(r'[^\w.-]+', '_', stem).strip('_.')
    return (stem or 'NC') + '_TOOL_LIST.pdf'


def find_next_regex_span(text, pattern, start=0):
    text = text or ''
    if not text:
        return None
    try:
        start = int(start)
    except (TypeError, ValueError):
        start = 0
    start = max(0, min(start, len(text)))
    match = pattern.search(text, start)
    if match:
        return match.start(), match.end(), False
    match = pattern.search(text, 0, start)
    if match:
        return match.start(), match.end(), True
    return None


def find_next_tool_change_span(text, start=0):
    return find_next_regex_span(text, M6_SEARCH_RE, start)


def find_next_literal_span(text, needle, start=0):
    needle = str(needle or '')
    if not needle:
        return None
    return find_next_regex_span(text, re.compile(re.escape(needle), re.I), start)


def open_file_with_default_app(path):
    try:
        os.startfile(os.fspath(path))
    except Exception as error:
        return str(error)
    return ''


def fmt_num(s):
    """'38.500000' -> '38.5', '10.000000' -> '10'"""
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except (ValueError, TypeError):
        return str(s).strip()


# 사용자용 표시 목록 (이름 약어 -> TYPE). "이름 경우의 수" 버튼에서 이 목록을 보여줌
DEFAULT_NAME_TYPES = [
    ('F.EM', 'FLAT E/M'),
    ('FLAT E/M', 'FLAT E/M'),
    ('FLAT END MILL', 'FLAT E/M'),
    ('R.EM', 'FILLET E/M'),
    ('FILLET E/M', 'FILLET E/M'),
    ('RADIUS E/M', 'FILLET E/M'),
    ('B.EM', 'BALL E/M'),
    ('BALL E/M', 'BALL E/M'),
    ('BALL END MILL', 'BALL E/M'),
    ('DR', 'DRILL'),
    ('DRILL', 'DRILL'),
    ('F.MIL', 'FACE MILL'),
    ('FACE MILL', 'FACE MILL'),
    ('CUT', 'CUTTER'),
    ('CUTTER', 'CUTTER'),
    ('RM', 'REAMER'),
    ('REAMER', 'REAMER'),
    ('C.D', 'CENTER'),
    ('CENTER DRILL', 'CENTER'),
    ('T.CUT', 'T-CUTTER'),
    ('T-CUTTER', 'T-CUTTER'),
    ('DY.EM', 'DYNAMIC E/M'),
    ('DYNAMIC E/M', 'DYNAMIC E/M'),
    ('C.MIL', 'CHAMF MILL'),
    ('CHAMF MILL', 'CHAMF MILL'),
]

# 매칭 순서 (긴/구체적인 약어를 앞에 둬서 잘못 잡히지 않게 함) + 풀네임 대비
def settings_path():
    """Return a user-writable path even when installed in Program Files."""
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'NC Tool List' / 'name_type_mappings.json'


def clean_name_types(items):
    """Keep valid, unique mapping rows while preserving their display order."""
    if not isinstance(items, list):
        return []
    clean, seen = [], set()
    for item in items:
        if isinstance(item, dict):
            abbr, typ = item.get('name', ''), item.get('type', '')
        else:
            try:
                abbr, typ = item
            except (TypeError, ValueError):
                continue
        abbr, typ = str(abbr).strip(), str(typ).strip()
        if abbr and typ and abbr.upper() not in seen:
            clean.append((abbr, typ))
            seen.add(abbr.upper())
    return clean


def load_name_types():
    try:
        with settings_path().open('r', encoding='utf-8') as fp:
            saved = json.load(fp)
        if isinstance(saved, list):
            return clean_name_types(saved)
    except (OSError, ValueError, TypeError):
        pass
    return list(DEFAULT_NAME_TYPES)


def save_name_types(items):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fp:
        json.dump([{'name': abbr, 'type': typ} for abbr, typ in items], fp,
                  ensure_ascii=False, indent=2)


def derive_type(name, name_types=None):
    """Return TYPE for the longest matching configured name expression."""
    u = (name or '').upper()
    mappings = name_types if name_types is not None else DEFAULT_NAME_TYPES
    for abbr, typ in sorted(mappings, key=lambda item: len(item[0]), reverse=True):
        if abbr.upper() in u:
            return typ
    return ''

def derive_d(name):
    m = re.search(r'D\s*([\d.]+)', name or '', re.I)
    return m.group(1) if m else ''


def parse_program(text, name_types=None):
    """N번호 ~ M6 사이의 괄호 주석만 읽어서 공구별로 정리해 행 목록 반환"""
    tools = {}          # 공구번호 -> {'f': {필드}, 'remarks': [...]}
    cur_n = [None]      # 리스트로 감싸 클로저에서 갱신값 참조
    buf = []

    def ensure(n):
        if n not in tools:
            tools[n] = {'f': {}, 'remarks': []}
        return tools[n]

    def flush(num):
        t = ensure(num)
        block = '\n'.join(buf)
        tm = TOOL_RE.search(block)
        if tm:
            t['f'].setdefault('NAME', tm.group(2).strip())
            t['f'].setdefault('SO', tm.group(3).strip())
            t['f'].setdefault('HOLDER', tm.group(4).strip())
        for m in KV_RE.finditer(block):
            key = m.group(1).upper()
            t['f'].setdefault(key, fmt_num(m.group(2)))
        if cur_n[0] and cur_n[0] not in t['remarks']:
            t['remarks'].append(cur_n[0])

    for line in text.splitlines():
        m = N_RE.match(line)
        if m:
            cur_n[0] = 'N' + m.group(1)
            buf = []
            continue
        m = M6_RE.match(line)
        if m:
            flush(int(m.group(1)))
            buf = []
            continue
        if '(' in line:
            buf.append(line)

    rows = []
    if not tools:
        return rows
    # 번호 = 행 위치. 없는 공구번호는 그 행을 빈칸으로 비움
    # (T1 없으면 1행이 비고, T4 없으면 4행이 빔)
    for n in range(1, max(tools) + 1):
        if n not in tools:
            rows.append({k: '' for k, _ in COLUMNS})
            continue
        f = tools[n]['f']
        # R(코너R): RE 값이 있고 0이 아니면 표시, 아니면 빈칸
        re_val = f.get('RE', '')
        r = ''
        if re_val not in (None, ''):
            try:
                if float(re_val) != 0:
                    r = re_val
            except ValueError:
                r = re_val
        d = f.get('DC') or derive_d(f.get('NAME', ''))
        rows.append({
            'NO': 'T%02d' % n,
            'TYPE': derive_type(f.get('NAME', ''), name_types),
            'NAME': f.get('NAME', ''),
            'D': d,
            'FL': f.get('FL', ''),
            'LCF': f.get('LCF', ''),
            'F': f.get('F', ''),
            'R': r,
            'SIG': f.get('SIG', ''),
            'PL': f.get('PL', ''),
            'SO': f.get('SO', ''),
            'GL': f.get('GL', ''),
            'HOLDER': f.get('HOLDER', ''),
            'SPINDL': f.get('SPINDL', ''),
            'FEED': f.get('FEED', ''),
            'REMARK': ', '.join(tools[n]['remarks']),
        })
    return rows


def tool_name_map_from_rows(rows):
    """Build lookup keys used by the embedded viewer filter labels."""
    mapping = {}
    for row in rows or []:
        no = str(row.get('NO', '')).strip().upper()
        name = str(row.get('NAME', '')).strip()
        match = re.fullmatch(r'T?(\d+)', no)
        if match:
            number = int(match.group(1))
            mapping['T%02d' % number] = name
            mapping['T%d' % number] = name
            mapping[str(number)] = name
    return mapping

def append_nc_programs(base_text, additions):
    """Append one or more NC programs below the current M30/% tail."""
    parts = []
    base = (base_text or '').rstrip()
    if base:
        parts.append(base)
    for addition in additions or []:
        text = (addition or '').strip()
        if text:
            parts.append(text)
    return '\n\n'.join(parts)


def startup_file_argument(argv):
    for arg in list(argv or [])[1:]:
        value = str(arg).strip().strip('"')
        if value and Path(value).is_file():
            return value
    return None

def resource_path(relative_path):
    """Resolve bundled files both from source and PyInstaller one-file builds."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return str(base / relative_path)


def missing_viewer_dependencies():
    if getattr(sys, 'frozen', False):
        return []
    return [name for name in ('PyQt5', 'pyqtgraph', 'numpy')
            if importlib.util.find_spec(name) is None]


QT_IMPORT_ERROR = None
try:
    from PyQt5.QtCore import Qt, QTimer, QSignalBlocker, pyqtSignal
    from PyQt5.QtGui import QFont, QIcon, QTextCursor
    from PyQt5.QtWidgets import (
        QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
        QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
        QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
        QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
        QTextEdit, QVBoxLayout, QWidget,
    )
    from nc_viewer_widget import NCViewerWidget
except ImportError as error:
    QT_IMPORT_ERROR = error


# ---------- GUI ----------
if QT_IMPORT_ERROR is not None:
    class App:
        def __init__(self, *args, **kwargs):
            raise RuntimeError('GUI 실행에 필요한 패키지가 없습니다: %s' % QT_IMPORT_ERROR)
else:
    class ProgramTextEdit(QTextEdit):
        filesDropped = pyqtSignal(list)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAcceptDrops(True)

        def setReadOnly(self, read_only):
            super().setReadOnly(read_only)
            self.setAcceptDrops(True)

        def _drop_paths(self, event):
            if not event.mimeData().hasUrls():
                return []
            return [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]

        def dragEnterEvent(self, event):
            if self._drop_paths(event):
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event):
            if self._drop_paths(event):
                event.acceptProposedAction()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event):
            paths = self._drop_paths(event)
            if paths:
                self.filesDropped.emit(paths)
                event.acceptProposedAction()
            else:
                super().dropEvent(event)


    class App(QMainWindow):
        def __init__(self, _root=None):
            super().__init__()
            self.name_types = load_name_types()
            self.metadata = {key: '' for key in METADATA_ALIASES}
            self.current_file_path = None
            self.current_mode = 'tool'
            self.viewer_update_timer = QTimer(self)
            self.viewer_update_timer.setSingleShot(True)
            self.viewer_update_timer.timeout.connect(self.sync_viewer_from_source)

            self.setWindowTitle('%s v%s' % (APP_NAME, APP_VERSION))
            self.resize(1180, 640)
            self.set_window_icon()
            self._build_ui()
            QTimer.singleShot(0, self.showMaximized)

        def _build_ui(self):
            kfont = QFont('맑은 고딕', 10)
            mono = QFont('Consolas', 10)

            central = QWidget()
            root_layout = QVBoxLayout(central)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
            self.setCentralWidget(central)

            top = QWidget()
            top.setStyleSheet('background: #1f3a5f; color: white;')
            top_layout = QHBoxLayout(top)
            top_layout.setContentsMargins(14, 7, 10, 7)
            title = QLabel('%s v%s' % (APP_NAME, APP_VERSION))
            title.setFont(QFont('맑은 고딕', 13, QFont.Bold))
            top_layout.addWidget(title)
            caption = QLabel('NC 프로그램을 넣고 공구 리스트를 생성하세요')
            caption.setStyleSheet('color: #c8d4e2;')
            top_layout.addWidget(caption)
            top_layout.addStretch()

            self.btn_tool_mode = QPushButton('툴리스트 산출 모드')
            self.btn_tool_mode.setCheckable(True)
            self.btn_tool_mode.clicked.connect(lambda: self.set_mode('tool'))
            self.btn_viewer_mode = QPushButton('Viewer 모드')
            self.btn_viewer_mode.setCheckable(True)
            self.btn_viewer_mode.clicked.connect(lambda: self.set_mode('viewer'))
            self.btn_machine_settings = QPushButton('설정')
            self.btn_machine_settings.clicked.connect(self.open_machine_settings)
            for button in (self.btn_tool_mode, self.btn_viewer_mode, self.btn_machine_settings):
                button.setFont(QFont('맑은 고딕', 9, QFont.Bold))
                top_layout.addWidget(button)
            root_layout.addWidget(top)

            splitter = QSplitter(Qt.Horizontal)
            splitter.setChildrenCollapsible(False)
            root_layout.addWidget(splitter, 1)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(8, 8, 6, 8)
            left_layout.setSpacing(5)
            splitter.addWidget(left)

            lbar = QHBoxLayout()
            label = QLabel('① 프로그램 입력')
            label.setFont(QFont('맑은 고딕', 10, QFont.Bold))
            lbar.addWidget(label)
            lbar.addStretch()
            self._add_button(lbar, '지우기', self.clear, kfont)
            self._add_button(lbar, '예제', self.load_example, kfont)
            self._add_button(lbar, '파일 열기', self.open_file, kfont)
            self._add_button(lbar, '프로그램 추가', self.open_add_program_files, kfont)
            run_button = self._add_button(lbar, '공구 리스트 생성', self.run, kfont)
            run_button.setStyleSheet('background: #2f6fb0; color: white; padding: 5px 9px;')
            left_layout.addLayout(lbar)

            search_bar = QHBoxLayout()
            self._add_button(search_bar, '다음공구검색', self.find_next_tool_change, kfont)
            search_bar.addWidget(QLabel('문자 검색'))
            self.search_text = QLineEdit()
            self.search_text.setFont(kfont)
            self.search_text.returnPressed.connect(self.find_next_text)
            search_bar.addWidget(self.search_text, 1)
            self._add_button(search_bar, '검색', self.find_next_text, kfont)
            self.search_status = QLabel('')
            self.search_status.setStyleSheet('color: #5a6577;')
            search_bar.addWidget(self.search_status)
            left_layout.addLayout(search_bar)

            input_splitter = QSplitter(Qt.Vertical)
            input_splitter.setChildrenCollapsible(False)
            left_layout.addWidget(input_splitter, 1)

            self.src = ProgramTextEdit()
            self.src.setFont(mono)
            self.src.setLineWrapMode(QTextEdit.NoWrap)
            self.src.setReadOnly(True)
            self.src.setAcceptDrops(True)
            self.src.filesDropped.connect(self.drop_file)
            self.src.textChanged.connect(self.source_changed)
            self.src.cursorPositionChanged.connect(self.source_cursor_changed)
            input_splitter.addWidget(self.src)

            self.filter_panel = QWidget()
            filter_layout = QVBoxLayout(self.filter_panel)
            filter_layout.setContentsMargins(0, 5, 0, 0)
            filter_layout.setSpacing(4)
            filter_bar = QHBoxLayout()
            filter_label = QLabel('공구별 경로 필터 선택')
            filter_label.setFont(QFont('맑은 고딕', 9, QFont.Bold))
            filter_bar.addWidget(filter_label)
            filter_bar.addStretch()
            self._add_button(filter_bar, '전체', lambda: self.viewer.select_all_tools(True), kfont)
            self._add_button(filter_bar, '해제', lambda: self.viewer.select_all_tools(False), kfont)
            filter_layout.addLayout(filter_bar)
            self.tool_filter = QListWidget()
            self.tool_filter.setSelectionMode(QAbstractItemView.MultiSelection)
            filter_layout.addWidget(self.tool_filter, 1)
            input_splitter.addWidget(self.filter_panel)
            input_splitter.setSizes([480, 160])

            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(6, 8, 8, 8)
            right_layout.setSpacing(0)
            splitter.addWidget(right)
            splitter.setSizes([430, 750])

            self.stack = QStackedWidget()
            right_layout.addWidget(self.stack, 1)
            self._build_tool_panel()
            self.viewer = NCViewerWidget()
            self.viewer.attach_tool_filter(self.tool_filter)
            self.stack.addWidget(self.viewer)
            self.set_mode('tool')

        def _add_button(self, layout, text, slot, font=None):
            button = QPushButton(text)
            if font is not None:
                button.setFont(font)
            button.clicked.connect(slot)
            layout.addWidget(button)
            return button

        def _build_tool_panel(self):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)

            rbar = QHBoxLayout()
            label = QLabel('② 공구 리스트 (복사용)')
            label.setFont(QFont('맑은 고딕', 10, QFont.Bold))
            rbar.addWidget(label)
            self.count = QLabel('공구 0개')
            self.count.setStyleSheet('color: #5a6577;')
            rbar.addWidget(self.count)
            rbar.addStretch()
            self._add_button(rbar, '삭제', self.delete_selected)
            self._add_button(rbar, '수정', self.edit_selected)
            self._add_button(rbar, '＋ 행 추가', self.add_row)
            self._add_button(rbar, '이름 경우의 수', self.show_type_list)
            self.with_header = QCheckBox('머리글 포함')
            rbar.addWidget(self.with_header)
            pdf_button = self._add_button(rbar, 'PDF 출력', self.export_pdf)
            pdf_button.setStyleSheet('background: #4c7f31; color: white; padding: 5px 9px;')
            copy_button = self._add_button(rbar, '표 복사', self.copy_table)
            copy_button.setStyleSheet('background: #2f6fb0; color: white; padding: 5px 9px;')
            layout.addLayout(rbar)

            self.metadata_summary = QLabel('출력 정보: -')
            self.metadata_summary.setStyleSheet('background: #eaf1f8; color: #40536b; padding: 4px 6px;')
            layout.addWidget(self.metadata_summary)

            self.table = QTableWidget(0, len(COLUMNS))
            self.table.setHorizontalHeaderLabels([label for _key, label in COLUMNS])
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setAlternatingRowColors(True)
            self.table.verticalHeader().setVisible(False)
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.Interactive)
            for index, (key, _label) in enumerate(COLUMNS):
                self.table.setColumnWidth(index, COL_WIDTH.get(key, 60))
            self.table.doubleClicked.connect(lambda _index: self.edit_selected())
            layout.addWidget(self.table, 1)

            hint = QLabel('행을 더블클릭하거나 수정/추가 버튼으로 직접 편집할 수 있습니다. (N번호 ~ M6 사이 괄호 주석을 읽음)')
            hint.setStyleSheet('color: #8a94a3;')
            layout.addWidget(hint)
            self.stack.addWidget(panel)

        def set_window_icon(self):
            icon_path = resource_path('assets/nc_tool_list.ico')
            if Path(icon_path).exists():
                self.setWindowIcon(QIcon(icon_path))

        def set_mode(self, mode):
            self.current_mode = mode
            is_viewer = mode == 'viewer'
            self.stack.setCurrentIndex(1 if is_viewer else 0)
            self.filter_panel.setVisible(is_viewer)
            self.btn_tool_mode.setChecked(not is_viewer)
            self.btn_viewer_mode.setChecked(is_viewer)
            self._style_mode_buttons()
            if is_viewer:
                self.sync_viewer_from_source()

        def _style_mode_buttons(self):
            active = 'background: #34577f; color: white; padding: 5px 9px;'
            inactive = 'background: #f0f4f8; color: #1f3a5f; padding: 5px 9px;'
            self.btn_tool_mode.setStyleSheet(active if self.current_mode == 'tool' else inactive)
            self.btn_viewer_mode.setStyleSheet(active if self.current_mode == 'viewer' else inactive)
            self.btn_machine_settings.setStyleSheet(inactive)

        def source_changed(self):
            if self.current_mode == 'viewer':
                self.viewer_update_timer.start(450)

        def source_cursor_changed(self):
            if self.current_mode == 'viewer':
                self.viewer.set_cursor_line(self.src.textCursor().blockNumber())

        def sync_viewer_from_source(self):
            source_text = self.src.toPlainText()
            if not source_text.strip():
                self.viewer.clear()
                return
            rows = parse_program(source_text, self.name_types) or self.current_rows()
            self.viewer.set_source_text(source_text, self.tool_name_map(rows))
            self.viewer.set_cursor_line(self.src.textCursor().blockNumber())

        def open_machine_settings(self):
            dialog = QDialog(self)
            dialog.setWindowTitle('장비 타입 및 스펙 설정')
            dialog.setMinimumWidth(420)
            body = QVBoxLayout(dialog)
            body.addWidget(QLabel('장비 타입'))
            combo = QComboBox()
            combo.addItems(self.viewer.machine_types())
            combo.setCurrentText(self.viewer.current_machine_type)
            body.addWidget(combo)
            form_widget = QWidget()
            form = QFormLayout(form_widget)
            body.addWidget(form)
            inputs = {}

            def rebuild_form():
                while form.rowCount():
                    form.removeRow(0)
                inputs.clear()
                for key, value in self.viewer.machine_spec(combo.currentText()).items():
                    edit = QLineEdit(str(value))
                    inputs[key] = edit
                    form.addRow(key, edit)

            combo.currentIndexChanged.connect(rebuild_form)
            rebuild_form()
            buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            body.addWidget(buttons)

            def save():
                self.viewer.update_machine_spec(
                    combo.currentText(), {key: edit.text() for key, edit in inputs.items()}
                )
                if self.current_mode == 'viewer':
                    self.sync_viewer_from_source()
                dialog.accept()

            buttons.accepted.connect(save)
            buttons.rejected.connect(dialog.reject)
            dialog.exec_()

        def update_count(self):
            self.count.setText('공구 %d개' % self.table.rowCount())

        def update_metadata_summary(self):
            values = []
            for _column, label, key in PDF_METADATA_FIELDS:
                value = self.metadata.get(key) or '-'
                values.append('%s %s' % (label, value))
            self.metadata_summary.setText('출력 정보: ' + ' | '.join(values))

        def source_cursor_offset(self):
            return self.src.textCursor().position()

        def select_source_span(self, start, end):
            cursor = self.src.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            self.src.setTextCursor(cursor)
            self.src.ensureCursorVisible()
            self.src.setFocus()

        def set_search_status(self, text, error=False):
            color = '#b03a2e' if error else '#5a6577'
            self.search_status.setText(text)
            self.search_status.setStyleSheet('color: %s;' % color)

        def find_next_tool_change(self):
            result = find_next_tool_change_span(self.src.toPlainText(), self.source_cursor_offset())
            if not result:
                self.set_search_status('M6T 항목 없음', True)
                self.src.setFocus()
                return
            start, end, wrapped = result
            self.select_source_span(start, end)
            self.set_search_status('처음부터 검색' if wrapped else '공구 위치 선택')

        def find_next_text(self):
            needle = self.search_text.text()
            if not needle:
                self.set_search_status('검색어 입력 필요', True)
                return
            result = find_next_literal_span(self.src.toPlainText(), needle, self.source_cursor_offset())
            if not result:
                self.set_search_status('검색 결과 없음', True)
                self.src.setFocus()
                return
            start, end, wrapped = result
            self.select_source_span(start, end)
            self.set_search_status('처음부터 검색' if wrapped else '검색 위치 선택')

        def next_tool_no(self):
            numbers = []
            for row in range(self.table.rowCount()):
                value = self.table_text(row, 'NO').upper()
                match = re.fullmatch(r'T?(\d+)', value)
                if match:
                    numbers.append(int(match.group(1)))
            return 'T%02d' % (max(numbers, default=0) + 1)

        def add_row(self):
            values = {key: '' for key, _ in COLUMNS}
            values['NO'] = self.next_tool_no()
            self.show_row_editor(values)

        def edit_selected(self):
            selected_rows = self.selected_rows()
            if not selected_rows:
                QMessageBox.information(self, '알림', '수정할 행을 먼저 선택하세요.')
                return
            row_index = selected_rows[0]
            row = {key: self.table_text(row_index, key) for key, _label in COLUMNS}
            self.show_row_editor(row, row_index)

        def delete_selected(self):
            selected_rows = self.selected_rows()
            if not selected_rows:
                QMessageBox.information(self, '알림', '삭제할 행을 먼저 선택하세요.')
                return
            reply = QMessageBox.question(
                self, '행 삭제', '%d개 행을 삭제할까요?' % len(selected_rows),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            for row in sorted(selected_rows, reverse=True):
                self.table.removeRow(row)
            self.update_count()
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def selected_rows(self):
            return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

        def table_text(self, row, key):
            column = [item_key for item_key, _label in COLUMNS].index(key)
            item = self.table.item(row, column)
            return item.text() if item else ''

        def show_row_editor(self, values, row_index=None):
            dialog = QDialog(self)
            dialog.setWindowTitle('공구 행 수정' if row_index is not None else '공구 행 추가')
            grid = QGridLayout(dialog)
            editors = {}
            for index, (key, label) in enumerate(COLUMNS):
                column = (index // 8) * 2
                row = index % 8
                grid.addWidget(QLabel(label), row, column)
                editor = QLineEdit(str(values.get(key, '')))
                editors[key] = editor
                grid.addWidget(editor, row, column + 1)
            buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            grid.addWidget(buttons, 8, 0, 1, 4)

            def save():
                row = {key: editors[key].text().strip() for key, _label in COLUMNS}
                if not row['TYPE'] and row['NAME']:
                    row['TYPE'] = derive_type(row['NAME'], self.name_types)
                if not row['D'] and row['NAME']:
                    row['D'] = derive_d(row['NAME'])
                target = row_index
                if target is None:
                    target = self.table.rowCount()
                    self.table.insertRow(target)
                self.set_table_row(target, row)
                self.table.selectRow(target)
                self.update_count()
                if self.current_mode == 'viewer':
                    self.sync_viewer_from_source()
                dialog.accept()

            buttons.accepted.connect(save)
            buttons.rejected.connect(dialog.reject)
            dialog.exec_()

        def set_table_row(self, row_index, row):
            for column, (key, _label) in enumerate(COLUMNS):
                item = QTableWidgetItem(str(row.get(key, '')))
                if key not in ('NAME', 'HOLDER', 'REMARK'):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column, item)

        def run(self):
            source_text = self.src.toPlainText()
            self.metadata = parse_program_metadata(source_text)
            rows = parse_program(source_text, self.name_types)
            self.table.setRowCount(0)
            for row_data in rows:
                row_index = self.table.rowCount()
                self.table.insertRow(row_index)
                self.set_table_row(row_index, row_data)
            self.update_count()
            self.update_metadata_summary()
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def open_file(self):
            path, _filter = QFileDialog.getOpenFileName(
                self,
                'NC 프로그램 파일 선택',
                str(Path(self.current_file_path).parent) if self.current_file_path else os.getcwd(),
                'NC/텍스트 파일 (*.nc *.txt *.tap *.min *.prg);;모든 파일 (*.*)',
            )
            if path:
                self.load_file(path)

        def open_add_program_files(self):
            paths, _filter = QFileDialog.getOpenFileNames(
                self,
                '추가할 NC 프로그램 파일 선택',
                str(Path(self.current_file_path).parent) if self.current_file_path else os.getcwd(),
                'NC/텍스트 파일 (*.nc *.txt *.tap *.min *.prg);;모든 파일 (*.*)',
            )
            if paths:
                self.add_program_files(paths)

        def read_program_file(self, path):
            with open(path, 'r', encoding='utf-8', errors='replace') as fp:
                return fp.read()

        def load_file(self, path):
            try:
                data = self.read_program_file(path)
            except Exception as error:
                QMessageBox.critical(self, '열기 실패', str(error))
                return
            self.current_file_path = path
            with QSignalBlocker(self.src):
                self.src.setPlainText(data)
            self.run()
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def add_program_files(self, paths):
            additions = []
            last_path = None
            for path in paths:
                try:
                    additions.append(self.read_program_file(path))
                    last_path = path
                except Exception as error:
                    QMessageBox.critical(self, '추가 실패', '%s\n%s' % (path, error))
                    return
            if not additions:
                return
            self.current_file_path = last_path or self.current_file_path
            combined = append_nc_programs(self.src.toPlainText(), additions)
            with QSignalBlocker(self.src):
                self.src.setPlainText(combined)
            self.run()
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def drop_file(self, paths):
            if not paths:
                return
            if self.src.toPlainText().strip():
                self.add_program_files(paths)
                return
            self.load_file(paths[0])
            if len(paths) > 1:
                self.add_program_files(paths[1:])

        def load_example(self):
            with QSignalBlocker(self.src):
                self.src.setPlainText(EXAMPLE)
            self.run()
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def clear(self):
            self.src.clear()
            self.table.setRowCount(0)
            self.update_count()
            self.metadata = {key: '' for key in METADATA_ALIASES}
            self.metadata_summary.setText('출력 정보: -')
            self.viewer.clear()

        def show_type_list(self):
            dialog = QDialog(self)
            dialog.setWindowTitle('이름 → TYPE 경우의 수')
            dialog.resize(520, 470)
            layout = QVBoxLayout(dialog)
            title = QLabel('공구 이름 → TYPE 변환표')
            title.setFont(QFont('맑은 고딕', 10, QFont.Bold))
            layout.addWidget(title)
            table = QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(['이름(약어·표현)', 'TYPE'])
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            layout.addWidget(table, 1)

            def refresh():
                table.setRowCount(0)
                for abbr, typ in self.name_types:
                    row = table.rowCount()
                    table.insertRow(row)
                    table.setItem(row, 0, QTableWidgetItem(abbr))
                    table.setItem(row, 1, QTableWidgetItem(typ))

            def save_mappings():
                try:
                    save_name_types(self.name_types)
                except OSError as error:
                    QMessageBox.critical(dialog, '저장 실패', str(error))
                    return False
                return True

            def selected_index():
                rows = table.selectionModel().selectedRows()
                if not rows:
                    QMessageBox.information(dialog, '알림', '수정하거나 삭제할 경우를 선택하세요.')
                    return None
                return rows[0].row()

            def open_editor(index=None):
                current = self.name_types[index] if index is not None else ('', '')
                editor = QDialog(dialog)
                editor.setWindowTitle('이름 경우 수정' if index is not None else '이름 경우 추가')
                form = QFormLayout(editor)
                name_edit = QLineEdit(current[0])
                type_edit = QLineEdit(current[1])
                form.addRow('이름(약어·표현)', name_edit)
                form.addRow('TYPE', type_edit)
                buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
                form.addRow(buttons)

                def commit():
                    abbr = name_edit.text().strip()
                    typ = type_edit.text().strip()
                    if not abbr or not typ:
                        QMessageBox.warning(editor, '입력 확인', '이름과 TYPE을 모두 입력하세요.')
                        return
                    duplicate = next(
                        (i for i, pair in enumerate(self.name_types)
                         if pair[0].upper() == abbr.upper() and i != index),
                        None,
                    )
                    if duplicate is not None:
                        QMessageBox.warning(editor, '중복 이름', '같은 이름 경우가 이미 있습니다.')
                        return
                    if index is None:
                        self.name_types.append((abbr, typ))
                    else:
                        self.name_types[index] = (abbr, typ)
                    if save_mappings():
                        refresh()
                        editor.accept()

                buttons.accepted.connect(commit)
                buttons.rejected.connect(editor.reject)
                editor.exec_()

            controls = QHBoxLayout()
            self._add_button(controls, '＋ 추가', lambda: open_editor())

            def edit_case():
                index = selected_index()
                if index is not None:
                    open_editor(index)

            self._add_button(controls, '수정', edit_case)

            def delete_case():
                index = selected_index()
                if index is None:
                    return
                if QMessageBox.question(dialog, '이름 경우 삭제', '선택한 이름 경우를 삭제할까요?') == QMessageBox.Yes:
                    del self.name_types[index]
                    if save_mappings():
                        refresh()

            def restore_defaults():
                if QMessageBox.question(dialog, '기본값 복원', '기본 이름 경우의 수로 되돌릴까요?') == QMessageBox.Yes:
                    self.name_types = list(DEFAULT_NAME_TYPES)
                    if save_mappings():
                        refresh()

            self._add_button(controls, '삭제', delete_case)
            self._add_button(controls, '기본값 복원', restore_defaults)
            controls.addStretch()
            self._add_button(controls, '닫기', dialog.accept)
            layout.addLayout(controls)
            table.doubleClicked.connect(lambda _index: open_editor(selected_index()))
            refresh()
            dialog.exec_()

        def export_pdf(self):
            rows = self.current_rows()
            if not rows:
                QMessageBox.information(self, '알림', '먼저 공구 리스트를 생성하세요.')
                return
            path, _filter = QFileDialog.getSaveFileName(
                self,
                '공구 리스트 PDF 저장',
                default_pdf_filename(self.metadata),
                'PDF 파일 (*.pdf)',
            )
            if path:
                self.save_pdf(path, rows)

        def save_pdf(self, path, rows):
            try:
                export_tool_list_pdf(path, rows, self.metadata)
            except Exception as error:
                QMessageBox.critical(self, 'PDF 출력 실패', str(error))
                return
            open_error = open_file_with_default_app(path)
            if open_error:
                QMessageBox.warning(
                    self, 'PDF 열기 실패',
                    'PDF 파일은 저장했지만 자동으로 열지 못했습니다.\n%s\n%s' % (path, open_error),
                )
                return
            QMessageBox.information(self, 'PDF 출력 완료', 'PDF 파일을 저장하고 열었습니다.\n' + path)

        def current_rows(self):
            rows = []
            for row_index in range(self.table.rowCount()):
                rows.append({key: self.table_text(row_index, key) for key, _label in COLUMNS})
            return rows

        def tool_name_map(self, rows):
            return tool_name_map_from_rows(rows)

        def copy_table(self):
            if self.table.rowCount() == 0:
                QMessageBox.information(self, '알림', '먼저 공구 리스트를 생성하세요.')
                return
            lines = []
            if self.with_header.isChecked():
                lines.append('\t'.join(label for _key, label in COLUMNS))
            for row in self.current_rows():
                lines.append('\t'.join(str(row.get(key, '')) for key, _label in COLUMNS))
            QApplication.clipboard().setText('\n'.join(lines))
            self.count.setText('복사됨! 엑셀에서 Ctrl+V')
            QTimer.singleShot(1800, self.update_count)


def main():
    missing = missing_viewer_dependencies()
    if missing:
        raise SystemExit('GUI 실행에 필요한 Python 패키지가 없습니다: ' + ', '.join(missing))
    app = QApplication(sys.argv)
    window = App()
    initial_file = startup_file_argument(sys.argv)
    if initial_file:
        QTimer.singleShot(0, lambda path=initial_file: window.load_file(path))
    window.show()
    sys.exit(app.exec_())

EXAMPLE = """NC PGM
%
O0001
( ** TECH STAR ** )
( PGM NO :  OP10_SSTR4171 )
( COMPLETE TIME : 11:15:01 )
( DATE : 2026-08-25 )
( PROGRAMER : S M.HWANG)
( MACHINE : M2-5AX / WORK CODE: 501 )
G0 G90 G49 G69 G80 G40 G17
M111
N1(#1: Tool Change)
 (T2 // D10 F.EM [SO 40] // T2 BT40-SK16-120 )
 (LCF   38.500000 FL   26.000000 GL  160.000000 F 3)
 (DC   10.000000 RE    0.000000 SIG PL )
 (SPINDL 10000.000000 FEED  4100.000000)
M6 T2
N2(#2: Tool Change)
 (T3 // D6 B.EM [SO 30] // T3 BT40-SK10-120 )
 (LCF   30.000000 FL   10.000000 GL  150.000000 F 2)
 (DC    6.000000 RE    3.000000 SIG PL )
 (SPINDL 10000.000000 FEED  3600.000000)
M6 T3
N3(#3: Tool Change)
 (T4 // D2.3 DRILL [SO 20] // T4 BT40-SK10-90 )
 (LCF   20.000000 FL   15.000000 GL  140.000000 F 2)
 (DC    2.300000 RE SIG  118.000000 PL    0.691000 )
 (SPINDL  3800.000000 FEED   152.000000)
M6 T4
N4(#4: Tool Change)
 (T2 // D10 F.EM [SO 40] // T2 BT40-SK16-120 )
 (LCF   38.500000 FL   26.000000 GL  160.000000 F 3)
 (DC   10.000000 RE    0.000000 SIG PL )
 (SPINDL 10000.000000 FEED  3600.000000)
M6 T2
N5(#5: Tool Change)
 (T6 // D1 B.EM [SO 22] // T6 BT40-SK10-120 )
 (LCF   22.000000 FL    4.000000 GL  142.000000 F 2)
 (DC    1.000000 RE    0.500000 SIG PL )
 (SPINDL  8000.000000 FEED   320.000000)
M6 T6
N6(#6: Tool Change)
 (T4 // D2.3 DRILL [SO 20] // T4 BT40-SK10-90 )
 (LCF   20.000000 FL   15.000000 GL  140.000000 F 2)
 (DC    2.300000 RE SIG  118.000000 PL    0.691000 )
 (SPINDL  3800.000000 FEED   152.000000)
M6 T4
N7(#7: Tool Change)
 (T2 // D10 F.EM [SO 40] // T2 BT40-SK16-120 )
 (LCF   38.500000 FL   26.000000 GL  160.000000 F 3)
 (DC   10.000000 RE    0.000000 SIG PL )
 (SPINDL 10000.000000 FEED  1500.000000)
M6 T2
N8(#8: Tool Change)
 (T5 // D6 F.EM [SO 35] // T5 BT40-SK13-120 )
 (LCF   35.000000 FL   15.000000 GL  155.000000 F 3)
 (DC    6.000000 RE    0.000000 SIG PL )
 (SPINDL 10000.000000 FEED  1500.000000)
M6 T5
N9(#9: Tool Change)
 (T5 // D6 F.EM [SO 35] // T5 BT40-SK13-120 )
 (LCF   35.000000 FL   15.000000 GL  155.000000 F 3)
 (DC    6.000000 RE    0.000000 SIG PL )
 (SPINDL 10000.000000 FEED  1500.000000)
M6 T5
N10(#10: Tool Change)
 (T5 // D6 F.EM [SO 35] // T5 BT40-SK13-120 )
 (LCF   35.000000 FL   15.000000 GL  155.000000 F 3)
 (DC    6.000000 RE    0.000000 SIG PL )
 (SPINDL 10000.000000 FEED  1500.000000)
M6 T5
M30
%"""


if __name__ == '__main__':
    main()
