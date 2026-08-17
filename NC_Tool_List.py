# -*- coding: utf-8 -*-
"""
NC 공구 리스트 생성기 (tkinter GUI)
- 왼쪽: NC 프로그램(G코드) 입력
- 오른쪽: N번호~M6 사이 괄호 주석을 읽어 만든 공구 리스트 (복사/보기용)
"""
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD

# ---------- 파싱 로직 ----------
TOOL_RE = re.compile(r'\(\s*T(\d+)\s*//\s*(.*?)\s*\[SO\s*([\d.]+)\]\s*//\s*T\d+\s*([^)]*?)\s*\)', re.I)
N_RE    = re.compile(r'^\s*N(\d+)\s*\(\s*#\d+\s*:\s*Tool\s*Change', re.I)
M6_RE   = re.compile(r'^\s*M0?6\s+T(\d+)', re.I)
# 키 뒤 숫자만 추출(값이 없으면 매칭 안 됨). 긴 키를 앞에 둬서 FL이 F로 잘못 잡히지 않게 함
KV_RE   = re.compile(r'\b(LCF|SPINDL|FEED|FL|GL|DC|RE|SIG|PL|F)\s+(-?\d+(?:\.\d+)?)', re.I)

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


def fmt_num(s):
    """'38.500000' -> '38.5', '10.000000' -> '10'"""
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except (ValueError, TypeError):
        return str(s).strip()


# 사용자용 표시 목록 (이름 약어 -> TYPE). "이름 경우의 수" 버튼에서 이 목록을 보여줌
NAME_TYPES = [
    ('F.EM',  'FLAT E/M'),
    ('R.EM',  'FILLET E/M'),
    ('B.EM',  'BALL E/M'),
    ('DR',    'DRILL'),
    ('F.MIL', 'FACE MILL'),
    ('CUT',   'CUTTER'),
    ('RM',    'REAMER'),
    ('C.D',   'CENTER'),
    ('T.CUT', 'T-CUTTER'),
    ('DY.EM', 'DYNAMIC E/M'),
    ('C.MIL', 'CHAMF MILL'),
]

# 매칭 순서 (긴/구체적인 약어를 앞에 둬서 잘못 잡히지 않게 함) + 풀네임 대비
_TYPE_MATCH = [
    ('DY.EM', 'DYNAMIC E/M'),
    ('F.MIL', 'FACE MILL'),
    ('C.MIL', 'CHAMF MILL'),
    ('T.CUT', 'T-CUTTER'),
    ('F.EM',  'FLAT E/M'),
    ('R.EM',  'FILLET E/M'),
    ('B.EM',  'BALL E/M'),
    ('C.D',   'CENTER'),
    ('DRILL', 'DRILL'),
    ('DR',    'DRILL'),
    ('REAMER', 'REAMER'),
    ('RM',    'REAMER'),
    ('CUTTER', 'CUTTER'),
    ('CUT',   'CUTTER'),
]


def derive_type(name):
    u = (name or '').upper()
    for abbr, typ in _TYPE_MATCH:
        if abbr in u:
            return typ
    return ''


def derive_d(name):
    m = re.search(r'D\s*([\d.]+)', name or '', re.I)
    return m.group(1) if m else ''


def parse_program(text):
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
            'TYPE': derive_type(f.get('NAME', '')),
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


# ---------- GUI ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title('🛠️ NC 공구 리스트 생성기')
        root.geometry('1180x640')
        root.after_idle(self.maximize_window)

        kfont = ('맑은 고딕', 10)
        mono = ('Consolas', 10)

        # 상단 바
        top = tk.Frame(root, bg='#1f3a5f')
        top.pack(fill='x')
        tk.Label(top, text='🛠️ NC 공구 리스트 생성기', bg='#1f3a5f', fg='white',
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
        self.with_header = tk.BooleanVar(value=False)
        tk.Checkbutton(rbar, text='머리글 포함', variable=self.with_header,
                       font=kfont).pack(side='right', padx=6)
        tk.Button(rbar, text='이름 경우의 수', command=self.show_type_list,
                  font=kfont).pack(side='right', padx=4)

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

        hint = tk.Label(right, anchor='w', fg='#8a94a3', font=('맑은 고딕', 8),
                        text='모든 칸은 프로그램에서 자동으로 채워집니다. (N번호 ~ M6 사이 괄호 주석을 읽음)')
        hint.pack(fill='x', pady=(4, 0))

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
        rows = parse_program(self.src.get('1.0', 'end'))
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for r in rows:
            self.tree.insert('', 'end', values=[r[k] for k, _ in COLUMNS])
        self.count.config(text='공구 %d개' % len(rows))

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

    def show_type_list(self):
        win = tk.Toplevel(self.root)
        win.title('이름 → TYPE 경우의 수')
        win.geometry('330x380')
        win.transient(self.root)
        tk.Label(win, text='공구 이름 약어 → TYPE 변환표',
                 font=('맑은 고딕', 10, 'bold')).pack(pady=8)
        frame = tk.Frame(win)
        frame.pack(fill='both', expand=True, padx=10, pady=(0, 6))
        tv = ttk.Treeview(frame, columns=('abbr', 'type'), show='headings')
        tv.heading('abbr', text='이름(약어)')
        tv.heading('type', text='TYPE')
        tv.column('abbr', width=110, anchor='center')
        tv.column('type', width=170, anchor='w')
        for abbr, typ in NAME_TYPES:
            tv.insert('', 'end', values=(abbr, typ))
        sb = tk.Scrollbar(frame, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        tv.pack(side='left', fill='both', expand=True)
        tk.Button(win, text='닫기', command=win.destroy,
                  font=('맑은 고딕', 10)).pack(pady=(0, 10))

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
