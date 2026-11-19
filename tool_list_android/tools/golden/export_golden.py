# -*- coding: utf-8 -*-
"""골든(정답) JSON 생성기 — WORK_PLAN.md P1 §1.1.

원본 데스크톱 앱(smhwang1984-lab/tool_list)의 Python 함수 결과를 그대로 JSON으로 남긴다.
TS 이식본(src/core)은 tests/golden.test.ts에서 이 JSON과 결과를 비교한다.

1) 함수 호출 기록: 원본 pytest를 '기록 모드'로 돌린다. 대상 함수를 감싸서
   (함수 이름, 인자, 결과)를 모은다 → tests/golden/calls/<함수>.json
2) 샘플 NC 전체 산출: tests/fixtures/*.nc 마다 밀링/선반 산출·메타데이터·코드 색·검색 결과
   → tests/golden/fixtures/<파일>.json
3) 기준 원본 커밋 → tests/golden/SOURCE_REV

실행 (Windows, 원본 빌드용 Python 환경):
    ..\\..\\nc_build_venv\\Scripts\\python.exe tools\\golden\\export_golden.py ..  (tool_list_android 폴더에서 실행, 원본 = 상위 폴더 tool_list)
원본 코드는 고치지 않는다. 원본 저장소에서 pytest만 돌린다.
"""
import functools
import hashlib
import inspect
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                     # tool_list_android
GOLDEN = ROOT / 'tests' / 'golden'
FIXTURES = ROOT / 'tests' / 'fixtures'

MAX_CALLS_PER_FUNC = 3000                     # 함수마다 남길 서로 다른 호출 수 상한
MAX_RECORD_BYTES = 100_000                    # 이보다 큰 호출(대용량 NC 전체 등)은 2)에서 다룬다
COLOR_LINES_PER_FIXTURE = 4000                # 코드 색 골든은 파일마다 앞쪽 N줄만

# 원본 pytest 중 대상 함수를 쓰는 파일
TEST_FILES = [
    'tests/test_nc_tool_list.py',
    'tests/test_lathe_insert_spec.py',
    'tests/test_so_comment.py',
    'tests/test_spindle_h_check.py',
    'tests/test_nc_highlight.py',
    'tests/test_edit_mode.py',
    'tests/test_v233_live_reload.py',
]

# NC_Tool_List.py 에서 기록할 함수 (WORK_PLAN P1 대응표)
NC_FUNCS = [
    # text / metadata / nameTypes
    'code_without_comments', 'fmt_num', 'normalize_metadata_key', 'parse_program_metadata',
    'program_header_text', 'clean_name_types', 'derive_type', 'derive_d', 'default_pdf_filename',
    # radiusComp
    '_subprogram_bodies', '_collect_radius_comp_codes', '_format_comp_suffix', '_format_remark',
    # alerts
    '_same_number', '_line_list_text', 'spindle_alert_text', 'h_number_alert_text', 'so_alert_text',
    # millParser
    'parse_program', 'tool_name_map_from_rows', 'tool_shape_map_from_rows',
    # latheParser
    '_lathe_collect_spindle_feed', '_lathe_numeric_value', '_lathe_value_range',
    '_strip_lathe_tool_prefix', 'parse_lathe_program', 'lathe_tool_name_map_from_rows',
    'is_lathe_machine',
    # ncColor / search
    'nc_color_line', 'find_next_regex_span', 'find_prev_regex_span', 'find_next_tool_change_span',
    'find_prev_tool_change_span', 'line_has_m00_stop', 'line_has_m01_stop',
    'line_has_program_stop', 'line_stops_playback', 'find_next_literal_span',
    # programText / password
    'compose_program_texts', 'append_nc_programs', 'program_text_digest',
    'decode_program_bytes', '_edit_password_hash',
]


class Unserializable(Exception):
    pass


def enc(value):
    """Python 값 → JSON 값. 표현할 수 없는 값(객체 등)은 Unserializable."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {'__float__': repr(value)}
    if isinstance(value, (bytes, bytearray)):
        return {'__bytes__': bytes(value).hex()}
    if isinstance(value, re.Pattern):
        return {'__re__': value.pattern, 'flags': int(value.flags)}
    if isinstance(value, (list, tuple)):
        return [enc(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((enc(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, dict):
        if not all(isinstance(k, (str, int)) for k in value):
            raise Unserializable(type(value))
        if all(isinstance(k, str) for k in value):
            data = {k: enc(v) for k, v in value.items()}
        else:  # 정수 키가 섞인 dict → 순서 있는 쌍 목록
            data = {'__pairs__': [[enc(k), enc(v)] for k, v in value.items()]}
        sources = getattr(value, 'sources', None)
        if isinstance(sources, dict):            # LatheRow
            return {'__lathe_row__': data, 'sources': enc(sources)}
        return data
    raise Unserializable(type(value))


class Recorder:
    def __init__(self):
        self.calls = {}      # 이름 -> [record]
        self.seen = {}       # 이름 -> set(key)
        self.skipped = {}    # 이름 -> 개수

    def _skip(self, name):
        self.skipped[name] = self.skipped.get(name, 0) + 1

    def wrap(self, module, name, label):
        original = getattr(module, name)
        if getattr(original, '__golden_wrapped__', False):
            return
        recorder = self

        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            try:
                enc_args = enc(list(args))
                enc_kwargs = enc(kwargs)
            except Unserializable:
                recorder._skip(label)
                return original(*args, **kwargs)
            try:
                result = original(*args, **kwargs)
            except Exception as error:  # 예외도 정답의 일부
                recorder.add(label, enc_args, enc_kwargs, {'raises': type(error).__name__})
                raise
            try:
                recorder.add(label, enc_args, enc_kwargs, {'result': enc(result)})
            except Unserializable:
                recorder._skip(label)
            return result

        wrapper.__golden_wrapped__ = True
        setattr(module, name, wrapper)

    def add(self, label, args, kwargs, outcome):
        record = {'args': args}
        if kwargs:
            record['kwargs'] = kwargs
        record.update(outcome)
        text = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if len(text.encode('utf-8')) > MAX_RECORD_BYTES:
            self._skip(label)
            return
        key = hashlib.sha1(json.dumps([args, kwargs], ensure_ascii=False, sort_keys=True)
                           .encode('utf-8')).hexdigest()
        seen = self.seen.setdefault(label, set())
        if key in seen:
            return
        bucket = self.calls.setdefault(label, [])
        if len(bucket) >= MAX_CALLS_PER_FUNC:
            return
        seen.add(key)
        bucket.append(record)

    # pytest 플러그인 훅: 테스트 수집 전에 감싼다(테스트는 app.func 로 부르므로 그때 감싼 함수를 본다).
    def pytest_configure(self, config):
        import NC_Tool_List
        import lathe_insert_spec
        for name in NC_FUNCS:
            self.wrap(NC_Tool_List, name, name)
        for name, obj in list(vars(lathe_insert_spec).items()):
            if (inspect.isfunction(obj) and obj.__module__ == 'lathe_insert_spec'
                    and name != '_cached_dict'):
                self.wrap(lathe_insert_spec, name, 'lis.' + name)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + '\n',
                    encoding='utf-8', newline='\n')


def export_fixtures(app):
    """샘플 NC 전체 산출 결과."""
    out_dir = GOLDEN / 'fixtures'
    for path in sorted(FIXTURES.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ('.nc', '.mpf', '.tap'):
            continue
        raw = path.read_bytes()
        text, encoding, newline, lossy = app.decode_program_bytes(raw)
        lines = text.splitlines()
        data = {
            'file': path.name,
            'decode': {'encoding': encoding, 'newline': newline, 'lossy': lossy,
                       'length': len(text), 'lines': len(lines),
                       'sha1': app.program_text_digest(text)},
            'metadata': app.parse_program_metadata(text),
            'header': app.program_header_text(text),
            'mill_rows': enc(app.parse_program(text)),
            'mill_rows_lathe_flag': enc(app.parse_program(text, lathe=True)),
            'lathe_rows': enc(app.parse_lathe_program(text)),
            'pdf_filename': app.default_pdf_filename(app.parse_program_metadata(text)),
        }
        data['mill_rows_custom_types'] = enc(app.parse_program(
            text, name_types=[('EM', 'END MILL'), ('DR', 'DRILL X')]))
        data['tool_name_map'] = app.tool_name_map_from_rows(app.parse_program(text))
        data['lathe_tool_name_map'] = app.lathe_tool_name_map_from_rows(app.parse_lathe_program(text))
        # 코드 색: 앞쪽 N줄, 밀링/선반
        for lathe in (False, True):
            state = 0
            spans = []
            for line in lines[:COLOR_LINES_PER_FIXTURE]:
                line_spans, state = app.nc_color_line(line, state, lathe=lathe)
                spans.append([[s, e, k] for s, e, k in line_spans] + [state])
            data['color_lathe' if lathe else 'color_mill'] = spans
        # 공구 교체 검색: 처음부터 끝까지 '다음'을 따라가며, '이전'은 각 지점에서 한 번
        for lathe in (False, True):
            chain = []
            pos = 0
            for _ in range(400):
                span = app.find_next_tool_change_span(text, pos, lathe=lathe)
                if span is None:
                    chain.append(None)
                    break
                prev = app.find_prev_tool_change_span(text, span[0], lathe=lathe)
                chain.append([list(span), list(prev) if prev else None])
                if span[2]:
                    break
                pos = span[1]
            data['tool_search_lathe' if lathe else 'tool_search_mill'] = chain
        # 정지 줄
        data['stop_m00'] = [i for i, line in enumerate(lines) if app.line_has_m00_stop(line)]
        data['stop_m01'] = [i for i, line in enumerate(lines) if app.line_has_m01_stop(line)]
        # 문자 검색
        literal = []
        for needle in ('G43', 'm30', 'T1', '(', 'SPINDL', 'x'):
            pos, chain = 0, []
            for _ in range(30):
                span = app.find_next_literal_span(text, needle, pos)
                chain.append(list(span) if span else None)
                if span is None or span[2]:
                    break
                pos = span[1]
            literal.append({'needle': needle, 'chain': chain})
        data['literal_search'] = literal
        write_json(out_dir / (path.name + '.json'), data)
        print('  fixture', path.name, 'mill', len(data['mill_rows']), 'lathe', len(data['lathe_rows']))


def extra_calls(app):
    """원본 테스트가 거의 부르지 않는 함수와 Python/JS 차이가 날 만한 경계값을 직접 불러 기록한다
    (감싼 함수를 부르므로 그대로 calls/ 에 남는다)."""
    def call(func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - 예외도 기록된다
            pass

    for items in (
        list(app.DEFAULT_NAME_TYPES),
        [['F.EM', 'FLAT'], ['f.em', 'DUP'], [' DR ', ' DRILL '], ['', 'X'], ['A', ''],
         {'name': 'B.EM', 'type': 'BALL'}, {'name': 'x'}, 'ab', 'abc', 3, None, ['only']],
        [{'name': '  C.D', 'type': 'CENTER'}, {'type': 'T'}, {'name': 1, 'type': 2}],
        'not a list', None, {'a': 1}, [],
    ):
        call(app.clean_name_types, items)
    for value in ('38.500000', '10.000000', '-0.000', '0.0001', '0.00001', '1e5', '1E-7',
                  '12345678901234567890', '1.5e300', ' 7 ', '+3', '.5', '5.', 'abc', '', '  x  ',
                  '1_000', 'inf', 'nan', '-inf', 'Infinity', '0x10', '١٢٣', '３', None, 3, 2.5,
                  -0.0, 1e16, 1e-7, 123456789.123456789, 0.1 + 0.2, True):
        call(app.fmt_num, value)
    for name in ('D10 F.EM', 'd 6.5 r.em', 'DY.EM D12', 'C.MIL', 'T.CUT D20', '', None,
                 'FACE MILL D80', 'CENTER DRILL', 'DRILL D3.3', 'ＤＲ', 'f.mil D50', 'D.5', 'D', 'DD12'):
        call(app.derive_type, name)
        call(app.derive_type, name, [('EM', 'END'), ('F.EM', 'FLAT'), ('D', 'DX')])
        call(app.derive_type, name, [])
        call(app.derive_d, name)
    for key in ('Part No.', 'part-no', 'RUN TIME', 'Run time', '프로그램', 'Op_10', 'ß', ''):
        call(app.normalize_metadata_key, key)
    for text in (
        '%\nO1234(TEST)\n(PART NO. : ABC-OP20)\n(DATE = 2026-01-01)\n',
        '%\n O0001\n(PROGRAM : K10M_OP10A)\n',
        '(program:   X  Y\n  Z )\n(Cycle Time: 1:00:00)\n(OPERATION NO : OP-30)\nO9999\n',
        '(PGM = OP 5 BODY)\n', '(PART=)\n(PART = P1)\n(PART = P2)\n', 'no comments', '', None,
        '(A:B:C)\n(=X)\n(:Y)\n(TOTAL TIME : 12 min)\n(CREATION DATE: 2026/11/10)\n',
        '%\nO12AB\nO3210 (  )\n', 'o5555 (lower)\n', '(PROGRAM : OPERATION7_PART)\n',
    ):
        call(app.parse_program_metadata, text)
        call(app.program_header_text, text)
    for meta in ({'part_no': 'A/B C', 'operation': 'OP10', 'program': 'O1'},
                 {'part_no': '', 'operation': '', 'program': ''}, {},
                 {'part_no': '..__', 'program': '부품 1'}, {'part_no': '  x  ', 'operation': None}):
        call(app.default_pdf_filename, meta)
    for line in ('G01 X1 (COMMENT) Y2', '(a)(b)c', '(unclosed', 'x)y(', '', None):
        call(app.code_without_comments, line)


def export_store_golden(app):
    """LatheSpecStore(직접 입력 저장소)와, 저장소를 넣은 resolve_fields 정답.
    저장소는 객체라 함수 호출 기록으로는 남지 않아 여기서 따로 만든다 → tests/golden/lathe_store.json"""
    import lathe_insert_spec as lis
    import tempfile

    pairs = []
    lathe_texts = {}
    for path in sorted(FIXTURES.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ('.nc', '.mpf', '.tap'):
            continue
        text = app.decode_program_bytes(path.read_bytes())[0]
        lathe_rows = app.parse_lathe_program(text)
        if lathe_rows:
            lathe_texts[path.name] = text
        for row in lathe_rows:
            pair = [str(row.get('INSERT', '')), str(row.get('HOLDER', ''))]
            if (pair[0] or pair[1]) and pair not in pairs:
                pairs.append(pair)
    pairs += [
        ['CNMG 120408', 'PCLNR 2525M12'], ['  cnmg 120408  [R 0.4]', 'pclnr 2525m12'],
        ['', 'MGEHR 2525-3'], ['', ''], ['16ER 1.5 ISO', 'SER 2525M16'],
        ['D10 X 90 NC DRILL', 'MILL TOOL CHECK'], ['GTN-3', 'MGEHR 2525-3'],
    ]

    def file_text(data):
        return json.dumps(data, ensure_ascii=False)

    # 사례 A: 실제 키로 만든 저장값(R/T/PITCH/D, KIND/DIR/TIP) + 일부러 비운 칸('-')
    data_a = {'version': 1, 'insert': {}, 'tool': {}}
    for i, (ins, hol) in enumerate(pairs[:30]):
        ikey = lis.LatheSpecStore.insert_key(ins, hol)
        tkey = lis.LatheSpecStore.tool_key(hol, ins)
        if ikey and i % 2 == 0:
            entry = {'R': '0.%d' % (i % 8 + 1)}
            if i % 3 == 0:
                entry['PITCH'] = '2'
            if i % 4 == 0:
                entry['D'] = '8'
            if i % 5 == 0:
                entry['T'] = '3.5'
            if i % 6 == 0:
                entry['R'] = '-'
            data_a['insert'][ikey] = entry
        if tkey != '||' and i % 3 != 1:
            data_a['tool'][tkey] = {'KIND': lis.KINDS[i % len(lis.KINDS)],
                                    'DIR': 'RLN'[i % 3], 'TIP': '12349'[i % 5]}
            if i % 7 == 0:
                data_a['tool'][tkey]['TIP'] = '-'
    raws = [
        file_text(data_a),
        '{}',
        'not json',
        '[]',
        file_text({'insert': [], 'tool': 'x'}),
        file_text({'insert': {'A': {'R': '  0.5  ', 'T': '', 'X': 'y', 'D': 3, 'PITCH': 1.5},
                              'B': 'str', 'C': {'R': '   '}},
                   'tool': {'A||B': {'KIND': ' 외경 ', 'DIR': None, 'TIP': True}}}),
    ]
    tag_variants = [{}, {'R': '0.4'}, {'PITCH': '1.25', 'D': '6'}, {'T': '2', 'R': '-'}]
    hint_variants = [None, {}, {'thread': True, 'pitch': '1.5'}, {'groove': True},
                     {'milling': True}, {'turning': True}, {'face_groove': True}]

    cases = []
    for raw in raws:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, 'lathe_insert_specs.json')
            with open(file_path, 'w', encoding='utf-8') as fp:
                fp.write(raw)
            store = lis.LatheSpecStore(file_path)
            queries, resolves = [], []
            for index, (ins, hol) in enumerate(pairs):
                queries.append({'insert_text': ins, 'holder_text': hol,
                                'insert_key': lis.LatheSpecStore.insert_key(ins, hol),
                                'tool_key': lis.LatheSpecStore.tool_key(hol, ins),
                                'get_insert': store.get_insert(ins, hol),
                                'get_tool': store.get_tool(hol, ins)})
                tags = tag_variants[index % len(tag_variants)]
                hints = hint_variants[index % len(hint_variants)]
                values, sources = lis.resolve_fields(ins, hol, tags, hints, store)
                resolves.append({'args': [ins, hol, tags, hints], 'values': values, 'sources': sources})
            # 저장소를 넣은 선반 공구 리스트 전체 산출 (샘플 NC 파일마다)
            parses = [{'file': name, 'rows': enc(app.parse_lathe_program(text, store))}
                      for name, text in lathe_texts.items()]
            cases.append({'raw': raw, 'insert': store.insert, 'tool': store.tool,
                          'queries': queries, 'resolves': resolves, 'parses': parses})

    # 갱신: 사례 A에서 시작해 연산을 차례로 적용한 뒤의 저장소
    ops_list = [
        [['update_insert', 'CNMG 120408', {'R': '0.8', 'T': ''}, ''],
         ['update_insert', '', {'PITCH': '1.5', 'R': '0.2'}, 'MGEHR 2525-3'],
         ['update_insert', '', {'R': '1'}, ''],
         ['update_tool', 'PCLNR 2525M12', 'CNMG 120408', {'KIND': '내경', 'DIR': 'L', 'TIP': ''}],
         ['update_tool', '', '', {'KIND': 'x'}],
         ['update_insert', 'cnmg 120408', {'R': None, 'D': 0, 'T': 3}, ''],
         ['update_insert', 'NEW [R 1]', {'R': ' 0.4 ', 'bogus': 'x'}, ''],
         ['update_tool', 'H', 'I', {'KIND': '-', 'TIP': '3'}]],
        [['update_insert', 'CNMG 120408', {'R': '', 'T': '', 'PITCH': '', 'D': ''}, '']],
    ]
    updates = []
    for ops in ops_list:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, 'lathe_insert_specs.json')
            with open(file_path, 'w', encoding='utf-8') as fp:
                fp.write(raws[0])
            store = lis.LatheSpecStore(file_path)
            for op in ops:
                if op[0] == 'update_insert':
                    store.update_insert(op[1], op[2], op[3])
                else:
                    store.update_tool(op[1], op[2], op[3])
            updates.append({'raw': raws[0], 'ops': ops, 'insert': store.insert, 'tool': store.tool})
    write_json(GOLDEN / 'lathe_store.json', {'pairs': pairs, 'cases': cases, 'updates': updates})
    print('  lathe_store', len(pairs), 'pairs,', len(cases), 'cases')


def export_program_text_golden(app):
    """인코딩 판별·저장·다이제스트·편집 비밀번호 정답 → tests/golden/program_text.json
    (PG ADD용 compose_program_texts / append_nc_programs 는 Android 버전에서 제외했으므로 만들지 않는다)"""
    import tempfile
    import unittest.mock as mock

    # --- 읽기: 바이트 -> (본문, 인코딩, 줄바꿈, 손실)
    samples = [
        b'', b'abc\n', b'abc\r\ndef\r\n', b'a\rb', b'a\r\nb\nc\r', b'\r\n', b'\n\n\n',
        b'\xef\xbb\xbfG0 X1\r\nM30\r\n', b'\xef\xbb\xbf', b'\xef\xbb\xbf\xef\xbb\xbfx',
        '(한글 주석)\nG0\n'.encode('utf-8'), '(한글 주석)\r\nG0\r\n'.encode('cp949'),
        '가나다라 한글'.encode('cp949'), '€ ® 한'.encode('cp949', errors='ignore'),
        b'\xa2\xe6\xa2\xe7', b'\xff\xfe', b'\x80', b'\xc3', b'\xc3\xa9', b'(\xc7\xd1\xb1\xdb)',
        b'\xed\xa0\x80', b'\xe2\x82', b'\xe2\x82\xac', b'\xef\xbb\xbf\xff', b'\xff\xff\xe2\x82abc',
        b'ab\x81', b'\x81\x40', b'\xfe\xfe', b'\xc8\xfe', b'\xa1', b'\x00\x01\x02',
        b'abc\xe2\x82\xe2\x82\xac\xff\xc3(\xc3\xa9', '%\nO1234 (한글)\n'.encode('cp949'),
    ]
    decode_cases = []
    for raw in samples:
        text, encoding, newline, lossy = app.decode_program_bytes(raw)
        decode_cases.append({'hex': raw.hex(), 'result': [text, encoding, newline, lossy]})

    # --- 저장: save_program_text 를 임시 파일에 실제로 실행해 나온 바이트
    texts = ['G0 X1\nG1 Y2\n', '(한글 주석)\nM30\n', '', '\n', 'é', '€', '😀', '한', 'ÿ', ' ', '①', '漢字',
             'Á', '﻿', 'x\ny\n\nz', '♥', 'ㅋㅋ', '　']
    encode_cases = []
    for text in texts:
        for encoding in ('utf-8', 'utf-8-sig', 'cp949'):
            for newline in ('\n', '\r\n'):
                with tempfile.TemporaryDirectory() as tmp:
                    path = os.path.join(tmp, 'x.nc')
                    case = {'text': text, 'encoding': encoding, 'newline': newline}
                    try:
                        app.save_program_text(path, text, encoding, newline)
                        case['hex'] = Path(path).read_bytes().hex()
                    except UnicodeEncodeError:
                        case['error'] = 'UnicodeEncodeError'
                        case['written'] = os.path.exists(path)
                    encode_cases.append(case)

    # --- 다이제스트
    digest_cases = [{'text': t, 'sha1': app.program_text_digest(t)}
                    for t in ('', 'a', 'G0 X1\n', '(한글)\n', '😀', 'x' * 5000)]

    # --- CP949 표: 모든 1바이트 + (0x81~0xFE) x (0x00~0xFF) 2바이트 조합의 디코딩 결과 해시
    import hashlib
    lines, mapped, injective, seen = [], 0, True, {}
    singles = [bytes([b]) for b in range(256)]
    pairs = [bytes([a, b]) for a in range(0x81, 0xFF) for b in range(256)]
    for raw in singles + pairs:
        try:
            ch = raw.decode('cp949')
            lines.append('%s:%s' % (raw.hex(), ch.encode('utf-8').hex()))
            if len(raw) == 2:
                mapped += 1
                if ch in seen:
                    injective = False
                seen[ch] = raw
        except UnicodeDecodeError:
            lines.append('%s:ERR' % raw.hex())
    cp949 = {'lines': len(lines), 'pairs_mapped': mapped, 'injective': injective,
             'sha1': hashlib.sha1('\n'.join(lines).encode('ascii')).hexdigest()}

    # --- 편집 비밀번호
    fixed_salt = bytes(range(1, 17))
    hash_cases = []
    for password, salt, iterations in (('1234', fixed_salt, 1000), ('', b'', 1), ('한글 비번', fixed_salt, 50),
                                       ('abc', b'NCToolList-edit-default', 1000), ('x' * 100, fixed_salt, 200000)):
        hash_cases.append({'password': password, 'salt': salt.hex(), 'iterations': iterations,
                           'hash': app._edit_password_hash(password, salt, iterations).hex()})

    def entry_for(password, salt=fixed_salt, iterations=2000):
        return {'algo': 'pbkdf2_sha256', 'iter': iterations, 'salt': salt.hex(),
                'hash': app._edit_password_hash(password, salt, iterations).hex()}

    good = entry_for('비번abc')
    setting_variants = [
        None, {}, 'not a dict', 5, [], good,
        dict(good, algo='md5'), dict(good, iter='2000'), dict(good, iter=2000.0), dict(good, iter=0),
        dict(good, iter=-5), dict(good, iter=None), dict(good, iter='x'), dict(good, iter=True),
        dict(good, salt='zz'), dict(good, salt='abc'), dict(good, salt=5), dict(good, hash='00'),
        dict(good, hash=good['hash'].upper()), dict(good, salt=' '.join(good['salt'][i:i + 2] for i in range(0, 32, 2))),
        {k: v for k, v in good.items() if k != 'hash'}, {k: v for k, v in good.items() if k != 'iter'},
        {'algo': 'pbkdf2_sha256'}, entry_for('1234'), entry_for('', b'', 1),
    ]
    verify_cases = []
    for settings in setting_variants:
        for password in ('1234', '비번abc', '', 'wrong', 'abc'):
            with mock.patch.object(app, 'load_app_settings',
                                   return_value={} if settings is None else {'edit_password': settings}):
                verify_cases.append({'entry': settings, 'password': password,
                                     'result': app.verify_edit_password(password)})
    create_cases = []
    for password in ('1234', '새 비밀번호', ''):
        saved = {}
        with mock.patch.object(app.os, 'urandom', return_value=fixed_salt), \
                mock.patch.object(app, 'load_app_settings', return_value={}), \
                mock.patch.object(app, 'save_app_settings', side_effect=lambda s: saved.update(s)):
            app.set_edit_password(password)
        create_cases.append({'password': password, 'salt': fixed_salt.hex(), 'entry': saved['edit_password']})

    write_json(GOLDEN / 'program_text.json', {
        'decode': decode_cases, 'encode': encode_cases, 'digest': digest_cases, 'cp949': cp949,
        'password': {'hash': hash_cases, 'verify': verify_cases, 'create': create_cases},
    })
    print('  program_text decode %d encode %d verify %d cp949 injective=%s' %
          (len(decode_cases), len(encode_cases), len(verify_cases), injective))


def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    if len(argv) < 2:
        print(__doc__)
        return 2
    source = Path(argv[1]).resolve()
    if not (source / 'NC_Tool_List.py').exists():
        print('원본 저장소 경로가 아닙니다:', source)
        return 2
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
    sys.path.insert(0, str(source))
    os.chdir(source)

    rev = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                           capture_output=True, text=True).stdout.strip()

    skip_pytest = '--skip-pytest' in argv   # 함수 호출 기록(calls/)은 그대로 두고 나머지만 다시 만든다
    code = 0
    if skip_pytest:
        import NC_Tool_List as app
    else:
        import pytest
        recorder = Recorder()
        code = pytest.main(TEST_FILES + ['-q', '-p', 'no:cacheprovider', '-x' if '--stop' in argv else '-q'],
                           plugins=[recorder])
        print('pytest 종료 코드:', code)
        import NC_Tool_List as app
        extra_calls(app)

        calls_dir = GOLDEN / 'calls'
        if calls_dir.exists():
            for old in calls_dir.glob('*.json'):
                old.unlink()
        total = 0
        for label in sorted(recorder.calls):
            records = recorder.calls[label]
            total += len(records)
            write_json(calls_dir / (label + '.json'), {'func': label, 'calls': records})
        print('기록한 함수 %d개, 호출 %d건' % (len(recorder.calls), total))
        missing = [n for n in NC_FUNCS if n not in recorder.calls]
        if missing:
            print('호출 기록이 없는 함수:', ', '.join(missing))
        if recorder.skipped:
            print('건너뛴 호출(직렬화 불가·대용량):',
                  ', '.join('%s %d' % kv for kv in sorted(recorder.skipped.items())))

    export_store_golden(app)
    export_program_text_golden(app)
    export_fixtures(app)

    (GOLDEN / 'SOURCE_REV').write_text(
        '%s%s\n' % (rev, ' (+ 커밋 안 된 변경 있음)' if dirty else ''), encoding='utf-8')
    print('SOURCE_REV', rev)
    if code != 0:
        # 원본 테스트 일부가 이 PC 설정(저장된 장비 선택 등) 때문에 실패해도 기록 자체는 유효하다.
        print('[주의] 원본 pytest 일부 실패(위 목록). 기록한 골든은 그대로 쓴다.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
