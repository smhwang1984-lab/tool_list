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
import shutil
import sys
import tempfile
import traceback
from datetime import date, datetime
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


APP_VERSION = '1.6.1'
APP_NAME = 'Sum Path'
APP_BUILD_DATE = '2026-09-05'
APP_CREATOR = 'Hwang.seonmun'
APP_PURPOSE = 'NC 프로그램에서 공구 리스트를 산출하고 NC 경로를 Viewer로 확인하는 도구'
OPEN_SOURCE_COMPONENTS = (
    'Python',
    'PyQt5',
    'pyqtgraph',
    'NumPy',
    'PyOpenGL',
    'ReportLab',
    'PyInstaller',
    'Inno Setup',
)
DEFAULT_UPDATE_ROOT = r'\\192.168.0.210\생산부서\05. 생산자료\Update_Files'
UPDATE_INSTALLER_RE = re.compile(r'^NC_Tool_List_Setup_v(\d+)\.(\d+)\.(\d+)\.exe$', re.I)
FILE_ASSOCIATION_EXTENSIONS = ('.nc', '.mpf', '.tap')
FILE_ASSOCIATION_PROG_ID = 'NCToolList.NCProgram'

# v1.6.2: 프로그램 입력 패널을 최소 폭까지 좁히면 '지우기'~'Tool List' 버튼
# 줄(가로 합 468px + 간격 24px + 좌우 여백 14px = 506px)이 다 들어가지 못해
# 'Tool List' 버튼이 가려지던 문제를 고쳤다 — 최소 폭을 그 필요폭보다 넉넉히
# 크게 잡는다.
PROGRAM_PANE_MIN_WIDTH = 520
VIEWER_PANE_INITIAL_WIDTH = 1125
INPUT_SPLITTER_INITIAL_SIZES = [480, 208]
MAIN_SPLITTER_INITIAL_SIZES = [PROGRAM_PANE_MIN_WIDTH, VIEWER_PANE_INITIAL_WIDTH]

# v1.6.2: 상단 바 맨 끝(다크모드 버튼)과 창 오른쪽 가장자리 사이의 여백.
TOP_BAR_EDGE_GAP_PX = 8

# v1.6.2: 1920x1080에서 필터 영역(텍스트 정지~PG 매칭 전체/해제) 레이아웃과
# 폰트를 15% 키운다.
FILTER_SECTION_SCALE = 1.15


def scaled(value):
    """FILTER_SECTION_SCALE(1.15배)을 적용한 정수 픽셀/포인트 값."""
    return round(value * FILTER_SECTION_SCALE)

# 라이트/다크 테마 색상 토큰. 의미 기반 키로 두어 위젯 각각이 하드코딩된
# 색 대신 이 값을 참조하고, 다크모드 토글 시 App.apply_theme()이 전체를
# 다시 칠한다. 뷰어(nc_viewer_widget.py)의 3D 캔버스는 테마와 무관하게
# 항상 어두운 배경을 쓰므로 이 테마를 참조하지 않는다(v1.5.7).
THEMES = {
    'light': {
        'window_bg': '#f0f4f8', 'panel_bg': '#ffffff', 'text': '#1f2937',
        'muted_text': '#5a6577', 'faint_text': '#8a94a3', 'border': '#c5ced8',
        'header_bg': '#1f3a5f', 'header_text': '#ffffff', 'header_caption': '#c8d4e2',
        'accent': '#2f6fb0', 'accent_text': '#ffffff', 'accent_hover': '#255a92',
        'success': '#4c7f31', 'success_text': '#ffffff',
        'neutral_button': '#555555', 'neutral_button_text': '#ffffff',
        'editor_bg': '#ffffff', 'editor_text': '#1f2937', 'current_line': '#dbe7f5',
        'list_bg': '#ffffff', 'list_text': '#1f2937', 'list_hover': '#eaf1f8',
        'list_selected_bg': '#2f6fb0', 'list_selected_text': '#ffffff',
        'info_bg': '#eaf1f8', 'info_text': '#40536b', 'error': '#b03a2e',
        'mode_active_bg': '#34577f', 'mode_active_text': '#ffffff',
        'mode_inactive_bg': '#f0f4f8', 'mode_inactive_text': '#1f3a5f',
    },
    'dark': {
        'window_bg': '#1b1f27', 'panel_bg': '#242a35', 'text': '#e4e8f0',
        'muted_text': '#9aa5b8', 'faint_text': '#7a8494', 'border': '#3a4250',
        'header_bg': '#10192b', 'header_text': '#e4e8f0', 'header_caption': '#8ea3c4',
        'accent': '#3f7fc9', 'accent_text': '#ffffff', 'accent_hover': '#5090d6',
        'success': '#4f9a38', 'success_text': '#ffffff',
        'neutral_button': '#4a5164', 'neutral_button_text': '#ffffff',
        'editor_bg': '#1a1f29', 'editor_text': '#dbe3f0', 'current_line': '#2c3a52',
        'list_bg': '#20262f', 'list_text': '#dbe3f0', 'list_hover': '#2c3644',
        'list_selected_bg': '#3f7fc9', 'list_selected_text': '#ffffff',
        'info_bg': '#233047', 'info_text': '#b7c8e6', 'error': '#e06a5a',
        'mode_active_bg': '#3f7fc9', 'mode_active_text': '#ffffff',
        'mode_inactive_bg': '#2a2f3a', 'mode_inactive_text': '#c7d0e0',
    },
}

# ---------- 파싱 로직 ----------
TOOL_RE = re.compile(r'\(\s*T(\d+)\s*//\s*(.*?)\s*\[SO\s*([\d.]+)\]\s*//\s*T\d+\s*([^)]*?)\s*\)', re.I)
N_RE    = re.compile(r'^\s*N(\d+)\s*\(\s*#\d+\s*:\s*Tool\s*Change', re.I)
M6_RE   = re.compile(r'^\s*M0?6\s*T0*(\d+)\b', re.I)
M6_SEARCH_RE = re.compile(r'^\s*M0?6\s*T0*\d+\b', re.I | re.M)
M00_STOP_RE = re.compile(r'M0?0(?!\d)', re.I)
M01_STOP_RE = re.compile(r'M0?1(?!\d)', re.I)
MAX_PLAYBACK_SPEED = 5000
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
# v1.5.9: 표기 셀(칸) 크기를 요청대로 기존 값의 1.6배로 키움.
_COL_WIDTH_BASE = {
    'NO': 72, 'TYPE': 128, 'NAME': 152, 'D': 72, 'FL': 72, 'LCF': 80, 'F': 56,
    'R': 72, 'SIG': 72, 'PL': 88, 'SO': 72, 'GL': 80, 'HOLDER': 192,
    'SPINDL': 96, 'FEED': 88, 'REMARK': 176,
}
# v1.6.0: 복사용 표 셀 좌우에 글자가 가려지지 않도록 폰트 한글자 폭의
# 절반(표 폰트 14pt 기준 근사치) 만큼 양쪽 여백을 추가한다. 여백은
# QTableWidget::item의 padding으로 그리므로, 실제 글자가 그려지는 폭이
# 줄어들지 않도록 칸 너비 자체도 그만큼 넓힌다.
# v1.6.2: 공구 리스트(복사용 표기) 폰트 크기와 셀 폭을 요청대로 15% 줄인다
# — 패딩도 같은 비율로 줄여 전체 칸 폭이 정확히 15% 작아지게 한다.
COPY_TABLE_SCALE = 0.85
TABLE_FONT_PT = 14 * COPY_TABLE_SCALE
TABLE_CELL_PADDING_PX = round(8 * COPY_TABLE_SCALE)
COL_WIDTH = {
    key: round(width * COPY_TABLE_SCALE) + TABLE_CELL_PADDING_PX * 2
    for key, width in _COL_WIDTH_BASE.items()
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


def _stop_scan_code(line):
    """정지 코드 검사를 위해 주석(괄호/세미콜론 이후)을 제거하고 공백을 없앤다."""
    code = re.sub(r'\([^)]*\)', ' ', str(line or '')).split(';')[0]
    return code.replace(' ', '')


def line_has_m00_stop(line):
    """M00/M0 (프로그램 정지)가 있는 줄인지. 주석은 제외."""
    return M00_STOP_RE.search(_stop_scan_code(line)) is not None


def line_has_m01_stop(line):
    """M01/M1 (옵셔널 정지)이 있는 줄인지. 주석은 제외."""
    return M01_STOP_RE.search(_stop_scan_code(line)) is not None


def line_has_program_stop(line):
    """M00/M0/M01/M1 (프로그램 정지·옵셔널 정지)가 있는 줄인지. 주석은 제외."""
    return line_has_m00_stop(line) or line_has_m01_stop(line)


def line_stops_playback(line, needle='', stop_text=False, stop_m00=True, stop_m01=True):
    """PG 매칭 자동 재생이 이 줄에서 멈춰야 하는지. 세 옵션 모두 해제면 멈추지 않는다."""
    if stop_m00 and line_has_m00_stop(line):
        return True
    if stop_m01 and line_has_m01_stop(line):
        return True
    if stop_text and needle:
        return needle.lower() in str(line or '').lower()
    return False


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


# ---------- 앱 설정(업데이트 경로 등) ----------
def app_settings_path():
    """Return a user-writable path even when installed in Program Files."""
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'NC Tool List' / 'app_settings.json'


def load_app_settings():
    try:
        with app_settings_path().open('r', encoding='utf-8') as fp:
            saved = json.load(fp)
        if isinstance(saved, dict):
            return saved
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_app_settings(settings):
    path = app_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fp:
        json.dump(settings, fp, ensure_ascii=False, indent=2)


def update_root_setting():
    """PC별로 지정한 업데이트 경로. 지정된 값이 없으면 기본 공유 경로를 사용."""
    value = str(load_app_settings().get('update_root') or '').strip()
    return value or DEFAULT_UPDATE_ROOT


def save_update_root_setting(update_root):
    settings = load_app_settings()
    settings['update_root'] = str(update_root or '').strip()
    save_app_settings(settings)


# ---------- 수동 업데이트 ----------
def current_version_tuple(version=None):
    return tuple(int(part) for part in (version or APP_VERSION).split('.'))


def parse_installer_version(filename):
    """'NC_Tool_List_Setup_v1.5.1.exe' -> (1, 5, 1); 형식이 다르면 None."""
    match = UPDATE_INSTALLER_RE.match(str(filename or '').strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def find_latest_installer(update_root):
    """update_root 아래에서 가장 높은 버전의 설치 파일을 찾아 (경로, 버전튜플)을 반환. 없으면 None."""
    try:
        entries = list(Path(update_root).iterdir())
    except OSError:
        return None
    best = None
    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue
        version = parse_installer_version(entry.name)
        if version is None:
            continue
        if best is None or version > best[1]:
            best = (entry, version)
    return best


def copy_installer_to_temp(source_path):
    """네트워크 공유가 끊기거나 파일이 잠겨도 설치가 실패하지 않도록 임시 폴더로 먼저 복사."""
    source_path = Path(source_path)
    destination = Path(tempfile.gettempdir()) / source_path.name
    shutil.copy2(source_path, destination)
    return destination


# ---------- 확장자 기본 프로그램 등록 ----------
def file_association_command():
    """앱 실행 파일(또는 소스 실행 시 python.exe)을 인자와 함께 호출하는 명령 문자열."""
    if getattr(sys, 'frozen', False):
        return '"%s" "%%1"' % sys.executable
    return '"%s" "%s" "%%1"' % (sys.executable, os.path.abspath(__file__))


def file_association_icon_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    return resource_path('assets/nc_tool_list.ico')


def _delete_registry_tree(root, path):
    import winreg
    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
    except OSError:
        return
    with key:
        while True:
            try:
                subkey_name = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_registry_tree(root, path + '\\' + subkey_name)
    try:
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def notify_shell_associations_changed():
    try:
        import ctypes
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


def register_file_associations():
    """현재 사용자(HKCU) 범위로 .nc/.mpf/.tap을 이 앱의 기본 프로그램으로 등록. 관리자 권한 불필요."""
    if os.name != 'nt':
        return False
    import winreg
    root = winreg.HKEY_CURRENT_USER
    command = file_association_command()
    icon_path = file_association_icon_path()
    prog_id_key = r'Software\Classes\%s' % FILE_ASSOCIATION_PROG_ID
    with winreg.CreateKey(root, prog_id_key) as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'NC 프로그램')
    with winreg.CreateKey(root, prog_id_key + r'\DefaultIcon') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, icon_path)
    with winreg.CreateKey(root, prog_id_key + r'\shell\open\command') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, command)
    for ext in FILE_ASSOCIATION_EXTENSIONS:
        ext_key = r'Software\Classes\%s' % ext
        with winreg.CreateKey(root, ext_key) as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, FILE_ASSOCIATION_PROG_ID)
        with winreg.CreateKey(root, ext_key + r'\OpenWithProgids') as key:
            winreg.SetValueEx(key, FILE_ASSOCIATION_PROG_ID, 0, winreg.REG_SZ, '')
    notify_shell_associations_changed()
    return True


def unregister_file_associations():
    """About에서 등록한 HKCU 연결을 해제. 설치 프로그램이 등록한 HKLM 연결은 건드리지 않음."""
    if os.name != 'nt':
        return False
    import winreg
    root = winreg.HKEY_CURRENT_USER
    for ext in FILE_ASSOCIATION_EXTENSIONS:
        try:
            winreg.DeleteKey(root, r'Software\Classes\%s\OpenWithProgids' % ext)
        except OSError:
            pass
        try:
            with winreg.OpenKey(root, r'Software\Classes\%s' % ext, 0,
                                 winreg.KEY_READ | winreg.KEY_WRITE) as key:
                value, _kind = winreg.QueryValueEx(key, '')
                if value == FILE_ASSOCIATION_PROG_ID:
                    winreg.DeleteValue(key, '')
        except OSError:
            pass
    _delete_registry_tree(root, r'Software\Classes\%s' % FILE_ASSOCIATION_PROG_ID)
    notify_shell_associations_changed()
    return True


def file_associations_status():
    """확장자 3종이 모두 이 앱의 ProgId로 연결돼 있으면 True (HKCU/HKLM 어느 쪽이든 인정)."""
    if os.name != 'nt':
        return False
    import winreg
    for ext in FILE_ASSOCIATION_EXTENSIONS:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as key:
                value, _kind = winreg.QueryValueEx(key, '')
        except OSError:
            return False
        if value != FILE_ASSOCIATION_PROG_ID:
            return False
    return True


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



def startup_log_path():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home())
    return base / 'NC_Tool_List' / 'startup.log'


def write_startup_log(message):
    try:
        path = startup_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write('[%s] %s\n' % (datetime.now().isoformat(timespec='seconds'), message))
    except Exception:
        pass
def missing_viewer_dependencies():
    if getattr(sys, 'frozen', False):
        return []
    return [name for name in ('PyQt5', 'pyqtgraph', 'numpy')
            if importlib.util.find_spec(name) is None]


QT_IMPORT_ERROR = None
VIEWER_IMPORT_ERROR = None
NCViewerWidget = None
try:
    from PyQt5.QtCore import Qt, QSettings, QSize, QTimer, QSignalBlocker, pyqtSignal
    from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QTextCursor, QTextFormat
    from PyQt5.QtWidgets import (
        QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
        QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
        QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
        QPlainTextEdit, QPushButton, QShortcut, QSplitter, QStackedWidget, QTableWidget,
        QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    )
except ImportError as error:
    QT_IMPORT_ERROR = error

if QT_IMPORT_ERROR is None:
    try:
        from nc_viewer_widget import NCViewerWidget
    except Exception as error:
        VIEWER_IMPORT_ERROR = error
        write_startup_log('Viewer import failed: %s\n%s' % (error, traceback.format_exc()))


# ---------- GUI ----------
if QT_IMPORT_ERROR is not None:
    class App:
        def __init__(self, *args, **kwargs):
            raise RuntimeError('GUI 실행에 필요한 패키지가 없습니다: %s' % QT_IMPORT_ERROR)
else:
    class ProgramTextEdit(QPlainTextEdit):
        # QTextEdit(리치 텍스트)이 아닌 QPlainTextEdit을 쓴다 — 3만 줄대의 NoWrap
        # 문서를 실제 레이아웃(스플리터)에 얹은 채 setExtraSelections()를 호출하면
        # QTextEdit은 사실상 멈춘 것처럼 보일 정도로 느려진다(줄 강조 도입 후
        # 발견된 회귀, v1.5.2). QPlainTextEdit은 대용량 평문 문서를 위해 설계된
        # 위젯이라 같은 조건에서 즉시 끝난다. 공개 API가 거의 동일해 아래
        # toPlainText/setPlainText/textCursor/document 등은 그대로 쓸 수 있고,
        # ExtraSelection만 QPlainTextEdit에 별도 별칭이 없어 QTextEdit.ExtraSelection을
        # 계속 쓴다(Qt C++ 쪽에서도 QPlainTextEdit::ExtraSelection은 QTextEdit::
        # ExtraSelection의 typedef라 같은 타입이다).
        filesDropped = pyqtSignal(list)
        focusGained = pyqtSignal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAcceptDrops(True)

        def focusInEvent(self, event):
            super().focusInEvent(event)
            self.focusGained.emit()

        def setReadOnly(self, read_only):
            super().setReadOnly(read_only)
            self.setAcceptDrops(True)
            if read_only:
                # Qt의 setReadOnly(True)는 상호작용 플래그를 TextSelectableByMouse
                # 하나로 덮어써서 키보드 커서를 없애버린다. 방향키/PgUp/PgDn으로
                # 커서를 옮기려면 TextSelectableByKeyboard를 다시 켜줘야 한다.
                self.setTextInteractionFlags(
                    Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
                )

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


    FALLBACK_MACHINE_SPECS = {
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


    class ViewerFallbackWidget(QWidget):
        def __init__(self, error=None, parent=None):
            super().__init__(parent)
            self.error = error
            self.settings = QSettings("NC Tool List", "EmbeddedViewer")
            self.machine_specs = json.loads(json.dumps(FALLBACK_MACHINE_SPECS, ensure_ascii=False))
            self.current_machine_type = self.settings.value(
                "machine_type", next(iter(self.machine_specs))
            )
            if self.current_machine_type not in self.machine_specs:
                self.current_machine_type = next(iter(self.machine_specs))
            self.tool_filter_list = None
            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 12, 12, 12)
            message = QLabel(
                "3D Viewer를 이 PC에서 시작하지 못했습니다.\n"
                "공구 리스트 생성, 복사, PDF 출력은 계속 사용할 수 있습니다.\n"
                "로그: %s" % startup_log_path()
            )
            message.setWordWrap(True)
            message.setStyleSheet("color: #8a3b00; font-weight: bold;")
            layout.addWidget(message)
            detail = QLabel(str(error or VIEWER_IMPORT_ERROR or "OpenGL viewer unavailable"))
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #5a6577;")
            layout.addWidget(detail)
            layout.addStretch()

        def attach_tool_filter(self, list_widget):
            self.tool_filter_list = list_widget
            self.tool_filter_list.setSelectionMode(QAbstractItemView.MultiSelection)

        def clear(self):
            if self.tool_filter_list is not None:
                self.tool_filter_list.clear()

        def set_source_text(self, text, tool_name_map=None):
            if self.tool_filter_list is None:
                return False
            self.tool_filter_list.clear()
            for tool_no in sorted(set((tool_name_map or {}).values())):
                self.tool_filter_list.addItem(QListWidgetItem(str(tool_no)))
            return False

        def set_cursor_line(self, _line):
            return None

        def set_pg_match_mode(self, _enabled):
            # 폴백에서는 그릴 경로 자체가 없으므로 아무 일도 하지 않는다.
            return None

        def set_dark_mode(self, _enabled):
            # 폴백 화면은 3D를 그리지 않아 배경 전환이 필요 없다.
            return None

        def select_all_tools(self, selected):
            if self.tool_filter_list is None:
                return
            for index in range(self.tool_filter_list.count()):
                self.tool_filter_list.item(index).setSelected(bool(selected))

        def machine_types(self):
            return list(self.machine_specs.keys())

        def machine_spec(self, machine_type=None):
            machine_type = machine_type or self.current_machine_type
            return dict(self.machine_specs.get(machine_type, {}))

        def set_machine_type(self, machine_type, init_camera=False):
            if machine_type in self.machine_specs:
                self.current_machine_type = machine_type
                self.settings.setValue("machine_type", machine_type)

        def update_machine_spec(self, machine_type, specs):
            self.machine_specs[str(machine_type)] = {
                str(key): str(value).strip() for key, value in specs.items()
            }
            self.set_machine_type(str(machine_type))


    class App(QMainWindow):
        def __init__(self, _root=None):
            super().__init__()
            self.name_types = load_name_types()
            self.metadata = {key: '' for key in METADATA_ALIASES}
            self.current_file_path = None
            self.current_mode = 'tool'
            self._last_parsed_source = None
            self._last_parsed_rows = []
            self._last_parsed_metadata = {key: '' for key in METADATA_ALIASES}
            self.viewer_update_timer = QTimer(self)
            self.viewer_update_timer.setSingleShot(True)
            self.viewer_update_timer.timeout.connect(self.sync_viewer_from_source)
            self._gl_info_logged = False
            if _root is None:
                self.layout_settings = QSettings('NC Tool List', 'MainWindow')
            else:
                self.layout_settings = QSettings(str(Path(_root) / 'ui_layout.ini'), QSettings.IniFormat)
            # PG 매칭 자동 재생: 50ms(20Hz) 고정 틱으로 배속과 무관하게 화면 갱신
            # 빈도를 일정하게 유지하고, 한 틱에 여러 줄을 건너뛰어 배속을 맞춘다.
            self.play_timer = QTimer(self)
            self.play_timer.setInterval(50)
            self.play_timer.timeout.connect(self._playback_tick)
            self.play_speed = self._load_playback_speed()
            self._play_carry = 0.0
            self._search_status_error = False

            # 다크모드: _build_ui()가 위젯을 만들 때부터 올바른 색을 쓰도록
            # UI 생성 전에 테마를 먼저 정한다. 큐브 크기 슬라이더 옆 토글
            # 버튼(뷰어 쪽)이 실제 전환을 담당한다.
            self.theme_name = 'dark' if self._load_dark_mode() else 'light'
            self.theme = THEMES[self.theme_name]

            self.setWindowTitle('%s v%s' % (APP_NAME, APP_VERSION))
            self.resize(sum(MAIN_SPLITTER_INITIAL_SIZES), 760)
            self.set_window_icon()
            self._build_ui()
            self._install_shortcuts()
            self.apply_theme(self.theme_name)
            if not self.restore_layout_settings():
                QTimer.singleShot(0, self.showMaximized)


        def _create_viewer(self):
            if NCViewerWidget is None:
                return ViewerFallbackWidget(VIEWER_IMPORT_ERROR, self)
            try:
                return NCViewerWidget(self)
            except Exception as error:
                write_startup_log('Viewer startup failed: %s\n%s' % (error, traceback.format_exc()))
                return ViewerFallbackWidget(error, self)

        def log_gl_info(self):
            """Record the live GL context once; the packaged app has no console."""
            if self._gl_info_logged:
                return
            self._gl_info_logged = True
            view = getattr(self.viewer, 'gl_view', None)
            if view is None:
                return
            try:
                from OpenGL.GL import glGetString, GL_RENDERER, GL_VENDOR, GL_VERSION
                view.makeCurrent()
                try:
                    values = []
                    for label, token in (('vendor', GL_VENDOR), ('renderer', GL_RENDERER),
                                         ('version', GL_VERSION)):
                        value = glGetString(token)
                        values.append('%s=%s' % (
                            label, value.decode('utf-8', 'replace') if isinstance(value, bytes) else value
                        ))
                    write_startup_log('OpenGL ' + ' '.join(values))
                finally:
                    view.doneCurrent()
            except Exception as error:
                write_startup_log('OpenGL context unavailable: %r' % (error,))

        # ---------- 다크모드 ----------
        def _load_dark_mode(self):
            # v1.6.0: 최초 실행(저장된 설정 없음) 시 다크모드를 기본값으로 시작한다.
            raw = self.layout_settings.value('dark_mode', True)
            if isinstance(raw, str):
                return raw.strip().lower() in ('1', 'true', 'yes')
            return bool(raw)

        def toggle_dark_mode(self, enabled):
            self.apply_theme('dark' if enabled else 'light')

        def apply_theme(self, name):
            """전체 앱 배색을 전환한다. QApplication 전역 스타일시트로 기본
            위젯들을 칠하고, 하드코딩된 색을 쓰던 개별 위젯들을 다시 그린다."""
            self.theme_name = name
            self.theme = THEMES[name]
            self.layout_settings.setValue('dark_mode', name == 'dark')

            app_instance = QApplication.instance()
            if app_instance is not None:
                app_instance.setStyleSheet(self._build_global_stylesheet(self.theme))

            self._apply_widget_themes()
            # 상태에 따라 달라지는 스타일은 해당 상태를 그대로 다시 넣어 갱신한다.
            self._style_mode_buttons()
            if hasattr(self, 'machine_panel_toggle'):
                self.set_machine_panel_expanded(self.machine_panel_toggle.isChecked())
            if hasattr(self, 'search_status'):
                self.set_search_status(self.search_status.text(), self._search_status_error)
            if hasattr(self, 'viewer') and hasattr(self.viewer, 'set_dark_mode'):
                self.viewer.set_dark_mode(name == 'dark')
            self._highlight_current_line()

        @staticmethod
        def _build_global_stylesheet(t):
            """QMainWindow/QDialog를 포함한 기본 위젯 전체에 적용되는 전역
            스타일시트. 개별 위젯의 setStyleSheet() 인스턴스 지정값이 항상
            우선하므로, 아래 규칙은 그 값이 없는 속성에만 실제로 적용된다."""
            t = dict(t, table_cell_padding=TABLE_CELL_PADDING_PX)
            return (
                'QMainWindow, QWidget, QDialog { background: %(window_bg)s; color: %(text)s; }'
                'QLabel { color: %(text)s; }'
                'QPlainTextEdit, QTextEdit, QLineEdit {'
                ' background: %(editor_bg)s; color: %(editor_text)s; border: 1px solid %(border)s; }'
                'QPushButton {'
                ' background: %(panel_bg)s; color: %(text)s; border: 1px solid %(border)s;'
                ' border-radius: 3px; padding: 4px 8px; }'
                'QPushButton:hover { background: %(list_hover)s; }'
                'QPushButton:disabled { color: %(faint_text)s; }'
                'QComboBox {'
                ' background: %(editor_bg)s; color: %(editor_text)s; border: 1px solid %(border)s; }'
                'QComboBox QAbstractItemView {'
                ' background: %(editor_bg)s; color: %(editor_text)s;'
                ' selection-background-color: %(list_selected_bg)s; selection-color: %(list_selected_text)s; }'
                'QCheckBox { color: %(text)s; }'
                'QGroupBox { color: %(text)s; }'
                'QTableWidget {'
                ' background: %(list_bg)s; color: %(list_text)s; gridline-color: %(border)s;'
                ' alternate-background-color: %(list_hover)s;'
                ' selection-background-color: %(list_selected_bg)s; selection-color: %(list_selected_text)s; }'
                'QTableWidget::item { padding: 0 %(table_cell_padding)dpx; }'
                'QHeaderView::section {'
                ' background: %(panel_bg)s; color: %(text)s; border: 1px solid %(border)s; padding: 3px; }'
                'QListWidget { background: %(list_bg)s; color: %(list_text)s; border: 1px solid %(border)s; }'
                'QSplitter::handle { background: %(border)s; }'
            ) % t

        def _apply_widget_themes(self):
            """하드코딩된 인라인 색을 쓰던 각 위젯을 현재 self.theme 값으로 다시 칠한다."""
            self._style_header_bar(self.top_bar)
            self._style_accent_button(self.run_button)
            self._style_accent_button_large(self.copy_button)
            self._style_success_button_large(self.pdf_button)
            self._style_neutral_button(self.machine_save_button)
            self._style_groupbox_border(self.machine_settings_panel)
            self._style_tool_filter_list(self.tool_filter)
            self._style_info_panel(self.metadata_summary)
            self._style_muted(self.count)
            self._style_muted(self.machine_settings_status)
            self._style_faint(self.tool_panel_hint)

        def _style_muted(self, widget):
            widget.setStyleSheet('color: %s;' % self.theme['muted_text'])

        def _style_faint(self, widget):
            widget.setStyleSheet('color: %s;' % self.theme['faint_text'])

        def _style_header_bar(self, widget):
            widget.setStyleSheet(
                'background: %s; color: %s;' % (self.theme['header_bg'], self.theme['header_text'])
            )

        def _style_accent_button(self, widget):
            widget.setStyleSheet(
                'background: %s; color: %s; padding: 5px 9px;'
                % (self.theme['accent'], self.theme['accent_text'])
            )

        def _style_accent_button_large(self, widget):
            # '표 복사' 버튼 전용: 폰트/버튼 크기를 1.3배로 키운다(v1.6.0).
            self._style_accent_button(widget)
            widget.setStyleSheet(widget.styleSheet() + ' padding: 7px 12px;')

        def _style_success_button(self, widget):
            widget.setStyleSheet(
                'background: %s; color: %s; padding: 5px 9px;'
                % (self.theme['success'], self.theme['success_text'])
            )

        def _style_success_button_large(self, widget):
            # 'PDF 출력' 버튼 전용: '표 복사'와 같은 행이라 크기를 맞춘다(v1.6.0).
            self._style_success_button(widget)
            widget.setStyleSheet(widget.styleSheet() + ' padding: 7px 12px;')

        def _style_neutral_button(self, widget):
            widget.setStyleSheet(
                'background: %s; color: %s; padding: 5px 9px;'
                % (self.theme['neutral_button'], self.theme['neutral_button_text'])
            )

        def _style_info_panel(self, widget):
            widget.setStyleSheet(
                'background: %s; color: %s; padding: 4px 6px;'
                % (self.theme['info_bg'], self.theme['info_text'])
            )

        def _style_groupbox_border(self, widget):
            widget.setStyleSheet(
                'QGroupBox { border: 1px solid %s; border-radius: 4px; margin-top: 0px; }'
                % self.theme['border']
            )

        def _style_tool_filter_list(self, widget):
            t = self.theme
            widget.setStyleSheet(
                'QListWidget { background: %s; border: 1px solid %s; }'
                'QListWidget::item { padding: 5px 6px; color: %s; }'
                'QListWidget::item:hover { background: %s; }'
                'QListWidget::item:selected { background: %s; color: %s; }'
                % (t['list_bg'], t['border'], t['list_text'], t['list_hover'],
                   t['list_selected_bg'], t['list_selected_text'])
            )

        def _build_ui(self):
            kfont = QFont('맑은 고딕', 10)
            mono = QFont('Consolas', 10)

            central = QWidget()
            root_layout = QVBoxLayout(central)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
            self.setCentralWidget(central)

            self.top_bar = QWidget()
            top_layout = QHBoxLayout(self.top_bar)
            top_layout.setContentsMargins(14, 7, 10, 7)
            title = QLabel('%s v%s' % (APP_NAME, APP_VERSION))
            title.setFont(QFont('맑은 고딕', 13, QFont.Bold))
            top_layout.addWidget(title)

            # About/모드 전환 버튼은 창 오른쪽 끝(addStretch 뒤)이 아니라 제목
            # 바로 옆(왼쪽)에 붙도록 배치하고, 폰트를 기존의 1.3배로 키운다
            # (v1.5.9 요청) — 9pt → 12pt. 패딩은 _style_mode_buttons에서
            # 함께 적용하며, v1.6.2부터 도움말/About과 같은 4px 8px이다.
            top_bar_button_font = QFont('맑은 고딕', 12, QFont.Bold)
            self.btn_about = QPushButton('About')
            self.btn_about.clicked.connect(self.show_about)
            self.btn_about.setFont(top_bar_button_font)
            top_layout.addWidget(self.btn_about)

            # v1.6.1: 단축키 및 유용한 기능을 설명하는 도움말 팝업.
            self.btn_help = QPushButton('도움말')
            self.btn_help.clicked.connect(self.show_help)
            self.btn_help.setFont(top_bar_button_font)
            top_layout.addWidget(self.btn_help)

            # 장비 패널의 ▶/▼ 접기 버튼과 시각적으로 구분되도록, 모드 전환
            # 버튼 2개를 About 버튼 끝에서 약 5cm 정도 띄워서 배치한다
            # (96DPI 가정, v1.6.0 요청).
            MODE_BUTTON_GAP_PX = round(5 * 96.0 / 2.54)
            top_layout.addSpacing(MODE_BUTTON_GAP_PX)

            self.btn_tool_mode = QPushButton('툴리스트 산출 모드')
            self.btn_tool_mode.setCheckable(True)
            self.btn_tool_mode.clicked.connect(lambda: self.set_mode('tool'))
            self.btn_viewer_mode = QPushButton('Viewer 모드')
            self.btn_viewer_mode.setCheckable(True)
            self.btn_viewer_mode.clicked.connect(lambda: self.set_mode('viewer'))
            for button in (self.btn_tool_mode, self.btn_viewer_mode):
                button.setFont(top_bar_button_font)
                top_layout.addWidget(button)
            # v1.6.2: 다크모드 버튼(원래 뷰어 안 감도/큐브 바 옆)을 이 상단
            # 바의 맨 끝(오른쪽)으로 옮긴다 — self.viewer가 만들어진 뒤에야
            # 그 버튼을 가져올 수 있으므로, 이 자리를 표시만 해 두고 실제
            # addStretch()/버튼 배치는 아래에서 self.viewer 생성 직후에 한다.
            root_layout.addWidget(self.top_bar)

            self.main_splitter = QSplitter(Qt.Horizontal)
            self.main_splitter.setChildrenCollapsible(False)
            root_layout.addWidget(self.main_splitter, 1)
            self.viewer = self._create_viewer()

            top_layout.addStretch()
            if hasattr(self.viewer, 'take_dark_mode_button'):
                self.btn_dark_mode = self.viewer.take_dark_mode_button(self.top_bar)
                top_layout.addWidget(self.btn_dark_mode)
                # 창 가장 오른쪽 가장자리에 버튼이 바로 붙지 않도록 한 칸
                # 띄운다(v1.6.2 요청).
                top_layout.addSpacing(TOP_BAR_EDGE_GAP_PX)

            self.program_panel = QWidget()
            self.program_panel.setMinimumWidth(PROGRAM_PANE_MIN_WIDTH)
            left_layout = QVBoxLayout(self.program_panel)
            left_layout.setContentsMargins(8, 8, 6, 8)
            left_layout.setSpacing(5)
            self.main_splitter.addWidget(self.program_panel)

            lbar = QHBoxLayout()
            label = QLabel('① 프로그램 입력')
            label.setFont(QFont('맑은 고딕', 10, QFont.Bold))
            lbar.addWidget(label)
            lbar.addStretch()
            left_layout.addLayout(lbar)

            # 지우기/예제/파일 열기/PG ADD/Tool List를 한 줄로 배치한다
            # (원래 2줄로 요청했던 것을 v1.5.9에서 1줄로 재배치).
            program_button_row = QHBoxLayout()
            program_button_row.setSpacing(6)
            self._add_button(program_button_row, '지우기', self.clear, kfont).setMinimumWidth(70)
            self._add_button(program_button_row, '예제', self.load_example, kfont).setMinimumWidth(70)
            self._add_button(program_button_row, '파일 열기', self.open_file, kfont).setMinimumWidth(88)
            self._add_button(program_button_row, 'PG ADD', self.open_add_program_files, kfont).setMinimumWidth(112)
            self.run_button = self._add_button(program_button_row, 'Tool List', self.run, kfont)
            self.run_button.setMinimumWidth(128)
            program_button_row.addStretch()
            left_layout.addLayout(program_button_row)

            # 장비 타입 및 스펙 설정 패널을 다음공구검색 행보다 위쪽에
            # 배치한다(v1.6.0 요청 — 두 행의 상하 순서 교체).
            self.machine_settings_panel = self._build_machine_settings_panel(kfont)
            left_layout.addWidget(self.machine_settings_panel)

            search_bar = QHBoxLayout()
            self._add_button(search_bar, '다음공구검색', self.find_next_tool_change, kfont)
            search_bar.addWidget(QLabel('문자 검색'))
            self.search_text = QLineEdit()
            self.search_text.setFont(kfont)
            self.search_text.returnPressed.connect(self.find_next_text)
            search_bar.addWidget(self.search_text, 1)
            self._add_button(search_bar, '검색', self.find_next_text, kfont)
            self.search_status = QLabel('')
            search_bar.addWidget(self.search_status)
            left_layout.addLayout(search_bar)

            self.input_splitter = QSplitter(Qt.Vertical)
            self.input_splitter.setChildrenCollapsible(False)
            left_layout.addWidget(self.input_splitter, 1)

            self.src = ProgramTextEdit()
            self.src.setFont(mono)
            self.src.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.src.setReadOnly(True)
            self.src.setAcceptDrops(True)
            self.src.filesDropped.connect(self.drop_file)
            self.src.textChanged.connect(self.source_changed)
            self.src.cursorPositionChanged.connect(self.source_cursor_changed)
            self.src.cursorPositionChanged.connect(self._highlight_current_line)
            self.src.focusGained.connect(lambda: self.set_machine_panel_expanded(False))
            self._highlight_current_line()
            self.input_splitter.addWidget(self.src)

            self.filter_panel = QWidget()
            filter_layout = QVBoxLayout(self.filter_panel)
            # v1.6.2: "텍스트 정지"~"PG 매칭/전체/해제" 구간의 레이아웃·폰트를
            # 15% 키운다(FILTER_SECTION_SCALE) — 요청받은 구간이라 이 아래
            # 위젯들만 scaled()/filter_kfont를 쓰고, 다른 패널은 그대로 둔다.
            filter_layout.setContentsMargins(0, scaled(5), 0, 0)
            filter_layout.setSpacing(scaled(4))

            filter_kfont = QFont('맑은 고딕')
            filter_kfont.setPointSizeF(kfont.pointSize() * FILTER_SECTION_SCALE)

            stop_bar = QHBoxLayout()
            stop_bar.setSpacing(scaled(6))
            self.stop_text_check = QCheckBox('텍스트 정지')
            self.stop_text_check.setFont(filter_kfont)
            self.stop_text_check.setToolTip(
                '오른쪽 입력창의 문자열이 포함된 줄에서 자동 재생을 멈춥니다.\n'
                '위쪽 "문자 검색"과는 별개의 값입니다.'
            )
            self.stop_text_input = QLineEdit()
            self.stop_text_input.setFont(filter_kfont)
            self.stop_text_input.setPlaceholderText('정지 문자')
            self.stop_text_input.setFixedWidth(scaled(120))
            self.stop_text_input.setToolTip(self.stop_text_check.toolTip())
            self.stop_m00_check = QCheckBox('정지')
            self.stop_m00_check.setFont(filter_kfont)
            self.stop_m00_check.setToolTip('M0 또는 M00에서 자동 재생을 멈춥니다.')
            self.stop_m01_check = QCheckBox('옵션정지')
            self.stop_m01_check.setFont(filter_kfont)
            self.stop_m01_check.setToolTip('M1 또는 M01에서 자동 재생을 멈춥니다.')
            self._load_playback_stop_options()
            self.stop_text_check.toggled.connect(self._on_stop_text_check_toggled)
            self.stop_text_check.toggled.connect(self._save_playback_stop_options)
            self.stop_text_input.textChanged.connect(self._save_playback_stop_options)
            self.stop_m00_check.toggled.connect(self._save_playback_stop_options)
            self.stop_m01_check.toggled.connect(self._save_playback_stop_options)
            self.stop_text_input.setEnabled(self.stop_text_check.isChecked())
            stop_bar.addWidget(self.stop_text_check)
            stop_bar.addWidget(self.stop_text_input)
            stop_bar.addWidget(self.stop_m00_check)
            stop_bar.addWidget(self.stop_m01_check)
            stop_bar.addStretch()
            filter_layout.addLayout(stop_bar)

            filter_bar = QHBoxLayout()
            filter_bar.setSpacing(scaled(6))
            filter_label = QLabel('공정별 경로 필터 선택')
            filter_label_font = QFont('맑은 고딕', weight=QFont.Bold)
            filter_label_font.setPointSizeF(9 * FILTER_SECTION_SCALE)
            filter_label.setFont(filter_label_font)
            filter_bar.addWidget(filter_label)
            filter_bar.addStretch()
            self.reset_program_button = self._add_button(
                filter_bar, 'Reset', lambda: self.jump_to_process_line(0), filter_kfont
            )
            self.reset_program_button.setToolTip(
                '프로그램 커서를 맨 상단(첫 줄)으로 이동합니다. (F5)'
            )
            self.pg_match_check = QCheckBox('PG 매칭')
            self.pg_match_check.setFont(filter_kfont)
            self.pg_match_check.setToolTip(
                '체크하면 그려진 경로를 지우고, 커서가 있는 공정만\n'
                '프로그램 방향키에 맞춰 실시간으로 그리고 지웁니다.'
            )
            self.pg_match_check.toggled.connect(self.toggle_pg_match_mode)
            filter_bar.addWidget(self.pg_match_check)
            self._add_button(filter_bar, '전체', lambda: self.viewer.select_all_tools(True), filter_kfont)
            self._add_button(filter_bar, '해제', lambda: self.viewer.select_all_tools(False), filter_kfont)
            filter_layout.addLayout(filter_bar)
            self.tool_filter = QListWidget()
            self.tool_filter.setSelectionMode(QAbstractItemView.MultiSelection)
            self.tool_filter.setFont(QFont('맑은 고딕', 10, QFont.Bold))
            self.tool_filter.setIconSize(QSize(14, 14))
            self._style_tool_filter_list(self.tool_filter)
            filter_layout.addWidget(self.tool_filter, 1)
            self.input_splitter.addWidget(self.filter_panel)
            self.input_splitter.setSizes(INPUT_SPLITTER_INITIAL_SIZES)
            self.input_splitter.splitterMoved.connect(self.save_splitter_settings)

            self.output_panel = QWidget()
            right_layout = QVBoxLayout(self.output_panel)
            right_layout.setContentsMargins(6, 8, 8, 8)
            right_layout.setSpacing(0)
            self.main_splitter.addWidget(self.output_panel)
            self.main_splitter.setStretchFactor(0, 0)
            self.main_splitter.setStretchFactor(1, 1)
            self.main_splitter.setSizes(MAIN_SPLITTER_INITIAL_SIZES)
            self.main_splitter.splitterMoved.connect(self.save_splitter_settings)

            self.stack = QStackedWidget()
            right_layout.addWidget(self.stack, 1)
            self._build_tool_panel()
            self.viewer.attach_tool_filter(self.tool_filter)
            if hasattr(self.viewer, 'process_activated'):
                self.viewer.process_activated.connect(self.jump_to_process_line)
            if hasattr(self.viewer, 'line_activated'):
                self.viewer.line_activated.connect(self.jump_to_process_line)
            if hasattr(self.viewer, 'dark_mode_toggled'):
                self.viewer.dark_mode_toggled.connect(self.toggle_dark_mode)
            playback_bar = getattr(self.viewer, 'playback_bar', None)
            if playback_bar is not None:
                playback_bar.play_clicked.connect(self.start_playback)
                playback_bar.pause_clicked.connect(self.pause_playback)
                playback_bar.rewind_clicked.connect(self.playback_rewind)
                playback_bar.prev_tool_clicked.connect(self.playback_prev_tool)
                playback_bar.next_tool_clicked.connect(self.playback_next_tool)
                playback_bar.speed_changed.connect(self.set_playback_speed)
                playback_bar.set_speed(self.play_speed)
            self.stack.addWidget(self.viewer)
            self.set_mode('tool')

        def _add_button(self, layout, text, slot, font=None):
            button = QPushButton(text)
            if font is not None:
                button.setFont(font)
            button.clicked.connect(slot)
            layout.addWidget(button)
            return button

        def _install_shortcuts(self):
            """v1.6.1: F5 리셋 / F6 이전 공구 / F7 재생·정지 / F8 다음 공구.
            기본 컨텍스트(Qt.WindowShortcut)를 그대로 쓴다 — 뷰어의 돋보기
            Escape처럼 ApplicationShortcut을 쓰면 모달(About/도움말) 창이
            떠 있어도 발동해, 창 뒤에서 프로그램 커서가 움직이는 부작용이
            생기기 때문이다. 어떤 위젯이 포커스를 갖고 있어도 발동한다."""
            shortcut_reset = QShortcut(QKeySequence('F5'), self)
            shortcut_reset.activated.connect(lambda: self.jump_to_process_line(0))
            shortcut_prev_tool = QShortcut(QKeySequence('F6'), self)
            shortcut_prev_tool.activated.connect(self.playback_prev_tool)
            shortcut_toggle_play = QShortcut(QKeySequence('F7'), self)
            shortcut_toggle_play.activated.connect(self.toggle_playback)
            shortcut_next_tool = QShortcut(QKeySequence('F8'), self)
            shortcut_next_tool.activated.connect(self.playback_next_tool)
            self._shortcuts = (
                shortcut_reset, shortcut_prev_tool, shortcut_toggle_play, shortcut_next_tool,
            )

        HELP_TEXT = (
            '■ 단축키\n'
            '  F5   프로그램 커서를 맨 위(첫 줄)로 이동 (Reset)\n'
            '  F6   이전 공구(선택된 공정 중 앞쪽)로 이동\n'
            '  F7   PG 매칭 자동 재생 시작/정지 토글\n'
            '  F8   다음 공구(선택된 공정 중 뒤쪽)로 이동\n'
            '  Esc  뷰어의 돋보기(우클릭으로 열림) 닫기\n'
            '\n'
            '■ 화면 모드\n'
            '  상단의 "툴리스트 산출 모드" / "Viewer 모드" 버튼으로 전환합니다.\n'
            '\n'
            '■ 프로그램 입력\n'
            '  파일 열기 / PG ADD(여러 파일을 이어붙여 추가) / 예제 / 지우기.\n'
            '  프로그램 입력창에 NC 파일을 드래그&드롭해도 열리거나 추가됩니다.\n'
            '  탐색기에서 연결된 확장자(.nc/.mpf/.tap) 파일을 더블클릭해도 바로 열립니다.\n'
            '\n'
            '■ 검색\n'
            '  다음공구검색: M6T 공구 교체 지점을 순서대로 찾습니다.\n'
            '  문자 검색: 입력한 문자열이 있는 다음 줄을 찾습니다(끝까지 가면 처음부터 재검색).\n'
            '\n'
            '■ 장비 타입 및 스펙 설정\n'
            '  ▶/▼를 눌러 펼치거나 접을 수 있고, 프로그램 입력창을 클릭하면 자동으로 접힙니다.\n'
            '\n'
            '■ 공구 리스트\n'
            '  행을 더블클릭하면 바로 수정할 수 있습니다.\n'
            '  삭제 / 수정 / ＋ 행 추가 / 이름 경우의 수(이름→TYPE 변환표 편집) / 머리글 포함 /\n'
            '  PDF 출력 / 표 복사(엑셀에 Ctrl+V로 붙여넣기).\n'
            '\n'
            '■ 3D 뷰어 조작\n'
            '  좌클릭 드래그: 카메라 회전 / 휠: 확대·축소\n'
            '  Ctrl+휠: 원근감(FOV) 조절 / Alt+휠: 감도 슬라이더 조절\n'
            '  우클릭: 돋보기(3배 확대) 열기·닫기 — 돋보기가 열려 있을 때만 좌클릭으로\n'
            '  가장 가까운 경로 라인의 프로그램 줄로 커서가 이동합니다.\n'
            '  방향 큐브: 면을 클릭하면 해당 뷰(ISO/XY/XZ/YZ)로 즉시 전환되고,\n'
            '  큐브를 감싼 고리를 드래그하면 스냅 없이 부드럽게 회전합니다.\n'
            '  큐브 크기 슬라이더를 조절하면 원점 화살표 크기도 함께 바뀝니다.\n'
            '\n'
            '■ PG 매칭 자동 재생 (Viewer 모드에서 "PG 매칭" 체크 시)\n'
            '  속도 슬라이더(1x~5000x)로 재생 속도를 조절합니다.\n'
            '  텍스트 정지 / 정지(M00) / 옵션정지(M01) 체크박스로 자동 정지 조건을 고릅니다.\n'
            '  재생바의 이전 툴 / 되감기 / 재생·정지 / 다음 툴 버튼으로도 조작할 수 있습니다.\n'
            '\n'
            '■ 공정별 경로 필터\n'
            '  목록에서 여러 공정을 선택해 3D 화면에 표시할 경로를 고를 수 있습니다.\n'
            '  항목을 클릭하면 해당 공정의 첫 줄로 프로그램 커서가 이동합니다.\n'
            '  전체 / 해제 버튼으로 한 번에 모두 선택하거나 해제할 수 있습니다.\n'
            '\n'
            '■ About\n'
            '  업데이트 경로 확인·설치, .nc/.mpf/.tap 기본 프로그램 등록/해제.\n'
        )

        def show_help(self):
            dialog = QDialog(self)
            dialog.setWindowTitle('도움말')
            dialog.resize(560, 640)
            layout = QVBoxLayout(dialog)
            title = QLabel('단축키 및 사용법')
            title.setFont(QFont('맑은 고딕', 12, QFont.Bold))
            layout.addWidget(title)
            viewer = QTextEdit()
            viewer.setReadOnly(True)
            viewer.setPlainText(self.HELP_TEXT)
            layout.addWidget(viewer, 1)
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.exec_()

        def show_about(self):
            dialog = QDialog(self)
            dialog.setWindowTitle('About')
            dialog.setFixedWidth(520)
            layout = QVBoxLayout(dialog)
            title = QLabel('%s v%s' % (APP_NAME, APP_VERSION))
            title.setFont(QFont('맑은 고딕', 12, QFont.Bold))
            layout.addWidget(title)
            viewer = QTextEdit()
            viewer.setReadOnly(True)
            # v1.6.0: 오픈소스 목록이 늘어나도 세로 스크롤바가 생기지 않도록,
            # 고정 높이 대신 실제 내용 길이에 맞춰 자동으로 늘어나게 한다.
            viewer.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            viewer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            viewer.setPlainText(
                '용도: %s\n'
                '버전: %s\n'
                '제작 년월일: %s\n'
                '제작자: %s\n\n'
                '사용 오픈소스:\n- %s' % (
                    APP_PURPOSE, APP_VERSION, APP_BUILD_DATE, APP_CREATOR,
                    '\n- '.join(OPEN_SOURCE_COMPONENTS),
                )
            )
            viewer.document().setTextWidth(480)
            viewer.setFixedHeight(int(viewer.document().size().height()) + 16)
            layout.addWidget(viewer)

            # --- 업데이트 경로 및 수동 업데이트 ---
            update_group = QGroupBox('업데이트')
            update_layout = QVBoxLayout(update_group)
            update_path_row = QHBoxLayout()
            update_path_row.addWidget(QLabel('업데이트 경로'))
            update_root_edit = QLineEdit(update_root_setting())
            update_path_row.addWidget(update_root_edit, 1)
            update_layout.addLayout(update_path_row)

            update_status_label = QLabel('')
            update_status_label.setWordWrap(True)
            update_status_label.setStyleSheet('color: #5a6577;')

            pending_update = {}

            def browse_update_root():
                path = QFileDialog.getExistingDirectory(
                    dialog, '업데이트 경로 선택', update_root_edit.text() or DEFAULT_UPDATE_ROOT,
                )
                if path:
                    update_root_edit.setText(path)

            def reset_update_root():
                update_root_edit.setText(DEFAULT_UPDATE_ROOT)

            def save_update_root():
                save_update_root_setting(update_root_edit.text().strip() or DEFAULT_UPDATE_ROOT)
                update_status_label.setText('업데이트 경로를 저장했습니다.')

            def check_for_update():
                root = update_root_edit.text().strip() or DEFAULT_UPDATE_ROOT
                result = find_latest_installer(root)
                if result is None:
                    pending_update.pop('path', None)
                    install_button.setEnabled(False)
                    update_status_label.setText('업데이트 파일을 찾을 수 없습니다.\n%s' % root)
                    return
                path, version = result
                version_text = '.'.join(str(part) for part in version)
                if version > current_version_tuple():
                    pending_update['path'] = path
                    install_button.setEnabled(True)
                    update_status_label.setText('새 버전 발견: v%s (현재 v%s)' % (version_text, APP_VERSION))
                else:
                    pending_update.pop('path', None)
                    install_button.setEnabled(False)
                    update_status_label.setText('현재 버전이 최신입니다. (v%s)' % APP_VERSION)

            def install_update():
                path = pending_update.get('path')
                if not path:
                    return
                if QMessageBox.question(
                    dialog, '업데이트 설치',
                    '설치 파일을 실행하면 프로그램이 종료됩니다. 계속할까요?\n%s' % path,
                ) != QMessageBox.Yes:
                    return
                try:
                    temp_path = copy_installer_to_temp(path)
                except OSError as error:
                    QMessageBox.critical(dialog, '업데이트 실패', '설치 파일을 복사하지 못했습니다.\n%s' % error)
                    return
                open_error = open_file_with_default_app(temp_path)
                if open_error:
                    QMessageBox.critical(dialog, '업데이트 실패', '설치 파일을 실행하지 못했습니다.\n%s' % open_error)
                    return
                QApplication.instance().quit()

            update_button_row = QHBoxLayout()
            self._add_button(update_button_row, '찾아보기', browse_update_root)
            self._add_button(update_button_row, '기본값 복원', reset_update_root)
            self._add_button(update_button_row, '경로 저장', save_update_root)
            self._add_button(update_button_row, '업데이트 확인', check_for_update)
            install_button = self._add_button(update_button_row, '지금 설치', install_update)
            install_button.setEnabled(False)
            update_layout.addLayout(update_button_row)
            update_layout.addWidget(update_status_label)
            layout.addWidget(update_group)

            # --- 확장자 기본 프로그램 등록 ---
            assoc_group = QGroupBox('확장자 기본 프로그램 등록 (%s)' % ', '.join(FILE_ASSOCIATION_EXTENSIONS))
            assoc_layout = QVBoxLayout(assoc_group)
            assoc_status_label = QLabel('')
            assoc_status_label.setWordWrap(True)
            assoc_status_label.setStyleSheet('color: #5a6577;')

            def refresh_assoc_status():
                connected = file_associations_status()
                assoc_status_label.setText('연결됨' if connected else '연결 안 됨')

            def do_register():
                try:
                    register_file_associations()
                except OSError as error:
                    QMessageBox.critical(dialog, '등록 실패', str(error))
                refresh_assoc_status()

            def do_unregister():
                try:
                    unregister_file_associations()
                except OSError as error:
                    QMessageBox.critical(dialog, '해제 실패', str(error))
                refresh_assoc_status()

            assoc_button_row = QHBoxLayout()
            self._add_button(assoc_button_row, '등록', do_register)
            self._add_button(assoc_button_row, '해제', do_unregister)
            assoc_layout.addLayout(assoc_button_row)
            assoc_layout.addWidget(assoc_status_label)
            layout.addWidget(assoc_group)
            refresh_assoc_status()

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.exec_()

        MACHINE_PANEL_TITLE = '장비 타입 및 스펙 설정'

        def _build_machine_settings_panel(self, font):
            panel = QGroupBox()
            self._style_groupbox_border(panel)
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(5)

            # 접이식 헤더: 클릭하면 아래 본문(장비 타입/스펙 폼)을 펼치거나 접는다.
            # 프로그램 입력창을 더 넓게 쓰기 위해 기본은 접힘 상태다. 어디 있는지
            # 눈에 잘 띄도록 투명 텍스트가 아닌 채워진 색상 블럭으로 표시한다.
            self.machine_panel_toggle = QPushButton()
            self.machine_panel_toggle.setCheckable(True)
            self.machine_panel_toggle.setFlat(True)
            self.machine_panel_toggle.setCursor(Qt.PointingHandCursor)
            self.machine_panel_toggle.setFont(QFont('맑은 고딕', 9, QFont.Bold))
            self.machine_panel_toggle.toggled.connect(self._on_machine_panel_toggled)
            layout.addWidget(self.machine_panel_toggle)

            self.machine_settings_body = QWidget()
            body_layout = QVBoxLayout(self.machine_settings_body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(5)
            layout.addWidget(self.machine_settings_body)

            self.machine_type_combo = QComboBox()
            self.machine_type_combo.setFont(font)
            self.machine_type_combo.addItems(self.viewer.machine_types())
            self.machine_type_combo.setCurrentText(self.viewer.current_machine_type)
            self.machine_type_combo.currentIndexChanged.connect(self._viewer_machine_type_changed)
            body_layout.addWidget(self.machine_type_combo)

            self.machine_spec_form_widget = QWidget()
            self.machine_spec_form = QFormLayout(self.machine_spec_form_widget)
            self.machine_spec_form.setContentsMargins(0, 0, 0, 0)
            self.machine_spec_form.setSpacing(4)
            body_layout.addWidget(self.machine_spec_form_widget)

            self.machine_spec_inputs = {}
            self._rebuild_machine_spec_form()

            self.machine_save_button = QPushButton('현재 장비 스펙 기록/저장')
            self.machine_save_button.setFont(font)
            self._style_neutral_button(self.machine_save_button)
            self.machine_save_button.clicked.connect(self.save_visible_machine_settings)
            body_layout.addWidget(self.machine_save_button)

            # 접힘 여부와 무관하게 항상 보이도록 본문(body_layout)이 아닌 패널
            # 바깥 레이아웃에 둔다 — 저장 후 자동으로 접혀도 상태 문구는 남는다.
            self.machine_settings_status = QLabel('')
            self._style_muted(self.machine_settings_status)
            layout.addWidget(self.machine_settings_status)

            self.set_machine_panel_expanded(self._load_machine_panel_expanded())
            return panel

        def _load_machine_panel_expanded(self):
            raw = self.layout_settings.value('machine_panel_expanded', False)
            if isinstance(raw, str):
                return raw.strip().lower() in ('1', 'true', 'yes')
            return bool(raw)

        def _on_machine_panel_toggled(self, expanded):
            self.set_machine_panel_expanded(expanded)

        def set_machine_panel_expanded(self, expanded):
            expanded = bool(expanded)
            arrow = '▼' if expanded else '▶'
            self.machine_panel_toggle.setText('%s %s' % (arrow, self.MACHINE_PANEL_TITLE))
            with QSignalBlocker(self.machine_panel_toggle):
                self.machine_panel_toggle.setChecked(expanded)
            self.machine_settings_body.setVisible(expanded)
            self.layout_settings.setValue('machine_panel_expanded', expanded)
            # 채워진 색상 블럭 헤더 — 접힘/펼침 어느 쪽이든 항상 눈에 띄게 한다.
            t = self.theme
            self.machine_panel_toggle.setStyleSheet(
                'QPushButton { text-align: left; border: none; border-radius: 4px;'
                ' background: %s; color: %s; padding: 6px 10px; }'
                'QPushButton:hover { background: %s; }'
                % (t['accent'], t['accent_text'], t['accent_hover'])
            )

        def _rebuild_machine_spec_form(self):
            while self.machine_spec_form.rowCount():
                self.machine_spec_form.removeRow(0)
            self.machine_spec_inputs = {}
            machine_type = self.machine_type_combo.currentText()
            for key, value in self.viewer.machine_spec(machine_type).items():
                edit = QLineEdit(str(value))
                self.machine_spec_inputs[key] = edit
                self.machine_spec_form.addRow('%s:' % key, edit)

        def _viewer_machine_type_changed(self):
            machine_type = self.machine_type_combo.currentText()
            self._rebuild_machine_spec_form()
            self.viewer.set_machine_type(machine_type)
            self.machine_settings_status.setText('')
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def save_visible_machine_settings(self):
            machine_type = self.machine_type_combo.currentText()
            specs = {key: edit.text() for key, edit in self.machine_spec_inputs.items()}
            self.viewer.update_machine_spec(machine_type, specs)
            self.machine_settings_status.setText('장비 스펙 설정이 저장되었습니다.')
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()
            # 저장이 끝나면 프로그램 입력창을 더 넓게 쓰도록 자동으로 접는다.
            self.set_machine_panel_expanded(False)

        def sync_visible_machine_settings(self):
            if not hasattr(self, 'machine_type_combo'):
                return
            with QSignalBlocker(self.machine_type_combo):
                self.machine_type_combo.clear()
                self.machine_type_combo.addItems(self.viewer.machine_types())
                self.machine_type_combo.setCurrentText(self.viewer.current_machine_type)
            self._rebuild_machine_spec_form()

        @staticmethod
        def _normalized_splitter_sizes(value, fallback, count):
            values = value
            if isinstance(values, str):
                values = [part for part in re.split(r'[,;\s]+', values) if part]
            if not isinstance(values, (list, tuple)) or len(values) != count:
                return list(fallback)
            try:
                sizes = [int(v) for v in values]
            except (TypeError, ValueError):
                return list(fallback)
            if any(size <= 0 for size in sizes) or sum(sizes) <= 0:
                return list(fallback)
            return sizes

        def _restore_splitter_sizes(self, splitter, key, fallback):
            sizes = self._normalized_splitter_sizes(
                self.layout_settings.value(key, fallback), fallback, len(fallback)
            )
            splitter.setSizes(sizes)

        def _restore_input_splitter_sizes(self):
            self._restore_splitter_sizes(
                self.input_splitter, 'input_splitter_sizes', INPUT_SPLITTER_INITIAL_SIZES
            )

        def restore_layout_settings(self):
            restored_geometry = False
            geometry = self.layout_settings.value('window_geometry', None)
            if geometry:
                try:
                    restored_geometry = bool(self.restoreGeometry(geometry))
                except TypeError:
                    restored_geometry = False
            state = self.layout_settings.value('window_state', None)
            if state:
                try:
                    self.restoreState(state)
                except TypeError:
                    pass
            self._restore_splitter_sizes(
                self.main_splitter, 'main_splitter_sizes', MAIN_SPLITTER_INITIAL_SIZES
            )
            self._restore_input_splitter_sizes()
            return restored_geometry

        def _current_valid_splitter_sizes(self, splitter):
            sizes = [int(size) for size in splitter.sizes()]
            if any(size <= 0 for size in sizes):
                return None
            return sizes

        def save_splitter_settings(self, *_args):
            main_sizes = self._current_valid_splitter_sizes(self.main_splitter)
            if main_sizes:
                self.layout_settings.setValue('main_splitter_sizes', main_sizes)
            input_sizes = self._current_valid_splitter_sizes(self.input_splitter)
            if input_sizes:
                self.layout_settings.setValue('input_splitter_sizes', input_sizes)
            self.layout_settings.sync()

        def save_layout_settings(self):
            self.layout_settings.setValue('window_geometry', self.saveGeometry())
            self.layout_settings.setValue('window_state', self.saveState())
            self.save_splitter_settings()

        def closeEvent(self, event):
            self.save_layout_settings()
            super().closeEvent(event)

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
            self._style_muted(self.count)
            rbar.addWidget(self.count)
            # 조작 버튼들을 패널 오른쪽 끝이 아니라 왼쪽(라벨 바로 옆)에 모아
            # 배치한다(v1.5.9 요청) — addStretch()를 버튼들 뒤로 옮긴다.
            # '표 복사'까지 이 행의 버튼들은 폰트/크기를 1.3배로 키운다(v1.6.0).
            row_button_font = QFont('맑은 고딕', 13)
            row_button_style = 'padding: 5px 10px;'
            btn_delete = self._add_button(rbar, '삭제', self.delete_selected, row_button_font)
            btn_delete.setStyleSheet(row_button_style)
            btn_edit = self._add_button(rbar, '수정', self.edit_selected, row_button_font)
            btn_edit.setStyleSheet(row_button_style)
            btn_add_row = self._add_button(rbar, '＋ 행 추가', self.add_row, row_button_font)
            btn_add_row.setStyleSheet(row_button_style)
            btn_type_list = self._add_button(rbar, '이름 경우의 수', self.show_type_list, row_button_font)
            btn_type_list.setStyleSheet(row_button_style)
            self.with_header = QCheckBox('머리글 포함')
            self.with_header.setFont(row_button_font)
            rbar.addWidget(self.with_header)
            self.pdf_button = self._add_button(rbar, 'PDF 출력', self.export_pdf, row_button_font)
            self._style_success_button_large(self.pdf_button)
            self.copy_button = self._add_button(rbar, '표 복사', self.copy_table, row_button_font)
            self._style_accent_button_large(self.copy_button)
            rbar.addStretch()
            layout.addLayout(rbar)

            self.metadata_summary = QLabel('출력 정보: -')
            self._style_info_panel(self.metadata_summary)
            layout.addWidget(self.metadata_summary)

            self.table = QTableWidget(0, len(COLUMNS))
            self.table.setHorizontalHeaderLabels([label for _key, label in COLUMNS])
            # v1.5.9: 표기 폰트를 기존(미지정 기본 폰트, ~9pt)의 1.6배로 키운다
            # — 행 높이는 Qt가 이 폰트 크기에 맞춰 함께 자동으로 커진다.
            # v1.6.2: 요청대로 그 폰트/셀 폭을 다시 15% 줄인다(COPY_TABLE_SCALE).
            table_font = QFont('맑은 고딕')
            table_font.setPointSizeF(TABLE_FONT_PT)
            table_header_font = QFont('맑은 고딕', weight=QFont.Bold)
            table_header_font.setPointSizeF(TABLE_FONT_PT)
            self.table.setFont(table_font)
            self.table.horizontalHeader().setFont(table_header_font)
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

            self.tool_panel_hint = QLabel('행을 더블클릭하거나 수정/추가 버튼으로 직접 편집할 수 있습니다. (N번호 ~ M6 사이 괄호 주석을 읽음)')
            self._style_faint(self.tool_panel_hint)
            layout.addWidget(self.tool_panel_hint)
            self.stack.addWidget(panel)

        def set_window_icon(self):
            icon_path = resource_path('assets/nc_tool_list.ico')
            if Path(icon_path).exists():
                self.setWindowIcon(QIcon(icon_path))

        def set_mode(self, mode):
            if mode != 'viewer':
                self.pause_playback()
            self.current_mode = mode
            is_viewer = mode == 'viewer'
            self.stack.setCurrentIndex(1 if is_viewer else 0)
            self.filter_panel.setVisible(is_viewer)
            self.machine_settings_panel.setVisible(is_viewer)
            if is_viewer:
                self._restore_input_splitter_sizes()
            self.btn_tool_mode.setChecked(not is_viewer)
            self.btn_viewer_mode.setChecked(is_viewer)
            self._style_mode_buttons()
            if is_viewer:
                self.sync_viewer_from_source()
                self.log_gl_info()

        def _style_mode_buttons(self):
            t = self.theme
            # v1.6.2: "툴리스트 산출 모드"/"Viewer 모드" 버튼을 "도움말" 버튼과
            # 같은 크기로 맞춘다 — 패딩을 도움말/About이 쓰는 전역 기본값
            # (4px 8px)과 같게 둔다(이전엔 7px 12px로 더 컸다).
            active = 'background: %s; color: %s; padding: 4px 8px;' % (
                t['mode_active_bg'], t['mode_active_text']
            )
            inactive = 'background: %s; color: %s; padding: 4px 8px;' % (
                t['mode_inactive_bg'], t['mode_inactive_text']
            )
            self.btn_tool_mode.setStyleSheet(active if self.current_mode == 'tool' else inactive)
            self.btn_viewer_mode.setStyleSheet(active if self.current_mode == 'viewer' else inactive)

        def source_changed(self):
            if self.current_mode == 'viewer':
                self.viewer_update_timer.start(450)

        def source_cursor_changed(self):
            if self.current_mode == 'viewer':
                self.viewer.set_cursor_line(self.src.textCursor().blockNumber())

        def toggle_pg_match_mode(self, enabled):
            """PG 매칭 모드를 켜고 끈다.

            켤 때는 프로그램 입력창에 포커스를 줘서 방향키가 바로 먹게 하고, 커서가
            필터에서 선택되지 않은 공정 위에 있으면(= 아무것도 그려지지 않아 고장으로
            오인할 상황) 선택된 공정 중 첫 번째의 시작 줄로 커서를 옮겨준다.
            """
            self.viewer.set_pg_match_mode(enabled)
            if not enabled:
                self.pause_playback()
                return
            self.src.setFocus()
            selected = getattr(self.viewer, 'selected_tools', None)
            first_line_map = getattr(self.viewer, 'process_first_line', None)
            line_to_tool = getattr(self.viewer, 'line_to_tool_map', None)
            if not callable(selected) or not first_line_map or line_to_tool is None:
                return
            selected_processes = selected()
            if not selected_processes:
                return
            current_process = line_to_tool.get(self.src.textCursor().blockNumber())
            if current_process in selected_processes:
                return
            for process_key in first_line_map:
                if process_key in selected_processes:
                    self.jump_to_process_line(first_line_map[process_key])
                    return

        def jump_to_process_line(self, line_index):
            """공정별 필터 항목을 클릭하면 프로그램 입력창의 해당 위치로 이동한다.

            텍스트를 선택(KeepAnchor)하지 않고 커서만 놓는다 — 행 강조는
            _highlight_current_line의 전체 폭 블럭이 담당하므로 파란 선택 영역과
            겹치지 않고, 방향키 첫 입력이 선택 해제로 소비되는 것도 막는다.
            """
            block = self.src.document().findBlockByNumber(max(0, int(line_index)))
            if not block.isValid():
                return
            self.src.setTextCursor(QTextCursor(block))
            self.src.ensureCursorVisible()
            self.src.setFocus()

        def _load_playback_speed(self):
            raw = self.layout_settings.value('playback_speed', 1)
            try:
                value = int(float(raw))
            except (TypeError, ValueError):
                value = 1
            return max(1, min(MAX_PLAYBACK_SPEED, value))

        def set_playback_speed(self, value):
            self.play_speed = max(1, min(MAX_PLAYBACK_SPEED, int(value)))
            self.layout_settings.setValue('playback_speed', self.play_speed)

        @staticmethod
        def _as_bool_setting(raw, default):
            if raw is None:
                return default
            if isinstance(raw, str):
                return raw.strip().lower() in ('1', 'true', 'yes')
            return bool(raw)

        def _load_playback_stop_options(self):
            """정지 옵션 체크 상태와 텍스트 정지 입력값을 layout_settings에서 복원한다.
            기본값: 정지·옵션정지 켜짐, 텍스트 정지 꺼짐, 정지 문자 비어 있음."""
            self.stop_text_check.setChecked(
                self._as_bool_setting(self.layout_settings.value('stop_at_text', None), False)
            )
            self.stop_text_input.setText(str(self.layout_settings.value('stop_text_value', '') or ''))
            self.stop_m00_check.setChecked(
                self._as_bool_setting(self.layout_settings.value('stop_at_m00', None), True)
            )
            self.stop_m01_check.setChecked(
                self._as_bool_setting(self.layout_settings.value('stop_at_m01', None), True)
            )

        def _on_stop_text_check_toggled(self, checked):
            self.stop_text_input.setEnabled(checked)

        def _save_playback_stop_options(self, *_args):
            self.layout_settings.setValue('stop_at_text', self.stop_text_check.isChecked())
            self.layout_settings.setValue('stop_text_value', self.stop_text_input.text())
            self.layout_settings.setValue('stop_at_m00', self.stop_m00_check.isChecked())
            self.layout_settings.setValue('stop_at_m01', self.stop_m01_check.isChecked())

        def start_playback(self):
            """PG 매칭 자동 재생을 시작한다. PG 매칭이 꺼져 있거나 뷰어 모드가 아니면 무시한다."""
            if self.current_mode != 'viewer' or not getattr(self.viewer, 'pg_match_mode', False):
                return
            self._play_carry = 0.0
            self.play_timer.start()
            bar = getattr(self.viewer, 'playback_bar', None)
            if bar is not None:
                bar.set_playing(True)

        def pause_playback(self):
            self.play_timer.stop()
            bar = getattr(self.viewer, 'playback_bar', None)
            if bar is not None:
                bar.set_playing(False)

        def toggle_playback(self):
            """F7 단축키 등에서 쓰는 재생/정지 토글. play_timer의 동작 여부가
            재생 상태의 단일 진실 소스이므로 이를 그대로 확인한다."""
            if self.play_timer.isActive():
                self.pause_playback()
            else:
                self.start_playback()

        def _playback_tick(self):
            """50ms마다 호출된다. 배속에 맞는 줄 수만큼 커서를 전진시키고, 그 사이에
            체크된 정지 옵션(텍스트 정지/정지/옵션정지)이나 문서 끝을 만나면 그
            줄에서 멈춘다."""
            if self.current_mode != 'viewer' or not getattr(self.viewer, 'pg_match_mode', False):
                self.pause_playback()
                return
            document = self.src.document()
            total_lines = document.blockCount()
            current_line = self.src.textCursor().blockNumber()
            self._play_carry += self.play_speed * (self.play_timer.interval() / 1000.0)
            steps = int(self._play_carry)
            if steps <= 0:
                return
            self._play_carry -= steps
            target_line = min(current_line + steps, total_lines - 1)
            needle = self.stop_text_input.text()
            stop_text = self.stop_text_check.isChecked()
            stop_m00 = self.stop_m00_check.isChecked()
            stop_m01 = self.stop_m01_check.isChecked()
            stop_line = None
            for line_index in range(current_line + 1, target_line + 1):
                block = document.findBlockByNumber(line_index)
                if block.isValid() and line_stops_playback(
                    block.text(), needle, stop_text, stop_m00, stop_m01
                ):
                    stop_line = line_index
                    break
            destination = stop_line if stop_line is not None else target_line
            if destination != current_line:
                self.jump_to_process_line(destination)
            if stop_line is not None or destination >= total_lines - 1:
                self.pause_playback()

        def playback_rewind(self):
            """현재 커서가 속한 공정의 시작 줄로 되감고 정지한다."""
            self.pause_playback()
            first_line_map = getattr(self.viewer, 'process_first_line', None)
            line_to_tool = getattr(self.viewer, 'line_to_tool_map', None)
            start_line = 0
            if first_line_map and line_to_tool is not None:
                current_process = line_to_tool.get(self.src.textCursor().blockNumber())
                start_line = first_line_map.get(current_process, 0)
            self.jump_to_process_line(start_line)

        def playback_prev_tool(self):
            self._jump_relative_tool(-1)

        def playback_next_tool(self):
            self._jump_relative_tool(1)

        def _jump_relative_tool(self, direction):
            """필터에서 선택된 공정들의 시작 줄 중, 현재 커서 기준 앞/뒤로 가장 가까운
            곳으로 점프한다. 재생 중이었으면 재생 상태를 유지한다."""
            # v1.6.1: F6/F8 단축키가 뷰어/PG 매칭 모드 밖에서도 커서를
            # 움직이지 않도록, start_playback()과 같은 조건으로 막는다.
            if self.current_mode != 'viewer' or not getattr(self.viewer, 'pg_match_mode', False):
                return
            first_line_map = getattr(self.viewer, 'process_first_line', None)
            selected = getattr(self.viewer, 'selected_tools', None)
            if not first_line_map or not callable(selected):
                return
            selected_processes = selected()
            ordered_lines = sorted(
                line for key, line in first_line_map.items() if key in selected_processes
            )
            if not ordered_lines:
                return
            current_line = self.src.textCursor().blockNumber()
            if direction > 0:
                later = [line for line in ordered_lines if line > current_line]
                target = later[0] if later else ordered_lines[-1]
            else:
                earlier = [line for line in ordered_lines if line < current_line]
                target = earlier[-1] if earlier else ordered_lines[0]
            self.jump_to_process_line(target)

        def _highlight_current_line(self):
            """읽기전용 프로그램 편집기에서 커서가 있는 행을 가로 전체 폭 블럭으로 칠한다."""
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(self.theme['current_line']))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.src.textCursor()
            selection.cursor.clearSelection()
            self.src.setExtraSelections([selection])

        def parsed_program_data(self, source_text=None):
            source_text = self.src.toPlainText() if source_text is None else source_text
            if source_text != self._last_parsed_source:
                self._last_parsed_source = source_text
                self._last_parsed_metadata = parse_program_metadata(source_text)
                self._last_parsed_rows = parse_program(source_text, self.name_types)
            return self._last_parsed_metadata, list(self._last_parsed_rows)

        def invalidate_parse_cache(self):
            self._last_parsed_source = None
            self._last_parsed_rows = []
            self._last_parsed_metadata = {key: '' for key in METADATA_ALIASES}

        def sync_viewer_from_source(self):
            source_text = self.src.toPlainText()
            if not source_text.strip():
                self.viewer.clear()
                return
            _metadata, rows = self.parsed_program_data(source_text)
            self.viewer.set_source_text(source_text, self.tool_name_map(rows or self.current_rows()))
            self.viewer.set_cursor_line(self.src.textCursor().blockNumber())

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
            self._search_status_error = error
            color = self.theme['error'] if error else self.theme['muted_text']
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
            self.metadata, rows = self.parsed_program_data(source_text)
            self.table.setUpdatesEnabled(False)
            try:
                self.table.setRowCount(len(rows))
                for row_index, row_data in enumerate(rows):
                    self.set_table_row(row_index, row_data)
            finally:
                self.table.setUpdatesEnabled(True)
            self.update_count()
            self.update_metadata_summary()
            if self.current_mode == 'viewer':
                self.sync_viewer_from_source()

        def open_file(self):
            path, _filter = QFileDialog.getOpenFileName(
                self,
                'NC 프로그램 파일 선택',
                str(Path(self.current_file_path).parent) if self.current_file_path else os.getcwd(),
                'NC/텍스트 파일 (*.nc *.mpf *.txt *.tap *.min *.prg);;모든 파일 (*.*)',
            )
            if path:
                self.load_file(path)

        def open_add_program_files(self):
            paths, _filter = QFileDialog.getOpenFileNames(
                self,
                '추가할 NC 프로그램 파일 선택',
                str(Path(self.current_file_path).parent) if self.current_file_path else os.getcwd(),
                'NC/텍스트 파일 (*.nc *.mpf *.txt *.tap *.min *.prg);;모든 파일 (*.*)',
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
            self._highlight_current_line()
            self.invalidate_parse_cache()
            self.run()

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
            append_text = '\n\n'.join(text.strip() for text in additions if text.strip())
            if not append_text:
                return
            with QSignalBlocker(self.src):
                if self.src.document().isEmpty():
                    self.src.setPlainText(append_text)
                else:
                    cursor = self.src.textCursor()
                    cursor.movePosition(QTextCursor.End)
                    cursor.insertText('\n\n' + append_text)
            self._highlight_current_line()
            self.invalidate_parse_cache()
            self.run()

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
            self.invalidate_parse_cache()
            self.run()

        def clear(self):
            self.src.clear()
            self.table.setRowCount(0)
            self.update_count()
            self.metadata = {key: '' for key in METADATA_ALIASES}
            self.invalidate_parse_cache()
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
    def log_unhandled_exception(exc_type, exc_value, exc_tb):
        write_startup_log('Unhandled exception: %s\n%s' % (
            exc_value, ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        ))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = log_unhandled_exception
    write_startup_log('Starting %s v%s frozen=%s argv=%s' % (
        APP_NAME, APP_VERSION, bool(getattr(sys, 'frozen', False)), sys.argv
    ))
    missing = missing_viewer_dependencies()
    if missing:
        raise SystemExit('GUI 실행에 필요한 Python 패키지가 없습니다: ' + ', '.join(missing))
    try:
        app = QApplication(sys.argv)
        window = App()
        initial_file = startup_file_argument(sys.argv)
        if initial_file:
            QTimer.singleShot(0, lambda path=initial_file: window.load_file(path))
        window.show()
        sys.exit(app.exec_())
    except Exception as error:
        write_startup_log('Fatal startup failure: %s\n%s' % (error, traceback.format_exc()))
        raise

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

