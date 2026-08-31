# -*- coding: utf-8 -*-
"""
NC 공구 리스트 생성기 (tkinter GUI)
- 왼쪽: NC 프로그램(G코드) 입력
- 오른쪽: N번호~M6 사이 괄호 주석을 읽어 만든 공구 리스트 (복사/보기용)
"""
import json
import os
import re
import sys
import tkinter as tk
from datetime import date
from html import escape
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle


APP_VERSION = '1.3.0'
APP_NAME = 'NC 공구 리스트 생성기'

# ---------- 파싱 로직 ----------
TOOL_RE = re.compile(r'\(\s*T(\d+)\s*//\s*(.*?)\s*\[SO\s*([\d.]+)\]\s*//\s*T\d+\s*([^)]*?)\s*\)', re.I)
N_RE    = re.compile(r'^\s*N(\d+)\s*\(\s*#\d+\s*:\s*Tool\s*Change', re.I)
M6_RE   = re.compile(r'^\s*M0?6\s+T(\d+)', re.I)
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


def resource_path(relative_path):
    """Resolve bundled files both from source and PyInstaller one-file builds."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return str(base / relative_path)

# ---------- GUI ----------
class App:
    def __init__(self, root):
        self.root = root
        self.name_types = load_name_types()
        self.metadata = {key: '' for key in METADATA_ALIASES}
        root.title('🛠️ %s v%s' % (APP_NAME, APP_VERSION))
        self.set_window_icon()
        root.geometry('1180x640')
        root.after_idle(self.maximize_window)

        kfont = ('맑은 고딕', 10)
        mono = ('Consolas', 10)

        # 상단 바
        top = tk.Frame(root, bg='#1f3a5f')
        top.pack(fill='x')
        tk.Label(top, text='🛠️ %s v%s' % (APP_NAME, APP_VERSION), bg='#1f3a5f', fg='white',
                 font=('맑은 고딕', 13, 'bold')).pack(side='left', padx=14, pady=8)
        tk.Label(top, text='NC 프로그램을 넣고 [공구 리스트 생성]을 누르세요',
                 bg='#1f3a5f', fg='#c8d4e2', font=('맑은 고딕', 9)).pack(side='left')

        paned = ttk.PanedWindow(root, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=8, pady=8)

        # ----- 왼쪽: 입력 -----
        left = tk.Frame(paned)
        paned.add(left, weight=1)
        lbar = tk.Frame(left)
        lbar.pack(fill='x', pady=(0, 4))
        tk.Label(lbar, text='① 프로그램 입력', font=('맑은 고딕', 10, 'bold')).pack(side='left')
        tk.Button(lbar, text='▶ 공구 리스트 생성', command=self.run,
                  bg='#2f6fb0', fg='white', font=kfont, relief='flat',
                  padx=8).pack(side='right')
        tk.Button(lbar, text='파일 열기', command=self.open_file, font=kfont).pack(side='right', padx=4)
        tk.Button(lbar, text='예제', command=self.load_example, font=kfont).pack(side='right')
        tk.Button(lbar, text='지우기', command=self.clear, font=kfont).pack(side='right', padx=4)

        txt_frame = tk.Frame(left)
        txt_frame.pack(fill='both', expand=True)
        self.src = tk.Text(txt_frame, wrap='none', font=mono, undo=True)
        ys = tk.Scrollbar(txt_frame, orient='vertical', command=self.src.yview)
        xs = tk.Scrollbar(txt_frame, orient='horizontal', command=self.src.xview)
        self.src.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side='right', fill='y')
        xs.pack(side='bottom', fill='x')
        self.src.pack(side='left', fill='both', expand=True)
        self.src.drop_target_register(DND_FILES)
        self.src.dnd_bind('<<Drop>>', self.drop_file)

        # ----- 오른쪽: 결과 -----
        right = tk.Frame(paned)
        paned.add(right, weight=2)
        rbar = tk.Frame(right)
        rbar.pack(fill='x', pady=(0, 4))
        tk.Label(rbar, text='② 공구 리스트 (복사용)', font=('맑은 고딕', 10, 'bold')).pack(side='left')
        self.count = tk.Label(rbar, text='공구 0개', font=('맑은 고딕', 9), fg='#5a6577')
        self.count.pack(side='left', padx=10)
        tk.Button(rbar, text='📋 표 복사 (엑셀 붙여넣기)', command=self.copy_table,
                  bg='#2f6fb0', fg='white', font=kfont, relief='flat',
                  padx=8).pack(side='right')
        tk.Button(rbar, text='PDF 출력', command=self.export_pdf,
                  bg='#4c7f31', fg='white', font=kfont, relief='flat',
                  padx=8).pack(side='right', padx=4)
        self.with_header = tk.BooleanVar(value=False)
        tk.Checkbutton(rbar, text='머리글 포함', variable=self.with_header,
                       font=kfont).pack(side='right', padx=6)
        tk.Button(rbar, text='이름 경우의 수', command=self.show_type_list,
                  font=kfont).pack(side='right', padx=4)
        tk.Button(rbar, text='＋ 행 추가', command=self.add_row, font=kfont).pack(side='right', padx=2)
        tk.Button(rbar, text='수정', command=self.edit_selected, font=kfont).pack(side='right', padx=2)
        tk.Button(rbar, text='삭제', command=self.delete_selected, font=kfont).pack(side='right', padx=2)

        self.metadata_summary = tk.Label(
            right, text='출력 정보: -', anchor='w', fg='#40536b',
            bg='#eaf1f8', font=('맑은 고딕', 8), padx=6, pady=3,
        )
        self.metadata_summary.pack(fill='x', pady=(0, 4))

        tv_frame = tk.Frame(right)
        tv_frame.pack(fill='both', expand=True)
        keys = [k for k, _ in COLUMNS]
        style = ttk.Style()
        style.configure('Treeview', font=('맑은 고딕', 9), rowheight=24)
        style.configure('Treeview.Heading', font=('맑은 고딕', 9, 'bold'))
        self.tree = ttk.Treeview(tv_frame, columns=keys, show='headings')
        for key, label in COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=COL_WIDTH.get(key, 60),
                             anchor='w' if key in ('NAME', 'HOLDER', 'REMARK') else 'center',
                             stretch=False)
        tys = tk.Scrollbar(tv_frame, orient='vertical', command=self.tree.yview)
        txs = tk.Scrollbar(tv_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=tys.set, xscrollcommand=txs.set)
        tys.pack(side='right', fill='y')
        txs.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda _event: self.edit_selected())
        self.tree.bind('<Delete>', lambda _event: self.delete_selected())

        hint = tk.Label(right, anchor='w', fg='#8a94a3', font=('맑은 고딕', 8),
                        text='행을 더블클릭하거나 수정/추가 버튼으로 직접 편집할 수 있습니다. (N번호 ~ M6 사이 괄호 주석을 읽음)')
        hint.pack(fill='x', pady=(4, 0))

    def set_window_icon(self):
        try:
            self.root.iconbitmap(default=resource_path('assets/nc_tool_list.ico'))
        except tk.TclError:
            pass

    def update_count(self):
        self.count.config(text='공구 %d개' % len(self.tree.get_children()))

    def update_metadata_summary(self):
        values = []
        for _column, label, key in PDF_METADATA_FIELDS:
            value = self.metadata.get(key) or '-'
            values.append('%s %s' % (label, value))
        self.metadata_summary.config(text='출력 정보: ' + ' | '.join(values))

    def next_tool_no(self):
        numbers = []
        for iid in self.tree.get_children():
            value = str(self.tree.item(iid, 'values')[0]).upper()
            match = re.fullmatch(r'T?(\d+)', value)
            if match:
                numbers.append(int(match.group(1)))
        return 'T%02d' % (max(numbers, default=0) + 1)

    def add_row(self):
        values = {key: '' for key, _ in COLUMNS}
        values['NO'] = self.next_tool_no()
        self.show_row_editor(values)

    def edit_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('알림', '수정할 행을 먼저 선택하세요.')
            return
        iid = selected[0]
        row = dict(zip((key for key, _ in COLUMNS), self.tree.item(iid, 'values')))
        self.show_row_editor(row, iid)

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('알림', '삭제할 행을 먼저 선택하세요.')
            return
        count = len(selected)
        if not messagebox.askyesno('행 삭제', '%d개 행을 삭제할까요?' % count):
            return
        for iid in selected:
            self.tree.delete(iid)
        self.update_count()

    def show_row_editor(self, values, iid=None):
        win = tk.Toplevel(self.root)
        win.title('공구 행 수정' if iid else '공구 행 추가')
        win.transient(self.root)
        win.grab_set()
        form = tk.Frame(win, padx=12, pady=12)
        form.pack(fill='both', expand=True)
        variables = {}
        for index, (key, label) in enumerate(COLUMNS):
            column, row = (index // 8) * 2, index % 8
            tk.Label(form, text=label, anchor='e', width=8).grid(row=row, column=column,
                                                                  padx=(0, 4), pady=3, sticky='e')
            var = tk.StringVar(value=str(values.get(key, '')))
            entry = tk.Entry(form, textvariable=var, width=22)
            entry.grid(row=row, column=column + 1, padx=(0, 14), pady=3, sticky='ew')
            variables[key] = var
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        def save():
            row = {key: variables[key].get().strip() for key, _ in COLUMNS}
            if not row['TYPE'] and row['NAME']:
                row['TYPE'] = derive_type(row['NAME'], self.name_types)
            if not row['D'] and row['NAME']:
                row['D'] = derive_d(row['NAME'])
            data = [row[key] for key, _ in COLUMNS]
            if iid:
                self.tree.item(iid, values=data)
                self.tree.selection_set(iid)
                self.tree.focus(iid)
            else:
                new_iid = self.tree.insert('', 'end', values=data)
                self.tree.selection_set(new_iid)
                self.tree.focus(new_iid)
            self.update_count()
            win.destroy()

        buttons = tk.Frame(win)
        buttons.pack(pady=(0, 12))
        tk.Button(buttons, text='저장', command=save, width=10).pack(side='left', padx=4)
        tk.Button(buttons, text='취소', command=win.destroy, width=10).pack(side='left', padx=4)
        win.bind('<Return>', lambda _event: save())
        win.bind('<Escape>', lambda _event: win.destroy())
        win.focus_set()
        win.geometry('760x300')
        win.resizable(False, False)
        self.root.wait_window(win)
    # ----- 동작 -----
    def maximize_window(self):
        """Maximize on Windows and retain the default size elsewhere."""
        try:
            self.root.state('zoomed')
        except tk.TclError:
            try:
                self.root.attributes('-zoomed', True)
            except tk.TclError:
                pass

    def run(self):
        source_text = self.src.get('1.0', 'end')
        self.metadata = parse_program_metadata(source_text)
        rows = parse_program(source_text, self.name_types)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for r in rows:
            self.tree.insert('', 'end', values=[r[k] for k, _ in COLUMNS])
        self.count.config(text='공구 %d개' % len(rows))
        self.update_metadata_summary()

    def open_file(self):
        path = filedialog.askopenfilename(
            title='NC 프로그램 파일 선택',
            filetypes=[('NC/텍스트 파일', '*.nc *.txt *.tap *.min *.prg'), ('모든 파일', '*.*')])
        if not path:
            return
        self.load_file(path)

    def load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fp:
                data = fp.read()
        except Exception as e:
            messagebox.showerror('열기 실패', str(e))
            return
        self.src.delete('1.0', 'end')
        self.src.insert('1.0', data)
        self.run()

    def drop_file(self, event):
        """Load the first file dropped into the input area."""
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return 'refuse_drop'
        if len(paths) > 1:
            messagebox.showinfo('File drop', 'Only the first dropped file will be loaded.')
        self.load_file(paths[0])
        return 'copy'

    def load_example(self):
        self.src.delete('1.0', 'end')
        self.src.insert('1.0', EXAMPLE)
        self.run()

    def clear(self):
        self.src.delete('1.0', 'end')
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.count.config(text='공구 0개')
        self.metadata = {key: '' for key in METADATA_ALIASES}
        self.metadata_summary.config(text='출력 정보: -')

    def show_type_list(self):
        win = tk.Toplevel(self.root)
        win.title('이름 → TYPE 경우의 수')
        win.geometry('500x460')
        win.transient(self.root)
        tk.Label(win, text='공구 이름 → TYPE 변환표', font=('맑은 고딕', 10, 'bold')).pack(pady=(10, 2))
        tk.Label(win, text='추가·수정한 내용은 다음 실행에도 유지됩니다.',
                 fg='#5a6577', font=('맑은 고딕', 8)).pack(pady=(0, 8))

        frame = tk.Frame(win)
        frame.pack(fill='both', expand=True, padx=10)
        tv = ttk.Treeview(frame, columns=('abbr', 'type'), show='headings', selectmode='browse')
        tv.heading('abbr', text='이름(약어·표현)')
        tv.heading('type', text='TYPE')
        tv.column('abbr', width=220, anchor='w')
        tv.column('type', width=220, anchor='w')
        sb = tk.Scrollbar(frame, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        tv.pack(side='left', fill='both', expand=True)

        def refresh():
            for item in tv.get_children():
                tv.delete(item)
            for index, (abbr, typ) in enumerate(self.name_types):
                tv.insert('', 'end', iid=str(index), values=(abbr, typ))

        def save_mappings():
            try:
                save_name_types(self.name_types)
            except OSError as error:
                messagebox.showerror('저장 실패', str(error), parent=win)
                return False
            return True

        def open_editor(index=None):
            current = self.name_types[index] if index is not None else ('', '')
            editor = tk.Toplevel(win)
            editor.title('이름 경우 수정' if index is not None else '이름 경우 추가')
            editor.transient(win)
            editor.grab_set()
            body = tk.Frame(editor, padx=14, pady=14)
            body.pack(fill='both', expand=True)
            tk.Label(body, text='이름(약어·표현)').grid(row=0, column=0, sticky='w', pady=(0, 4))
            name_var = tk.StringVar(value=current[0])
            name_entry = tk.Entry(body, textvariable=name_var, width=34)
            name_entry.grid(row=1, column=0, sticky='ew', pady=(0, 10))
            tk.Label(body, text='TYPE').grid(row=2, column=0, sticky='w', pady=(0, 4))
            type_var = tk.StringVar(value=current[1])
            type_entry = tk.Entry(body, textvariable=type_var, width=34)
            type_entry.grid(row=3, column=0, sticky='ew', pady=(0, 12))

            def commit():
                abbr, typ = name_var.get().strip(), type_var.get().strip()
                if not abbr or not typ:
                    messagebox.showwarning('입력 확인', '이름과 TYPE을 모두 입력하세요.', parent=editor)
                    return
                duplicate = next((i for i, pair in enumerate(self.name_types)
                                  if pair[0].upper() == abbr.upper() and i != index), None)
                if duplicate is not None:
                    messagebox.showwarning('중복 이름', '같은 이름 경우가 이미 있습니다.', parent=editor)
                    return
                if index is None:
                    self.name_types.append((abbr, typ))
                else:
                    self.name_types[index] = (abbr, typ)
                if save_mappings():
                    refresh()
                    editor.destroy()

            actions = tk.Frame(body)
            actions.grid(row=4, column=0)
            tk.Button(actions, text='저장', command=commit, width=9).pack(side='left', padx=3)
            tk.Button(actions, text='취소', command=editor.destroy, width=9).pack(side='left', padx=3)
            editor.bind('<Return>', lambda _event: commit())
            editor.bind('<Escape>', lambda _event: editor.destroy())
            name_entry.focus_set()

        def selected_index():
            selected = tv.selection()
            if not selected:
                messagebox.showinfo('알림', '수정하거나 삭제할 경우를 선택하세요.', parent=win)
                return None
            return int(selected[0])

        def edit_selected():
            index = selected_index()
            if index is not None:
                open_editor(index)

        def delete_selected():
            index = selected_index()
            if index is None:
                return
            if messagebox.askyesno('이름 경우 삭제', '선택한 이름 경우를 삭제할까요?', parent=win):
                del self.name_types[index]
                if save_mappings():
                    refresh()

        def restore_defaults():
            if messagebox.askyesno('기본값 복원', '기본 이름 경우의 수로 되돌릴까요?', parent=win):
                self.name_types = list(DEFAULT_NAME_TYPES)
                if save_mappings():
                    refresh()

        controls = tk.Frame(win)
        controls.pack(fill='x', padx=10, pady=10)
        tk.Button(controls, text='＋ 추가', command=open_editor).pack(side='left', padx=2)
        tk.Button(controls, text='수정', command=edit_selected).pack(side='left', padx=2)
        tk.Button(controls, text='삭제', command=delete_selected).pack(side='left', padx=2)
        tk.Button(controls, text='기본값 복원', command=restore_defaults).pack(side='left', padx=12)
        tk.Button(controls, text='닫기', command=win.destroy).pack(side='right', padx=2)
        tv.bind('<Double-1>', lambda _event: edit_selected())
        refresh()
    def export_pdf(self):
        rows = self.current_rows()
        if not rows:
            messagebox.showinfo('알림', '먼저 공구 리스트를 생성하세요.')
            return
        path = filedialog.asksaveasfilename(
            title='공구 리스트 PDF 저장', defaultextension='.pdf',
            initialfile=default_pdf_filename(self.metadata),
            filetypes=[('PDF 파일', '*.pdf')],
        )
        if path:
            self.save_pdf(path, rows)

    def save_pdf(self, path, rows):
        try:
            export_tool_list_pdf(path, rows, self.metadata)
        except Exception as error:
            messagebox.showerror('PDF 출력 실패', str(error))
            return
        messagebox.showinfo('PDF 출력 완료', 'PDF 파일을 저장했습니다.\n' + path)

    def current_rows(self):
        rows = []
        keys = [key for key, _label in COLUMNS]
        for iid in self.tree.get_children():
            rows.append(dict(zip(keys, self.tree.item(iid, 'values'))))
        return rows

    def copy_table(self):
        rows = self.tree.get_children()
        if not rows:
            messagebox.showinfo('알림', '먼저 공구 리스트를 생성하세요.')
            return
        lines = []
        if self.with_header.get():
            lines.append('\t'.join(label for _, label in COLUMNS))
        for iid in rows:
            vals = self.tree.item(iid, 'values')
            lines.append('\t'.join(str(v) for v in vals))
        # 줄 구분은 '\n' 만 사용 (tkinter가 Windows에서 CRLF로 변환 -> Excel 빈 행 방지)
        tsv = '\n'.join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(tsv)
        self.root.update()
        self.count.config(text='✅ 복사됨! 엑셀에서 Ctrl+V')
        self.root.after(1800, lambda: self.count.config(text='공구 %d개' % len(rows)))


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
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()
